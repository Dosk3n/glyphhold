import sqlite3
from pathlib import Path

from app.storage.upgrade import before_v2_upgrade, snapshot_database


def test_preupgrade_snapshot_includes_committed_wal_and_preserves_source(tmp_path: Path):
    source = tmp_path / "legacy.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE schema_migrations(version INTEGER)")
        conn.execute("INSERT INTO schema_migrations VALUES (5)")
        conn.execute("CREATE TABLE example(value TEXT)")
        conn.execute("INSERT INTO example VALUES ('original')")
        conn.commit()
        backup = before_v2_upgrade(source)
        assert backup is not None and backup != source
        with sqlite3.connect(backup) as copy:
            assert copy.execute("SELECT value FROM example").fetchone()[0] == "original"
            assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert source.exists()
        conn.execute("UPDATE schema_migrations SET version=6")
        conn.commit()
        assert before_v2_upgrade(source) is None


def test_snapshot_never_overwrites_an_existing_backup(tmp_path: Path):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE example(value TEXT)")
    destination = tmp_path / "existing.sqlite"
    destination.write_bytes(b"preserve me")
    import pytest

    with pytest.raises(FileExistsError):
        snapshot_database(source, destination)
    assert destination.read_bytes() == b"preserve me"


def test_health_fails_when_database_integrity_is_not_ok(client, monkeypatch):
    import app.api.health as module

    monkeypatch.setattr(module, "database_ok", lambda: False)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["database"] == "error"
    assert response.json()["status"] == "error"
