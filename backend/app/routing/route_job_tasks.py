from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

import psycopg
from celery import Celery
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.corridor_matcher import RouteCandidateGeometry, match_route_candidates
from app.routing.osrm_client import OsrmClient, OsrmNoRoute
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
)


def _sync_database_url() -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _line_string_wkt(coordinates: list[tuple[float, float]]) -> str:
    return "LINESTRING(" + ",".join(f"{longitude} {latitude}" for longitude, latitude in coordinates) + ")"


def _fail_job(job_id: str, code: str, message: str) -> None:
    with psycopg.connect(_sync_database_url()) as connection:
        connection.execute(
            """
            UPDATE app.route_jobs
            SET status = 'failed', error_code = %s, error_message = %s,
                completed_at = now()
            WHERE id = %s AND status <> 'completed'
            """,
            (code, message, job_id),
        )


@celery_app.task(name="app.routing.route_job_tasks.execute_route_job")
def execute_route_job(job_id: str) -> None:
    try:
        with psycopg.connect(_sync_database_url()) as connection:
            job = connection.execute(
                """
                UPDATE app.route_jobs
                SET status = 'running', started_at = now()
                WHERE id = %s AND status = 'queued'
                RETURNING origin_longitude, origin_latitude,
                          destination_longitude, destination_latitude, snapshot
                """,
                (job_id,),
            ).fetchone()
            connection.commit()
        if job is None:
            return

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
            _fail_job(job_id, "no_route", "No route was found between the submitted points.")
            return

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

        candidates = []
        geometry_by_index: dict[int, dict[str, Any]] = {}
        duration_by_index: dict[int, float] = {}
        for index, osrm_candidate in enumerate(osrm_result.candidates):
            geometry_by_index[index] = osrm_candidate.geometry.model_dump()
            duration_by_index[index] = osrm_candidate.duration
        for match in matches:
            candidates.append(
                CandidateRouteMeasurement(
                    candidate_index=match.candidate_index,
                    distance_m=match.route_distance_m,
                    duration_seconds=duration_by_index[match.candidate_index],
                    matched_route_length_m=match.matched_route_length_m,
                    accident_score=match.accident_score,
                    historical_accident_density_per_km=match.historical_accident_density_per_km,
                    coverage=match.coverage,
                )
            )
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
        result_candidates = []
        for candidate in scoring.candidates:
            result_candidates.append({**asdict(candidate), "geometry": geometry_by_index[candidate.candidate_index]})
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
        with psycopg.connect(_sync_database_url()) as connection:
            connection.execute(
                """
                UPDATE app.route_jobs
                SET status = 'completed', chosen_index = %s, route_count = %s,
                    result = %s, completed_at = now(), error_code = NULL,
                    error_message = NULL
                WHERE id = %s AND status = 'running'
                """,
                (scoring.chosen_index, len(scoring.candidates), Jsonb(result), job_id),
            )
    except Exception as error:
        _fail_job(job_id, "route_processing_failed", "The route could not be processed.")
        raise error
