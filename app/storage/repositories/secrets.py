from __future__ import annotations

import json
import re
from typing import Any

from app.core.encryption import decrypt_secret, encrypt_secret, encryption_key_id
from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now

VALUE_TYPES = ("text", "api_key", "password", "token", "webhook_url", "username", "json")
SECRET_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


METADATA_COLUMNS = """
    id, name, description, encryption_version, encryption_key_id, value_type,
    service, host, scope, tags_json, allowed_agents_json, allowed_tools_json,
    created_at, updated_at, last_revealed_at
"""


def _json(value: Any, default: Any) -> str:
    return json.dumps(default if value is None else value, sort_keys=True)


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def validate_secret_name(name: str) -> str:
    normalized = name.strip()
    if not SECRET_NAME_RE.fullmatch(normalized):
        raise ValueError("secret name must be an uppercase environment variable name")
    return normalized


def _check_reveal_allowed(
    secret: dict[str, Any],
    *,
    requesting_agent: str | None = None,
    tool: str | None = None,
) -> None:
    allowed_agents = _json_list(secret.get("allowed_agents_json"))
    allowed_tools = _json_list(secret.get("allowed_tools_json"))
    if allowed_agents and requesting_agent not in allowed_agents:
        raise PermissionError("secret reveal denied for this agent")
    if allowed_tools and tool not in allowed_tools:
        raise PermissionError("secret reveal denied for this tool")


def list_secrets(
    *,
    query: str | None = None,
    service: str | None = None,
    host: str | None = None,
    scope: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where = []
    values: list[Any] = []
    if query:
        where.append(
            "(name LIKE ? OR description LIKE ? OR service LIKE ? OR host LIKE ? OR scope LIKE ? OR tags_json LIKE ?)"
        )
        pattern = f"%{query}%"
        values.extend([pattern, pattern, pattern, pattern, pattern, pattern])
    if service:
        where.append("service = ?")
        values.append(service)
    if host:
        where.append("host = ?")
        values.append(host)
    if scope:
        where.append("scope = ?")
        values.append(scope)
    values.extend([limit, offset])
    sql = f"""
        SELECT {METADATA_COLUMNS}
        FROM secrets
        {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY lower(name)
        LIMIT ? OFFSET ?
    """
    with connection() as conn:
        rows = conn.execute(sql, values).fetchall()
        return [dict(row) for row in rows]


def get_secret_metadata(id_or_name: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            f"SELECT {METADATA_COLUMNS} FROM secrets WHERE id = ? OR name = ?",
            (id_or_name, id_or_name),
        ).fetchone()
        return dict(row) if row else None


def _get_secret_with_value(id_or_name: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM secrets WHERE id = ? OR name = ?",
            (id_or_name, id_or_name),
        ).fetchone()
        return dict(row) if row else None


def create_secret(
    *,
    name: str,
    value: str,
    description: str | None = None,
    value_type: str = "text",
    service: str | None = None,
    host: str | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    allowed_agents: list[str] | None = None,
    allowed_tools: list[str] | None = None,
) -> dict[str, Any]:
    name = validate_secret_name(name)
    if value_type not in VALUE_TYPES:
        raise ValueError(f"value_type must be one of: {', '.join(VALUE_TYPES)}")
    secret_id = new_id("sec")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO secrets (
                id, name, description, encrypted_value, encryption_version,
                encryption_key_id, value_type, service, host, scope, tags_json,
                allowed_agents_json, allowed_tools_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                secret_id,
                name,
                description,
                encrypt_secret(value),
                encryption_key_id(),
                value_type,
                service,
                host,
                scope,
                _json(tags, []),
                _json(allowed_agents, []),
                _json(allowed_tools, []),
                now,
                now,
            ),
        )
    secret = get_secret_metadata(secret_id)
    assert secret is not None
    return secret


def update_secret(id_or_name: str, **fields: Any) -> dict[str, Any] | None:
    existing = get_secret_metadata(id_or_name)
    if existing is None:
        return None

    updates: dict[str, Any] = {}
    for key in ("name", "description", "value_type", "service", "host", "scope"):
        if key in fields and fields[key] is not None:
            updates[key] = fields[key]
    if "name" in updates:
        updates["name"] = validate_secret_name(updates["name"])
    if updates.get("value_type") is not None and updates["value_type"] not in VALUE_TYPES:
        raise ValueError(f"value_type must be one of: {', '.join(VALUE_TYPES)}")
    if fields.get("value") is not None:
        updates["encrypted_value"] = encrypt_secret(fields["value"])
        updates["encryption_version"] = 1
        updates["encryption_key_id"] = encryption_key_id()
    if fields.get("tags") is not None:
        updates["tags_json"] = _json(fields["tags"], [])
    if fields.get("allowed_agents") is not None:
        updates["allowed_agents_json"] = _json(fields["allowed_agents"], [])
    if fields.get("allowed_tools") is not None:
        updates["allowed_tools_json"] = _json(fields["allowed_tools"], [])
    if not updates:
        return existing
    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values())
    values.append(existing["id"])
    with connection() as conn:
        conn.execute(f"UPDATE secrets SET {assignments} WHERE id = ?", values)
    return get_secret_metadata(existing["id"])


def delete_secret(id_or_name: str) -> bool:
    with connection() as conn:
        cursor = conn.execute("DELETE FROM secrets WHERE id = ? OR name = ?", (id_or_name, id_or_name))
        return cursor.rowcount > 0


def reveal_secret(
    id_or_name: str,
    *,
    requesting_agent: str | None = None,
    tool: str | None = None,
    bypass_restrictions: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    secret = _get_secret_with_value(id_or_name)
    if secret is None:
        return None, None
    if not bypass_restrictions:
        _check_reveal_allowed(secret, requesting_agent=requesting_agent, tool=tool)
    value = decrypt_secret(secret["encrypted_value"])
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "UPDATE secrets SET last_revealed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, secret["id"]),
        )
    metadata = get_secret_metadata(secret["id"])
    return metadata, value
