from __future__ import annotations

import copy
import json

import pytest

from app.providers import vault
from app.storage.db import connection
from tests.conftest import make_api_key_headers


@pytest.fixture
def live_vault(secrets_client, monkeypatch):
    vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "user.test",
            "client_secret": "test-key",
            "master_password": "test-password",
            "write_enabled": True,
        }
    )
    state = {
        "items": [
            {
                "id": "existing-login",
                "name": "Home server",
                "folderId": "home",
                "type": 1,
                "notes": "private-notes",
                "login": {"username": "private-user", "password": "private-password"},
                "fields": [{"name": "api_token", "value": "private-token"}],
            }
        ],
        "folders": [{"id": None, "name": "No Folder"}, {"id": "home", "name": "Home Network"}],
    }
    calls = []

    def call(args, *, payload=None, write=False):
        calls.append((args, write))
        if write and not vault.get_config(private=True)["write_enabled"]:
            raise vault.VaultError("External writes are disabled")
        if args == ["list", "items"]:
            return copy.deepcopy(state["items"])
        if args == ["list", "folders"]:
            return copy.deepcopy(state["folders"])
        if args[:2] == ["get", "item"]:
            return copy.deepcopy(next(i for i in state["items"] if i["id"] == args[2]))
        if args == ["create", "item"]:
            item = payload | {"id": "created-" + str(len(state["items"]))}
            state["items"].append(copy.deepcopy(item))
            return copy.deepcopy(item)
        if args == ["create", "folder"]:
            folder = payload | {"id": "new-folder"}
            state["folders"].append(folder)
            return folder
        if args[:2] == ["edit", "item"]:
            state["items"] = [
                copy.deepcopy(payload) if i["id"] == args[2] else i for i in state["items"]
            ]
            return copy.deepcopy(payload)
        raise AssertionError(args)

    monkeypatch.setattr(vault.vault, "call", call)
    headers = make_api_key_headers(scopes=["secrets:reveal", "secrets:write"])
    return secrets_client, headers, state, calls


def test_preexisting_vault_entries_are_searchable_without_links_and_values_are_private(live_vault):
    client, headers, state, _ = live_vault
    response = client.get("/api/v2/secrets?query=Home", headers=headers)
    assert response.status_code == 200
    found = response.json()["secrets"]
    assert len(found) == 1 and found[0]["folder_name"] == "Home Network"
    for private in ("private-notes", "private-user", "private-password", "private-token"):
        assert private not in response.text
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM gh2_secret_handles").fetchone()[0] == 0
    endpoint = "/api/v2/secrets/" + found[0]["id"]
    assert (
        client.post(endpoint + "/reveal", headers=headers, json={"field": "login.username"}).json()[
            "value"
        ]
        == "private-user"
    )
    assert (
        client.post(
            endpoint + "/reveal", headers=headers, json={"field": "custom:api_token"}
        ).json()["value"]
        == "private-token"
    )
    state["items"][0]["folderId"] = None
    assert client.post(endpoint + "/reveal", headers=headers).json()["value"] == "private-password"


def test_remote_create_folders_defaults_duplicates_and_write_disable(live_vault):
    client, headers, state, _ = live_vault
    assert client.get("/api/v2/secrets/folders", headers=headers).json()["supported"]
    assert (
        client.post(
            "/api/v2/secrets/folders", headers=headers, json={"name": "Home Network"}
        ).status_code
        == 409
    )
    assert (
        client.post("/api/v2/secrets/folders", headers=headers, json={"name": "Friend"}).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v2/secrets", headers=headers, json={"name": "HOME SERVER", "value": "duplicate"}
        ).status_code
        == 409
    )
    vault.save_config({"default_folder_id": "home"})
    created = client.post(
        "/api/v2/secrets", headers=headers, json={"name": "New token", "value": "new-token"}
    )
    assert created.status_code == 201 and created.json()["folder_id"] == "home"
    explicit = client.post(
        "/api/v2/secrets",
        headers=headers,
        json={"name": "Unfiled token", "value": "unfiled", "folder_id": None},
    )
    assert explicit.status_code == 201 and explicit.json()["folder_id"] is None
    invalid = client.post(
        "/api/v2/secrets",
        headers=headers,
        json={"name": "Bad folder", "value": "test", "folder_id": "missing"},
    )
    assert invalid.status_code == 409
    vault.save_config({"write_enabled": False})
    assert (
        client.post(
            "/api/v2/secrets", headers=headers, json={"name": "Blocked", "value": "blocked"}
        ).status_code
        == 503
    )
    assert not any(i["name"] == "Blocked" for i in state["items"])


