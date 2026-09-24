"""The error type ``ask_user_question`` reports to the model.

Same shape as the other tools' errors: a message for the model plus a machine-readable
``reason`` and whatever details explain it, so a rejected call is a result it can act on
rather than an exception that fails the step.
"""

from typing import Any, Dict


class AskUserQuestionError(Exception):
    """Raised when the questions cannot be shown to anyone."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}
