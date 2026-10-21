"""Serializable state; no hidden reasoning or executable persisted objects."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Budget(BaseModel):
    max_iterations: int = Field(default=12, ge=1, le=100)
    max_tool_calls: int = Field(default=30, ge=1, le=200)
    max_tokens: int = Field(default=24000, ge=100, le=1000000)
    timeout_seconds: float = Field(default=90, gt=0, le=1800)
    model_timeout: float = Field(default=20, gt=0, le=120)
    tool_timeout: float = Field(default=3, gt=0, le=30)


class Step(BaseModel):
    description: str
    status: Literal["pending", "completed"] = "pending"


class ToolEvent(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] | str
    result: dict[str, Any] | None = None
    started_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None


class TaskState(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    goal: str = Field(min_length=1, max_length=4000)
    workspace: str = Field(min_length=1, max_length=4096)
    status: Literal[
        "running", "completed", "preview", "failed", "budget_exceeded", "interrupted"
    ] = "running"
    plan: list[Step] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    plan_revisions: list[str] = Field(default_factory=list)
    tool_history: list[ToolEvent] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    final_result: str = ""
    budget: Budget = Field(default_factory=Budget)
    iterations: int = 0
    tokens_used: int = 0
    token_charges: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_seconds: float = 0
    started_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
