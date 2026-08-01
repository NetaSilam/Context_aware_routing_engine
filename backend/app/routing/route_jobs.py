from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from celery import Celery
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import bindparam

from app.auth import get_current_user, require_trusted_origin
from app.config import get_settings
from app.db import get_engine
from app.routing.route_scoring_service import SCORING_FORMULA_VERSION

router = APIRouter(prefix="/api/route-jobs", tags=["route-jobs"])
history_router = APIRouter(prefix="/api/route-history", tags=["route-history"])
logger = logging.getLogger(__name__)

Coordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]
DisplayLabel = Annotated[str, Field(min_length=1, max_length=200)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteJobCreate(StrictRequest):
    origin_longitude: Coordinate
    origin_latitude: Coordinate
    destination_longitude: Coordinate
    destination_latitude: Coordinate
    origin_label: DisplayLabel | None = None
    destination_label: DisplayLabel | None = None

    @model_validator(mode="after")
    def reject_identical_points(self) -> "RouteJobCreate":
        if (
            self.origin_longitude == self.destination_longitude
            and self.origin_latitude == self.destination_latitude
        ):
            raise ValueError("origin and destination must be different")
        return self


class RouteJobAccepted(BaseModel):
    id: UUID
    status: str


class RouteJobStatus(BaseModel):
    id: UUID
    status: str
    origin_longitude: float
    origin_latitude: float
    destination_longitude: float
    destination_latitude: float
    origin_label: str | None
    destination_label: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    failure: dict[str, Any] | None = None
    result: dict[str, Any] | None


class RouteHistorySummary(BaseModel):
    id: UUID
    origin_label: str | None
    destination_label: str | None
    origin_longitude: float
    origin_latitude: float
    destination_longitude: float
    destination_latitude: float
    completed_at: datetime
    chosen_index: int
    route_count: int
    distance_m: float
    duration_seconds: float
    historical_accident_density_per_km: float
    coverage: float
    final_cost: float
    risk_choice_available: bool


class RouteHistoryPage(BaseModel):
    items: list[RouteHistorySummary]
    offset: int
    limit: int
    has_more: bool


def _validate_region(payload: RouteJobCreate) -> None:
    settings = get_settings()
    for name, longitude, latitude in (
        ("origin", payload.origin_longitude, payload.origin_latitude),
        ("destination", payload.destination_longitude, payload.destination_latitude),
    ):
        if not (
            settings.route_region_min_longitude
            <= longitude
            <= settings.route_region_max_longitude
            and settings.route_region_min_latitude
            <= latitude
            <= settings.route_region_max_latitude
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{name} is outside the supported route region",
            )


def _queue_client() -> Celery:
    queue = Celery("road-risk-api", broker=str(get_settings().redis_url))
    queue.conf.broker_connection_timeout = get_settings().route_queue_publish_timeout_seconds
    return queue


def _publish_job(job_id: str) -> None:
    queue = _queue_client()
    try:
        queue.send_task(
            "app.routing.route_job_tasks.execute_route_job",
            args=[job_id],
            retry=False,
        )
    finally:
        queue.close()


async def _mark_published(job_id: UUID) -> None:
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE app.route_jobs
                SET status = 'queued', enqueued_at = now(), completed_at = NULL,
                    error_code = NULL, error_message = NULL
                WHERE id = :id AND status IN ('created', 'enqueue_failed', 'queued')
                """
            ),
            {"id": job_id},
        )


async def _mark_enqueue_failed(job_id: UUID) -> None:
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE app.route_jobs
                SET status = 'enqueue_failed', error_code = 'queue_unavailable',
                    error_message = 'The route worker queue is unavailable.',
                    completed_at = now()
                WHERE id = :id AND status IN ('created', 'enqueue_failed')
                """
            ),
            {"id": job_id},
        )


