from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    version: str = "0.1.0"
    db_path: Path = Path(os.getenv("TOMEWARDEN_DB_PATH", "./data/tomewarden.sqlite"))
    host: str = os.getenv("TOMEWARDEN_HOST", "0.0.0.0")
    port: int = _env_int("TOMEWARDEN_PORT", 5995)
    encryption_key: str | None = os.getenv("TOMEWARDEN_ENCRYPTION_KEY") or None
    log_level: str = os.getenv("TOMEWARDEN_LOG_LEVEL", "INFO").upper()
    log_format: str = os.getenv("TOMEWARDEN_LOG_FORMAT", "pretty").lower()
    event_retention_days: int = _env_int("TOMEWARDEN_EVENT_RETENTION_DAYS", 90)
    max_event_rows: int = _env_int("TOMEWARDEN_MAX_EVENT_ROWS", 100000)
    cookie_secure: bool = _env_bool("TOMEWARDEN_COOKIE_SECURE", False)
    session_cookie_name: str = "tomewarden_session"

    @property
    def secrets_enabled(self) -> bool:
        return self.encryption_key is not None


settings = Settings()
