from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.initialize_foundation import synchronous_database_url

RISK_DATA_SCHEMA_VERSION = "corridor-risk-v1"


@dataclass(frozen=True)
class RiskRefreshReport:
    version: str
    input_corridor_count: int
    input_accident_count: int
    attributed_accident_count: int
    attribution_counts_by_confidence: dict[str, int]
    output_corridor_count: int
    included_year_start: int
    included_year_end: int
    reference_risk_p95: float
    refresh_duration_ms: float
    storage_bytes: int


def _weighted_percentile_95(rows: list[dict[str, Any]]) -> float:
    positive = [
        (row["raw_accident_count"] / (row["corridor_length_m"] / 1000.0), row["corridor_length_m"])
        for row in rows
        if row["raw_accident_count"] > 0
    ]
    if not positive:
        raise RuntimeError("risk version has no corridor with an attributed accident")

    positive.sort(key=lambda item: item[0])
    target_weight = sum(length for _, length in positive) * 0.95
    cumulative_weight = 0.0
    reference = positive[-1][0]
    for density, length in positive:
        cumulative_weight += length
        if cumulative_weight >= target_weight:
            reference = density
            break
    if not math.isfinite(reference) or reference <= 0:
        raise RuntimeError("reference_risk_p95 must be finite and greater than zero")
    return reference


def _existing_active_report(
    connection: psycopg.Connection[dict[str, Any]], version: str
) -> RiskRefreshReport | None:
    row = connection.execute(
        """
        SELECT v.*
        FROM app.risk_data_versions v
        JOIN app.active_risk_data_version a ON a.version = v.version
        WHERE v.version = %s
        """,
        (version,),
    ).fetchone()
    if row is None:
        return None
    if row["schema_version"] != RISK_DATA_SCHEMA_VERSION or row["validation_status"] != "valid":
        raise RuntimeError(f"active risk data version {version!r} is invalid or incompatible")
    snapshot = connection.execute(
        """
        SELECT
            count(*) AS row_count,
            count(*) FILTER (
                WHERE ST_SRID(geometry) <> 2039 OR NOT ST_IsValid(geometry)
                   OR ST_IsEmpty(geometry)
            ) AS invalid_geometry_count
        FROM app.corridor_risk_statistics
        WHERE risk_data_version = %s
        """,
        (version,),
    ).fetchone()
    if (
        snapshot["row_count"] != row["output_corridor_count"]
        or snapshot["invalid_geometry_count"] != 0
    ):
        raise RuntimeError(f"active risk data version {version!r} failed validation")
    return RiskRefreshReport(
        version=row["version"],
        input_corridor_count=row["input_corridor_count"],
        input_accident_count=row["input_accident_count"],
        attributed_accident_count=row["attributed_accident_count"],
        attribution_counts_by_confidence=row["attribution_counts_by_confidence"],
        output_corridor_count=row["output_corridor_count"],
        included_year_start=row["included_year_start"],
        included_year_end=row["included_year_end"],
        reference_risk_p95=row["reference_risk_p95"],
        refresh_duration_ms=row["refresh_duration_ms"],
        storage_bytes=row["storage_bytes"],
    )


