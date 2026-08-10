from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from celery import Celery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import get_settings
from app.llm.scheduling import Kind, choose_queue, estimate_duration_ms


async def create_llm_job(
    connection: AsyncConnection,
    *,
    kind: Kind,
    subject_post_id: UUID | None = None,
    subject_route_job_id: UUID | None = None,
    input_chars: int,
    candidate_count: int = 0,
) -> dict[str, Any]:
    """Insert a queued app.llm_jobs row. Call enqueue_llm_job(...) with the result after the
    transaction that created it has committed, mirroring notifications/service.py's
    create_notification/publish_notification split."""
    settings = get_settings()
    estimated_duration_ms = estimate_duration_ms(kind, input_chars, candidate_count)
    queue_name = choose_queue(estimated_duration_ms, settings.llm_fast_queue_max_estimated_ms)
    row = (
        await connection.execute(
            text(
                """
                INSERT INTO app.llm_jobs
                    (id, kind, subject_post_id, subject_route_job_id, status, queue_name,
                     estimated_duration_ms)
                VALUES
                    (:id, :kind, :subject_post_id, :subject_route_job_id, 'queued', :queue_name,
                     :estimated_duration_ms)
                RETURNING id, kind, queue_name, estimated_duration_ms
                """
            ),
            {
                "id": uuid4(),
                "kind": kind,
                "subject_post_id": subject_post_id,
                "subject_route_job_id": subject_route_job_id,
                "queue_name": queue_name,
                "estimated_duration_ms": estimated_duration_ms,
            },
        )
    ).mappings().one()
    return dict(row)


def enqueue_llm_job(job: dict[str, Any]) -> None:
    """Dispatch the Celery task for a job created by create_llm_job, after its transaction has
    committed. Builds a fresh, lightweight client per call and sends by task name — mirroring
    app/routing/route_jobs.py's _queue_client()/_publish_job() — rather than importing and reusing
    app.llm.tasks.celery_app's persistent module-level app. This matters for real correctness, not
    just import-cost avoidance: a caller with its own isolated Redis db for rate limiting/capacity
    (e.g. stress-api, abuse-api — see LLM_QUEUE_BROKER_URL in compose.test.yaml) still needs its
    enqueued jobs to land on the *shared* llm-fast/llm-slow broker where llm-worker-fast/slow
    actually listen, not silently orphaned on its own isolated db. A real run against stress-api
    proved the orphaning: forum posts it created enqueued llm_jobs rows that stayed 'queued'
    forever, since no worker was ever listening on that db."""
    settings = get_settings()
    broker_url = settings.llm_queue_broker_url or settings.redis_url
    queue = Celery("road-risk-api", broker=str(broker_url))
    queue.conf.broker_connection_timeout = settings.llm_queue_publish_timeout_seconds
    try:
        queue.send_task(
            "app.llm.tasks.run_llm_job", args=[str(job["id"])], queue=job["queue_name"]
        )
    finally:
        queue.close()
