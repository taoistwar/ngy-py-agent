"""Admin configuration: retention, step limit, AGENTS.md, permission mode and rules, deny-list.

Two things live here that are not routes: the startup loaders that resolve env + database
into :mod:`commons.state`, and the retention purge the task routes also call. Both belong to
"the config the admin API owns", which is why they are not in the routes' way.

Every setter writes the database **and** the live state, and reports ``source``
accordingly: an admin PUT has to take effect on the next task, not on the next restart.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

from agent.agent_loop import DEFAULT_MAX_STEPS
from agent.agents_md import DEFAULT_MAX_BYTES as AGENTS_MD_DEFAULT_MAX_BYTES
from agent.agents_md import MAX_BYTES_LIMIT as AGENTS_MD_MAX_BYTES_LIMIT
from agent.agents_md import MIN_MAX_BYTES as AGENTS_MD_MIN_BYTES
from agent.agents_md import AgentsMdSettings
from agent.tools.denylist import (
    MATCH_FIXED,
    MATCH_KINDS,
    MATCH_REGEX,
    ToolDenyRule,
    parse_rules,
)
from agent.tools.memory_notes import DEFAULT_MAX_PROMPT_CHARS as MEMORY_PROMPT_DEFAULT_CHARS
from agent.tools.memory_notes import MAX_PROMPT_CHARS as MEMORY_MAX_PROMPT_CHARS
from agent.tools.permissions import PermissionMode, normalize_mode
from agent.tools.web_fetch import limits as web_fetch_limits
from agent.tools.web_fetch import providers as web_fetch_providers
from agent.tools.web_search import limits as web_search_limits
from agent.tools.web_search import providers as web_search_providers
from commons import state
from commons.schemas import (
    MAX_STEPS_LIMIT,
    AgentsMdConfigRequest,
    AgentsMdConfigResponse,
    DenyRuleItem,
    DenyRuleListResponse,
    DenyRuleRequest,
    MaxStepsConfigRequest,
    MaxStepsConfigResponse,
    PermissionModeConfigRequest,
    PermissionModeConfigResponse,
    PermissionRuleItem,
    PermissionRuleListResponse,
    PermissionRuleRequest,
    RetentionConfigRequest,
    RetentionConfigResponse,
    WebFetchConfigRequest,
    WebFetchConfigResponse,
    WebSearchConfigRequest,
    WebSearchConfigResponse,
)
from dao import TASK_RETENTION_DEFAULT_DAYS
from routes import llm_api

router = APIRouter()


# ------------------------------------------------------------------- startup


def load_env_file() -> None:
    """Read the repository's ``.env`` before anything else asks for configuration."""
    root_env = state.ROOT_DIR / ".env"
    if root_env.exists():
        load_dotenv(root_env)


def _clamp_max_steps(value: int) -> int:
    """Keep a step limit inside the range the API advertises."""
    return max(1, min(value, MAX_STEPS_LIMIT))


def _load_agent_max_steps_config() -> tuple[int, str]:
    """The global step limit: the database value, else the code default."""
    db_steps = state.monitor_store.get_agent_max_steps()
    if db_steps is None:
        return DEFAULT_MAX_STEPS, "default"
    return _clamp_max_steps(db_steps), "database"


def _clamp_agents_md_bytes(value: int) -> int:
    """Keep the byte cap inside the range the API advertises."""
    return max(AGENTS_MD_MIN_BYTES, min(int(value), AGENTS_MD_MAX_BYTES_LIMIT))


def _load_agents_md_config() -> tuple[AgentsMdSettings, str]:
    """AGENTS.md on/off and byte cap: the database value, else the code defaults."""
    stored = state.monitor_store.get_agents_md_config()
    if not stored:
        return AgentsMdSettings(), "default"
    raw_bytes = stored.get("max_bytes", AGENTS_MD_DEFAULT_MAX_BYTES)
    try:
        max_bytes = _clamp_agents_md_bytes(int(raw_bytes))
    except (TypeError, ValueError):
        max_bytes = AGENTS_MD_DEFAULT_MAX_BYTES
    return (
        AgentsMdSettings(enabled=bool(stored.get("enabled", True)), max_bytes=max_bytes),
        "database",
    )


