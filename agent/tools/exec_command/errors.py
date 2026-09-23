"""The error type ``exec_command`` reports to the model.

Its own module because the runtime, the session helpers and the factory all raise or
catch it, and a type shared across modules does not belong inside one of them.
"""

from typing import Any, Dict


class ExecError(Exception):
    """Raised when the command cannot be started or the arguments are malformed."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}
