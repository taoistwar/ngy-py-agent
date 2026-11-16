"""Sessions, forks and the composer's context meter."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """Create session request."""

    name: str | None = Field(
        default=None,
        max_length=120,
        description="Session name; auto-generated from the current time when omitted.",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Owning workspace id; empty means the session has no workspace.",
    )


class SessionUpdateRequest(BaseModel):
    """Rename session request."""

    name: str = Field(min_length=1, max_length=120, description="Session name.")


class SessionItemResponse(BaseModel):
    """Session list item."""

    session_id: str
    name: str
    workspace_id: str | None = None
    created_at: datetime
    updated_at: datetime
    task_count: int = 0
    query_preview: str = ""
    result_preview: str = ""


class SessionListResponse(BaseModel):
    """Session list response."""

    sessions: list[SessionItemResponse]


class ForkTaskResponse(BaseModel):
    """The session a fork created, and the task the branch starts from.

    ``task_id`` is the copy of the forked task (not the original), so a client can
    select it without a second lookup; ``copied_task_count`` says how many turns of
    the original conversation the branch carries as history.
    """

    session_id: str
    session: SessionItemResponse
    task_id: str
    source_session_id: str
    source_task_id: str
    copied_task_count: int
    event_count: int


class ContextUsageResponse(BaseModel):
    """How full the model's context window already is, for the composer's meter.

    ``used_tokens`` is the provider's own count for the session's newest answered
    turn; ``max_tokens`` is the selected model's input window, or the loop's own
    budget when the model declares none. ``limit_source`` says which one it was, so
    the number is never presented as a window it is not.
    """

    session_id: str
    model_id: str | None = None
    model_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    used_tokens: int = 0
    max_tokens: int = 0
    limit_source: str = "none"
    percent: float = 0.0
