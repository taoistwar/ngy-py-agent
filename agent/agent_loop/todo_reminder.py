"""Nudging the model back to its plan when it stops updating it.

A long run drifts: tool results keep filling the context, and the checklist stops
being edited while the work goes on. After ``EVERY`` consecutive tool rounds that did
not call ``todo_write``, one reminder travels back with the last tool result - the
text the model reads next - and the count restarts.

State lives in one object per run rather than in the loop body, so "three rounds
without a plan update" is expressed once and can be tested without a model.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

TODO_WRITE_TOOL_NAME = "todo_write"

REMINDER_TEXT = "<reminder>Update your todos.</reminder>"

# Three rounds: two is still one short detour (a read, a second read); four is a
# stretch of work the model has already finished without saying so.
EVERY = 3


class TodoReminder:
    """Counts tool rounds that did not update the plan and reports when it is due."""

    def __init__(self, every: int = EVERY) -> None:
        self.every = max(1, int(every))
        self.rounds_since_todo = 0

    def record(self, tool_names: Iterable[str]) -> Optional[str]:
        """Account for one tool round; the reminder text when it is due, else ``None``."""
        names = list(tool_names)
        if TODO_WRITE_TOOL_NAME in names:
            self.rounds_since_todo = 0
            return None
        self.rounds_since_todo += 1
        if self.rounds_since_todo < self.every:
            return None
        # Reset before returning: the next reminder is due three rounds later, not on
        # the very next one.
        self.rounds_since_todo = 0
        return REMINDER_TEXT


def append_to_last_tool_message(
    messages: List[Dict[str, Any]], start: int, text: str
) -> bool:
    """Append ``text`` to the last ``tool`` message at or after ``start``.

    The reminder rides on a tool result instead of becoming a user message: it is
    harness guidance, and a user message would read as the user saying it.
    """
    for index in range(len(messages) - 1, max(-1, start - 1), -1):
        message = messages[index]
        if isinstance(message, dict) and message.get("role") == "tool":
            message["content"] = f"{message.get('content') or ''}\n\n{text}"
            return True
    return False
