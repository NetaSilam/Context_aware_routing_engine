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

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_LLM_INTEGRATION") != "true",
        reason="requires the disposable Compose LLM stack",
    ),
]

API_URL = os.environ.get("LLM_DEDUP_TEST_API_URL", "http://api:8000")
ALLOWED_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
MUTATE_HEADERS = {"Origin": ALLOWED_ORIGIN}
DATABASE_URL = os.environ.get("DATABASE_URL", "").replace(
    "postgresql+psycopg://", "postgresql://"
)

# Must match this service's LLM_DEDUP_CANDIDATE_LIMIT override in compose.test.yaml.
CANDIDATE_LIMIT = 2


@pytest.fixture(autouse=True)
def clear_rate_limits() -> None:
    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    for pattern in ("action-rate:forum-*", "auth-rate:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@contextmanager
def _signup_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL) as client:
        email = f"llm-dedup-{uuid.uuid4().hex}@example.com"
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
        "title": "Hazard report",
        "body": "Deep pothole right after the junction, watch out.",
        "hazard_type": "pothole",
        "is_anonymous": False,
        **overrides,
    }
    response = client.post("/api/forum/posts", json=payload, headers=MUTATE_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def _job_row(post_id: str, kind: str) -> tuple[str, dict] | None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT status, result FROM app.llm_jobs WHERE subject_post_id = %s AND kind = %s",
            (post_id, kind),
        ).fetchone()
    return row


def _wait_for_job(post_id: str, kind: str, *, deadline_seconds: float = 15) -> tuple[str, dict]:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        row = _job_row(post_id, kind)
        if row is not None and row[0] in {"completed", "failed"}:
            return row
        time.sleep(0.2)
    pytest.fail(f"{kind} job for post {post_id} did not reach a terminal state in time")


def test_a_genuine_near_duplicate_gets_flagged() -> None:
    duplicate_body = "Deep pothole near the school entrance, cars are swerving around it."
    with _signup_client() as client:
        original = _create_post(
            client, hazard_type="pothole", body=duplicate_body, longitude=34.7800, latitude=32.0700
        )
        _wait_for_job(original["id"], "triage")

        candidate = _create_post(
            client, hazard_type="pothole", body=duplicate_body, longitude=34.7801, latitude=32.0701
        )
        _wait_for_job(candidate["id"], "triage")
        status, result = _wait_for_job(candidate["id"], "dedup_check")

        detail = client.get(f"/api/forum/posts/{candidate['id']}")
        original_detail = client.get(f"/api/forum/posts/{original['id']}")

    assert status == "completed"
    assert result["is_duplicate"] is True
    assert detail.status_code == 200
    assert detail.json()["duplicate_of_post_id"] == original["id"]
    # The earlier, original report is the one being copied — it must never itself end up
    # flagged as a duplicate just because a later report happened to be checked against it.
    assert original_detail.status_code == 200
    assert original_detail.json()["duplicate_of_post_id"] is None


def test_a_different_hazard_type_at_the_same_spot_is_not_flagged() -> None:
    same_body = "Something is wrong with the road here, be careful."
    with _signup_client() as client:
        original = _create_post(
            client, hazard_type="pothole", body=same_body, longitude=34.7900, latitude=32.0800
        )
        _wait_for_job(original["id"], "triage")

        candidate = _create_post(
            client, hazard_type="flooding", body=same_body, longitude=34.7900, latitude=32.0800
        )
        _wait_for_job(candidate["id"], "triage")

        detail = client.get(f"/api/forum/posts/{candidate['id']}")

    # A dedup_check job may or may not be created (there are zero same-hazard-type candidates at
    # this spot), but either way the post must never end up flagged as a duplicate of `original`.
    assert detail.status_code == 200
    assert detail.json()["duplicate_of_post_id"] != original["id"]


def test_the_same_hazard_type_far_away_is_not_flagged() -> None:
    same_body = "Same wording, different place entirely."
    with _signup_client() as client:
        original = _create_post(
            client, hazard_type="crash", body=same_body, longitude=34.70, latitude=32.00
        )
        _wait_for_job(original["id"], "triage")

        # Roughly 100km+ away — far outside the default/overridden dedup radius.
        candidate = _create_post(
            client, hazard_type="crash", body=same_body, longitude=35.70, latitude=33.00
        )
        status, _ = _wait_for_job(candidate["id"], "triage")
        assert status == "completed"

        detail = client.get(f"/api/forum/posts/{candidate['id']}")

    assert detail.status_code == 200
    assert detail.json()["duplicate_of_post_id"] is None


