from __future__ import annotations

import asyncio
import time
from typing import Any

import psycopg
from celery import Celery
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.initialize_foundation import synchronous_database_url
from app.llm.client import classify_report

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


def _connect() -> psycopg.Connection:
    return psycopg.connect(synchronous_database_url(settings.database_url))


def _run_triage(connection: psycopg.Connection, subject_post_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT body, hazard_type, longitude, latitude FROM app.forum_posts WHERE id = %s",
        (subject_post_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"forum post {subject_post_id} no longer exists")
    body, hazard_type, longitude, latitude = row
    coordinates = None if longitude is None or latitude is None else (longitude, latitude)
    result = asyncio.run(classify_report(body, hazard_type, coordinates))
    connection.execute(
        """
        UPDATE app.forum_posts
        SET llm_hazard_type_suggested = %s, llm_severity = %s
        WHERE id = %s
        """,
        (result.hazard_type_suggested, result.severity, subject_post_id),
    )
    return {"hazard_type_suggested": result.hazard_type_suggested, "severity": result.severity}


def _run_placeholder(estimated_duration_ms: int) -> dict[str, Any]:
    # dedup_check (ticket 5) and route_explanation (ticket 7) are not dispatched to
    # app/llm/client.py yet — see docs/llm-feature-tickets.md ticket 3's status for why this
    # placeholder (proportional sleep, fixed result) is a deliberate, temporary stand-in that
    # already proves the scheduling/queueing behavior those tickets will reuse unchanged.
    time.sleep(estimated_duration_ms / 1000)
    return {"placeholder": True}


@celery_app.task(
    name="app.llm.tasks.run_llm_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_llm_job(task, job_id: str) -> None:
    with _connect() as connection:
        row = connection.execute(
            """
            UPDATE app.llm_jobs SET status = 'running'
            WHERE id = %s AND status = 'queued'
            RETURNING kind, subject_post_id, estimated_duration_ms
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return
        kind, subject_post_id, estimated_duration_ms = row

    try:
        if kind == "triage":
            with _connect() as connection:
                result = _run_triage(connection, subject_post_id)
        else:
            result = _run_placeholder(estimated_duration_ms)
    except Exception as exc:
        # Fail-open (PRD decision 6): classification is enrichment, not load-bearing. The
        # subject (forum post / route job) is left exactly as it was — visible and fully
        # functional, just unclassified. Only the job bookkeeping records the failure.
        with _connect() as connection:
            connection.execute(
                """
                UPDATE app.llm_jobs SET status = 'failed', error = %s, completed_at = now()
                WHERE id = %s AND status = 'running'
                """,
                (str(exc)[:2000], job_id),
            )
        return

    with _connect() as connection:
        connection.execute(
            """
            UPDATE app.llm_jobs
            SET status = 'completed', result = %s, completed_at = now()
            WHERE id = %s AND status = 'running'
            """,
            (Jsonb(result), job_id),
        )
