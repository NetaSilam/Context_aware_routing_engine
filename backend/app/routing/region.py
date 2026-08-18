from __future__ import annotations

from fastapi import HTTPException, status

from app.config import Settings


def validate_route_region(
    *, longitude: float, latitude: float, label: str, settings: Settings
) -> None:
    if not (
        settings.route_region_min_longitude <= longitude <= settings.route_region_max_longitude
        and settings.route_region_min_latitude
        <= latitude
        <= settings.route_region_max_latitude
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} is outside the supported route region",
        )
