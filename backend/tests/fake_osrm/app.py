from __future__ import annotations

import asyncio

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, Response


app = FastAPI(title="Deterministic fake OSRM")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def route(distance: float, offset: float = 0.0) -> dict[str, object]:
    return {
        "distance": distance,
        "duration": distance / 12.0,
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [34.7800 + offset, 32.0800],
                [34.7900 + offset, 32.0900],
            ],
        },
    }


@app.get("/{scenario}/route/v1/driving/{coordinates}", response_model=None)
async def route_candidates(
    scenario: str,
    coordinates: str,
    alternatives: str = Query(),
    overview: str = Query(),
    geometries: str = Query(),
    exclude: str | None = Query(default=None),
) -> Response | dict[str, object]:
    if alternatives != "3" or overview != "full" or geometries != "geojson":
        return JSONResponse(
            status_code=400,
            content={"code": "InvalidQuery", "message": "incorrect route contract"},
        )
    if len(coordinates.split(";")) != 2:
        return JSONResponse(
            status_code=400,
            content={"code": "InvalidQuery", "message": "two coordinates required"},
        )
    if exclude not in {None, "motorway", "toll", "motorway,toll"}:
        return JSONResponse(
            status_code=400,
            content={"code": "InvalidOptions", "message": "unsupported exclusion"},
        )

    if scenario == "timeout":
        await asyncio.sleep(1.0)
    elif scenario == "delay":
        await asyncio.sleep(0.05)
    elif scenario == "server-error":
        return JSONResponse(status_code=503, content={"code": "Error"})
    elif scenario == "unsupported-option":
        return JSONResponse(
            status_code=400,
            content={"code": "InvalidOptions", "message": "unsupported option"},
        )
    elif scenario == "malformed-json":
        return Response(content=b'{"code":', media_type="application/json")
    elif scenario == "invalid-geometry":
        invalid = route(1200)
        invalid["geometry"] = {
            "type": "LineString",
            "coordinates": [[34.78], [34.79, 32.09]],
        }
        return {"code": "Ok", "routes": [invalid]}
    elif scenario == "no-route":
        return {"code": "NoRoute", "message": "No route found", "routes": []}
    elif scenario == "no-candidates":
        return {"code": "Ok", "routes": []}
    elif scenario == "missing-routes":
        return {"code": "Ok"}
    elif scenario == "one-route":
        return {"code": "Ok", "routes": [route(1200)]}
    elif scenario != "normal":
        return JSONResponse(status_code=404, content={"code": "InvalidUrl"})

    exclusion_distance = {
        None: 1000,
        "motorway": 1100,
        "toll": 1200,
        "motorway,toll": 1300,
    }[exclude]
    return {
        "code": "Ok",
        "routes": [
            route(exclusion_distance),
            route(exclusion_distance + 100, 0.001),
            route(exclusion_distance + 200, 0.002),
        ],
    }
