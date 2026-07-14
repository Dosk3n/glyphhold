from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.storage.db import connect
from app.storage.migrations import MIGRATIONS, apply_migrations, current_schema_version


def _apply_migration_versions(db_path: Path, versions: set[int]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        for migration in MIGRATIONS:
            if migration.version not in versions:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        conn.commit()


def test_migrations_upgrade_v3_database_without_losing_revisions(tmp_path: Path) -> None:
    db_path = tmp_path / "glyphhold-v3.sqlite"
    object.__setattr__(settings, "db_path", db_path)
    _apply_migration_versions(db_path, {1, 2, 3})

    created_at = "2026-06-29T09:00:00.000Z"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memories (
                id, category_id, title, summary, body, tags_json, metadata_json,
                source, confidence, auto_prefetch_level, archived, superseded_by,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "mem_upgrade",
                "cat_projects",
                "Upgrade memory",
                "summary",
                "body",
                "[]",
                "{}",
                "test",
                4,
                "normal",
                0,
                None,
                created_at,
                created_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_revisions (
                id, memory_id, title, summary, body, tags_json, metadata_json,
                confidence, auto_prefetch_level, archived, superseded_by,
                changed_by, change_reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rev_upgrade",
                "mem_upgrade",
                "Old title",
                "old summary",
                "old body",
                "[]",
                "{}",
                3,
                "low",
                0,
                None,
                "tester",
                "pre-upgrade",
                created_at,
            ),
        )
        conn.commit()

    apply_migrations()

    assert current_schema_version() == 5
    with connect(db_path) as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(memory_revisions)").fetchall()
        }
        assert {"category_id", "source"} <= columns
        revision = conn.execute(
            "SELECT title, change_reason FROM memory_revisions WHERE id = ?",
            ("rev_upgrade",),
        ).fetchone()
        assert revision is not None
        assert revision["title"] == "Old title"
        assert revision["change_reason"] == "pre-upgrade"
