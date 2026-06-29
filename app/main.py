from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.agent import router as agent_router
from app.api.categories import router as categories_router
from app.api.dashboard import router as dashboard_router
from app.api.dashboard_json import router as dashboard_json_router
from app.api.dashboard_spa import router as dashboard_spa_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.memories import router as memories_router
from app.api.secrets import router as secrets_router
from app.config import settings
from app.core.logging import configure_logging, log_info
from app.core.request_context import RequestContextMiddleware
from app.storage.migrations import apply_migrations, current_schema_version


def create_app() -> FastAPI:
    configure_logging()
    apply_migrations()

    app = FastAPI(
        title="Glyph Hold",
        version=settings.version,
        description="A local, non-LLM memory and secrets service for agents.",
    )
    app.add_middleware(RequestContextMiddleware)
    app.mount("/static", StaticFiles(directory="app/dashboard/static"), name="static")
    app.mount(
        "/dashboard-assets",
        StaticFiles(directory="app/dashboard/static/dashboard"),
        name="dashboard-assets",
    )
    app.include_router(dashboard_json_router)
    app.include_router(dashboard_spa_router)
    app.include_router(dashboard_router)
    app.include_router(health_router)
    app.include_router(categories_router)
    app.include_router(memories_router)
    app.include_router(events_router)
    app.include_router(agent_router)
    app.include_router(secrets_router)

    @app.on_event("startup")
    def log_startup() -> None:
        log_info(
            "app.startup",
            event="app.startup",
            version=settings.version,
            schema_version=current_schema_version(),
            secrets_enabled=settings.secrets_enabled,
        )

    return app


app = create_app()
