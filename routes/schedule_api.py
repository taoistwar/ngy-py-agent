"""Scheduled task routes: definitions, the pause switch, run history and live runs.

Nothing here decides *when* a schedule fires - that is the scheduler thread's job. The
routes own the definition (validated before it is stored), the manual trigger, and the
two read models the page needs: what ran, and what is running right now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent.modes import DEFAULT_MODE
from agent.runtime import fire_schedule, next_fire_after, validate_cron
from agent.runtime.scheduling.cron import CronError
from commons import state
from commons.schemas import (
    RunningScheduleTaskListResponse,
    ScheduleCreateRequest,
    ScheduleItemResponse,
    ScheduleListResponse,
    ScheduleRunItemResponse,
    ScheduleRunListResponse,
    ScheduleUpdateRequest,
)
from dao.scheduled import TRIGGER_MANUAL

router = APIRouter()

# Default history depth. Enough for a week of an hourly schedule, small enough that
# the page never waits on a year of rows.
DEFAULT_RUN_LIMIT = 50
MAX_RUN_LIMIT = 200

# A derived name is a label, not a summary: the first line of the prompt, cut short.
_NAME_LENGTH = 40


def _schedule_or_404(schedule_id: str) -> dict[str, Any]:
    schedule = state.monitor_store.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found.")
    return schedule


def _checked_cron(raw: str) -> str:
    """The expression as stored: whitespace collapsed, syntax verified."""
    text = " ".join(str(raw or "").split())
    error = validate_cron(text)
    if error is not None:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {error}")
    return text


def _checked_prompt(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="A scheduled task needs a prompt.")
    return text


def _default_name(prompt: str) -> str:
    return " ".join(str(prompt or "").split())[:_NAME_LENGTH]


def _checked_agent(raw: str | None) -> str:
    agent_id = str(raw or "").strip() or DEFAULT_MODE
    if state.monitor_store.get_agent(agent_id) is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent '{agent_id}'.")
    return agent_id


def _checked_model(raw: str | None) -> str | None:
    model_id = str(raw or "").strip()
    if not model_id:
        return None
    if state.monitor_store.llm.get_model(model_id) is None:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model_id}'.")
    return model_id


def _checked_workspace(raw: str | None) -> str | None:
    workspace_id = str(raw or "").strip()
    if not workspace_id:
        return None
    if state.monitor_store.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=400, detail=f"Unknown workspace '{workspace_id}'.")
    return workspace_id


def _next_run_at(schedule: dict[str, Any]) -> datetime | None:
    """When the scheduler will fire this next, or ``None`` when it is paused."""
    if not schedule.get("enabled"):
        return None
    try:
        return next_fire_after(schedule["cron"], datetime.now())
    except CronError:
        # Only a hand-edited row can get here; the list must still render.
        return None


def _schedule_response(schedule: dict[str, Any]) -> ScheduleItemResponse:
    schedule_id = str(schedule["schedule_id"])
    latest = state.monitor_store.list_schedule_runs(schedule_id, limit=1)
    last_run = latest[0] if latest else None
    return ScheduleItemResponse(
        schedule_id=schedule_id,
        name=schedule["name"],
        cron=schedule["cron"],
        prompt=schedule["prompt"],
        agent_id=schedule["agent_id"],
        model_id=schedule["model_id"],
        workspace_id=schedule["workspace_id"],
        enabled=schedule["enabled"],
        recurring=schedule["recurring"],
        created_at=schedule["created_at"],
        updated_at=schedule["updated_at"],
        last_fired=schedule["last_fired"],
        last_run_at=schedule["last_run_at"],
        next_run_at=_next_run_at(schedule),
        last_run_status=(last_run or {}).get("status"),
        last_run_task_id=(last_run or {}).get("task_id") or None,
        running=state.monitor_store.has_active_schedule_run(schedule_id),
    )


def _run_response(run: dict[str, Any]) -> ScheduleRunItemResponse:
    return ScheduleRunItemResponse(**run)


# ------------------------------------------------------------------ read: live runs
# Declared before the per-id routes below: ``/api/schedules/running`` would otherwise
# be read as a schedule id.


@router.get("/api/schedules/running", response_model=RunningScheduleTaskListResponse)
async def list_running_schedule_tasks() -> RunningScheduleTaskListResponse:
    """Scheduled runs whose task is still going, including ones waiting for an answer."""
    return RunningScheduleTaskListResponse(
        tasks=[_run_response(run) for run in state.monitor_store.list_running_schedule_runs()]
    )


# ------------------------------------------------------------------- schedules CRUD


@router.get("/api/schedules", response_model=ScheduleListResponse)
async def list_schedules() -> ScheduleListResponse:
    return ScheduleListResponse(
        schedules=[
            _schedule_response(schedule)
            for schedule in state.monitor_store.list_schedules()
        ]
    )


@router.post("/api/schedules", response_model=ScheduleItemResponse, status_code=201)
async def create_schedule(payload: ScheduleCreateRequest) -> ScheduleItemResponse:
    """Validate, store, and answer with the schedule as the list will read it."""
    prompt = _checked_prompt(payload.prompt)
    name = payload.name.strip() or _default_name(prompt)
    schedule_id = state.monitor_store.create_schedule(
        cron=_checked_cron(payload.cron),
        prompt=prompt,
        name=name,
        agent_id=_checked_agent(payload.agent_id),
        model_id=_checked_model(payload.model_id),
        workspace_id=_checked_workspace(payload.workspace_id),
        enabled=payload.enabled,
        recurring=payload.recurring,
    )
    return _schedule_response(_schedule_or_404(schedule_id))


@router.put("/api/schedules/{schedule_id}", response_model=ScheduleItemResponse)
async def update_schedule(
    schedule_id: str, payload: ScheduleUpdateRequest
) -> ScheduleItemResponse:
    """Patch the definition. The pause switch is just ``{"enabled": false}``."""
    current = _schedule_or_404(schedule_id)
    changes = payload.model_dump(exclude_unset=True)

    if "cron" in changes:
        if changes["cron"] is None:
            raise HTTPException(status_code=400, detail="A cron expression cannot be cleared.")
        changes["cron"] = _checked_cron(changes["cron"])
    if "prompt" in changes:
        if changes["prompt"] is None:
            raise HTTPException(status_code=400, detail="A prompt cannot be cleared.")
        changes["prompt"] = _checked_prompt(changes["prompt"])
    if "name" in changes:
        name = str(changes["name"] or "").strip()
        changes["name"] = name or _default_name(changes.get("prompt") or current["prompt"])
    if "agent_id" in changes:
        changes["agent_id"] = _checked_agent(changes["agent_id"])
    if "model_id" in changes:
        changes["model_id"] = _checked_model(changes["model_id"])
    if "workspace_id" in changes:
        changes["workspace_id"] = _checked_workspace(changes["workspace_id"])
    if "enabled" in changes and changes["enabled"] is None:
        raise HTTPException(status_code=400, detail="'enabled' must be true or false.")

    state.monitor_store.update_schedule(schedule_id, **changes)
    return _schedule_response(_schedule_or_404(schedule_id))


@router.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str) -> dict[str, Any]:
    """Remove the schedule and its run history; the tasks those runs started stay."""
    _schedule_or_404(schedule_id)
    state.monitor_store.delete_schedule(schedule_id)
    return {"schedule_id": schedule_id, "deleted": True}


# --------------------------------------------------------------- running one schedule


@router.post("/api/schedules/{schedule_id}/run", response_model=ScheduleRunItemResponse)
async def run_schedule_now(schedule_id: str) -> ScheduleRunItemResponse:
    """Fire the schedule immediately, whether or not it is paused.

    A manual trigger goes through the same path as a timed one - session first, task
    second - so "run now" cannot produce a run the history does not know about.
    """
    schedule = _schedule_or_404(schedule_id)
    return _run_response(fire_schedule(schedule, TRIGGER_MANUAL))


@router.get("/api/schedules/{schedule_id}/runs", response_model=ScheduleRunListResponse)
async def list_schedule_runs(
    schedule_id: str,
    limit: int = Query(DEFAULT_RUN_LIMIT, ge=1, le=MAX_RUN_LIMIT),
) -> ScheduleRunListResponse:
    _schedule_or_404(schedule_id)
    return ScheduleRunListResponse(
        runs=[
            _run_response(run)
            for run in state.monitor_store.list_schedule_runs(schedule_id, limit=limit)
        ]
    )
