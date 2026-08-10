from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import psycopg
import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_FOUNDATION_INTEGRATION") != "true",
        reason="requires the disposable Compose foundation stack",
    ),
]

API_URL = os.environ.get("FOUNDATION_TEST_API_URL", "http://api:8000")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
REDIS_URL = os.environ.get("REDIS_URL", "")
FIXTURE_PATH = Path("/app/tests/fixtures/foundation_fixture.sql")
ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _latest_migration_id() -> str:
    # Derived from the committed migration files rather than hardcoded, so this test
    # does not silently go stale (and start failing in CI) every time a migration is added.
    revision_ids = sorted(
        path.stem.split("_", 1)[0] for path in ALEMBIC_VERSIONS_DIR.glob("*_*.py")
    )
    return revision_ids[-1]


@pytest.fixture(autouse=True)
def clear_foundation_auth_limits() -> None:
    client = redis.Redis.from_url(REDIS_URL)
    for key in client.scan_iter("auth-rate:*"):
        client.delete(key)


def run_initializer(**environment_changes: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, **environment_changes}
    return subprocess.run(
        ["python", "-m", "app.initialize_foundation"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_clean_stack_is_migrated_initialized_and_ready() -> None:
    live_response = httpx.get(f"{API_URL}/health/live", timeout=5)
    ready_response = httpx.get(f"{API_URL}/health/ready", timeout=5)

    assert live_response.status_code == 200
    assert ready_response.status_code == 200
    assert ready_response.json()["checks"]["database"]["postgis_version"]
    assert ready_response.json()["checks"]["redis"] == {"status": "ready"}

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        migration = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        foundation = connection.execute(
            """
            SELECT version, source_checksum, source_kind, row_counts
            FROM app.foundation_data_versions
            """
        ).fetchone()
        postgis_version = connection.execute("SELECT PostGIS_Version()").fetchone()[0]

    assert migration == _latest_migration_id()
    assert foundation[0] == "test-fixture-v1"
    assert len(foundation[1]) == 64
    assert foundation[2] == "fixture"
    assert foundation[3] == {
        "canonical_network.canonical_corridors": 1,
        "canonical_network.official_segment_links": 1,
        "accident_attribution.accident_attributions": 1,
        "accident_attribution.accident_attribution_summary": 1,
    }
    assert postgis_version
    assert redis.Redis.from_url(REDIS_URL).ping() is True


def test_preserved_explorer_apis_read_the_fixture() -> None:
    with httpx.Client(base_url=API_URL) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"email": "foundation-explorer@example.com", "password": "test-password"},
            timeout=5,
        )
        assert signup.status_code in {201, 409}
        if signup.status_code == 409:
            login = client.post(
                "/api/auth/login",
                json={"email": "foundation-explorer@example.com", "password": "test-password"},
                timeout=5,
            )
            assert login.status_code == 200
        corridors = client.get(
            "/api/canonical-network/corridors",
            params={"bbox": "34.7,32.0,34.9,32.2"},
            timeout=5,
        )
        accidents = client.get(
            "/api/accident-attribution/accidents",
            params={"bbox": "34.7,32.0,34.9,32.2"},
            timeout=5,
        )
        summary = client.get("/api/accident-attribution/summary", timeout=5)

    assert corridors.status_code == 200
    assert corridors.json()["corridors"][0]["corridor_id"] == "fixture-corridor-1"
    assert accidents.status_code == 200
    assert accidents.json()["accidents"][0]["accident_id"] == "fixture-accident-1"
    assert summary.status_code == 200
    assert summary.json()["total_accident_count"] == 1


def test_initializer_is_idempotent_and_rejects_stale_or_partial_data() -> None:
    same_source = run_initializer()
    assert same_source.returncode == 0, same_source.stderr
    assert "already initialized and verified" in same_source.stdout

    stale_source = run_initializer(
        FOUNDATION_DATA_MODE="verify",
        FOUNDATION_DATA_CHECKSUM="0" * 64,
    )
    assert stale_source.returncode != 0
    assert "checksum or kind does not match" in stale_source.stderr

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(
            "DELETE FROM canonical_network.official_segment_links "
            "WHERE official_segment_id = 'fixture-segment-1'"
        )
        connection.commit()

    partial_source = run_initializer()
    assert partial_source.returncode != 0
    assert "empty: canonical_network.official_segment_links" in partial_source.stderr

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        connection.execute(FIXTURE_PATH.read_text(encoding="utf-8"))
        connection.commit()

    restored_source = run_initializer()
    assert restored_source.returncode == 0, restored_source.stderr
