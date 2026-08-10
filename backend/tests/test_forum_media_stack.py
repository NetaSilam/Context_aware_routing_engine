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

# Small fixed in-memory payloads. Content-type validation trusts the declared upload
# content type rather than sniffing bytes, so these never need to be real media files.
TINY_IMAGE_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes"
TINY_VIDEO_BYTES = b"fake-mp4-bytes" * 4


@pytest.fixture(autouse=True)
def clear_forum_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("action-rate:forum-*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@contextmanager
def _signup_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        email = f"forum-media-{uuid.uuid4().hex}@example.com"
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


def _create_comment(client: httpx.Client, post_id: str, **overrides: object) -> dict:
    payload = {"body": "Still there today.", "is_anonymous": False, **overrides}
    response = client.post(
        f"/api/forum/posts/{post_id}/comments", json=payload, headers=MUTATE_HEADERS
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_and_retrieve_post_media() -> None:
    with _signup_client() as client:
        post = _create_post(client)
        uploaded = client.post(
            f"/api/forum/posts/{post['id']}/media",
            files={"file": ("hazard.jpg", TINY_IMAGE_BYTES, "image/jpeg")},
            headers=MUTATE_HEADERS,
        )
        assert uploaded.status_code == 201, uploaded.text
        media = uploaded.json()
        assert media["media_type"] == "image"
        assert media["content_type"] == "image/jpeg"
        assert media["byte_size"] == len(TINY_IMAGE_BYTES)

        fetched = client.get(f"/api/forum/media/{media['id']}")
        assert fetched.status_code == 200
        assert fetched.content == TINY_IMAGE_BYTES
        assert fetched.headers["content-type"] == "image/jpeg"

        detail = client.get(f"/api/forum/posts/{post['id']}").json()
        assert [item["id"] for item in detail["media"]] == [media["id"]]


def test_upload_post_media_is_owner_only() -> None:
    with _signup_client() as owner, _signup_client() as other:
        post = _create_post(owner)
        forbidden = other.post(
            f"/api/forum/posts/{post['id']}/media",
            files={"file": ("hazard.jpg", TINY_IMAGE_BYTES, "image/jpeg")},
            headers=MUTATE_HEADERS,
        )
    assert forbidden.status_code == 404


def test_upload_post_media_rejects_unsupported_content_type() -> None:
    with _signup_client() as client:
        post = _create_post(client)
        rejected = client.post(
            f"/api/forum/posts/{post['id']}/media",
            files={"file": ("hazard.pdf", b"%PDF-fake", "application/pdf")},
            headers=MUTATE_HEADERS,
        )
    assert rejected.status_code == 422


def test_upload_post_media_rejects_oversized_video() -> None:
    # One byte past the default 25 MB video cap; large enough to exercise the real
    # size check without sending an unnecessarily large request body in a test.
    oversized_payload = b"\x00" * 25_000_001
    with _signup_client() as client:
        post = _create_post(client)
        oversized = client.post(
            f"/api/forum/posts/{post['id']}/media",
            files={"file": ("hazard.mp4", oversized_payload, "video/mp4")},
            headers=MUTATE_HEADERS,
        )
    assert oversized.status_code in (413, 422)


def test_upload_comment_media_and_retrieve_via_post_detail() -> None:
    with _signup_client() as author, _signup_client() as commenter:
        post = _create_post(author)
        comment = _create_comment(commenter, post["id"])
        uploaded = commenter.post(
            f"/api/forum/comments/{comment['id']}/media",
            files={"file": ("clip.mp4", TINY_VIDEO_BYTES, "video/mp4")},
            headers=MUTATE_HEADERS,
        )
        assert uploaded.status_code == 201, uploaded.text
        media = uploaded.json()
        assert media["media_type"] == "video"

        fetched = author.get(f"/api/forum/media/{media['id']}")
        assert fetched.status_code == 200
        assert fetched.content == TINY_VIDEO_BYTES

        comments = author.get(f"/api/forum/posts/{post['id']}/comments").json()
        assert [item["id"] for item in comments["items"][0]["media"]] == [media["id"]]


def test_upload_comment_media_is_owner_only() -> None:
    with _signup_client() as author, _signup_client() as other:
        post = _create_post(author)
        comment = _create_comment(author, post["id"])
        forbidden = other.post(
            f"/api/forum/comments/{comment['id']}/media",
            files={"file": ("clip.mp4", TINY_VIDEO_BYTES, "video/mp4")},
            headers=MUTATE_HEADERS,
        )
    assert forbidden.status_code == 404


def test_media_becomes_inaccessible_after_post_deleted() -> None:
    with _signup_client() as client:
        post = _create_post(client)
        media = client.post(
            f"/api/forum/posts/{post['id']}/media",
            files={"file": ("hazard.jpg", TINY_IMAGE_BYTES, "image/jpeg")},
            headers=MUTATE_HEADERS,
        ).json()
        client.delete(f"/api/forum/posts/{post['id']}", headers=MUTATE_HEADERS)
        after_delete = client.get(f"/api/forum/media/{media['id']}")
    assert after_delete.status_code == 404


def test_media_count_per_post_is_capped() -> None:
    with _signup_client() as client:
        post = _create_post(client)
        responses = [
            client.post(
                f"/api/forum/posts/{post['id']}/media",
                files={"file": (f"hazard-{index}.jpg", TINY_IMAGE_BYTES, "image/jpeg")},
                headers=MUTATE_HEADERS,
            )
            for index in range(8)
        ]
    statuses = [response.status_code for response in responses]
    assert statuses.count(201) <= 6
    assert 422 in statuses


def test_missing_media_id_returns_404() -> None:
    with _signup_client() as client:
        response = client.get(f"/api/forum/media/{uuid.uuid4()}")
    assert response.status_code == 404
