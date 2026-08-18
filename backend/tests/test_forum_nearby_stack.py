from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_FORUM_INTEGRATION") != "true",
        reason="requires the disposable Compose forum stack",
    ),
]

API_URL = os.environ.get("FORUM_TEST_API_URL", "http://api:8000")
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
MUTATE_HEADERS = {"Origin": ALLOWED_ORIGIN}


@pytest.fixture(autouse=True)
def clear_forum_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("action-rate:forum-*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@contextmanager
def _signup_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL) as client:
        email = f"forum-nearby-{uuid.uuid4().hex}@example.com"
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
        yield client


def _create_post(client: httpx.Client, *, longitude: float, latitude: float, **overrides: object) -> dict:
    payload = {
        "title": "Deep pothole on the shoulder",
        "body": "Wide and deep pothole right after the junction, watch out.",
        "hazard_type": "pothole",
        "is_anonymous": False,
        "longitude": longitude,
        "latitude": latitude,
        **overrides,
    }
    response = client.post("/api/forum/posts", json=payload, headers=MUTATE_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def _nearby(client: httpx.Client, **params: object) -> httpx.Response:
    query = {
        "min_lon": 34.70, "min_lat": 32.00, "max_lon": 34.90, "max_lat": 32.20,
        **params,
    }
    return client.get("/api/forum/posts/nearby", params=query)


def test_nearby_returns_only_posts_within_the_bbox() -> None:
    with _signup_client() as client:
        inside = _create_post(client, longitude=34.78, latitude=32.08)
        outside = _create_post(client, longitude=35.50, latitude=33.00)

        response = _nearby(client)

    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert inside["id"] in ids
    assert outside["id"] not in ids


def test_nearby_excludes_removed_posts() -> None:
    with _signup_client() as client:
        post = _create_post(client, longitude=34.78, latitude=32.08)
        deleted = client.delete(f"/api/forum/posts/{post['id']}", headers=MUTATE_HEADERS)
        assert deleted.status_code == 204

        response = _nearby(client)

    ids = {item["id"] for item in response.json()["items"]}
    assert post["id"] not in ids


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_lon": 34.90, "max_lon": 34.70},  # min > max
        {"min_lat": 32.20, "max_lat": 32.00},  # min > max
        {"min_lon": -190},  # out of range
        {"min_lon": 30.0, "max_lon": 40.0, "min_lat": 25.0, "max_lat": 35.0},  # span too large
    ],
)
def test_nearby_rejects_malformed_or_oversized_bbox(overrides: dict[str, object]) -> None:
    with _signup_client() as client:
        response = _nearby(client, **overrides)

    assert response.status_code == 422


def test_nearby_requires_authentication() -> None:
    response = httpx.get(
        f"{API_URL}/api/forum/posts/nearby",
        params={"min_lon": 34.70, "min_lat": 32.00, "max_lon": 34.90, "max_lat": 32.20},
        timeout=5,
    )
    assert response.status_code == 401
