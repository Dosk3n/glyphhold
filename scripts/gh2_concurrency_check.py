"""Disposable multi-process WAL stress check; never uses an existing database."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="gh2-concurrency-") as temp:
        path = Path(temp) / "stress.sqlite"
        os.environ["GLYPHHOLD_DB_PATH"] = str(path)
        from app.storage.db import connection
        from app.storage.migrations import apply_migrations
        from app.v2.core import ensure_schema

        apply_migrations()
        ensure_schema()
        code = """
import sys
from app.v2.core import ADMIN,create_memory,update_memory,search
worker=sys.argv[1]
for i in range(50):
 m=create_memory(ADMIN,{'space_id':'space_work','title':f'Test {worker} {i}','body':'Synthetic concurrency fixture'},f'worker:{worker}:{i}')
 update_memory(ADMIN,m['id'],{'body':'Synthetic concurrency fixture updated'},m['version'])
 search(ADMIN,'Synthetic',space_id='space_work',limit=3)
"""
        children = [subprocess.Popen([sys.executable, "-c", code, str(i)]) for i in range(6)]
        failures = [p.wait() for p in children if p.wait() != 0]
        if failures:
            raise RuntimeError(f"Concurrent child processes failed: {failures}")
        with connection() as conn:
            check = conn.execute("PRAGMA integrity_check").fetchall()
            count = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
            versions = conn.execute("SELECT count(*) FROM memories WHERE version=2").fetchone()[0]
            conn.execute("INSERT INTO memories_fts(memories_fts,rank) VALUES('integrity-check',1)")
            assert [r[0] for r in check] == ["ok"], check
            assert count == versions == 300, (count, versions)
        print(
            "PASS: six processes,300 creates+300 versioned updates+300 recalls; SQLite and FTS integrity OK"
        )


if __name__ == "__main__":
    main()
