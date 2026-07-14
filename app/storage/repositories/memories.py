from __future__ import annotations

import json
import re
from typing import Any

from app.core.ids import new_id
from app.storage.db import connection
from app.utils.time import utc_now

VALID_PREFETCH_LEVELS = {"never", "low", "normal", "high", "pinned"}
STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "who",
    "with",
}


def _json(value: Any, default: Any) -> str:
    return json.dumps(default if value is None else value, sort_keys=True)


def _terms(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9_]+", value.lower())
        if token not in STOP_WORDS
    ]


def _fts_query(query: str, *, operator: str = "OR") -> str:
    return f" {operator} ".join(f"{token}*" for token in _terms(query))


def _normalize_tags(tags: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags or []:
        tag = raw_tag.strip().lower()
        if tag and tag not in seen:
            normalized.append(tag)
            seen.add(tag)
    return normalized


def list_memories(
    *,
    category: str | None = None,
    tag: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where = []
    values: list[Any] = []
    joins = ["JOIN memory_categories c ON c.id = m.category_id"]
    if not include_archived:
        where.append("m.archived = 0")
    if category:
        where.append("(c.id = ? OR c.name = ?)")
        values.extend([category, category])
    if tag:
        where.append(
            "EXISTS (SELECT 1 FROM json_each(m.tags_json) WHERE lower(json_each.value) = lower(?))"
        )
        values.append(tag.strip())
    values.extend([limit, offset])
    sql = f"""
        SELECT m.*, c.name AS category_name
        FROM memories m
        {' '.join(joins)}
        {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY m.updated_at DESC
        LIMIT ? OFFSET ?
    """
    with connection() as conn:
        rows = conn.execute(sql, values).fetchall()
        return [dict(row) for row in rows]


def get_memory(memory_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT m.*, c.name AS category_name
            FROM memories m
            JOIN memory_categories c ON c.id = m.category_id
            WHERE m.id = ?
            """,
            (memory_id,),
        ).fetchone()
        return dict(row) if row else None


def create_memory(
    *,
    category_id: str,
    title: str,
    body: str,
    summary: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source: str | None = None,
    confidence: int = 3,
    auto_prefetch_level: str = "normal",
) -> dict[str, Any]:
    if auto_prefetch_level not in VALID_PREFETCH_LEVELS:
        raise ValueError("Invalid auto_prefetch_level")
    if confidence < 1 or confidence > 5:
        raise ValueError("confidence must be between 1 and 5")

    memory_id = new_id("mem")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO memories (
                id, category_id, title, summary, body, tags_json, metadata_json,
                source, confidence, auto_prefetch_level, archived, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                memory_id,
                category_id,
                title,
                summary,
                body,
                _json(_normalize_tags(tags), []),
                _json(metadata, {}),
                source,
                confidence,
                auto_prefetch_level,
                now,
                now,
            ),
        )
    memory = get_memory(memory_id)
    assert memory is not None
    return memory


def _save_revision(
    conn,
    memory: dict[str, Any],
    *,
    changed_by: str | None,
    change_reason: str | None,
) -> str:
    revision_id = new_id("rev")
    conn.execute(
        """
        INSERT INTO memory_revisions (
            id, memory_id, title, summary, body, tags_json, metadata_json, confidence,
            auto_prefetch_level, archived, superseded_by, changed_by, change_reason,
            created_at, category_id, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            memory["id"],
            memory["title"],
            memory["summary"],
            memory["body"],
            memory["tags_json"],
            memory["metadata_json"],
            memory["confidence"],
            memory["auto_prefetch_level"],
            memory["archived"],
            memory["superseded_by"],
            changed_by,
            change_reason,
            utc_now(),
            memory["category_id"],
            memory["source"],
        ),
    )
    return revision_id


def update_memory(
    memory_id: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
    **fields: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    existing = get_memory(memory_id)
    if existing is None:
        return None, None

    updates: dict[str, Any] = {}
    nullable_fields = {"summary", "source", "superseded_by"}
    for key in (
        "category_id",
        "title",
        "summary",
        "body",
        "source",
        "confidence",
        "auto_prefetch_level",
        "archived",
        "superseded_by",
    ):
        if key in fields and (fields[key] is not None or key in nullable_fields):
            updates[key] = fields[key]
    if fields.get("tags") is not None:
        updates["tags_json"] = _json(_normalize_tags(fields["tags"]), [])
    if fields.get("metadata") is not None:
        updates["metadata_json"] = _json(fields["metadata"], {})
    if not updates:
        return existing, None

    if "confidence" in updates and (int(updates["confidence"]) < 1 or int(updates["confidence"]) > 5):
        raise ValueError("confidence must be between 1 and 5")
    if "auto_prefetch_level" in updates and updates["auto_prefetch_level"] not in VALID_PREFETCH_LEVELS:
        raise ValueError("Invalid auto_prefetch_level")

    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [int(value) if isinstance(value, bool) else value for value in updates.values()]
    values.append(memory_id)
    with connection() as conn:
        revision_id = _save_revision(conn, existing, changed_by=changed_by, change_reason=change_reason)
        conn.execute(f"UPDATE memories SET {assignments} WHERE id = ?", values)
    return get_memory(memory_id), revision_id


def archive_memory(memory_id: str, *, changed_by: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    return update_memory(memory_id, archived=True, changed_by=changed_by, change_reason="archive")


def supersede_memory(
    memory_id: str,
    superseded_by: str,
    *,
    changed_by: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    return update_memory(
        memory_id,
        superseded_by=superseded_by,
        archived=True,
        changed_by=changed_by,
        change_reason="supersede",
    )


def delete_memory(memory_id: str) -> bool:
    with connection() as conn:
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0


def search_memories(
    *,
    query: str,
    category: str | None = None,
    include_archived: bool = False,
    limit: int = 10,
    auto_prefetch_only: bool = False,
) -> list[dict[str, Any]]:
    fts_and = _fts_query(query, operator="AND")
    fts_or = _fts_query(query, operator="OR")
    values: list[Any] = []
    where = []
    if not include_archived:
        where.append("m.archived = 0")
    if category:
        where.append("(c.id = ? OR c.name = ?)")
        values.extend([category, category])
    if auto_prefetch_only:
        where.append("c.allow_auto_prefetch = 1")

    with connection() as conn:
        if fts_or:
            sql = f"""
                SELECT m.*, c.name AS category_name,
                       bm25(memories_fts, 8.0, 4.0, 1.0, 6.0) AS fts_rank
                FROM memories_fts
                JOIN memories m ON m.rowid = memories_fts.rowid
                JOIN memory_categories c ON c.id = m.category_id
                {'WHERE ' + ' AND '.join(['memories_fts MATCH ?'] + where)}
                ORDER BY fts_rank
                LIMIT ?
            """
            rows = []
            seen: set[str] = set()
            for fts in dict.fromkeys([fts_and, fts_or]):
                if not fts or len(rows) >= limit:
                    continue
                matches = conn.execute(sql, [fts, *values, limit]).fetchall()
                for row in matches:
                    if row["id"] not in seen:
                        rows.append(row)
                        seen.add(row["id"])
                    if len(rows) >= limit:
                        break
            return [dict(row) for row in rows]

        return list_memories(category=category, include_archived=include_archived, limit=limit)


def list_pinned_memories(*, limit: int = 100) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT m.*, c.name AS category_name
            FROM memories m
            JOIN memory_categories c ON c.id = m.category_id
            WHERE m.archived = 0
              AND m.auto_prefetch_level = 'pinned'
              AND c.allow_auto_prefetch = 1
            ORDER BY m.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_revisions(memory_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM memory_revisions
            WHERE memory_id = ?
            ORDER BY created_at DESC
            """,
            (memory_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_revision(memory_id: str, revision_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM memory_revisions
            WHERE memory_id = ? AND id = ?
            """,
            (memory_id, revision_id),
        ).fetchone()
        return dict(row) if row else None


def restore_revision(
    memory_id: str,
    revision_id: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    existing = get_memory(memory_id)
    if existing is None:
        return None, None
    revision = get_revision(memory_id, revision_id)
    if revision is None:
        return None, None

    restored = {
        "category_id": revision.get("category_id") or existing["category_id"],
        "title": revision["title"],
        "summary": revision["summary"],
        "body": revision["body"],
        "tags_json": revision["tags_json"],
        "metadata_json": revision["metadata_json"],
        "source": revision.get("source") or existing["source"],
        "confidence": revision["confidence"],
        "auto_prefetch_level": revision["auto_prefetch_level"],
        "archived": revision["archived"],
        "superseded_by": revision["superseded_by"],
        "updated_at": utc_now(),
    }
    assignments = ", ".join(f"{key} = ?" for key in restored)
    values = list(restored.values())
    values.append(memory_id)

    with connection() as conn:
        restore_revision_id = _save_revision(
            conn,
            existing,
            changed_by=changed_by,
            change_reason=change_reason or f"restore:{revision_id}",
        )
        conn.execute(f"UPDATE memories SET {assignments} WHERE id = ?", values)
    return get_memory(memory_id), restore_revision_id


def find_similar(
    *,
    category: str | None,
    title: str,
    body: str,
    tags: list[str] | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    candidates = search_memories(query=f"{title} {body}", category=category, limit=max(limit * 4, 10))
    tag_set = {tag.lower() for tag in tags or []}
    title_terms = set(_terms(title))
    body_terms = set(_terms(body))
    results = []
    for memory in candidates:
        reasons = []
        score = 0.0
        memory_title_terms = set(_terms(memory["title"]))
        overlap = title_terms & memory_title_terms
        if overlap:
            score += min(0.45, 0.15 * len(overlap))
            reasons.append(f"title terms: {', '.join(sorted(overlap))}")
        candidate_terms = set(_terms(f"{memory.get('summary') or ''} {memory['body']}"))
        body_overlap = body_terms & candidate_terms
        if body_overlap:
            body_ratio = len(body_overlap) / max(1, min(len(body_terms), len(candidate_terms)))
            score += min(0.35, 0.35 * body_ratio)
            reasons.append(f"content overlap: {len(body_overlap)} terms")
        memory_tags = {tag.lower() for tag in json.loads(memory["tags_json"] or "[]")}
        tag_overlap = tag_set & memory_tags
        if tag_overlap:
            score += min(0.35, 0.12 * len(tag_overlap))
            reasons.append(f"tags: {', '.join(sorted(tag_overlap))}")
        if category and category in {memory.get("category_id"), memory.get("category_name")}:
            score += 0.15
            reasons.append(f"category: {category}")
        if score > 0:
            item = dict(memory)
            item["match_score"] = round(min(score, 1.0), 2)
            item["match_reasons"] = reasons
            results.append(item)
    return sorted(results, key=lambda item: item["match_score"], reverse=True)[:limit]
