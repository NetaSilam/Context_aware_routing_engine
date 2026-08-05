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
    # Each test signs up one or more fresh users through the real signup endpoint, which
    # shares the same per-IP auth rate limit as every other test in this file.
    for pattern in ("action-rate:forum-*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@contextmanager
def _signup_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL) as client:
        email = f"forum-{uuid.uuid4().hex}@example.com"
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
        client.headers.update({"X-Test-Email": email})
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


def test_forum_requires_authentication() -> None:
    response = httpx.get(f"{API_URL}/api/forum/posts", timeout=5)
    assert response.status_code == 401


def test_create_list_and_get_post() -> None:
    with _signup_client() as client:
        created = _create_post(client, title="Flooded underpass")
        feed = client.get("/api/forum/posts")
        detail = client.get(f"/api/forum/posts/{created['id']}")

    assert created["title"] == "Flooded underpass"
    assert created["hazard_type"] == "pothole"
    assert created["is_own"] is True
    assert created["upvote_count"] == 0
    assert created["comment_count"] == 0
    assert feed.status_code == 200
    assert any(item["id"] == created["id"] for item in feed.json()["items"])
    assert detail.status_code == 200
    assert detail.json()["body"] == created["body"]


def test_hazard_type_filter_only_returns_matching_posts() -> None:
    with _signup_client() as client:
        _create_post(client, hazard_type="pothole", title="Pothole entry")
        _create_post(client, hazard_type="flooding", title="Flooding entry")
        filtered = client.get("/api/forum/posts", params={"hazard_type": "flooding"})

    titles = [item["title"] for item in filtered.json()["items"]]
    assert "Flooding entry" in titles
    assert "Pothole entry" not in titles


def test_post_update_and_delete_are_owner_only() -> None:
    with _signup_client() as owner, _signup_client() as other:
        created = _create_post(owner)
        post_id = created["id"]

        forbidden_update = other.patch(
            f"/api/forum/posts/{post_id}", json={"title": "Hijacked title"}, headers=MUTATE_HEADERS
        )
        forbidden_delete = other.delete(f"/api/forum/posts/{post_id}", headers=MUTATE_HEADERS)

        owner_update = owner.patch(
            f"/api/forum/posts/{post_id}", json={"title": "Updated title"}, headers=MUTATE_HEADERS
        )
        owner_delete = owner.delete(f"/api/forum/posts/{post_id}", headers=MUTATE_HEADERS)
        after_delete = owner.get(f"/api/forum/posts/{post_id}")

    assert forbidden_update.status_code == 404
    assert forbidden_delete.status_code == 404
    assert owner_update.status_code == 200
    assert owner_update.json()["title"] == "Updated title"
    assert owner_delete.status_code == 204
    assert after_delete.status_code == 404


def test_comment_lifecycle_and_post_comment_count() -> None:
    with _signup_client() as author, _signup_client() as commenter:
        post = _create_post(author)
        post_id = post["id"]

        created = commenter.post(
            f"/api/forum/posts/{post_id}/comments",
            json={"body": "Still there this morning.", "is_anonymous": False},
            headers=MUTATE_HEADERS,
        )
        assert created.status_code == 201
        comment_id = created.json()["id"]

        listed = author.get(f"/api/forum/posts/{post_id}/comments")
        after_comment_post = author.get(f"/api/forum/posts/{post_id}")

        forbidden_edit = author.patch(
            f"/api/forum/comments/{comment_id}", json={"body": "hijacked"}, headers=MUTATE_HEADERS
        )
        owner_edit = commenter.patch(
            f"/api/forum/comments/{comment_id}",
            json={"body": "Cleared up by afternoon."},
            headers=MUTATE_HEADERS,
        )
        owner_delete = commenter.delete(f"/api/forum/comments/{comment_id}", headers=MUTATE_HEADERS)
        after_delete_post = author.get(f"/api/forum/posts/{post_id}")

    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert after_comment_post.json()["comment_count"] == 1
    assert forbidden_edit.status_code == 404
    assert owner_edit.status_code == 200
    assert owner_edit.json()["body"] == "Cleared up by afternoon."
    assert owner_delete.status_code == 204
    assert after_delete_post.json()["comment_count"] == 0


