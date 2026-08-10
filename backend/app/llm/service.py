from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

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
    committed — importing tasks here (not at module scope) avoids a needless celery_app
    construction for callers, like FastAPI request handlers, that only ever call create_llm_job
    in tests with a mocked enqueue step."""
    from app.llm.tasks import run_llm_job

    run_llm_job.apply_async(args=[str(job["id"])], queue=job["queue_name"])
