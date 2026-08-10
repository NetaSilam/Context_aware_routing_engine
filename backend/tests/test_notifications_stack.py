from __future__ import annotations

import json
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
        os.environ.get("RUN_NOTIFICATIONS_INTEGRATION") != "true",
        reason="requires the disposable Compose notifications stack",
    ),
]

API_URL = os.environ.get("NOTIFICATIONS_TEST_API_URL", "http://api:8000")
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
MUTATE_HEADERS = {"Origin": ALLOWED_ORIGIN}


def _clear_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("action-rate:*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@pytest.fixture(autouse=True)
def clear_rate_limits() -> None:
    _clear_rate_limits()


@contextmanager
def _signup_client() -> Iterator[tuple[httpx.Client, int]]:
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        _clear_rate_limits()
        email = f"notif-{uuid.uuid4().hex}@example.com"
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
        yield client, response.json()["id"]


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


def test_new_dm_creates_a_notification_for_the_recipient() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        sent = alice.post(f"/api/messages/{bob_id}", data={"body": "hi bob"}, headers=MUTATE_HEADERS)
        assert sent.status_code == 201, sent.text

        notifications = bob.get("/api/notifications").json()

    kinds = [item["kind"] for item in notifications["items"]]
    assert "new_dm" in kinds
    assert notifications["unread_count"] >= 1


def test_voting_on_someone_elses_post_notifies_the_author() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        post = _create_post(alice)
        voted = bob.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)
        assert voted.status_code == 204

        notifications = alice.get("/api/notifications").json()

    kinds = [item["kind"] for item in notifications["items"]]
    assert "new_vote" in kinds


def test_self_vote_does_not_create_a_notification() -> None:
    with _signup_client() as (alice, alice_id):
        post = _create_post(alice)
        alice.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)

        notifications = alice.get("/api/notifications").json()

    assert notifications["items"] == []


def test_clearing_a_vote_does_not_create_a_notification() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        post = _create_post(alice)
        bob.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)
        alice.post("/api/notifications/read-all", headers=MUTATE_HEADERS)
        bob.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "none"}, headers=MUTATE_HEADERS)

        notifications = alice.get("/api/notifications").json()

    assert notifications["unread_count"] == 0


def test_commenting_on_someone_elses_post_notifies_the_author_with_anonymity_respected() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        post = _create_post(alice)
        bob.post(
            f"/api/forum/posts/{post['id']}/comments",
            json={"body": "still there", "is_anonymous": True},
            headers=MUTATE_HEADERS,
        )

        notifications = alice.get("/api/notifications").json()

    comment_notification = next(
        item for item in notifications["items"] if item["kind"] == "new_comment"
    )
    assert comment_notification["payload"].get("actor_label") is None
    assert "email" not in json.dumps(comment_notification["payload"])


def test_mark_notification_read_and_read_all() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        post = _create_post(alice)
        bob.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)

        page = alice.get("/api/notifications").json()
        notification_id = page["items"][0]["id"]

        marked = alice.post(f"/api/notifications/{notification_id}/read", headers=MUTATE_HEADERS)
        after_one = alice.get("/api/notifications").json()

        bob.post(
            f"/api/forum/posts/{post['id']}/comments",
            json={"body": "confirmed", "is_anonymous": False},
            headers=MUTATE_HEADERS,
        )
        alice.post("/api/notifications/read-all", headers=MUTATE_HEADERS)
        after_all = alice.get("/api/notifications").json()

    assert marked.status_code == 204
    assert after_one["items"][0]["read_at"] is not None
    assert after_all["unread_count"] == 0


def test_notifications_are_scoped_to_the_authenticated_recipient() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id), _signup_client() as (
        carol,
        carol_id,
    ):
        post = _create_post(alice)
        bob.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)

        carol_notifications = carol.get("/api/notifications").json()

    assert carol_notifications["items"] == []


def test_sse_stream_delivers_a_live_event_after_a_new_dm() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        with alice.stream("GET", "/api/notifications/stream", timeout=10) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            first_line = next(lines)
            assert "ready" in first_line or first_line == "" or first_line.startswith("data:")

            sent = bob.post(f"/api/messages/{alice_id}", data={"body": "hi"}, headers=MUTATE_HEADERS)
            assert sent.status_code == 201, sent.text

            found_event = False
            for line in lines:
                if line.startswith("data:") and "new_dm" in line:
                    found_event = True
                    break
            assert found_event