def test_external_versions_field_updates_and_account_binding(live_vault):
    client, headers, state, _ = live_vault
    row = client.get("/api/v2/secrets", headers=headers).json()["secrets"][0]
    endpoint = "/api/v2/secrets/" + row["id"]
    response = client.patch(
        endpoint,
        headers=headers,
        json={
            "expected_version": row["version"],
            "field": "login.password",
            "value": "new-password",
        },
    )
    assert response.status_code == 200
    assert state["items"][0]["login"]["username"] == "private-user"
    assert state["items"][0]["notes"] == "private-notes"
    assert (
        client.patch(
            endpoint,
            headers=headers,
            json={"expected_version": row["version"], "field": "login.password", "value": "stale"},
        ).status_code
        == 409
    )
    vault.save_config({"client_id": "user.other"})
    assert client.get(endpoint, headers=headers).status_code == 409
    vault.save_config({"enabled": False})
    assert client.post(endpoint + "/reveal", headers=headers).status_code == 503


def test_ambiguous_names_and_fields_fail_closed(live_vault):
    client, headers, state, _ = live_vault
    state["items"].append(
        {"id": "same-name", "name": "Home server", "type": 2, "notes": "different"}
    )
    assert client.post("/api/v2/secrets/Home server/reveal", headers=headers).status_code == 409
    state["items"].append(
        {
            "id": "ambiguous",
            "name": "Notes and keys",
            "notes": "test-note",
            "fields": [{"name": "a", "value": "test-a"}, {"name": "a", "value": "test-b"}],
        }
    )
    # Duplicate custom field names are not advertised or guessed.
    row = client.get("/api/v2/secrets/Notes and keys", headers=headers).json()
    assert row["fields"] == ["notes"]
    assert (
        client.post(
            "/api/v2/secrets/" + row["id"] + "/reveal", headers=headers, json={"field": "custom:a"}
        ).status_code
        == 400
    )


def test_builtin_stays_accessible_and_transfer_checks_existing_values(live_vault):
    client, headers, state, _ = live_vault
    vault.save_config({"enabled": False})
    local = client.post(
        "/api/v2/secrets",
        headers=headers,
        json={"name": "Home server", "value": "private-password", "value_type": "password"},
    ).json()
    vault.save_config({"enabled": True})
    rows = client.get("/api/v2/secrets", headers=headers).json()["secrets"]
    assert len(rows) == 2
    remote = next(r for r in rows if r["provider"] == "vaultwarden")
    endpoint = "/api/v2/secrets/" + local["id"]
    assert client.post(endpoint + "/reveal", headers=headers).json()["value"] == "private-password"
    assert (
        client.post(
            endpoint + "/migrate", headers=headers, json={"expected_version": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint + "/migrate",
            headers=headers,
            json={"expected_version": 1, "target_id": remote["id"], "field": "login.username"},
        ).status_code
        == 409
    )
    result = client.post(
        endpoint + "/migrate",
        headers=headers,
        json={"expected_version": 1, "target_id": remote["id"], "field": "login.password"},
    )
    assert result.status_code == 200 and result.json()["value_verified"]
    assert "private-password" not in result.text
    assert len(state["items"]) == 1
    with connection() as conn:
        assert (
            conn.execute(
                "SELECT encrypted_value FROM gh2_secret_handles WHERE id=?", (local["id"],)
            ).fetchone()[0]
            is None
        )
    assert client.post(endpoint + "/reveal", headers=headers).json()["value"] == "private-password"


def test_provider_failure_is_not_an_empty_search_or_builtin_fallback(live_vault, monkeypatch):
    client, headers, _, _ = live_vault

    def fail(*args, **kwargs):
        raise vault.VaultError("Vault operation failed")

    monkeypatch.setattr(vault.vault, "call", fail)
    assert client.get("/api/v2/secrets", headers=headers).status_code == 503
    assert (
        client.post(
            "/api/v2/secrets", headers=headers, json={"name": "No fallback", "value": "value"}
        ).status_code
        == 503
    )
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM gh2_secret_handles").fetchone()[0] == 0


def test_secret_scopes_still_required_and_ssh_fields_supported(live_vault):
    client, headers, state, _ = live_vault
    none = make_api_key_headers(scopes=["memories:read"])
    assert client.get("/api/v2/secrets", headers=none).status_code == 403
    assert (
        client.post("/api/v2/secrets/folders", headers=none, json={"name": "Denied"}).status_code
        == 403
    )
    state["items"].append(
        {
            "id": "ssh",
            "name": "SSH",
            "type": 5,
            "sshKey": {
                "privateKey": "test-private-key",
                "publicKey": "test-public-key",
                "keyFingerprint": "test-fingerprint",
            },
        }
    )
    row = client.get("/api/v2/secrets/SSH", headers=headers).json()
    assert "test-private-key" not in json.dumps(row)
    assert (
        client.post("/api/v2/secrets/" + row["id"] + "/reveal", headers=headers).json()["value"]
        == "test-private-key"
    )


def test_saved_connection_can_be_tested_while_disabled(secrets_client, monkeypatch):
    from app.api.provider_settings import test_provider

    vault.save_config(
        {
            "enabled": False,
            "server_url": "https://vault.example.test",
            "client_id": "user.test",
            "client_secret": "test",
            "master_password": "test",
        }
    )
    calls = []

    def run(args, *, config, **kwargs):
        calls.append(args)
        assert config["enabled"]
        if args == ["status"]:
            return {"serverUrl": config["server_url"], "status": "locked"}
        if args[0] == "unlock":
            return "test-session"
        if args == ["list", "folders"]:
            return []
        return None

    monkeypatch.setattr(vault.vault, "_run", run)
    assert test_provider() == {"status": "unlocked", "folder_count": 0}
    assert ["list", "folders"] in calls
    assert vault.get_config(private=True)["enabled"] is False


def test_cli_operation_syncs_once_and_refreshes_after_writes(secrets_client, monkeypatch):
    vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "user.test",
            "client_secret": "test",
            "master_password": "test",
            "write_enabled": True,
        }
    )
    cli = vault.VaultCLI()
    cli.session = "test-session"
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return []

    monkeypatch.setattr(cli, "_run", run)
    with cli.operation():
        cli.call(["list", "folders"])
        cli.call(["list", "items"])
        cli.call(["create", "item"], payload={"notes": "test"}, write=True)
        cli.call(["get", "item", "test-id"])
    assert calls.count(["sync"]) == 2
    cli.call(["list", "items"])
    assert calls.count(["sync"]) == 3


