from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
import redis
from celery import Celery

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_ROUTE_JOB_INTEGRATION") != "true",
        reason="requires disposable PostGIS, Redis, Celery, and fake OSRM",
    ),
]

API_URL = os.environ.get("ROUTE_JOB_TEST_API_URL", "http://api:8000")
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
            "driving_experience": "novice",
            "vehicle_type": "motorcycle",
            "avoid_tolls": True,
            "avoid_highways": False,
        },
    )
    assert response.status_code == 201
    return response.json()


def route_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "origin_longitude": 34.78,
        "origin_latitude": 32.07,
        "destination_longitude": 34.79,
        "destination_latitude": 32.08,
        "origin_label": "Fixture origin",
        "destination_label": "Fixture destination",
    }
    payload.update(overrides)
    return payload


def idempotency_headers(key: str | None = None) -> dict[str, str]:
    return {"Origin": ORIGIN, "Idempotency-Key": key or str(uuid4())}


def wait_for_terminal(client: httpx.Client, job_id: str, timeout: float = 15) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    response = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/route-jobs/{job_id}")
        assert response.status_code == 200
        if response.json()["status"] in {"completed", "failed"}:
            return response.json()
        time.sleep(0.1)
    pytest.fail(f"route job did not finish: {response.text if response else job_id}")


def publish(job_id: str) -> None:
    app = Celery("route-job-integration", broker=os.environ["REDIS_URL"])
    try:
        app.send_task("app.routing.route_job_tasks.execute_route_job", args=[job_id])
    finally:
        app.close()