async def recover_stale_route_jobs() -> None:
    """Republish persisted jobs that a web process failed to enqueue."""
    settings = get_settings()
    try:
        async with get_engine().begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        UPDATE app.route_jobs
                        SET enqueued_at = now()
                        WHERE id IN (
                            SELECT id FROM app.route_jobs
                            WHERE status = 'created'
                              AND created_at <= now() - make_interval(secs => :stale_seconds)
                              AND (
                                  enqueued_at IS NULL
                                  OR enqueued_at <= now() - make_interval(secs => :stale_seconds)
                              )
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING id
                        """
                    ),
                    {"stale_seconds": settings.route_job_stale_created_seconds},
                )
            ).mappings().all()
        for row in rows:
            job_id = row["id"]
            try:
                await asyncio.to_thread(_publish_job, str(job_id))
                await _mark_published(job_id)
            except Exception:
                await _mark_enqueue_failed(job_id)
                logger.warning("Could not republish stale route job", extra={"job_id": str(job_id)})
    except Exception:
        # Recovery must not prevent the API process from serving liveness checks.
        logger.exception("Route job startup recovery failed")


@router.post(
    "",
    response_model=RouteJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_trusted_origin)],
)
async def create_route_job(
    payload: RouteJobCreate,
    user: dict[str, Any] = Depends(get_current_user),
    idempotency_key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    _validate_region(payload)
    settings = get_settings()
    submitted_at = datetime.now(timezone.utc)
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header is required.",
        )
    job_id = uuid4()

    active_version_sql = text(
        """
        SELECT version, reference_risk_p95, included_year_start, included_year_end
        FROM app.risk_data_versions
        WHERE version = (SELECT version FROM app.active_risk_data_version WHERE singleton)
          AND validation_status = 'valid'
        """
    )
    insert_sql = text(
        """
        INSERT INTO app.route_jobs (
            id, user_id, idempotency_key, status,
            origin_longitude, origin_latitude,
            destination_longitude, destination_latitude,
            origin_label, destination_label, snapshot
        ) VALUES (
            :id, :user_id, :idempotency_key, 'created',
            :origin_longitude, :origin_latitude,
            :destination_longitude, :destination_latitude,
            :origin_label, :destination_label, :snapshot
        )
        ON CONFLICT (user_id, idempotency_key) DO NOTHING
        RETURNING id, status, enqueued_at
        """
    ).bindparams(bindparam("snapshot", type_=JSONB))
    try:
        async with get_engine().begin() as connection:
            inserted = (
                await connection.execute(
                    text(
                        """
                        SELECT id, status, enqueued_at
                        FROM app.route_jobs
                        WHERE user_id = :user_id AND idempotency_key = :idempotency_key
                        """
                    ),
                    {"user_id": user["id"], "idempotency_key": idempotency_key},
                )
            ).mappings().first()
            if inserted is None:
                risk_version = (
                    await connection.execute(active_version_sql)
                ).mappings().first()
                if risk_version is None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="No compatible active risk data is available.",
                        headers={"Retry-After": "5"},
                    )
                snapshot = {
                    "driving_experience": user["driving_experience"],
                    "vehicle_type": user["vehicle_type"],
                    "avoid_tolls": user["avoid_tolls"],
                    "avoid_highways": user["avoid_highways"],
                    "submitted_at": submitted_at.isoformat(),
                    "risk_data_version": risk_version["version"],
                    "reference_risk_p95": risk_version["reference_risk_p95"],
                    "included_year_start": risk_version["included_year_start"],
                    "included_year_end": risk_version["included_year_end"],
                    "formula_version": SCORING_FORMULA_VERSION,
                    "matcher_version": settings.corridor_matcher_version,
                    "expected_graph_version": settings.expected_osrm_graph_version,
                }
                inserted = (
                    await connection.execute(
                        insert_sql,
                        {
                            "id": job_id,
                            "user_id": user["id"],
                            "idempotency_key": idempotency_key,
                            **payload.model_dump(),
                            "snapshot": snapshot,
                        },
                    )
                ).mappings().first()
                if inserted is None:
                    inserted = (
                        await connection.execute(
                            text(
                                """
                                SELECT id, status, enqueued_at
                                FROM app.route_jobs
                                WHERE user_id = :user_id
                                  AND idempotency_key = :idempotency_key
                                """
                            ),
                            {"user_id": user["id"], "idempotency_key": idempotency_key},
                        )
                    ).mappings().one()
            job_id = inserted["id"]
            existing_status = inserted["status"]
            stale_queued = (
                existing_status == "queued"
                and inserted["enqueued_at"] is not None
                and (submitted_at - inserted["enqueued_at"]).total_seconds()
                >= settings.route_job_stale_created_seconds
            )
            should_publish = existing_status in {"created", "enqueue_failed"} or stale_queued
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The route job service is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from exc

    if not should_publish:
        public_status = "failed" if existing_status == "enqueue_failed" else existing_status
        return {"id": job_id, "status": public_status}

    try:
        await asyncio.to_thread(_publish_job, str(job_id))
        await _mark_published(job_id)
    except Exception as exc:
        await _mark_enqueue_failed(job_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The route worker queue is unavailable.",
            headers={"Retry-After": "5"},
        ) from exc

    return {"id": job_id, "status": "queued"}


@router.get("/{job_id}", response_model=RouteJobStatus)
async def get_route_job(
    job_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    query = text(
        """
        SELECT id, status, origin_longitude, origin_latitude,
               destination_longitude, destination_latitude,
               origin_label, destination_label, created_at, started_at,
               completed_at, error_code, error_message, result
        FROM app.route_jobs
        WHERE id = :id AND user_id = :user_id
        """
    )
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(query, {"id": job_id, "user_id": user["id"]})
            ).mappings().first()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The route job service is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route job not found.")
    response = dict(row)
    if response["status"] == "enqueue_failed":
        response["status"] = "failed"
    if response["status"] == "created":
        response["status"] = "queued"
    response["failure"] = (
        {
            "code": response["error_code"],
            "message": response["error_message"],
            "retryable": response["error_code"] in {
                "queue_unavailable",
                "osrm_timeout",
                "osrm_connection",
                "osrm_server_error",
                "database_unavailable",
            },
        }
        if response["error_code"]
        else None
    )
    return response


@history_router.get("", response_model=RouteHistoryPage)
async def list_route_history(
    user: dict[str, Any] = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    try:
        async with get_engine().begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT id, origin_label, destination_label,
                               origin_longitude, origin_latitude,
                               destination_longitude, destination_latitude,
                               completed_at, chosen_index, route_count, result
                        FROM app.route_jobs
                        WHERE user_id = :user_id AND status = 'completed'
                        ORDER BY completed_at DESC, id DESC
                        OFFSET :offset LIMIT :fetch_limit
                        """
                    ),
                    {"user_id": user["id"], "offset": offset, "fetch_limit": limit + 1},
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route history is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from exc

    items = []
    for row in rows[:limit]:
        result = row["result"]
        chosen = next(
            candidate
            for candidate in result["candidates"]
            if candidate["candidate_index"] == result["chosen_index"]
        )
        items.append(
            {
                **{key: row[key] for key in (
                    "id", "origin_label", "destination_label", "origin_longitude",
                    "origin_latitude", "destination_longitude", "destination_latitude",
                    "completed_at", "chosen_index", "route_count",
                )},
                "distance_m": chosen["distance_m"],
                "duration_seconds": chosen["duration_seconds"],
                "historical_accident_density_per_km": chosen[
                    "historical_accident_density_per_km"
                ],
                "coverage": chosen["coverage"],
                "final_cost": chosen["final_cost"],
                "risk_choice_available": result["risk_choice_available"],
            }
        )
    return {"items": items, "offset": offset, "limit": limit, "has_more": len(rows) > limit}