def refresh_risk_data(database_url: str, version: str) -> RiskRefreshReport:
    version = version.strip()
    if not version or len(version) > 100:
        raise ValueError("RISK_DATA_VERSION must contain 1-100 characters")

    started_at = time.perf_counter()
    with psycopg.connect(synchronous_database_url(database_url), row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('app.risk-data-refresh'))")
            existing = _existing_active_report(connection, version)
            if existing is not None:
                return existing
            if connection.execute(
                "SELECT 1 FROM app.risk_data_versions WHERE version = %s", (version,)
            ).fetchone():
                raise RuntimeError(f"risk data version {version!r} already exists and is immutable")

            foundation = connection.execute(
                """
                SELECT version, source_checksum, source_kind, row_counts
                FROM app.foundation_data_versions
                ORDER BY initialized_at DESC
                LIMIT 1
                """
            ).fetchone()
            if foundation is None:
                raise RuntimeError("foundation data is not initialized")

            source = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM canonical_network.canonical_corridors) AS corridor_count,
                    count(*) AS accident_count,
                    count(*) FILTER (WHERE corridor_id IS NOT NULL) AS attributed_count,
                    min(accident_year) AS year_start,
                    max(accident_year) AS year_end,
                    array_agg(DISTINCT attribution_version ORDER BY attribution_version)
                        AS attribution_versions
                FROM accident_attribution.accident_attributions
                """
            ).fetchone()
            if source["corridor_count"] <= 0 or source["accident_count"] <= 0:
                raise RuntimeError("risk refresh requires non-empty corridor and accident inputs")
            if source["year_start"] is None or source["year_end"] is None:
                raise RuntimeError("risk refresh requires an accident year range")

            confidence_rows = connection.execute(
                """
                SELECT confidence_tier, count(*) AS accident_count
                FROM accident_attribution.accident_attributions
                WHERE corridor_id IS NOT NULL
                GROUP BY confidence_tier
                ORDER BY confidence_tier
                """
            ).fetchall()
            confidence_counts = {
                row["confidence_tier"]: row["accident_count"] for row in confidence_rows
            }
            if None in confidence_counts:
                raise RuntimeError("attributed accidents must have a confidence tier")
            if sum(confidence_counts.values()) != source["attributed_count"]:
                raise RuntimeError("confidence-tier counts do not match attributed accidents")
            source_metadata = {
                "foundation_data_version": foundation["version"],
                "foundation_source_checksum": foundation["source_checksum"],
                "foundation_source_kind": foundation["source_kind"],
                "attribution_versions": source["attribution_versions"],
            }

            # The metadata row is inserted first so its FK can own the immutable corridor snapshot.
            # Final calculated fields are updated only after validation, before activation.
            connection.execute(
                """
                INSERT INTO app.risk_data_versions (
                    version, schema_version, foundation_data_version, source_metadata,
                    included_year_start, included_year_end, input_corridor_count,
                    input_accident_count, attributed_accident_count,
                    attribution_counts_by_confidence, output_corridor_count,
                    reference_risk_p95, validation_status, refresh_duration_ms, storage_bytes
                ) VALUES (
                    %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, 1, 'invalid', 0, 0
                )
                """,
                (
                    version, RISK_DATA_SCHEMA_VERSION, foundation["version"],
                    json.dumps(source_metadata, sort_keys=True), source["year_start"],
                    source["year_end"], source["corridor_count"], source["accident_count"],
                    source["attributed_count"], json.dumps(confidence_counts, sort_keys=True),
                    source["corridor_count"],
                ),
            )
            connection.execute(
                """
                INSERT INTO app.corridor_risk_statistics (
                    risk_data_version, corridor_id, corridor_family, road_id,
                    primary_ref, primary_name, geometry, corridor_length_m,
                    raw_accident_count
                )
                SELECT
                    %s, c.corridor_id, c.corridor_family, c.road_id,
                    c.primary_ref, c.primary_name, c.geometry, c.length_m,
                    count(a.accident_id)
                FROM canonical_network.canonical_corridors c
                LEFT JOIN accident_attribution.accident_attributions a
                    ON a.corridor_id = c.corridor_id
                GROUP BY c.corridor_id, c.corridor_family, c.road_id,
                    c.primary_ref, c.primary_name, c.geometry, c.length_m
                """,
                (version,),
            )
            rows = connection.execute(
                """
                SELECT corridor_length_m, raw_accident_count
                FROM app.corridor_risk_statistics
                WHERE risk_data_version = %s
                """,
                (version,),
            ).fetchall()
            output_count = len(rows)
            counted_accidents = sum(row["raw_accident_count"] for row in rows)
            if output_count != source["corridor_count"]:
                raise RuntimeError("risk output corridor count does not match input")
            if counted_accidents != source["attributed_count"]:
                raise RuntimeError(
                    "some attributed accidents reference a missing canonical corridor"
                )
            invalid_geometry_count = connection.execute(
                """
                SELECT count(*)
                FROM app.corridor_risk_statistics
                WHERE risk_data_version = %s
                  AND (ST_SRID(geometry) <> 2039 OR NOT ST_IsValid(geometry)
                       OR ST_IsEmpty(geometry))
                """,
                (version,),
            ).fetchone()["count"]
            if invalid_geometry_count:
                raise RuntimeError("risk output contains invalid EPSG:2039 geometry")

            reference = _weighted_percentile_95(rows)
            duration_ms = (time.perf_counter() - started_at) * 1000.0
            storage_bytes = connection.execute(
                """
                SELECT COALESCE(sum(pg_column_size(s)), 0) AS bytes
                FROM app.corridor_risk_statistics s
                WHERE risk_data_version = %s
                """,
                (version,),
            ).fetchone()["bytes"]
            connection.execute(
                """
                UPDATE app.risk_data_versions
                SET output_corridor_count = %s,
                    reference_risk_p95 = %s,
                    validation_status = 'valid',
                    refresh_duration_ms = %s,
                    storage_bytes = %s,
                    activated_at = now()
                WHERE version = %s
                """,
                (output_count, reference, duration_ms, storage_bytes, version),
            )
            connection.execute(
                """
                INSERT INTO app.active_risk_data_version (singleton, version)
                VALUES (TRUE, %s)
                ON CONFLICT (singleton) DO UPDATE SET version = EXCLUDED.version
                """,
                (version,),
            )

    return RiskRefreshReport(
        version=version,
        input_corridor_count=source["corridor_count"],
        input_accident_count=source["accident_count"],
        attributed_accident_count=source["attributed_count"],
        attribution_counts_by_confidence=confidence_counts,
        output_corridor_count=output_count,
        included_year_start=source["year_start"],
        included_year_end=source["year_end"],
        reference_risk_p95=reference,
        refresh_duration_ms=duration_ms,
        storage_bytes=storage_bytes,
    )


def main() -> None:
    report = refresh_risk_data(os.environ["DATABASE_URL"], os.environ["RISK_DATA_VERSION"])
    print(json.dumps(asdict(report), sort_keys=True))


if __name__ == "__main__":
    main()
