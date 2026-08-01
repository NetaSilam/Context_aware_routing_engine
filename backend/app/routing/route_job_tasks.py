from __future__ import annotations

import os
import signal
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import redis
from celery import Celery
from celery.exceptions import Retry
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.corridor_matcher import RouteCandidateGeometry, match_route_candidates
from app.routing.osrm_client import (
    OsrmClient,
    OsrmClientError,
    OsrmNoRoute,
    OsrmTransientError,
)
from app.routing.route_scoring_service import (
    CandidateRouteMeasurement,
    UserScoringContext,
    score_route_candidates,
)

settings = get_settings()
celery_app = Celery("road-risk-worker", broker=str(settings.redis_url))
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.route_worker_concurrency,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    broker_transport_options={
        "visibility_timeout": settings.celery_visibility_timeout_seconds,
    },
)


def _sync_database_url() -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _line_string_wkt(coordinates: list[tuple[float, float]]) -> str:
    return "LINESTRING(" + ",".join(
        f"{longitude} {latitude}" for longitude, latitude in coordinates
    ) + ")"


def _claim_job(job_id: str, lease_token: UUID) -> tuple[Any, ...] | None:
    with psycopg.connect(_sync_database_url()) as connection:
        job = connection.execute(
            """
            UPDATE app.route_jobs
            SET status = 'running', started_at = COALESCE(started_at, now()),
                attempt_count = attempt_count + 1,
                lease_token = %s,
                lease_expires_at = now() + make_interval(secs => %s),
                completed_at = NULL, error_code = NULL, error_message = NULL
            WHERE id = %s
              AND (
                  status IN ('created', 'queued')
                  OR (status = 'running' AND lease_expires_at <= now())
              )
            RETURNING origin_longitude, origin_latitude,
                      destination_longitude, destination_latitude, snapshot
            """,
            (lease_token, settings.route_job_lease_seconds, job_id),
        ).fetchone()
        connection.commit()
    return job


def _seconds_until_reclaim(job_id: str) -> float | None:
    with psycopg.connect(_sync_database_url()) as connection:
        row = connection.execute(
            """
            SELECT status, GREATEST(
                EXTRACT(EPOCH FROM (lease_expires_at - now())), 0
            )
            FROM app.route_jobs WHERE id = %s
            """,
            (job_id,),
        ).fetchone()
    if row is None or row[0] != "running":
        return None
    return float(row[1])


def _release_for_retry(job_id: str, lease_token: UUID) -> None:
    with psycopg.connect(_sync_database_url()) as connection:
        connection.execute(
            """
            UPDATE app.route_jobs
            SET status = 'queued', lease_token = NULL, lease_expires_at = NULL
            WHERE id = %s AND status = 'running' AND lease_token = %s
            """,
            (job_id, lease_token),
        )


def _fail_claimed_job(
    job_id: str, lease_token: UUID, code: str, message: str
) -> None:
    with psycopg.connect(_sync_database_url()) as connection:
        connection.execute(
            """
            UPDATE app.route_jobs
            SET status = 'failed', error_code = %s, error_message = %s,
                completed_at = now(), lease_token = NULL, lease_expires_at = NULL
            WHERE id = %s AND status = 'running' AND lease_token = %s
            """,
            (code, message, job_id, lease_token),
        )


def _exercise_test_worker_loss(snapshot: dict[str, Any], job_id: str) -> None:
    if not settings.testing or not snapshot.get("_test_crash_once"):
        return
    marker = redis.Redis.from_url(str(settings.redis_url))
    if marker.set(f"route-job-test-crashed:{job_id}", "1", nx=True, ex=300):
        # Kill the worker's main process, not only this pool child. Docker then
        # restarts the real worker and Redis redelivers the unacknowledged task.
        os.kill(os.getppid(), signal.SIGKILL)
        os._exit(86)


