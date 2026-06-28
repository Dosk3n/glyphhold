from __future__ import annotations

import json
from typing import Any

from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now


def record_event(
    *,
    request_id: str,
    event_type: str,
    success: bool,
    actor: str | None = None,
    tool: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    action: str | None = None,
    message: str | None = None,
    query: str | None = None,
    result_count: int | None = None,
    estimated_tokens: int | None = None,
    duration_ms: int | None = None,
    purpose: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    event_id = new_id("evt")
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO event_log (
                id, request_id, event_type, actor, tool, target_type, target_id, action,
                success, message, query, result_count, estimated_tokens, duration_ms,
                purpose, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                request_id,
                event_type,
                actor,
                tool,
                target_type,
                target_id,
                action,
                1 if success else 0,
                message,
                query,
                result_count,
                estimated_tokens,
                duration_ms,
                purpose,
                utc_now(),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
    return event_id

