"""Independent cross-feature regression checks for GH2 permission boundaries."""

from __future__ import annotations

import json

import pytest

from app.api import v2_secrets
from app.core.auth import create_api_key
from app.providers import vault
from app.storage.db import connection
from app.v2 import core
from tests.conftest import dashboard_csrf_headers


def key(space_id, scopes=None):
    scopes = scopes or ["memories:read", "memories:write", "secrets:write", "secrets:reveal"]
    kid, token = create_api_key(
        name="Adversarial key", actor="reviewer", description="", scopes=scopes
    )
    core.set_connection(
        core.ADMIN,
        kid,
        {
            "default_space_id": space_id,
            "grants": [{"space_id": space_id, "can_read": True, "can_write": True}],
        },
    )
    return core.Principal(kid, "reviewer", set(scopes)), {"Authorization": "Bearer " + token}


def make(p, idem, **data):
    return core.create_memory(
        p, {"title": "Saved fact", "body": "Sensitive source fact"} | data, idem
    )


def test_nested_profile_move_redacts_reads_and_idempotency_replay(client):
    work, headers = key("space_work")
    source = make(work, "source")
    profile_payload = {
        "title": "Profile",
        "body": "Sensitive source fact",
        "record_type": "profile",
        "source_refs": [{"id": source["id"], "version": 1}],
    }
    profile = make(work, "profile", **profile_payload)
    nested = make(
        work,
        "nested",
        title="Nested",
        body="Sensitive source fact",
        record_type="summary",
        source_refs=[{"id": profile["id"], "version": 1}],
    )
    core.update_memory(core.ADMIN, source["id"], {"space_id": "space_personal"}, 1)
    for mid in (profile["id"], nested["id"]):
        result = client.get("/api/v2/memories/" + mid, headers=headers)
        assert result.status_code == 200
        assert "Sensitive source fact" not in result.text
        assert result.json()["stale"]
    replayed = make(work, "profile", **profile_payload)
    assert "Sensitive source fact" not in json.dumps(replayed)
    assert not core.search(work, "Sensitive", broaden=True)["results"]


def test_move_history_and_revoked_grants_cannot_leak(client):
    work, _ = key("space_work")
    personal, _ = key("space_personal")
    original = make(work, "source")
    core.update_memory(core.ADMIN, original["id"], {"space_id": "space_personal"}, 1)
    assert core.revisions(personal, original["id"]) == []
    with pytest.raises(core.SpaceError):
        core.get_memory(work, original["id"])
    core.set_connection(core.ADMIN, personal.key_id, {"grants": [], "default_space_id": None})
    with pytest.raises(core.SpaceError):
        core.get_memory(personal, original["id"])


def test_api_admin_scope_without_space_grants_is_not_dashboard_admin(client):
    kid, token = create_api_key(
        name="Admin scoped", actor="reviewer", description="", scopes=["admin"]
    )
    headers = {"Authorization": "Bearer " + token}
    response = client.get("/api/v2/spaces", headers=headers)
    assert response.status_code == 200 and response.json()["spaces"] == []
    assert (
        client.post("/api/v2/spaces", headers=headers, json={"name": "Injected"}).status_code == 403
    )
    assert client.get(
        "/dashboard/api/advanced/settings", headers=headers, follow_redirects=False
    ).status_code in {303, 401, 403}
    assert core.Principal(kid, "reviewer", {"admin"}).admin is False


def test_cookie_mutations_with_nonbearer_header_still_require_csrf(client):
    client.get("/dashboard/api/session")
    response = client.post(
        "/dashboard/api/setup",
        headers=dashboard_csrf_headers(client),
        json={
            "username": "reviewer",
            "password": "a-long-test-password",
            "confirm_password": "a-long-test-password",
        },
    )
    assert response.status_code == 200
    for authorization in ["Basic dGVzdDp0ZXN0", "Bearer", "Bearer "]:
        response = client.post(
            "/api/v2/spaces",
            headers={"Authorization": authorization},
            json={"name": "Must not be created"},
        )
        assert response.status_code in {401, 403}, response.text
    assert not any(space["name"] == "Must not be created" for space in core.list_spaces(core.ADMIN))


