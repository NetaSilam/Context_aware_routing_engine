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


def test_llm_jobs_kind_and_subject_are_consistent() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO app.llm_jobs
                        (id, kind, status, queue_name, estimated_duration_ms)
                    VALUES
                        (gen_random_uuid(), 'triage', 'queued', 'llm-fast', 100)
                    """
                )


def test_llm_worker_is_running_and_responds_to_a_celery_ping() -> None:
    redis.Redis.from_url(REDIS_URL).ping()
    app = Celery("llm-stack-test", broker=REDIS_URL)
    try:
        replies = app.control.inspect(timeout=5.0).ping()
    finally:
        app.close()
    assert replies, "no llm worker responded to the Celery health ping"
    assert any("llm-worker" in hostname for hostname in replies)
