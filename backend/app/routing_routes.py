from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import get_current_user
from app.db import get_engine

router = APIRouter(tags=["routing"])

ISRAEL_UTC_OFFSET = timedelta(hours=3)  # good enough for "day vs night", not full tz handling
ROUTE_RISK_BUFFER_M = 30  # how far from the route geometry an accident still "counts"


def _osrm_base_url() -> str:
    return os.environ.get("OSRM_BASE_URL", "http://osrm:5000")


def _nominatim_base_url() -> str:
    # Defaults to the public Nominatim instance rather than a self-hosted one: importing
    # Israel/Palestine into self-hosted Nominatim needs several GB of free RAM for the
    # indexing phase, which this dev machine doesn't reliably have alongside the rest of
    # the stack (see PROJECT_REQUIREMENTS.md). Self-host on a bigger machine (e.g. the
    # course's Azure VM) by setting NOMINATIM_BASE_URL to that instance instead.
    return os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")


class GeocodeResult(BaseModel):
    label: str
    lat: float
    lon: float


@router.get("/api/geocode")
def geocode(q: str) -> dict[str, Any]:
    url = f"{_nominatim_base_url()}/search"
    params = {
        "q": q,
        "format": "jsonv2",
        "countrycodes": "il",
        "accept-language": "he",
        "limit": 5,
    }
    # Required by Nominatim's usage policy when hitting the public instance:
    # https://operations.osmfoundation.org/policies/nominatim/
    headers = {"User-Agent": "context-aware-safe-routing-engine (course project)"}
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Geocoding service unavailable: {exc}") from exc

    results = [
        GeocodeResult(label=item["display_name"], lat=float(item["lat"]), lon=float(item["lon"]))
        for item in response.json()
    ]
    return {"query": q, "results": [r.model_dump() for r in results]}


class Coordinate(BaseModel):
    lat: float
    lon: float


class RouteRequest(BaseModel):
    origin: Coordinate
    destination: Coordinate
    time_of_day: Literal["day", "night"] | None = None


def _infer_time_of_day() -> Literal["day", "night"]:
    local_hour = (datetime.now(timezone.utc) + ISRAEL_UTC_OFFSET).hour
    return "day" if 6 <= local_hour < 19 else "night"


def _safety_weight(user: dict[str, Any], time_of_day: str) -> float:
    """Wsafe: higher for more vulnerable trip contexts. Wtime = 1 - Wsafe.
    Mirrors the proposal's example: a novice motorcyclist at night gets a high Wsafe.
    """
    weight = 0.4
    if user["driving_experience"] == "novice":
        weight += 0.2
    if user["vehicle_type"] == "motorcycle":
        weight += 0.2
    if time_of_day == "night":
        weight += 0.1
    return max(0.1, min(0.9, weight))


def _osrm_exclude_param(user: dict[str, Any]) -> str | None:
    excludes = []
    if user["avoid_highways"]:
        excludes.append("motorway")
    if user["avoid_tolls"]:
        excludes.append("toll")
    return ",".join(excludes) if excludes else None


def _fetch_osrm_routes(origin: Coordinate, destination: Coordinate, exclude: str | None) -> list[dict[str, Any]]:
    url = f"{_osrm_base_url()}/route/v1/driving/{origin.lon},{origin.lat};{destination.lon},{destination.lat}"
    params: dict[str, Any] = {
        "alternatives": "true",
        "geometries": "geojson",
        "overview": "full",
    }
    if exclude:
        params["exclude"] = exclude
    try:
        response = httpx.get(url, params=params, timeout=15.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Routing service unavailable: {exc}") from exc

    payload = response.json()
    if payload.get("code") != "Ok":
        raise HTTPException(status_code=422, detail=f"No route found: {payload.get('message', payload.get('code'))}")
    return payload["routes"]


def _accident_count_near_route(conn: Any, geometry: dict[str, Any]) -> int:
    sql = text(
        """
        SELECT COUNT(*) FROM accident_attribution.accident_attributions a
        WHERE ST_DWithin(
            ST_Transform(a.geometry, 2039),
            ST_Buffer(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326), 2039), :buffer_m),
            0
        )
        """
    )
    return conn.execute(
        sql, {"geojson": json.dumps(geometry), "buffer_m": ROUTE_RISK_BUFFER_M}
    ).scalar_one()


def _normalize(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    if high == low:
        return [0.0 for _ in values]
    return [(v - low) / (high - low) for v in values]


@router.post("/api/route")
def plan_route(payload: RouteRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    time_of_day = payload.time_of_day or _infer_time_of_day()
    w_safe = _safety_weight(user, time_of_day)
    w_time = 1 - w_safe

    osrm_routes = _fetch_osrm_routes(payload.origin, payload.destination, _osrm_exclude_param(user))

    with get_engine().begin() as conn:
        candidates = []
        for osrm_route in osrm_routes:
            accident_count = _accident_count_near_route(conn, osrm_route["geometry"])
            distance_km = osrm_route["distance"] / 1000
            risk_density = accident_count / distance_km if distance_km > 0 else 0.0
            candidates.append(
                {
                    "geometry": osrm_route["geometry"],
                    "distance_m": osrm_route["distance"],
                    "duration_s": osrm_route["duration"],
                    "accident_count": accident_count,
                    "risk_density": risk_density,
                }
            )

    normalized_time = _normalize([c["duration_s"] for c in candidates])
    normalized_risk = _normalize([c["risk_density"] for c in candidates])
    for candidate, n_time, n_risk in zip(candidates, normalized_time, normalized_risk):
        candidate["normalized_time"] = n_time
        candidate["normalized_risk"] = n_risk
        candidate["cost"] = w_time * n_time + w_safe * n_risk

    best = min(candidates, key=lambda c: c["cost"])
    chosen_index = candidates.index(best)

    return {
        "time_of_day": time_of_day,
        "weights": {"w_safe": w_safe, "w_time": w_time},
        "chosen_route": best,
        "chosen_index": chosen_index,
        "alternatives": candidates,
        "explanation": (
            f"Chose the route minimizing cost given a safety weight of {w_safe:.2f} "
            f"(driving_experience={user['driving_experience']}, vehicle_type={user['vehicle_type']}, "
            f"time_of_day={time_of_day}): {best['accident_count']} historical accidents near this "
            f"route ({best['risk_density']:.2f} per km), {best['duration_s']:.0f}s travel time."
        ),
    }
