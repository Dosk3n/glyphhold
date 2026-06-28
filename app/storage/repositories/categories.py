from __future__ import annotations

from typing import Any

from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now


def list_categories() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT c.*,
                   count(m.id) AS memory_count
            FROM memory_categories c
            LEFT JOIN memories m ON m.category_id = c.id
            GROUP BY c.id
            ORDER BY c.name
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_category(category_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM memory_categories WHERE id = ? OR name = ?",
            (category_id, category_id),
        ).fetchone()
        return dict(row) if row else None


def create_category(
    *,
    name: str,
    description: str | None = None,
    allow_auto_prefetch: bool = True,
    agent_can_create: bool = True,
    agent_can_write: bool = True,
) -> dict[str, Any]:
    category_id = new_id("cat")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO memory_categories (
                id, name, description, allow_auto_prefetch, agent_can_create,
                agent_can_write, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category_id,
                name,
                description,
                1 if allow_auto_prefetch else 0,
                1 if agent_can_create else 0,
                1 if agent_can_write else 0,
                now,
                now,
            ),
        )
    category = get_category(category_id)
    assert category is not None
    return category


def update_category(category_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "name",
        "description",
        "allow_auto_prefetch",
        "agent_can_create",
        "agent_can_write",
    }
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    if not updates:
        return get_category(category_id)

    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [
        int(value) if isinstance(value, bool) else value
        for value in updates.values()
    ]
    values.append(category_id)
    with connection() as conn:
        conn.execute(
            f"UPDATE memory_categories SET {assignments} WHERE id = ?",
            values,
        )
    return get_category(category_id)


def delete_category(category_id: str) -> bool:
    with connection() as conn:
        cursor = conn.execute("DELETE FROM memory_categories WHERE id = ?", (category_id,))
        return cursor.rowcount > 0

