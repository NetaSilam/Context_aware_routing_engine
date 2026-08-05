from __future__ import annotations

import json
import os
import subprocess

import httpx
import psycopg
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_RISK_DATA_INTEGRATION") != "true",
        reason="requires the disposable Compose PostGIS stack",
    ),
]

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
API_URL = os.environ.get("RISK_TEST_API_URL", "http://api:8000")

RISK_FIXTURE_SQL = """
TRUNCATE accident_attribution.accident_attributions;
TRUNCATE canonical_network.canonical_corridors CASCADE;

INSERT INTO canonical_network.canonical_corridors (
    corridor_id, corridor_family, road_id, primary_ref, primary_name, length_m,
    atom_count, build_basis, split_from_reason, geometry
) VALUES
    ('risk-short', 'named_road', 'road-1', '1', 'Short', 1000, 1, 'fixture',
     'not_split', ST_GeomFromText('LINESTRING(100000 600000, 101000 600000)', 2039)),
    ('risk-long', 'named_road', 'road-2', '2', 'Long', 18000, 1, 'fixture',
     'not_split', ST_GeomFromText('LINESTRING(100000 601000, 118000 601000)', 2039)),
    ('risk-high', 'named_road', 'road-3', '3', 'High', 1000, 1, 'fixture',
     'not_split', ST_GeomFromText('LINESTRING(100000 602000, 101000 602000)', 2039));

INSERT INTO accident_attribution.accident_attributions (
    accident_id, accident_year, severity, road_number, locality_code,
    geographic_domain, corridor_id, corridor_family, road_id,
    corridor_primary_ref, corridor_primary_name, attribution_status,
    confidence_tier, assignment_method, unresolved_reason,
    confidence_reason_code, review_needed, distance_to_corridor_m,
    second_best_distance_m, official_reference_effect, diagnostics_json,
    attribution_version, geometry
) VALUES
    ('high-confidence', 2020, 1, '1', 1, 1, 'risk-short', 'named_road', 'road-1',
     '1', 'Short', 'assigned', 'high', 'fixture', NULL, 'fixture', FALSE, 0, NULL,
     'none', '{}', 'attribution-fixture-v2', ST_SetSRID(ST_MakePoint(34.8, 32.0), 4326)),
    ('low-confidence', 2024, 99, '1', 1, 1, 'risk-short', 'named_road', 'road-1',
     '1', 'Short', 'assigned_with_warnings', 'low', 'fixture', NULL, 'fixture', TRUE,
     1, NULL, 'none', '{}', 'attribution-fixture-v2',
     ST_SetSRID(ST_MakePoint(34.8, 32.0), 4326)),
    ('medium-confidence', 2022, 3, '2', 1, 1, 'risk-long', 'named_road', 'road-2',
     '2', 'Long', 'assigned', 'medium', 'fixture', NULL, 'fixture', FALSE, 0, NULL,
     'none', '{}', 'attribution-fixture-v2', ST_SetSRID(ST_MakePoint(34.8, 32.0), 4326)),
    ('unassigned-old-year', 2018, 1, NULL, 1, 1, NULL, NULL, NULL, NULL, NULL,
     'unassigned', 'none', 'fixture', 'no_corridor', 'fixture', TRUE, NULL, NULL,
     'none', '{}', 'attribution-fixture-v2', ST_SetSRID(ST_MakePoint(34.8, 32.0), 4326));

INSERT INTO accident_attribution.accident_attributions (
    accident_id, accident_year, severity, road_number, locality_code,
    geographic_domain, corridor_id, corridor_family, road_id,
    corridor_primary_ref, corridor_primary_name, attribution_status,
    confidence_tier, assignment_method, unresolved_reason,
    confidence_reason_code, review_needed, distance_to_corridor_m,
    second_best_distance_m, official_reference_effect, diagnostics_json,
    attribution_version, geometry
)
SELECT
    'high-density-' || number, 2023, 1, '3', 1, 1, 'risk-high', 'named_road',
    'road-3', '3', 'High', 'assigned', 'high', 'fixture', NULL, 'fixture', FALSE,
    0, NULL, 'none', '{}', 'attribution-fixture-v2',
    ST_SetSRID(ST_MakePoint(34.8, 32.0), 4326)
FROM generate_series(1, 10) AS number;
"""


def run_refresh(version: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", "-m", "app.refresh_risk_data"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "RISK_DATA_VERSION": version},
    )


