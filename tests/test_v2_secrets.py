import json
import os

import pytest

from app.config import settings
from app.core.auth import create_api_key
from app.core.encryption import SecretDecryptionError, ensure_installation_key
from app.providers import vault
from app.storage.db import connection
from app.v2 import core


def scoped_key(space):
    key_id, key = create_api_key(
        name="secrets test",
        actor="test",
        description="",
        scopes=["secrets:write", "secrets:reveal"],
    )
    core.set_connection(
        core.ADMIN,
        key_id,
        {
            "default_space_id": space,
            "grants": [{"space_id": space, "can_read": True, "can_write": True}],
        },
    )
    return {"Authorization": "Bearer " + key}


def test_scoped_builtin_secrets_and_versions(secrets_client):
    personal = scoped_key("space_personal")
    work = scoped_key("space_work")
    response = secrets_client.post(
        "/api/v2/secrets",
        headers=personal,
        json={"name": "SSH_KEY", "value": "test-secret-material", "space_id": "space_personal"},
    )
    assert response.status_code == 201, response.text
    secret = response.json()
    assert "test-secret-material" not in response.text
    assert secrets_client.get("/api/v2/secrets", headers=work).json()["secrets"] == []
    assert (
        secrets_client.post("/api/v2/secrets/" + secret["id"] + "/reveal", headers=work).status_code
        == 404
    )
    result = secrets_client.post("/api/v2/secrets/" + secret["id"] + "/reveal", headers=personal)
    assert result.json()["value"] == "test-secret-material"
    updated = secrets_client.patch(
        "/api/v2/secrets/" + secret["id"],
        headers=personal,
        json={"value": "replacement", "expected_version": 1},
    )
    assert updated.json()["version"] == 2
    assert (
        secrets_client.patch(
            "/api/v2/secrets/" + secret["id"],
            headers=personal,
            json={"value": "stale", "expected_version": 1},
        ).status_code
        == 409
    )
    with connection() as conn:
        assert b"test-secret-material" not in bytes(
            conn.execute(
                "SELECT encrypted_value FROM gh2_secret_handles WHERE id=?", (secret["id"],)
            ).fetchone()[0]
        )


def test_provider_config_masked_and_encrypted(secrets_client):
    config = vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "user.test",
            "client_secret": "provider-token-test",
            "master_password": "provider-password-test",
            "folder_mappings": {},
        }
    )
    assert config["master_password_configured"]
    assert "provider-password-test" not in json.dumps(config)
    with connection() as conn:
        value = conn.execute(
            "SELECT value FROM app_settings WHERE key='gh2_vault_config'"
        ).fetchone()[0]
        assert "provider-password-test" not in value
    vault.save_config({"enabled": False, "master_password": ""})
    assert vault.get_config(private=True)["master_password"] == "provider-password-test"


def test_external_link_enforces_account_folder_and_explicit_field(secrets_client, monkeypatch):
    vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "fake",
            "client_secret": "fake",
            "master_password": "fake",
            "folder_mappings": {
                "space_personal": {"folder_ids": ["home"], "write_folder_id": "home"}
            },
        }
    )
    item = {
        "id": "test-item",
        "name": "Login",
        "folderId": "home",
        "login": {"username": "fakeuser", "password": "hidden-value"},
    }
    monkeypatch.setattr(vault.vault, "call", lambda *a, **k: item)
    from app.api.v2_secrets import create_handle

    linked = create_handle(
        core.ADMIN,
        {
            "name": "LOGIN_PASSWORD",
            "space_id": "space_personal",
            "item_id": "test-item",
            "field": "login.password",
        },
        external_link=True,
    )
    headers = scoped_key("space_personal")
    response = secrets_client.post("/api/v2/secrets/" + linked["id"] + "/reveal", headers=headers)
    assert response.json()["value"] == "hidden-value"
    assert "fakeuser" not in response.text
    item["folderId"] = "work"
    assert (
        secrets_client.post(
            "/api/v2/secrets/" + linked["id"] + "/reveal", headers=headers
        ).status_code
        == 503
    )
    vault.save_config({"enabled": False})
    assert (
        secrets_client.post(
            "/api/v2/secrets/" + linked["id"] + "/reveal", headers=headers
        ).status_code
        == 503
    )


def test_installation_key_restart_missing_key_and_database_marker(client, monkeypatch):
    object.__setattr__(settings, "auto_encryption_key", True)
    first = ensure_installation_key()
    assert len(first) >= 48
    assert ensure_installation_key() == first
    path = settings.db_path.parent / "encryption.key"
    assert os.stat(path).st_mode & 0o777 == 0o600
    vault.save_config({"enabled": False})
    path.unlink()
    with pytest.raises(SecretDecryptionError, match="missing"):
        ensure_installation_key()
    assert not path.exists()


