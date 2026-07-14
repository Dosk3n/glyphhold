from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from app.api.validation import (
    validate_memory_body,
    validate_secret_value,
    validate_summary,
    validate_tags,
)
from app.config import settings
from app.core import auth
from app.core.encryption import SecretDecryptionError, SecretStorageDisabled
from app.core.request_context import get_request_id
from app.core.security import client_address
from app.storage.db import database_ok
from app.storage.migrations import current_schema_version
from app.storage.repositories import auth as auth_repo
from app.storage.repositories import categories, memories
from app.storage.repositories import events as events_repo
from app.storage.repositories import secrets as secrets_repo
from app.storage.repositories.events import record_event
from app.storage.repositories.secrets import VALUE_TYPES

router = APIRouter(prefix="/dashboard/api", tags=["dashboard"])

DEFAULT_SCOPES = [
    "memories:read",
    "memories:write",
    "secrets:write",
    "secrets:reveal",
    "events:read",
]


class SetupRequest(BaseModel):
    username: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ApiKeyCreateRequest(BaseModel):
    name: str
    actor: str
    description: str | None = None
    scopes: list[str] = Field(default_factory=list)


class ConfirmNameRequest(BaseModel):
    confirm_name: str = ""


class MemoryCreateRequest(BaseModel):
    category_id: str
    title: str
    summary: str | None = None
    body: str
    tags: list[str] = Field(default_factory=list)
    confidence: int = Field(default=3, ge=1, le=5)
    auto_prefetch_level: str = "normal"

    _body_limit = field_validator("body")(validate_memory_body)
    _summary_limit = field_validator("summary")(validate_summary)
    _tag_limits = field_validator("tags")(validate_tags)


class MemoryUpdateRequest(MemoryCreateRequest):
    pass


class ConfirmTitleRequest(BaseModel):
    confirm_title: str = ""


class SecretCreateRequest(BaseModel):
    name: str
    value: str
    description: str | None = None
    value_type: str = "text"
    service: str | None = None
    host: str | None = None
    scope: str | None = None
    tags: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)

    _value_limit = field_validator("value")(validate_secret_value)
    _tag_limits = field_validator("tags")(validate_tags)


class SecretUpdateRequest(BaseModel):
    name: str
    value: str | None = None
    description: str | None = None
    value_type: str = "text"
    service: str | None = None
    host: str | None = None
    scope: str | None = None
    tags: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)

    _value_limit = field_validator("value")(validate_secret_value)
    _tag_limits = field_validator("tags")(validate_tags)


def _dashboard_user(request: Request) -> dict:
    user = auth.get_current_dashboard_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


def _tags_text(tags_json: str | None) -> str:
    try:
        tags = json.loads(tags_json or "[]")
    except json.JSONDecodeError:
        return ""
    if not isinstance(tags, list):
        return ""
    return ", ".join(str(tag) for tag in tags)


def _parse_json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _api_key_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["scopes"] = _parse_json_list(item.get("scopes_json"))
    return item


def _memory_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["tags"] = _parse_json_list(item.get("tags_json"))
    item["tags_text"] = ", ".join(item["tags"])
    return item


def _secret_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["tags"] = _parse_json_list(item.get("tags_json"))
    item["tags_text"] = ", ".join(item["tags"])
    item["allowed_agents"] = _parse_json_list(item.get("allowed_agents_json"))
    item["allowed_agents_text"] = ", ".join(item["allowed_agents"])
    item["allowed_tools"] = _parse_json_list(item.get("allowed_tools_json"))
    item["allowed_tools_text"] = ", ".join(item["allowed_tools"])
    return item


def _dashboard_secret_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SecretStorageDisabled):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, SecretDecryptionError):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Secret operation failed")


@router.get("/session")
def session(request: Request, response: Response) -> dict:
    user = auth.get_current_dashboard_user(request)
    response.set_cookie(
        settings.csrf_cookie_name,
        auth.create_csrf_value(),
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=60 * 60 * 24 * 14,
    )
    return {
        "has_admin": auth_repo.has_admin_user(),
        "user": {"id": user["id"], "username": user["username"]} if user else None,
    }