def _calculate_result(job: tuple[Any, ...]) -> tuple[dict[str, Any], int, int]:
    origin_longitude, origin_latitude, destination_longitude, destination_latitude, snapshot = job
    with OsrmClient(settings) as osrm:
        osrm_result = osrm.request_routes(
            origin_longitude=origin_longitude,
            origin_latitude=origin_latitude,
            destination_longitude=destination_longitude,
            destination_latitude=destination_latitude,
            avoid_highways=snapshot["avoid_highways"],
            avoid_tolls=snapshot["avoid_tolls"],
        )
    if isinstance(osrm_result, OsrmNoRoute):
        raise NoRouteFailure

    matcher_inputs = [
        RouteCandidateGeometry(
            candidate_index=index,
            geometry_wkt=_line_string_wkt(candidate.geometry.coordinates),
            distance_m=candidate.distance,
        )
        for index, candidate in enumerate(osrm_result.candidates)
    ]
    with psycopg.connect(_sync_database_url()) as connection:
        matches = match_route_candidates(
            connection,
            matcher_inputs,
            sample_interval_m=settings.corridor_matcher_sample_interval_m,
            tolerance_m=settings.corridor_matcher_tolerance_m,
            low_coverage_threshold=settings.corridor_matcher_low_coverage_threshold,
        )

    geometry_by_index = {
        index: candidate.geometry.model_dump()
        for index, candidate in enumerate(osrm_result.candidates)
    }
    duration_by_index = {
        index: candidate.duration
        for index, candidate in enumerate(osrm_result.candidates)
    }
    candidates = [
        CandidateRouteMeasurement(
            candidate_index=match.candidate_index,
            distance_m=match.route_distance_m,
            duration_seconds=duration_by_index[match.candidate_index],
            matched_route_length_m=match.matched_route_length_m,
            accident_score=match.accident_score,
            historical_accident_density_per_km=match.historical_accident_density_per_km,
            coverage=match.coverage,
        )
        for match in matches
    ]
    scoring = score_route_candidates(
        candidates,
        UserScoringContext(
            driving_experience=snapshot["driving_experience"],
            vehicle_type=snapshot["vehicle_type"],
            submitted_at=datetime.fromisoformat(snapshot["submitted_at"]),
        ),
        reference_risk_p95=snapshot["reference_risk_p95"],
        risk_data_version=snapshot["risk_data_version"],
        low_coverage_threshold=settings.corridor_matcher_low_coverage_threshold,
    )
    result_candidates = [
        {
            **asdict(candidate),
            "geometry": geometry_by_index[candidate.candidate_index],
        }
        for candidate in scoring.candidates
    ]
    result = {
        "schema_version": "route-result-v1",
        "chosen_index": scoring.chosen_index,
        "risk_choice_available": scoring.risk_choice_available,
        "candidates": result_candidates,
        "safety_weight": scoring.safety_weight,
        "time_weight": scoring.time_weight,
        "safety_factor_contributions": asdict(scoring.safety_factor_contributions),
        "reference_risk_p95": scoring.reference_risk_p95,
        "low_coverage_threshold": scoring.low_coverage_threshold,
        "risk_data_version": scoring.risk_data_version,
        "formula_version": scoring.formula_version,
        "matcher_version": snapshot["matcher_version"],
        "graph_version": snapshot["expected_graph_version"],
        "included_year_start": snapshot["included_year_start"],
        "included_year_end": snapshot["included_year_end"],
        "risk_metric_name": scoring.risk_metric_name,
        "risk_metric_description": scoring.risk_metric_description,
        "time_context": {
            "local_timestamp": scoring.time_context.local_timestamp.isoformat(),
            "period": scoring.time_context.period,
            "rule_version": scoring.time_context.rule_version,
        },
    }
    return result, scoring.chosen_index, len(scoring.candidates)


class NoRouteFailure(Exception):
    pass


@celery_app.task(
    bind=True,
    name="app.routing.route_job_tasks.execute_route_job",
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_route_job(task: Any, job_id: str) -> None:
    lease_token = uuid4()
    try:
        job = _claim_job(job_id, lease_token)
        if job is None:
            reclaim_delay = _seconds_until_reclaim(job_id)
            if reclaim_delay is not None and reclaim_delay > 0:
                raise task.retry(
                    countdown=max(1, int(reclaim_delay) + 1),
                    max_retries=settings.route_job_max_retries,
                )
            return

        snapshot = job[4]
        _exercise_test_worker_loss(snapshot, job_id)
        result, chosen_index, route_count = _calculate_result(job)
        with psycopg.connect(_sync_database_url()) as connection:
            connection.execute(
                """
                UPDATE app.route_jobs
                SET status = 'completed', chosen_index = %s, route_count = %s,
                    result = %s, completed_at = now(), error_code = NULL,
                    error_message = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = %s AND status = 'running' AND lease_token = %s
                """,
                (
                    chosen_index,
                    route_count,
                    Jsonb(result),
                    job_id,
                    lease_token,
                ),
            )
    except Retry:
        raise
    except NoRouteFailure:
        _fail_claimed_job(
            job_id,
            lease_token,
            "no_route",
            "No route was found between the submitted points.",
        )
    except OsrmTransientError as error:
        if task.request.retries >= settings.route_job_max_retries:
            _fail_claimed_job(
                job_id,
                lease_token,
                error.code.value,
                "The routing service remained unavailable after bounded retries.",
            )
            return
        _release_for_retry(job_id, lease_token)
        countdown = min(
            2 ** task.request.retries,
            settings.route_job_retry_backoff_max_seconds,
        )
        raise task.retry(exc=error, countdown=countdown)
    except OsrmClientError as error:
        _fail_claimed_job(
            job_id,
            lease_token,
            error.code.value,
            "The routing service returned an invalid permanent response.",
        )
    except (psycopg.OperationalError, psycopg.InterfaceError) as error:
        if task.request.retries >= settings.route_job_max_retries:
            try:
                _fail_claimed_job(
                    job_id,
                    lease_token,
                    "database_unavailable",
                    "The route database remained unavailable after bounded retries.",
                )
            except psycopg.Error:
                pass
            return
        try:
            _release_for_retry(job_id, lease_token)
        except psycopg.Error:
            pass
        countdown = min(
            2 ** task.request.retries,
            settings.route_job_retry_backoff_max_seconds,
        )
        raise task.retry(exc=error, countdown=countdown)
    except Exception:
        _fail_claimed_job(
            job_id,
            lease_token,
            "route_processing_failed",
            "The route could not be processed.",
        )
