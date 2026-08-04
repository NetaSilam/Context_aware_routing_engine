from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.load_real_foundation import load_real_foundation, source_manifest_checksum

REQUIRED_TABLES = (
    ("canonical_network", "canonical_corridors"),
    ("canonical_network", "official_segment_links"),
    ("accident_attribution", "accident_attributions"),
    ("accident_attribution", "accident_attribution_summary"),
)

REQUIRED_COLUMNS = {
    "canonical_network.canonical_corridors": {
        "corridor_id", "corridor_family", "road_id", "primary_ref", "primary_name",
        "length_m", "atom_count", "build_basis", "split_from_reason", "geometry",
    },
    "canonical_network.official_segment_links": {
        "official_segment_id", "segment_key", "road_number", "target_object_type",
        "target_object_id", "link_method", "link_strength", "source_match_confidence",
        "distance_m", "is_multi_target",
    },
    "accident_attribution.accident_attributions": {
        "accident_id", "accident_year", "severity", "road_number", "locality_code",
        "geographic_domain", "corridor_id", "corridor_family", "road_id",
        "corridor_primary_ref", "corridor_primary_name", "attribution_status",
        "confidence_tier", "assignment_method", "unresolved_reason",
        "confidence_reason_code", "review_needed", "distance_to_corridor_m",
        "second_best_distance_m", "official_reference_effect", "diagnostics_json",
        "attribution_version", "geometry",
    },
    "accident_attribution.accident_attribution_summary": {
        "attribution_version", "total_accident_count", "review_needed_count",
        "status_breakdown", "confidence_breakdown", "unresolved_reason_breakdown",
        "official_reference_effect_breakdown", "assigned_rate",
        "assigned_with_warnings_rate", "unresolved_rate",
    },
}


def synchronous_database_url(value: str) -> str:
    url = make_url(value)
    if url.drivername not in {"postgresql+psycopg", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use postgresql+psycopg or postgresql+asyncpg")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_foundation(connection: psycopg.Connection[object]) -> dict[str, int]:
    row_counts: dict[str, int] = {}
    for schema_name, table_name in REQUIRED_TABLES:
        relation = f"{schema_name}.{table_name}"
        exists = connection.execute(
            "SELECT to_regclass(%s) IS NOT NULL", (relation,)
        ).fetchone()[0]
        if not exists:
            raise RuntimeError(f"required foundation table is missing: {relation}")
        columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema_name, table_name),
            ).fetchall()
        }
        missing_columns = REQUIRED_COLUMNS[relation] - columns
        if missing_columns:
            raise RuntimeError(
                f"required foundation table {relation} is partial; "
                f"missing columns: {sorted(missing_columns)}"
            )
        count = connection.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)
            )
        ).fetchone()[0]
        if count <= 0:
            raise RuntimeError(f"required foundation table is empty: {relation}")
        row_counts[relation] = count
    return row_counts


def initialize() -> None:
    database_url = synchronous_database_url(os.environ["DATABASE_URL"])
    version = os.environ["FOUNDATION_DATA_VERSION"].strip()
    mode = os.environ.get("FOUNDATION_DATA_MODE", "verify").strip()
    if not version:
        raise ValueError("FOUNDATION_DATA_VERSION must not be empty")
    if mode not in {"fixture", "real", "verify"}:
        raise ValueError("FOUNDATION_DATA_MODE must be fixture, real, or verify")

    fixture_path: Path | None = None
    if mode == "fixture":
        fixture_path = Path(
            os.environ.get(
                "FOUNDATION_FIXTURE_PATH", "/app/tests/fixtures/foundation_fixture.sql"
            )
        )
        if not fixture_path.is_file():
            raise FileNotFoundError(f"foundation fixture does not exist: {fixture_path}")
        checksum = file_checksum(fixture_path)
    elif mode == "real":
        data_path = Path(os.environ.get("FOUNDATION_DATA_PATH", "/data"))
        checksum = source_manifest_checksum(data_path)
        expected_checksum = os.environ.get("FOUNDATION_DATA_CHECKSUM", "").strip()
        if expected_checksum:
            if not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
                raise ValueError(
                    "FOUNDATION_DATA_CHECKSUM must be a lowercase SHA-256 checksum"
                )
            if expected_checksum != checksum:
                raise RuntimeError(
                    "real foundation source checksum does not match "
                    f"FOUNDATION_DATA_CHECKSUM: expected={expected_checksum}, actual={checksum}"
                )
        load_real_foundation(database_url, data_path)
    else:
        checksum = os.environ.get("FOUNDATION_DATA_CHECKSUM", "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError(
                "FOUNDATION_DATA_CHECKSUM must be a lowercase SHA-256 checksum in verify mode"
            )

    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            existing_rows = connection.execute(
                """
                SELECT version, source_checksum, source_kind, row_counts
                FROM app.foundation_data_versions
                FOR UPDATE
                """
            ).fetchall()
            if existing_rows:
                existing = existing_rows[0]
                if len(existing_rows) != 1 or existing[0] != version:
                    raise RuntimeError(
                        f"stale foundation version: requested {version!r}, "
                        f"found {[row[0] for row in existing_rows]!r}"
                    )
                if existing[1] != checksum or existing[2] != mode:
                    raise RuntimeError("foundation source checksum or kind does not match")
                actual_counts = validate_foundation(connection)
                recorded_counts = existing[3]
                if actual_counts != recorded_counts:
                    raise RuntimeError(
                        "foundation data is partial or changed: "
                        f"recorded={recorded_counts}, actual={actual_counts}"
                    )
                print(f"Foundation data {version} already initialized and verified")
                return

            if fixture_path is not None:
                connection.execute(fixture_path.read_text(encoding="utf-8"))

            row_counts = validate_foundation(connection)
            connection.execute(
                """
                INSERT INTO app.foundation_data_versions
                    (version, source_checksum, source_kind, row_counts)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (version, checksum, mode, json.dumps(row_counts, sort_keys=True)),
            )
            print(
                f"Initialized foundation data {version} ({mode}, {checksum}) "
                f"with {row_counts}"
            )


if __name__ == "__main__":
    initialize()
