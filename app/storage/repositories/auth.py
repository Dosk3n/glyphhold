from __future__ import annotations

import json
from typing import Any

from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now


def has_admin_user() -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM dashboard_users WHERE is_admin = 1 LIMIT 1"
        ).fetchone()
        return row is not None


def create_dashboard_user(username: str, password_hash: str, *, is_admin: bool = True) -> str:
    user_id = new_id("usr")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO dashboard_users (
                id, username, password_hash, is_admin, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, password_hash, 1 if is_admin else 0, now, now),
        )
    return user_id


def get_dashboard_user_by_username(username: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM dashboard_users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_dashboard_user_by_id(user_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM dashboard_users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def list_admin_users() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, username, is_admin, created_at, updated_at, last_login_at
            FROM dashboard_users
            WHERE is_admin = 1
            ORDER BY created_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def update_dashboard_password(username: str, password_hash: str) -> bool:
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE dashboard_users
            SET password_hash = ?, updated_at = ?
            WHERE username = ? AND is_admin = 1
            """,
            (password_hash, now, username),
        )
        return cursor.rowcount > 0


def mark_dashboard_login(user_id: str) -> None:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "UPDATE dashboard_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )


def create_api_key_record(
    *,
    name: str,
    actor: str,
    description: str | None,
    key_prefix: str,
    key_hash: str,
    scopes: list[str],
) -> str:
    key_id = new_id("key")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO api_keys (
                id, name, actor, description, key_prefix, key_hash, scopes_json,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                key_id,
                name,
                actor,
                description,
                key_prefix,
                key_hash,
                json.dumps(scopes),
                now,
                now,
            ),
        )
    return key_id


def list_api_keys() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, actor, description, key_prefix, scopes_json, enabled,
                   created_at, updated_at, last_used_at
            FROM api_keys
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_api_key_metadata(key_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, actor, description, key_prefix, scopes_json, enabled,
                   created_at, updated_at, last_used_at
            FROM api_keys
            WHERE id = ?
            """,
            (key_id,),
        ).fetchone()
        return dict(row) if row else None


def get_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? AND enabled = 1", (key_hash,)
        ).fetchone()
        return dict(row) if row else None


def touch_api_key(key_id: str) -> None:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = ?, updated_at = ? WHERE id = ?",
            (now, now, key_id),
        )


def set_api_key_enabled(key_id: str, enabled: bool) -> None:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "UPDATE api_keys SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, now, key_id),
        )