def test_legacy_data_routes_closed_in_gh2(client, monkeypatch):
    object.__setattr__(settings, "allow_legacy_api", False)
    for path in [
        "/api/v1/memories",
        "/api/v1/agent/prefetch",
        "/api/v1/secrets",
        "/dashboard/api/memories",
        "/dashboard/api/secrets",
    ]:
        assert client.get(path).status_code == 410


def test_v2_cookie_mutations_require_csrf(client):
    assert client.post("/api/v2/spaces", json={"name": "Denied"}).status_code == 403


def test_encrypted_secret_transfer_repeatability_and_wrong_passphrase(secrets_client):
    from app.api.v2_secrets import create_handle
    from app.providers.transfer import export_secrets, import_package

    create_handle(
        core.ADMIN,
        {"name": "TRANSFER_TEST", "space_id": "space_personal", "value": "source-secret-value"},
    )
    package = export_secrets(settings.db_path, "test-encryption-key", "test-transfer-password")
    assert "source-secret-value" not in json.dumps(package)
    preview = import_package(package, "test-transfer-password", "source-home", "space_work")
    assert preview["new"] == 1 and not preview["conflicts"]
    assert "source-secret-value" not in json.dumps(preview)
    import_package(package, "test-transfer-password", "source-home", "space_work", apply=True)
    repeat = import_package(
        package, "test-transfer-password", "source-home", "space_work", apply=True
    )
    assert repeat["existing"] == 1 and repeat["new"] == 0
    with pytest.raises(ValueError, match="decrypt"):
        import_package(package, "incorrect-password", "source-home", "space_work")
    headers = scoped_key("space_work")
    result = secrets_client.post("/api/v2/secrets/TRANSFER_TEST/reveal", headers=headers)
    assert result.json()["value"] == "source-secret-value"


def test_builtin_to_external_transfer_verifies_before_switch(secrets_client, monkeypatch):
    from app.api.provider_settings import (
        ExternalTransfer,
        apply_external_transfer,
        preview_external_transfer,
    )
    from app.api.v2_secrets import create_handle

    source = create_handle(
        core.ADMIN,
        {
            "name": "MOVE_TO_VAULT",
            "space_id": "space_personal",
            "value": "transfer-only-test-value",
        },
    )
    vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "fake",
            "client_secret": "fake",
            "master_password": "fake",
            "write_enabled": True,
            "folder_mappings": {
                "space_personal": {"folder_ids": ["home"], "write_folder_id": "home"}
            },
        }
    )
    upstream = []

    def call(args, **kwargs):
        if args[:2] == ["list", "items"]:
            return upstream
        if args[:2] == ["create", "item"]:
            item = kwargs["payload"] | {"id": "remote-item"}
            upstream.append(item)
            return item
        if args[:2] == ["get", "item"]:
            return upstream[0]
        raise AssertionError(args)

    monkeypatch.setattr(vault.vault, "call", call)
    payload = ExternalTransfer(items=[{"id": source["id"], "expected_version": 1}])
    assert preview_external_transfer(payload)["items"][0]["folder_id"] == "home"
    result = apply_external_transfer(payload)
    assert len(result["migrated"]) == 1
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM gh2_secret_handles WHERE id=?", (source["id"],)
        ).fetchone()
        assert (
            row["provider"] == "vaultwarden"
            and row["encrypted_value"] is None
            and row["version"] == 2
        )
    assert len(upstream) == 1


def test_migrated_secret_preserves_legacy_caller_restrictions(secrets_client):
    headers = scoped_key("space_import_review")
    created = secrets_client.post(
        "/api/v2/secrets",
        headers=headers,
        json={
            "name": "MIGRATED_RESTRICTED",
            "value": "restricted-value",
            "space_id": "space_import_review",
        },
    ).json()
    with connection() as conn:
        conn.execute(
            "INSERT INTO gh2_secret_provenance VALUES (?,?)",
            (
                created["id"],
                json.dumps(
                    {"allowed_agents_json": '["Melchior"]', "allowed_tools_json": '["ssh"]'}
                ),
            ),
        )
    endpoint = "/api/v2/secrets/" + created["id"] + "/reveal"
    for payload in [
        {},
        {"requesting_agent": "Melchior"},
        {"requesting_agent": "other", "tool": "ssh"},
    ]:
        result = secrets_client.post(endpoint, headers=headers, json=payload)
        assert result.status_code == 403
        assert "restricted-value" not in result.text
    result = secrets_client.post(
        endpoint, headers=headers, json={"requesting_agent": "Melchior", "tool": "ssh"}
    )
    assert result.status_code == 200
    assert result.json()["value"] == "restricted-value"
    # An owner label cannot replace the authenticated ownership-space grant.
    other = scoped_key("space_work")
    assert (
        secrets_client.post(
            endpoint, headers=other, json={"requesting_agent": "Melchior", "tool": "ssh"}
        ).status_code
        == 404
    )
