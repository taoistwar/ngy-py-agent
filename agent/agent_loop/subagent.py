"""Running one delegated sub-task: a nested loop with its own messages.

This is the other half of the ``subagent`` tool. The tool package owns the contract;
this module owns the run - which provider, which tools, and how the timeline hears
about it. It sits in ``agent.agent_loop`` rather than in the tool package because it
needs the provider and the event sink, and a tool is deliberately given neither.

Isolation is messages, not process or workspace: the subagent shares the working
directory, the permission gate, the deny-list and the parent's undo record. Its tool
calls never enter the parent's ``messages``; only the final report does. Delegation is
one level deep - the child registry never contains ``subagent`` itself.

The timeline sees one ``subagent`` event per phase (``started`` / ``tool`` / ``done``
or ``failed``) carrying the brief, each child tool call and the final report. The
child loop's own ``llm_request``/``llm_response`` events are not emitted: they would
double the log for a conversation the parent never reads.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.agent_loop.messages import _with_base_dir
from agent.agent_loop.model_turn import run_model_turn
from agent.agent_loop.runtime import _emit
from agent.models import EventCategory, EventSink, TaskEvent, ToolOutcome
from agent.provider import resolve_tool_provider_for_schemas
from agent.telemetry import current_trace_ids
from agent.tool_registry import ToolRegistry
from agent.tools.catalog import CHILD_EXCLUDED_TOOLS

SUBAGENT_TOOL_NAME = "subagent"
# One delegated task should not be able to spend the parent's whole budget: this is a
# turn budget of its own, not a continuation of the parent's step counter.
DEFAULT_SUBAGENT_MAX_STEPS = 12
# Event payloads are persisted with the task, so a brief that quotes a whole file is
# clipped here. The reader needs "what this was about", not a second copy of it.
EVENT_TEXT_LIMIT = 4000
TITLE_LIMIT = 60

SUBAGENT_SYSTEM_PROMPT = (
    "You are a subagent. You were delegated one self-contained task and you start with "
    "a fresh conversation: the brief from the delegating agent is everything you know "
    "about the work. You have the same tools, workspace and permission checks as that "
    "agent. Work until the task is done, then answer with a short report: the delegating "
    "agent sees only that report, never your tool calls or intermediate notes. You "
    "cannot delegate further (the subagent tool is not available to you). If the brief "
    "is ambiguous, state the assumption you made and proceed instead of asking the user."
)


def make_subagent_runner(
    *,
    registry: Any,
    provider: Any,
    event_sink: EventSink | None,
    task_id: str | None,
    should_stop: Optional[Callable[[], bool]] = None,
    max_steps: int = DEFAULT_SUBAGENT_MAX_STEPS,
    stream: bool = True,
) -> Callable[[str], str]:
    """Build the callable ``ToolBindings.run_subagent`` binds for one run."""

    def run(prompt: str) -> str:
        return _run_subagent(
            prompt,
            registry=registry,
            provider=provider,
            event_sink=event_sink,
            task_id=task_id,
            should_stop=should_stop,
            max_steps=max_steps,
            stream=stream,
        )

    return run


def _run_subagent(
    prompt: str,
    *,
    registry: Any,
    provider: Any,
    event_sink: EventSink | None,
    task_id: str | None,
    should_stop: Optional[Callable[[], bool]],
    max_steps: int,
    stream: bool,
) -> str:
    subagent_id = f"sa-{uuid.uuid4().hex[:8]}"
    started = time.monotonic()
    _emit_phase(
        event_sink,
        task_id,
        subagent_id,
        phase="started",
        title=f"Subagent started: {_first_line(prompt)}",
        data={"prompt": _clip_text(prompt), "max_steps": max_steps},
    )

    child = _build_child_registry(registry)
    schemas = child.get_tool_schemas(
        resolve_tool_provider_for_schemas(getattr(registry, "provider", "") or "openai")
    )
    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": _with_base_dir(
                SUBAGENT_SYSTEM_PROMPT, getattr(registry, "base_dir", None)
            ),
        },
        {"role": "user", "content": prompt},
    ]

    tool_calls = 0
    for step in range(1, max_steps + 1):
        if should_stop is not None and should_stop():
            return _finish(
                event_sink,
                task_id,
                subagent_id,
                phase="failed",
                report="Subagent stopped by user.",
                reason="stopped",
                steps_used=step - 1,
                tool_calls=tool_calls,
                started=started,
            )

        try:
            turn = run_model_turn(
                provider,
                step,
                messages,
                schemas,
                {"tool_choice": "auto"},
                None,
                None,
                stream=stream,
            )
        except Exception as exc:  # noqa: BLE001 - the parent decides whether to retry
            return _finish(
                event_sink,
                task_id,
                subagent_id,
                phase="failed",
                report=f"Error: {exc}",
                reason="model_error",
                steps_used=step,
                tool_calls=tool_calls,
                started=started,
            )

        if not turn.tool_calls:
            return _finish(
                event_sink,
                task_id,
                subagent_id,
                phase="done",
                report=turn.assistant_content or "(no summary)",
                reason="",
                steps_used=step,
                tool_calls=tool_calls,
                started=started,
            )

        for name, arguments, call_id in turn.tool_calls:
            if should_stop is not None and should_stop():
                return _finish(
                    event_sink,
                    task_id,
                    subagent_id,
                    phase="failed",
                    report="Subagent stopped by user.",
                    reason="stopped",
                    steps_used=step,
                    tool_calls=tool_calls,
                    started=started,
                )

            result, is_error = _run_child_call(child, name, arguments)
            tool_calls += 1
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": result,
                }
            )
            _emit_phase(
                event_sink,
                task_id,
                subagent_id,
                phase="tool",
                title=f"Subagent tool: {name}",
                data={
                    "step": step,
                    "name": name,
                    "arguments": _clip(arguments, EVENT_TEXT_LIMIT),
                    "result": _clip_text(result),
                    "is_error": is_error,
                    "tool_calls": tool_calls,
                },
            )

    return _finish(
        event_sink,
        task_id,
        subagent_id,
        phase="failed",
        report=f"Subagent stopped after {max_steps} turns without a final answer.",
        reason="step_limit",
        steps_used=max_steps,
        tool_calls=tool_calls,
        started=started,
    )


def _build_child_registry(parent: Any) -> ToolRegistry:
    """The subagent's registry: the parent's tools minus delegation and the board.

    The brokers and the checkpoint store are shared on purpose. The child runs in the
    same task, so its ``exec_command`` must ask the same user, its writes must land in
    the same undo record, and the deny-list must cover it identically.

    The board tools are left out on purpose (``CHILD_EXCLUDED_TOOLS``): a delegated
    context is thrown away when it returns, so creating, sequencing and claiming tasks
    stays with the parent conversation, which is the one that keeps the plan.
    """
    names = [
        name for name in getattr(parent, "tools", {}) if name not in CHILD_EXCLUDED_TOOLS
    ]
    child = ToolRegistry(
        enabled_tools=names,
        base_dir=getattr(parent, "base_dir", None),
        max_tokens=getattr(parent, "max_tokens", 0),
        provider=getattr(parent, "provider", ""),
        model=getattr(parent, "model", ""),
        session_id=getattr(parent, "session_id", ""),
        task_id=getattr(parent, "task_id", ""),
        should_stop=getattr(parent, "should_stop", None),
        permission_broker=getattr(parent, "permission_broker", None),
        denylist=getattr(parent, "denylist", None),
        user_question_broker=getattr(parent, "user_question_broker", None),
        checkpoint_store=getattr(parent, "checkpoint_store", None),
        # A subagent's plan is its own: sharing the board would let a delegated task
        # replace the plan the parent conversation is working through.
        todo_board=None,
        # The run's background ledger, on the other hand, is shared: the parent loop is
        # the only thing that reports finished commands, so a command the subagent
        # started has to be recorded where that loop will look (ADR 0034).
        background=getattr(parent, "background", None),
    )
    _adopt_dynamic_tools(parent, child, names)
    return child


def _adopt_dynamic_tools(parent: Any, child: ToolRegistry, names: List[str]) -> None:
    """Copy tools the catalog does not know (MCP servers) into the child registry.

    ``ToolRegistry`` only builds built-in tools, so a dynamically registered MCP tool
    would otherwise be visible to the parent and invisible to the subagent.
    """
    for name in names:
        if name in child.tools:
            continue
        entry = parent.tools[name]
        child.register_tool(
            name=name,
            function=entry["function"],
            description=entry["description"],
            parameters=entry["parameters"],
            permission=entry.get("permission"),
            scopes=entry.get("scopes"),
            preview=entry.get("preview"),
            category=entry.get("category"),
            description_i18n=entry.get("description_i18n"),
            always_confirm=entry.get("always_confirm", False),
        )


def _run_child_call(child: ToolRegistry, name: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
    """Run one child tool call; a failure becomes text the child model can read."""
    try:
        outcome = child.execute_tool(name, arguments)
        text = outcome.model_text if isinstance(outcome, ToolOutcome) else str(outcome)
        return text, False
    except Exception as exc:  # noqa: BLE001 - one failed call must not end the subagent
        return f"Error: {exc}", True


def _finish(
    event_sink: EventSink | None,
    task_id: str | None,
    subagent_id: str,
    *,
    phase: str,
    report: str,
    reason: str,
    steps_used: int,
    tool_calls: int,
    started: float,
) -> str:
    data: Dict[str, Any] = {
        "steps_used": steps_used,
        "tool_calls": tool_calls,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "result": _clip_text(report),
    }
    if reason:
        data["reason"] = reason
    _emit_phase(
        event_sink,
        task_id,
        subagent_id,
        phase=phase,
        title="Subagent finished" if phase == "done" else "Subagent failed",
        data=data,
    )
    return report


def _emit_phase(
    event_sink: EventSink | None,
    task_id: str | None,
    subagent_id: str,
    *,
    phase: str,
    title: str,
    data: Dict[str, Any],
) -> None:
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.SUBAGENT,
            title=title,
            data={"subagent_id": subagent_id, "phase": phase, **data, **current_trace_ids()},
            collapsed=True,
        ),
    )


def _clip_text(value: Any, limit: int = EVENT_TEXT_LIMIT) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else f"{text[:limit]}… [truncated]"


def _clip(value: Any, limit: int) -> Any:
    """Clip every string inside a payload, so one big argument cannot bloat the log."""
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}… [truncated]"
    if isinstance(value, dict):
        return {str(key): _clip(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(item, limit) for item in value]
    return value


def _first_line(text: Any, limit: int = TITLE_LIMIT) -> str:
    first = str(text or "").strip().splitlines()
    line = first[0].strip() if first else ""
    if not line:
        return "(empty brief)"
    return line if len(line) <= limit else f"{line[:limit]}…"


__all__ = [
    "DEFAULT_SUBAGENT_MAX_STEPS",
    "SUBAGENT_SYSTEM_PROMPT",
    "SUBAGENT_TOOL_NAME",
    "make_subagent_runner",
]
