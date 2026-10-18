from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_dashboard_user
from app.providers import vault as provider

router = APIRouter(
    prefix="/dashboard/api/providers/secrets",
    tags=["secret provider settings"],
    dependencies=[Depends(require_dashboard_user)],
)


class ProviderSettings(BaseModel):
    enabled: bool | None = None
    server_url: str | None = Field(default=None, max_length=2048)
    client_id: str | None = Field(default=None, max_length=2048)
    client_secret: str | None = Field(default=None, max_length=8192)
    master_password: str | None = Field(default=None, max_length=8192)
    write_enabled: bool | None = None
    folder_mappings: dict | None = None
    default_folder_id: str | None = Field(default=None, max_length=200)
    clear_credentials: bool = False


def provider_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ValueError, TypeError, provider.VaultError)):
        return HTTPException(400, str(exc))
    return HTTPException(
        503, "Secret provider unavailable; check saved credentials, unlock and server status"
    )


@router.get("")
def read_settings():
    return provider.get_config()


@router.put("")
def update_settings(payload: ProviderSettings):
    try:
        fields = payload.model_dump(exclude_none=True)
        if "default_folder_id" in payload.model_fields_set:
            fields["default_folder_id"] = payload.default_folder_id
        return provider.save_config(fields)
    except Exception as exc:
        raise provider_error(exc) from exc


@router.post("/test")
def test_provider():
    try:
        folders = provider.vault.call(["list", "folders"], allow_disabled=True)
        return {"status": "unlocked", "folder_count": len(folders)}
    except Exception as exc:
        raise provider_error(exc) from exc


@router.get("/folders")
def folders():
    try:
        return {"folders": provider.vault.call(["list", "folders"])}
    except Exception as exc:
        raise provider_error(exc) from exc


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/folders")
def create_folder(payload: FolderCreate):
    try:
        return provider.vault.call(["create", "folder"], payload={"name": payload.name}, write=True)
    except Exception as exc:
        raise provider_error(exc) from exc


@router.get("/items")
def items(folder_id: str):
    if not folder_id or folder_id.startswith("-"):
        raise HTTPException(400, "Invalid folder ID")
    try:
        rows = provider.vault.call(["list", "items", "--folderid", folder_id])
        return {
            "items": [
                {
                    "id": r["id"],
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "folder_id": r.get("folderId"),
                    "fields": available_fields(r),
                }
                for r in rows
            ]
        }
    except Exception as exc:
        raise provider_error(exc) from exc


from app.providers.vault_proxy import available_fields


class LinkRequest(BaseModel):
    space_id: str
    name: str = Field(min_length=1, max_length=200)
    item_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
    field: str
    value_type: str = "text"
    description: str | None = None


@router.post("/link")
def link_item(payload: LinkRequest):
    from app.api.v2_secrets import create_handle
    from app.v2.core import ADMIN

    try:
        return create_handle(ADMIN, payload.model_dump(), external_link=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise provider_error(exc) from exc


class TransferRequest(BaseModel):
    package: dict
    password: str = Field(min_length=12, max_length=8192)
    namespace: str = Field(min_length=1, max_length=200)
    space_id: str = "space_import_review"


@router.post("/migration/preview")
def preview_transfer(payload: TransferRequest):
    from app.providers.transfer import import_package

    try:
        return import_package(**payload.model_dump())
    except Exception as exc:
        raise provider_error(exc) from exc


@router.post("/migration/apply")
def apply_transfer(payload: TransferRequest):
    from app.providers.transfer import import_package

    try:
        return import_package(**payload.model_dump(), apply=True)
    except Exception as exc:
        raise provider_error(exc) from exc


class ExternalTransferItem(BaseModel):
    id: str
    expected_version: int = Field(ge=1)


class ExternalTransfer(BaseModel):
    items: list[ExternalTransferItem] = Field(min_length=1, max_length=20)


def external_transfer_plan(payload: ExternalTransfer):
    from app.storage.db import connection

    config = provider.get_config(private=True)
    if not config["enabled"] or not config["write_enabled"]:
        raise ValueError("Enable the external provider and its write capability first")
    items, conflicts = [], []
    with connection() as conn:
        for selected in payload.items:
            row = conn.execute(
                "SELECT * FROM gh2_secret_handles WHERE id=?", (selected.id,)
            ).fetchone()
            if not row or row["version"] != selected.expected_version:
                conflicts.append(
                    {"id": selected.id, "reason": "Secret changed or no longer exists"}
                )
                continue
            if row["provider"] != "builtin":
                conflicts.append(
                    {"id": selected.id, "reason": "Secret is already externally bound"}
                )
                continue
            folder = config.get("default_folder_id")
            items.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "space_id": row["space_id"],
                    "version": row["version"],
                    "folder_id": folder,
                }
            )
    return {"items": items, "conflicts": conflicts}


