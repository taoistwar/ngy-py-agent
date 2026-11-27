"""Scheduled tasks: their definition, their runs, and what is running right now."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from agent.modes import DEFAULT_MODE


class ScheduleCreateRequest(BaseModel):
    """Create a scheduled task."""

    cron: str = Field(
        min_length=1,
        description="Five-field cron expression (minute hour day month weekday), local time.",
    )
    prompt: str = Field(min_length=1, description="What each run should ask the agent.")
    name: str = Field(default="", description="Label for the list; derived from the prompt when empty.")
    agent_id: str | None = Field(default=None, description="Configured agent id; default agent when omitted.")
    model_id: str | None = Field(default=None, description="Configured model id; provider default when omitted.")
    workspace_id: str | None = Field(
        default=None, description="Workspace the run's session belongs to."
    )
    permission_mode: str | None = Field(
        default=None,
        description=(
            "Confirmation mode pinned to this schedule's runs (ask / auto_approve / "
            "deny_all); omit to follow the global setting."
        ),
    )
    enabled: bool = Field(default=True, description="False starts the schedule paused.")
    recurring: bool = Field(
        default=True,
        description="False runs once and pauses itself, instead of firing on every match.",
    )


class ScheduleUpdateRequest(BaseModel):
    """Change part of a schedule.

    Only the fields present in the body are written, so the pause switch
    (``{"enabled": false}``) does not have to resend the definition. Sending an
    explicit ``null`` for ``model_id`` / ``workspace_id`` clears it.
    """

    cron: str | None = None
    prompt: str | None = None
    name: str | None = None
    agent_id: str | None = None
    model_id: str | None = None
    workspace_id: str | None = None
    # An explicit ``null`` (or empty string) restores "follow the global mode".
    permission_mode: str | None = None
    enabled: bool | None = None
    recurring: bool | None = None


class ScheduleItemResponse(BaseModel):
    """One scheduled task, with the two facts the list shows at a glance."""

    schedule_id: str
    name: str = ""
    cron: str
    prompt: str
    agent_id: str = DEFAULT_MODE
    model_id: str | None = None
    workspace_id: str | None = None
    # Empty follows the global mode; otherwise this schedule's runs are pinned to it.
    permission_mode: str = ""
    enabled: bool = True
    recurring: bool = True
    created_at: datetime
    updated_at: datetime
    # The minute marker the scheduler last claimed ("YYYY-MM-DD HH:MM", local time).
    last_fired: str = ""
    last_run_at: datetime | None = None
    # Computed on read: a stored "next run" would be wrong the moment the clock moves
    # past it without a run actually happening.
    next_run_at: datetime | None = None
    last_run_status: str | None = None
    last_run_task_id: str | None = None
    # True while one of this schedule's tasks is still in flight; that run blocks the
    # next one (the page shows both facts together).
    running: bool = False


class ScheduleRunItemResponse(BaseModel):
    """One attempt: what it created, and what became of the task it created."""

    run_id: str
    schedule_id: str
    schedule_name: str = ""
    trigger: str
    # Launch outcome: ``started`` (a task exists), ``failed`` or ``skipped``.
    status: str
    task_id: str = ""
    session_id: str = ""
    # Live status of the task, read when the run is listed. ``None`` when the task
    # was deleted since (or never created).
    task_status: str | None = None
    task_query: str | None = None
    error: str = ""
    created_at: datetime


class ScheduleListResponse(BaseModel):
    """All scheduled tasks."""

    schedules: list[ScheduleItemResponse]


class ScheduleRunListResponse(BaseModel):
    """Run history of one schedule, newest first."""

    runs: list[ScheduleRunItemResponse]


class RunningScheduleTaskListResponse(BaseModel):
    """Runs whose task is still running or waiting for an answer."""

    tasks: list[ScheduleRunItemResponse]
