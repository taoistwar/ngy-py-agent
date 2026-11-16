"""Tool management: the registered list, one tool test, and skill imports."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolTextResponse(BaseModel):
    """One language's display text for a tool.

    The page shows the English ``description`` / parameter text always, and adds
    this underneath when the current locale is not English.
    """

    description: str = ""
    parameters: dict[str, str] = Field(default_factory=dict)


class ToolItemResponse(BaseModel):
    """One registered tool, as the admin tool page shows it.

    The model only ever sees ``name`` / ``description`` / ``parameters``; the rest
    is the management view - which confirmation the gate asks for, where the tool
    is implemented, how it is grouped and its translations.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Confirmation kind (see agent/tools/permissions.py); "none" never asks.
    permission: str = "none"
    scopes: list[str] = Field(default_factory=list)
    # Whether the tool provides a dry run to fill in the confirmation dialog.
    has_preview: bool = False
    # Implementing file, relative to the repository root; empty when unknown.
    source: str = ""
    # Agent ids whose configuration lets the model call this tool.
    agent_ids: list[str] = Field(default_factory=list)
    # Grouping in the tool list (file / shell / computer / compute / lookup / ...).
    category: str = "other"
    # Locale -> display text. English is not repeated here: it is the fields above.
    description_i18n: dict[str, ToolTextResponse] = Field(default_factory=dict)


class ToolListResponse(BaseModel):
    """Registered tool list response."""

    tools: list[ToolItemResponse]


class ToolTestRequest(BaseModel):
    """Arguments for running one tool from the tool management page."""

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the tool by keyword, as the model would send them.",
    )


class ToolTestResponse(BaseModel):
    """Outcome of running one tool from the tool management page."""

    tool: str
    # False means the call raised; the tool's own errors still come back as
    # ok=true with the error text in ``result``.
    ok: bool
    # What the model would receive as the tool message, capped for display.
    result: str = ""
    # ToolOutcome.details as pretty JSON, for tools that report to the UI.
    details: str = ""
    error: str = ""
    truncated: bool = False
    duration_ms: int = 0


class SkillsRootUpdateRequest(BaseModel):
    """Update the shared skills root folder."""

    skills_root: str = Field(default="", max_length=1024, description="Shared skills root folder.")


class SkillImportRequest(BaseModel):
    """Import a local folder as a new skill."""

    source_path: str = Field(min_length=1, max_length=1024, description="Local folder to copy in.")
