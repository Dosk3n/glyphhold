from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.ids import new_id
from app.config import settings
from app.storage.db import connection
from app.utils.time import utc_now

_prune_lock = threading.Lock()
_events_since_prune = 0


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
    _maybe_prune_events()
    return event_id


def _maybe_prune_events() -> None:
    global _events_since_prune
    should_prune = False
    with _prune_lock:
        _events_since_prune += 1
        if _events_since_prune >= 1000:
            _events_since_prune = 0
            should_prune = True
    if should_prune:
        prune_events()


def prune_events() -> int:
    deleted = 0
    with connection() as conn:
        if settings.event_retention_days > 0:
            cutoff = (
                datetime.now(UTC) - timedelta(days=settings.event_retention_days)
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            deleted += conn.execute(
                "DELETE FROM event_log WHERE created_at < ?", (cutoff,)
            ).rowcount
        if settings.max_event_rows > 0:
            deleted += conn.execute(
                """
                DELETE FROM event_log
                WHERE id IN (
                    SELECT id FROM event_log
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (settings.max_event_rows,),
            ).rowcount
    return deleted


def list_events(
    *,
    actor: str | None = None,
    event_type: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    success: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where = []
    values: list[Any] = []
    if actor:
        where.append("actor = ?")
        values.append(actor)
    if event_type:
        where.append("event_type = ?")
        values.append(event_type)
    if target_type:
        where.append("target_type = ?")
        values.append(target_type)
    if target_id:
        where.append("target_id = ?")
        values.append(target_id)
    if success is not None:
        where.append("success = ?")
        values.append(1 if success else 0)
    values.extend([limit, offset])
    sql = f"""
        SELECT *
        FROM event_log
        {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    with connection() as conn:
        rows = conn.execute(sql, values).fetchall()
        return [dict(row) for row in rows]


def get_event(event_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM event_log WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None
