from __future__ import annotations

from typing import Annotated
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.advanced import service, store
from app.advanced.codex import CodexError
from app.advanced.models import AdvancedSettings
from app.advanced.worker import worker
from app.core.auth import require_dashboard_user
from app.v2 import core

router = APIRouter(
    prefix="/dashboard/api/advanced",
    tags=["advanced-memory"],
    dependencies=[Depends(require_dashboard_user)],
)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_review: bool = False


def failure(exc: Exception):
    raise HTTPException(status_code=getattr(exc, "status", 409), detail=str(exc)) from exc


@router.get("/settings")
def get_settings():
    return store.settings()


@router.put("/settings")
async def update_settings(config: AdvancedSettings):
    if config.enabled:
        if not config.space_ids:
            raise HTTPException(400, "Choose at least one permitted space")
        if not (await worker.runner.authentication())["authenticated"]:
            raise HTTPException(
                409, "Sign in to Codex with ChatGPT before enabling Advanced Memory"
            )
    if config.model and config.reasoning != "default":
        known = next((item for item in worker.runner.models() if item["id"] == config.model), None)
        if (
            known
            and known.get("reasoning_levels")
            and config.reasoning not in known["reasoning_levels"]
        ):
            raise HTTPException(
                400,
                "Selected reasoning level is not supported by this model; choose one from its available levels",
            )
    try:
        for space_id in config.space_ids:
            core.require_space(core.ADMIN, space_id, write=True)
        return store.save_settings(config)
    except (ValueError, core.SpaceError) as exc:
        failure(exc)


@router.get("/status")
async def get_status():
    config = store.settings()
    auth = await worker.runner.authentication()
    if auth["authenticated"]:
        await worker.runner.refresh_models()
    return auth | {
        "login": dict(worker.runner.login),
        "models": worker.runner.models(),
        "reasoning_levels": [
            "default",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ],
        "worker_running": bool(worker.task and not worker.task.done()),
        "next_run": config["next_run"],
        "paused_reason": config["paused_reason"],
        "model_catalog_note": "Models come from the signed-in Codex catalog when available. You may enter a model ID; account availability and supported reasoning vary. Default uses Codex's configured account default.",
    }


@router.get("/timezones")
def timezones():
    return sorted(available_timezones())


@router.post("/auth/login")
async def login():
    try:
        return await worker.runner.begin_login()
    except CodexError as exc:
        failure(exc)


@router.post("/auth/cancel")
async def cancel_login():
    await worker.runner.cancel_login()
    return dict(worker.runner.login)


@router.post("/auth/logout")
async def logout():
    config = AdvancedSettings.model_validate(
        {
            key: value
            for key, value in store.settings().items()
            if key in AdvancedSettings.model_fields
        }
    )
    config.enabled = False
    store.save_settings(config)
    await worker.runner.logout()
    return {"authenticated": False}


@router.post("/jobs", status_code=202)
def enqueue(payload: RunRequest):
    try:
        return store.enqueue(payload.full_review)
    except ValueError as exc:
        failure(exc)


@router.get("/jobs")
def jobs(limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return store.list_jobs(limit)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    found = store.get_job(job_id)
    if not found:
        raise HTTPException(404, "Run not found")
    return found | {"proposals": store.list_proposals(job_id)}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    try:
        return store.cancellation(job_id)
    except ValueError as exc:
        failure(exc)


@router.post("/jobs/{job_id}/resume", status_code=202)
def resume(job_id: str):
    try:
        return store.resume(job_id)
    except ValueError as exc:
        failure(exc)


@router.get("/proposals")
def proposals(job_id: str | None = None):
    return store.list_proposals(job_id)


@router.get("/proposals/pending-count")
def pending_approval_count():
    return {"count": store.pending_approval_count()}


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str):
    try:
        return service.decide(proposal_id, True)
    except (ValueError, core.SpaceError) as exc:
        failure(exc)


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str):
    try:
        return service.decide(proposal_id, False)
    except (ValueError, core.SpaceError) as exc:
        failure(exc)
