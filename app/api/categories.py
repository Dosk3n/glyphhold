from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.auth import ApiPrincipal, require_scope
from app.core.request_context import get_request_id
from app.storage.repositories import categories
from app.storage.repositories.events import record_event

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    allow_auto_prefetch: bool = True
    agent_can_create: bool = True
    agent_can_write: bool = True


class CategoryPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    allow_auto_prefetch: bool | None = None
    agent_can_create: bool | None = None
    agent_can_write: bool | None = None


@router.get("")
def list_categories(
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> list[dict]:
    return categories.list_categories()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    category = categories.create_category(**payload.model_dump())
    record_event(
        request_id=get_request_id(request),
        event_type="category.create",
        actor=principal.actor,
        target_type="category",
        target_id=category["id"],
        action="create",
        success=True,
        message=category["name"],
    )
    return category


@router.get("/{category_id}")
def get_category(
    category_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    category = categories.get_category(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.patch("/{category_id}")
def update_category(
    category_id: str,
    payload: CategoryPatch,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> dict:
    category = categories.update_category(category_id, **payload.model_dump(exclude_unset=True))
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    record_event(
        request_id=get_request_id(request),
        event_type="category.update",
        actor=principal.actor,
        target_type="category",
        target_id=category["id"],
        action="update",
        success=True,
        message=category["name"],
    )
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: str,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:write"))],
) -> None:
    category = categories.get_category(category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if not categories.delete_category(category_id):
        raise HTTPException(status_code=400, detail="Category could not be deleted")
    record_event(
        request_id=get_request_id(request),
        event_type="category.delete",
        actor=principal.actor,
        target_type="category",
        target_id=category_id,
        action="delete",
        success=True,
        message=category["name"],
    )
