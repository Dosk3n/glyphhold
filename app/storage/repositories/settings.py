from __future__ import annotations

from collections.abc import Callable

from app.config import settings
from app.core.encryption import derive_key, persistent_private_key
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
    # A database-only leak must not allow forging administrator sessions. Legacy
    # cookies expire once, while the new secret remains stable across restarts.
    if settings.secrets_enabled:
        secret = derive_key("dashboard-signing")
    else:
        secret = persistent_private_key(settings.db_path.parent / "session.key")
    if get_setting("session_secret") is not None:
        with connection() as conn:
            conn.execute("DELETE FROM app_settings WHERE key='session_secret'")
    return secret
