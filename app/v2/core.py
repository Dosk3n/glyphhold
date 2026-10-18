"""GH2 ownership, traceable recall and atomic lifecycle operations.

The v1 content tables remain authoritative. Additive tables and columns provide
ownership and concurrency without discarding existing records or their history.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now


class SpaceError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


@dataclass(frozen=True)
class Principal:
    key_id: str
    actor: str
    scopes: set[str]
    admin: bool = False


ADMIN = Principal("dashboard", "dashboard", {"admin"}, True)
BUILTINS = [
    ("space_personal", "Personal", "Personal life and home systems"),
    ("space_work", "Work", "Work-specific knowledge and systems"),
    ("space_general", "General", "Explicitly shared general preferences"),
    ("space_import_review", "Import review", "Restricted records awaiting ownership review"),
]


def _audit(
    c: sqlite3.Connection,
    p: Principal,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict | None = None,
) -> None:
    """Append content-free activity in the same transaction as the mutation.

    The core also runs outside HTTP requests (imports and maintenance). An
    operation ID provides correlation without inventing a browser request ID.
    Free-form titles, reasons, guidance and record contents are never logged.
    """
    c.execute(
        "INSERT INTO event_log(id,request_id,event_type,actor,target_type,target_id,action,success,message,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,1,?,?,?)",
        (
            new_id("evt"),
            new_id("op"),
            target_type + "." + action,
            p.actor,
            target_type,
            target_id,
            action,
            target_type.replace("_", " ").capitalize() + " " + action,
            utc_now(),
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )


def ensure_schema() -> None:
    with connection() as c:
        c.executescript("""
