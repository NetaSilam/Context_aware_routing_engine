from __future__ import annotations

import os

import psycopg
import pytest
import redis
from celery import Celery

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_LLM_INTEGRATION") != "true",
        reason="requires the disposable Compose LLM stack",
    ),
]

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace(
    "postgresql+psycopg://", "postgresql://"
)
REDIS_URL = os.environ.get("REDIS_URL", "")


def _columns(table_schema: str, table_name: str) -> dict[str, str]:
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (table_schema, table_name),
        ).fetchall()
    return {name: is_nullable for name, is_nullable in rows}


def test_llm_jobs_table_exists_with_expected_shape() -> None:
    columns = _columns("app", "llm_jobs")
    assert columns, "app.llm_jobs must exist"
    assert columns["id"] == "NO"
    assert columns["kind"] == "NO"
    assert columns["subject_post_id"] == "YES"
    assert columns["subject_route_job_id"] == "YES"
    assert columns["status"] == "NO"
    assert columns["queue_name"] == "NO"
    assert columns["estimated_duration_ms"] == "NO"
    assert columns["result"] == "YES"
    assert columns["error"] == "YES"
    assert columns["created_at"] == "NO"
    assert columns["completed_at"] == "YES"


def test_forum_posts_gains_nullable_llm_columns() -> None:
    columns = _columns("app", "forum_posts")
    assert columns["llm_hazard_type_suggested"] == "YES"
    assert columns["llm_severity"] == "YES"
    assert columns["duplicate_of_post_id"] == "YES"


def test_llm_jobs_allows_a_subject_less_job_but_rejects_a_mismatched_subject() -> None:
    # 0008 relaxed 0007's original "kind requires a subject" constraint: a scheduling-only job
    # (ticket 3's integration test) legitimately has no real forum post/route job to reference
    # yet. What must still be rejected is a subject column that belongs to the wrong kind.
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO app.llm_jobs
                    (id, kind, status, queue_name, estimated_duration_ms)
                VALUES
                    (gen_random_uuid(), 'triage', 'queued', 'llm-fast', 100)
                """
            )

        # A real, existing forum post id (cold-seeded by `initialize`) isolates the assertion to
        # the CHECK constraint itself, rather than also tripping the subject_post_id foreign key.
        real_post_id = connection.execute(
            "SELECT id FROM app.forum_posts LIMIT 1"
        ).fetchone()[0]

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO app.llm_jobs
                        (id, kind, subject_post_id, status, queue_name, estimated_duration_ms)
                    VALUES
                        (gen_random_uuid(), 'route_explanation', %s, 'queued', 'llm-fast', 100)
                    """,
                    (real_post_id,),
                )


def test_llm_workers_are_running_and_respond_to_a_celery_ping() -> None:
    # Two separate worker processes, one per queue (llm-worker-fast / llm-worker-slow) — not one
    # worker listening to both — see docs/LLM_FEATURE_PRD.md decision 2 for why: a real test
    # proved Celery/Kombu's Redis transport does not reliably prioritize by -Q argument order.
    redis.Redis.from_url(REDIS_URL).ping()
    app = Celery("llm-stack-test", broker=REDIS_URL)
    try:
        replies = app.control.inspect(timeout=5.0).ping()
    finally:
        app.close()
    assert replies, "no llm worker responded to the Celery health ping"
    assert any("llm-worker-fast" in hostname for hostname in replies)
    assert any("llm-worker-slow" in hostname for hostname in replies)
