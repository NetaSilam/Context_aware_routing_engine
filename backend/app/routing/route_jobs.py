from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import bindparam

from app.auth import get_current_user, require_trusted_origin
from app.config import get_settings
from app.db import get_engine
from app.routing.route_scoring_service import SCORING_FORMULA_VERSION

router = APIRouter(prefix="/api/route-jobs", tags=["route-jobs"])

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
    result: dict[str, Any] | None


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
    return Celery("road-risk-api", broker=str(get_settings().redis_url))


def _publish_job(job_id: str) -> None:
    queue = _queue_client()
    try:
        queue.send_task("app.routing.route_job_tasks.execute_route_job", args=[job_id])
    finally:
        queue.close()


@router.post(
    "",
    response_model=RouteJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_trusted_origin)],
)
async def create_route_job(
    payload: RouteJobCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _validate_region(payload)
    settings = get_settings()
    submitted_at = datetime.now(timezone.utc)
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
            id, user_id, status,
            origin_longitude, origin_latitude,
            destination_longitude, destination_latitude,
            origin_label, destination_label, snapshot
        ) VALUES (
            :id, :user_id, 'queued',
            :origin_longitude, :origin_latitude,
            :destination_longitude, :destination_latitude,
            :origin_label, :destination_label, :snapshot
        )
        """
    ).bindparams(bindparam("snapshot", type_=JSONB))
    async with get_engine().begin() as connection:
        risk_version = (await connection.execute(active_version_sql)).mappings().first()
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
        await connection.execute(
            insert_sql,
            {
                "id": job_id,
                "user_id": user["id"],
                **payload.model_dump(),
                "snapshot": snapshot,
            },
        )

    try:
        await asyncio.to_thread(_publish_job, str(job_id))
    except Exception as exc:
        # Ticket 9 adds republishing and idempotency. For this slice, preserve the
        # accepted row and expose a controlled queue failure.
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE app.route_jobs
                    SET status = 'failed', error_code = 'queue_unavailable',
                        error_message = 'The route worker queue is unavailable.',
                        completed_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": job_id},
            )
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
    async with get_engine().begin() as connection:
        row = (
            await connection.execute(query, {"id": job_id, "user_id": user["id"]})
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route job not found.")
    return dict(row)
