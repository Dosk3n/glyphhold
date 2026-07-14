from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.core.encryption import SecretDecryptionError
from app.storage.repositories import memories, secrets
from tests.conftest import dashboard_csrf_headers


def _setup_dashboard(client: TestClient) -> None:
    response = client.post(
        "/dashboard/api/setup",
        json={
            "username": "admin",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        },
        headers=dashboard_csrf_headers(client),
    )
    assert response.status_code == 200


def _checkpoint(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA wal_checkpoint(FULL)")


def _copy_sqlite_files(source_db: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in source_db.parent.glob(f"{source_db.name}*"):
        shutil.copy2(path, target_dir / path.name)
    return target_dir / source_db.name


def test_backup_restore_keeps_data_and_requires_original_encryption_key(
    secrets_client: TestClient,
    tmp_path: Path,
) -> None:
    _setup_dashboard(secrets_client)

    memory_response = secrets_client.post(
        "/dashboard/api/memories",
        json={
            "category_id": "cat_projects",
            "title": "Restore check",
            "summary": "Backup restore test",
            "body": "This memory should survive a file restore.",
            "tags": ["backup"],
        },
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert memory_response.status_code == 201

    secret_response = secrets_client.post(
        "/dashboard/api/secrets",
        json={
            "name": "RESTORE_TEST_SECRET",
            "value": "restored-secret-value",
            "description": "Backup restore secret",
        },
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert secret_response.status_code == 201

    original_db = settings.db_path
    _checkpoint(original_db)
    restored_db = _copy_sqlite_files(original_db, tmp_path / "restored-data")

    object.__setattr__(settings, "db_path", restored_db)
    object.__setattr__(settings, "encryption_key", "test-encryption-key")

    restored_memory = memories.get_memory(memory_response.json()["id"])
    assert restored_memory is not None
    assert restored_memory["title"] == "Restore check"

    restored_secret = secrets.get_secret_metadata("RESTORE_TEST_SECRET")
    assert restored_secret is not None
    assert restored_secret["description"] == "Backup restore secret"
    _, revealed = secrets.reveal_secret("RESTORE_TEST_SECRET")
    assert revealed == "restored-secret-value"

    object.__setattr__(settings, "encryption_key", "wrong-encryption-key")
    try:
        secrets.reveal_secret("RESTORE_TEST_SECRET")
    except SecretDecryptionError as exc:
        assert "configured key" in str(exc)
    else:
        raise AssertionError("secret reveal should fail with the wrong encryption key")
