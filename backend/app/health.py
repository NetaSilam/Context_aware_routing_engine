from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "live"}


async def _database_readiness() -> dict[str, Any]:
    settings = get_settings()
    async with get_engine().connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT
                        PostGIS_Version() AS postgis_version,
                        EXISTS (
                            SELECT 1
                            FROM app.foundation_data_versions
                            WHERE version = :version
                        ) AS foundation_ready
                    """
                ),
                {"version": settings.foundation_data_version},
            )
        ).mappings().one()
    if not row["foundation_ready"]:
        raise RuntimeError(
            f"foundation data version {settings.foundation_data_version!r} is not initialized"
        )
    return {"status": "ready", "postgis_version": row["postgis_version"]}


async def _redis_readiness() -> dict[str, str]:
    if not await get_redis().ping():
        raise RuntimeError("Redis ping returned false")
    return {"status": "ready"}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    timeout = get_settings().readiness_timeout_seconds
    checks: dict[str, Any] = {}
    for name, check in (("database", _database_readiness), ("redis", _redis_readiness)):
        try:
            checks[name] = await asyncio.wait_for(check(), timeout=timeout)
        except Exception as exc:
            checks[name] = {"status": "unavailable", "reason": str(exc)}

    ready = all(check["status"] == "ready" for check in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
