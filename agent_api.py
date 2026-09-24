"""Agent configuration: modes, agents, and the shared skills library.

An agent is the prompt + tool set + skills a task runs with, so these routes are the
editing surface for what ``agent/modes.py`` and the skills folder provide.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

import app_state
from agent import skills as skill_library
from agent.modes import (
    DEFAULT_MODE,
    MODE_CONFIGS,
    SKILLS,
    VALID_MODES,
    list_available_skills,
    list_available_tools,
)
from api_schemas import (
    AgentItemResponse,
    AgentListResponse,
    AgentUpdateRequest,
    AgentUpsertRequest,
    SkillImportRequest,
    SkillsRootUpdateRequest,
)
from mcp_store import MCP_TRANSPORTS
from task_runtime import resolve_skills_root

router = APIRouter()


@router.get("/api/modes")
async def list_modes() -> dict[str, Any]:
    """List available agent modes with their prompt/tool/skill configuration."""
    modes = []
    for name in VALID_MODES:
        config = MODE_CONFIGS[name]
        modes.append(
            {
                "mode": name,
                "label": config.get("label", name),
                "description": config.get("description", ""),
                "is_default": name == DEFAULT_MODE,
                "tool_names": config.get("tool_names"),
                "skills": [
                    {"name": skill, "label": SKILLS.get(skill, {}).get("label", skill)}
                    for skill in config.get("skills", [])
                    if skill in SKILLS
                ],
            }
        )
    return {"modes": modes, "default_mode": DEFAULT_MODE}


@router.get("/api/agents", response_model=AgentListResponse)
async def list_agents() -> AgentListResponse:
    agents = app_state.monitor_store.list_agents()
    return AgentListResponse(agents=[AgentItemResponse(**item) for item in agents])


@router.get("/api/agents/meta")
async def get_agent_meta() -> dict[str, Any]:
    """Available tools, skills and MCP transports used to build agents.

    ``skills`` are the built-in registry skills injected into the system prompt;
    ``library_skills`` are the folders of the shared skills root, listed in the
    agent editor for reference but not yet injected at runtime.
    """
    return {
        "tools": list_available_tools(),
        "skills": list_available_skills(),
        "library_skills": skill_library.list_skills(resolve_skills_root()),
        "mcp_transports": list(MCP_TRANSPORTS),
    }


@router.post("/api/agents", response_model=AgentItemResponse)
async def create_agent(payload: AgentUpsertRequest) -> AgentItemResponse:
    created = app_state.monitor_store.create_agent(payload.model_dump())
    return AgentItemResponse(**created)


@router.put("/api/agents/{agent_id}", response_model=AgentItemResponse)
async def update_agent(agent_id: str, payload: AgentUpdateRequest) -> AgentItemResponse:
    updated = app_state.monitor_store.update_agent(agent_id, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return AgentItemResponse(**updated)


@router.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, Any]:
    agent = app_state.monitor_store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    if agent.get("is_builtin"):
        raise HTTPException(status_code=400, detail="Built-in agents cannot be deleted.")
    if not app_state.monitor_store.delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found.")
    return {"agent_id": agent_id, "deleted": True}


# ----------------------------------------------------------------------- skills


@router.get("/api/skills")
async def list_skills() -> dict[str, Any]:
    """List skills stored under the shared root folder."""
    root = resolve_skills_root()
    return {"skills_root": root, "skills": skill_library.list_skills(root)}


@router.get("/api/admin/skills-root")
async def get_skills_root() -> dict[str, Any]:
    stored = app_state.monitor_store.get_skills_root()
    return {
        "skills_root": resolve_skills_root(),
        "skills_root_source": "database" if stored and stored.strip() else "env",
    }


@router.put("/api/admin/skills-root")
async def update_skills_root(payload: SkillsRootUpdateRequest) -> dict[str, Any]:
    app_state.monitor_store.set_skills_root(payload.skills_root.strip())
    return {"skills_root": resolve_skills_root()}


@router.post("/api/skills/import")
async def import_skill(payload: SkillImportRequest) -> dict[str, Any]:
    root = resolve_skills_root()
    try:
        return skill_library.import_skill(root, payload.source_path.strip())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/skills/{name}")
async def delete_skill(name: str) -> dict[str, Any]:
    if not skill_library.delete_skill(resolve_skills_root(), name):
        raise HTTPException(status_code=404, detail="Skill not found.")
    return {"name": name, "deleted": True}
