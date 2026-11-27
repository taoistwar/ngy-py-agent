"""Errors the ``subagent`` tool reports as a tool result rather than as a crash."""

from __future__ import annotations

from typing import Any, Dict


class SubagentError(Exception):
    """A call the tool refuses before any subagent work starts."""

    def __init__(self, message: str, *, reason: str = "invalid_argument") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {"reason": self.reason, "error": self.message}
