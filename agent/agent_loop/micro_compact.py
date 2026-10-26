"""The third compaction step: shrink what the model has already read (ADR 0016).

The first two steps are unconditional and lossless: :mod:`result_budget` caps one
step's results by size, :mod:`snip_compact` caps the message count. This one runs only
when the estimated conversation is over the context limit, and it deals in the
currency the first two do not touch - results the model has already been shown and
that are still sitting in full.

Two rules decide what may be shortened:

- **Unread results are untouchable.** The newest batch has not been sent yet, so the
  model has not had a chance to use it. Removing it before it is seen means acting on
  history the model never received.
- **The most recent consumed results stay whole.** They are the ones the current work
  is built on; older ones are the ones it can afford to look up again.

Everything removed is written to disk first. The first two steps are pure text
surgery; this one must stay recoverable, and it does: every placeholder is an absolute
path that ``read_file`` can open.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.agent_loop.runtime import _emit
from agent.models import EventCategory, EventSink, TaskEvent
from agent.telemetry import current_trace_ids
from agent.tools.output_store import (
    ensure_result_directory,
    persist_text,
    persisted_note,
    result_file_name,
    workspace_result_directory,
)

# Whole-conversation budget, in characters. A model attribute first: when the model
# config states its input window, that wins over any default here.
CONTEXT_LIMIT_ENV = "CONTEXT_CHAR_LIMIT"
DEFAULT_CONTEXT_CHAR_LIMIT = 200_000
CHARS_PER_TOKEN = 4

# Shorten until the estimate is back to this fraction of the limit, not just under it:
# stopping at the line means the very next step is over it again.
TARGET_RATIO = 0.8

# The newest consumed results carry the work in progress.
KEEP_RECENT_RESULTS = 3

# Below this a result is already noise; replacing it with a path saves nothing.
MIN_SHRINK_CHARS = 120

# Unread results are only ever fitted with a preview - the model has not seen them, so
# a path alone would ask it to fetch something whose shape it cannot guess.
FIT_PREVIEW_CHARS = 1_000

# A screenshot is a data URL of megabytes but costs the model a fixed, small number
# of tokens. Counting its base64 length would put every vision session permanently
# over the limit, and no amount of text surgery could bring it back.
IMAGE_CHAR_COST = 1_600

# Already a pointer: shortening it again would point at a pointer.
PERSISTED_PREFIX = "<persisted-output>"

# Role, keys, separators: the parts of a message the text does not cover. Without it,
# a hundred empty tool messages would estimate at zero.
MESSAGE_OVERHEAD = 20


def resolve_context_limit(
    configured: Optional[int] = None,
    model_max_input_tokens: int = 0,
) -> int:
    """The whole-conversation budget; ``<= 0`` disables the step.

    Order: explicit argument, ``CONTEXT_CHAR_LIMIT``, the model's own input window,
    the default. The window belongs to the model, so when it is configured it beats a
    constant that would silently make the model use a fraction of itself.
    """
    if configured is not None:
        return max(0, int(configured))
    raw = (os.getenv(CONTEXT_LIMIT_ENV) or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    try:
        tokens = int(model_max_input_tokens or 0)
    except (TypeError, ValueError):
        tokens = 0
    if tokens > 0:
        return tokens * CHARS_PER_TOKEN
    return DEFAULT_CONTEXT_CHAR_LIMIT


def estimate_chars(messages: List[Dict[str, Any]]) -> int:
    """Approximate what the conversation costs, in characters.

    Not ``len(json.dumps(messages))``: that would count a screenshot at its base64
    length (megabytes for something the model charges a fixed price for) and would
    also re-serialise everything on each replacement. Walking the structure is just as
    faithful for text and lets images carry their own price.
    """
    return sum(_message_chars(message) for message in messages)


def mark_seen(seen: Set[str], messages: List[Dict[str, Any]]) -> None:
    """Record which tool results just went out in a request.

    By ``tool_call_id`` rather than position: :mod:`snip_compact` rewrites the list, so
    an index recorded earlier stops meaning the same message.
    """
    for message in messages:
        if message.get("role") != "tool":
            continue
        call_id = message.get("tool_call_id")
        if call_id:
            seen.add(str(call_id))


def prepare_context(
    messages: List[Dict[str, Any]],
    seen: Set[str],
    base_dir: Optional[str] = None,
    event_sink: EventSink | None = None,
    task_id: str | None = None,
    step: int = 0,
    context_limit: Optional[int] = None,
    model_max_input_tokens: int = 0,
) -> Dict[str, Any]:
    """Run the conditional half of the pipeline and report what happened.

    Shortening first, fitting second: consumed results are the cheaper thing to give
    up (the model has already used them), so they are spent before touching a result
    that has not been seen. Only one debug event per call - one per step is already
    the resolution an operator needs.
    """
    limit = resolve_context_limit(context_limit, model_max_input_tokens)
    summary: Dict[str, Any] = {
        "step": step,
        "context_limit": limit,
        "before_chars": 0,
        "after_chars": 0,
        "micro": _empty_step_summary(),
        "fit": _empty_step_summary(),
        "still_over": False,
        "reason": "",
    }
    if limit <= 0:
        summary["reason"] = "context limit disabled"
        return summary

    before = estimate_chars(messages)
    summary["before_chars"] = before
    summary["after_chars"] = before
    if before <= limit:
        summary["reason"] = "under the limit"
        return summary

    target = int(limit * TARGET_RATIO)
    summary["micro"] = apply_micro_compact(
        messages,
        seen,
        target,
        base_dir=base_dir,
        event_sink=event_sink,
        task_id=task_id,
        step=step,
    )
    if estimate_chars(messages) > limit:
        summary["fit"] = fit_tool_results(
            messages,
            seen,
            target,
            base_dir=base_dir,
            event_sink=event_sink,
            task_id=task_id,
            step=step,
        )

    summary["after_chars"] = estimate_chars(messages)
    summary["still_over"] = summary["after_chars"] > limit
    summary["reason"] = "still over the limit" if summary["still_over"] else "compacted"
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.DEBUG,
            title=f"micro_compact Step {step}",
            data={
                "step": step,
                "context_limit": limit,
                "target_chars": target,
                "before_chars": summary["before_chars"],
                "after_chars": summary["after_chars"],
                "micro_replaced": len(summary["micro"]["replaced"]),
                "fit_replaced": len(summary["fit"]["replaced"]),
                "failed": len(summary["micro"]["failed"]) + len(summary["fit"]["failed"]),
                "still_over": summary["still_over"],
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )
    return summary


def apply_micro_compact(
    messages: List[Dict[str, Any]],
    seen: Set[str],
    target_chars: int,
    base_dir: Optional[str] = None,
    event_sink: EventSink | None = None,
    task_id: str | None = None,
    step: int = 0,
) -> Dict[str, Any]:
    """Replace the oldest consumed results with their path, until back under target."""
    summary = _empty_step_summary(target_chars)
    total = estimate_chars(messages)
    summary["before_chars"] = total

    candidates = _consumed_positions(messages, seen)[:-KEEP_RECENT_RESULTS]
    for _index, block in candidates:
        if total <= target_chars:
            break
        content = str(block.get("content") or "")
        if len(content) <= MIN_SHRINK_CHARS:
            continue
        if content.startswith(PERSISTED_PREFIX):
            continue
        try:
            path = _persist_result(base_dir, block, content)
        except OSError as exc:
            _record_failure(summary, block, exc)
            continue
        placeholder = f"[Earlier tool result saved at {path.as_posix()}]"
        if len(placeholder) >= len(content):
            continue
        total += len(placeholder) - len(content)
        block["content"] = placeholder
        summary["replaced"].append(
            {
                "tool_call_id": block.get("tool_call_id"),
                "chars": len(content),
                "path": path.as_posix(),
            }
        )

    summary["after_chars"] = total
    _report_failures(summary, event_sink, task_id, step, "micro_compact")
    return summary


def fit_tool_results(
    messages: List[Dict[str, Any]],
    seen: Set[str],
    target_chars: int,
    base_dir: Optional[str] = None,
    event_sink: EventSink | None = None,
    task_id: str | None = None,
    step: int = 0,
) -> Dict[str, Any]:
    """Persist the largest *unread* results, leaving a preview and a path.

    This is the case where the batch that just arrived would not fit on its own.
    Without it the model would have to give up history before it ever saw what the
    tools just returned - which is the wrong thing to forget, and the reason the
    preview is kept: it has not read this yet.
    """
    summary = _empty_step_summary(target_chars)
    total = estimate_chars(messages)
    summary["before_chars"] = total

    candidates = [
        (index, message)
        for index, message in enumerate(messages)
        if _is_tool_result(message) and not _is_seen(message, seen)
    ]
    candidates.sort(key=lambda pair: len(str(pair[1].get("content") or "")), reverse=True)

    for _index, block in candidates:
        if total <= target_chars:
            break
        content = str(block.get("content") or "")
        if len(content) <= MIN_SHRINK_CHARS:
            continue
        if content.startswith(PERSISTED_PREFIX):
            continue
        stored = content.replace("\x00", "\ufffd")
        path = workspace_result_directory(base_dir) / result_file_name(block.get("tool_call_id"))
        note = persisted_note(path, stored, FIT_PREVIEW_CHARS)
        if len(note) >= len(content):
            continue
        try:
            path = _persist_result(base_dir, block, stored)
        except OSError as exc:
            _record_failure(summary, block, exc)
            continue
        total += len(note) - len(content)
        block["content"] = note
        summary["replaced"].append(
            {
                "tool_call_id": block.get("tool_call_id"),
                "chars": len(content),
                "path": path.as_posix(),
            }
        )

    summary["after_chars"] = total
    _report_failures(summary, event_sink, task_id, step, "fit_tool_results")
    return summary


def _empty_step_summary(target_chars: int = 0) -> Dict[str, Any]:
    return {
        "target_chars": target_chars,
        "before_chars": 0,
        "after_chars": 0,
        "replaced": [],
        "failed": [],
    }


def _consumed_positions(
    messages: List[Dict[str, Any]],
    seen: Set[str],
) -> List[Tuple[int, Dict[str, Any]]]:
    return [
        (index, message)
        for index, message in enumerate(messages)
        if _is_tool_result(message) and _is_seen(message, seen)
    ]


def _is_tool_result(message: Dict[str, Any]) -> bool:
    return message.get("role") == "tool"


def _is_seen(message: Dict[str, Any], seen: Set[str]) -> bool:
    call_id = message.get("tool_call_id")
    return bool(call_id) and str(call_id) in seen


def _persist_result(
    base_dir: Optional[str],
    block: Dict[str, Any],
    content: str,
) -> Path:
    """Write the result out and return its path, reusing one that already exists.

    The file name comes from the tool call id (ADR 0012), so a result the size budget
    already persisted is found again instead of being written twice under a second
    path the model would then have to choose between.
    """
    directory = workspace_result_directory(base_dir)
    path = directory / result_file_name(block.get("tool_call_id"))
    if path.exists():
        return path
    ensure_result_directory(directory)
    return persist_text(directory, path.name, content.replace("\x00", "\ufffd"))


def _record_failure(summary: Dict[str, Any], block: Dict[str, Any], exc: OSError) -> None:
    summary["failed"].append(
        {
            "tool_call_id": block.get("tool_call_id"),
            "name": block.get("name"),
            "error": str(exc),
        }
    )


def _report_failures(
    summary: Dict[str, Any],
    event_sink: EventSink | None,
    task_id: str | None,
    step: int,
    title: str,
) -> None:
    if not summary["failed"]:
        return
    problems = [
        f"{item.get('tool_call_id')}: {item.get('error')}" for item in summary["failed"]
    ]
    _emit(
        event_sink,
        task_id,
        TaskEvent(
            task_id=task_id or "",
            category=EventCategory.ERROR,
            title=f"{title} could not persist {len(problems)} result(s) Step {step}",
            data={
                "step": step,
                "count": len(problems),
                "problems": problems[:10],
                "action": "kept the full content in the context",
                **current_trace_ids(),
            },
            collapsed=True,
        ),
    )


def _message_chars(message: Any) -> int:
    if not isinstance(message, dict):
        return len(str(message))
    total = MESSAGE_OVERHEAD
    total += _content_chars(message.get("content"))
    for entry in message.get("tool_calls") or []:
        total += _arguments_chars(entry)
    return total


def _content_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                total += IMAGE_CHAR_COST
            elif isinstance(part, dict):
                total += len(str(part.get("text") or ""))
            else:
                total += len(str(part))
        return total
    return len(str(content or ""))


def _arguments_chars(entry: Any) -> int:
    if not isinstance(entry, dict):
        return len(str(entry))
    function = entry.get("function")
    arguments = function.get("arguments") if isinstance(function, dict) else None
    if isinstance(arguments, str):
        return len(arguments)
    return len(json.dumps(entry, default=str, ensure_ascii=False))
