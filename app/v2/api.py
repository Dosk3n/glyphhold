from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.core.auth import bearer_scheme, get_api_principal, get_current_dashboard_user
from app.v2 import core

router = APIRouter(prefix="/api/v2", tags=["glyphhold-v2"])


def principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> core.Principal:
    if credentials is not None:
        p = get_api_principal(request, credentials)
        # API-level admin scope never implicitly grants every ownership space.
        return core.Principal(p.key_id, p.actor, p.scopes)
    if request.headers.get("authorization"):
        get_api_principal(request, None)
    user = get_current_dashboard_user(request)
    if user and user.get("is_admin"):
        return core.Principal("dashboard", str(user["username"]), {"admin"}, True)
    get_api_principal(request, None)
    raise HTTPException(401, "Sign in or supply a bearer API key")


P = Annotated[core.Principal, Depends(principal)]


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except core.SpaceError as e:
        raise HTTPException(e.status, e.detail) from e
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.IntegrityError) as e:
        raise HTTPException(400, "Invalid request data or conflicting reference") from e


@router.get("/capabilities")
def capabilities(p: P):
    return {
        "version": 2,
        "spaces": core.list_spaces(p),
        "default_space_id": core.default_space(p),
        "features": [
            "scoped-recall",
            "atomic-revisions",
            "idempotent-create",
            "subjects",
            "guidance",
            "migration",
        ],
        "legacy_policy": "v1 data routes disabled by default; existing records require ownership review",
    }


@router.get("/spaces")
def spaces(p: P):
    return {"spaces": core.list_spaces(p)}


@router.post("/spaces", status_code=201)
def create_space(payload: dict, p: P):
    return invoke(core.create_space, p, payload.get("name", ""), payload.get("description", ""))


@router.patch("/spaces/{space_id}")
def update_space(space_id: str, payload: dict, p: P):
    return invoke(core.update_space, p, space_id, payload)


@router.get("/connections/{key_id}")
def get_connection(key_id: str, p: P):
    return invoke(core.get_connection, p, key_id)


@router.put("/connections/{key_id}")
def connection(key_id: str, payload: dict, p: P):
    return invoke(core.set_connection, p, key_id, payload)


class Search(BaseModel):
    query: str = Field(default="", max_length=8192)
    space_id: str | None = None
    broaden: bool = False
    limit: int = Field(default=10, ge=1, le=100)
    max_chars: int = Field(default=12000, ge=256, le=100000)
    subject_ids: list[str] = Field(default_factory=list, max_length=100)
    session_id: str | None = Field(default=None, max_length=200)


@router.post("/search")
def search(payload: Search, p: P):
    return invoke(core.search, p, **payload.model_dump())


@router.post("/recall")
def recall(payload: Search, p: P):
    return invoke(core.search, p, recall=True, **payload.model_dump())


@router.get("/memories")
def memories(
    p: P,
    space_id: str | None = None,
    include_archived: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return {"memories": invoke(core.list_memories, p, space_id, include_archived, limit, offset)}


@router.post("/memories", status_code=201)
def create_memory(payload: dict, p: P, idempotency_key: Annotated[str | None, Header()] = None):
    data = dict(payload)
    key = idempotency_key or data.pop("idempotency_key", None)
    return invoke(core.create_memory, p, data, key)


@router.get("/memories/{memory_id}")
def memory(memory_id: str, p: P):
    return invoke(core.get_memory, p, memory_id)


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: str, payload: dict, p: P):
    data = dict(payload)
    version = data.pop("expected_version", None)
    reason = data.pop("change_reason", None)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise HTTPException(422, "expected_version is required")
    return invoke(core.update_memory, p, memory_id, data, version, reason)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, p: P, expected_version: int = Query(..., ge=1)):
    return invoke(
        core.update_memory,
        p,
        memory_id,
        {"archived": True, "auto_prefetch_level": "never"},
        expected_version,
        "User removed record; preserved recoverable history",
    )


@router.post("/memories/{memory_id}/archive")
def archive(memory_id: str, payload: dict, p: P):
    if not isinstance(payload.get("expected_version"), int):
        raise HTTPException(422, "expected_version is required")
    return invoke(
        core.update_memory, p, memory_id, {"archived": True}, payload["expected_version"], "Archive"
    )


@router.post("/memories/{memory_id}/move")
def move(memory_id: str, payload: dict, p: P):
    if not isinstance(payload.get("expected_version"), int) or not payload.get("space_id"):
        raise HTTPException(422, "expected_version and space_id are required")
    fields = {"space_id": payload["space_id"]}
    if "subject_ids" in payload:
        fields["subject_ids"] = payload["subject_ids"]
    return invoke(
        core.update_memory,
        p,
        memory_id,
        fields,
        payload["expected_version"],
        "Explicit owner-approved move",
    )


@router.get("/memories/{memory_id}/revisions")
def revisions(memory_id: str, p: P):
    return {"revisions": invoke(core.revisions, p, memory_id)}


@router.post("/memories/{memory_id}/restore")
def restore(memory_id: str, payload: dict, p: P):
    if not isinstance(payload.get("expected_version"), int) or not payload.get("revision_id"):
        raise HTTPException(422, "expected_version and revision_id are required")
    return invoke(core.restore, p, memory_id, payload["revision_id"], payload["expected_version"])


@router.get("/subjects")
def subjects(p: P, space_id: str | None = None):
    return {"subjects": invoke(core.subjects, p, space_id)}


@router.post("/subjects", status_code=201)
def subject(payload: dict, p: P):
    return invoke(core.create_subject, p, payload)


@router.get("/guidance")
def guidance(p: P, space_id: str | None = None):
    return {"guidance": invoke(core.guidance, p, space_id)}


@router.post("/guidance", status_code=201)
def add_guidance(payload: dict, p: P):
    return invoke(core.create_guidance, p, payload)


@router.delete("/guidance/{guidance_id}")
def delete_guidance(guidance_id: str, p: P):
    invoke(core.delete_guidance, p, guidance_id)
    return {"deleted": True}


@router.get("/migration/export")
def export(p: P):
    return invoke(core.export_memories, p)


@router.post("/migration/preview")
def preview(payload: dict, p: P):
    return invoke(core.import_preview, p, payload)


@router.post("/migration/apply")
def apply(payload: dict, p: P):
    return invoke(core.import_apply, p, payload)


@router.get("/context")
def context(p: P, session_id: str):
    return invoke(core.get_context, p, session_id)


@router.put("/context")
def set_context(payload: dict, p: P):
    return invoke(core.set_context, p, payload.get("session_id"), payload.get("space_id"))
