from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_ROUTE_JOB_INTEGRATION") != "true",
        reason="requires disposable PostGIS, Redis, and fake OSRM",
    ),
]

API_URL = os.environ.get("ROUTE_JOB_TEST_API_URL", "http://api:8000")
ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")


@pytest.fixture(autouse=True)
def clear_reroute_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    # Also clear auth-rate keys: each test signs up its own user, and the shared
    # SIGNUP_RATE_LIMIT is low enough that later tests in this file would otherwise
    # get a spurious 429 from earlier tests' signups, not from anything under test.
    for pattern in ("action-rate:route-reroute:*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


def signup(client: httpx.Client, prefix: str) -> dict[str, object]:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": f"{prefix}-{uuid4()}@example.com",
            "password": "correct-password",
            "driving_experience": "novice",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def reroute_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "current_longitude": 34.78,
        "current_latitude": 32.07,
        "destination_longitude": 34.79,
        "destination_latitude": 32.08,
        "scoring_context": {
            "driving_experience": "novice",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
            "reference_risk_p95": 10,
            "risk_data_version": "test-risk-v1",
        },
    }
    payload.update(overrides)
    return payload


def call_reroute(client: httpx.Client, **overrides: object) -> httpx.Response:
    return client.post(
        "/api/routing/reroute", json=reroute_payload(**overrides), headers={"Origin": ORIGIN}
    )


def test_reroute_returns_a_scored_candidate_with_turn_by_turn_steps() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "reroute-owner")
        response = call_reroute(owner)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "reroute-result-v1"
    assert body["chosen_index"] in {0, 1, 2}
    assert len(body["candidates"]) >= 1
    for candidate in body["candidates"]:
        assert candidate["geometry"]["type"] == "LineString"
        assert isinstance(candidate["steps"], list)


def test_reroute_rejects_a_point_outside_the_supported_region() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "reroute-out-of-region")
        response = call_reroute(owner, current_longitude=0, current_latitude=0)

    assert response.status_code == 422


def test_reroute_requires_authentication() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as anonymous:
        response = call_reroute(anonymous)

    assert response.status_code == 401


def test_rapid_rerouting_is_rate_limited_with_429_and_retry_after() -> None:
    with httpx.Client(base_url=API_URL, timeout=10) as owner:
        signup(owner, "reroute-spammer")
        responses = [call_reroute(owner) for _ in range(6)]

    statuses = [response.status_code for response in responses]
    assert 429 in statuses
    limited = responses[statuses.index(429)]
    assert "retry-after" in limited.headers