async def _owned_completed_history_row(job_id: UUID, user_id: int) -> dict[str, Any]:
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT id, status, origin_longitude, origin_latitude,
                               destination_longitude, destination_latitude,
                               origin_label, destination_label, created_at, started_at,
                               completed_at, error_code, error_message, result
                        FROM app.route_jobs
                        WHERE id = :id AND user_id = :user_id AND status = 'completed'
                        """
                    ),
                    {"id": job_id, "user_id": user_id},
                )
            ).mappings().first()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route history is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route history entry not found.")
    return dict(row)


@history_router.get("/{job_id}", response_model=RouteJobStatus)
async def get_route_history_entry(
    job_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    response = await _owned_completed_history_row(job_id, user["id"])
    response["failure"] = None
    return response


@history_router.post(
    "/{job_id}/run-again",
    response_model=RouteJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_trusted_origin)],
)
async def run_route_history_again(
    job_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
    idempotency_key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    saved = await _owned_completed_history_row(job_id, user["id"])
    payload = RouteJobCreate(
        origin_longitude=saved["origin_longitude"],
        origin_latitude=saved["origin_latitude"],
        destination_longitude=saved["destination_longitude"],
        destination_latitude=saved["destination_latitude"],
        origin_label=saved["origin_label"],
        destination_label=saved["destination_label"],
    )
    return await create_route_job(payload, user, idempotency_key)


@history_router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def delete_route_history_entry(
    job_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    try:
        async with get_engine().begin() as connection:
            deleted = await connection.execute(
                text(
                    """
                    DELETE FROM app.route_jobs
                    WHERE id = :id AND user_id = :user_id AND status = 'completed'
                    """
                ),
                {"id": job_id, "user_id": user["id"]},
            )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route history is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from exc
    if deleted.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route history entry not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@history_router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def clear_route_history(
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    try:
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM app.route_jobs WHERE user_id = :user_id AND status = 'completed'"
                ),
                {"user_id": user["id"]},
            )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route history is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
