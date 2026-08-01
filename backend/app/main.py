from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from app.auth_routes import router as auth_router
from app.data_routes import router as data_router
from app.db import check_connection

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Context-Aware Safe Routing Engine API",
        version="0.1.0",
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

    return app


app = create_app()
