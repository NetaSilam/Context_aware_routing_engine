from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from app.abuse_protection import enforce_action_rate_limit
from app.auth import get_current_user, require_trusted_origin
from app.config import Settings, get_settings
from app.corridor_matcher import RouteCandidateGeometry, match_route_candidates
from app.operations import log_route_event, operations_metrics
from app.request_bounds import reject_unexpected_query_parameters
from app.routing.osrm_client import (
    OsrmClient,
    OsrmClientError,
    OsrmNoRoute,
    OsrmTransientError,
)
from app.routing.region import validate_route_region
from app.routing.route_scoring_service import (
    CandidateRouteMeasurement,
    DrivingExperience,
    UserScoringContext,
    VehicleType,
    score_route_candidates,
)

router = APIRouter(prefix="/api/routing", tags=["routing"])

Coordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RerouteScoringContext(StrictRequest):
    """The original route job's snapshot, so a reroute is scored with the same
    weighting the driver already chose to trust — not recomputed defaults."""

    driving_experience: DrivingExperience
    vehicle_type: VehicleType
    avoid_tolls: bool
    avoid_highways: bool
    reference_risk_p95: float = Field(gt=0, allow_inf_nan=False)
    risk_data_version: str = Field(min_length=1, max_length=100)


class RerouteRequest(StrictRequest):
    current_longitude: Coordinate
    current_latitude: Coordinate
    destination_longitude: Coordinate
    destination_latitude: Coordinate
    scoring_context: RerouteScoringContext


RETRYABLE_OSRM_ERROR_CODES = {"osrm_timeout", "osrm_connection", "osrm_server_error"}


def _sync_database_url(settings: Settings) -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _line_string_wkt(coordinates: list[tuple[float, float]]) -> str:
    return "LINESTRING(" + ",".join(
        f"{longitude} {latitude}" for longitude, latitude in coordinates
    ) + ")"


def _typed_unavailable(error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error_code": error_code, "message": message, "retryable": True},
        headers={"Retry-After": "3"},
    )


def _request_osrm_routes_with_retry(
    settings: Settings,
    *,
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
    avoid_highways: bool,
    avoid_tolls: bool,
):
    started = time.monotonic()
    last_transient_error: OsrmTransientError | None = None
    for attempt in range(2):
        # Skip the retry once the overall reroute budget is spent, so a slow first
        # attempt can't be doubled by a second full-length one under load.
        if attempt > 0 and time.monotonic() - started >= settings.route_reroute_retry_timeout_seconds:
            break
        try:
            with OsrmClient(settings) as osrm:
                return osrm.request_routes(
                    origin_longitude=origin_longitude,
                    origin_latitude=origin_latitude,
                    destination_longitude=destination_longitude,
                    destination_latitude=destination_latitude,
                    avoid_highways=avoid_highways,
                    avoid_tolls=avoid_tolls,
                )
        except OsrmTransientError as error:
            last_transient_error = error
            continue
    assert last_transient_error is not None
    raise last_transient_error


_db_pool: ConnectionPool | None = None


def _get_db_pool(settings: Settings) -> ConnectionPool:
    # Lazily built and reused across requests instead of opening a fresh connection
    # per reroute, which under concurrent load added connection-setup latency to every
    # request and pushed Postgres toward its max-connections ceiling faster than needed.
    global _db_pool
    if _db_pool is None:
        _db_pool = ConnectionPool(
            _sync_database_url(settings),
            min_size=settings.route_reroute_db_pool_min_size,
            max_size=settings.route_reroute_db_pool_max_size,
            open=True,
        )
    return _db_pool


def _match_route_candidates_with_retry(
    settings: Settings, matcher_inputs: list[RouteCandidateGeometry]
):
    last_db_error: Exception | None = None
    for _ in range(2):
        try:
            with _get_db_pool(settings).connection() as connection:
                return match_route_candidates(
                    connection,
                    matcher_inputs,
                    sample_interval_m=settings.corridor_matcher_sample_interval_m,
                    tolerance_m=settings.corridor_matcher_tolerance_m,
                    low_coverage_threshold=settings.corridor_matcher_low_coverage_threshold,
                )
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            last_db_error = error
            continue
    assert last_db_error is not None
    raise last_db_error


