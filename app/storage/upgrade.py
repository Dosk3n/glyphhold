"""Consistent pre-upgrade snapshots and read-only legacy memory exports."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def snapshot_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with (
            sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src,
            sqlite3.connect(destination) as dst,
        ):
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def before_v2_upgrade(source: Path) -> Path | None:
    if not source.exists():
        return None
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "schema_migrations" not in tables:
            return None
        version = conn.execute("SELECT coalesce(max(version),0) FROM schema_migrations").fetchone()[
            0
        ]
        if version >= 6:
            return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = source.parent / "backups" / f"pre-gh2-{stamp}.sqlite"
    snapshot_database(source, destination)
    return destination


def export_legacy_memories(source: Path) -> dict:
    # SQLite's read-only connection and backup API include committed WAL content.
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        version = conn.execute("SELECT coalesce(max(version),0) FROM schema_migrations").fetchone()[
            0
        ]
        memories = [dict(r) for r in conn.execute("SELECT * FROM memories")]
        revisions = [dict(r) for r in conn.execute("SELECT * FROM memory_revisions")]
        categories = [dict(r) for r in conn.execute("SELECT * FROM memory_categories")]
    return {
        "format": "glyphhold-memory-export",
        "schema_version": version,
        "memories": memories,
        "revisions": revisions,
        "categories": categories,
        "exported_at": datetime.now(UTC).isoformat(),
        "includes_secrets": False,
    }


def write_private_json(destination: Path, data: dict) -> None:
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
