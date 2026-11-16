"""Running a task and reading it back: requests, list/detail rows, events, revert."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.modes import DEFAULT_MODE
from commons.schemas.config import MAX_STEPS_LIMIT


class RunTaskRequest(BaseModel):
    """Create task request."""

    query: str = Field(min_length=1, description="User input")
    provider: str | None = None
    model_id: str | None = Field(default=None, description="Configured model id.")
    session_id: str | None = Field(default=None, description="Owning session id.")
    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=MAX_STEPS_LIMIT,
        description="Optional override; omit to use the global max-steps setting (default 9).",
    )
    agent_id: str | None = Field(
        default=None,
        description="Configured agent id; falls back to mode / the default agent when omitted.",
    )
    mode: str = Field(
        default=DEFAULT_MODE,
        description="Legacy agent mode (build / ask / plan); used when agent_id is omitted.",
    )
    permission_mode: str | None = Field(
        default=None,
        description=(
            "Optional override for tool confirmation (ask / auto_approve / deny_all); "
            "omit to use the global config."
        ),
    )
    stream: bool = Field(
        default=True,
        description=(
            "Read the model's answer as it is produced instead of waiting for the "
            "whole turn. On by default: it is what surfaces the reasoning trace on "
            "gateways that only send it incrementally."
        ),
    )


class RunTaskResponse(BaseModel):
    """Create task response."""

    task_id: str
    status: str
    mode: str
    created_at: datetime


class TaskListItemResponse(BaseModel):
    """Task list item."""

    task_id: str
    query: str
    # Short name shown in the task list; empty until the naming step has run.
    name: str = ""
    status: str
    provider: str
    session_id: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    mode: str = DEFAULT_MODE
    created_at: datetime
    updated_at: datetime
    event_count: int
    result: str | None = None
    # Present while the task is blocked on a confirmation, so a task waiting in
    # the background is visible without opening it.
    pending_permission: dict[str, Any] | None = None
    # Same idea for the question channel: a batch the model is waiting on.
    pending_question: dict[str, Any] | None = None


class TaskDetailResponse(BaseModel):
    """Task detail."""

    task_id: str
    query: str
    name: str = ""
    status: str
    provider: str
    session_id: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    mode: str = DEFAULT_MODE
    created_at: datetime
    updated_at: datetime
    # What the run cost, summed from the task's own ``llm_response`` events, and how
    # long it took. The result pane prints them next to the answer.
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    result: str | None = None
    # Set while the task is blocked on a confirmation, so a client that (re)connects
    # late can still render the dialog without replaying the whole event stream.
    pending_permission: dict[str, Any] | None = None
    # Same for a pending question batch: the dialog is rendered from this, not from
    # the event stream, so a late client still sees it.
    pending_question: dict[str, Any] | None = None
    events: list[dict[str, Any]]


class RevertTaskRequest(BaseModel):
    """Which files to undo, and whether to overwrite ones edited since (ADR 0020)."""

    # ``None`` means "everything this task changed"; an explicit list is a per-file undo.
    paths: list[str] | None = None
    force: bool = Field(
        default=False,
        description="Overwrite files whose content changed after the task wrote them.",
    )


class EventResponse(BaseModel):
    """Event response."""

    events: list[dict[str, Any]]


class EventPageResponse(BaseModel):
    """Paged event response."""

    items: list[dict[str, Any]]
    offset: int
    limit: int
    next_offset: int
    total: int
    has_more: bool


class TaskListResponse(BaseModel):
    """Task list response."""

    tasks: list[TaskListItemResponse]
