from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SENSITIVE_KEYS = (
    "value",
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "webhook",
    "encrypted_value",
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEYS)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value

