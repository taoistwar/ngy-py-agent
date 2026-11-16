"""Tool confirmation: allow rules, deny-list rules, decisions and question answers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PermissionRuleItem(BaseModel):
    """One persisted allow rule."""

    tool: str
    target: str
    kind: str = ""
    created_at: str = ""


class PermissionRuleListResponse(BaseModel):
    """Persisted allow rules."""

    rules: list[PermissionRuleItem]
    path: str


class PermissionRuleRequest(BaseModel):
    """Add a persisted allow rule without going through a dialog."""

    tool: str = Field(min_length=1, description="Tool name, e.g. exec.")
    target: str = Field(min_length=1, description="The exact target shown in the dialog.")


class DenyArgumentRequest(BaseModel):
    """One argument condition of a deny-list rule."""

    field: str = Field(min_length=1, description="Argument name; a.b reaches nested values.")
    match: str = Field(default="fixed", description="fixed / regex")
    value: str = Field(default="", description="Exact value, or the pattern for regex.")


class DenyRuleItem(BaseModel):
    """One deny-list rule, as the management page shows it."""

    id: str
    tool: dict[str, Any]
    args: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""


class DenyRuleListResponse(BaseModel):
    """Deny-list rules, the file they live in, and the rules that were dropped."""

    rules: list[DenyRuleItem]
    path: str
    problems: list[str] = Field(default_factory=list)


class DenyRuleRequest(BaseModel):
    """Create (or replace, by id) one deny-list rule."""

    id: str = Field(default="", description="Rule id; empty generates one.")
    tool: str = Field(min_length=1, description="Tool name, or a pattern when tool_match is regex.")
    tool_match: str = Field(default="fixed", description="fixed / regex")
    args: list[DenyArgumentRequest] = Field(
        default_factory=list, description="All of them must match; empty blocks the whole tool."
    )
    reason: str = ""


class PermissionDecisionRequest(BaseModel):
    """Answer to a pending permission request."""

    allowed: bool = Field(description="Whether the tool call may run.")
    scope: str = Field(
        default="once", description="once / session / always, as offered by the tool"
    )


class PermissionDecisionResponse(BaseModel):
    """Result of answering a permission request."""

    task_id: str
    request_id: str
    allowed: bool
    scope: str


class QuestionAnswerRequest(BaseModel):
    """Answer to a pending question batch.

    ``answers`` is keyed by question id and each value is ``{"answers": [...]}``, i.e.
    the same shape the model is promised as output. A question the user skipped may be
    omitted or carry an empty list (ADR 0010 D5).
    """

    answers: dict[str, Any] = Field(
        default_factory=dict,
        description='Answers keyed by question id, each an object with an "answers" array.',
    )


class QuestionAnswerResponse(BaseModel):
    """Result of answering a pending question batch."""

    task_id: str
    request_id: str
    status: str
    answered_count: int
