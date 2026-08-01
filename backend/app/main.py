from __future__ import annotations

import logging

from fastapi import FastAPI

from app.auth_routes import router as auth_router
from app.config import get_settings
from app.data_routes import router as data_router
from app.health import router as health_router

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    # Validate required dependency configuration before the process begins serving.
    get_settings()
    app = FastAPI(
        title="Context-Aware Safe Routing Engine API",
        version="0.1.0",
    )

    app.include_router(health_router)
    app.include_router(data_router)
    app.include_router(auth_router)

    return app


app = create_app()
