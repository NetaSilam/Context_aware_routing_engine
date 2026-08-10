from __future__ import annotations

import json
import os
import subprocess

import psycopg
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_FORUM_SEED_INTEGRATION") != "true",
        reason="requires the disposable Compose forum-seed stack",
    ),
]

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def run_seed() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", "-m", "app.seed_forum_demo_data"],
        check=False,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )


def test_seeding_is_idempotent_and_populates_realistic_content() -> None:
    first = run_seed()
    assert first.returncode == 0, first.stderr
    first_report = json.loads(first.stdout)
    assert first_report["users"] >= 6
    assert first_report["posts"] >= 8
    assert first_report["comments"] >= 8
    assert first_report["votes"] >= 8

    second = run_seed()
    assert second.returncode == 0, second.stderr
    second_report = json.loads(second.stdout)
    assert second_report == first_report, "re-running the seed step must not change row counts"

    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        user_count = connection.execute(
            "SELECT COUNT(*) FROM app.users WHERE is_seed_account = TRUE"
        ).fetchone()[0]
        assert user_count == first_report["users"]

        hazard_types = {
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT p.hazard_type FROM app.forum_posts p
                JOIN app.users u ON u.id = p.author_user_id
                WHERE u.is_seed_account = TRUE
                """
            ).fetchall()
        }
        assert len(hazard_types) >= 5, "seed posts should span most hazard types"

        threads_with_comments = connection.execute(
            """
            SELECT COUNT(*) FROM app.forum_posts p
            JOIN app.users u ON u.id = p.author_user_id
            WHERE u.is_seed_account = TRUE AND p.comment_count > 0
            """
        ).fetchone()[0]
        assert threads_with_comments > 0

        voted_posts = connection.execute(
            """
            SELECT COUNT(*) FROM app.forum_posts p
            JOIN app.users u ON u.id = p.author_user_id
            WHERE u.is_seed_account = TRUE AND (p.upvote_count > 0 OR p.downvote_count > 0)
            """
        ).fetchone()[0]
        assert voted_posts > 0


def test_seed_accounts_use_a_stable_recognizable_email_pattern_and_valid_password_hash() -> None:
    run_seed()
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        rows = connection.execute(
            "SELECT email, password_hash FROM app.users WHERE is_seed_account = TRUE"
        ).fetchall()
    assert rows
    for email, password_hash in rows:
        assert email.startswith("seed+")
        assert email.endswith("@example.local")
        assert password_hash.startswith("$2")


def test_seeded_posts_never_reference_a_real_non_seed_author() -> None:
    run_seed()
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        non_seed_authors = connection.execute(
            """
            SELECT COUNT(*) FROM app.forum_posts p
            JOIN app.users u ON u.id = p.author_user_id
            WHERE u.is_seed_account = TRUE AND u.email NOT LIKE 'seed+%@example.local'
            """
        ).fetchone()[0]
    assert non_seed_authors == 0