@router.post("/setup")
def setup(payload: SetupRequest, response: Response) -> dict:
    if auth_repo.has_admin_user():
        raise HTTPException(status_code=409, detail="Dashboard user already exists")

    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required.")
    if len(payload.password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    user_id = auth_repo.create_dashboard_user(username, auth.hash_password(payload.password))
    response.set_cookie(
        settings.session_cookie_name,
        auth.create_session_value(user_id),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return {"ok": True, "user": {"id": user_id, "username": username}}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    if not auth_repo.has_admin_user():
        raise HTTPException(status_code=404, detail="Dashboard setup is required")

    username = payload.username.strip()
    limiter = request.app.state.failure_rate_limiter
    limiter_key = f"dashboard-login:{client_address(request)}:{username.casefold()}"
    retry_after = limiter.retry_after(
        limiter_key,
        limit=settings.dashboard_login_attempts,
        window_seconds=settings.dashboard_login_window_seconds,
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Wait and retry.",
            headers={"Retry-After": str(retry_after)},
        )

    user = auth_repo.get_dashboard_user_by_username(username)
    if user is None or not auth.verify_password(payload.password, user["password_hash"]):
        limiter.add_failure(
            limiter_key, window_seconds=settings.dashboard_login_window_seconds
        )
        record_event(
            request_id=get_request_id(request),
            event_type="dashboard.login_failed",
            actor=username or None,
            action="login",
            success=False,
            message="Invalid username or password",
        )
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    limiter.clear(limiter_key)
    auth_repo.mark_dashboard_login(user["id"])
    response.set_cookie(
        settings.session_cookie_name,
        auth.create_session_value(user["id"], int(user.get("session_version", 1))),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return {"ok": True, "user": {"id": user["id"], "username": user["username"]}}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.session_cookie_name)
    return {"ok": True}


@router.get("/overview")
def overview(request: Request) -> dict:
    _dashboard_user(request)
    return {
        "database_status": "ok" if database_ok() else "error",
        "schema_version": current_schema_version(),
        "version": settings.version,
        "secrets_enabled": settings.secrets_enabled,
        "api_key_count": len(auth_repo.list_api_keys()),
        "memory_count": len(memories.list_memories(limit=500)),
        "secret_count": len(secrets_repo.list_secrets(limit=500)),
        "recent_events": events_repo.list_events(limit=8),
    }


@router.get("/categories")
def list_categories(request: Request) -> list[dict]:
    _dashboard_user(request)
    return categories.list_categories()


@router.post("/categories")
def create_category(request: Request, payload: dict[str, Any]) -> dict:
    user = _dashboard_user(request)
    category = categories.create_category(
        name=str(payload.get("name", "")).strip(),
        description=(str(payload.get("description", "")).strip() or None),
        allow_auto_prefetch=bool(payload.get("allow_auto_prefetch", True)),
        agent_can_create=bool(payload.get("agent_can_create", True)),
        agent_can_write=bool(payload.get("agent_can_write", True)),
    )
    record_event(
        request_id=get_request_id(request),
        event_type="category.create",
        actor=user["username"],
        target_type="category",
        target_id=category["id"],
        action="create",
        success=True,
        message=category["name"],
    )
    return category


@router.get("/api-keys")
def list_api_keys(request: Request) -> dict:
    _dashboard_user(request)
    return {
        "default_scopes": DEFAULT_SCOPES,
        "keys": [_api_key_row(row) for row in auth_repo.list_api_keys()],
    }


@router.post("/api-keys")
def create_api_key(request: Request, payload: ApiKeyCreateRequest) -> dict:
    _dashboard_user(request)
    name = payload.name.strip()
    actor = payload.actor.strip()
    if not name or not actor:
        raise HTTPException(status_code=400, detail="Name and actor are required.")
    selected_scopes = payload.scopes or DEFAULT_SCOPES
    key_id, api_key = auth.create_api_key(
        name=name,
        actor=actor,
        description=(payload.description or "").strip() or None,
        scopes=selected_scopes,
    )
    return {"id": key_id, "value": api_key}


@router.post("/api-keys/{key_id}/disable")
def disable_api_key(request: Request, key_id: str, payload: ConfirmNameRequest) -> dict:
    user = _dashboard_user(request)
    key = auth_repo.get_api_key_metadata(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if payload.confirm_name.strip() != key["name"]:
        raise HTTPException(status_code=400, detail=f'Type "{key["name"]}" to disable that API key.')
    auth_repo.set_api_key_enabled(key_id, False)
    record_event(
        request_id=get_request_id(request),
        event_type="api_key.disable",
        actor=user["username"],
        target_type="api_key",
        target_id=key_id,
        action="disable",
        success=True,
        message=key["name"],
    )
    return {"ok": True}


@router.post("/api-keys/{key_id}/enable")
def enable_api_key(request: Request, key_id: str) -> dict:
    user = _dashboard_user(request)
    key = auth_repo.get_api_key_metadata(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    auth_repo.set_api_key_enabled(key_id, True)
    record_event(
        request_id=get_request_id(request),
        event_type="api_key.enable",
        actor=user["username"],
        target_type="api_key",
        target_id=key_id,
        action="enable",
        success=True,
        message=key["name"],
    )
    return {"ok": True}


@router.get("/memories")
def list_memories(
    request: Request,
    q: str = "",
    category: str | None = None,
    include_archived: bool = False,
) -> dict:
    _dashboard_user(request)
    if q.strip():
        rows = memories.search_memories(
            query=q,
            category=category or None,
            include_archived=include_archived,
            limit=100,
        )
    else:
        rows = memories.list_memories(
            category=category or None,
            include_archived=include_archived,
            limit=250,
        )
    return {"memories": [_memory_row(row) for row in rows]}


@router.post("/memories", status_code=status.HTTP_201_CREATED)
def create_memory(request: Request, payload: MemoryCreateRequest) -> dict:
    _dashboard_user(request)
    memory = memories.create_memory(
        category_id=payload.category_id,
        title=payload.title.strip(),
        summary=(payload.summary or "").strip() or None,
        body=payload.body.strip(),
        tags=payload.tags,
        source="dashboard",
        confidence=payload.confidence,
        auto_prefetch_level=payload.auto_prefetch_level,
    )
    return _memory_row(memory)


@router.get("/memories/{memory_id}")
def get_memory(request: Request, memory_id: str) -> dict:
    _dashboard_user(request)
    memory = memories.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {
        "memory": _memory_row(memory),
        "revisions": [_memory_row(row) for row in memories.list_revisions(memory_id)],
    }


@router.patch("/memories/{memory_id}")
def update_memory(request: Request, memory_id: str, payload: MemoryUpdateRequest) -> dict:
    user = _dashboard_user(request)
    memory, revision_id = memories.update_memory(
        memory_id,
        category_id=payload.category_id,
        title=payload.title.strip(),
        summary=(payload.summary or "").strip() or None,
        body=payload.body.strip(),
        tags=payload.tags,
        confidence=payload.confidence,
        auto_prefetch_level=payload.auto_prefetch_level,
        changed_by=user["username"],
        change_reason="dashboard edit",
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.update",
        actor=user["username"],
        target_type="memory",
        target_id=memory["id"],
        action="update",
        success=True,
        message=memory["title"],
        metadata={"revision_id": revision_id},
    )
    return _memory_row(memory)


@router.post("/memories/{memory_id}/archive")
def archive_memory(request: Request, memory_id: str) -> dict:
    user = _dashboard_user(request)
    memory, revision_id = memories.archive_memory(memory_id, changed_by=user["username"])
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.archive",
        actor=user["username"],
        target_type="memory",
        target_id=memory["id"],
        action="archive",
        success=True,
        metadata={"revision_id": revision_id},
    )
    return _memory_row(memory)


@router.delete("/memories/{memory_id}")
def delete_memory(request: Request, memory_id: str, payload: ConfirmTitleRequest) -> dict:
    user = _dashboard_user(request)
    memory = memories.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if payload.confirm_title.strip() != memory["title"]:
        raise HTTPException(status_code=400, detail=f'Type "{memory["title"]}" to delete this memory.')
    deleted = memories.delete_memory(memory_id)
    record_event(
        request_id=get_request_id(request),
        event_type="memory.delete",
        actor=user["username"],
        target_type="memory",
        target_id=memory_id,
        action="delete",
        success=deleted,
    )
    return {"ok": True}


@router.post("/memories/{memory_id}/revisions/{revision_id}/restore")
def restore_memory_revision(request: Request, memory_id: str, revision_id: str) -> dict:
    user = _dashboard_user(request)
    memory, restore_revision_id = memories.restore_revision(
        memory_id,
        revision_id,
        changed_by=user["username"],
        change_reason="dashboard restore",
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory or revision not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.restore",
        actor=user["username"],
        target_type="memory",
        target_id=memory_id,
        action="restore",
        success=True,
        metadata={"revision_id": revision_id, "restore_revision_id": restore_revision_id},
    )
    return _memory_row(memory)


@router.get("/secrets")
def list_secrets(
    request: Request,
    query: str | None = None,
    service: str | None = None,
    host: str | None = None,
    scope: str | None = None,
) -> dict:
    _dashboard_user(request)
    rows = secrets_repo.list_secrets(query=query, service=service, host=host, scope=scope)
    return {
        "secrets_enabled": settings.secrets_enabled,
        "value_types": list(VALUE_TYPES),
        "secrets": [_secret_row(row) for row in rows],
    }


@router.post("/secrets", status_code=status.HTTP_201_CREATED)
def create_secret(request: Request, payload: SecretCreateRequest) -> dict:
    user = _dashboard_user(request)
    try:
        secret = secrets_repo.create_secret(
            name=payload.name.strip(),
            value=payload.value,
            description=(payload.description or "").strip() or None,
            value_type=payload.value_type,
            service=(payload.service or "").strip() or None,
            host=(payload.host or "").strip() or None,
            scope=(payload.scope or "").strip() or None,
            tags=payload.tags,
            allowed_agents=payload.allowed_agents,
            allowed_tools=payload.allowed_tools,
        )
    except Exception as exc:
        raise _dashboard_secret_error(exc) from exc
    record_event(
        request_id=get_request_id(request),
        event_type="secret.create",
        actor=user["username"],
        target_type="secret",
        target_id=secret["name"],
        action="create",
        success=True,
        message=secret["name"],
    )
    return _secret_row(secret)


@router.patch("/secrets/{id_or_name}")
def update_secret(request: Request, id_or_name: str, payload: SecretUpdateRequest) -> dict:
    user = _dashboard_user(request)
    fields: dict[str, Any] = {
        "name": payload.name.strip(),
        "description": (payload.description or "").strip() or None,
        "value_type": payload.value_type,
        "service": (payload.service or "").strip() or None,
        "host": (payload.host or "").strip() or None,
        "scope": (payload.scope or "").strip() or None,
        "tags": payload.tags,
        "allowed_agents": payload.allowed_agents,
        "allowed_tools": payload.allowed_tools,
    }
    if payload.value:
        fields["value"] = payload.value
    try:
        secret = secrets_repo.update_secret(id_or_name, **fields)
    except Exception as exc:
        raise _dashboard_secret_error(exc) from exc
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    record_event(
        request_id=get_request_id(request),
        event_type="secret.update",
        actor=user["username"],
        target_type="secret",
        target_id=secret["name"],
        action="update",
        success=True,
        message=secret["name"],
    )
    return _secret_row(secret)


@router.delete("/secrets/{id_or_name}")
def delete_secret(request: Request, id_or_name: str, payload: ConfirmNameRequest) -> dict:
    user = _dashboard_user(request)
    secret = secrets_repo.get_secret_metadata(id_or_name)
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    if payload.confirm_name.strip() != secret["name"]:
        raise HTTPException(status_code=400, detail=f'Type "{secret["name"]}" to delete this secret.')
    deleted = secrets_repo.delete_secret(id_or_name)
    record_event(
        request_id=get_request_id(request),
        event_type="secret.delete",
        actor=user["username"],
        target_type="secret",
        target_id=id_or_name,
        action="delete",
        success=deleted,
    )
    return {"ok": True}


@router.post("/secrets/{id_or_name}/reveal")
def reveal_secret(request: Request, id_or_name: str) -> dict:
    user = _dashboard_user(request)
    try:
        secret, value = secrets_repo.reveal_secret(id_or_name, bypass_restrictions=True)
    except Exception as exc:
        raise _dashboard_secret_error(exc) from exc
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    record_event(
        request_id=get_request_id(request),
        event_type="secret.reveal",
        actor=user["username"],
        target_type="secret",
        target_id=secret["name"],
        action="reveal",
        success=True,
        purpose="dashboard reveal",
    )
    return {"name": secret["name"], "value": value}


@router.get("/activity")
def activity(
    request: Request,
    actor: str | None = None,
    event_type: str | None = None,
) -> dict:
    _dashboard_user(request)
    return {"events": events_repo.list_events(actor=actor, event_type=event_type, limit=150)}
