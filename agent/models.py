"""Monitor data models for agent task events."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List
from uuid import uuid4

from pydantic import BaseModel, Field


class EventCategory(str, Enum):
    """Event category."""

    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DEBUG = "debug"
    ERROR = "error"


class TaskStatus(str, Enum):
    """Task status."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TaskEvent(BaseModel):
    """Single debug event."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: EventCategory
    title: str
    source: str = "agent"
    data: Dict[str, Any] = Field(default_factory=dict)
    collapsed: bool = True


class LLMRequestData(BaseModel):
    """LLM request payload."""

    step: int
    model: str | None = None
    provider: str | None = None
    tool_count: int = 0
    message_count: int = 0
    tool_choice: str = "auto"


class LLMResponseData(BaseModel):
    """LLM response payload."""

    step: int
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    tool_call_count: int = 0
    content: str | None = None


class ToolCallData(BaseModel):
    """Tool call payload."""

    step: int
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None


class ToolResultData(BaseModel):
    """Tool result payload."""

    step: int
    name: str
    tool_call_id: str | None = None
    result: str
    is_error: bool = False


class AgentTaskTrace(BaseModel):
    """Single task trace."""

    task_id: str
    status: TaskStatus = TaskStatus.RUNNING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    query: str
    provider: str = "openai"
    events: List[TaskEvent] = Field(default_factory=list)


class TaskListItem(BaseModel):
    """Task list item."""

    task_id: str
    query: str
    status: TaskStatus
    provider: str = "openai"
    created_at: datetime
    updated_at: datetime
    event_count: int = 0


class BuildEvent(BaseModel):
    """Reusable event payload used for manual event construction."""

    task_id: str
    category: EventCategory
    title: str
    source: str = "agent"
    payload: Dict[str, Any] = Field(default_factory=dict)
    collapsed: bool = True

    def to_event(self) -> TaskEvent:
        return TaskEvent(
            task_id=self.task_id,
            category=self.category,
            title=self.title,
            source=self.source,
            data=self.payload,
            collapsed=self.collapsed,
        )


EventSink = Callable[[str, TaskEvent], None]
