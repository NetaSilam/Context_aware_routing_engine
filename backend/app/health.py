from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.redis_client import get_redis
from app.refresh_risk_data import RISK_DATA_SCHEMA_VERSION

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
                        ) AS foundation_ready,
                        risk.version AS risk_data_version,
                        risk.schema_version AS risk_schema_version,
                        risk.validation_status AS risk_validation_status,
                        risk.reference_risk_p95,
                        risk.output_corridor_count,
                        risk.has_corridor_data
                    FROM (SELECT 1) dependency_check
                    LEFT JOIN (
                        SELECT
                            v.version, v.schema_version, v.validation_status,
                            v.reference_risk_p95, v.output_corridor_count,
                            EXISTS (
                                SELECT 1
                                FROM app.corridor_risk_statistics s
                                WHERE s.risk_data_version = v.version
                            ) AS has_corridor_data
                        FROM app.active_risk_data_version a
                        JOIN app.risk_data_versions v ON v.version = a.version
                    ) risk ON TRUE
                    """
                ),
                {"version": settings.foundation_data_version},
            )
        ).mappings().one()
    if not row["foundation_ready"]:
        raise RuntimeError(
            f"foundation data version {settings.foundation_data_version!r} is not initialized"
        )
    if row["risk_data_version"] is None:
        raise RuntimeError("active risk data is missing")
    if row["risk_schema_version"] != RISK_DATA_SCHEMA_VERSION:
        raise RuntimeError(
            f"active risk data schema {row['risk_schema_version']!r} is incompatible; "
            f"expected {RISK_DATA_SCHEMA_VERSION!r}"
        )
    if (
        row["risk_validation_status"] != "valid"
        or row["reference_risk_p95"] is None
        or row["reference_risk_p95"] <= 0
        or row["output_corridor_count"] <= 0
        or not row["has_corridor_data"]
    ):
        raise RuntimeError("active risk data is invalid")
    return {
        "status": "ready",
        "postgis_version": row["postgis_version"],
        "risk_data_version": row["risk_data_version"],
    }


async def _redis_readiness() -> dict[str, str]:
    if not await get_redis().ping():
        raise RuntimeError("Redis ping returned false")
    return {"status": "ready"}


async def _osrm_compatibility_readiness(risk_data_version: str | None) -> dict[str, str]:
    settings = get_settings()
    path = settings.osrm_deployment_manifest_path
    if not settings.osrm_compatibility_required:
        return {"status": "ready"}
    if path is None or not path.is_file():
        raise RuntimeError("OSRM deployment compatibility manifest is unavailable")
    try:
        combinations = json.loads(path.read_text(encoding="utf-8"))["tested_combinations"]
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError("OSRM deployment compatibility manifest is invalid") from exc
    expected = {
        "graph_version": settings.expected_osrm_graph_version,
        "corridor_risk_version": risk_data_version,
        "matcher_version": settings.corridor_matcher_version,
    }
    if expected not in combinations:
        raise RuntimeError("OSRM graph, risk-data, and matcher combination is unverified")
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
    try:
        risk_data_version = checks.get("database", {}).get("risk_data_version")
        checks["osrm"] = await asyncio.wait_for(
            _osrm_compatibility_readiness(risk_data_version), timeout=timeout
        )
    except Exception as exc:
        checks["osrm"] = {"status": "unavailable", "reason": str(exc)}

    ready = all(check["status"] == "ready" for check in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