@pytest.mark.parametrize(
    "query",
    [
        "RADARR.deanbox.co.uk",
        "https://radarr.deanbox.co.uk",
        "https://radarr.deanbox.co.uk:443/login?token=ignore#fragment",
        "192.168.1.189",
        "ssh://192.168.1.189:22",
        "radarr.deanbox.co.uk/login",
    ],
)
def test_search_finds_entries_by_website_and_hostname(live_vault, query):
    client, headers, state, _ = live_vault
    state["items"][0]["name"] = "Unrelated name"
    state["items"][0]["login"]["uris"] = [
        {
            "uri": "https://URL_USER:URL_PASSWORD@radarr.deanbox.co.uk/login?token=URL_TOKEN#URL_FRAGMENT"
        },
        {"uri": "ssh://dean@192.168.1.189:22"},
    ]
    response = client.get("/api/v2/secrets", headers=headers, params={"query": query})
    assert response.status_code == 200
    rows = response.json()["secrets"]
    assert len(rows) == 1 and rows[0]["name"] == "Unrelated name"
    assert rows[0]["hostnames"] == ["radarr.deanbox.co.uk", "192.168.1.189"]
    for sensitive in (
        "URL_USER",
        "URL_PASSWORD",
        "URL_TOKEN",
        "URL_FRAGMENT",
        "private-password",
        "private-user",
    ):
        assert sensitive not in response.text
        assert (
            client.get("/api/v2/secrets", headers=headers, params={"query": sensitive}).json()[
                "secrets"
            ]
            == []
        )


def test_website_normalization_and_duplicate_host_ambiguity(live_vault):
    client, headers, state, _ = live_vault
    state["items"][0]["login"]["uris"] = [
        {"uri": "radarr.deanbox.co.uk"},
        {"uri": "https://[fd00::1]:8443/login"},
        {"uri": "https://münich.example/"},
        {"uri": "https://host:invalid"},
        {"uri": None},
        None,
        {"uri": "https://invalid host/"},
    ]
    state["items"].append(
        {
            "id": "second",
            "name": "Other account",
            "type": 1,
            "login": {"password": "other", "uris": [{"uri": "https://radarr.deanbox.co.uk"}]},
        }
    )
    rows = client.get(
        "/api/v2/secrets", headers=headers, params={"query": "radarr.deanbox.co.uk"}
    ).json()["secrets"]
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
    assert (
        len(
            client.get("/api/v2/secrets", headers=headers, params={"query": "fd00::1"}).json()[
                "secrets"
            ]
        )
        == 1
    )
    assert (
        len(
            client.get(
                "/api/v2/secrets", headers=headers, params={"query": "münich.example"}
            ).json()["secrets"]
        )
        == 1
    )


