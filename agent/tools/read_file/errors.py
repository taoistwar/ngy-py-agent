"""The error type ``read_file`` reports to the model.

Its own module because both :mod:`~agent.tools.read_file.tool` and
:mod:`~agent.tools.read_file.lines` raise it, and a type shared across modules
does not belong inside one of them (see ``AGENTS.md``).
"""

from typing import Any, Dict


class ReadFileError(Exception):
    """Raised when a read request cannot be served."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, **self.details}
