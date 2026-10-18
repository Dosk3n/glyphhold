from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.encryption import decrypt_secret, encrypt_secret, encryption_key_id
from app.core.ids import new_id
from app.providers import vault as provider
from app.storage.db import connection
from app.storage.repositories.events import record_event
from app.utils.time import utc_now
from app.v2.api import principal
from app.v2.core import Principal, check_scope, list_spaces, require_space

router = APIRouter(prefix="/api/v2/secrets", tags=["v2 secrets"])
Auth = Annotated[Principal, Depends(principal)]


def public(row) -> dict:
    return {k: v for k, v in dict(row).items() if k not in {"encrypted_value", "account_id"}}


def load(p: Principal, id_or_name: str, *, write: bool = False, space_id: str | None = None):
    check_scope(p, "secrets:write" if write else "secrets:reveal")
    allowed = {s["id"] for s in list_spaces(p) if s.get("can_read")}
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM gh2_secret_handles WHERE id=? OR name=?", (id_or_name, id_or_name)
        ).fetchall()
    matches = [
        r for r in rows if r["space_id"] in allowed and (not space_id or r["space_id"] == space_id)
    ]
    if not matches:
        raise HTTPException(404, "Secret not found")
    if len(matches) > 1:
        raise HTTPException(409, "Secret name is ambiguous; use its ID or specify space_id")
    require_space(p, matches[0]["space_id"], write=write)
    return matches[0]


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
    require_space(p, fields["space_id"], write=True)
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
            "SELECT 1 FROM gh2_secret_handles WHERE space_id=? AND name=?",
            (row["space_id"], row["name"]),
        ).fetchone():
            raise HTTPException(409, "A secret with this name already exists in the space")
    if row["provider"] == "builtin":
        if not fields.get("value"):
            raise HTTPException(400, "A secret value is required")
        row["encrypted_value"] = encrypt_secret(fields["value"])
    else:
        row["account_id"] = provider.account_id(config)
        if external_link:
            row["item_id"], row["field"] = fields["item_id"], fields["field"]
            provider.get_field(external_item(row), row["field"])
        else:
            if not fields.get("value"):
                raise HTTPException(400, "A secret value is required")
            folder = config["folder_mappings"].get(row["space_id"], {}).get("write_folder_id")
            if not folder:
                raise HTTPException(400, "Select an approved write folder for this space first")
            item = provider.vault.call(
                ["create", "item"],
                write=True,
                payload={
                    "type": 2,
                    "name": row["name"],
                    "folderId": folder,
                    "secureNote": {"type": 0},
                    "notes": fields["value"],
                },
            )
            row["item_id"], row["field"] = item["id"], "notes"
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
    space_id: str
    value: str = Field(min_length=1, max_length=1048576)
    description: str | None = None
    value_type: str = Field(default="text", max_length=50)


@router.get("")
def list_handles(p: Auth, space_id: str | None = None, query: str = ""):
    check_scope(p, "secrets:reveal")
    allowed = {s["id"] for s in list_spaces(p) if s.get("can_read")}
    if space_id:
        require_space(p, space_id)
        allowed &= {space_id}
    with connection() as conn:
        rows = conn.execute("SELECT * FROM gh2_secret_handles ORDER BY name").fetchall()
    return {
        "secrets_enabled": True,
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
        "secrets": [
            public(r)
            for r in rows
            if r["space_id"] in allowed
            and query.lower() in (r["name"] + " " + (r["description"] or "")).lower()
        ],
    }


@router.post("", status_code=201)
def create_secret(payload: Create, p: Auth):
    try:
        return create_handle(p, payload.model_dump())
    except provider.VaultError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/{id_or_name}")
def metadata(id_or_name: str, p: Auth, space_id: str | None = None):
    return public(load(p, id_or_name, space_id=space_id))


@router.post("/{id_or_name}/reveal")
def reveal(id_or_name: str, p: Auth, space_id: str | None = None):
    row = dict(load(p, id_or_name, space_id=space_id))
    try:
        value = (
            decrypt_secret(row["encrypted_value"])
            if row["provider"] == "builtin"
            else provider.get_field(external_item(row), row["field"])
        )
    except (provider.VaultError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    audit(p, "reveal", row)
    return {"name": row["name"], "value": value, "expires_in_seconds": 60}


class Patch(BaseModel):
    expected_version: int = Field(ge=1)
    value: str | None = Field(default=None, max_length=1048576)
    description: str | None = None
    space_id: str | None = None


@router.patch("/{id_or_name}")
def update(id_or_name: str, payload: Patch, p: Auth):
    row = dict(load(p, id_or_name, write=True))
    if row["version"] != payload.expected_version:
        raise HTTPException(409, "Secret changed; reread before updating")
    destination = payload.space_id or row["space_id"]
    require_space(p, destination, write=True)
    if destination != row["space_id"] and row["provider"] != "builtin":
        raise HTTPException(
            409, "External bindings must be deliberately relinked to an approved destination folder"
        )
    encrypted = row["encrypted_value"]
    if payload.value is not None:
        if row["provider"] == "builtin":
            encrypted = encrypt_secret(payload.value)
        else:
            try:
                item = external_item(row)
                item = provider.set_field(item, row["field"], payload.value)
                provider.vault.call(["edit", "item", row["item_id"]], payload=item, write=True)
            except (provider.VaultError, ValueError) as exc:
                raise HTTPException(503, str(exc)) from exc
    description = (
        payload.description if "description" in payload.model_fields_set else row["description"]
    )
    with connection() as conn:
        try:
            changed = conn.execute(
                "UPDATE gh2_secret_handles SET encrypted_value=?,description=?,space_id=?,version=version+1,updated_at=? WHERE id=? AND version=?",
                (
                    encrypted,
                    description,
                    destination,
                    utc_now(),
                    row["id"],
                    payload.expected_version,
                ),
            ).rowcount
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Destination already has a secret with this name") from exc
        if not changed:
            raise HTTPException(409, "Secret changed; external edit may already have completed")
    audit(p, "update", row)
    return public(load(p, row["id"]))


@router.delete("/{id_or_name}")
def unlink(id_or_name: str, p: Auth, expected_version: int):
    row = dict(load(p, id_or_name, write=True))
    with connection() as conn:
        if not conn.execute(
            "DELETE FROM gh2_secret_handles WHERE id=? AND version=?", (row["id"], expected_version)
        ).rowcount:
            raise HTTPException(409, "Secret changed; reread before unlinking")
    audit(p, "unlink", row)
    return {"ok": True, "external_item_deleted": False}
