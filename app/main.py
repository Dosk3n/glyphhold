from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.api.advanced import router as advanced_router
from app.api.agent import router as agent_router
from app.api.categories import router as categories_router
from app.api.dashboard_json import router as dashboard_json_router
from app.api.dashboard_spa import router as dashboard_spa_router
from app.api.events import router as events_router
from app.api.health import HealthSnapshot
from app.api.health import router as health_router
from app.api.memories import router as memories_router
from app.api.provider_settings import router as provider_router
from app.api.secrets import router as secrets_router
from app.api.v2_secrets import router as v2_secrets_router
from app.config import settings
from app.core.encryption import ensure_installation_key
from app.core.logging import configure_logging, log_info
from app.core.rate_limit import FailureRateLimiter
from app.core.request_context import RequestContextMiddleware
from app.core.security import (
    DashboardCSRFMiddleware,
    LegacyDataBoundaryMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.providers.transfer import migrate_legacy_fingerprints
from app.providers.vault import initialize as initialize_providers
from app.storage.db import database_ok
from app.storage.migrations import apply_migrations, current_schema_version
from app.storage.repositories.events import prune_events
from app.storage.repositories.settings import get_session_secret
from app.storage.upgrade import before_v2_upgrade
from app.v2.api import router as v2_router
from app.v2.core import SpaceError, ensure_schema


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.advanced.worker import worker

    await worker.start()
    prune_events()
    log_info(
        "app.startup",
        event="app.startup",
        version=settings.version,
        schema_version=current_schema_version(),
        secrets_enabled=settings.secrets_enabled,
    )
    try:
        yield
    finally:
        await worker.stop()


def create_app() -> FastAPI:
    configure_logging()
    before_v2_upgrade(settings.db_path)
    apply_migrations()
    ensure_schema()
    if settings.secrets_enabled:
        ensure_installation_key()
    initialize_providers()
    get_session_secret()
    if settings.secrets_enabled:
        migrate_legacy_fingerprints()
    if not database_ok():
        raise RuntimeError(
            "SQLite integrity check failed; preserve the data and restore a validated backup"
        )
    # The model process uses a separate UID in Docker and must not read the DB.
    settings.db_path.chmod(0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = settings.db_path.with_name(settings.db_path.name + suffix)
        if sidecar.exists():
            sidecar.chmod(0o600)

    app = FastAPI(
        title="Glyph Hold",
        version=settings.version,
        description="Shared agent memory with spaces and optional Advanced Memory.",
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )
    app.state.failure_rate_limiter = FailureRateLimiter()
    app.state.health_snapshot = HealthSnapshot()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(DashboardCSRFMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(LegacyDataBoundaryMiddleware)

    @app.exception_handler(SpaceError)
    async def space_error_handler(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    app.mount(
        "/dashboard-assets",
        StaticFiles(directory="app/dashboard/static/dashboard"),
        name="dashboard-assets",
    )
    app.include_router(dashboard_json_router)
    app.include_router(health_router)
    app.include_router(categories_router)
    app.include_router(memories_router)
    app.include_router(events_router)
    app.include_router(agent_router)
    app.include_router(secrets_router)
    app.include_router(v2_router)
    app.include_router(v2_secrets_router)
    app.include_router(provider_router)
    app.include_router(advanced_router)
    # The SPA catchall must follow every dashboard API route.
    app.include_router(dashboard_spa_router)

    return app


app = create_app()
