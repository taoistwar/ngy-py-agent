"""The error type ``grep`` reports to the model.

Its own module because :mod:`~agent.tools.grep.tool` raises it, and a type shared
across modules does not belong inside one of them (see ``AGENTS.md``).
"""

from typing import Any, Dict


class GrepError(Exception):
    """Raised when a search request cannot be served."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, **self.details}
