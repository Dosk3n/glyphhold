from __future__ import annotations

import json
import sqlite3
from functools import wraps
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.encryption import decrypt_secret, encrypt_secret, encryption_key_id
from app.core.ids import new_id
from app.providers import vault as provider
from app.providers import vault_proxy as proxy
from app.storage.db import connection
from app.storage.repositories.events import record_event
from app.utils.time import utc_now
from app.v2.api import principal
from app.v2.core import Principal, check_scope

router = APIRouter(prefix="/api/v2/secrets", tags=["v2 secrets"])
Auth = Annotated[Principal, Depends(principal)]


def public(row) -> dict:
    result = {k: v for k, v in dict(row).items() if k not in {"encrypted_value", "account_id"}}
    result["space_id"] = None
    return result


def local_rows() -> list[dict]:
    with connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM gh2_secret_handles ORDER BY name")]


def load(p: Principal, id_or_name: str, *, write: bool = False, space_id: str | None = None):
    # space_id is accepted for old clients, but secrets are global. Scopes still
    # authenticate and authorise secret access independently of memory grants.
    check_scope(p, "secrets:write" if write else "secrets:reveal")
    rows = local_rows()
    exact = [r for r in rows if r["id"] == id_or_name]
    if exact:
        return exact[0]
    if id_or_name.startswith("vw:"):
        if not provider.get_config(private=True)["enabled"]:
            raise provider.VaultError("External secret provider is disabled")
        return proxy.metadata(proxy.get_item(proxy.decode_reference(id_or_name)))
    matches = [r for r in rows if r["name"].casefold() == id_or_name.casefold()]
    if provider.get_config(private=True)["enabled"]:
        bound = {r["item_id"] for r in matches if r["provider"] == "vaultwarden"}
        matches += [
            proxy.metadata(r)
            for r in proxy.list_items()
            if (r.get("name") or "").casefold() == id_or_name.casefold() and r["id"] not in bound
        ]
    if not matches:
        raise HTTPException(404, "Secret not found")
    if len(matches) > 1:
        raise HTTPException(409, "Secret name is ambiguous; search and use its ID")
    return matches[0]


def vault_errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            with provider.vault.operation():
                return fn(*args, **kwargs)
        except provider.VaultError as exc:
            raise HTTPException(503, str(exc)) from exc

    return wrapped


def audit(p: Principal, action: str, row: dict):
    record_event(
        request_id="v2-secret",
        event_type="secret." + action,
        actor=p.actor,
        target_type="secret",
        target_id=row["id"],
        action=action,
        success=True,
        metadata={"space_id": row["space_id"], "provider": row["provider"]},
    )


def external_item(row: dict):
    config = provider.get_config(private=True)
    if not config["enabled"]:
        raise provider.VaultError("External secret provider is disabled")
    if row["account_id"] != provider.account_id(config):
        raise provider.VaultError("This secret is bound to a different provider account")
    item = provider.vault.call(["get", "item", row["item_id"]])
    provider.approved_item(config, row["space_id"], item)
    return item


def create_handle(p: Principal, fields: dict, external_link: bool = False):
    check_scope(p, "secrets:write")
    fields = dict(fields)
    fields["space_id"] = fields.get("space_id") or "space_general"
    if provider.get_config(private=True)["enabled"] and not external_link:
        with provider.vault.lock:
            proxy.ensure_unique(fields["name"], local_rows())
            result = proxy.metadata(proxy.create(fields))
            audit(p, "create", result)
            return result
    config = provider.get_config(private=True)
    now = utc_now()
    row = {
        "id": new_id("sec"),
        "name": fields["name"],
        "space_id": fields["space_id"],
        "description": fields.get("description"),
        "value_type": fields.get("value_type", "text"),
        "provider": "vaultwarden" if external_link or config["enabled"] else "builtin",
        "encrypted_value": None,
        "account_id": None,
        "item_id": None,
        "field": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    with connection() as conn:
        if conn.execute(
            "SELECT 1 FROM gh2_secret_handles WHERE lower(name)=lower(?)",
            (row["name"],),
        ).fetchone():
            raise HTTPException(
                409, "A secret with this name already exists; search and use its ID"
            )
    if row["provider"] == "builtin":
        if not fields.get("value"):
            raise HTTPException(400, "A secret value is required")
        row["encrypted_value"] = encrypt_secret(fields["value"])
    else:
        row["account_id"] = provider.account_id(config)
        row["item_id"], row["field"] = fields["item_id"], fields["field"]
        provider.get_field(external_item(row), row["field"])
    try:
        with connection() as conn:
            conn.execute(
                f"INSERT INTO gh2_secret_handles ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                tuple(row.values()),
            )
            if row["provider"] == "builtin":
                conn.execute(
                    "INSERT OR IGNORE INTO gh2_encryption_marker VALUES (?)", (encryption_key_id(),)
                )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            409, "Secret already exists; check the external vault before retrying"
        ) from exc
    audit(p, "link" if external_link else "create", row)
    return public(row)