def test_provider_bound_handles_fail_closed_after_account_change_or_outage(
    secrets_client, monkeypatch
):
    config = {
        "enabled": True,
        "server_url": "https://vault.example.test",
        "client_id": "first-account",
        "client_secret": "fake-test-token",
        "master_password": "fake-test-password",
        "folder_mappings": {
            "space_work": {"folder_ids": ["work-folder"], "write_folder_id": "work-folder"}
        },
    }
    vault.save_config(config)
    item = {
        "id": "item-one",
        "name": "Login",
        "folderId": "work-folder",
        "login": {"password": "never-persist-this"},
    }
    monkeypatch.setattr(vault.vault, "call", lambda *args, **kwargs: item)
    handle = v2_secrets.create_handle(
        core.ADMIN,
        {
            "space_id": "space_work",
            "name": "Linked credential",
            "item_id": "item-one",
            "field": "login.password",
        },
        external_link=True,
    )
    _, headers = key("space_work")
    with connection() as conn:
        stored = dict(
            conn.execute("SELECT * FROM gh2_secret_handles WHERE id=?", (handle["id"],)).fetchone()
        )
        assert stored["encrypted_value"] is None
    vault.save_config({"client_id": "different-account"})
    response = secrets_client.post(f"/api/v2/secrets/{handle['id']}/reveal", headers=headers)
    assert response.status_code == 503 and "never-persist-this" not in response.text
    vault.save_config({"client_id": "first-account"})

    def outage(*args, **kwargs):
        raise vault.VaultError("Provider offline")

    monkeypatch.setattr(vault.vault, "call", outage)
    response = secrets_client.post(f"/api/v2/secrets/{handle['id']}/reveal", headers=headers)
    assert response.status_code == 503
    with connection() as conn:
        assert (
            conn.execute(
                "SELECT provider FROM gh2_secret_handles WHERE id=?", (handle["id"],)
            ).fetchone()[0]
            == "vaultwarden"
        )


def test_builtin_handles_stay_builtin_when_external_provider_enabled(secrets_client):
    _, headers = key("space_personal")
    created = secrets_client.post(
        "/api/v2/secrets",
        headers=headers,
        json={
            "name": "Existing builtin",
            "space_id": "space_personal",
            "value": "fake-builtin-material",
        },
    )
    assert created.status_code == 201
    handle = created.json()
    vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "account",
            "client_secret": "fake-token",
            "master_password": "fake-password",
        }
    )
    reveal = secrets_client.post(f"/api/v2/secrets/{handle['id']}/reveal", headers=headers)
    assert reveal.status_code == 200 and reveal.json()["value"] == "fake-builtin-material"


def test_encrypted_secret_transfer_tampering_repeatability_and_atomic_conflicts(secrets_client):
    from app.config import settings
    from app.core.encryption import ensure_installation_key
    from app.providers import transfer

    _, personal_headers = key("space_personal")
    secret = secrets_client.post(
        "/api/v2/secrets",
        headers=personal_headers,
        json={
            "name": "Transfer fixture",
            "space_id": "space_personal",
            "value": "fake-transfer-value",
        },
    )
    assert secret.status_code == 201
    package = transfer.export_secrets(
        settings.db_path, ensure_installation_key(), "test-transfer-passphrase"
    )
    assert "fake-transfer-value" not in json.dumps(package)
    with pytest.raises(ValueError, match="cannot be decrypted"):
        transfer.import_package(package, "incorrect-passphrase", "old-instance", "space_work")
    tampered = package | {"ciphertext": package["ciphertext"][:-8] + "AAAAAAAA"}
    with pytest.raises(ValueError, match="cannot be decrypted"):
        transfer.import_package(tampered, "test-transfer-passphrase", "old-instance", "space_work")
    preview = transfer.import_package(
        package, "test-transfer-passphrase", "old-instance", "space_work"
    )
    assert preview["new"] == 1 and "fake-transfer-value" not in json.dumps(preview)
    with connection() as conn:
        assert not conn.execute(
            "SELECT 1 FROM gh2_secret_handles WHERE space_id='space_work'"
        ).fetchone()
    imported = transfer.import_package(
        package, "test-transfer-passphrase", "old-instance", "space_work", apply=True
    )
    assert imported["new"] == 1
    repeated = transfer.import_package(
        package, "test-transfer-passphrase", "old-instance", "space_work", apply=True
    )
    assert repeated["existing"] == 1 and repeated["new"] == 0
    # Same names from a differently identified source must be reviewed, never overwritten.
    with pytest.raises(ValueError, match="conflicts"):
        transfer.import_package(
            package, "test-transfer-passphrase", "different-instance", "space_work", apply=True
        )
    with connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM gh2_secret_handles WHERE space_id='space_work'"
            ).fetchone()[0]
            == 1
        )


