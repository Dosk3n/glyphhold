from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from app.config import settings
from app.core.encryption import decrypt_secret, encrypt_secret, encryption_key_id
from app.storage.db import connection
from app.utils.time import utc_now

DEFAULTS = {
    "enabled": False,
    "server_url": "",
    "client_id": "",
    "client_secret": "",
    "master_password": "",
    "write_enabled": False,
    "folder_mappings": {},  # Legacy configuration retained for rollback only.
    "default_folder_id": None,
}
SENSITIVE = {"client_id", "client_secret", "master_password"}


def initialize() -> None:
    with connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS gh2_encryption_marker(key_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS gh2_secret_provenance(handle_id TEXT PRIMARY KEY,metadata_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gh2_secret_handles(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, space_id TEXT NOT NULL,
          description TEXT, value_type TEXT NOT NULL DEFAULT 'text', provider TEXT NOT NULL,
          encrypted_value BLOB, account_id TEXT, item_id TEXT, field TEXT,
          version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(space_id,name));
        """)
        if not conn.execute(
            "SELECT 1 FROM app_settings WHERE key='gh2_legacy_secrets_migrated'"
        ).fetchone():
            conn.execute("""INSERT OR IGNORE INTO gh2_secret_handles
              (id,name,space_id,description,value_type,provider,encrypted_value,version,created_at,updated_at)
              SELECT id,name,'space_import_review',description,value_type,'builtin',encrypted_value,1,created_at,updated_at
              FROM secrets""")
            for row in conn.execute("SELECT * FROM secrets").fetchall():
                metadata = {
                    k: v
                    for k, v in dict(row).items()
                    if k not in {"encrypted_value", "encryption_key_id"}
                }
                conn.execute(
                    "INSERT OR IGNORE INTO gh2_secret_provenance VALUES (?,?)",
                    (row["id"], json.dumps(metadata)),
                )
            now = utc_now()
            conn.execute(
                "INSERT INTO app_settings VALUES ('gh2_legacy_secrets_migrated','true',?,?)",
                (now, now),
            )


def get_config(private: bool = False) -> dict:
    from app.storage.repositories.settings import get_setting

    raw = get_setting("gh2_vault_config")
    config = dict(DEFAULTS)
    if raw:
        config.update(json.loads(decrypt_secret(raw.encode())))
    if private:
        return config
    public = {k: v for k, v in config.items() if k not in SENSITIVE}
    public.update({k + "_configured": bool(config.get(k)) for k in SENSITIVE})
    public["configured"] = all(config.get(k) for k in SENSITIVE) and bool(config["server_url"])
    public["cli_available"] = shutil.which("bw") is not None
    return public


def save_config(fields: dict) -> dict:
    with vault.lock:
        return _save_config(dict(fields))


def _save_config(fields: dict) -> dict:
    config = get_config(private=True)
    unknown = set(fields) - set(DEFAULTS) - {"clear_credentials"}
    if unknown:
        raise ValueError("Unknown provider settings")
    if fields.pop("clear_credentials", False):
        for key in SENSITIVE:
            config[key] = ""
    for key, value in fields.items():
        if key in SENSITIVE and value == "":
            continue  # Empty password fields mean keep the saved credential.
        config[key] = value
    url = urlsplit(config["server_url"])
    if config["server_url"] and (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Server URL must be an HTTP(S) origin without credentials or query")
    if config["server_url"] and url.scheme != "https":
        raise ValueError("Bitwarden CLI requires an HTTPS server URL with a trusted certificate")
    if config["enabled"] and not all(config.get(k) for k in (*SENSITIVE, "server_url")):
        raise ValueError("Server URL, personal API credentials and master password are required")
    if not isinstance(config["folder_mappings"], dict):
        raise TypeError("Folder mappings must be an object")
    for mapping in config["folder_mappings"].values():
        if not isinstance(mapping, dict) or not isinstance(mapping.get("folder_ids", []), list):
            raise TypeError("Each folder mapping needs folder_ids and an optional write_folder_id")
        if mapping.get("write_folder_id") and mapping["write_folder_id"] not in mapping.get(
            "folder_ids", []
        ):
            raise ValueError("Write folder must be one of the approved folders")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO app_settings VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            ("gh2_vault_config", encrypt_secret(json.dumps(config)).decode(), now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO gh2_encryption_marker VALUES (?)", (encryption_key_id(),)
        )
    vault.reset()
    return get_config()


def account_id(config: dict) -> str:
    import hashlib

    return hashlib.sha256(
        (config["server_url"].rstrip("/") + "|" + config["client_id"]).encode()
    ).hexdigest()


class VaultError(RuntimeError):
    def __init__(self, message: str, *, code: str = "vault_unavailable", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def failure(args: list[str], *, retryable: bool = False) -> VaultError:
    operation = (
        args[0]
        if args
        and args[0]
        in {"status", "config", "login", "unlock", "sync", "get", "list", "create", "edit"}
        else "operation"
    )
    advice = (
        "Check whether the destination changed before retrying."
        if operation in {"create", "edit"}
        else "Test the saved connection or repeat this read."
    )
    return VaultError(
        f"Vault {operation} failed. {advice}",
        code="vault_" + operation + "_failed",
        retryable=retryable,
    )


class VaultCLI:
    def __init__(self):
        self.lock = threading.RLock()
        self.session: str | None = None
        self.operation_depth = 0
        self.operation_synced = False

    @contextmanager
    def operation(self):
        """One fresh sync per logical operation, and again after any write."""
        with self.lock:
            if not self.operation_depth:
                self.operation_synced = False
            self.operation_depth += 1
            try:
                yield
            finally:
                self.operation_depth -= 1
                if not self.operation_depth:
                    self.operation_synced = False

    def reset(self):
        with self.lock:
            self.session = None
            self.operation_synced = False

    def _run(
        self,
        args: list[str],
        *,
        config: dict,
        data: str | None = None,
        extra: dict | None = None,
        raw: bool = False,
    ):
        provider_home = Path(settings.db_path).parent / "bitwarden"
        provider_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        provider_home.chmod(0o700)
        directory = provider_home / account_id(config)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        # Do not forward unrelated host/API credentials into provider processes.
        env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "HOME", "LANG", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"}
        }
        env.update({"BITWARDENCLI_APPDATA_DIR": str(directory), "BW_NOINTERACTION": "true"})
        if self.session:
            env["BW_SESSION"] = self.session
        env.update(extra or {})
        try:
            result = subprocess.run(
                ["bw", *args, "--nointeraction"],
                check=False,
                input=data,
                text=True,
                capture_output=True,
                env=env,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise failure(args) from exc
        if result.returncode:
            # Classify only known failures; never forward raw CLI output or data.
            output = (result.stderr + " " + result.stdout).casefold()
            if args[:2] == ["get", "item"] and (
                result.stderr.strip().casefold() in {"not found", "not found."}
                or result.stdout.strip().casefold() in {"not found", "not found."}
            ):
                raise VaultError(
                    "Vault item not found; search again and use a current ID",
                    code="vault_item_not_found",
                )
            transient = args[0] in {"get", "list", "sync"} or any(
                marker in output
                for marker in (
                    "your vault is locked",
                    "you are not logged in",
                    "invalid session",
                    "econnreset",
                    "econnrefused",
                    "etimedout",
                )
            )
            raise failure(args, retryable=transient)
        if raw:
            return result.stdout.strip()
        try:
            return json.loads(result.stdout or "null")
        except json.JSONDecodeError as exc:
            raise VaultError("Vault returned an invalid response") from exc

    def unlock(self, config: dict):
        if not config["enabled"]:
            raise VaultError("External secret provider is disabled")
        if not all(config.get(k) for k in (*SENSITIVE, "server_url")):
            raise VaultError(
                "Save the server URL, personal API client ID and secret, and master password before testing"
            )
        if not self.session:
            status = self._run(["status"], config=config)
            # Configuring an already logged-in CLI fails after a GH2 restart.
            # Its private account directory already retains the correct server.
            if (status.get("serverUrl") or "").rstrip("/") != config["server_url"].rstrip("/"):
                if status.get("status") != "unauthenticated":
                    self._run(["logout"], config=config, raw=True)
                self._run(["config", "server", config["server_url"]], config=config, raw=True)
                status = self._run(["status"], config=config)
            if status.get("status") == "unauthenticated":
                self._run(
                    ["login", "--apikey"],
                    config=config,
                    raw=True,
                    extra={
                        "BW_CLIENTID": config["client_id"],
                        "BW_CLIENTSECRET": config["client_secret"],
                    },
                )
            self.session = self._run(
                ["unlock", "--passwordenv", "GH2_VAULT_PASSWORD", "--raw"],
                config=config,
                raw=True,
                extra={"GH2_VAULT_PASSWORD": config["master_password"]},
            )
            if not self.session:
                raise VaultError("Vault unlock did not return a session")

    def call(
        self,
        args: list[str],
        *,
        payload: dict | None = None,
        write: bool = False,
        allow_disabled: bool = False,
    ):
        with self.lock:
            config = get_config(private=True)
            if allow_disabled:
                config = config | {"enabled": True}
            if write and not config["write_enabled"]:
                raise VaultError("External writes are disabled")
            for attempt in range(2):
                mutation_started = False
                try:
                    self.unlock(config)
                    if not self.operation_depth or not self.operation_synced:
                        self._run(["sync"], config=config, raw=True)
                        self.operation_synced = True
                    data = (
                        base64.b64encode(json.dumps(payload).encode()).decode()
                        if payload is not None
                        else None
                    )
                    mutation_started = write
                    result = self._run(args, config=config, data=data)
                    if write:
                        self.operation_synced = False
                    return result
                except VaultError as exc:
                    self.session = None
                    self.operation_synced = False
                    # Only repeat safe reads/preparation. A mutation may have
                    # reached the vault even when its acknowledgement was lost.
                    if attempt == 0 and not mutation_started and exc.retryable:
                        continue
                    raise


vault = VaultCLI()


def approved_item(config: dict, space_id: str, item: dict) -> None:
    # Folders organise secrets; they are independent of memory spaces.
    if not config["enabled"]:
        raise VaultError("External secret provider is disabled")


def get_field(item: dict, field: str) -> str:
    if field in {
        "card.cardholderName",
        "card.number",
        "card.brand",
        "card.expMonth",
        "card.expYear",
        "card.code",
        *{
            "identity." + key
            for key in (
                "title",
                "firstName",
                "middleName",
                "lastName",
                "address1",
                "address2",
                "address3",
                "city",
                "state",
                "postalCode",
                "country",
                "company",
                "email",
                "phone",
                "ssn",
                "username",
                "passportNumber",
                "licenseNumber",
            )
        },
        "login.username",
        "login.password",
        "login.totp",
        "sshKey.privateKey",
        "sshKey.publicKey",
        "sshKey.keyFingerprint",
    }:
        group, key = field.split(".")
        value = (item.get(group) or {}).get(key)
    elif field == "notes":
        value = item.get("notes")
    elif field.startswith("custom:"):
        matches = [f for f in (item.get("fields") or []) if f.get("name") == field[7:]]
        if len(matches) != 1:
            raise VaultError("Custom field is missing or ambiguous")
        value = matches[0].get("value")
    else:
        raise ValueError("Unsupported item field")
    if not isinstance(value, str):
        raise VaultError("Selected item field has no text value")
    return value


def set_field(item: dict, field: str, value: str) -> dict:
    get_field(item, field)  # Validate field and ambiguity before modifying.
    if field.startswith("custom:"):
        next(f for f in item["fields"] if f["name"] == field[7:])["value"] = value
    elif field == "notes":
        item["notes"] = value
    else:
        group, key = field.split(".")
        item[group][key] = value
    return item
