from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import psycopg
import pytest
import redis

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


def signup(client: httpx.Client, prefix: str) -> None:
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


def test_authenticated_route_job_completes_and_reloads_persisted_result() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "route-owner")
        accepted = owner.post(
            "/api/route-jobs", json=route_payload(), headers={"Origin": ORIGIN}
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
            response = owner.post("/api/route-jobs", json=payload, headers={"Origin": ORIGIN})
            assert response.status_code == 422
        with psycopg.connect(DATABASE_URL) as connection:
            after = connection.execute("SELECT count(*) FROM app.route_jobs").fetchone()[0]
        assert after == before

        accepted = owner.post("/api/route-jobs", json=route_payload(), headers={"Origin": ORIGIN})
        assert accepted.status_code == 202
        job_id = accepted.json()["id"]

    with httpx.Client(base_url=API_URL, timeout=10) as other_user:
        signup(other_user, "route-other")
        hidden = other_user.get(f"/api/route-jobs/{job_id}")
    assert hidden.status_code == 404