def test_lifecycle_and_evidence_cycles_are_rejected(client):
    worker, _ = key("space_work")
    a = make(worker, "cycle-a", title="A")
    b = make(worker, "cycle-b", title="B")
    core.update_memory(worker, a["id"], {"merged_into": b["id"]}, 1)
    with pytest.raises(core.SpaceError):
        core.update_memory(worker, b["id"], {"superseded_by": a["id"]}, 1)
    one = make(worker, "profile-one", title="One", record_type="profile")
    two = make(
        worker,
        "profile-two",
        title="Two",
        record_type="summary",
        source_refs=[{"id": one["id"], "version": 1}],
    )
    with pytest.raises(core.SpaceError):
        core.update_memory(worker, one["id"], {"source_refs": [{"id": two["id"], "version": 1}]}, 1)


def test_vault_cli_restart_reuses_saved_server_without_reconfiguration(monkeypatch):
    runner = vault.VaultCLI()
    calls = []
    config = {
        "enabled": True,
        "server_url": "https://vault.example.test",
        "client_id": "fixture",
        "client_secret": "test-only",
        "master_password": "test-only-password",
    }

    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["status"]:
            return {"status": "locked", "serverUrl": "https://vault.example.test/"}
        if args[0] == "unlock":
            assert kwargs["extra"] == {"GH2_VAULT_PASSWORD": "test-only-password"}
            assert "test-only-password" not in args
            return "test-only-session"
        raise AssertionError("Restart must not logout or reconfigure an already logged-in CLI")

    monkeypatch.setattr(runner, "_run", fake_run)
    runner.unlock(config)
    assert runner.session == "test-only-session"
    assert [args[0] for args in calls] == ["status", "unlock"]


def test_provider_rejects_http_before_saving_credentials(secrets_client):
    with pytest.raises(ValueError, match="HTTPS"):
        vault.save_config({"server_url": "http://vault.example.test"})


def test_opening_another_connection_does_not_release_process_file_locks(tmp_path):
    """A raw open/close of an existing SQLite inode silently drops POSIX locks."""
    import fcntl
    import os
    import sqlite3
    import subprocess
    import sys

    from app.storage.db import connect

    path = tmp_path / "locks.sqlite"
    seed = sqlite3.connect(path)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE test(id INTEGER)")
    seed.commit()
    seed.execute("BEGIN IMMEDIATE")
    descriptor = os.open(path, os.O_RDWR)
    fcntl.lockf(descriptor, fcntl.LOCK_EX, 1, 0, os.SEEK_SET)
    opened = None
    try:
        opened = connect(path)
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                """import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR)
try:fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB,1,0,os.SEEK_SET)
except BlockingIOError:sys.exit(1)
sys.exit(0)
""",
                str(path),
            ],
            check=False,
            capture_output=True,
        )
        assert child.returncode == 1, (
            "Opening a second connection released existing database inode locks"
        )
    finally:
        if opened is not None:
            opened.close()
        os.close(descriptor)
        seed.rollback()
        seed.close()


def test_multiple_processes_can_write_while_opening_nested_connections(tmp_path):
    import sqlite3
    import subprocess
    import sys

    path = tmp_path / "multiprocess.sqlite"
    from app.storage.db import connect

    initial = connect(path)
    initial.execute(
        "CREATE TABLE writes(worker INTEGER,sequence INTEGER,PRIMARY KEY(worker,sequence))"
    )
    initial.commit()
    initial.close()
    script = """import sys
from pathlib import Path
from app.storage.db import connect
path=Path(sys.argv[1]);worker=int(sys.argv[2])
for sequence in range(30):
 c=connect(path)
 try:
  c.execute('BEGIN IMMEDIATE')
  c.execute('INSERT INTO writes VALUES(?,?)',(worker,sequence))
  nested=connect(path)
  nested.execute('SELECT count(*) FROM writes').fetchone()
  nested.close()
  c.commit()
 finally:c.close()
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(worker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for worker in range(3)
    ]
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, (stdout + stderr).decode(errors="replace")
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM writes").fetchone()[0] == 90
