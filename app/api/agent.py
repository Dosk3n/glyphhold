from __future__ import annotations

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.auth import ApiPrincipal, require_scope
from app.core.request_context import get_request_id
from app.storage.repositories import memories
from app.storage.repositories.events import record_event

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class PrefetchRequest(BaseModel):
    agent: str | None = None
    message: str
    max_memories: int = Field(default=3, ge=1, le=10)
    max_chars: int = Field(default=1200, ge=100, le=8000)
    max_tokens: int = Field(default=300, ge=25, le=2000)
    summaries_only: bool = True


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _prefetch_score(memory: dict, message_terms: set[str]) -> int:
    if memory["auto_prefetch_level"] == "never" or memory["archived"]:
        return -999

    score = 0
    title_terms = set(re.findall(r"[A-Za-z0-9_]+", memory["title"].lower()))
    tag_terms = set(json.loads(memory["tags_json"] or "[]"))
    tag_terms = {tag.lower() for tag in tag_terms}

    if memory["title"].lower() in " ".join(message_terms):
        score += 50
    score += 20 * len(message_terms & title_terms)
    score += 25 * len(message_terms & tag_terms)
    if memory["confidence"] >= 4:
        score += 5
    if memory["confidence"] <= 2:
        score -= 5
    if memory["auto_prefetch_level"] == "high":
        score += 10
    if memory["auto_prefetch_level"] == "pinned":
        score += 15
    if memory["auto_prefetch_level"] == "low":
        score -= 10
    return score


@router.post("/prefetch")
def prefetch(
    payload: PrefetchRequest,
    request: Request,
    principal: Annotated[ApiPrincipal, Depends(require_scope("memories:read"))],
) -> dict:
    results = memories.search_memories(query=payload.message, limit=20)
    message_terms = set(re.findall(r"[A-Za-z0-9_]+", payload.message.lower()))
    ranked = []
    for memory in results:
        score = _prefetch_score(memory, message_terms)
        if score >= 25:
            ranked.append((score, memory))
    ranked.sort(key=lambda item: item[0], reverse=True)

    selected = []
    used_chars = 0
    for score, memory in ranked:
        if len(selected) >= payload.max_memories:
            break
        summary = memory["summary"] or memory["body"][:300]
        item_chars = len(summary) + len(memory["title"])
        if used_chars + item_chars > payload.max_chars:
            continue
        selected.append(
            {
                "id": memory["id"],
                "category": memory["category_name"],
                "title": memory["title"],
                "summary": summary,
                "score": score,
            }
        )
        used_chars += item_chars

    estimated_tokens = _estimate_tokens("\n".join(item["summary"] for item in selected))
    if estimated_tokens > payload.max_tokens:
        selected = []
        estimated_tokens = 0

    record_event(
        request_id=get_request_id(request),
        event_type="agent.prefetch",
        actor=payload.agent or principal.actor,
        target_type="memory",
        action="prefetch",
        success=True,
        query=payload.message,
        result_count=len(selected),
        estimated_tokens=estimated_tokens,
        metadata={
            "candidate_count": len(results),
            "should_inject": bool(selected),
            "memory_ids": [item["id"] for item in selected],
        },
    )
    return {
        "should_inject": bool(selected),
        "estimated_tokens": estimated_tokens,
        "memories": selected,
    }

