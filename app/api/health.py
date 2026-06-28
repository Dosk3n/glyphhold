from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.storage.db import database_ok
from app.storage.migrations import current_schema_version

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": settings.version,
        "database": "ok" if database_ok() else "error",
        "schema_version": current_schema_version(),
        "secrets_enabled": settings.secrets_enabled,
    }

