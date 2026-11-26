"""The plan a conversation already had, put in front of a new task's prompt.

A plan outlives the task that wrote it, so a follow-up task starts knowing where the
work stands instead of rebuilding the list from the transcript or, worse, replacing a
half-finished checklist with a fresh one. The block is only added when there is a
plan: an empty list means the previous task left nothing to continue.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.tools.todo_write import render_todos

# Says what the list is for, not only what it contains: without the second sentence
# the model reads a leftover checklist as part of the request.
_TODO_SECTION = (
    "\n\n## Plan left by an earlier task\n"
    "This conversation already has a plan; it is what the user sees as the current progress. "
    "Continue it instead of starting over: update the statuses with ``todo_write`` (sending "
    "the complete list), keep the items that still apply, and ignore the rest.\n"
)


def append_todo_context(system_prompt: str, todos: List[Dict[str, Any]]) -> str:
    """Append the conversation's plan to ``system_prompt`` (a no-op when empty)."""
    items = [item for item in todos if isinstance(item, dict)]
    if not items:
        return system_prompt
    return f"{system_prompt}{_TODO_SECTION}\n{render_todos(items)}"