def insert_job(
    *, user_id: int, snapshot: dict[str, object], status: str = "queued",
    created_at: datetime | None = None, idempotency_key: UUID | None = None,
) -> str:
    job_id = str(uuid4())
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO app.route_jobs (
                id, user_id, idempotency_key, status,
                origin_longitude, origin_latitude,
                destination_longitude, destination_latitude,
                snapshot, created_at
            ) VALUES (%s, %s, %s, %s, 34.78, 32.07, 34.79, 32.08, %s, %s)
            """,
            (job_id, user_id, idempotency_key or uuid4(), status, psycopg.types.json.Jsonb(snapshot),
             created_at or datetime.now(timezone.utc)),
        )
    return job_id


def test_authenticated_route_job_completes_and_reloads_persisted_result() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "route-owner")
        accepted = owner.post(
            "/api/route-jobs", json=route_payload(), headers=idempotency_headers()
        )
        assert accepted.status_code == 202
        assert accepted.json()["status"] == "queued"
        job_id = accepted.json()["id"]

        observed_states = set()
        response = None
        for _ in range(50):
            response = owner.get(f"/api/route-jobs/{job_id}")
            assert response.status_code == 200
            observed_states.add(response.json()["status"])
            if response.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert response is not None
        assert response.json()["status"] == "completed", response.text
        result = response.json()["result"]
        assert len(result["candidates"]) == 3
        assert result["chosen_index"] in {0, 1, 2}
        assert result["risk_choice_available"] is True
        assert result["formula_version"] == "route-scoring-v1"
        assert result["matcher_version"] == "sampled-nearest-v1"
        assert result["graph_version"] == "test-osrm-graph-v1"
        assert result["risk_data_version"] == "test-risk-v1"
        assert all(candidate["geometry"]["type"] == "LineString" for candidate in result["candidates"])
        assert all(0 <= candidate["coverage"] <= 1 for candidate in result["candidates"])

        reloaded = owner.get(f"/api/route-jobs/{job_id}")
        assert reloaded.json()["result"] == result

    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT status, chosen_index, route_count, snapshot, result FROM app.route_jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
    assert row[0:3] == ("completed", result["chosen_index"], 3)
    assert row[3]["driving_experience"] == "novice"
    assert row[3]["vehicle_type"] == "motorcycle"
    assert row[3]["avoid_tolls"] is True
    assert row[3]["expected_graph_version"] == "test-osrm-graph-v1"
    assert row[4] == result


def test_invalid_input_never_creates_a_job_and_cross_user_lookup_is_404() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "validation-owner")
        with psycopg.connect(DATABASE_URL) as connection:
            before = connection.execute("SELECT count(*) FROM app.route_jobs").fetchone()[0]
        invalid_cases = [
            route_payload(destination_longitude=34.78, destination_latitude=32.07),
            route_payload(origin_longitude=0),
            route_payload(origin_longitude="34.78"),
            route_payload(origin_label="x" * 201),
        ]
        for payload in invalid_cases:
            response = owner.post("/api/route-jobs", json=payload, headers=idempotency_headers())
            assert response.status_code == 422
        with psycopg.connect(DATABASE_URL) as connection:
            after = connection.execute("SELECT count(*) FROM app.route_jobs").fetchone()[0]
        assert after == before

        accepted = owner.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers())
        assert accepted.status_code == 202
        job_id = accepted.json()["id"]

    with httpx.Client(base_url=API_URL, timeout=10) as other_user:
        signup(other_user, "route-other")
        hidden = other_user.get(f"/api/route-jobs/{job_id}")
    assert hidden.status_code == 404


def test_idempotency_is_unique_per_user_and_duplicate_delivery_is_harmless() -> None:
    key = str(uuid4())
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "idempotent-owner")
        first = owner.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers(key))
        second = owner.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers(key))
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]
        completed = wait_for_terminal(owner, first.json()["id"])
        assert completed["status"] == "completed"

        with psycopg.connect(DATABASE_URL) as connection:
            before_attempts = connection.execute(
                "SELECT attempt_count FROM app.route_jobs WHERE id = %s", (first.json()["id"],)
            ).fetchone()[0]
        publish(first.json()["id"])
        time.sleep(0.5)
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT count(*), min(status), min(attempt_count) FROM app.route_jobs "
                "WHERE user_id = (SELECT user_id FROM app.route_jobs WHERE id = %s) "
                "AND idempotency_key = %s",
                (first.json()["id"], key),
            ).fetchone()
        assert row == (1, "completed", before_attempts)

    with httpx.Client(base_url=API_URL, timeout=10) as other:
        signup(other, "idempotent-other")
        accepted = other.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers(key))
        assert accepted.status_code == 202
        assert accepted.json()["id"] != first.json()["id"]


def test_publish_failure_is_persisted_and_same_key_retry_recovers_row() -> None:
    queue_unavailable_url = os.environ["QUEUE_UNAVAILABLE_API_URL"]
    key = str(uuid4())
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "publish-failure")
        session_value = owner.cookies.get("road_risk_session")

    with httpx.Client(base_url=queue_unavailable_url, timeout=10) as unavailable:
        unavailable.cookies.set("road_risk_session", session_value)
        failed = unavailable.post(
            "/api/route-jobs", json=route_payload(), headers=idempotency_headers(key)
        )
        assert failed.status_code == 503
        assert failed.headers["Retry-After"] == "5"

    with psycopg.connect(DATABASE_URL) as connection:
        saved = connection.execute(
            "SELECT id, status, error_code FROM app.route_jobs WHERE idempotency_key = %s", (key,)
        ).fetchone()
    assert saved[1:] == ("enqueue_failed", "queue_unavailable")

    with httpx.Client(base_url=API_URL, timeout=10) as recovered:
        recovered.cookies.set("road_risk_session", session_value)
        retry = recovered.post(
            "/api/route-jobs", json=route_payload(), headers=idempotency_headers(key)
        )
        assert retry.status_code == 202
        assert retry.json()["id"] == str(saved[0])
        assert wait_for_terminal(recovered, retry.json()["id"])["status"] == "completed"


@pytest.mark.parametrize(
    ("origin_longitude", "expected_code", "minimum_attempts"),
    [
        (34.7001, "no_route", 1),
        (34.7002, "osrm_invalid_response", 1),
        (34.7003, "osrm_server_error", 3),
    ],
)
def test_upstream_failures_have_stable_retry_behavior(
    origin_longitude: float, expected_code: str, minimum_attempts: int
) -> None:
    with httpx.Client(base_url=API_URL, timeout=20) as owner:
        signup(owner, f"failure-{expected_code}")
        accepted = owner.post(
            "/api/route-jobs",
            json=route_payload(origin_longitude=origin_longitude),
            headers=idempotency_headers(),
        )
        assert accepted.status_code == 202
        failed = wait_for_terminal(owner, accepted.json()["id"], timeout=20)
    assert failed["status"] == "failed"
    assert failed["failure"]["code"] == expected_code
    assert failed["failure"]["message"]
    with psycopg.connect(DATABASE_URL) as connection:
        attempts = connection.execute(
            "SELECT attempt_count FROM app.route_jobs WHERE id = %s", (accepted.json()["id"],)
        ).fetchone()[0]
    assert attempts >= minimum_attempts
    if expected_code in {"no_route", "osrm_invalid_response"}:
        assert attempts == 1


def test_expired_lease_is_reclaimed_and_active_lease_is_not_claimed_twice() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        user = signup(owner, "lease-owner")
        seed = owner.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers())
        seed_result = wait_for_terminal(owner, seed.json()["id"])
        assert seed_result["status"] == "completed"
    with psycopg.connect(DATABASE_URL) as connection:
        snapshot = connection.execute(
            "SELECT snapshot FROM app.route_jobs WHERE id = %s", (seed.json()["id"],)
        ).fetchone()[0]

    job_id = insert_job(user_id=int(user["id"]), snapshot=snapshot)
    active_token = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            UPDATE app.route_jobs SET status = 'running', attempt_count = 1,
                lease_token = %s, lease_expires_at = now() + interval '2 seconds'
            WHERE id = %s
            """,
            (active_token, job_id),
        )
    publish(job_id)
    time.sleep(0.5)
    with psycopg.connect(DATABASE_URL) as connection:
        active = connection.execute(
            "SELECT status, attempt_count, lease_token FROM app.route_jobs WHERE id = %s", (job_id,)
        ).fetchone()
        connection.execute(
            "UPDATE app.route_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
            (job_id,),
        )
    assert active == ("running", 1, active_token)
    publish(job_id)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT status, attempt_count FROM app.route_jobs WHERE id = %s", (job_id,)
            ).fetchone()
        if row[0] == "completed":
            break
        time.sleep(0.1)
    assert row == ("completed", 2)