def _compute_reroute(payload: RerouteRequest) -> dict[str, Any]:
    settings = get_settings()
    started = time.monotonic()

    try:
        osrm_result = _request_osrm_routes_with_retry(
            settings,
            origin_longitude=payload.current_longitude,
            origin_latitude=payload.current_latitude,
            destination_longitude=payload.destination_longitude,
            destination_latitude=payload.destination_latitude,
            avoid_highways=payload.scoring_context.avoid_highways,
            avoid_tolls=payload.scoring_context.avoid_tolls,
        )
    except OsrmTransientError as error:
        operations_metrics.record_upstream_failure()
        log_route_event(
            "reroute_upstream_failure", stage="osrm",
            duration_ms=(time.monotonic() - started) * 1000,
            error_code=error.code.value, level=30,
        )
        raise _typed_unavailable(
            error.code.value, "The routing service remained unavailable after a retry."
        ) from error
    except OsrmClientError as error:
        operations_metrics.record_upstream_failure()
        log_route_event(
            "reroute_upstream_failure", stage="osrm",
            duration_ms=(time.monotonic() - started) * 1000,
            error_code=error.code.value, level=30,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": error.code.value,
                "message": "The routing service returned an invalid response.",
                "retryable": False,
            },
        ) from error

    if isinstance(osrm_result, OsrmNoRoute):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "no_route",
                "message": "No route was found from the current position.",
                "retryable": False,
            },
        )

    matcher_inputs = [
        RouteCandidateGeometry(
            candidate_index=index,
            geometry_wkt=_line_string_wkt(candidate.geometry.coordinates),
            distance_m=candidate.distance,
        )
        for index, candidate in enumerate(osrm_result.candidates)
    ]
    try:
        matches = _match_route_candidates_with_retry(settings, matcher_inputs)
    except (psycopg.OperationalError, psycopg.InterfaceError) as error:
        log_route_event(
            "reroute_upstream_failure", stage="database",
            duration_ms=(time.monotonic() - started) * 1000,
            error_code="database_unavailable", level=30,
        )
        raise _typed_unavailable(
            "database_unavailable", "The route database remained unavailable after a retry."
        ) from error

    geometry_by_index = {
        index: candidate.geometry.model_dump()
        for index, candidate in enumerate(osrm_result.candidates)
    }
    duration_by_index = {
        index: candidate.duration for index, candidate in enumerate(osrm_result.candidates)
    }
    steps_by_index = {
        index: [step.model_dump() for step in candidate.steps]
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
            driving_experience=payload.scoring_context.driving_experience,
            vehicle_type=payload.scoring_context.vehicle_type,
            submitted_at=datetime.now(timezone.utc),
        ),
        reference_risk_p95=payload.scoring_context.reference_risk_p95,
        risk_data_version=payload.scoring_context.risk_data_version,
        low_coverage_threshold=settings.corridor_matcher_low_coverage_threshold,
    )
    result_candidates = [
        {
            **asdict(candidate),
            "geometry": geometry_by_index[candidate.candidate_index],
            "steps": steps_by_index[candidate.candidate_index],
        }
        for candidate in scoring.candidates
    ]
    log_route_event(
        "reroute_completed", stage="scored",
        duration_ms=(time.monotonic() - started) * 1000,
    )
    return {
        "schema_version": "reroute-result-v1",
        "chosen_index": scoring.chosen_index,
        "risk_choice_available": scoring.risk_choice_available,
        "candidates": result_candidates,
        "safety_weight": scoring.safety_weight,
        "time_weight": scoring.time_weight,
        "formula_version": scoring.formula_version,
        "risk_data_version": scoring.risk_data_version,
    }


@router.post("/reroute", dependencies=[Depends(require_trusted_origin)])
async def reroute(
    payload: RerouteRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, set())
    settings = get_settings()
    validate_route_region(
        longitude=payload.current_longitude,
        latitude=payload.current_latitude,
        label="current position",
        settings=settings,
    )
    validate_route_region(
        longitude=payload.destination_longitude,
        latitude=payload.destination_latitude,
        label="destination",
        settings=settings,
    )
    await enforce_action_rate_limit(
        "route-reroute",
        request,
        int(user["id"]),
        user_limit=settings.route_reroute_user_rate_limit,
        ip_limit=settings.route_reroute_ip_rate_limit,
    )
    return await asyncio.to_thread(_compute_reroute, payload)
