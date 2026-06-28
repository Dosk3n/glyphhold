from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.auth import ApiPrincipal, require_scope
from app.core.request_context import get_request_id
from app.storage.repositories import entities
from app.storage.repositories.events import record_event

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])


class EntityCreate(BaseModel):
    name: str = Field(min_length=1)
    type: str | None = None
    aliases: list[str] = Field(default_factory=list)


class EntityPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    aliases: list[str] | None = None


@router.get("")
def list_entities(
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> list[dict]:
    return entities.list_entities()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_entity(
    payload: EntityCreate,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    entity = entities.create_entity(**payload.model_dump())
    record_event(
        request_id=get_request_id(request),
        event_type="entity.create",
        actor=principal.actor,
        target_type="entity",
        target_id=entity["id"],
        action="create",
        success=True,
        message=entity["name"],
    )
    return entity


@router.get("/{entity_id}")
def get_entity(
    entity_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    entity = entities.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.patch("/{entity_id}")
def update_entity(
    entity_id: str,
    payload: EntityPatch,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    entity = entities.update_entity(entity_id, **payload.model_dump(exclude_unset=True))
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    record_event(
        request_id=get_request_id(request),
        event_type="entity.update",
        actor=principal.actor,
        target_type="entity",
        target_id=entity["id"],
        action="update",
        success=True,
        message=entity["name"],
    )
    return entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(
    entity_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> None:
    if not entities.delete_entity(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")

