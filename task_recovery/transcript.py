"""Turn a task's event log back into a conversation a new process can continue.

The log is the only thing that survives a crash, so the resume decision is made
entirely from it (no in-memory state, no thread). Two rules shape the result:

* **A recorded result is reused verbatim.** The tool is not called again, so an
  edit that already landed does not land twice.
* **A call without a recorded result is never executed again.** The model is told
  the call was interrupted and that its outcome is unknown, and it decides what to
  verify before doing anything - the one safe reading of a tool call whose side
  effects are unknowable from here.

The conversation itself comes from the model request that was last sent. That
request is the exact list the provider saw, so a task that was compacted, given
history, or fed screenshots resumes from the state it actually reached.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from agent.agent_loop.config import DEFAULT_MAX_STEPS
from agent.models import TaskStatus

# Categories and titles are the only stable contract with the loop, so they are
# spelled once here instead of being repeated at every comparison.
_CATEGORY_LLM_REQUEST = "llm_request"
_CATEGORY_LLM_RESPONSE = "llm_response"
_CATEGORY_TOOL_RESULT = "tool_result"
_CATEGORY_DEBUG = "debug"
_CATEGORY_ERROR = "error"

_TITLE_STARTING = "Starting ReAct loop"
_TITLE_START_TASK = "Start task execution"

# Event titles that already carry the task's own conclusion. Finding one means the
# work is over and only the row was left behind, so resuming would redo it.
_TERMINAL_SUCCESS_TITLES = (
    "Task finished",
    "ReAct finished",
    "ReAct run completed",
)
_TERMINAL_FAILED_TITLES = ("Task failed",)
_TERMINAL_STOPPED_TITLES = ("Task stopped", "ReAct stopped")
_TERMINAL_LIMIT_TITLES = ("Reached maximum step limit",)

# What the loop returns when it runs out of steps; kept identical so a resumed
# task that has already spent its budget ends the way the original would have.
MAX_STEPS_RESULT = "Reached maximum reasoning steps without a final answer."

INTERRUPTED_TOOL_NOTE = (
    "[recovery] The process restarted before this tool call recorded a result, so "
    "whether it took effect is unknown. Do not repeat it blindly: inspect the current "
    "state first, and run it again only if the inspection shows it did not happen."
)

# Adapters that rewrite ``messages`` into their own wire shape; a raw request from
# them cannot be fed back to the loop as a chat transcript.
_REWRITING_PROVIDER_PREFIXES = ("anthropic", "gemini")


class ResumeMode(str, Enum):
    """What a restarted process should do with an unfinished task."""

    # Nothing had been asked of the model yet: run the task from the beginning.
    RESTART = "restart"
    # Continue from the rebuilt conversation and the step it stopped in.
    CONTINUE = "continue"
    # The task already reached a conclusion; only the record needs settling.
    SETTLE = "settle"


@dataclass(frozen=True)
class ResumePlan:
    """The recovery decision for one task, derived from its events alone."""

    mode: ResumeMode
    messages: list[dict[str, Any]] = field(default_factory=list)
    next_step: int = 1
    max_steps: int = DEFAULT_MAX_STEPS
    # Tool results taken from the log instead of being produced again.
    reused_results: int = 0
    # Tool calls whose outcome the log cannot prove; the model is told so.
    unresolved_calls: int = 0
    status: TaskStatus | None = None
    result: str = ""
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        """The plan as the event log records it (never the whole conversation)."""
        return {
            "mode": self.mode.value,
            "next_step": self.next_step,
            "max_steps": self.max_steps,
            "reused_tool_results": self.reused_results,
            "unresolved_tool_calls": self.unresolved_calls,
            "reason": self.reason,
        }


def build_resume_plan(
    events: Iterable[dict[str, Any]] | None,
    query: str,
    default_max_steps: int = DEFAULT_MAX_STEPS,
    provider: str | None = None,
) -> ResumePlan | None:
    """Decide how to continue a task from its event log.

    ``None`` means the log cannot be turned back into a conversation - a task from
    before the log carried its starting point, or one written by an adapter that
    reshapes messages. The caller has to settle such a task instead of guessing.
    """
    ordered = list(events or [])
    terminal = _terminal_plan(ordered)
    if terminal is not None:
        return terminal

    requests = [event for event in ordered if _category(event) == _CATEGORY_LLM_REQUEST]
    max_steps = _max_steps(ordered, default_max_steps)
    if not requests:
        # The task died before its first model call: nothing was executed, so
        # starting over repeats no work.
        return ResumePlan(
            mode=ResumeMode.RESTART,
            max_steps=max_steps,
            reason="no model request was recorded",
        )

    baseline = _baseline(ordered, requests[-1], provider)
    if baseline is None:
        return None
    messages, baseline_step = baseline

    replay = _replay(
        ordered,
        messages,
        baseline_step,
        _tool_results(ordered),
    )
    if replay is None:
        return None
    messages, consumed_step, reused, unresolved, answered = replay

    if answered is not None:
        # The model had already produced its final answer; the run died before the
        # closing event was written. Settling is the whole recovery.
        return ResumePlan(
            mode=ResumeMode.SETTLE,
            status=TaskStatus.SUCCESS,
            result=answered,
            reused_results=reused,
            reason="the model answered before the restart",
        )

    next_step = consumed_step + 1
    if next_step > max_steps:
        return ResumePlan(
            mode=ResumeMode.SETTLE,
            status=TaskStatus.SUCCESS,
            result=MAX_STEPS_RESULT,
            reused_results=reused,
            unresolved_calls=unresolved,
            reason="the task had already spent its step budget",
        )

    return ResumePlan(
        mode=ResumeMode.CONTINUE,
        messages=messages,
        next_step=next_step,
        max_steps=max_steps,
        reused_results=reused,
        unresolved_calls=unresolved,
        reason=f"continue from the request of step {baseline_step}",
    )


# --------------------------------------------------------------------- terminal


def _terminal_plan(events: list[dict[str, Any]]) -> ResumePlan | None:
    """The plan for a task whose log already ends with a conclusion, if it does."""
    for event in reversed(events):
        title = str(event.get("title") or "")
        data = _data(event)
        if title in _TERMINAL_SUCCESS_TITLES:
            return ResumePlan(
                mode=ResumeMode.SETTLE,
                status=TaskStatus.SUCCESS,
                result=str(data.get("result") or ""),
                reason=f"already concluded by '{title}'",
            )
        if title in _TERMINAL_FAILED_TITLES:
            return ResumePlan(
                mode=ResumeMode.SETTLE,
                status=TaskStatus.FAILED,
                result=str(data.get("result") or ""),
                reason=f"already concluded by '{title}'",
            )
        if title in _TERMINAL_STOPPED_TITLES:
            return ResumePlan(
                mode=ResumeMode.SETTLE,
                status=TaskStatus.STOPPED,
                result=str(data.get("result") or ""),
                reason=f"already concluded by '{title}'",
            )
        if title in _TERMINAL_LIMIT_TITLES:
            return ResumePlan(
                mode=ResumeMode.SETTLE,
                status=TaskStatus.SUCCESS,
                result=MAX_STEPS_RESULT,
                reason="the task had already spent its step budget",
            )
        if _category(event) == _CATEGORY_ERROR and title == "Task recovery gave up":
            return ResumePlan(
                mode=ResumeMode.SETTLE,
                status=TaskStatus.FAILED,
                result=str(data.get("result") or ""),
                reason="recovery was already abandoned",
            )
    return None


# --------------------------------------------------------------------- baseline


def _baseline(
    events: list[dict[str, Any]],
    last_request: dict[str, Any],
    provider: str | None,
) -> tuple[list[dict[str, Any]], int] | None:
    """The conversation as it stood when the last request went out, and its step.

    A request already contains every earlier turn *and* whatever compaction did to
    them, so replaying from it is both exact and cheap. The starting point recorded
    by the loop is the fallback: it is one full copy from step one, which is what
    adapters with their own wire format leave behind.
    """
    data = _data(last_request)
    raw_request = data.get("raw_request")
    # The event's own provider is the adapter that actually shaped the request; the
    # task row is only a fallback because it can be rewritten after the fact.
    if _is_chat_transcript_provider(data.get("provider") or provider):
        if isinstance(raw_request, dict):
            messages = raw_request.get("messages")
            if isinstance(messages, list) and messages:
                return copy.deepcopy(messages), _step(last_request) or 1

    for event in events:
        if _category(event) != _CATEGORY_DEBUG:
            continue
        if str(event.get("title") or "") != _TITLE_STARTING:
            continue
        starting_messages = _data(event).get("initial_messages")
        if isinstance(starting_messages, list) and starting_messages:
            return copy.deepcopy(starting_messages), 1
    return None


def _is_chat_transcript_provider(provider: str | None) -> bool:
    name = str(provider or "").strip().lower()
    return not any(name.startswith(prefix) for prefix in _REWRITING_PROVIDER_PREFIXES)


# ----------------------------------------------------------------------- replay


def _replay(
    events: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    baseline_step: int,
    tool_results: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, int, str | None] | None:
    """Append what happened after ``baseline_step`` to ``messages``.

    Returns the messages, the last step fully applied, how many results came from
    the log, how many calls are unresolved, and the final answer when the model had
    already given one. ``None`` means an answer could not be read from the log.
    """
    reused = 0
    unresolved = 0
    consumed_step = baseline_step - 1

    for response in events:
        if _category(response) != _CATEGORY_LLM_RESPONSE:
            continue
        step = _step(response)
        if step < baseline_step:
            continue
        assistant = _assistant_message(response)
        if assistant is None:
            return None
        messages.append(assistant)
        consumed_step = step

        calls = _calls_of(assistant, step)
        if not calls:
            return messages, consumed_step, reused, unresolved, _content_of(response)

        for call_id, name in calls:
            recorded = tool_results.get(call_id)
            if recorded is not None:
                messages.append(_tool_message(call_id, name, str(recorded.get("result") or "")))
                reused += 1
                continue
            messages.append(_tool_message(call_id, name, INTERRUPTED_TOOL_NOTE))
            unresolved += 1

    return messages, consumed_step, reused, unresolved, None


def _assistant_message(response: dict[str, Any]) -> dict[str, Any] | None:
    """The chat-style assistant turn recorded with a response event."""
    raw = _data(response).get("raw_response")
    if not isinstance(raw, dict):
        return None
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    # Reasoning is an artefact of how the turn was produced, never part of the
    # conversation the next turn continues from.
    cleaned = {key: value for key, value in message.items() if key != "reasoning_content"}
    cleaned["role"] = str(cleaned.get("role") or "assistant")
    if cleaned.get("content") is None:
        cleaned["content"] = ""
    return cleaned


def _calls_of(assistant: dict[str, Any], step: int) -> list[tuple[str, str]]:
    """``(call_id, name)`` for each tool call, giving ids to the ones without one.

    A tool message refers back to its call by id, so a recovered message needs an id
    even when the provider omitted it: the value is written onto the assistant turn
    as well, otherwise the pair would not line up.
    """
    raw_calls = assistant.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []

    calls: list[tuple[str, str]] = []
    for index, call in enumerate(raw_calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        name = str((function or {}).get("name") or "")
        if not name:
            continue
        call_id = str(call.get("id") or "")
        if not call_id:
            call_id = f"recovered-{step}-{index}"
            call["id"] = call_id
            call["type"] = str(call.get("type") or "function")
        calls.append((call_id, name))
    return calls


def _tool_message(call_id: str, name: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def _tool_results(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recorded tool results by call id, so an executed call is never executed twice."""
    results: dict[str, dict[str, Any]] = {}
    for event in events:
        if _category(event) != _CATEGORY_TOOL_RESULT:
            continue
        data = _data(event)
        call_id = str(data.get("tool_call_id") or "")
        if call_id:
            results[call_id] = data
    return results


# ---------------------------------------------------------------------- reading


def _data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _category(event: dict[str, Any]) -> str:
    value = event.get("category")
    category = getattr(value, "value", value)
    return str(category or "").strip().lower()


def _step(event: dict[str, Any]) -> int:
    try:
        return int(_data(event).get("step") or 0)
    except (TypeError, ValueError):
        return 0


def _content_of(response: dict[str, Any]) -> str:
    content = _data(response).get("content")
    return str(content or "")


def _max_steps(events: list[dict[str, Any]], default: int) -> int:
    """The step budget the task was started with, as its own events recorded it."""
    budget = default
    for event in events:
        title = str(event.get("title") or "")
        if title not in (_TITLE_STARTING, _TITLE_START_TASK):
            continue
        value = _data(event).get("max_steps")
        if isinstance(value, int) and value > 0:
            budget = value
    return budget


__all__ = [
    "INTERRUPTED_TOOL_NOTE",
    "MAX_STEPS_RESULT",
    "ResumeMode",
    "ResumePlan",
    "build_resume_plan",
]
