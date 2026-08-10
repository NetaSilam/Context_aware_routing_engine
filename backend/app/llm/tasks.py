from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

import psycopg
from celery import Celery
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.initialize_foundation import synchronous_database_url
from app.llm.client import classify_report, compare_for_duplicate
from app.llm.scheduling import choose_queue, estimate_duration_ms

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


def _find_dedup_candidates(
    connection: psycopg.Connection,
    *,
    subject_post_id: str,
    hazard_type: str,
    longitude: float,
    latitude: float,
) -> list[tuple[str, str]]:
    """Other active posts of the same hazard type, recent and nearby. No PostGIS geometry column
    exists on forum_posts (plain lon/lat floats — see PRD decision 5), so the point-radius search
    is computed on the fly via a geography cast rather than a stored/indexed geometry, consistent
    with this project's general PostGIS usage (extension already enabled) without widening the
    forum schema for a single feature."""
    rows = connection.execute(
        """
        SELECT id, body FROM app.forum_posts
        WHERE status = 'active' AND hazard_type = %s AND id != %s
          AND longitude IS NOT NULL AND latitude IS NOT NULL
          AND created_at >= now() - (%s || ' days')::interval
          AND ST_DWithin(
                ST_MakePoint(longitude, latitude)::geography,
                ST_MakePoint(%s, %s)::geography,
                %s
              )
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (
            hazard_type,
            subject_post_id,
            settings.llm_dedup_lookback_days,
            longitude,
            latitude,
            settings.llm_dedup_radius_meters,
            settings.llm_dedup_candidate_limit,
        ),
    ).fetchall()
    return [(str(candidate_id), body) for candidate_id, body in rows]


def _enqueue_dedup_check_if_applicable(
    connection: psycopg.Connection, subject_post_id: str
) -> None:
    """Called after a successful triage. Fail-open by design (bare except at the call site,
    like the enqueue step in forum/routes.py's create_post): a problem here must never turn an
    already-completed triage job into a failure — dedup is enrichment on top of enrichment."""
    row = connection.execute(
        "SELECT body, hazard_type, longitude, latitude FROM app.forum_posts WHERE id = %s",
        (subject_post_id,),
    ).fetchone()
    if row is None:
        return
    body, hazard_type, longitude, latitude = row
    if longitude is None or latitude is None:
        return  # PRD decision 5: no coordinates, nothing to compare against — skip entirely.
    candidates = _find_dedup_candidates(
        connection,
        subject_post_id=subject_post_id,
        hazard_type=hazard_type,
        longitude=longitude,
        latitude=latitude,
    )
    if not candidates:
        return
    estimated = estimate_duration_ms("dedup_check", len(body), len(candidates))
    queue_name = choose_queue(estimated, settings.llm_fast_queue_max_estimated_ms)
    job_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.llm_jobs
            (id, kind, subject_post_id, status, queue_name, estimated_duration_ms)
        VALUES
            (%s, 'dedup_check', %s, 'queued', %s, %s)
        """,
        (job_id, subject_post_id, queue_name, estimated),
    )
    connection.commit()
    run_llm_job.apply_async(args=[str(job_id)], queue=queue_name)


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


def _run_dedup_check(connection: psycopg.Connection, subject_post_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT body, hazard_type, longitude, latitude FROM app.forum_posts WHERE id = %s",
        (subject_post_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"forum post {subject_post_id} no longer exists")
    body, hazard_type, longitude, latitude = row
    if longitude is None or latitude is None:
        return {"is_duplicate": False, "candidates_checked": 0}
    candidates = _find_dedup_candidates(
        connection,
        subject_post_id=subject_post_id,
        hazard_type=hazard_type,
        longitude=longitude,
        latitude=latitude,
    )
    for candidate_id, candidate_body in candidates:
        judgment = asyncio.run(compare_for_duplicate(body, candidate_body))
        if judgment.is_duplicate:
            connection.execute(
                "UPDATE app.forum_posts SET duplicate_of_post_id = %s WHERE id = %s",
                (candidate_id, subject_post_id),
            )
            return {
                "is_duplicate": True,
                "duplicate_of_post_id": candidate_id,
                "candidates_checked": len(candidates),
            }
    return {"is_duplicate": False, "candidates_checked": len(candidates)}


def _run_placeholder(estimated_duration_ms: int) -> dict[str, Any]:
    # route_explanation (ticket 7) is not dispatched to app/llm/client.py yet — see
    # docs/llm-feature-tickets.md ticket 3's status for why this placeholder (proportional
    # sleep, fixed result) is a deliberate, temporary stand-in that already proves the
    # scheduling/queueing behavior that ticket will reuse unchanged.
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
            try:
                with _connect() as connection:
                    _enqueue_dedup_check_if_applicable(connection, subject_post_id)
            except Exception:
                pass
        elif kind == "dedup_check":
            with _connect() as connection:
                result = _run_dedup_check(connection, subject_post_id)
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