def _load_permission_mode_config() -> tuple[PermissionMode, str]:
    env_mode = normalize_mode(os.getenv("PERMISSION_MODE", PermissionMode.ASK.value))
    db_mode = state.monitor_store.get_permission_mode()
    if not db_mode:
        return env_mode, "env"
    return normalize_mode(db_mode), "database"


def _load_web_search_config() -> tuple[web_search_limits.BackendSettings, str]:
    """The saved search backend, else the environment's.

    A saved row owns all three fields: falling back per field would let a key
    from ``.env`` silently serve a provider chosen on the page, which is not
    what the page says. A row naming an unknown backend (a hand-edited database)
    degrades to the keyless default instead of failing every search.
    """
    env_backend = web_search_limits.env_backend()
    # The page only offers canonical ids, so an alias in .env must not leave the
    # GET response naming a value the form cannot display.
    env_provider = web_search_providers.canonical_name(env_backend.provider)
    if env_provider not in web_search_providers.SUPPORTED:
        env_provider = web_search_limits.DEFAULT_PROVIDER
    env_backend = web_search_limits.BackendSettings(
        provider=env_provider,
        api_key=env_backend.api_key,
        base_url=env_backend.base_url,
    )
    stored = state.monitor_store.get_web_search_config()
    if not stored:
        return env_backend, "env"
    provider = web_search_providers.canonical_name(stored.get("provider"))
    if provider not in web_search_providers.SUPPORTED:
        provider = web_search_limits.DEFAULT_PROVIDER
    return (
        web_search_limits.BackendSettings(
            provider=provider,
            api_key=str(stored.get("api_key") or "").strip(),
            base_url=str(stored.get("base_url") or "").strip(),
        ),
        "database",
    )


def _checked_web_search_provider(raw: Any) -> str:
    provider = web_search_providers.canonical_name(raw)
    if provider not in web_search_providers.SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown search provider '{raw}'; use one of: "
                f"{', '.join(web_search_providers.SUPPORTED)}."
            ),
        )
    return provider


def _load_web_fetch_config() -> tuple[web_fetch_limits.BackendSettings, str]:
    """The saved fetch backend, else the environment's.

    A saved row owns all three fields, so a key in ``.env`` cannot silently serve
    a provider chosen on the page. An unknown stored backend (a hand-edited
    database) degrades to the keyless local fetcher instead of failing every fetch.
    """
    env_backend = web_fetch_limits.env_backend()
    env_provider = web_fetch_providers.canonical_name(env_backend.provider)
    if env_provider not in web_fetch_providers.SUPPORTED:
        env_provider = web_fetch_limits.DEFAULT_PROVIDER
    env_backend = web_fetch_limits.BackendSettings(
        provider=env_provider,
        api_key=env_backend.api_key,
        base_url=env_backend.base_url,
    )
    stored = state.monitor_store.get_web_fetch_config()
    if not stored:
        return env_backend, "env"
    provider = web_fetch_providers.canonical_name(stored.get("provider"))
    if provider not in web_fetch_providers.SUPPORTED:
        provider = web_fetch_limits.DEFAULT_PROVIDER
    return (
        web_fetch_limits.BackendSettings(
            provider=provider,
            api_key=str(stored.get("api_key") or "").strip(),
            base_url=str(stored.get("base_url") or "").strip(),
        ),
        "database",
    )


def _checked_web_fetch_provider(raw: Any) -> str:
    provider = web_fetch_providers.canonical_name(raw)
    if provider not in web_fetch_providers.SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown fetch provider '{raw}'; use one of: "
                f"{', '.join(web_fetch_providers.SUPPORTED)}."
            ),
        )
    return provider


