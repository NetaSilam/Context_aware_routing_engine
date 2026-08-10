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
        os.environ.get("RUN_FORUM_ABUSE_INTEGRATION") != "true",
        reason="requires disposable PostgreSQL and Redis",
    ),
]

API_URL = os.environ.get("FORUM_ABUSE_TEST_API_URL", "http://abuse-api:8000")
UNAVAILABLE_API_URL = os.environ.get(
    "FORUM_ABUSE_UNAVAILABLE_API_URL", "http://geocoding-unavailable-api:8000"
)
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
REDIS_URL = os.environ["REDIS_URL"]
MUTATE_HEADERS = {"Origin": ORIGIN}


@pytest.fixture(autouse=True)
def clear_test_state() -> None:
    redis.Redis.from_url(REDIS_URL).flushdb()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("DELETE FROM app.users WHERE email LIKE 'forum-abuse-%@example.com'")


def signup(prefix: str) -> tuple[dict[str, object], str]:
    # Signup itself is Redis-rate-limited, so it always goes through the working
    # abuse-api instance. Its JWT/cookie is then reused against UNAVAILABLE_API_URL,
    # which shares the same JWT_SECRET and database, to probe fail-closed behavior
    # without the outage blocking signup itself.
    response = httpx.post(
        f"{API_URL}/api/auth/signup",
        json={
            "email": f"forum-abuse-{prefix}-{uuid4()}@example.com",
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        },
        timeout=5,
    )
    assert response.status_code == 201, response.text
    return response.json(), response.cookies["road_risk_session"]


def create_post(base_url: str, cookie: str, **overrides: object) -> httpx.Response:
    payload: dict[str, object] = {
        "title": "Deep pothole on Herzl",
        "body": "Careful, it's wide and deep near the crosswalk.",
        "hazard_type": "pothole",
        "is_anonymous": False,
    }
    payload.update(overrides)
    return httpx.post(
        f"{base_url}/api/forum/posts",
        cookies={"road_risk_session": cookie},
        headers=MUTATE_HEADERS,
        json=payload,
        timeout=5,
    )


def create_comment(base_url: str, cookie: str, post_id: str, body: str = "Still there today.") -> httpx.Response:
    return httpx.post(
        f"{base_url}/api/forum/posts/{post_id}/comments",
        cookies={"road_risk_session": cookie},
        headers=MUTATE_HEADERS,
        json={"body": body, "is_anonymous": False},
        timeout=5,
    )


def vote_on_post(base_url: str, cookie: str, post_id: str, value: str = "up") -> httpx.Response:
    return httpx.put(
        f"{base_url}/api/forum/posts/{post_id}/vote",
        cookies={"road_risk_session": cookie},
        headers=MUTATE_HEADERS,
        json={"value": value},
        timeout=5,
    )


def send_message(base_url: str, cookie: str, recipient_id: int, body: str = "hi there") -> httpx.Response:
    return httpx.post(
        f"{base_url}/api/messages/{recipient_id}",
        cookies={"road_risk_session": cookie},
        headers=MUTATE_HEADERS,
        data={"body": body},
        timeout=5,
    )


def test_rapid_post_creation_is_rate_limited_with_429_and_retry_after() -> None:
    _, cookie = signup("post")
    responses = [create_post(API_URL, cookie) for _ in range(5)]
    statuses = [response.status_code for response in responses]
    assert statuses.count(201) <= 2
    assert 429 in statuses
    limited = responses[statuses.index(429)]
    assert "retry-after" in limited.headers


def test_rapid_commenting_is_rate_limited() -> None:
    _, cookie = signup("comment")
    post = create_post(API_URL, cookie)
    assert post.status_code == 201, post.text
    post_id = post.json()["id"]

    responses = [create_comment(API_URL, cookie, post_id) for _ in range(5)]
    statuses = [response.status_code for response in responses]
    assert 429 in statuses
    assert statuses.count(201) < len(statuses)


def test_rapid_voting_is_rate_limited() -> None:
    _, cookie = signup("voter")
    post = create_post(API_URL, cookie)
    assert post.status_code == 201, post.text
    post_id = post.json()["id"]

    values = ["up", "none", "up", "none", "up", "none"]
    responses = [vote_on_post(API_URL, cookie, post_id, value) for value in values]
    statuses = [response.status_code for response in responses]
    assert 429 in statuses


