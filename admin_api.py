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
from agent.provider import SUPPORTED_PROVIDERS, canonicalize_provider
from agent.rate_limit import parse_rpm_limits, provider_throttle
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
    RpmLimitsConfigRequest,
    RpmLimitsConfigResponse,
)
from task_runtime import purge_expired_tasks_with_log
from task_store import TASK_RETENTION_DEFAULT_DAYS

# Ceiling for one provider's limit: 6000 RPM is 100 requests per second, already past
# anything a real endpoint answers without throttling us itself.
RPM_LIMIT_MAX = 6000

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


def _normalize_rpm_limits(raw: Any) -> dict[str, int]:
    """Canonical provider names only, clamped into ``[0, RPM_LIMIT_MAX]``.

    Unknown names are dropped rather than kept: a bucket no provider can ever ask
    for is a typo, and an admin page that shows it would be reporting configuration
    that does nothing.
    """
    limits: dict[str, int] = {}
    for provider, value in (raw or {}).items():
        name = canonicalize_provider(provider) if str(provider or "").strip() else ""
        if name not in SUPPORTED_PROVIDERS:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        limits[name] = max(0, min(parsed, RPM_LIMIT_MAX))
    return limits


def _load_llm_rpm_config() -> tuple[dict[str, int], str]:
    env_limits = _normalize_rpm_limits(parse_rpm_limits(os.getenv("LLM_RPM", "")))
    db_limits = app_state.monitor_store.get_llm_rpm_limits()
    if db_limits is None:
        return env_limits, "env"
    return _normalize_rpm_limits(db_limits), "database"


def load_startup_config() -> None:
    """Resolve env + database into the live state; called once before serving."""
    app_state.task_retention_days, app_state.task_retention_source = _load_task_retention_config()
    app_state.agent_max_steps, app_state.agent_max_steps_source = _load_agent_max_steps_config()
    app_state.permission_mode, app_state.permission_mode_source = _load_permission_mode_config()
    app_state.llm_rpm_limits, app_state.llm_rpm_limits_source = _load_llm_rpm_config()
    # The limiter holds the policy itself: a task builds its provider per run, so
    # nothing else survives long enough to carry the budget (ADR 0013).
    provider_throttle.configure(app_state.llm_rpm_limits)


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


# ------------------------------------------------------------------ llm rate limit


def _rpm_response(limits: dict[str, int], source: str) -> RpmLimitsConfigResponse:
    return RpmLimitsConfigResponse(
        limits=dict(limits),
        source=source,
        providers=list(SUPPORTED_PROVIDERS),
        max_limit=RPM_LIMIT_MAX,
    )


@router.get("/api/admin/llm-rpm", response_model=RpmLimitsConfigResponse)
async def get_llm_rpm_config() -> RpmLimitsConfigResponse:
    return _rpm_response(app_state.llm_rpm_limits, app_state.llm_rpm_limits_source)


@router.put("/api/admin/llm-rpm", response_model=RpmLimitsConfigResponse)
async def set_llm_rpm_config(
    payload: RpmLimitsConfigRequest,
) -> RpmLimitsConfigResponse:
    """Replace the whole table: a provider left out becomes unlimited again."""
    limits: dict[str, int] = {}
    for provider, value in payload.limits.items():
        name = canonicalize_provider(provider) if str(provider or "").strip() else ""
        if name not in SUPPORTED_PROVIDERS:
            # Rejected, not dropped: silently ignoring a limit the operator just
            # asked for is how a deployment ends up believing it is protected.
            raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'.")
        if value < 0 or value > RPM_LIMIT_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Limit for '{provider}' must be between 0 and {RPM_LIMIT_MAX}.",
            )
        limits[name] = value
    app_state.monitor_store.set_llm_rpm_limits(limits)
    app_state.llm_rpm_limits = limits
    app_state.llm_rpm_limits_source = "database"
    provider_throttle.configure(limits)
    return _rpm_response(limits, "database")


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
