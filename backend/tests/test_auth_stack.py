from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
import jwt
import psycopg
import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_AUTH_INTEGRATION") != "true",
        reason="requires the disposable Compose authentication stack",
    ),
]

API_URL = os.environ.get("AUTH_TEST_API_URL", "http://api:8000")
SECURE_API_URL = os.environ.get("AUTH_TEST_SECURE_API_URL", "http://secure-auth-api:8000")
UNAVAILABLE_API_URL = os.environ.get(
    "AUTH_TEST_UNAVAILABLE_API_URL", "http://auth-unavailable-api:8000"
)
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
JWT_SECRET = os.environ["JWT_SECRET"]
DATABASE_URL = os.environ["DATABASE_URL"].replace(
    "postgresql+psycopg://", "postgresql://"
)
COOKIE_NAME = "road_risk_session"


@pytest.fixture(autouse=True)
def clear_auth_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for key in client.scan_iter("auth-rate:*"):
        client.delete(key)


def signup_payload(email: str, password: str = "correct-password") -> dict[str, object]:
    return {
        "email": email,
        "password": password,
        "driving_experience": "novice",
        "vehicle_type": "motorcycle",
        "avoid_tolls": True,
        "avoid_highways": False,
    }


def test_signup_normalizes_email_hashes_password_and_rejects_duplicate() -> None:
    with httpx.Client(base_url=API_URL) as client:
        response = client.post("/api/auth/signup", json=signup_payload("  Mixed.Case@Example.com "))
        duplicate = client.post("/api/auth/signup", json=signup_payload("mixed.case@example.com"))

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "email": "mixed.case@example.com",
        "driving_experience": "novice",
        "vehicle_type": "motorcycle",
        "avoid_tolls": True,
        "avoid_highways": False,
    }
    assert "password" not in response.text
    assert duplicate.status_code == 409

    with psycopg.connect(DATABASE_URL) as connection:
        stored_email, password_hash = connection.execute(
            "SELECT email, password_hash FROM app.users WHERE email = %s",
            ("mixed.case@example.com",),
        ).fetchone()
    assert stored_email == "mixed.case@example.com"
    assert password_hash.startswith("$2")
    assert password_hash != "correct-password"
    assert bcrypt.checkpw(b"correct-password", password_hash.encode())


@pytest.mark.parametrize("password", ["1234567", "a" * 73, "\N{LOCK}" * 19])
def test_signup_rejects_passwords_outside_bcrypt_bounds(password: str) -> None:
    response = httpx.post(
        f"{API_URL}/api/auth/signup",
        json=signup_payload(f"bounds-{len(password.encode())}@example.com", password),
        timeout=5,
    )
    assert response.status_code == 422


def test_login_profile_preference_update_origin_and_logout() -> None:
    email = "journey@example.com"
    httpx.post(f"{API_URL}/api/auth/signup", json=signup_payload(email), timeout=5)

    with httpx.Client(base_url=API_URL) as client:
        incorrect = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        correct = client.post(
            "/api/auth/login", json={"email": email.upper(), "password": "correct-password"}
        )
        profile = client.get("/api/auth/me")
        rejected_update = client.patch("/api/auth/me", json={"vehicle_type": "truck"})
        updated = client.patch(
            "/api/auth/me",
            json={"vehicle_type": "truck", "avoid_highways": True},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        logout = client.post("/api/auth/logout", headers={"Origin": ALLOWED_ORIGIN})
        after_logout = client.get("/api/auth/me")

    assert incorrect.status_code == 401
    assert correct.status_code == 200
    assert profile.status_code == 200
    assert rejected_update.status_code == 403
    assert updated.status_code == 200
    assert updated.json()["vehicle_type"] == "truck"
    assert updated.json()["avoid_highways"] is True
    assert logout.status_code == 204
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert after_logout.status_code == 401


def test_session_cookie_flags_no_store_and_secure_deployment_flag() -> None:
    response = httpx.post(
        f"{API_URL}/api/auth/signup",
        json=signup_payload("cookie@example.com"),
        timeout=5,
    )
    cookie = response.headers["set-cookie"]
    assert f"{COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age=86400" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert "access_token" not in response.text

    secure_response = httpx.post(
        f"{SECURE_API_URL}/api/auth/signup",
        json=signup_payload("secure-cookie@example.com"),
        timeout=5,
    )
    assert secure_response.status_code == 201
    assert "Secure" in secure_response.headers["set-cookie"]


def test_missing_invalid_and_expired_sessions_are_controlled_401s() -> None:
    missing = httpx.get(f"{API_URL}/api/auth/me", timeout=5)
    invalid = httpx.get(
        f"{API_URL}/api/auth/me", cookies={COOKIE_NAME: "not-a-jwt"}, timeout=5
    )
    expired_token = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        JWT_SECRET,
        algorithm="HS256",
    )
    expired = httpx.get(
        f"{API_URL}/api/auth/me", cookies={COOKIE_NAME: expired_token}, timeout=5
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert expired.status_code == 401


def test_login_rate_limit_blocks_even_a_correct_password_after_limit() -> None:
    email = "limited-login@example.com"
    httpx.post(f"{API_URL}/api/auth/signup", json=signup_payload(email), timeout=5)
    for _ in range(2):
        response = httpx.post(
            f"{API_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=5,
        )
        assert response.status_code == 401

    limited = httpx.post(
        f"{API_URL}/api/auth/login",
        json={"email": email, "password": "correct-password"},
        timeout=5,
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_signup_rate_limit_is_shared_by_client_ip() -> None:
    for index in range(2):
        response = httpx.post(
            f"{API_URL}/api/auth/signup",
            json=signup_payload(f"signup-limit-{index}@example.com"),
            timeout=5,
        )
        assert response.status_code == 201

    limited = httpx.post(
        f"{API_URL}/api/auth/signup",
        json=signup_payload("signup-limit-blocked@example.com"),
        timeout=5,
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_signup_and_login_fail_closed_when_redis_is_unavailable() -> None:
    signup = httpx.post(
        f"{UNAVAILABLE_API_URL}/api/auth/signup",
        json=signup_payload("redis-down@example.com"),
        timeout=5,
    )
    login = httpx.post(
        f"{UNAVAILABLE_API_URL}/api/auth/login",
        json={"email": "redis-down@example.com", "password": "correct-password"},
        timeout=5,
    )
    assert signup.status_code == 503
    assert login.status_code == 503
    assert signup.headers["retry-after"] == "5"


def test_application_data_requires_cookie_authentication() -> None:
    response = httpx.get(
        f"{API_URL}/api/canonical-network/corridors",
        params={"bbox": "34.7,32.0,34.9,32.2"},
        timeout=5,
    )
    assert response.status_code == 401
