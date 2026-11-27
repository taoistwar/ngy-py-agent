"""Cross-session memories: the notes an earlier conversation kept (ADR 0035).

The shape mirrors ``agent/tools/memory_notes.py``: a name (the slug a later save
replaces), a type, one index line, and the body. The bounds here are request validation;
the same rules are enforced again where the record is written, because the model reaches
that path through a tool rather than through HTTP.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from agent.tools.memory_notes import (
    DEFAULT_MAX_PROMPT_CHARS,
    MAX_BODY_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_NAME_CHARS,
    MAX_PROMPT_CHARS,
    MEMORY_TYPES,
)

# Spelled once so the four request models cannot drift from the store's vocabulary.
_TYPE_PATTERN = r"^(?:" + "|".join(MEMORY_TYPES) + r")$"


class MemoryCreateRequest(BaseModel):
    """Add a memory, or replace the one an existing name already holds."""

    name: str = Field(
        min_length=1,
        max_length=MAX_NAME_CHARS,
        description="Short identifier; saving the same name replaces what it held.",
    )
    type: str = Field(pattern=_TYPE_PATTERN, description="user / feedback / project / reference.")
    description: str = Field(
        default="", max_length=MAX_DESCRIPTION_CHARS, description="One line for the index."
    )
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS, description="The note itself.")


class MemoryUpdateRequest(BaseModel):
    """Partial edit of one memory; omitted fields are left alone."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_CHARS)
    type: str | None = Field(default=None, pattern=_TYPE_PATTERN)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_BODY_CHARS)


class MemoryItemResponse(BaseModel):
    """One stored memory."""

    memory_id: str
    name: str
    type: str
    description: str = ""
    body: str = ""
    source_task_id: str = ""
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    """The library plus the settings the page renders next to it."""

    memories: list[MemoryItemResponse]
    total: int = 0
    enabled: bool = True
    auto_extract: bool = True
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    # Where the switches came from: "default" until an admin saves them once.
    source: str = "default"


class MemoryConfigRequest(BaseModel):
    """The feature's three switches, written together."""

    enabled: bool = Field(default=True, description="Use the library at all.")
    auto_extract: bool = Field(
        default=True, description="Extract durable facts when a task finishes."
    )
    max_prompt_chars: int = Field(
        default=DEFAULT_MAX_PROMPT_CHARS,
        ge=0,
        le=MAX_PROMPT_CHARS,
        description="How much of the index may enter a system prompt.",
    )


class MemoryConfigResponse(MemoryConfigRequest):
    """The switches as they are now, and where they came from."""

    source: str = "default"
    total: int = 0
