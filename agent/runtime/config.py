"""Resolution: which endpoint, workspace, step limit and confirmation mode a task runs with.

The request carries optional overrides; the live state carries the global settings the
admin API wrote. Everything here answers one question of that shape, so the runner can
stay about running.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from agent.agent_loop import DEFAULT_MAX_STEPS
from agent.agents_md import AgentsMdSettings
from agent.checkpoints import CheckpointStore
from agent.provider import ProviderConfig, canonicalize_provider
from agent.tools.permissions import PermissionMode, normalize_mode
from commons import state
from commons.schemas import RunTaskRequest


def build_provider_config(
    model: dict[str, Any] | None,
    provider: dict[str, Any] | None = None,
) -> Optional[ProviderConfig]:
    """Combine a model with the endpoint it runs on into one wire config.

    The model carries the name and the flags that describe it; the provider carries the
    protocol, the URL and the key (ADR 0014). Without a provider record the model is not
    buildable, but a caller that passes only a model keeps working through the adapter's
    own defaults.
    """
    if not model:
        return None
    protocol = str((provider or {}).get("protocol") or model.get("protocol") or "openai-compatible")
    base_url = str((provider or {}).get("base_url") or "").strip()
    return ProviderConfig(
        provider=canonicalize_provider(protocol),
        model=str(model.get("name") or ""),
        api_key=str((provider or {}).get("api_key") or ""),
        base_url=base_url or None,
        max_input_tokens=int(model.get("max_input_tokens") or 0),
        supports_image_input=bool(model.get("supports_image_input")),
    )


def global_max_steps() -> int:
    """Global ReAct step limit, loaded at startup and editable via the admin API."""
    return state.agent_max_steps or DEFAULT_MAX_STEPS


def resolve_max_steps(request: RunTaskRequest) -> int:
    """Resolve the step limit for one task: explicit override, else global config."""
    if request.max_steps is not None:
        return request.max_steps
    return global_max_steps()


def resolve_permission_mode(request: RunTaskRequest) -> PermissionMode:
    """Resolve the confirmation mode for one task: explicit override, else global."""
    if request.permission_mode:
        return normalize_mode(request.permission_mode)
    return state.permission_mode


def resolve_agents_md_settings() -> AgentsMdSettings:
    """AGENTS.md reading rules for one task: on/off and byte cap, already resolved."""
    return AgentsMdSettings(
        enabled=state.agents_md_enabled,
        max_bytes=state.agents_md_max_bytes,
    )


def resolve_session_base_dir(session_id: str | None) -> str | None:
    """Return the workspace root path bound to a session, if any."""
    if not session_id:
        return None
    session = state.monitor_store.get_session(session_id)
    workspace_id = (session or {}).get("workspace_id")
    if not workspace_id:
        return None
    workspace = state.monitor_store.get_workspace(workspace_id)
    root_path = str((workspace or {}).get("root_path") or "").strip()
    return root_path or None


def checkpoint_store_for_task(trace: dict[str, Any] | None) -> CheckpointStore | None:
    """The undo history a stored task belongs to, or ``None`` when it has none.

    Resolved through the task's session: the session names the workspace, and the
    workspace is the directory the task actually wrote into. The task record itself
    only says which session it ran in (ADR 0020 D2).
    """
    if not trace:
        return None
    task_id = str(trace.get("task_id") or "").strip()
    if not task_id:
        return None
    return CheckpointStore.for_run(resolve_session_base_dir(trace.get("session_id")), task_id)


def agent_runtime_config(agent: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map a stored agent record to the runtime config consumed by the ReAct loop."""
    if not agent:
        return None
    return {
        "agent_id": agent.get("agent_id"),
        "name": agent.get("name"),
        "system_prompt": agent.get("system_prompt") or "",
        "tool_names": agent.get("tool_names"),
        "skills": agent.get("skill_names") or [],
        "mcp_servers": agent.get("mcp_servers") or [],
    }


def resolve_skills_root() -> str:
    """Shared skills root folder: database setting, else env, else the repo ``skills`` folder."""
    stored = state.monitor_store.get_skills_root()
    if stored is not None and stored.strip():
        return stored.strip()
    env_root = os.getenv("SKILLS_ROOT", "").strip()
    if env_root:
        return env_root
    return str(state.ROOT_DIR / "skills")
