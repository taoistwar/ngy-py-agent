"""The error type ``web_search`` reports to the model.

A search that cannot be served is a *result*, not an exception the loop has to
handle: "no API key is configured" and "the provider answered 429" are things the
model must read and act on, and the UI needs their fields to render the failure.
The handler converts this type with :meth:`WebSearchError.to_dict`, and the
registry then serializes that dict like any other tool result.

Argument validation goes through the same shape, so a mistyped ``num_results``
and an unreachable provider look alike to the caller (``reason`` is what differs).
"""

from __future__ import annotations

from typing import Any, Dict


class WebSearchError(Exception):
    """Raised when a search cannot be served."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}
