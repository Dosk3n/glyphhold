from __future__ import annotations

import sqlite3
import threading
import time

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.storage.db import database_ok
from app.storage.migrations import current_schema_version

router = APIRouter(prefix="/api/v1", tags=["health"])


class HealthSnapshot:
    """Coalesce expensive integrity checks; at most one scan per refresh interval."""

    def __init__(self, interval: float = 60) -> None:
        self.interval = interval
        self.checked_at = float("-inf")
        self.payload: dict | None = None
        self.lock = threading.Lock()

    def read(self) -> dict:
        now = time.monotonic()
        if self.payload is not None and now - self.checked_at < self.interval:
            return self.payload
        # Continue serving the previous result while another request refreshes it.
        if not self.lock.acquire(blocking=self.payload is None):
            return self.payload
        try:
            if self.payload is None or now - self.checked_at >= self.interval:
                healthy = database_ok()
                try:
                    schema = current_schema_version() if healthy else None
                except sqlite3.DatabaseError:
                    healthy, schema = False, None
                self.payload = {
                    "status": "ok" if healthy else "error",
                    "version": settings.version,
                    "database": "ok" if healthy else "error",
                    "schema_version": schema,
                    "secrets_enabled": settings.secrets_enabled,
                }
                self.checked_at = time.monotonic()
            return self.payload
        finally:
            self.lock.release()


@router.get("/health")
def health(request: Request, response: Response) -> dict[str, object]:
    payload = request.app.state.health_snapshot.read()
    if payload["status"] != "ok":
        response.status_code = 503
    return payload
