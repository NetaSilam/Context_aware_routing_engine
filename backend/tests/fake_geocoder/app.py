from __future__ import annotations

import asyncio
from collections import Counter

from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Deterministic fake geocoder")
requests_by_query: Counter[str] = Counter()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reset")
async def reset() -> dict[str, str]:
    requests_by_query.clear()
    return {"status": "reset"}


@app.get("/metrics")
async def metrics() -> dict[str, dict[str, int]]:
    return {"requests_by_query": dict(requests_by_query)}


@app.get("/search", response_model=None)
async def search(
    q: str = Query(),
    format: str = Query(),
    limit: int = Query(),
    countrycodes: str = Query(),
    bounded: int = Query(),
    viewbox: str = Query(),
    user_agent: str | None = Header(default=None),
) -> Response | list[dict[str, str]]:
    requests_by_query[q] += 1
    if (
        format != "jsonv2"
        or countrycodes != "il"
        or bounded != 1
        or not viewbox
        or user_agent != "road-risk-integration-tests/1.0"
    ):
        return JSONResponse(status_code=400, content={"error": "invalid contract"})
    if q == "empty place":
        return []
    if q == "malformed data":
        return [{"display_name": "Missing coordinates"}]
    if q == "delayed place":
        await asyncio.sleep(0.5)
    if q == "service failure":
        return JSONResponse(status_code=503, content={"error": "unavailable"})
    if q == "malformed json":
        return Response(content=b"[{", media_type="application/json")
    results = [
        {"display_name": "Tel Aviv Center", "lon": "34.7800", "lat": "32.0700"},
        {"display_name": "Outside Israel", "lon": "10.0", "lat": "10.0"},
    ]
    return results[:limit]