def test_rapid_dm_sending_is_rate_limited() -> None:
    _, sender_cookie = signup("dm-sender")
    recipient, _ = signup("dm-recipient")

    responses = [send_message(API_URL, sender_cookie, recipient["id"]) for _ in range(5)]
    statuses = [response.status_code for response in responses]
    assert 429 in statuses
    limited = responses[statuses.index(429)]
    assert "retry-after" in limited.headers


def test_redis_outage_fails_closed_for_forum_writes_but_keeps_feed_readable() -> None:
    _, cookie = signup("outage-writer")

    post = create_post(UNAVAILABLE_API_URL, cookie)
    assert post.status_code == 503, post.text
    assert post.headers["retry-after"] == "5"

    feed = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/forum/posts",
        cookies={"road_risk_session": cookie},
        timeout=5,
    )
    assert feed.status_code == 200


def test_redis_outage_fails_closed_for_comments_and_votes() -> None:
    _, cookie = signup("outage-commenter")
    # Created through the working abuse-api instance (writes are Redis-gated), then
    # acted on through the outage instance, which shares the same database and JWT
    # secret, to isolate the outage's effect to the comment/vote calls under test.
    post = create_post(API_URL, cookie)
    assert post.status_code == 201, post.text
    post_id = post.json()["id"]

    comment = create_comment(UNAVAILABLE_API_URL, cookie, post_id)
    assert comment.status_code == 503, comment.text
    assert comment.headers["retry-after"] == "5"

    vote = vote_on_post(UNAVAILABLE_API_URL, cookie, post_id)
    assert vote.status_code == 503, vote.text
    assert vote.headers["retry-after"] == "5"

    post_detail = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/forum/posts/{post_id}",
        cookies={"road_risk_session": cookie},
        timeout=5,
    )
    assert post_detail.status_code == 200


def test_redis_outage_fails_closed_for_dm_send_but_keeps_conversation_readable() -> None:
    sender, sender_cookie = signup("outage-dm-sender")
    recipient, recipient_cookie = signup("outage-dm-recipient")

    sent = send_message(UNAVAILABLE_API_URL, sender_cookie, recipient["id"])
    assert sent.status_code == 503, sent.text
    assert sent.headers["retry-after"] == "5"

    conversation = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/messages/{sender['id']}",
        cookies={"road_risk_session": recipient_cookie},
        timeout=5,
    )
    assert conversation.status_code == 200

    conversations = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/messages",
        cookies={"road_risk_session": sender_cookie},
        timeout=5,
    )
    assert conversations.status_code == 200


def test_a_post_created_against_the_isolated_abuse_api_still_gets_triaged_by_the_shared_llm_worker() -> None:
    # abuse-api runs on its own isolated Redis db (see REDIS_URL above) so its rate-limit/capacity
    # state never cross-talks with other test services — but app.llm.tasks.celery_app's Celery
    # broker used to be bound to that SAME isolated db at import time, meaning any LLM job an
    # isolated api service enqueued had zero consumers (llm-worker-fast/slow only ever listen on
    # the shared db) and sat 'queued' forever. Fixed via LLM_QUEUE_BROKER_URL (see compose.test.yaml),
    # mirroring the existing ROUTE_QUEUE_BROKER_URL pattern. This proves the fix for real: a post
    # created here must still reach a terminal triage state via the shared llm-worker-fast.
    _, cookie = signup("llm-routing")
    post = create_post(API_URL, cookie)
    assert post.status_code == 201, post.text
    post_id = post.json()["id"]

    deadline = time.monotonic() + 15
    status = None
    while time.monotonic() < deadline:
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT status FROM app.llm_jobs WHERE subject_post_id = %s AND kind = 'triage'",
                (post_id,),
            ).fetchone()
        if row is not None and row[0] in {"completed", "failed"}:
            status = row[0]
            break
        time.sleep(0.2)
    assert status == "completed", f"triage job for post {post_id} never completed (last status: {status})"
