from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdvancedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    space_ids: list[str] = Field(default_factory=list, max_length=100)
    frequency: Literal["hourly", "daily", "weekly"] = "daily"
    hour: int = Field(default=3, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    weekday: int = Field(default=0, ge=0, le=6)
    timezone: str = "Europe/London"
    model: str = Field(default="", max_length=100, pattern=r"^(?:[a-zA-Z0-9][a-zA-Z0-9._:/-]*)?$")
    reasoning: Literal["default", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] = (
        "low"
    )
    batch_size: int = Field(default=20, ge=1, le=100)
    max_context_chars: int = Field(default=60000, ge=4000, le=200000)
    timeout_seconds: int = Field(default=180, ge=30, le=900)
    execution_policy: Literal["review", "automatic"] = "review"
    guidance: list[dict] = Field(default_factory=list, max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a named IANA timezone") from exc
        return value

    @field_validator("guidance")
    @classmethod
    def bounded_guidance(cls, value: list[dict]) -> list[dict]:
        import json

        if len(json.dumps(value)) > 20000:
            raise ValueError("Placement guidance is too large")
        return value


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: int = Field(ge=1)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["profile", "summary", "update", "merge", "supersede", "move", "question"]
    target_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    space_id: str
    destination_space_id: str | None = None
    replacement_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=60000)
    summary: str | None = Field(default=None, max_length=8192)
    subject_ids: list[str] = Field(default_factory=list, max_length=100)
    source_refs: list[SourceRef] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    uncertainty: str | None = Field(default=None, max_length=2000)


class RunnerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[Proposal] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)
