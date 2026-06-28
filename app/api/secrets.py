from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.core.auth import ApiPrincipal, require_scope
from app.core.encryption import SecretDecryptionError, SecretStorageDisabled
from app.core.request_context import get_request_id
from app.storage.repositories import secrets
from app.storage.repositories.events import record_event

router = APIRouter(prefix="/api/v1/secrets", tags=["secrets"])


class SecretCreate(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    description: str | None = None
    value_type: str = "text"
    service: str | None = None
    host: str | None = None
    scope: str | None = None
    tags: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)


class SecretPatch(BaseModel):
    name: str | None = None
    value: str | None = None
    description: str | None = None
    value_type: str | None = None
    service: str | None = None
    host: str | None = None
    scope: str | None = None
    tags: list[str] | None = None
    allowed_agents: list[str] | None = None
    allowed_tools: list[str] | None = None


class SecretRevealRequest(BaseModel):
    requesting_agent: str | None = None
    tool: str | None = None
    purpose: str | None = None


class SecretEnvRequest(BaseModel):
    scope: str | None = None
    requesting_agent: str | None = None
    purpose: str | None = None


def _secret_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SecretStorageDisabled):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, SecretDecryptionError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_secrets(
    _: Annotated[ApiPrincipal, Depends(require_scope("secrets:read"))],
    query: str | None = None,
    service: str | None = None,
    host: str | None = None,
    scope: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return secrets.list_secrets(
        query=query,
        service=service,
        host=host,
        scope=scope,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_secret(
    payload: SecretCreate,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("secrets:write"))],
) -> dict:
    try:
        secret = secrets.create_secret(**payload.model_dump())
    except Exception as exc:
        raise _secret_error(exc) from exc
    record_event(
        request_id=get_request_id(request),
        event_type="secret.create",
        actor=principal.actor,
        target_type="secret",
        target_id=secret["name"],
        action="create",
        success=True,
        message=secret["name"],
    )
    return secret


@router.post("/env")
def reveal_env(
    payload: SecretEnvRequest,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("secrets:reveal"))],
) -> dict:
    selected = secrets.list_secrets(scope=payload.scope, limit=500)
    values = {}
    try:
        for secret in selected:
            _, value = secrets.reveal_secret(secret["id"])
            values[secret["name"]] = value
    except Exception as exc:
        raise _secret_error(exc) from exc
    record_event(
        request_id=get_request_id(request),
        event_type="secret.env",
        actor=payload.requesting_agent or principal.actor,
        target_type="secret",
        action="env",
        success=True,
        result_count=len(values),
        purpose=payload.purpose,
        metadata={"scope": payload.scope, "secret_names": list(values)},
    )
    return {"format": "env", "values": values}


@router.get("/{id_or_name}")
def get_secret(
    id_or_name: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("secrets:read"))],
) -> dict:
    secret = secrets.get_secret_metadata(id_or_name)
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    return secret


@router.patch("/{id_or_name}")
def update_secret(
    id_or_name: str,
    payload: SecretPatch,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("secrets:write"))],
) -> dict:
    try:
        secret = secrets.update_secret(id_or_name, **payload.model_dump(exclude_unset=True))
    except Exception as exc:
        raise _secret_error(exc) from exc
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    record_event(
        request_id=get_request_id(request),
        event_type="secret.update",
        actor=principal.actor,
        target_type="secret",
        target_id=secret["name"],
        action="update",
        success=True,
        message=secret["name"],
    )
    return secret


@router.delete("/{id_or_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret(
    id_or_name: str,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("secrets:write"))],
) -> None:
    deleted = secrets.delete_secret(id_or_name)
    record_event(
        request_id=get_request_id(request),
        event_type="secret.delete",
        actor=principal.actor,
        target_type="secret",
        target_id=id_or_name,
        action="delete",
        success=deleted,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found")


@router.post("/{id_or_name}/reveal")
def reveal_secret(
    id_or_name: str,
    payload: SecretRevealRequest,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("secrets:reveal"))],
) -> dict:
    try:
        secret, value = secrets.reveal_secret(id_or_name)
    except Exception as exc:
        raise _secret_error(exc) from exc
    if secret is None or value is None:
        record_event(
            request_id=get_request_id(request),
            event_type="secret.reveal",
            actor=payload.requesting_agent or principal.actor,
            tool=payload.tool,
            target_type="secret",
            target_id=id_or_name,
            action="reveal",
            success=False,
            purpose=payload.purpose,
        )
        raise HTTPException(status_code=404, detail="Secret not found")
    record_event(
        request_id=get_request_id(request),
        event_type="secret.reveal",
        actor=payload.requesting_agent or principal.actor,
        tool=payload.tool,
        target_type="secret",
        target_id=secret["name"],
        action="reveal",
        success=True,
        purpose=payload.purpose,
    )
    return {"name": secret["name"], "value": value, "expires_in_seconds": 60}

