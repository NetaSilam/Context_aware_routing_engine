from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_GEOCODING_INTEGRATION") != "true",
        reason="requires the disposable Compose geocoding stack",
    ),
]

API_URL = os.environ.get("GEOCODING_TEST_API_URL", "http://api:8000")
UNAVAILABLE_API_URL = os.environ.get(
    "GEOCODING_UNAVAILABLE_API_URL", "http://geocoding-unavailable-api:8000"
)
FAKE_URL = os.environ.get("FAKE_GEOCODER_URL", "http://fake-geocoder:5001")
COOKIE_NAME = "road_risk_session"


@pytest.fixture(autouse=True)
def reset_geocoding_state() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("geocode-*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    httpx.post(f"{FAKE_URL}/reset", timeout=5).raise_for_status()


def authenticated_client() -> httpx.Client:
    email = f"geocode-{uuid4()}@example.com"
    response = httpx.post(
        f"{API_URL}/api/auth/signup",
        json={
            "email": email,
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        },
    )
    response.raise_for_status()
    redis_client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for key in redis_client.scan_iter("auth-rate:*"):
        redis_client.delete(key)
    return httpx.Client(base_url=API_URL, cookies=response.cookies)


def test_address_search_requires_login_and_validates_normalized_length() -> None:
    unauthorized = httpx.get(f"{API_URL}/api/geocoding/search", params={"q": "Tel Aviv"})
    with authenticated_client() as client:
        too_short = client.get("/api/geocoding/search", params={"q": "   x  "})
        too_long = client.get("/api/geocoding/search", params={"q": "x" * 201})

    assert unauthorized.status_code == 401
    assert too_short.status_code == 422
    assert too_long.status_code == 422


def test_normalized_query_is_cached_and_results_are_restricted_to_israel() -> None:
    with authenticated_client() as client:
        first = client.get("/api/geocoding/search", params={"q": "  TEL   AVIV  "})
        second = client.get("/api/geocoding/search", params={"q": "tel aviv"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json() == {
        "results": [
            {
                "label": "Tel Aviv Center",
                "longitude": 34.78,
                "latitude": 32.07,
            }
        ],
        "attribution": "© OpenStreetMap contributors",
    }
    metrics = httpx.get(f"{FAKE_URL}/metrics", timeout=5).json()
    assert metrics["requests_by_query"] == {"tel aviv": 1}


def test_empty_results_are_cached() -> None:
    with authenticated_client() as client:
        first = client.get("/api/geocoding/search", params={"q": "Empty Place"})
        second = client.get("/api/geocoding/search", params={"q": "empty   place"})
    assert first.status_code == second.status_code == 200
    assert first.json()["results"] == []
    metrics = httpx.get(f"{FAKE_URL}/metrics", timeout=5).json()
    assert metrics["requests_by_query"] == {"empty place": 1}


def test_application_wide_gate_allows_only_one_cache_miss_per_second() -> None:
    with authenticated_client() as client:
        first = client.get("/api/geocoding/search", params={"q": "First Place"})
        limited = client.get("/api/geocoding/search", params={"q": "Second Place"})
    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "1"


def test_per_user_limit_applies_even_to_cached_searches() -> None:
    with authenticated_client() as client:
        responses = [
            client.get("/api/geocoding/search", params={"q": "Same Place"})
            for _ in range(5)
        ]
    assert [response.status_code for response in responses] == [200, 200, 200, 200, 429]


def test_per_ip_limit_is_shared_across_users() -> None:
    clients = [authenticated_client() for _ in range(3)]
    try:
        responses = [
            client.get("/api/geocoding/search", params={"q": "Shared Cached Place"})
            for client in clients
            for _ in range(3)
        ]
    finally:
        for client in clients:
            client.close()
    assert [response.status_code for response in responses] == [200] * 8 + [429]


@pytest.mark.parametrize("query", ["malformed data", "malformed json", "service failure", "delayed place"])
def test_provider_failures_are_controlled_and_keep_coordinate_fallback_available(query: str) -> None:
    with authenticated_client() as client:
        response = client.get("/api/geocoding/search", params={"q": query})
    assert response.status_code == 503
    assert "map or numeric coordinates" in response.json()["detail"]
    assert response.headers["retry-after"] == "5"


def test_redis_unavailability_returns_controlled_feedback() -> None:
    with authenticated_client() as client:
        cookie = client.cookies.get(COOKIE_NAME)
    response = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/geocoding/search",
        params={"q": "Tel Aviv"},
        cookies={COOKIE_NAME: cookie},
        timeout=5,
    )
    assert response.status_code == 503
    assert "map or numeric coordinates" in response.json()["detail"]