def test_versioned_risk_refresh_aggregation_validation_and_atomic_activation() -> None:
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(RISK_FIXTURE_SQL)
        connection.commit()

    refresh = run_refresh("integration-risk-v2")
    assert refresh.returncode == 0, refresh.stderr
    report = json.loads(refresh.stdout)
    assert report["input_corridor_count"] == 3
    assert report["input_accident_count"] == 14
    assert report["attributed_accident_count"] == 13
    assert report["attribution_counts_by_confidence"] == {
        "high": 11,
        "low": 1,
        "medium": 1,
    }
    assert report["output_corridor_count"] == 3
    assert report["included_year_start"] == 2018
    assert report["included_year_end"] == 2024
    assert report["reference_risk_p95"] == pytest.approx(2.0)
    assert report["refresh_duration_ms"] > 0
    assert report["storage_bytes"] > 0

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        version = connection.execute(
            """
            SELECT v.version, v.schema_version, v.source_metadata,
                   v.reference_risk_p95, v.validation_status
            FROM app.risk_data_versions v
            JOIN app.active_risk_data_version a ON a.version = v.version
            """
        ).fetchone()
        corridors = connection.execute(
            """
            SELECT corridor_id, raw_accident_count, corridor_length_m,
                   ST_SRID(geometry), ST_IsValid(geometry)
            FROM app.corridor_risk_statistics
            WHERE risk_data_version = 'integration-risk-v2'
            ORDER BY corridor_id
            """
        ).fetchall()
        spatial_index = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'app'
              AND indexname = 'corridor_risk_statistics_geometry_gist'
            """
        ).fetchone()[0]

    assert version[0] == "integration-risk-v2"
    assert version[1] == "corridor-risk-v1"
    assert version[2]["attribution_versions"] == ["attribution-fixture-v2"]
    assert version[3] == pytest.approx(2.0)
    assert version[4] == "valid"
    # Severity 99 counts once, exactly like every other attributed accident.
    assert corridors == [
        ("risk-high", 10, 1000.0, 2039, True),
        ("risk-long", 1, 18000.0, 2039, True),
        ("risk-short", 2, 1000.0, 2039, True),
    ]
    assert "USING gist (geometry)" in spatial_index

    ready = httpx.get(f"{API_URL}/health/ready", timeout=5)
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"]["risk_data_version"] == "integration-risk-v2"

    # A missing-corridor attribution makes the new version invalid. The failed transaction
    # leaves both the prior active pointer and its immutable rows unchanged.
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(
            """
            UPDATE accident_attribution.accident_attributions
            SET corridor_id = 'missing-corridor'
            WHERE accident_id = 'medium-confidence'
            """
        )
        connection.commit()
    failed_refresh = run_refresh("integration-risk-invalid")
    assert failed_refresh.returncode != 0
    assert "missing canonical corridor" in failed_refresh.stderr

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        active = connection.execute(
            "SELECT version FROM app.active_risk_data_version"
        ).fetchone()[0]
        rejected = connection.execute(
            "SELECT count(*) FROM app.risk_data_versions WHERE version = 'integration-risk-invalid'"
        ).fetchone()[0]
    assert active == "integration-risk-v2"
    assert rejected == 0

    # Readiness distinguishes incompatible, invalid, and missing active data.
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(
            "UPDATE app.risk_data_versions SET schema_version = 'future-v9' "
            "WHERE version = 'integration-risk-v2'"
        )
        connection.commit()
    incompatible = httpx.get(f"{API_URL}/health/ready", timeout=5)
    assert incompatible.status_code == 503
    assert "incompatible" in incompatible.json()["checks"]["database"]["reason"]

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(
            "UPDATE app.risk_data_versions SET schema_version = 'corridor-risk-v1', "
            "validation_status = 'invalid' WHERE version = 'integration-risk-v2'"
        )
        connection.commit()
    invalid = httpx.get(f"{API_URL}/health/ready", timeout=5)
    assert invalid.status_code == 503
    assert invalid.json()["checks"]["database"]["reason"] == "active risk data is invalid"

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(
            "UPDATE app.risk_data_versions SET validation_status = 'valid' "
            "WHERE version = 'integration-risk-v2'"
        )
        connection.execute("DELETE FROM app.active_risk_data_version")
        connection.commit()
    missing = httpx.get(f"{API_URL}/health/ready", timeout=5)
    assert missing.status_code == 503
    assert missing.json()["checks"]["database"]["reason"] == "active risk data is missing"

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(
            "INSERT INTO app.active_risk_data_version (singleton, version) "
            "VALUES (TRUE, 'integration-risk-v2')"
        )
        connection.commit()
