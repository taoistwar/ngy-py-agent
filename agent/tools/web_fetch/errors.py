"""The error type ``web_fetch`` reports to the model.

A fetch failure is a *result*, not an exception the loop has to handle: the model
needs to read "the host refused the connection" the same way it reads a page, and
the UI needs the fields to render it. The handler converts this type with
:meth:`WebFetchError.to_dict` and the registry then serializes that dict like any
other tool result.

URL validation failures are reported through the same shape, so a bad argument and
a dead server look alike to the caller (``reason`` is what differs).
"""

from __future__ import annotations

from typing import Any, Dict


class WebFetchError(Exception):
    """Raised when a fetch cannot be served."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}
