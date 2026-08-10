from __future__ import annotations

import asyncio
import os
import time

import psycopg
import pytest

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


def _real_post() -> tuple[str, str]:
    # Cold-seeded by `initialize` — see test_llm_stack.py/test_llm_scheduling_stack.py for the
    # same expectation. Real triage/dedup_check dispatch needs a subject that actually exists.
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT id, hazard_type FROM app.forum_posts LIMIT 1"
        ).fetchone()
    return str(row[0]), row[1]


def _job_row(job_id) -> tuple[str, dict] | None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT status, result FROM app.llm_jobs WHERE id = %s", (str(job_id),)
        ).fetchone()
    return row


def _wait_for_job(job_id, *, deadline_seconds: float = 15) -> tuple[str, dict]:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        row = _job_row(job_id)
        if row is not None and row[0] in {"completed", "failed"}:
            return row
        time.sleep(0.2)
    pytest.fail(f"job {job_id} did not reach a terminal state in time")


def test_the_shared_llm_fast_and_slow_workers_both_run_with_testing_enabled() -> None:
    # Explicit, dedicated regression guard for PRD Testing Decision 5/7 (ticket 9): if TESTING
    # were ever accidentally dropped from llm-worker-fast/llm-worker-slow's Compose environment,
    # a real network call would either fail outright (no real GEMINI_API_KEY is configured for
    # these services under a normal `--env-file .env.test` run) or, if a key leaked in via the
    # calling shell's own environment (Compose's `${GEMINI_API_KEY:-}` reads the shell before
    # falling back), produce a non-deterministic real classification instead of these exact
    # canned/derived values. Ticket 4/5/7's own functional tests already prove this incidentally,
    # as a side effect of testing their own feature — but only for llm-fast, since none of their
    # fixtures are large enough to cross the fast-queue threshold. This test exists specifically
    # to make the invariant explicit and to additionally exercise the shared llm-worker-slow,
    # which nothing else in the suite does (test_llm_scheduling_stack.py proves queue isolation
    # with its own short-lived spawned workers, not the standing shared ones).
    from app.db import get_engine
    from app.llm.service import create_llm_job, enqueue_llm_job

    real_post_id, real_hazard_type = _real_post()

    async def _create_jobs():
        async with get_engine().begin() as connection:
            fast_job = await create_llm_job(
                connection, kind="triage", subject_post_id=real_post_id, input_chars=10
            )
            slow_job = await create_llm_job(
                connection,
                kind="dedup_check",
                subject_post_id=real_post_id,
                input_chars=50,
                candidate_count=60,
            )
        return fast_job, slow_job

    fast_job, slow_job = asyncio.run(_create_jobs())
    assert fast_job["queue_name"] == "llm-fast"
    assert slow_job["queue_name"] == "llm-slow"

    enqueue_llm_job(fast_job)
    enqueue_llm_job(slow_job)

    fast_status, fast_result = _wait_for_job(fast_job["id"])
    slow_status, slow_result = _wait_for_job(slow_job["id"])

    assert fast_status == "completed", fast_result
    assert fast_result["hazard_type_suggested"] == real_hazard_type
    assert fast_result["severity"] == "medium"

    assert slow_status == "completed", slow_result
    assert isinstance(slow_result["is_duplicate"], bool)
    assert isinstance(slow_result["candidates_checked"], int)
