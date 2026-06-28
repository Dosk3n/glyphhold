from __future__ import annotations

import secrets
from collections.abc import Callable

from app.storage.db import connection
from app.utils.time import utc_now


def get_setting(key: str) -> str | None:
    with connection() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None


def get_or_create_setting(key: str, default_factory: Callable[[], str]) -> str:
    existing = get_setting(key)
    if existing is not None:
        return existing

    value = str(default_factory())
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO app_settings(key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, value, now, now),
        )
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"])


def get_session_secret() -> str:
    return get_or_create_setting("session_secret", lambda: secrets.token_urlsafe(48))
