from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.config import settings
from app.core.auth import create_session_value
from app.core.encryption import (
    SecretDecryptionError,
    ensure_installation_key,
    persistent_private_key,
)
from app.providers import transfer
from app.storage.db import connection
from app.storage.repositories.auth import create_dashboard_user
from app.storage.repositories.settings import get_session_secret


def test_database_signing_secret_no_longer_forges_admin_session(secrets_client):
    user_id = create_dashboard_user("audit-admin", "not-used-by-this-test")
    with connection() as conn:
        conn.execute(
            "INSERT INTO app_settings VALUES ('session_secret','copied-database-secret','now','now')"
        )
    signer = URLSafeTimedSerializer("copied-database-secret", salt="glyphhold-dashboard-session")
    forged = signer.dumps({"user_id": user_id, "session_version": 1})
    get_session_secret()
    secrets_client.cookies.set(settings.session_cookie_name, forged)
    assert secrets_client.get("/api/v2/spaces").status_code == 401
    with connection() as conn:
        assert (
            conn.execute("SELECT 1 FROM app_settings WHERE key='session_secret'").fetchone() is None
        )
    secrets_client.cookies.set(settings.session_cookie_name, create_session_value(user_id))
    assert secrets_client.get("/api/v2/spaces").status_code == 200


def test_secret_disabled_signing_key_is_private_and_persistent(client):
    first = get_session_secret()
    assert get_session_secret() == first
    path = settings.db_path.parent / "session.key"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text().strip() == first
    assert not (settings.db_path.parent / "encryption.key").exists()
    with connection() as conn:
        assert not conn.execute("SELECT 1 FROM app_settings WHERE value=?", (first,)).fetchone()


def test_existing_installation_key_permissions_are_repaired(client):
    object.__setattr__(settings, "auto_encryption_key", True)
    path = settings.db_path.parent / "encryption.key"
    path.write_text("synthetic-restored-installation-key")
    path.chmod(0o644)
    assert ensure_installation_key() == "synthetic-restored-installation-key"
    assert path.stat().st_mode & 0o777 == 0o600


def test_private_key_reader_rejects_links_and_nonregular_files(tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("synthetic-secret")
    target.chmod(0o644)
    link = tmp_path / "linked-key"
    link.symlink_to(target)
    with pytest.raises(SecretDecryptionError):
        persistent_private_key(link)
    assert target.stat().st_mode & 0o777 == 0o644
    fifo = tmp_path / "fifo-key"
    os.mkfifo(fifo)
    with pytest.raises(SecretDecryptionError):
        persistent_private_key(fifo)


def test_import_fingerprints_are_keyed_and_legacy_retries_preserve_conflicts(secrets_client):
    item = {"source_id": "source-pin", "name": "PIN", "value": "1234"}
    salt = b"0123456789abcdef"
    password = "synthetic-transfer-password"

    def package(record):
        return {
            "format": "glyphhold-encrypted-secret-transfer-v1",
            "salt": base64.b64encode(salt).decode(),
            "ciphertext": transfer.transfer_cipher(password, salt)
            .encrypt(json.dumps({"secrets": [record]}).encode())
            .decode(),
        }

    original = package(item)
    transfer.import_package(original, password, "old-installation", "space_personal", apply=True)
    legacy = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
    with connection() as conn:
        row = conn.execute("SELECT * FROM gh2_secret_imports").fetchone()
        assert row["source_hash"].startswith("hmac-sha256-v1:")
        assert legacy not in row["source_hash"]
        conn.execute("UPDATE gh2_secret_imports SET source_hash=?", (legacy,))
    transfer.migrate_legacy_fingerprints()
    with connection() as conn:
        assert (
            conn.execute("SELECT source_hash FROM gh2_secret_imports")
            .fetchone()[0]
            .startswith("legacy-fernet:")
        )
    changed = package(item | {"value": "9999"})
    assert transfer.import_package(changed, password, "old-installation", "space_personal")[
        "conflicts"
    ]
    with pytest.raises(ValueError, match="conflicts"):
        transfer.import_package(changed, password, "old-installation", "space_personal", apply=True)
    result = transfer.import_package(
        original, password, "old-installation", "space_personal", apply=True
    )
    assert result["existing"] == 1 and result["new"] == 0
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM gh2_secret_handles").fetchone()[0] == 1
        assert (
            conn.execute("SELECT source_hash FROM gh2_secret_imports")
            .fetchone()[0]
            .startswith("hmac-sha256-v1:")
        )
