"""The error type ``write_stdin`` reports to the model.

Its own module because the rules, the session I/O and the call itself all raise it,
and a type shared across modules does not belong inside one of them.
"""

from typing import Any, Dict


class WriteStdinError(Exception):
    """Raised when the request is malformed or the session cannot be reached."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}
