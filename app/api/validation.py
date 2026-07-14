from __future__ import annotations

import json
from typing import Any

from app.config import settings


def validate_memory_body(value: str | None) -> str | None:
    if value is not None and len(value) > settings.max_memory_body_chars:
        limit_mib = settings.max_memory_body_chars / (1024 * 1024)
        raise ValueError(
            f"Memory body exceeds the {limit_mib:g} MiB limit. Shorten it or split it "
            "into multiple focused memories, then retry."
        )
    return value


def validate_summary(value: str | None) -> str | None:
    if value is not None and len(value) > settings.max_summary_chars:
        raise ValueError(
            f"Memory summary exceeds the {settings.max_summary_chars:,} character limit. "
            "Keep the summary concise and put additional detail in the memory body."
        )
    return value


def validate_tags(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if len(value) > 100:
        raise ValueError("A memory or secret can have at most 100 tags. Remove excess tags and retry.")
    if any(len(tag) > 100 for tag in value):
        raise ValueError("Each tag can be at most 100 characters. Shorten long tags and retry.")
    return value


def validate_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is not None and len(json.dumps(value, separators=(",", ":"))) > 128 * 1024:
        raise ValueError(
            "Memory metadata exceeds the 128 KiB limit. Move large content into the memory body."
        )
    return value


def validate_secret_value(value: str | None) -> str | None:
    if value is not None and len(value) > settings.max_secret_value_chars:
        limit_mib = settings.max_secret_value_chars / (1024 * 1024)
        raise ValueError(
            f"Secret value exceeds the {limit_mib:g} MiB limit. Reduce the value and retry."
        )
    return value
