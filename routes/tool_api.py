"""Tool catalog routes: what the agent can call, and who may call it.

The tool management page reads this. The registry is the source of truth for
names, parameter schemas and permission kinds; the agent configurations in the
store say who may use a tool. Joining them here keeps the page a pure renderer
instead of a second place that knows how ``tool_names`` is interpreted.

The page can also run one tool with hand-written arguments (``/test``). That is
the only route in this app that executes a tool outside a task, so its contract is
stated at the route itself.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException

from agent.models import ToolOutcome
from agent.tools.registry import ToolRegistry
from commons import state
from commons.schemas import ToolItemResponse, ToolListResponse, ToolTestRequest, ToolTestResponse

router = APIRouter()

# Display cap for a test result. A tool can legitimately return a lot (a whole
# file, a long command log); the dialog is a viewer, not a transcript.
MAX_RESULT_CHARS = 20000


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
    agents = state.monitor_store.list_agents()
    used_by = _agent_ids_by_tool(agents, [item["name"] for item in described])
    return ToolListResponse(
        tools=[
            ToolItemResponse(**item, agent_ids=used_by.get(item["name"], []))
            for item in described
        ]
    )


def _split_outcome(outcome: Any) -> Tuple[str, str]:
    """Turn a tool result into the text and the UI payload a test can show.

    ``ToolOutcome`` carries the model-facing text and a structured ``details``
    payload; every other result is already the string the model would receive.
    ``details`` is rendered as JSON text so one display cap covers both.
    """
    if isinstance(outcome, ToolOutcome):
        details = outcome.details or {}
        return outcome.model_text, json.dumps(details, ensure_ascii=False, indent=2, default=str)
    return str(outcome), ""


def _clip(text: str) -> Tuple[str, bool]:
    """Cap display text so a huge result cannot freeze the dialog."""
    if len(text) <= MAX_RESULT_CHARS:
        return text, False
    return f"{text[:MAX_RESULT_CHARS]}\n... ({len(text) - MAX_RESULT_CHARS} more characters)", True


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _run_tool(registry: ToolRegistry, tool_name: str, arguments: Dict[str, Any]) -> ToolTestResponse:
    """Execute one tool and package the outcome, exceptions included."""
    started = time.perf_counter()
    try:
        outcome = registry.execute_tool(tool_name, dict(arguments))
    except Exception as exc:  # noqa: BLE001 - a failing tool is the test result
        error, _ = _clip(f"{exc.__class__.__name__}: {exc}")
        return ToolTestResponse(
            tool=tool_name,
            ok=False,
            error=error,
            duration_ms=_elapsed_ms(started),
        )

    raw_result, raw_details = _split_outcome(outcome)
    result, result_clipped = _clip(raw_result)
    details, details_clipped = _clip(raw_details)
    return ToolTestResponse(
        tool=tool_name,
        ok=True,
        result=result,
        details=details,
        truncated=result_clipped or details_clipped,
        duration_ms=_elapsed_ms(started),
    )


@router.post("/api/tools/{tool_name}/test", response_model=ToolTestResponse)
def test_tool(tool_name: str, payload: ToolTestRequest) -> ToolTestResponse:
    """Run a tool once with the given arguments and report what came back.

    Two things this route is **not**:

    * It is not a task. There is no ``task_id``, no event stream, and therefore no
      permission broker to ask, so a gated tool runs directly. The page warns
      before testing one; do not reuse this route as a general execution API.
    * A tool that raises is not a server error. The exception is the answer the
      caller wants, so it comes back as ``ok=false`` with the message intact.
    """
    registry = ToolRegistry()
    if tool_name not in registry.tools:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    return _run_tool(registry, tool_name, payload.arguments)
