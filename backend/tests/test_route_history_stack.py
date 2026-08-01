from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import psycopg
import pytest
import redis
from psycopg.types.json import Jsonb

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_ROUTE_HISTORY_INTEGRATION") != "true",
        reason="requires disposable PostGIS, Redis, Celery, and fake OSRM",
    ),
]

API_URL = os.environ.get("ROUTE_HISTORY_TEST_API_URL", "http://api:8000")
ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(autouse=True)
def clear_signup_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for key in client.scan_iter("auth-rate:signup:*"):
        client.delete(key)


def signup(client: httpx.Client, prefix: str) -> dict[str, object]:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": f"{prefix}-{uuid4()}@example.com",
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        },
    )
    assert response.status_code == 201
    return response.json()


def submit_and_wait(client: httpx.Client, *, origin_label: str = "Saved origin") -> dict[str, object]:
    accepted = client.post(
        "/api/route-jobs",
        headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
        json={
            "origin_longitude": 34.78,
            "origin_latitude": 32.07,
            "destination_longitude": 34.79,
            "destination_latitude": 32.08,
            "origin_label": origin_label,
            "destination_label": "Saved destination",
        },
    )
    assert accepted.status_code == 202
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        loaded = client.get(f"/api/route-jobs/{accepted.json()['id']}")
        assert loaded.status_code == 200
        if loaded.json()["status"] == "completed":
            return loaded.json()
        assert loaded.json()["status"] != "failed", loaded.text
        time.sleep(0.1)
    pytest.fail("route job did not complete")


def test_history_lists_only_completed_compact_summaries_in_deterministic_pages() -> None:
    assert httpx.get(f"{API_URL}/api/route-history", timeout=5).status_code == 401
    with httpx.Client(base_url=API_URL, timeout=20) as owner:
        user = signup(owner, "history-list")
        completed = [submit_and_wait(owner, origin_label=f"Origin {index}") for index in range(3)]

        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "UPDATE app.route_jobs SET completed_at = TIMESTAMPTZ '2026-01-01 00:00:00+00' "
                "WHERE id = ANY(%s)",
                ([job["id"] for job in completed],),
            )
            failed_id = uuid4()
            connection.execute(
                """
                INSERT INTO app.route_jobs (
                    id, user_id, idempotency_key, status, origin_longitude, origin_latitude,
                    destination_longitude, destination_latitude, snapshot, error_code, completed_at
                ) VALUES (%s, %s, %s, 'failed', 34.78, 32.07, 34.79, 32.08, '{}',
                          'no_route', now())
                """,
                (failed_id, user["id"], uuid4()),
            )

        first = owner.get("/api/route-history", params={"limit": 2, "offset": 0})
        second = owner.get("/api/route-history", params={"limit": 2, "offset": 2})
        default_page = owner.get("/api/route-history")
        too_large = owner.get("/api/route-history", params={"limit": 51})

    assert first.status_code == second.status_code == 200
    assert first.json()["has_more"] is True
    assert second.json()["has_more"] is False
    assert default_page.json()["limit"] == 10
    ids = [item["id"] for item in first.json()["items"] + second.json()["items"]]
    assert ids == sorted((job["id"] for job in completed), reverse=True)
    assert str(failed_id) not in ids
    assert "result" not in first.json()["items"][0]
    assert "geometry" not in str(first.json()["items"])
    assert first.json()["items"][0]["distance_m"] > 0
    assert too_large.status_code == 422

    with psycopg.connect(DATABASE_URL) as connection:
        definition = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'app' "
            "AND indexname = 'route_jobs_completed_history_idx'"
        ).fetchone()[0]
    assert "user_id, status, completed_at DESC, id DESC" in definition


