from __future__ import annotations

import time

import psycopg
from celery import Celery
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.initialize_foundation import synchronous_database_url

settings = get_settings()
celery_app = Celery("road-risk-llm-worker", broker=str(settings.redis_url))
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.llm_worker_concurrency,
    worker_hijack_root_logger=False,
)


@celery_app.task(
    name="app.llm.tasks.run_llm_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_llm_job(task, job_id: str) -> None:
    # Placeholder body: proves the fast/slow queue scheduling this ticket delivers actually
    # affects real wall-clock completion order (sleeping proportional to the pre-computed
    # estimate makes that observable), without yet depending on tickets 4/5/7's real per-kind
    # dispatch to app/llm/client.py — those tickets replace the sleep+placeholder-result body
    # below with real classify_report/compare_for_duplicate/explain_route calls, but do not
    # change how a job gets created, estimated, or routed to a queue.
    with psycopg.connect(synchronous_database_url(settings.database_url)) as connection:
        row = connection.execute(
            """
            UPDATE app.llm_jobs SET status = 'running'
            WHERE id = %s AND status = 'queued'
            RETURNING estimated_duration_ms
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return
        estimated_duration_ms = row[0]

    time.sleep(estimated_duration_ms / 1000)

    with psycopg.connect(synchronous_database_url(settings.database_url)) as connection:
        connection.execute(
            """
            UPDATE app.llm_jobs
            SET status = 'completed', result = %s, completed_at = now()
            WHERE id = %s AND status = 'running'
            """,
            (Jsonb({"placeholder": True}), job_id),
        )
