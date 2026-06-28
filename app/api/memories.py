from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.core.auth import ApiPrincipal, require_scope
from app.core.request_context import get_request_id
from app.storage.repositories import memories
from app.storage.repositories.events import record_event

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


class MemoryCreate(BaseModel):
    category_id: str
    title: str = Field(min_length=1)
    summary: str | None = None
    body: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    confidence: int = Field(default=3, ge=1, le=5)
    auto_prefetch_level: str = "normal"


class MemoryPatch(BaseModel):
    category_id: str | None = None
    title: str | None = None
    summary: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    source: str | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    auto_prefetch_level: str | None = None
    archived: bool | None = None
    superseded_by: str | None = None
    change_reason: str | None = None


class MemorySearch(BaseModel):
    query: str = ""
    category: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
    include_archived: bool = False
    mode: str = "explicit"


class FindSimilar(BaseModel):
    category: str | None = None
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)


class ConfidenceUpdate(BaseModel):
    confidence: int = Field(ge=1, le=5)
    change_reason: str | None = None


class SupersedeRequest(BaseModel):
    superseded_by: str


@router.get("")
def list_memories(
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
    category: str | None = None,
    tag: str | None = None,
    entity: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return memories.list_memories(
        category=category,
        tag=tag,
        entity=entity,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: MemoryCreate,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    try:
        memory = memories.create_memory(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_event(
        request_id=get_request_id(request),
        event_type="memory.create",
        actor=principal.actor,
        target_type="memory",
        target_id=memory["id"],
        action="create",
        success=True,
        message=memory["title"],
    )
    return memory


@router.get("/{memory_id}")
def get_memory(
    memory_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    memory = memories.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.patch("/{memory_id}")
def update_memory(
    memory_id: str,
    payload: MemoryPatch,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    change_reason = data.pop("change_reason", None)
    try:
        memory, revision_id = memories.update_memory(
            memory_id,
            changed_by=principal.actor,
            change_reason=change_reason,
            **data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.update",
        actor=principal.actor,
        target_type="memory",
        target_id=memory["id"],
        action="update",
        success=True,
        message=memory["title"],
        metadata={"revision_id": revision_id},
    )
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> None:
    if not memories.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/search")
def search_memories(
    payload: MemorySearch,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    results = memories.search_memories(
        query=payload.query,
        category=payload.category,
        include_archived=payload.include_archived,
        limit=payload.limit,
    )
    record_event(
        request_id=get_request_id(request),
        event_type="memory.search",
        actor=principal.actor,
        target_type="memory",
        action="search",
        success=True,
        query=payload.query,
        result_count=len(results),
        metadata={"category": payload.category, "mode": payload.mode},
    )
    return {"results": results}


@router.post("/find-similar")
def find_similar(
    payload: FindSimilar,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    matches = memories.find_similar(**payload.model_dump())
    record_event(
        request_id=get_request_id(request),
        event_type="memory.find_similar",
        actor=principal.actor,
        target_type="memory",
        action="find_similar",
        success=True,
        query=payload.title,
        result_count=len(matches),
    )
    return {"matches": matches}


@router.post("/prepare-write")
def prepare_write(
    payload: FindSimilar,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    matches = memories.find_similar(**payload.model_dump())
    record_event(
        request_id=get_request_id(request),
        event_type="memory.prepare_write",
        actor=principal.actor,
        target_type="memory",
        action="prepare_write",
        success=True,
        query=payload.title,
        result_count=len(matches),
    )
    return {"likely_duplicates": matches, "likely_conflicts": [], "matched_entities": []}


@router.post("/{memory_id}/confidence")
def update_confidence(
    memory_id: str,
    payload: ConfidenceUpdate,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    memory, revision_id = memories.update_memory(
        memory_id,
        confidence=payload.confidence,
        changed_by=principal.actor,
        change_reason=payload.change_reason or "confidence_update",
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.confidence_update",
        actor=principal.actor,
        target_type="memory",
        target_id=memory["id"],
        action="confidence_update",
        success=True,
        metadata={"revision_id": revision_id, "confidence": payload.confidence},
    )
    return memory


@router.post("/{memory_id}/archive")
def archive_memory(
    memory_id: str,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    memory, revision_id = memories.archive_memory(memory_id, changed_by=principal.actor)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.archive",
        actor=principal.actor,
        target_type="memory",
        target_id=memory["id"],
        action="archive",
        success=True,
        metadata={"revision_id": revision_id},
    )
    return memory


@router.post("/{memory_id}/supersede")
def supersede_memory(
    memory_id: str,
    payload: SupersedeRequest,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    memory, revision_id = memories.supersede_memory(
        memory_id,
        payload.superseded_by,
        changed_by=principal.actor,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    record_event(
        request_id=get_request_id(request),
        event_type="memory.supersede",
        actor=principal.actor,
        target_type="memory",
        target_id=memory["id"],
        action="supersede",
        success=True,
        metadata={"revision_id": revision_id, "superseded_by": payload.superseded_by},
    )
    return memory


@router.get("/{memory_id}/revisions")
def list_revisions(
    memory_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> list[dict]:
    if memories.get_memory(memory_id) is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memories.list_revisions(memory_id)

