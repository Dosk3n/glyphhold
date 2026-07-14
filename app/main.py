from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.agent import router as agent_router
from app.api.categories import router as categories_router
from app.api.dashboard_json import router as dashboard_json_router
from app.api.dashboard_spa import router as dashboard_spa_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.memories import router as memories_router
from app.api.secrets import router as secrets_router
from app.config import settings
from app.core.logging import configure_logging, log_info
from app.core.rate_limit import FailureRateLimiter
from app.core.request_context import RequestContextMiddleware
from app.core.security import (
    DashboardCSRFMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.storage.migrations import apply_migrations, current_schema_version
from app.storage.repositories.events import prune_events


@asynccontextmanager
async def lifespan(_: FastAPI):
    prune_events()
    log_info(
        "app.startup",
        event="app.startup",
        version=settings.version,
        schema_version=current_schema_version(),
        secrets_enabled=settings.secrets_enabled,
    )
    yield


def create_app() -> FastAPI:
    configure_logging()
    apply_migrations()

    app = FastAPI(
        title="Glyph Hold",
        version=settings.version,
        description="A local, non-LLM memory and secrets service for agents.",
        lifespan=lifespan,
    )
    app.state.failure_rate_limiter = FailureRateLimiter()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(DashboardCSRFMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount(
        "/dashboard-assets",
        StaticFiles(directory="app/dashboard/static/dashboard"),
        name="dashboard-assets",
    )
    app.include_router(dashboard_json_router)
    app.include_router(dashboard_spa_router)
    app.include_router(health_router)
    app.include_router(categories_router)
    app.include_router(memories_router)
    app.include_router(events_router)
    app.include_router(agent_router)
    app.include_router(secrets_router)

    return app


app = create_app()
