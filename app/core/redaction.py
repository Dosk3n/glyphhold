from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SENSITIVE_EXACT_KEYS = {
    "value",
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "webhook",
    "encrypted_value",
    "encryption_key",
    "authorization",
    "cookie",
    "set_cookie",
}

SENSITIVE_SUFFIXES = (
    "_value",
    "_secret",
    "_password",
    "_token",
    "_api_key",
    "_apikey",
    "_webhook",
    "_encryption_key",
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_EXACT_KEYS or normalized.endswith(SENSITIVE_SUFFIXES)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
