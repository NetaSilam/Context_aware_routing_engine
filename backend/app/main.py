from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.auth_routes import router as auth_router
from app.data_routes import router as data_router
from app.db import check_connection, get_engine
from app.routing_routes import router as routing_router
from app.schema import ensure_app_schema
from app.seed import ensure_seeded

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_seeded(get_engine())
    ensure_app_schema(get_engine())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Context-Aware Safe Routing Engine API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/db")
    def health_db() -> dict[str, str]:
        try:
            check_connection()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
        return {"status": "ok"}

    app.include_router(data_router)
    app.include_router(auth_router)
    app.include_router(routing_router)

    return app


app = create_app()
