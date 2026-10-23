"""Tool catalog routes: what the agent can call, and which agents may call it.

The tool management page reads this. The registry is the source of truth for
names, parameter schemas and permission kinds; the agent configurations in the
store say who may use a tool. Joining them here keeps the page a pure renderer
instead of a second place that knows how ``tool_names`` is interpreted.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

import app_state
from agent.tools.registry import ToolRegistry
from api_schemas import ToolItemResponse, ToolListResponse

router = APIRouter()


def _agent_uses(agent: Dict[str, Any], tool_name: str) -> bool:
    """Whether this agent's configuration includes ``tool_name``.

    ``tool_names`` is ``None`` for "every registered tool" and an explicit list
    otherwise; an empty list therefore means "no tools" and must not fall through
    to the "all tools" branch.
    """
    tool_names = agent.get("tool_names")
    if tool_names is None:
        return True
    return tool_name in tool_names


def _agent_ids_by_tool(
    agents: List[Dict[str, Any]], tool_names: List[str]
) -> Dict[str, List[str]]:
    """Map each tool name to the ids of the agents that enable it."""
    return {
        name: [
            str(agent.get("agent_id", ""))
            for agent in agents
            if _agent_uses(agent, name)
        ]
        for name in tool_names
    }


@router.get("/api/tools", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """Every registered tool with its schema, permission gate and agents."""
    described = ToolRegistry().describe_tools()
    agents = app_state.monitor_store.list_agents()
    used_by = _agent_ids_by_tool(agents, [item["name"] for item in described])
    return ToolListResponse(
        tools=[
            ToolItemResponse(**item, agent_ids=used_by.get(item["name"], []))
            for item in described
        ]
    )