def test_anonymous_post_and_comment_hide_author_from_others_but_not_from_self() -> None:
    with _signup_client() as author, _signup_client() as other:
        post = _create_post(author, is_anonymous=True, title="Speed camera on the bridge")
        post_id = post["id"]
        comment = author.post(
            f"/api/forum/posts/{post_id}/comments",
            json={"body": "Confirmed, still there.", "is_anonymous": True},
            headers=MUTATE_HEADERS,
        ).json()

        as_author_post = author.get(f"/api/forum/posts/{post_id}").json()
        as_other_post = other.get(f"/api/forum/posts/{post_id}").json()
        as_other_comments = other.get(f"/api/forum/posts/{post_id}/comments").json()

    assert post["author_id"] is None
    assert post["author_email"] is None
    assert post["is_own"] is True

    assert as_author_post["is_own"] is True
    assert as_author_post["author_id"] is None

    assert as_other_post["is_own"] is False
    assert as_other_post["author_id"] is None
    assert as_other_post["author_email"] is None
    assert "@example.com" not in httpx.Response(200, json=as_other_post).text

    other_comment = as_other_comments["items"][0]
    assert other_comment["author_id"] is None
    assert other_comment["author_email"] is None
    assert other_comment["is_own"] is False
    assert comment["is_own"] is True


def test_vote_toggle_updates_counts_and_my_vote() -> None:
    with _signup_client() as author, _signup_client() as voter:
        post = _create_post(author)
        post_id = post["id"]

        up = voter.put(f"/api/forum/posts/{post_id}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)
        after_up = voter.get(f"/api/forum/posts/{post_id}").json()

        switched = voter.put(
            f"/api/forum/posts/{post_id}/vote", json={"value": "down"}, headers=MUTATE_HEADERS
        )
        after_switch = voter.get(f"/api/forum/posts/{post_id}").json()

        cleared = voter.put(
            f"/api/forum/posts/{post_id}/vote", json={"value": "none"}, headers=MUTATE_HEADERS
        )
        after_clear = voter.get(f"/api/forum/posts/{post_id}").json()

    assert up.status_code == 204
    assert after_up["upvote_count"] == 1
    assert after_up["downvote_count"] == 0
    assert after_up["my_vote"] == "up"

    assert switched.status_code == 204
    assert after_switch["upvote_count"] == 0
    assert after_switch["downvote_count"] == 1
    assert after_switch["my_vote"] == "down"

    assert cleared.status_code == 204
    assert after_clear["upvote_count"] == 0
    assert after_clear["downvote_count"] == 0
    assert after_clear["my_vote"] == "none"


def test_vote_on_comment_and_missing_targets_return_404() -> None:
    with _signup_client() as author, _signup_client() as voter:
        post = _create_post(author)
        comment = author.post(
            f"/api/forum/posts/{post['id']}/comments",
            json={"body": "First to confirm.", "is_anonymous": False},
            headers=MUTATE_HEADERS,
        ).json()

        voted = voter.put(
            f"/api/forum/comments/{comment['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS
        )
        listed = author.get(f"/api/forum/posts/{post['id']}/comments").json()

        missing_post_vote = voter.put(
            f"/api/forum/posts/{uuid.uuid4()}/vote", json={"value": "up"}, headers=MUTATE_HEADERS
        )
        missing_comment_vote = voter.put(
            f"/api/forum/comments/{uuid.uuid4()}/vote", json={"value": "up"}, headers=MUTATE_HEADERS
        )

    assert voted.status_code == 204
    assert listed["items"][0]["upvote_count"] == 1
    assert missing_post_vote.status_code == 404
    assert missing_comment_vote.status_code == 404


def test_dashboard_reports_counts_and_net_votes_received() -> None:
    with _signup_client() as author, _signup_client() as voter:
        post = _create_post(author)
        author.post(
            f"/api/forum/posts/{post['id']}/comments",
            json={"body": "Own follow-up comment.", "is_anonymous": False},
            headers=MUTATE_HEADERS,
        )
        voter.put(f"/api/forum/posts/{post['id']}/vote", json={"value": "up"}, headers=MUTATE_HEADERS)

        dashboard = author.get("/api/forum/me/dashboard")

    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["post_count"] == 1
    assert body["comment_count"] == 1
    assert body["net_votes_received"] == 1
