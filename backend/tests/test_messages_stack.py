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
        os.environ.get("RUN_MESSAGES_INTEGRATION") != "true",
        reason="requires the disposable Compose messages stack",
    ),
]

API_URL = os.environ.get("MESSAGES_TEST_API_URL", "http://api:8000")
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
MUTATE_HEADERS = {"Origin": ALLOWED_ORIGIN}
TINY_IMAGE_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes"


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
        # The shared `api` test service caps SIGNUP_RATE_LIMIT at 2 per IP per window (see
        # compose.test.yaml), and several tests here need three fresh users in one test. Clear
        # the signup limiter before every individual signup, not just once per test.
        _clear_rate_limits()
        email = f"dm-{uuid.uuid4().hex}@example.com"
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


def _send_message(
    client: httpx.Client,
    recipient_id: int,
    *,
    body: str | None = "Hello there",
    files: dict | None = None,
) -> httpx.Response:
    data = {} if body is None else {"body": body}
    return client.post(
        f"/api/messages/{recipient_id}",
        data=data,
        files=files,
        headers=MUTATE_HEADERS,
    )


def test_send_and_fetch_conversation_in_ascending_order() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        first = _send_message(alice, bob_id, body="Hi Bob, is the pothole still there?")
        second = _send_message(bob, alice_id, body="Yes, still there this morning.")
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

        conversation = alice.get(f"/api/messages/{bob_id}")

    assert conversation.status_code == 200
    items = conversation.json()["items"]
    assert [item["body"] for item in items] == [
        "Hi Bob, is the pothole still there?",
        "Yes, still there this morning.",
    ]
    assert items[0]["sender_user_id"] == alice_id
    assert items[1]["sender_user_id"] == bob_id


def test_send_message_requires_body_or_media() -> None:
    with _signup_client() as (alice, _), _signup_client() as (_, bob_id):
        rejected = _send_message(alice, bob_id, body=None)
    assert rejected.status_code == 422


def test_cannot_message_self() -> None:
    with _signup_client() as (alice, alice_id):
        rejected = _send_message(alice, alice_id, body="talking to myself")
    assert rejected.status_code == 422


def test_send_message_to_unknown_user_returns_404() -> None:
    with _signup_client() as (alice, _):
        rejected = _send_message(alice, 987654321, body="hello?")
    assert rejected.status_code == 404


def test_send_message_with_media_attachment_is_retrievable() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        sent = _send_message(
            alice,
            bob_id,
            body="See attached",
            files={"file": ("hazard.jpg", TINY_IMAGE_BYTES, "image/jpeg")},
        )
        assert sent.status_code == 201, sent.text
        media = sent.json()["media"]
        assert media is not None
        assert media["media_type"] == "image"

        fetched_by_recipient = bob.get(f"/api/forum/media/{media['id']}")
        stranger_media = alice.get(f"/api/forum/media/{media['id']}")

    assert fetched_by_recipient.status_code == 200
    assert fetched_by_recipient.content == TINY_IMAGE_BYTES
    # The sender is also a participant and must be able to see their own attachment.
    assert stranger_media.status_code == 200


def test_dm_media_is_not_visible_to_a_non_participant() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id), _signup_client() as (
        eve,
        _,
    ):
        sent = _send_message(
            alice,
            bob_id,
            body="private attachment",
            files={"file": ("hazard.jpg", TINY_IMAGE_BYTES, "image/jpeg")},
        )
        media_id = sent.json()["media"]["id"]
        forbidden = eve.get(f"/api/forum/media/{media_id}")
    assert forbidden.status_code == 404


def test_conversation_read_receipts_update_when_recipient_opens_it() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id):
        _send_message(alice, bob_id, body="are you there?")

        before_read = alice.get(f"/api/messages/{bob_id}").json()["items"]
        bob.get(f"/api/messages/{alice_id}")
        after_read = alice.get(f"/api/messages/{bob_id}").json()["items"]

    assert before_read[0]["read_at"] is None
    assert after_read[0]["read_at"] is not None


def test_get_conversation_with_unknown_user_returns_404() -> None:
    with _signup_client() as (alice, _):
        response = alice.get("/api/messages/987654321")
    assert response.status_code == 404


def test_list_conversations_shows_other_participant_and_unread_count() -> None:
    with _signup_client() as (alice, alice_id), _signup_client() as (bob, bob_id), _signup_client() as (
        carol,
        carol_id,
    ):
        _send_message(alice, bob_id, body="hi bob")
        _send_message(carol, alice_id, body="hi alice")
        _send_message(carol, alice_id, body="are you there")

        conversations = alice.get("/api/messages").json()["items"]

    by_partner = {item["other_user_id"]: item for item in conversations}
    assert by_partner[bob_id]["unread_count"] == 0
    assert by_partner[carol_id]["unread_count"] == 2
    assert by_partner[carol_id]["last_message_body"] == "are you there"


def test_cannot_send_oversized_message_body() -> None:
    with _signup_client() as (alice, _), _signup_client() as (_, bob_id):
        rejected = _send_message(alice, bob_id, body="x" * 2001)
    assert rejected.status_code == 422
