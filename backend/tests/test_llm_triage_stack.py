from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import psycopg
import pytest
import redis

from app.llm.client import TEST_FAILURE_MARKER

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_LLM_INTEGRATION") != "true",
        reason="requires the disposable Compose LLM stack",
    ),
]

API_URL = os.environ.get("LLM_TRIAGE_TEST_API_URL", "http://api:8000")
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
MUTATE_HEADERS = {"Origin": ALLOWED_ORIGIN}
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace(
    "postgresql+psycopg://", "postgresql://"
)


@pytest.fixture(autouse=True)
def clear_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("action-rate:forum-*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@contextmanager
def _signup_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL) as client:
        email = f"llm-triage-{uuid.uuid4().hex}@example.com"
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


def _create_post(client: httpx.Client, **overrides: object) -> dict:
    payload = {
        "title": "Deep pothole on the shoulder",
        "body": "Wide and deep pothole right after the junction, watch out.",
        "hazard_type": "pothole",
        "is_anonymous": False,
        **overrides,
    }
    response = client.post("/api/forum/posts", json=payload, headers=MUTATE_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def _llm_job_status(post_id: str) -> str | None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT status FROM app.llm_jobs WHERE subject_post_id = %s AND kind = 'triage'",
            (post_id,),
        ).fetchone()
    return row[0] if row else None


def _wait_for_llm_job(post_id: str, *, deadline_seconds: float = 15) -> str:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        status = _llm_job_status(post_id)
        if status in {"completed", "failed"}:
            return status
        time.sleep(0.2)
    pytest.fail(f"triage job for post {post_id} did not reach a terminal state in time")


def test_new_post_gets_llm_classification_fields_populated() -> None:
    with _signup_client() as client:
        created = _create_post(client, hazard_type="flooding")
        post_id = created["id"]

        assert created["llm_hazard_type_suggested"] is None
        assert created["llm_severity"] is None

        status = _wait_for_llm_job(post_id)
        assert status == "completed"

        detail = client.get(f"/api/forum/posts/{post_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["llm_hazard_type_suggested"] == "flooding"
    assert body["llm_severity"] == "medium"


def test_a_failed_triage_job_leaves_the_post_fully_visible_and_unclassified() -> None:
    with _signup_client() as client:
        created = _create_post(client, body=f"Deep pothole {TEST_FAILURE_MARKER}")
        post_id = created["id"]

        status = _wait_for_llm_job(post_id)
        assert status == "failed"

        detail = client.get(f"/api/forum/posts/{post_id}")
        feed = client.get("/api/forum/posts")

    assert detail.status_code == 200
    body = detail.json()
    assert body["llm_hazard_type_suggested"] is None
    assert body["llm_severity"] is None
    assert body["title"] == created["title"]

    assert feed.status_code == 200
    assert any(item["id"] == post_id for item in feed.json()["items"])