def test_a_post_with_no_coordinates_is_flagged_against_the_same_authors_recent_post() -> None:
    # PRD decision 5's location-based search has nothing to compare against without
    # coordinates, but a post without a location is a fully supported, first-class path
    # (PostForm.tsx's lon/lat fields are optional) — the author-scoped fallback (see
    # app/llm/tasks.py's _find_dedup_candidates_for_post) catches this exact case: the same user
    # posting an identical report twice.
    duplicate_body = "Debris blocking the exit ramp, watch out at night."
    with _signup_client() as client:
        original = _create_post(
            client, hazard_type="other", body=duplicate_body, longitude=None, latitude=None
        )
        _wait_for_job(original["id"], "triage")

        candidate = _create_post(
            client, hazard_type="other", body=duplicate_body, longitude=None, latitude=None
        )
        _wait_for_job(candidate["id"], "triage")
        status, result = _wait_for_job(candidate["id"], "dedup_check")

        detail = client.get(f"/api/forum/posts/{candidate['id']}")

    assert status == "completed"
    assert result["is_duplicate"] is True
    assert detail.status_code == 200
    assert detail.json()["duplicate_of_post_id"] == original["id"]


def test_a_post_with_no_coordinates_is_not_compared_against_a_different_authors_posts() -> None:
    # The author-scoped fallback is deliberately narrow: comparing a stranger's posts with no
    # location signal at all would be noisy and could produce implausible duplicate claims.
    same_body = "Debris blocking the exit ramp, watch out at night, cross-author check."
    with _signup_client() as first_author:
        original = _create_post(
            first_author, hazard_type="other", body=same_body, longitude=None, latitude=None
        )
        _wait_for_job(original["id"], "triage")

    with _signup_client() as second_author:
        candidate = _create_post(
            second_author, hazard_type="other", body=same_body, longitude=None, latitude=None
        )
        status, _ = _wait_for_job(candidate["id"], "triage")
        assert status == "completed"

        job = _job_row(candidate["id"], "dedup_check")
        detail = second_author.get(f"/api/forum/posts/{candidate['id']}")

    assert job is None
    assert detail.status_code == 200
    assert detail.json()["duplicate_of_post_id"] is None


def test_a_backfill_style_recheck_never_flags_the_earlier_post_as_a_duplicate_of_a_later_one() -> None:
    # Simulates seed_forum_demo_data.py's _backfill_missing_dedup_checks calling
    # enqueue_dedup_check_if_applicable directly for a post that already exists, after a later
    # near-identical post was also created — the earlier report is the one being copied, so it
    # must never retroactively end up flagged as a duplicate of the later one just because a
    # dedup check happens to run for it after the later post exists.
    from app.llm.tasks import enqueue_dedup_check_if_applicable

    duplicate_body = "Backfill-order check: debris on the shoulder near the toll gate."
    with _signup_client() as client:
        original = _create_post(
            client, hazard_type="other", body=duplicate_body, longitude=34.77, latitude=32.06
        )
        _wait_for_job(original["id"], "triage")

        later = _create_post(
            client, hazard_type="other", body=duplicate_body, longitude=34.7701, latitude=32.0601
        )
        _wait_for_job(later["id"], "triage")
        _wait_for_job(later["id"], "dedup_check")

        # original's own triage-time dedup check found zero candidates (later didn't exist yet),
        # so no job was ever created for it — this is the first dedup attempt for original,
        # exactly like a backfill re-checking a post that never got one the first time.
        with psycopg.connect(DATABASE_URL) as connection:
            enqueue_dedup_check_if_applicable(connection, original["id"])
        time.sleep(2)

        original_detail = client.get(f"/api/forum/posts/{original['id']}")

    assert original_detail.status_code == 200
    assert original_detail.json()["duplicate_of_post_id"] is None


def test_candidate_count_is_capped_against_a_dense_cluster() -> None:
    with _signup_client() as client:
        candidate_ids = []
        for i in range(CANDIDATE_LIMIT + 2):
            candidate = _create_post(
                client,
                hazard_type="pothole",
                body=f"Distinct pothole description number {i}, not a duplicate of the others.",
                longitude=34.75,
                latitude=32.05,
            )
            _wait_for_job(candidate["id"], "triage")
            candidate_ids.append(candidate["id"])

        subject = _create_post(
            client,
            hazard_type="pothole",
            body="Yet another distinct description, the subject post itself.",
            longitude=34.75,
            latitude=32.05,
        )
        _wait_for_job(subject["id"], "triage")
        status, result = _wait_for_job(subject["id"], "dedup_check")

    assert status == "completed"
    assert result["candidates_checked"] == CANDIDATE_LIMIT
