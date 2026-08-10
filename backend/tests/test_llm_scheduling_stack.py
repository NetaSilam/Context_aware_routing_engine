from __future__ import annotations

import asyncio
import os
import subprocess
import time
from uuid import UUID

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


def _job_status(job_id: UUID) -> str | None:
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT status FROM app.llm_jobs WHERE id = %s", (str(job_id),)
        ).fetchone()
    return row[0] if row else None


def _real_post_id() -> str:
    # Cold-seeded by `initialize` — see test_llm_stack.py for the same expectation. Real triage/
    # dedup_check dispatch (tickets 4/5) needs a subject that actually exists; this test only
    # cares about queue isolation, not classification content, so any seeded post will do.
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute("SELECT id FROM app.forum_posts LIMIT 1").fetchone()
    return str(row[0])


def _spawn_worker(queue: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "celery",
            "-A",
            "app.llm.tasks.celery_app",
            "worker",
            "-Q",
            queue,
            "--concurrency=1",
            "--loglevel=INFO",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_llm_fast_jobs_complete_quickly_despite_a_slow_job_queued_first() -> None:
    # An earlier version of this ticket had one worker process consuming both `-Q
    # llm-fast,llm-slow`, on the assumption that Celery/Kombu's Redis transport drains queues in
    # -Q argument order (fast first). A real run of this exact scenario proved that false: the
    # slow job finished before the fast ones despite being queued after them being impossible —
    # see docs/LLM_FEATURE_PRD.md decision 2. The fix, proven here, is two separate worker
    # processes, one per queue — OS-level isolation, not broker-internal ordering.
    #
    # Once every kind (triage/dedup_check/route_explanation) got real dispatch (tickets 4/5/7),
    # every mock-path LLM call became effectively instant by design (TESTING=true exists so tests
    # run fast) — there is no longer a reliable way to make a "slow" job's real processing time
    # actually take longer than a "fast" job's. So this proves isolation structurally instead of
    # by a wall-clock race: only the llm-fast worker is ever started while asserting the fast jobs
    # complete; the slow job sits in llm-slow with zero consumers, so it is provably untouched —
    # a slow-queued job can never delay a fast-queued one, independent of relative processing time.
    from app.db import get_engine
    from app.llm.service import create_llm_job, enqueue_llm_job

    real_post_id = _real_post_id()

    async def _create_jobs():
        async with get_engine().begin() as connection:
            slow_job = await create_llm_job(
                connection,
                kind="dedup_check",
                subject_post_id=real_post_id,
                input_chars=50,
                candidate_count=60,
            )
            fast_jobs = [
                await create_llm_job(
                    connection, kind="triage", subject_post_id=real_post_id, input_chars=10
                )
                for _ in range(3)
            ]
        return slow_job, fast_jobs

    slow_job, fast_jobs = asyncio.run(_create_jobs())
    assert slow_job["queue_name"] == "llm-slow"
    assert all(job["queue_name"] == "llm-fast" for job in fast_jobs)

    # This service's REDIS_URL (see compose.test.yaml) is a dedicated Redis db that no other
    # worker listens on, so every job below is already sitting in its queue before any consumer
    # exists at all.
    enqueue_llm_job(slow_job)
    for job in fast_jobs:
        enqueue_llm_job(job)

    fast_worker = _spawn_worker("llm-fast")
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if all(_job_status(job["id"]) == "completed" for job in fast_jobs):
                break
            time.sleep(0.1)
        else:
            pytest.fail("fast jobs did not complete in time")

        assert _job_status(slow_job["id"]) == "queued", (
            "the slow job should still be untouched — no worker has ever consumed llm-slow"
        )
    finally:
        fast_worker.terminate()
        fast_worker.wait(timeout=10)

    # Sanity check: the slow job is not broken, just deprioritized — it completes once its own
    # queue actually has a consumer.
    slow_worker = _spawn_worker("llm-slow")
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _job_status(slow_job["id"]) == "completed":
                break
            time.sleep(0.1)
        else:
            pytest.fail("slow job never completed once its own worker was started")
    finally:
        slow_worker.terminate()
        slow_worker.wait(timeout=10)
