from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
import redis
from psycopg.types.json import Jsonb

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_LLM_INTEGRATION") != "true",
        reason="requires the disposable Compose LLM stack",
    ),
]

API_URL = os.environ.get("LLM_ROUTE_EXPLANATION_TEST_API_URL", "http://api:8000")
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace(
    "postgresql+psycopg://", "postgresql://"
)


@pytest.fixture(autouse=True)
def clear_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("auth-rate:*", "action-rate:route-*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


def _signup(client: httpx.Client) -> dict:
    email = f"llm-route-explain-{uuid4().hex}@example.com"
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _mutate_headers() -> dict:
    return {"Origin": ALLOWED_ORIGIN, "Idempotency-Key": str(uuid4())}


def _route_payload() -> dict:
    return {
        "origin_longitude": 34.78,
        "origin_latitude": 32.07,
        "destination_longitude": 34.79,
        "destination_latitude": 32.08,
        "origin_label": "Fixture origin",
        "destination_label": "Fixture destination",
    }


def _wait_for_route_job_completed(client: httpx.Client, job_id: str, *, deadline_seconds: float = 15) -> dict:
    deadline = time.monotonic() + deadline_seconds
    response = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/route-jobs/{job_id}")
        assert response.status_code == 200, response.text
        if response.json()["status"] in {"completed", "failed"}:
            return response.json()
        time.sleep(0.2)
    pytest.fail(f"route job {job_id} did not reach a terminal state in time: {response.text if response else ''}")


def _wait_for_llm_explanation(client: httpx.Client, job_id: str, *, deadline_seconds: float = 15) -> dict:
    deadline = time.monotonic() + deadline_seconds
    response = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/route-jobs/{job_id}")
        assert response.status_code == 200, response.text
        if response.json()["llm_explanation"] is not None:
            return response.json()
        time.sleep(0.2)
    pytest.fail(f"route job {job_id} never gained an llm_explanation: {response.text if response else ''}")


def test_a_completed_route_job_eventually_gets_a_plain_language_explanation() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        _signup(client)
        accepted = client.post("/api/route-jobs", json=_route_payload(), headers=_mutate_headers())
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["id"]

        completed = _wait_for_route_job_completed(client, job_id)
        assert completed["status"] == "completed", completed
        # Not asserting llm_explanation is still None here: with the deterministic test mock the
        # explanation job can finish before this next GET, so that would be a race, not a real
        # check. The non-blocking guarantee (explanation is enqueued only after route_jobs is
        # already marked completed, and a failure there can't undo that) is proven structurally
        # by route_job_tasks.py's ordering and by the fail-open test below.

        explained = _wait_for_llm_explanation(client, job_id)

    assert explained["llm_explanation"] == "Deterministic test explanation."
    # The explanation must merge into the existing result, not replace or corrupt it.
    assert explained["result"]["chosen_index"] == completed["result"]["chosen_index"]
    assert len(explained["result"]["candidates"]) == len(completed["result"]["candidates"])
    assert explained["result"]["llm_explanation"] == "Deterministic test explanation."


def _insert_completed_route_job(user_id: int) -> tuple[str, dict]:
    job_id = str(uuid4())
    result = {
        "schema_version": "route-result-v1",
        "chosen_index": 0,
        "risk_choice_available": False,
        "candidates": [
            {
                "candidate_index": 0,
                "distance_m": 1000.0,
                "duration_seconds": 120.0,
                "historical_accident_density_per_km": 0.1,
                "final_cost": 0.2,
            }
        ],
    }
    snapshot = {
        "driving_experience": "experienced",
        "vehicle_type": "car",
        "avoid_tolls": False,
        "avoid_highways": False,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO app.route_jobs (
                id, user_id, idempotency_key, status,
                origin_longitude, origin_latitude,
                destination_longitude, destination_latitude,
                snapshot, result, chosen_index, route_count, completed_at
            ) VALUES (
                %s, %s, %s, 'completed',
                34.78, 32.07, 34.79, 32.08,
                %s, %s, 0, 1, now()
            )
            """,
            (job_id, user_id, uuid4(), Jsonb(snapshot), Jsonb(result)),
        )
        connection.commit()
    return job_id, result


def _llm_job_status(route_job_id: str) -> str | None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT status FROM app.llm_jobs
            WHERE subject_route_job_id = %s AND kind = 'route_explanation'
            ORDER BY created_at DESC LIMIT 1
            """,
            (route_job_id,),
        ).fetchone()
    return row[0] if row else None


def _route_job_result(route_job_id: str) -> dict:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT result FROM app.route_jobs WHERE id = %s", (route_job_id,)
        ).fetchone()
    return row[0]


def test_a_failed_explanation_job_leaves_the_route_result_fully_intact() -> None:
    # The real cost_breakdown/user_context route_job_tasks.py builds are computed numeric/enum
    # values with no user-controlled free text, so there is no HTTP-reachable way to inject the
    # TEST_FAILURE_MARKER through the normal submission flow (unlike forum triage/dedup, where
    # the report body is free text). This test instead calls enqueue_route_explanation directly
    # against a fixture route job, exactly like test_llm_scheduling_stack.py calls
    # create_llm_job/enqueue_llm_job directly to exercise scheduling without going through HTTP.
    from app.llm.client import TEST_FAILURE_MARKER
    from app.llm.tasks import enqueue_route_explanation

    with httpx.Client(base_url=API_URL, timeout=10) as client:
        user = _signup(client)

    route_job_id, original_result = _insert_completed_route_job(int(user["id"]))

    enqueue_route_explanation(
        route_job_id=route_job_id,
        cost_breakdown={"duration_seconds": TEST_FAILURE_MARKER, "final_cost": 0.2},
        user_context={"driving_experience": "experienced"},
    )

    deadline = time.monotonic() + 15
    status = None
    while time.monotonic() < deadline:
        status = _llm_job_status(route_job_id)
        if status in {"completed", "failed"}:
            break
        time.sleep(0.2)
    assert status == "failed", status

    assert _route_job_result(route_job_id) == original_result
