from __future__ import annotations

import os
import uuid

import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_FORUM_SECURITY_INTEGRATION") != "true",
        reason="requires the disposable Compose forum-security stack (real Postgres/Redis)",
    ),
]

ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
MUTATE_HEADERS = {"Origin": ALLOWED_ORIGIN}


@pytest.fixture(autouse=True)
def clear_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("action-rate:*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


def _signup(client, prefix: str) -> tuple[dict, dict]:
    email = f"forum-security-{prefix}-{uuid.uuid4().hex}@example.com"
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
    return response.json(), {"road_risk_session": response.cookies["road_risk_session"]}


def test_forum_dm_and_notification_activity_never_appears_in_process_output(capfd) -> None:
    # Imported here, not at module scope, so `RUN_FORUM_SECURITY_INTEGRATION`-gated skip
    # takes effect before app.main's module-level configure_structured_logging() runs.
    from fastapi.testclient import TestClient

    from app.main import create_app

    secret_post_body = f"SECRET-POST-BODY-{uuid.uuid4().hex}"
    secret_comment_body = f"SECRET-COMMENT-BODY-{uuid.uuid4().hex}"
    secret_dm_body = f"SECRET-DM-BODY-{uuid.uuid4().hex}"
    secret_media_marker = f"SECRET-MEDIA-{uuid.uuid4().hex}"
    secret_media_bytes = (secret_media_marker + "-not-a-real-jpeg").encode()

    with TestClient(create_app()) as client:
        author, author_cookies = _signup(client, "author")
        recipient, recipient_cookies = _signup(client, "recipient")

        post = client.post(
            "/api/forum/posts",
            json={
                "title": "Security log check",
                "body": secret_post_body,
                "hazard_type": "pothole",
                "is_anonymous": False,
            },
            cookies=author_cookies,
            headers=MUTATE_HEADERS,
        )
        assert post.status_code == 201, post.text
        post_id = post.json()["id"]

        media = client.post(
            f"/api/forum/posts/{post_id}/media",
            files={"file": ("hazard.jpg", secret_media_bytes, "image/jpeg")},
            cookies=author_cookies,
            headers=MUTATE_HEADERS,
        )
        assert media.status_code == 201, media.text

        comment = client.post(
            f"/api/forum/posts/{post_id}/comments",
            json={"body": secret_comment_body, "is_anonymous": False},
            cookies=author_cookies,
            headers=MUTATE_HEADERS,
        )
        assert comment.status_code == 201, comment.text

        dm = client.post(
            f"/api/messages/{author['id']}",
            data={"body": secret_dm_body},
            cookies=recipient_cookies,
            headers=MUTATE_HEADERS,
        )
        assert dm.status_code == 201, dm.text

        notifications = client.get("/api/notifications", cookies=author_cookies)
        assert notifications.status_code == 200

    # capfd reads the real OS-level stdout/stderr file descriptors, matching exactly what a
    # container's log driver would capture — not just records routed through pytest's own
    # logging handlers, which app.main's configure_structured_logging() replaces at import time.
    captured = capfd.readouterr()
    output = captured.out + captured.err

    assert secret_post_body not in output
    assert secret_comment_body not in output
    assert secret_dm_body not in output
    assert secret_media_marker not in output