def test_history_detail_is_exact_and_run_again_uses_current_context_without_mutation() -> None:
    unsafe_label = '<img src=x onerror="alert(1)">'
    with httpx.Client(base_url=API_URL, timeout=20) as owner:
        signup(owner, "history-rerun")
        original = submit_and_wait(owner, origin_label=unsafe_label)
        original_id = original["id"]
        original_result = original["result"]

        with psycopg.connect(DATABASE_URL) as connection:
            original_snapshot = connection.execute(
                "SELECT snapshot FROM app.route_jobs WHERE id = %s", (original_id,)
            ).fetchone()[0]
            old_result = {**original_result, "graph_version": "old-graph-v0"}
            connection.execute(
                "UPDATE app.route_jobs SET result = %s WHERE id = %s",
                (Jsonb(old_result), original_id),
            )
        owner.patch(
            "/api/auth/me",
            headers={"Origin": ORIGIN},
            json={"driving_experience": "novice", "vehicle_type": "motorcycle"},
        ).raise_for_status()

        detail = owner.get(f"/api/route-history/{original_id}")
        rerun_key = str(uuid4())
        rerun = owner.post(
            f"/api/route-history/{original_id}/run-again",
            headers={"Origin": ORIGIN, "Idempotency-Key": rerun_key},
        )
        duplicate = owner.post(
            f"/api/route-history/{original_id}/run-again",
            headers={"Origin": ORIGIN, "Idempotency-Key": rerun_key},
        )
        rerun_result = submit_wait_existing(owner, rerun.json()["id"])
        original_after = owner.get(f"/api/route-history/{original_id}")

    assert detail.status_code == 200
    assert detail.json()["origin_label"] == unsafe_label
    assert detail.json()["result"]["graph_version"] == "old-graph-v0"
    assert len(detail.json()["result"]["candidates"]) == len(original_result["candidates"])
    assert all("geometry" in candidate for candidate in detail.json()["result"]["candidates"])
    assert rerun.status_code == duplicate.status_code == 202
    assert rerun.json()["id"] == duplicate.json()["id"]
    assert rerun.json()["id"] != original_id
    assert rerun_result["result"]["graph_version"] == "test-osrm-graph-v1"
    with psycopg.connect(DATABASE_URL) as connection:
        new_snapshot = connection.execute(
            "SELECT snapshot FROM app.route_jobs WHERE id = %s", (rerun.json()["id"],)
        ).fetchone()[0]
    assert new_snapshot["driving_experience"] == "novice"
    assert new_snapshot["vehicle_type"] == "motorcycle"
    assert new_snapshot["submitted_at"] != original_snapshot["submitted_at"]
    assert new_snapshot["risk_data_version"] == "test-risk-v1"
    assert new_snapshot["matcher_version"] == "sampled-nearest-v1"
    assert new_snapshot["expected_graph_version"] == "test-osrm-graph-v1"
    assert original_after.json() == detail.json()


def submit_wait_existing(client: httpx.Client, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        loaded = client.get(f"/api/route-jobs/{job_id}")
        if loaded.json()["status"] == "completed":
            return loaded.json()
        time.sleep(0.1)
    pytest.fail("rerun did not complete")


def test_history_deletion_is_completed_only_owned_and_private() -> None:
    with httpx.Client(base_url=API_URL, timeout=20) as owner:
        owner_user = signup(owner, "history-delete-owner")
        first = submit_and_wait(owner)
        second = submit_and_wait(owner)

    with httpx.Client(base_url=API_URL, timeout=20) as other:
        signup(other, "history-delete-other")
        assert other.get(f"/api/route-history/{first['id']}").status_code == 404
        assert other.delete(
            f"/api/route-history/{first['id']}", headers={"Origin": ORIGIN}
        ).status_code == 404
        assert other.post(
            f"/api/route-history/{first['id']}/run-again",
            headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
        ).status_code == 404

    with httpx.Client(base_url=API_URL, timeout=20) as owner:
        # Restore the owner's authenticated cookie through login.
        email = owner_user["email"]
        owner.post("/api/auth/login", json={"email": email, "password": "correct-password"})
        assert owner.delete(
            f"/api/route-history/{first['id']}", headers={"Origin": ORIGIN}
        ).status_code == 204
        assert owner.get(f"/api/route-history/{first['id']}").status_code == 404
        assert owner.delete("/api/route-history", headers={"Origin": ORIGIN}).status_code == 204
        assert owner.get("/api/route-history").json()["items"] == []

    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.route_jobs WHERE id = %s", (second["id"],)
        ).fetchone()[0] == 0