def test_worker_loss_redelivers_after_lease_expiry() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        user = signup(owner, "worker-loss")
        seed = owner.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers())
        wait_for_terminal(owner, seed.json()["id"])
    with psycopg.connect(DATABASE_URL) as connection:
        snapshot = connection.execute(
            "SELECT snapshot FROM app.route_jobs WHERE id = %s", (seed.json()["id"],)
        ).fetchone()[0]
    snapshot["_test_crash_once"] = True
    job_id = insert_job(user_id=int(user["id"]), snapshot=snapshot)
    publish(job_id)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT status, attempt_count FROM app.route_jobs WHERE id = %s", (job_id,)
            ).fetchone()
        if row[0] == "completed":
            break
        time.sleep(0.2)
    assert row == ("completed", 2)


def test_startup_recovers_stale_created_job_and_client_disconnect_does_not_cancel() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        user = signup(owner, "startup-recovery")
        seed = owner.post("/api/route-jobs", json=route_payload(), headers=idempotency_headers())
        wait_for_terminal(owner, seed.json()["id"])
        session_value = owner.cookies.get("road_risk_session")
    with psycopg.connect(DATABASE_URL) as connection:
        snapshot = connection.execute(
            "SELECT snapshot FROM app.route_jobs WHERE id = %s", (seed.json()["id"],)
        ).fetchone()[0]
    stale_id = insert_job(
        user_id=int(user["id"]), snapshot=snapshot, status="created",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )

    retry_key = uuid4()
    retry_stale_id = insert_job(
        user_id=int(user["id"]), snapshot=snapshot, status="created",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        idempotency_key=retry_key,
    )
    with httpx.Client(base_url=API_URL, timeout=10) as retrying_client:
        retrying_client.cookies.set("road_risk_session", session_value)
        retried = retrying_client.post(
            "/api/route-jobs",
            json=route_payload(),
            headers=idempotency_headers(str(retry_key)),
        )
        assert retried.status_code == 202
        assert retried.json()["id"] == retry_stale_id
        assert wait_for_terminal(retrying_client, retry_stale_id)["status"] == "completed"

    recovery_api = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8011"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if httpx.get("http://127.0.0.1:8011/health/live", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        with httpx.Client(base_url=API_URL, timeout=10) as reconnected:
            reconnected.cookies.set("road_risk_session", session_value)
            recovered = wait_for_terminal(reconnected, stale_id)
        assert recovered["status"] == "completed"

        with httpx.Client(base_url=API_URL, timeout=10) as submitting_client:
            submitting_client.cookies.set("road_risk_session", session_value)
            accepted = submitting_client.post(
                "/api/route-jobs", json=route_payload(), headers=idempotency_headers()
            )
            assert accepted.status_code == 202
            disconnected_job_id = accepted.json()["id"]
        with httpx.Client(base_url=API_URL, timeout=10) as refreshed_client:
            refreshed_client.cookies.set("road_risk_session", session_value)
            assert wait_for_terminal(refreshed_client, disconnected_job_id)["status"] == "completed"
    finally:
        recovery_api.terminate()
        recovery_api.wait(timeout=5)
