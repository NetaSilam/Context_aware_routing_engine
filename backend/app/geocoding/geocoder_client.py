from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.config import Settings, get_settings


class GeocoderError(Exception):
    """A controlled upstream geocoder failure."""


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str
    lon: float
    lat: float

    @field_validator("lon", "lat")
    @classmethod
    def finite_coordinate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinate must be finite")
        return value


@dataclass(frozen=True)
class AddressMatch:
    label: str
    longitude: float
    latitude: float


def parse_provider_results(payload: Any, settings: Settings) -> list[AddressMatch]:
    if not isinstance(payload, list):
        raise GeocoderError("The address provider returned an invalid response.")

    matches: list[AddressMatch] = []
    try:
        for item in payload:
            result = ProviderResult.model_validate(item)
            if not (
                settings.route_region_min_longitude
                <= result.lon
                <= settings.route_region_max_longitude
                and settings.route_region_min_latitude
                <= result.lat
                <= settings.route_region_max_latitude
            ):
                continue
            label = " ".join(result.display_name.split())[:200]
            if not label:
                continue
            matches.append(
                AddressMatch(
                    label=label,
                    longitude=result.lon,
                    latitude=result.lat,
                )
            )
    except ValidationError as exc:
        raise GeocoderError("The address provider returned an invalid response.") from exc
    return matches[: settings.geocoder_result_limit]


async def search_provider(query: str) -> list[AddressMatch]:
    settings = get_settings()
    timeout = httpx.Timeout(
        connect=settings.geocoder_connect_timeout_seconds,
        read=settings.geocoder_response_timeout_seconds,
        write=settings.geocoder_response_timeout_seconds,
        pool=settings.geocoder_connect_timeout_seconds,
    )
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(settings.geocoder_result_limit),
        "countrycodes": "il",
        "bounded": "1",
        "viewbox": (
            f"{settings.route_region_min_longitude},"
            f"{settings.route_region_max_latitude},"
            f"{settings.route_region_max_longitude},"
            f"{settings.route_region_min_latitude}"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                str(settings.geocoder_base_url),
                params=params,
                headers={"User-Agent": settings.geocoder_user_agent},
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocoderError("Address search is temporarily unavailable.") from exc
    return parse_provider_results(payload, settings)
