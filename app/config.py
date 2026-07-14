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
    version: str = "1.1.0"
    db_path: Path = Path(os.getenv("GLYPHHOLD_DB_PATH", "./data/glyphhold.sqlite"))
    host: str = os.getenv("GLYPHHOLD_HOST", "0.0.0.0")
    port: int = _env_int("GLYPHHOLD_PORT", 5995)
    encryption_key: str | None = os.getenv("GLYPHHOLD_ENCRYPTION_KEY") or None
    log_level: str = os.getenv("GLYPHHOLD_LOG_LEVEL", "INFO").upper()
    log_format: str = os.getenv("GLYPHHOLD_LOG_FORMAT", "pretty").lower()
    event_retention_days: int = _env_int("GLYPHHOLD_EVENT_RETENTION_DAYS", 90)
    max_event_rows: int = _env_int("GLYPHHOLD_MAX_EVENT_ROWS", 100000)
    max_request_bytes: int = _env_int("GLYPHHOLD_MAX_REQUEST_BYTES", 2 * 1024 * 1024)
    max_memory_body_chars: int = _env_int("GLYPHHOLD_MAX_MEMORY_BODY_CHARS", 1024 * 1024)
    max_summary_chars: int = _env_int("GLYPHHOLD_MAX_SUMMARY_CHARS", 8 * 1024)
    max_secret_value_chars: int = _env_int("GLYPHHOLD_MAX_SECRET_VALUE_CHARS", 1024 * 1024)
    dashboard_login_attempts: int = _env_int("GLYPHHOLD_DASHBOARD_LOGIN_ATTEMPTS", 5)
    dashboard_login_window_seconds: int = _env_int(
        "GLYPHHOLD_DASHBOARD_LOGIN_WINDOW_SECONDS", 15 * 60
    )
    invalid_api_key_attempts: int = _env_int("GLYPHHOLD_INVALID_API_KEY_ATTEMPTS", 30)
    invalid_api_key_window_seconds: int = _env_int(
        "GLYPHHOLD_INVALID_API_KEY_WINDOW_SECONDS", 60
    )
    cookie_secure: bool = _env_bool("GLYPHHOLD_COOKIE_SECURE", False)
    session_cookie_name: str = "glyphhold_session"
    csrf_cookie_name: str = "glyphhold_csrf"

    @property
    def secrets_enabled(self) -> bool:
        return self.encryption_key is not None


settings = Settings()
