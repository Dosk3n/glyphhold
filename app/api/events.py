from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import ApiPrincipal, require_scope
from app.storage.repositories import events

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("")
def list_events(
    _: Annotated[ApiPrincipal, Depends(require_scope("events:read"))],
    actor: str | None = None,
    event_type: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    success: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return events.list_events(
        actor=actor,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        success=success,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}")
def get_event(
    event_id: str,
    _: Annotated[ApiPrincipal, Depends(require_scope("events:read"))],
) -> dict:
    event = events.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

