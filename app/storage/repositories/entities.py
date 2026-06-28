from __future__ import annotations

import json
from typing import Any

from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now


def list_entities() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT e.*,
                   count(me.memory_id) AS memory_count
            FROM entities e
            LEFT JOIN memory_entities me ON me.entity_id = e.id
            GROUP BY e.id
            ORDER BY lower(e.name)
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_entity(entity_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return dict(row) if row else None


def create_entity(*, name: str, type: str | None = None, aliases: list[str] | None = None) -> dict[str, Any]:
    entity_id = new_id("ent")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO entities(id, name, type, aliases_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entity_id, name, type, json.dumps(aliases or []), now, now),
        )
    entity = get_entity(entity_id)
    assert entity is not None
    return entity


def update_entity(entity_id: str, **fields: Any) -> dict[str, Any] | None:
    updates: dict[str, Any] = {}
    if fields.get("name") is not None:
        updates["name"] = fields["name"]
    if "type" in fields:
        updates["type"] = fields["type"]
    if fields.get("aliases") is not None:
        updates["aliases_json"] = json.dumps(fields["aliases"])
    if not updates:
        return get_entity(entity_id)
    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values())
    values.append(entity_id)
    with connection() as conn:
        conn.execute(f"UPDATE entities SET {assignments} WHERE id = ?", values)
    return get_entity(entity_id)


def delete_entity(entity_id: str) -> bool:
    with connection() as conn:
        cursor = conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        return cursor.rowcount > 0