@router.post("/migration/external/preview")
def preview_external_transfer(payload: ExternalTransfer):
    try:
        return external_transfer_plan(payload)
    except Exception as exc:
        raise provider_error(exc) from exc


@router.post("/migration/external/apply")
def apply_external_transfer(payload: ExternalTransfer):
    from app.core.encryption import decrypt_secret
    from app.storage.db import connection
    from app.storage.repositories.events import record_event
    from app.utils.time import utc_now

    completed = []
    try:
        plan = external_transfer_plan(payload)
        if plan["conflicts"]:
            raise ValueError("Resolve preview conflicts before migrating")
        config = provider.get_config(private=True)
        account = provider.account_id(config)
        with provider.vault.lock:
            for selected in plan["items"]:
                with connection() as conn:
                    row = conn.execute(
                        "SELECT * FROM gh2_secret_handles WHERE id=?", (selected["id"],)
                    ).fetchone()
                if not row or row["version"] != selected["version"] or row["provider"] != "builtin":
                    raise ValueError("Secret changed; preview again before continuing")
                value = decrypt_secret(row["encrypted_value"])
                # A stable marker allows retry to recover an upstream create whose
                # result was not committed locally. Never identify by alias alone.
                remote_name = row["name"] + " [GH2:" + row["id"] + "]"
                remote = provider.vault.call(["list", "items"])
                ordinary = [
                    item
                    for item in remote
                    if (item.get("name") or "").casefold() == row["name"].casefold()
                ]
                if ordinary:
                    raise ValueError(
                        "A vault item with this name exists; use the secret migrate tool with its target ID and field to verify it without overwriting"
                    )
                matches = [item for item in remote if item.get("name") == remote_name]
                if len(matches) > 1:
                    raise ValueError(
                        "Multiple migration-marked vault items exist; resolve them before retrying"
                    )
                if matches:
                    item = matches[0]
                    if provider.get_field(item, "notes") != value:
                        raise ValueError(
                            "Existing migration-marked item differs from the local value"
                        )
                else:
                    item = provider.vault.call(
                        ["create", "item"],
                        write=True,
                        payload={
                            "type": 2,
                            "name": remote_name,
                            "folderId": selected["folder_id"],
                            "secureNote": {"type": 0},
                            "notes": value,
                        },
                    )
                verified = provider.vault.call(["get", "item", item["id"]])
                if (
                    provider.get_field(verified, "notes") != value
                    or verified.get("folderId") != selected["folder_id"]
                ):
                    raise ValueError("Destination verification failed; local secret retained")
                current_config = provider.get_config(private=True)
                if not current_config["enabled"] or provider.account_id(current_config) != account:
                    raise ValueError("Provider configuration changed; local secret retained")
                provider.approved_item(current_config, selected["space_id"], verified)
                with connection() as conn:
                    if not conn.execute(
                        "UPDATE gh2_secret_handles SET provider='vaultwarden',account_id=?,item_id=?,field='notes',encrypted_value=NULL,version=version+1,updated_at=? WHERE id=? AND version=? AND provider='builtin'",
                        (account, item["id"], utc_now(), row["id"], selected["version"]),
                    ).rowcount:
                        raise ValueError(
                            "Secret changed during transfer; local value retained and destination needs review"
                        )
                record_event(
                    request_id="secret-provider-transfer",
                    event_type="secret.migrate",
                    actor="dashboard",
                    target_type="secret",
                    target_id=row["id"],
                    action="migrate",
                    success=True,
                    metadata={"provider": "vaultwarden", "space_id": row["space_id"]},
                )
                completed.append(
                    {"id": row["id"], "provider": "vaultwarden", "version": selected["version"] + 1}
                )
        return plan | {"migrated": completed}
    except Exception as exc:
        if completed:
            return {
                "migrated": completed,
                "partial": True,
                "conflicts": [
                    {
                        "reason": "Transfer stopped after some items completed. Refresh metadata and preview remaining built-in items before retrying."
                    }
                ],
            }
        raise provider_error(exc) from exc