def _checked_http_endpoint(raw: Any, what: str) -> str:
    """An empty or http(s) endpoint override; anything else is a 400."""
    url = str(raw or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(
            status_code=400,
            detail=f"{what} '{url}' is not an http(s) URL.",
        )
    return url


def _load_task_retention_config() -> tuple[int, str]:
    """The stored row, else the code default; retention has no environment fallback."""
    db_days = state.monitor_store.get_task_retention_days()
    if db_days is None:
        return TASK_RETENTION_DEFAULT_DAYS, "default"
    return db_days, "database"


def _clamp_memory_prompt_chars(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return MEMORY_PROMPT_DEFAULT_CHARS
    return max(0, min(MEMORY_MAX_PROMPT_CHARS, value))


def _load_memory_config() -> tuple[bool, bool, int, str]:
    """The cross-session memory switches: the stored row, else the code's defaults.

    No environment variables: a feature that ships on has one answer, and an operator
    who wants it off can say so on the page (the same reasoning as the skill library's
    root, minus the env fallback it needs for a folder that may not exist yet).
    """
    stored = state.monitor_store.get_memory_config()
    if not stored:
        return True, True, MEMORY_PROMPT_DEFAULT_CHARS, "default"
    return (
        bool(stored.get("enabled", True)),
        bool(stored.get("auto_extract", True)),
        _clamp_memory_prompt_chars(stored.get("max_prompt_chars")),
        "database",
    )


def load_startup_config() -> None:
    """Resolve env + database into the live state; called once before serving."""
    state.task_retention_days, state.task_retention_source = _load_task_retention_config()
    state.agent_max_steps, state.agent_max_steps_source = _load_agent_max_steps_config()
    agents_md, agents_md_source = _load_agents_md_config()
    state.agents_md_enabled = agents_md.enabled
    state.agents_md_max_bytes = agents_md.max_bytes
    state.agents_md_source = agents_md_source
    (
        state.memories_enabled,
        state.memories_auto_extract,
        state.memories_max_prompt_chars,
        state.memories_source,
    ) = _load_memory_config()
    state.permission_mode, state.permission_mode_source = _load_permission_mode_config()
    # The tool layer keeps no database handle, so the effective search backend is
    # pushed into it here and on every admin write (see ``web_search_limits``).
    web_search_backend, _ = _load_web_search_config()
    web_search_limits.configure(web_search_backend)
    web_fetch_backend, _ = _load_web_fetch_config()
    web_fetch_limits.configure(web_fetch_backend)
    # The limiter holds the policy itself: a task builds its provider per run, so
    # nothing else survives long enough to carry the budgets (ADR 0014).
    llm_api.sync_provider_throttle()


# -------------------------------------------------------------------- retention


@router.get("/api/admin/retention", response_model=RetentionConfigResponse)
async def get_retention_config() -> RetentionConfigResponse:
    return RetentionConfigResponse(
        retention_days=state.task_retention_days,
        retention_source=state.task_retention_source,
        removed_tasks=0,
    )


@router.put("/api/admin/retention", response_model=RetentionConfigResponse)
async def set_retention_config(
    payload: RetentionConfigRequest,
) -> RetentionConfigResponse:
    state.monitor_store.set_task_retention_days(payload.retention_days)
    state.task_retention_days = max(0, payload.retention_days)
    state.task_retention_source = "database"
    # The hourly sweep picks the new window up on its next tick; nothing is purged
    # inline, so this response always reports zero removed rows.
    return RetentionConfigResponse(
        retention_days=state.task_retention_days,
        retention_source=state.task_retention_source,
        removed_tasks=0,
    )


# -------------------------------------------------------------------- max steps


@router.get("/api/admin/max-steps", response_model=MaxStepsConfigResponse)
async def get_max_steps_config() -> MaxStepsConfigResponse:
    return MaxStepsConfigResponse(
        max_steps=state.agent_max_steps,
        source=state.agent_max_steps_source,
    )


@router.put("/api/admin/max-steps", response_model=MaxStepsConfigResponse)
async def set_max_steps_config(
    payload: MaxStepsConfigRequest,
) -> MaxStepsConfigResponse:
    steps = _clamp_max_steps(payload.max_steps)
    state.monitor_store.set_agent_max_steps(steps)
    state.agent_max_steps = steps
    state.agent_max_steps_source = "database"
    return MaxStepsConfigResponse(
        max_steps=state.agent_max_steps,
        source=state.agent_max_steps_source,
    )


# ------------------------------------------------------------------- agents md


@router.get("/api/admin/agents-md", response_model=AgentsMdConfigResponse)
async def get_agents_md_config() -> AgentsMdConfigResponse:
    return AgentsMdConfigResponse(
        enabled=state.agents_md_enabled,
        max_bytes=state.agents_md_max_bytes,
        source=state.agents_md_source,
    )


@router.put("/api/admin/agents-md", response_model=AgentsMdConfigResponse)
async def set_agents_md_config(payload: AgentsMdConfigRequest) -> AgentsMdConfigResponse:
    max_bytes = _clamp_agents_md_bytes(payload.max_bytes)
    # Written and reported together: the panel edits one setting, and a task reads it
    # from ``commons.state`` on its next run rather than on its next restart.
    state.monitor_store.set_agents_md_config(payload.enabled, max_bytes)
    state.agents_md_enabled = payload.enabled
    state.agents_md_max_bytes = max_bytes
    state.agents_md_source = "database"
    return AgentsMdConfigResponse(
        enabled=state.agents_md_enabled,
        max_bytes=state.agents_md_max_bytes,
        source=state.agents_md_source,
    )


# --------------------------------------------------------------- permission mode


@router.get("/api/admin/permission-mode", response_model=PermissionModeConfigResponse)
async def get_permission_mode_config() -> PermissionModeConfigResponse:
    return PermissionModeConfigResponse(
        mode=state.permission_mode.value,
        source=state.permission_mode_source,
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
    state.monitor_store.set_permission_mode(mode.value)
    state.permission_mode = mode
    state.permission_mode_source = "database"
    return PermissionModeConfigResponse(
        mode=state.permission_mode.value,
        source=state.permission_mode_source,
    )


# ------------------------------------------------------------------ web search


def _web_search_response(
    backend: web_search_limits.BackendSettings, source: str
) -> WebSearchConfigResponse:
    return WebSearchConfigResponse(
        provider=backend.provider,
        api_key=backend.api_key,
        base_url=backend.base_url,
        source=source,
        supported=list(web_search_providers.SUPPORTED),
    )


@router.get("/api/admin/web-search", response_model=WebSearchConfigResponse)
async def get_web_search_config() -> WebSearchConfigResponse:
    backend, source = _load_web_search_config()
    return _web_search_response(backend, source)


@router.put("/api/admin/web-search", response_model=WebSearchConfigResponse)
async def set_web_search_config(
    payload: WebSearchConfigRequest,
) -> WebSearchConfigResponse:
    backend = web_search_limits.BackendSettings(
        provider=_checked_web_search_provider(payload.provider),
        api_key=payload.api_key.strip(),
        base_url=_checked_http_endpoint(payload.base_url, "Search endpoint"),
    )
    # Written and pushed together: the next search in a running task must use
    # the backend the page just saved, without waiting for a restart.
    state.monitor_store.set_web_search_config(
        backend.provider, backend.api_key, backend.base_url
    )
    web_search_limits.configure(backend)
    return _web_search_response(backend, "database")


# ------------------------------------------------------------------- web fetch


def _web_fetch_response(
    backend: web_fetch_limits.BackendSettings, source: str
) -> WebFetchConfigResponse:
    return WebFetchConfigResponse(
        provider=backend.provider,
        api_key=backend.api_key,
        base_url=backend.base_url,
        source=source,
        supported=list(web_fetch_providers.SUPPORTED),
    )


@router.get("/api/admin/web-fetch", response_model=WebFetchConfigResponse)
async def get_web_fetch_config() -> WebFetchConfigResponse:
    backend, source = _load_web_fetch_config()
    return _web_fetch_response(backend, source)


@router.put("/api/admin/web-fetch", response_model=WebFetchConfigResponse)
async def set_web_fetch_config(payload: WebFetchConfigRequest) -> WebFetchConfigResponse:
    backend = web_fetch_limits.BackendSettings(
        provider=_checked_web_fetch_provider(payload.provider),
        api_key=payload.api_key.strip(),
        base_url=_checked_http_endpoint(payload.base_url, "Fetch endpoint"),
    )
    # Written and pushed together: the next fetch in a running task must use the
    # backend the page just saved, without waiting for a restart.
    state.monitor_store.set_web_fetch_config(
        backend.provider, backend.api_key, backend.base_url
    )
    web_fetch_limits.configure(backend)
    return _web_fetch_response(backend, "database")


# -------------------------------------------------------------- permission rules


@router.get("/api/admin/permission-rules", response_model=PermissionRuleListResponse)
async def list_permission_rules() -> PermissionRuleListResponse:
    """Rules that answer "always allow" without asking again."""
    rules = state.permission_rule_store.list()
    return PermissionRuleListResponse(
        rules=[PermissionRuleItem(**rule.to_payload()) for rule in rules],
        path=state.permission_rule_store.path.as_posix(),
    )


@router.post("/api/admin/permission-rules", response_model=PermissionRuleItem)
async def add_permission_rule(payload: PermissionRuleRequest) -> PermissionRuleItem:
    tool = payload.tool.strip()
    if not state.permission_rule_store.add(tool, payload.target):
        raise HTTPException(
            status_code=500, detail="Could not write the permission rule file."
        )
    for rule in state.permission_rule_store.list():
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
    if not state.permission_rule_store.remove(tool, target):
        raise HTTPException(status_code=404, detail="No such permission rule.")
    return {"removed": True, "tool": tool, "target": target}


# ------------------------------------------------------------------- deny-list


def _deny_spec(kind: str, text: str, where: str) -> dict[str, str]:
    """Build one match spec from the flat form the management page posts."""
    match = (kind or MATCH_FIXED).strip().lower()
    if match not in MATCH_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"{where}: unknown match kind '{kind}'. Use one of: {', '.join(MATCH_KINDS)}.",
        )
    body = str(text or "")
    if not body.strip():
        raise HTTPException(status_code=400, detail=f"{where}: value must not be empty.")
    if match == MATCH_REGEX:
        return {"match": MATCH_REGEX, "pattern": body}
    return {"match": MATCH_FIXED, "value": body}


def _build_deny_rule(payload: DenyRuleRequest) -> ToolDenyRule:
    """Validate a posted rule through the parser the file itself goes through.

    One parser means the page cannot write a rule that the running tasks would
    drop: a bad pattern fails here with a 400 instead of silently never matching.
    """
    draft: dict[str, Any] = {
        "id": payload.id.strip() or f"ui-{uuid4().hex[:8]}",
        "tool": _deny_spec(payload.tool_match, payload.tool, "tool"),
        "reason": payload.reason.strip(),
    }
    args = [
        {
            "field": item.field.strip(),
            **_deny_spec(item.match, item.value, f"args[{index}].{item.field}"),
        }
        for index, item in enumerate(payload.args)
    ]
    if args:
        draft["args"] = args
    rules, problems = parse_rules({"rules": [draft]})
    if problems or not rules:
        raise HTTPException(status_code=400, detail="; ".join(problems) or "Invalid deny rule.")
    return rules[0]


@router.get("/api/admin/denylist", response_model=DenyRuleListResponse)
async def list_deny_rules() -> DenyRuleListResponse:
    """Rules that refuse a tool call outright, before the permission gate (ADR 0024)."""
    store = state.denylist_store
    return DenyRuleListResponse(
        rules=[DenyRuleItem(**rule.to_payload()) for rule in store.list()],
        path=store.path.as_posix(),
        problems=store.problems,
    )


@router.post("/api/admin/denylist", response_model=DenyRuleItem)
async def add_deny_rule(payload: DenyRuleRequest) -> DenyRuleItem:
    rule = _build_deny_rule(payload)
    if not state.denylist_store.add(rule):
        raise HTTPException(status_code=500, detail="Could not write the deny-list file.")
    return DenyRuleItem(**rule.to_payload())


@router.delete("/api/admin/denylist")
async def delete_deny_rule(rule_id: str = Query(min_length=1, alias="id")) -> dict[str, Any]:
    # Query parameter rather than a body, for the same reason as the rule delete
    # above: a silently dropped DELETE body would look like "rule not found".
    if not state.denylist_store.remove(rule_id):
        raise HTTPException(status_code=404, detail="No such deny rule.")
    return {"removed": True, "id": rule_id}
