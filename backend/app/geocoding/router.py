from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from redis.exceptions import RedisError

from app.auth import get_current_user
from app.config import get_settings
from app.geocoding.geocoder_client import GeocoderError, search_provider
from app.redis_client import get_redis

router = APIRouter(prefix="/api/geocoding", tags=["geocoding"])
ATTRIBUTION = "© OpenStreetMap contributors"


class AddressSearchResult(BaseModel):
    label: str
    longitude: float
    latitude: float


class AddressSearchResponse(BaseModel):
    results: list[AddressSearchResult]
    attribution: str


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip().casefold()


async def _enforce_request_limits(request: Request, user_id: int) -> None:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    keys = [
        f"geocode-rate:user:{user_id}",
        f"geocode-rate:ip:{client_ip}",
    ]
    try:
        counts = await get_redis().eval(
            """
            local results = {}
            for index, key in ipairs(KEYS) do
                local count = redis.call('INCR', key)
                if count == 1 then redis.call('EXPIRE', key, ARGV[1]) end
                results[index] = count
            end
            results[3] = math.max(redis.call('TTL', KEYS[1]), redis.call('TTL', KEYS[2]))
            return results
            """,
            2,
            *keys,
            settings.geocoder_rate_limit_window_seconds,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Address search protection is temporarily unavailable. Use map or numeric coordinates.",
            headers={"Retry-After": "5"},
        ) from exc
    if counts[0] > settings.geocoder_user_rate_limit or counts[1] > settings.geocoder_ip_rate_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many address searches. Use map or numeric coordinates or retry later.",
            headers={"Retry-After": str(max(counts[2], 1))},
        )


async def _reserve_upstream_request() -> None:
    try:
        reserved = await get_redis().set(
            "geocode-upstream:global-one-per-second",
            "1",
            nx=True,
            px=1000,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Address search protection is temporarily unavailable. Use map or numeric coordinates.",
            headers={"Retry-After": "5"},
        ) from exc
    if not reserved:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Address search is limited to one new provider request per second. Please retry.",
            headers={"Retry-After": "1"},
        )


@router.get("/search", response_model=AddressSearchResponse)
async def search_addresses(
    request: Request,
    q: str = Query(),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()
    query = normalize_query(q)
    if not settings.geocoder_query_min_length <= len(query) <= settings.geocoder_query_max_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Address query length must be between "
                f"{settings.geocoder_query_min_length} and {settings.geocoder_query_max_length} characters."
            ),
        )
    await _enforce_request_limits(request, int(user["id"]))

    cache_key = f"geocode-cache:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
    try:
        cached = await get_redis().get(cache_key)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Address search cache is temporarily unavailable. Use map or numeric coordinates.",
            headers={"Retry-After": "5"},
        ) from exc
    if cached is not None:
        return json.loads(cached)

    await _reserve_upstream_request()
    try:
        matches = await search_provider(query)
    except GeocoderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{exc} Use map or numeric coordinates.",
            headers={"Retry-After": "5"},
        ) from exc
    response = {
        "results": [match.__dict__ for match in matches],
        "attribution": ATTRIBUTION,
    }
    try:
        await get_redis().setex(
            cache_key,
            settings.geocoder_cache_ttl_seconds,
            json.dumps(response),
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Address search cache is temporarily unavailable. Use map or numeric coordinates.",
            headers={"Retry-After": "5"},
        ) from exc
    return response
