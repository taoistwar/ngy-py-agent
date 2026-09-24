"""Admin configuration: retention, step limit, permission mode and permission rules.

Two things live here that are not routes: the startup loaders that resolve env + database
into :mod:`app_state`, and the retention purge the task routes also call. Both belong to
"the config the admin API owns", which is why they are not in the routes' way.

Every setter writes the database **and** the live state, and reports ``source``
accordingly: an admin PUT has to take effect on the next task, not on the next restart.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

import app_state
from agent.agent_loop import DEFAULT_MAX_STEPS
from agent.tools.permissions import PermissionMode, normalize_mode
from api_schemas import (
    MaxStepsConfigRequest,
    MaxStepsConfigResponse,
    PermissionModeConfigRequest,
    PermissionModeConfigResponse,
    PermissionRuleItem,
    PermissionRuleListResponse,
    PermissionRuleRequest,
    RetentionConfigRequest,
    RetentionConfigResponse,
)
from task_runtime import purge_expired_tasks_with_log
from task_store import TASK_RETENTION_DEFAULT_DAYS

router = APIRouter()


# ------------------------------------------------------------------- startup


def load_env_file() -> None:
    """Read the repository's ``.env`` before anything else asks for configuration."""
    root_env = app_state.ROOT_DIR / ".env"
    if root_env.exists():
        load_dotenv(root_env)


def _load_agent_max_steps_config() -> tuple[int, str]:
    env_raw = os.getenv("REACT_MAX_STEPS", str(DEFAULT_MAX_STEPS)).strip()
    try:
        env_steps = int(env_raw)
    except ValueError:
        env_steps = DEFAULT_MAX_STEPS
    env_steps = max(1, min(env_steps, 1000))

    db_steps = app_state.monitor_store.get_agent_max_steps()
    if db_steps is None:
        return env_steps, "env"
    return max(1, min(db_steps, 1000)), "database"


def _load_permission_mode_config() -> tuple[PermissionMode, str]:
    env_mode = normalize_mode(os.getenv("PERMISSION_MODE", PermissionMode.ASK.value))
    db_mode = app_state.monitor_store.get_permission_mode()
    if not db_mode:
        return env_mode, "env"
    return normalize_mode(db_mode), "database"


def _get_env_task_retention_days() -> int:
    raw = os.getenv("TASK_RETENTION_DAYS", str(TASK_RETENTION_DEFAULT_DAYS)).strip()
    try:
        days = int(raw)
    except ValueError:
        return TASK_RETENTION_DEFAULT_DAYS
    if days < 0:
        return 0
    return days


def _load_task_retention_config() -> tuple[int, str]:
    env_days = _get_env_task_retention_days()
    db_days = app_state.monitor_store.get_task_retention_days()
    if db_days is None:
        return env_days, "env"
    return db_days, "database"


def load_startup_config() -> None:
    """Resolve env + database into the live state; called once before serving."""
    app_state.task_retention_days, app_state.task_retention_source = _load_task_retention_config()
    app_state.agent_max_steps, app_state.agent_max_steps_source = _load_agent_max_steps_config()
    app_state.permission_mode, app_state.permission_mode_source = _load_permission_mode_config()


# -------------------------------------------------------------------- retention


@router.get("/api/admin/retention", response_model=RetentionConfigResponse)
async def get_retention_config() -> RetentionConfigResponse:
    return RetentionConfigResponse(
        retention_days=app_state.task_retention_days,
        retention_source=app_state.task_retention_source,
        removed_tasks=0,
    )


@router.put("/api/admin/retention", response_model=RetentionConfigResponse)
async def set_retention_config(
    payload: RetentionConfigRequest,
) -> RetentionConfigResponse:
    app_state.monitor_store.set_task_retention_days(payload.retention_days)
    app_state.task_retention_days = max(0, payload.retention_days)
    app_state.task_retention_source = "database"
    removed = purge_expired_tasks_with_log("Retention config updated")
    return RetentionConfigResponse(
        retention_days=app_state.task_retention_days,
        retention_source=app_state.task_retention_source,
        removed_tasks=removed,
    )


# -------------------------------------------------------------------- max steps


@router.get("/api/admin/max-steps", response_model=MaxStepsConfigResponse)
async def get_max_steps_config() -> MaxStepsConfigResponse:
    return MaxStepsConfigResponse(
        max_steps=app_state.agent_max_steps,
        source=app_state.agent_max_steps_source,
    )


@router.put("/api/admin/max-steps", response_model=MaxStepsConfigResponse)
async def set_max_steps_config(
    payload: MaxStepsConfigRequest,
) -> MaxStepsConfigResponse:
    steps = max(1, min(payload.max_steps, 1000))
    app_state.monitor_store.set_agent_max_steps(steps)
    app_state.agent_max_steps = steps
    app_state.agent_max_steps_source = "database"
    return MaxStepsConfigResponse(
        max_steps=app_state.agent_max_steps,
        source=app_state.agent_max_steps_source,
    )


# --------------------------------------------------------------- permission mode


@router.get("/api/admin/permission-mode", response_model=PermissionModeConfigResponse)
async def get_permission_mode_config() -> PermissionModeConfigResponse:
    return PermissionModeConfigResponse(
        mode=app_state.permission_mode.value,
        source=app_state.permission_mode_source,
    )


@router.put("/api/admin/permission-mode", response_model=PermissionModeConfigResponse)
async def set_permission_mode_config(
    payload: PermissionModeConfigRequest,
) -> PermissionModeConfigResponse:
    try:
        mode = PermissionMode(payload.mode)
    except ValueError as exc:
        # Rejected rather than coerced: silently turning a typo into "ask" (or
        # worse, into "auto_approve") is not something an admin API should do.
        raise HTTPException(
            status_code=400,
            detail=f"Unknown permission mode '{payload.mode}'.",
        ) from exc
    app_state.monitor_store.set_permission_mode(mode.value)
    app_state.permission_mode = mode
    app_state.permission_mode_source = "database"
    return PermissionModeConfigResponse(
        mode=app_state.permission_mode.value,
        source=app_state.permission_mode_source,
    )


# -------------------------------------------------------------- permission rules


@router.get("/api/admin/permission-rules", response_model=PermissionRuleListResponse)
async def list_permission_rules() -> PermissionRuleListResponse:
    """Rules that answer "always allow" without asking again."""
    rules = app_state.permission_rule_store.list()
    return PermissionRuleListResponse(
        rules=[PermissionRuleItem(**rule.to_payload()) for rule in rules],
        path=app_state.permission_rule_store.path.as_posix(),
    )


@router.post("/api/admin/permission-rules", response_model=PermissionRuleItem)
async def add_permission_rule(payload: PermissionRuleRequest) -> PermissionRuleItem:
    tool = payload.tool.strip()
    if not app_state.permission_rule_store.add(tool, payload.target):
        raise HTTPException(
            status_code=500, detail="Could not write the permission rule file."
        )
    for rule in app_state.permission_rule_store.list():
        if rule.tool == tool and rule.target == payload.target:
            return PermissionRuleItem(**rule.to_payload())
    raise HTTPException(status_code=500, detail="The permission rule was not persisted.")


@router.delete("/api/admin/permission-rules")
async def delete_permission_rule(
    tool: str = Query(min_length=1),
    target: str = Query(min_length=1),
) -> dict[str, Any]:
    # Query parameters rather than a body: DELETE bodies are dropped by some
    # proxies, and a silently dropped body would look like "rule not found".
    if not app_state.permission_rule_store.remove(tool, target):
        raise HTTPException(status_code=404, detail="No such permission rule.")
    return {"removed": True, "tool": tool, "target": target}
