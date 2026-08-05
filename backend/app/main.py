from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI

from app.auth import get_current_user
from app.auth_routes import router as auth_router
from app.config import get_settings
from app.data_routes import router as data_router
from app.forum.routes import router as forum_router
from app.health import router as health_router
from app.geocoding.router import router as geocoding_router
from app.routing.route_jobs import router as route_jobs_router
from app.routing.route_jobs import history_router as route_history_router
from app.routing.route_jobs import recover_stale_route_jobs
from app.routing.route_jobs import reconcile_unfinished_route_job_capacity
from app.request_bounds import RequestSizeLimitMiddleware
from app.operations import configure_structured_logging

configure_structured_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await reconcile_unfinished_route_job_capacity()
    await recover_stale_route_jobs()
    yield


def create_app() -> FastAPI:
    # Validate required dependency configuration before the process begins serving.
    settings = get_settings()
    app = FastAPI(
        title="Context-Aware Safe Routing Engine API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_body_bytes=settings.request_body_max_bytes,
        max_query_bytes=settings.request_query_max_bytes,
    )

    app.include_router(health_router)
    app.include_router(data_router, dependencies=[Depends(get_current_user)])
    app.include_router(auth_router)
    app.include_router(geocoding_router)
    app.include_router(route_jobs_router)
    app.include_router(route_history_router)
    app.include_router(forum_router)
    if settings.testing:
        from app.routing.test_scoring_router import router as test_scoring_router

        app.include_router(test_scoring_router)

    return app


app = create_app()