class Create(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    space_id: str | None = None  # Deprecated, ignored for authorisation.
    folder_id: str | None = Field(default=None, max_length=200)
    value: str = Field(min_length=1, max_length=1048576)
    description: str | None = None
    value_type: str = Field(default="text", max_length=50)
    username: str | None = Field(default=None, max_length=8192)
    uri: str | None = Field(default=None, max_length=2048)


@router.get("")
@vault_errors
def list_handles(
    p: Auth, space_id: str | None = None, query: str = "", provider_name: str | None = None
):
    check_scope(p, "secrets:reveal")
    if provider_name not in {None, "builtin", "vaultwarden"}:
        raise HTTPException(400, "Unknown secret provider")
    enabled = provider.get_config(private=True)["enabled"]
    rows = [public(r) for r in local_rows() if r["provider"] == "builtin"]
    if enabled and provider_name != "builtin":
        names = {f["id"]: f["name"] for f in proxy.folders()}
        rows += [proxy.metadata(item, names) for item in proxy.list_items()]
    elif not enabled and provider_name != "builtin":
        rows += [public(r) for r in local_rows() if r["provider"] != "builtin"]
    rows = [
        r
        for r in rows
        if (not provider_name or r["provider"] == provider_name)
        and query.casefold()
        in (
            r["name"] + " " + (r.get("description") or "") + " " + (r.get("folder_name") or "")
        ).casefold()
    ]
    return {
        "secrets_enabled": True,
        "active_provider": "vaultwarden" if enabled else "builtin",
        "value_types": [
            "text",
            "password",
            "username",
            "api_key",
            "token",
            "webhook_url",
            "json",
            "ssh_key",
        ],
        "secrets": sorted(rows, key=lambda r: r["name"].casefold()),
    }


@router.get("/folders")
@vault_errors
def list_folders(p: Auth):
    check_scope(p, "secrets:reveal")
    enabled = provider.get_config(private=True)["enabled"]
    return {"supported": enabled, "folders": proxy.folders() if enabled else []}


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/folders", status_code=201)
@vault_errors
def create_folder(payload: FolderCreate, p: Auth):
    check_scope(p, "secrets:write")
    with provider.vault.lock:
        existing = [f for f in proxy.folders() if f["name"].casefold() == payload.name.casefold()]
        if existing:
            raise HTTPException(409, "Folder already exists; use the existing folder ID")
        folder = provider.vault.call(
            ["create", "folder"], write=True, payload={"name": payload.name}
        )
    return {"id": folder["id"], "name": folder["name"]}


@router.post("", status_code=201)
@vault_errors
def create_secret(payload: Create, p: Auth):
    with provider.vault.lock:
        return create_handle(p, payload.model_dump(exclude_unset=True))


@router.get("/{id_or_name}")
@vault_errors
def metadata(id_or_name: str, p: Auth, space_id: str | None = None):
    return public(load(p, id_or_name, space_id=space_id))


class Reveal(BaseModel):
    requesting_agent: str | None = Field(default=None, max_length=128)
    tool: str | None = Field(default=None, max_length=128)
    field: str | None = Field(default=None, max_length=200)


def resolved_item(row: dict) -> dict:
    return (
        proxy.get_item(proxy.decode_reference(row["id"]))
        if row.get("direct")
        else external_item(row)
    )


@router.post("/{id_or_name}/reveal")
@vault_errors
def reveal(id_or_name: str, p: Auth, payload: Reveal | None = None, space_id: str | None = None):
    row = dict(load(p, id_or_name, space_id=space_id))
    if not p.admin:
        from app.storage.repositories.secrets import _check_reveal_allowed

        with connection() as conn:
            legacy = conn.execute(
                "SELECT metadata_json FROM gh2_secret_provenance WHERE handle_id=?", (row["id"],)
            ).fetchone()
        if legacy:
            try:
                _check_reveal_allowed(
                    json.loads(legacy["metadata_json"]),
                    requesting_agent=(payload.requesting_agent if payload else None) or p.actor,
                    tool=payload.tool if payload else None,
                )
            except PermissionError as exc:
                raise HTTPException(
                    403, "Legacy secret caller restrictions were not satisfied"
                ) from exc
    field = None
    if row["provider"] == "builtin":
        value = decrypt_secret(row["encrypted_value"])
    else:
        item = resolved_item(row)
        field = proxy.selected_field(item, (payload.field if payload else None) or row.get("field"))
        value = provider.get_field(item, field)
    audit(p, "reveal", row)
    return {"name": row["name"], "field": field, "value": value, "expires_in_seconds": 60}


class Patch(BaseModel):
    expected_version: int | str
    value: str | None = Field(default=None, max_length=1048576)
    field: str | None = Field(default=None, max_length=200)
    description: str | None = None
    space_id: str | None = None  # Deprecated.
    folder_id: str | None = Field(default=None, max_length=200)


@router.patch("/{id_or_name}")
@vault_errors
def update(id_or_name: str, payload: Patch, p: Auth):
    with provider.vault.lock:
        row = dict(load(p, id_or_name, write=True))
        if row["version"] != payload.expected_version:
            raise HTTPException(409, "Secret changed; reread before updating")
        if row.get("direct"):
            item = resolved_item(row)
            if proxy.version(item) != payload.expected_version:
                raise HTTPException(409, "Vault item changed; reread before updating")
            if "description" in payload.model_fields_set and payload.description:
                raise HTTPException(
                    400, "Vault notes are secret values; use field=notes explicitly"
                )
            if payload.value is not None:
                item = provider.set_field(
                    item, proxy.selected_field(item, payload.field), payload.value
                )
            if "folder_id" in payload.model_fields_set:
                item["folderId"] = proxy.folder_destination(payload.folder_id, explicit=True)
            result = proxy.metadata(
                provider.vault.call(["edit", "item", item["id"]], payload=item, write=True)
            )
            audit(p, "update", result)
            return result
        encrypted = row["encrypted_value"]
        if payload.value is not None:
            if row["provider"] == "builtin":
                encrypted = encrypt_secret(payload.value)
            else:
                item = provider.set_field(external_item(row), row["field"], payload.value)
                provider.vault.call(["edit", "item", row["item_id"]], payload=item, write=True)
        description = (
            payload.description if "description" in payload.model_fields_set else row["description"]
        )
        with connection() as conn:
            changed = conn.execute(
                "UPDATE gh2_secret_handles SET encrypted_value=?,description=?,version=version+1,updated_at=? WHERE id=? AND version=?",
                (encrypted, description, utc_now(), row["id"], payload.expected_version),
            ).rowcount
            if not changed:
                raise HTTPException(409, "Secret changed; reread before updating")
        audit(p, "update", row)
        return public(load(p, row["id"]))


class Migrate(BaseModel):
    expected_version: int = Field(ge=1)
    target_id: str | None = Field(default=None, max_length=300)
    field: str | None = Field(default=None, max_length=200)
    folder_id: str | None = Field(default=None, max_length=200)


@router.post("/{id_or_name}/migrate")
@vault_errors
def migrate(id_or_name: str, payload: Migrate, p: Auth):
    # Transfer server-to-server, never via an agent response or plaintext file.
    check_scope(p, "secrets:reveal")
    with provider.vault.lock:
        row = dict(load(p, id_or_name, write=True))
        config = provider.get_config(private=True)
        if not config["enabled"] or not config["write_enabled"]:
            raise HTTPException(409, "Enable Vaultwarden and external writes first")
        if row["provider"] != "builtin" or row["version"] != payload.expected_version:
            raise HTTPException(409, "Reread the built-in secret before migrating")
        value = decrypt_secret(row["encrypted_value"])
        if payload.target_id:
            item = proxy.get_item(proxy.decode_reference(payload.target_id))
            field = proxy.selected_field(item, payload.field)
            if not hmac_compare(provider.get_field(item, field), value):
                raise HTTPException(
                    409, "Values differ; existing vault item and built-in secret were retained"
                )
        else:
            fields = {"name": row["name"], "value": value, "value_type": row["value_type"]}
            if "folder_id" in payload.model_fields_set:
                fields["folder_id"] = payload.folder_id
            item = proxy.create(fields)
            field = proxy.selected_field(item, None)
        verified = proxy.get_item(item["id"])
        if not hmac_compare(provider.get_field(verified, field), value):
            raise HTTPException(409, "Destination verification failed; built-in secret retained")
        with connection() as conn:
            changed = conn.execute(
                "UPDATE gh2_secret_handles SET provider='vaultwarden',account_id=?,item_id=?,field=?,encrypted_value=NULL,version=version+1,updated_at=? WHERE id=? AND version=? AND provider='builtin'",
                (
                    provider.account_id(config),
                    item["id"],
                    field,
                    utc_now(),
                    row["id"],
                    row["version"],
                ),
            ).rowcount
            if not changed:
                raise HTTPException(409, "Local secret changed; vault item retained for review")
        audit(p, "migrate", row)
        return {
            "migrated": True,
            "secret": proxy.metadata(verified),
            "legacy_id": row["id"],
            "value_verified": True,
        }


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())


@router.delete("/{id_or_name}")
@vault_errors
def unlink(id_or_name: str, p: Auth, expected_version: int):
    row = dict(load(p, id_or_name, write=True))
    if row.get("direct"):
        raise HTTPException(409, "Manage deletion of vault items in Bitwarden or Vaultwarden")
    with connection() as conn:
        if not conn.execute(
            "DELETE FROM gh2_secret_handles WHERE id=? AND version=?", (row["id"], expected_version)
        ).rowcount:
            raise HTTPException(409, "Secret changed; reread before unlinking")
    audit(p, "unlink", row)
    return {"ok": True, "external_item_deleted": False}