CREATE TABLE IF NOT EXISTS gh2_spaces(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gh2_contexts(principal_id TEXT NOT NULL,session_id TEXT NOT NULL,space_id TEXT NOT NULL REFERENCES gh2_spaces(id),updated_at TEXT NOT NULL,PRIMARY KEY(principal_id,session_id));
CREATE TABLE IF NOT EXISTS gh2_connections(key_id TEXT PRIMARY KEY REFERENCES api_keys(id) ON DELETE CASCADE,default_space_id TEXT REFERENCES gh2_spaces(id));
CREATE TABLE IF NOT EXISTS gh2_grants(key_id TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,space_id TEXT NOT NULL REFERENCES gh2_spaces(id),can_read INTEGER NOT NULL DEFAULT 1,can_write INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(key_id,space_id));
CREATE TABLE IF NOT EXISTS gh2_revisions(id TEXT PRIMARY KEY,memory_id TEXT NOT NULL,version INTEGER NOT NULL,snapshot_json TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gh2_idempotency(principal_id TEXT NOT NULL,key TEXT NOT NULL,request_hash TEXT NOT NULL,response_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(principal_id,key));
CREATE TABLE IF NOT EXISTS gh2_subjects(id TEXT PRIMARY KEY,space_id TEXT NOT NULL REFERENCES gh2_spaces(id),name TEXT NOT NULL,kind TEXT NOT NULL,aliases_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gh2_guidance(id TEXT PRIMARY KEY,space_id TEXT NOT NULL REFERENCES gh2_spaces(id),subject_id TEXT REFERENCES gh2_subjects(id),statement TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gh2_imports(namespace TEXT NOT NULL,source_id TEXT NOT NULL,memory_id TEXT NOT NULL,source_hash TEXT NOT NULL,PRIMARY KEY(namespace,source_id));
""")
        cols = {r["name"] for r in c.execute("PRAGMA table_xinfo(memories)")}
        additions = {
            # v1's external-content FTS column is called tags, while its source
            # JSON column is tags_json. Expose the matching read-only content
            # column so FTS rebuild/integrity checks read the indexed source.
            "tags": "TEXT GENERATED ALWAYS AS (tags_json) VIRTUAL",
            "space_id": "TEXT NOT NULL DEFAULT 'space_import_review'",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "last_verified_at": "TEXT",
            "record_type": "TEXT NOT NULL DEFAULT 'fact'",
            "source_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "subject_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "stale": "INTEGER NOT NULL DEFAULT 0",
            "merged_into": "TEXT",
        }
        for name, definition in additions.items():
            if name not in cols:
                c.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
        for sid, name, desc in BUILTINS:
            c.execute(
                "INSERT OR IGNORE INTO gh2_spaces VALUES(?,?,?,?)", (sid, name, desc, utc_now())
            )
        c.execute("CREATE INDEX IF NOT EXISTS gh2_memory_space ON memories(space_id,archived)")
        # Preserve in-place v1 history in the v2 lifecycle interface. Historical
        # ownership was unknown in v1, so it remains explicitly restricted.
        for revision in c.execute("SELECT * FROM memory_revisions").fetchall():
            owner = c.execute(
                "SELECT category_id FROM memories WHERE id=?", (revision["memory_id"],)
            ).fetchone()
            if owner is None:
                continue
            snapshot = decode(revision)
            snapshot.update(
                id=revision["memory_id"],
                space_id="space_import_review",
                category_id=owner["category_id"],
                version=0,
                record_type="fact",
                source_refs=[],
                subject_ids=[],
                last_verified_at=None,
                merged_into=None,
            )
            for key in ("memory_id", "changed_by", "change_reason"):
                snapshot.pop(key, None)
            c.execute(
                "INSERT OR IGNORE INTO gh2_revisions VALUES(?,?,?,?,?,?,?)",
                (
                    "rev_legacy_" + revision["id"],
                    revision["memory_id"],
                    0,
                    json.dumps(snapshot),
                    revision["changed_by"] or "legacy",
                    revision["change_reason"] or "Preserved v1 history",
                    revision["created_at"],
                ),
            )
        c.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(6,'gh2_spaces_versions_lineage')"
        )


def check_scope(p: Principal, operation: str) -> None:
    if not (p.admin or "admin" in p.scopes or operation in p.scopes):
        raise SpaceError(403, "Insufficient API key scope")


def list_spaces(p: Principal) -> list[dict]:
    with connection() as c:
        if p.admin:
            return [
                dict(r) | {"can_read": True, "can_write": True}
                for r in c.execute("SELECT * FROM gh2_spaces ORDER BY name")
            ]
        return [
            dict(r)
            for r in c.execute(
                "SELECT s.*,g.can_read,g.can_write FROM gh2_spaces s JOIN gh2_grants g ON s.id=g.space_id WHERE g.key_id=? AND (g.can_read=1 OR g.can_write=1) ORDER BY s.name",
                (p.key_id,),
            )
        ]


def readable_spaces(p: Principal) -> list[str]:
    return [s["id"] for s in list_spaces(p) if s["can_read"]]


def require_space(p: Principal, space_id: str, write: bool = False) -> None:
    if not any(
        s["id"] == space_id and s["can_write" if write else "can_read"] for s in list_spaces(p)
    ):
        raise SpaceError(404, "Space unavailable")


def default_space(p: Principal) -> str | None:
    if p.admin:
        return "space_personal"
    with connection() as c:
        row = c.execute(
            "SELECT default_space_id FROM gh2_connections WHERE key_id=?", (p.key_id,)
        ).fetchone()
    return row["default_space_id"] if row else None


def resolve_space(
    p: Principal, space_id: str | None = None, *, write: bool = False, session_id: str | None = None
) -> str:
    session_space = None
    if session_id:
        with connection() as c:
            row = c.execute(
                "SELECT space_id FROM gh2_contexts WHERE principal_id=? AND session_id=?",
                (p.key_id, session_id),
            ).fetchone()
            session_space = row[0] if row else None
    sid = space_id or session_space or default_space(p)
    if not sid:
        raise SpaceError(
            409, "This connection needs a default space or an explicit permitted space"
        )
    require_space(p, sid, write)
    return sid


def create_space(p: Principal, name: str, description: str = "") -> dict:
    if not p.admin:
        raise SpaceError(403, "Dashboard administration required")
    name = name.strip()
    if not name or len(name) > 100:
        raise SpaceError(400, "Space name must contain 1–100 characters")
    sid = new_id("space")
    try:
        with connection() as c:
            c.execute("INSERT INTO gh2_spaces VALUES(?,?,?,?)", (sid, name, description, utc_now()))
            _audit(c, p, "create", "space", sid)
    except sqlite3.IntegrityError as e:
        raise SpaceError(409, "Space name already exists") from e
    return next(s for s in list_spaces(p) if s["id"] == sid)


def update_space(p: Principal, sid: str, data: dict) -> dict:
    if not p.admin:
        raise SpaceError(403, "Dashboard administration required")
    require_space(p, sid, True)
    with connection() as c:
        row = dict(c.execute("SELECT * FROM gh2_spaces WHERE id=?", (sid,)).fetchone())
        name = str(data.get("name", row["name"])).strip()
        if not name or len(name) > 100:
            raise SpaceError(400, "Invalid name")
        try:
            c.execute(
                "UPDATE gh2_spaces SET name=?,description=? WHERE id=?",
                (name, data.get("description", row["description"]), sid),
            )
        except sqlite3.IntegrityError as e:
            raise SpaceError(409, "Space name already exists") from e
        _audit(c, p, "update", "space", sid)
    return next(s for s in list_spaces(p) if s["id"] == sid)


def get_connection(p: Principal, key_id: str) -> dict:
    if not p.admin:
        raise SpaceError(403, "Dashboard administration required")
    with connection() as c:
        if not c.execute("SELECT 1 FROM api_keys WHERE id=?", (key_id,)).fetchone():
            raise SpaceError(404, "API key not found")
        row = c.execute(
            "SELECT default_space_id FROM gh2_connections WHERE key_id=?", (key_id,)
        ).fetchone()
        return {
            "key_id": key_id,
            "default_space_id": row[0] if row else None,
            "grants": [
                dict(r)
                for r in c.execute(
                    "SELECT space_id,can_read,can_write FROM gh2_grants WHERE key_id=?", (key_id,)
                )
            ],
        }


def set_connection(p: Principal, key_id: str, data: dict) -> dict:
    get_connection(p, key_id)
    grants = data.get("grants", [])
    if len({g["space_id"] for g in grants}) != len(grants):
        raise SpaceError(400, "Duplicate space grant")
    for g in grants:
        require_space(p, g["space_id"])
    default = data.get("default_space_id")
    if default and not any(
        g["space_id"] == default and g.get("can_read", True) and g.get("can_write", False)
        for g in grants
    ):
        raise SpaceError(400, "Default space requires read and write grants")
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO gh2_connections VALUES(?,?) ON CONFLICT(key_id) DO UPDATE SET default_space_id=excluded.default_space_id",
            (key_id, default),
        )
        c.execute("DELETE FROM gh2_grants WHERE key_id=?", (key_id,))
        for g in grants:
            c.execute(
                "INSERT INTO gh2_grants VALUES(?,?,?,?)",
                (
                    key_id,
                    g["space_id"],
                    int(g.get("can_read", True)),
                    int(g.get("can_write", False)),
                ),
            )
        _audit(
            c,
            p,
            "grants_update",
            "connection",
            key_id,
            {
                "default_space_id": default,
                "grants": [
                    {
                        "space_id": g["space_id"],
                        "can_read": bool(g.get("can_read", True)),
                        "can_write": bool(g.get("can_write", False)),
                    }
                    for g in grants
                ],
            },
        )
    return get_connection(p, key_id)


def decode(row: sqlite3.Row | dict) -> dict:
    d = dict(row)
    for col, key, default in [
        ("tags_json", "tags", []),
        ("metadata_json", "metadata", {}),
        ("source_refs_json", "source_refs", []),
        ("subject_ids_json", "subject_ids", []),
    ]:
        d[key] = json.loads(d.pop(col, json.dumps(default)) or json.dumps(default))
    d["archived"] = bool(d.get("archived"))
    d["stale"] = bool(d.get("stale"))
    return d


def get_memory(p: Principal, memory_id: str) -> dict:
    check_scope(p, "memories:read")
    with connection() as c:
        row = c.execute(
            "SELECT m.*,s.name AS space_name,cat.name AS category_name FROM memories m JOIN gh2_spaces s ON s.id=m.space_id JOIN memory_categories cat ON cat.id=m.category_id WHERE m.id=?",
            (memory_id,),
        ).fetchone()
    if not row:
        raise SpaceError(404, "Memory unavailable")
    require_space(p, row["space_id"])
    return _visible_record(p, decode(row))


def _visible_record(p, record):
    if record["stale"] and record["record_type"] != "fact" and not p.admin:
        record = record | {
            "title": "Profile requires refresh",
            "summary": None,
            "body": "",
            "metadata": {},
            "source": None,
            "tags": [],
            "source_refs": [],
        }
    return record


def list_memories(
    p: Principal,
    space_id: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    check_scope(p, "memories:read")
    spaces = [resolve_space(p, space_id)] if space_id else readable_spaces(p)
    if not spaces:
        return []
    marks = ",".join("?" for _ in spaces)
    with connection() as c:
        rows = c.execute(
            f"SELECT m.*,s.name AS space_name,cat.name AS category_name FROM memories m JOIN gh2_spaces s ON s.id=m.space_id JOIN memory_categories cat ON cat.id=m.category_id WHERE m.space_id IN ({marks}) "
            + (
                ""
                if include_archived
                else "AND m.archived=0 AND m.merged_into IS NULL AND m.superseded_by IS NULL "
            )
            + "ORDER BY m.updated_at DESC,m.id LIMIT ? OFFSET ?",
            [*spaces, min(500, max(1, limit)), max(0, offset)],
        ).fetchall()
    return [_visible_record(p, decode(r)) for r in rows]


def _fingerprint(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _idempotent(c, p, key, data):
    if not key or len(key) > 200:
        raise SpaceError(400, "An idempotency key of 1–200 characters is required")
    row = c.execute(
        "SELECT * FROM gh2_idempotency WHERE principal_id=? AND key=?", (p.key_id, key)
    ).fetchone()
    if row:
        if row["request_hash"] != _fingerprint(data):
            raise SpaceError(409, "Idempotency key reused with different content")
        result = json.loads(row["response_json"])
        # Replayed results must remain subject to current access, not old grants.
        current = c.execute(
            "SELECT space_id,stale FROM memories WHERE id=?", (result["id"],)
        ).fetchone()
        if not current:
            raise SpaceError(404, "Memory unavailable")
        require_space(p, current["space_id"])
        require_space(p, result["space_id"])
        return _visible_record(p, result | {"stale": bool(current["stale"])})
    return None


def _validate_data(c, p, data, space_id, current=None):
    for field in ("title", "body"):
        if not isinstance(data.get(field), str):
            raise SpaceError(400, field + " must be text")
    if data.get("summary") is not None and (
        not isinstance(data["summary"], str) or len(data["summary"]) > 10000
    ):
        raise SpaceError(400, "Summary must be text of at most 10000 characters")
    if not isinstance(data.get("metadata", {}), dict):
        raise SpaceError(400, "Metadata must be an object")
    for field in ("tags", "source_refs", "subject_ids"):
        if not isinstance(data.get(field, []), list):
            raise SpaceError(400, field + " must be a list")
    if any(
        not isinstance(ref, dict)
        or not isinstance(ref.get("id"), str)
        or not isinstance(ref.get("version"), int)
        for ref in data.get("source_refs", [])
    ):
        raise SpaceError(400, "Source references require id and integer version")
    if any(not isinstance(sid, str) for sid in data.get("subject_ids", [])):
        raise SpaceError(400, "Subject IDs must be strings")
    if not isinstance(data.get("confidence", 3), int) or isinstance(
        data.get("confidence", 3), bool
    ):
        raise SpaceError(400, "Confidence must be an integer")
    if data.get("last_verified_at") is not None:
        from datetime import datetime

        try:
            parsed = datetime.fromisoformat(data["last_verified_at"])
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
        except (ValueError, TypeError, AttributeError) as exc:
            raise SpaceError(400, "Verification timestamp needs ISO format and timezone") from exc
    if not data.get("title") or not str(data.get("title", "")).strip() or len(data["title"]) > 500:
        raise SpaceError(400, "Title must contain 1–500 characters")
    if not data.get("body") or len(data["body"]) > 500000:
        raise SpaceError(400, "Body must contain 1–500000 characters")
    if data.get("auto_prefetch_level", "normal") not in {
        "never",
        "low",
        "normal",
        "high",
        "pinned",
    }:
        raise SpaceError(400, "Invalid recall priority")
    if data.get("record_type", "fact") not in {"fact", "profile", "summary"}:
        raise SpaceError(400, "Invalid record type")
    if not 1 <= int(data.get("confidence", 3)) <= 5:
        raise SpaceError(400, "Confidence must be 1–5")
    if len(json.dumps(data.get("metadata", {}))) > 65536:
        raise SpaceError(400, "Metadata too large")
    if len(data.get("tags", [])) > 100 or any(
        not isinstance(t, str) or len(t) > 100 for t in data.get("tags", [])
    ):
        raise SpaceError(400, "Invalid tags")
    category = data.get("category_id")
    if not category:
        cat = c.execute(
            "SELECT id FROM memory_categories ORDER BY CASE WHEN id='cat_facts' THEN 0 ELSE 1 END LIMIT 1"
        ).fetchone()
        if not cat:
            raise SpaceError(400, "Create a category first")
        data["category_id"] = cat[0]
    elif not c.execute("SELECT 1 FROM memory_categories WHERE id=?", (category,)).fetchone():
        raise SpaceError(400, "Category unavailable")
    for subject in data.get("subject_ids", []):
        row = c.execute("SELECT space_id FROM gh2_subjects WHERE id=?", (subject,)).fetchone()
        if not row or row["space_id"] != space_id:
            raise SpaceError(400, "Subject must belong to the owning space")
    for ref in data.get("source_refs", []):
        if current:
            pending = [ref["id"]]
            seen = set()
            while pending:
                candidate = pending.pop()
                if candidate == current["id"]:
                    raise SpaceError(409, "Evidence lineage must not contain cycles")
                if candidate in seen:
                    continue
                seen.add(candidate)
                evidence = c.execute(
                    "SELECT source_refs_json FROM memories WHERE id=?", (candidate,)
                ).fetchone()
                if evidence:
                    pending.extend(r["id"] for r in json.loads(evidence[0]))
        row = c.execute(
            "SELECT id,space_id,version FROM memories WHERE id=?", (ref.get("id"),)
        ).fetchone()
        if not row or row["space_id"] != space_id:
            raise SpaceError(400, "Evidence must belong to the same space")
        require_space(p, row["space_id"])
        if ref.get("version") != row["version"]:
            raise SpaceError(409, "Source evidence version changed")
    for target in ("superseded_by", "merged_into"):
        if data.get(target):
            row = c.execute(
                "SELECT id,space_id,archived,superseded_by,merged_into FROM memories WHERE id=?",
                (data[target],),
            ).fetchone()
            if not row or row["space_id"] != space_id or (current and row["id"] == current["id"]):
                raise SpaceError(
                    400, "Lifecycle target must be a different memory in the same space"
                )
            if row["archived"] or row["superseded_by"] or row["merged_into"]:
                raise SpaceError(409, "Lifecycle target must be an active canonical memory")
            if current:
                pending = [data[target]]
                seen = set()
                while pending:
                    candidate = pending.pop()
                    if candidate == current["id"]:
                        raise SpaceError(409, "Lifecycle relationships must not contain cycles")
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    link = c.execute(
                        "SELECT superseded_by,merged_into FROM memories WHERE id=?", (candidate,)
                    ).fetchone()
                    if link:
                        pending.extend(value for value in link if value)


_COLUMNS = [
    "category_id",
    "title",
    "summary",
    "body",
    "tags_json",
    "metadata_json",
    "source",
    "confidence",
    "auto_prefetch_level",
    "archived",
    "superseded_by",
    "space_id",
    "version",
    "last_verified_at",
    "record_type",
    "source_refs_json",
    "subject_ids_json",
    "stale",
    "merged_into",
    "created_at",
    "updated_at",
]


def _stored(d):
    result = dict(d)
    for key in ("tags", "metadata", "source_refs", "subject_ids"):
        result[key + "_json"] = json.dumps(
            d.get(key, {} if key == "metadata" else []), sort_keys=True
        )
    return result


def create_memory(
    p: Principal, data: dict, idempotency_key: str, *, guard=None, on_commit=None
) -> dict:
    check_scope(p, "memories:write")
    data = dict(data)
    allowed = {
        "session_id",
        "category_id",
        "title",
        "summary",
        "body",
        "tags",
        "metadata",
        "source",
        "confidence",
        "auto_prefetch_level",
        "archived",
        "superseded_by",
        "space_id",
        "last_verified_at",
        "record_type",
        "source_refs",
        "subject_ids",
        "stale",
        "merged_into",
    }
    if set(data) - allowed:
        raise SpaceError(
            400, "Unsupported create fields: " + ", ".join(sorted(set(data) - allowed))
        )
    request_data = dict(data)
    session_id = data.pop("session_id", None)
    sid = resolve_space(p, data.get("space_id"), write=True, session_id=session_id)
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        if guard:
            guard(c)
        replay = _idempotent(c, p, idempotency_key, request_data)
        if replay:
            if on_commit:
                on_commit(c, replay)
            return replay
        _validate_data(c, p, data, sid)
        now = utc_now()
        d = (
            {
                "category_id": None,
                "title": "",
                "body": "",
                "summary": None,
                "source": None,
                "confidence": 3,
                "auto_prefetch_level": "normal",
                "archived": False,
                "superseded_by": None,
                "last_verified_at": None,
                "record_type": "fact",
                "stale": False,
                "merged_into": None,
            }
            | data
            | {
                "id": new_id("mem"),
                "space_id": sid,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            }
        )
        s = _stored(d)
        c.execute(
            "INSERT INTO memories(id,"
            + ",".join(_COLUMNS)
            + ") VALUES("
            + ",".join("?" for _ in range(len(_COLUMNS) + 1))
            + ")",
            [d["id"]] + [s.get(k) for k in _COLUMNS],
        )
        result = decode(c.execute("SELECT * FROM memories WHERE id=?", (d["id"],)).fetchone())
        c.execute(
            "INSERT INTO gh2_idempotency VALUES(?,?,?,?,?)",
            (p.key_id, idempotency_key, _fingerprint(request_data), json.dumps(result), now),
        )
        _audit(
            c,
            p,
            "create",
            "memory",
            result["id"],
            {"space_id": sid, "version": 1, "record_type": result["record_type"]},
        )
        if on_commit:
            on_commit(c, result)
    return result


def _invalidate(c, memory_id):
    # Transitively invalidate derived output and clear stale content from recall.
    pending = [memory_id]
    seen = set()
    while pending:
        mid = pending.pop()
        if mid in seen:
            continue
        seen.add(mid)
        for r in c.execute(
            "SELECT DISTINCT m.id FROM memories m,json_each(m.source_refs_json) refs WHERE json_extract(refs.value,'$.id')=?",
            (mid,),
        ).fetchall():
            c.execute("UPDATE memories SET stale=1 WHERE id=?", (r["id"],))
            pending.append(r["id"])


def update_memory(
    p: Principal,
    memory_id: str,
    data: dict,
    expected_version: int,
    reason: str | None = None,
    *,
    audit_action: str | None = None,
    guard=None,
    on_commit=None,
) -> dict:
    check_scope(p, "memories:write")
    allowed = {
        "category_id",
        "title",
        "summary",
        "body",
        "tags",
        "metadata",
        "source",
        "confidence",
        "auto_prefetch_level",
        "archived",
        "superseded_by",
        "space_id",
        "last_verified_at",
        "record_type",
        "source_refs",
        "subject_ids",
        "stale",
        "merged_into",
    }
    unknown = set(data) - allowed
    if unknown:
        raise SpaceError(400, "Unsupported update fields: " + ", ".join(sorted(unknown)))
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        if guard:
            guard(c)
        row = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not row:
            raise SpaceError(404, "Memory unavailable")
        require_space(p, row["space_id"], True)
        if row["version"] != expected_version:
            raise SpaceError(409, f"Memory changed; current version is {row['version']}")
        old = decode(row)
        d = old | data
        require_space(p, d["space_id"], True)
        if d["space_id"] != old["space_id"] and old["source_refs"]:
            raise SpaceError(409, "Derived records must be rebuilt in the destination space")
        _validate_data(c, p, d, d["space_id"], old)
        rev = new_id("rev")
        now = utc_now()
        c.execute(
            "INSERT INTO gh2_revisions VALUES(?,?,?,?,?,?,?)",
            (rev, memory_id, old["version"], json.dumps(old), p.actor, reason, now),
        )
        d["version"] = old["version"] + 1
        d["updated_at"] = now
        s = _stored(d)
        c.execute(
            "UPDATE memories SET " + ",".join(k + "=?" for k in _COLUMNS) + " WHERE id=?",
            [s.get(k) for k in _COLUMNS] + [memory_id],
        )
        _invalidate(c, memory_id)
        result = decode(c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())
        action = audit_action or (
            "move"
            if d["space_id"] != old["space_id"]
            else "archive"
            if d["archived"] and not old["archived"]
            else "unarchive"
            if old["archived"] and not d["archived"]
            else "merge"
            if d["merged_into"] != old["merged_into"]
            else "supersede"
            if d["superseded_by"] != old["superseded_by"]
            else "update"
        )
        if action not in {
            "update",
            "move",
            "archive",
            "unarchive",
            "merge",
            "supersede",
            "restore",
        }:
            raise ValueError("Unsupported audit action")
        _audit(
            c,
            p,
            action,
            "memory",
            memory_id,
            {
                "space_id": d["space_id"],
                "previous_space_id": old["space_id"],
                "version": d["version"],
                "previous_version": old["version"],
                "revision_id": rev,
                "changed_fields": sorted(data),
            },
        )
        if on_commit:
            on_commit(c, result)
    return result


def revisions(p, memory_id):
    get_memory(p, memory_id)
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM gh2_revisions WHERE memory_id=? ORDER BY version DESC", (memory_id,)
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        snapshot = json.loads(item.pop("snapshot_json"))
        # A move does not grant the destination access to previous-space data.
        try:
            require_space(p, snapshot["space_id"])
        except SpaceError:
            continue
        if snapshot.get("source_refs") and not p.admin:
            with connection() as c:
                for ref in snapshot["source_refs"]:
                    source = c.execute(
                        "SELECT space_id FROM memories WHERE id=?", (ref.get("id"),)
                    ).fetchone()
                    if not source or source["space_id"] != snapshot["space_id"]:
                        break
                else:
                    item["snapshot"] = snapshot
                    result.append(item)
            continue
        item["snapshot"] = snapshot
        result.append(item)
    return result


def restore(p, memory_id, revision_id, expected_version):
    revision = next((r for r in revisions(p, memory_id) if r["id"] == revision_id), None)
    if not revision:
        raise SpaceError(404, "Revision unavailable")
    snapshot = dict(revision["snapshot"])
    if "tags_json" in snapshot:
        snapshot = decode(snapshot)
    if snapshot.get("version") is None and "original_memory_id" in snapshot:
        snapshot["category_id"] = get_memory(p, memory_id)["category_id"]
    for extra in (
        "memory_id",
        "changed_by",
        "change_reason",
        "import_namespace",
        "original_memory_id",
    ):
        snapshot.pop(extra, None)
    fields = {
        k: v
        for k, v in snapshot.items()
        if k not in {"id", "version", "created_at", "updated_at", "space_name", "category_name"}
    }
    return update_memory(
        p, memory_id, fields, expected_version, "Restore " + revision_id, audit_action="restore"
    )


def _bounded_result(record: dict, budget: int) -> dict | None:
    """Bound serialized result content, including titles, lineage and metadata.

    When full text cannot fit, preserve identity and indicate truncation. A
    caller can retrieve the full record/lineage by ID instead of losing an
    otherwise relevant result because its summary alone exceeds the budget.
    """
    keys = (
        "id",
        "version",
        "space_id",
        "space_name",
        "title",
        "summary",
        "source",
        "last_verified_at",
        "updated_at",
        "record_type",
        "source_refs",
        "stale",
        "body",
    )
    result = {key: record[key] for key in keys}
    size = lambda: len(json.dumps(result, ensure_ascii=False))
    if size() <= budget:
        return result
    result["truncated"] = True
    for field in ("body", "summary", "source"):
        result.pop(field, None)
    refs = result["source_refs"]
    if size() > budget and refs:
        result["source_refs_count"] = len(refs)
        result["source_refs_truncated"] = True
        low, high = 0, len(refs)
        while low < high:
            middle = (low + high + 1) // 2
            result["source_refs"] = refs[:middle]
            if size() <= budget:
                low = middle
            else:
                high = middle - 1
        result["source_refs"] = refs[:low]
    if size() > budget:
        result["title"] = result["title"][:64]
    for field in ("last_verified_at", "updated_at", "space_name"):
        if size() > budget:
            result.pop(field, None)
    if size() > budget:
        result["title"] = result["title"][:16]
    if size() > budget:
        return None
    for field in ("summary", "body"):
        value = record.get(field)
        if not value:
            continue
        result[field] = ""
        if size() > budget:
            result.pop(field)
            continue
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            result[field] = value[:middle]
            if size() <= budget:
                low = middle
            else:
                high = middle - 1
        if low:
            result[field] = value[:low]
        else:
            result.pop(field)
    return result


def search(
    p: Principal,
    query: str = "",
    space_id: str | None = None,
    broaden: bool = False,
    limit: int = 10,
    max_chars: int = 12000,
    recall: bool = False,
    subject_ids: list[str] | None = None,
    session_id: str | None = None,
) -> dict:
    check_scope(p, "memories:read")
    active = resolve_space(p, space_id, session_id=session_id)
    spaces = readable_spaces(p) if broaden else [active]
    if recall and "space_general" in readable_spaces(p) and "space_general" not in spaces:
        spaces.append("space_general")
    marks = ",".join("?" for _ in spaces)
    terms = re.findall(r"[\w]+", query.lower())[:64]
    candidate_limit = min(1000, max(64, limit * 8))
    select = "SELECT m.*,s.name AS space_name,cat.name AS category_name"
    joins = (
        " JOIN gh2_spaces s ON s.id=m.space_id JOIN memory_categories cat ON cat.id=m.category_id "
    )
    where = f"m.space_id IN ({marks}) AND m.archived=0 AND m.superseded_by IS NULL AND m.merged_into IS NULL AND (m.stale=0 OR m.record_type='fact')"
    if recall:
        where += " AND m.auto_prefetch_level!='never'"
    with connection() as c:
        if terms:
            # Tokens are quoted individually: operators and punctuation from user
            # text can never become FTS syntax. Ownership filters precede LIMIT,
            # so inaccessible records cannot exhaust the candidate shortlist.
            fts = " OR ".join('"' + term.replace('"', '""') + '"*' for term in terms)
            rows = c.execute(
                select
                + ",bm25(memories_fts,8.0,4.0,1.0,6.0) AS fts_rank FROM memories_fts JOIN memories m ON m.rowid=memories_fts.rowid"
                + joins
                + " WHERE memories_fts MATCH ? AND "
                + where
                + " ORDER BY fts_rank,m.updated_at DESC,m.id LIMIT ?",
                [fts, *spaces, candidate_limit],
            ).fetchall()
        elif not query.strip():
            rows = c.execute(
                select
                + ",0.0 AS fts_rank FROM memories m"
                + joins
                + " WHERE "
                + where
                + " ORDER BY m.updated_at DESC,m.id LIMIT ?",
                [*spaces, candidate_limit],
            ).fetchall()
        else:
            rows = []
        matched_ids = {row["id"] for row in rows}
        if recall:
            pins = c.execute(
                select
                + ",0.0 AS fts_rank FROM memories m"
                + joins
                + " WHERE "
                + where
                + " AND m.auto_prefetch_level='pinned' ORDER BY m.updated_at DESC,m.id LIMIT ?",
                [*spaces, min(256, max(16, limit * 4))],
            ).fetchall()
            rows = list(rows) + [row for row in pins if row["id"] not in matched_ids]
    scored = []
    for row in rows:
        d = decode(row)
        if d["stale"] and d["record_type"] != "fact":
            continue
        if recall and d["auto_prefetch_level"] == "never":
            continue
        text = (" ".join([d["title"], d["summary"] or "", d["body"], " ".join(d["tags"])])).lower()
        matches = sum(1 for term in terms if term in text)
        pinned = recall and d["auto_prefetch_level"] == "pinned"
        if query.strip() and d["id"] not in matched_ids and not pinned:
            continue
        score = (
            matches
            + sum(2 for term in terms if term in d["title"].lower())
            + (2 if set(subject_ids or []) & set(d["subject_ids"]) else 0)
        )
        scored.append((score, d, pinned))
    scored.sort(
        key=lambda item: (
            item[0],
            -float(item[1].get("fts_rank", 0)),
            item[1]["updated_at"],
            item[1]["id"],
        ),
        reverse=True,
    )
    # At most a quarter of the requested count is reserved for unmatched pins.
    results = []
    used = 0
    pin_count = 0
    for score, d, pinned in scored:
        if len(results) >= limit:
            break
        if pinned and not score:
            if pin_count >= max(1, limit // 4):
                continue
            pin_count += 1
        concise = _bounded_result(d, max_chars - used)
        if concise is None:
            continue
        used += len(json.dumps(concise, ensure_ascii=False))
        results.append(concise)
    return {
        "results": results,
        "context": {
            "active_space_id": active,
            "default_space_id": default_space(p),
            "searched_space_ids": spaces,
            "expanded": bool(broaden),
        },
        "estimated_tokens": (used + 3) // 4,
        "character_count": used,
    }


def subjects(p: Principal, space_id: str | None = None) -> list[dict]:
    check_scope(p, "memories:read")
    spaces = [resolve_space(p, space_id)] if space_id else readable_spaces(p)
    if not spaces:
        return []
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM gh2_subjects WHERE space_id IN ("
            + ",".join("?" for _ in spaces)
            + ") ORDER BY name",
            spaces,
        ).fetchall()
    return [dict(r) | {"aliases": json.loads(r["aliases_json"])} for r in rows]


def create_subject(p: Principal, data: dict) -> dict:
    check_scope(p, "memories:write")
    sid = resolve_space(p, data.get("space_id"), write=True)
    if not data.get("name", "").strip() or len(data["name"]) > 200:
        raise SpaceError(400, "Subject name is required (maximum 200 characters)")
    item = {
        "id": new_id("subject"),
        "space_id": sid,
        "name": data["name"].strip(),
        "kind": data.get("kind", "topic"),
        "aliases": data.get("aliases", []),
        "created_at": utc_now(),
    }
    with connection() as c:
        c.execute(
            "INSERT INTO gh2_subjects VALUES(?,?,?,?,?,?)",
            (
                item["id"],
                sid,
                item["name"],
                item["kind"],
                json.dumps(item["aliases"]),
                item["created_at"],
            ),
        )
    return item


def guidance(p: Principal, space_id: str | None = None) -> list[dict]:
    check_scope(p, "memories:read")
    spaces = [resolve_space(p, space_id)] if space_id else readable_spaces(p)
    if not spaces:
        return []
    with connection() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM gh2_guidance WHERE space_id IN ("
                + ",".join("?" for _ in spaces)
                + ") ORDER BY created_at",
                spaces,
            )
        ]


def create_guidance(p: Principal, data: dict) -> dict:
    if not p.admin:
        raise SpaceError(403, "Only the owner may confirm placement guidance")
    sid = resolve_space(p, data.get("space_id"), write=True)
    statement = data.get("statement", "").strip()
    if not statement or len(statement) > 4000:
        raise SpaceError(400, "Guidance must contain 1–4000 characters")
    item = {
        "id": new_id("guidance"),
        "space_id": sid,
        "subject_id": data.get("subject_id"),
        "statement": statement,
        "confirmed": True,
        "version": 1,
        "created_at": utc_now(),
    }
    with connection() as c:
        if (
            item["subject_id"]
            and not c.execute(
                "SELECT 1 FROM gh2_subjects WHERE id=? AND space_id=?", (item["subject_id"], sid)
            ).fetchone()
        ):
            raise SpaceError(400, "Subject unavailable")
        c.execute("INSERT INTO gh2_guidance VALUES(?,?,?,?,?,?,?)", tuple(item.values()))
        _audit(
            c,
            p,
            "create",
            "guidance",
            item["id"],
            {"space_id": sid, "version": 1, "subject_id": item["subject_id"]},
        )
    return item


def delete_guidance(p: Principal, guidance_id: str) -> None:
    if not p.admin:
        raise SpaceError(403, "Dashboard administration required")
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT space_id,subject_id,version FROM gh2_guidance WHERE id=?", (guidance_id,)
        ).fetchone()
        c.execute("DELETE FROM gh2_guidance WHERE id=?", (guidance_id,))
        if row:
            _audit(c, p, "delete", "guidance", guidance_id, dict(row))


def export_memories(p: Principal) -> dict:
    if not p.admin:
        raise SpaceError(403, "Dashboard administration required")
    with connection() as c:
        memories = [decode(r) for r in c.execute("SELECT * FROM memories ORDER BY id")]
        categories = [dict(r) for r in c.execute("SELECT * FROM memory_categories")]
        legacy_revisions = [dict(r) for r in c.execute("SELECT * FROM memory_revisions")]
        legacy_copies = {"rev_legacy_" + revision["id"] for revision in legacy_revisions}
        new_revisions = [
            dict(r)
            for r in c.execute("SELECT * FROM gh2_revisions")
            if r["id"] not in legacy_copies
        ]
    return {
        "format": "glyphhold-memory-export",
        "version": 2,
        "exported_at": utc_now(),
        "memories": memories,
        "categories": categories,
        "revisions": legacy_revisions,
        "v2_revisions": new_revisions,
        "subjects": subjects(p),
        "guidance": guidance(p),
        "spaces": list_spaces(p),
    }


def _mapped(namespace: str, source_id: str) -> str:
    return "mem_import_" + hashlib.sha256((namespace + "\0" + source_id).encode()).hexdigest()[:28]


def import_preview(p: Principal, payload: dict) -> dict:
    if not p.admin:
        raise SpaceError(403, "Dashboard administration required")
    namespace = str(payload.get("namespace", "")).strip()
    if not namespace or len(namespace) > 200:
        raise SpaceError(400, "A unique source namespace is required")
    document = payload.get("document") or payload.get("data") or {}
    if not isinstance(document, dict) or not isinstance(document.get("memories"), list):
        raise SpaceError(400, "Expected a memory export document")
    if len(document["memories"]) > 50000:
        raise SpaceError(400, "Import contains too many records; split into bounded exports")
    sid = payload.get("space_id") or "space_import_review"
    require_space(p, sid, True)
    seen = set()
    new = existing = 0
    conflicts = []
    errors = []
    with connection() as c:
        for m in document["memories"]:
            source_id = m.get("id")
            if not source_id or source_id in seen:
                errors.append("Missing or duplicate source ID")
                continue
            seen.add(source_id)
            if not m.get("title") or not m.get("body"):
                errors.append(f"{source_id}: missing title or body")
                continue
            imported = c.execute(
                "SELECT source_hash FROM gh2_imports WHERE namespace=? AND source_id=?",
                (namespace, source_id),
            ).fetchone()
            if imported:
                existing += 1
                if imported[0] != _fingerprint(m):
                    conflicts.append(source_id)
            else:
                new += 1
            for relation in ("superseded_by", "merged_into"):
                if m.get(relation) and not any(
                    o.get("id") == m[relation] for o in document["memories"]
                ):
                    errors.append(f"{source_id}: unresolved {relation}")
    return {
        "namespace": namespace,
        "space_id": sid,
        "total": len(document["memories"]),
        "new": new,
        "existing": existing,
        "conflicts": conflicts,
        "errors": errors,
        "can_apply": not (errors or conflicts),
        "secrets_included": False,
    }


def import_apply(p: Principal, payload: dict) -> dict:
    preview = import_preview(p, payload)
    if not preview["can_apply"]:
        raise SpaceError(409, "Import has errors or changed source records; review preview")
    document = payload.get("document") or payload.get("data")
    namespace = preview["namespace"]
    sid = preview["space_id"]
    mappings = {m["id"]: _mapped(namespace, m["id"]) for m in document["memories"]}
    core_import_new = {}
    subject_map = {
        item["id"]: "subject_import_"
        + hashlib.sha256((namespace + "\0" + item["id"]).encode()).hexdigest()[:24]
        for item in document.get("subjects", [])
    }
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        for item in document.get("subjects", []):
            c.execute(
                "INSERT OR IGNORE INTO gh2_subjects VALUES(?,?,?,?,?,?)",
                (
                    subject_map[item["id"]],
                    sid,
                    item["name"],
                    item.get("kind", "topic"),
                    json.dumps(item.get("aliases", [])),
                    item.get("created_at") or utc_now(),
                ),
            )
        for item in document.get("guidance", []):
            guidance_id = (
                "guidance_import_"
                + hashlib.sha256((namespace + "\0" + item["id"]).encode()).hexdigest()[:24]
            )
            c.execute(
                "INSERT OR IGNORE INTO gh2_guidance VALUES(?,?,?,?,?,?,?)",
                (
                    guidance_id,
                    sid,
                    subject_map.get(item.get("subject_id")),
                    item["statement"],
                    int(item.get("confirmed", True)),
                    item.get("version", 1),
                    item.get("created_at") or utc_now(),
                ),
            )
        for cat in document.get("categories", []):
            category_id = (
                "cat_import_"
                + hashlib.sha256((namespace + "\0" + cat["id"]).encode()).hexdigest()[:24]
            )
            c.execute(
                "INSERT OR IGNORE INTO memory_categories(id,name,description,allow_auto_prefetch,agent_can_create,agent_can_write,created_at,updated_at) VALUES(?,?,?,1,1,1,?,?)",
                (
                    category_id,
                    namespace + ": " + cat["name"],
                    cat.get("description"),
                    cat.get("created_at") or utc_now(),
                    cat.get("updated_at") or utc_now(),
                ),
            )
        for m in document["memories"]:
            previous = c.execute(
                "SELECT * FROM gh2_imports WHERE namespace=? AND source_id=?", (namespace, m["id"])
            ).fetchone()
            if previous:
                if previous["source_hash"] != _fingerprint(m):
                    raise SpaceError(409, "Concurrent import source mismatch")
                continue
            core_import_new[m["id"]] = True
            category_id = (
                "cat_import_"
                + hashlib.sha256(
                    (namespace + "\0" + str(m.get("category_id", ""))).encode()
                ).hexdigest()[:24]
            )
            if not c.execute(
                "SELECT 1 FROM memory_categories WHERE id=?", (category_id,)
            ).fetchone():
                c.execute(
                    "INSERT INTO memory_categories(id,name,description,allow_auto_prefetch,agent_can_create,agent_can_write,created_at,updated_at) VALUES(?,?,?,1,1,1,?,?)",
                    (
                        category_id,
                        namespace + ": " + str(m.get("category_id", "Imported")),
                        "Imported category",
                        utc_now(),
                        utc_now(),
                    ),
                )
            d = {
                "summary": None,
                "source": None,
                "confidence": 3,
                "auto_prefetch_level": "normal",
                "archived": False,
                "superseded_by": None,
                "last_verified_at": None,
                "record_type": "fact",
                "stale": False,
                "merged_into": None,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            } | m
            for key in ("tags", "metadata", "source_refs", "subject_ids"):
                d[key] = m.get(
                    key, json.loads(m.get(key + "_json") or ("{}" if key == "metadata" else "[]"))
                )
            # Preserve the unmodified original including associations in provenance.
            d["metadata"] = d["metadata"] | {
                "import": {"namespace": namespace, "source_id": m["id"], "original": m}
            }
            d.update(
                id=mappings[m["id"]],
                space_id=sid,
                category_id=category_id,
                version=1,
                subject_ids=[
                    subject_map[subject] for subject in d["subject_ids"] if subject in subject_map
                ],
            )
            d["source_refs"] = [
                {"id": mappings[r["id"]], "version": 1}
                for r in d["source_refs"]
                if r.get("id") in mappings
            ]
            d["superseded_by"] = mappings.get(m.get("superseded_by"))
            d["merged_into"] = mappings.get(m.get("merged_into"))
            # Insert relationships after every target exists, including forward references.
            d["superseded_by"] = None
            s = _stored(d)
            c.execute(
                "INSERT INTO memories(id,"
                + ",".join(_COLUMNS)
                + ") VALUES("
                + ",".join("?" for _ in range(len(_COLUMNS) + 1))
                + ")",
                [d["id"]] + [s.get(k) for k in _COLUMNS],
            )
            c.execute(
                "INSERT INTO gh2_imports VALUES(?,?,?,?)",
                (namespace, m["id"], d["id"], _fingerprint(m)),
            )
        for m in document["memories"]:
            if m.get("superseded_by") and core_import_new.get(m["id"], False):
                c.execute(
                    "UPDATE memories SET superseded_by=? WHERE id=?",
                    (mappings[m["superseded_by"]], mappings[m["id"]]),
                )
        for r in document.get("revisions", []):
            source_memory = r.get("memory_id")
            if source_memory not in mappings:
                continue
            revision_id = (
                "rev_import_"
                + hashlib.sha256((namespace + "\0" + r["id"]).encode()).hexdigest()[:28]
            )
            # Full source snapshot is retained rather than guessing a historical owner/version.
            snapshot = dict(r) | {
                "id": mappings[source_memory],
                "space_id": sid,
                "import_namespace": namespace,
                "original_memory_id": source_memory,
            }
            c.execute(
                "INSERT OR IGNORE INTO gh2_revisions VALUES(?,?,?,?,?,?,?)",
                (
                    revision_id,
                    mappings[source_memory],
                    0,
                    json.dumps(snapshot),
                    r.get("changed_by") or "import",
                    r.get("change_reason") or "Imported v1 revision",
                    r.get("created_at") or utc_now(),
                ),
            )
        for r in document.get("v2_revisions", []):
            if r.get("memory_id") not in mappings:
                continue
            rid = (
                "rev_import_"
                + hashlib.sha256((namespace + "\0" + r["id"]).encode()).hexdigest()[:28]
            )
            snapshot = json.loads(r["snapshot_json"])
            snapshot["space_id"] = sid
            snapshot["id"] = mappings[r["memory_id"]]
            snapshot["source_refs"] = [
                {"id": mappings[ref["id"]], "version": 1}
                for ref in snapshot.get("source_refs", [])
                if ref.get("id") in mappings
            ]
            snapshot["subject_ids"] = [
                subject_map[subject]
                for subject in snapshot.get("subject_ids", [])
                if subject in subject_map
            ]
            snapshot["category_id"] = (
                "cat_import_"
                + hashlib.sha256(
                    (namespace + "\0" + str(snapshot.get("category_id", ""))).encode()
                ).hexdigest()[:24]
            )
            for key in ("superseded_by", "merged_into"):
                snapshot[key] = mappings.get(snapshot.get(key))
            c.execute(
                "INSERT OR IGNORE INTO gh2_revisions VALUES(?,?,?,?,?,?,?)",
                (
                    rid,
                    mappings[r["memory_id"]],
                    r["version"],
                    json.dumps(snapshot),
                    r.get("actor", "import"),
                    r.get("reason"),
                    r.get("created_at") or utc_now(),
                ),
            )
    return preview | {"applied": True, "mappings": mappings}


def get_context(p: Principal, session_id: str) -> dict:
    check_scope(p, "memories:read")
    if not session_id or len(session_id) > 200:
        raise SpaceError(400, "Session ID must contain 1–200 characters")
    sid = resolve_space(p, session_id=session_id)
    return {
        "session_id": session_id,
        "space_id": sid,
        "default_space_id": default_space(p),
        "guidance": guidance(p, sid),
    }


def set_context(p: Principal, session_id: str, space_id: str) -> dict:
    check_scope(p, "memories:read")
    if not session_id or len(session_id) > 200:
        raise SpaceError(400, "Session ID must contain 1–200 characters")
    require_space(p, space_id)
    with connection() as c:
        c.execute(
            "INSERT INTO gh2_contexts VALUES(?,?,?,?) ON CONFLICT(principal_id,session_id) DO UPDATE SET space_id=excluded.space_id,updated_at=excluded.updated_at",
            (p.key_id, session_id, space_id, utc_now()),
        )
    return get_context(p, session_id)