def test_migration_dry_run_verifies_without_changing_source_or_destination(live_vault):
    client, headers, _state, calls = live_vault
    vault.save_config({"enabled": False})
    local = client.post(
        "/api/v2/secrets",
        headers=headers,
        json={"name": "Home server", "value": "private-password", "value_type": "password"},
    ).json()
    vault.save_config({"enabled": True})
    remote = next(
        r
        for r in client.get("/api/v2/secrets", headers=headers).json()["secrets"]
        if r["provider"] == "vaultwarden"
    )
    calls.clear()
    result = client.post(
        "/api/v2/secrets/" + local["id"] + "/migrate",
        headers=headers,
        json={
            "expected_version": 1,
            "target_id": remote["id"],
            "field": "login.password",
            "dry_run": True,
        },
    )
    assert result.status_code == 200 and result.json()["can_migrate"] and result.json()["dry_run"]
    assert "private-password" not in result.text
    assert not any(write for _, write in calls)
    with connection() as c:
        row = c.execute(
            "SELECT provider,version,encrypted_value FROM gh2_secret_handles WHERE id=?",
            (local["id"],),
        ).fetchone()
        assert (
            row["provider"] == "builtin"
            and row["version"] == 1
            and row["encrypted_value"] is not None
        )
    conflict = client.post(
        "/api/v2/secrets/" + local["id"] + "/migrate",
        headers=headers,
        json={
            "expected_version": 1,
            "target_id": remote["id"],
            "field": "login.username",
            "dry_run": True,
        },
    )
    assert (
        conflict.status_code == 409
        and conflict.headers["X-GlyphHold-Error"] == "secret_values_differ"
    )


def test_migration_creation_preview_does_not_create_anything(live_vault):
    client, headers, state, calls = live_vault
    vault.save_config({"enabled": False})
    local = client.post(
        "/api/v2/secrets", headers=headers, json={"name": "Preview only", "value": "test-only"}
    ).json()
    vault.save_config({"enabled": True})
    calls.clear()
    result = client.post(
        "/api/v2/secrets/" + local["id"] + "/migrate",
        headers=headers,
        json={"expected_version": 1, "dry_run": True, "folder_id": "home"},
    )
    assert result.status_code == 200 and result.json()["action"] == "create"
    assert not any(write for _, write in calls) and len(state["items"]) == 1


def test_cli_retries_reads_once_but_never_repeats_attempted_writes(secrets_client, monkeypatch):
    vault.save_config(
        {
            "enabled": True,
            "server_url": "https://vault.example.test",
            "client_id": "user.test",
            "client_secret": "test",
            "master_password": "test",
            "write_enabled": True,
        }
    )
    cli = vault.VaultCLI()
    calls = []
    monkeypatch.setattr(cli, "unlock", lambda config: None)

    def run(args, **kwargs):
        calls.append(args[0])
        if args[0] == "get" and calls.count("get") == 1:
            raise vault.VaultError("Safe retry", retryable=True)
        if args[0] == "create":
            raise vault.VaultError("Uncertain write", retryable=True)
        return {"id": "test"}

    monkeypatch.setattr(cli, "_run", run)
    assert cli.call(["get", "item", "test"]) == {"id": "test"} and calls.count("get") == 2
    with pytest.raises(vault.VaultError):
        cli.call(["create", "item"], payload={"notes": "test"}, write=True)
    assert calls.count("create") == 1


def test_cli_errors_are_safe_and_identify_the_failed_stage(secrets_client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        vault.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="private-value", stderr="ECONNRESET private-password"
        ),
    )
    cli = vault.VaultCLI()
    with pytest.raises(vault.VaultError) as error:
        cli._run(["sync"], config={"server_url": "https://vault.example.test", "client_id": "test"})
    assert error.value.code == "vault_sync_failed" and error.value.retryable
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "saved,query",
    [
        ("nas.example.test", "https://nas.example.test/login"),
        ("http://nas.example.test:8080", "https://nas.example.test/login"),
    ],
)
def test_full_website_queries_find_same_hostname_across_saved_url_formats(live_vault, saved, query):
    client, headers, state, _ = live_vault
    state["items"][0]["name"] = "Different service label"
    state["items"][0]["login"]["uris"] = [{"uri": saved}]
    response = client.get("/api/v2/secrets", headers=headers, params={"query": query})
    assert response.status_code == 200 and len(response.json()["secrets"]) == 1
