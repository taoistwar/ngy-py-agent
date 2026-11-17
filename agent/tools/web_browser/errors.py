"""The error type ``web_browser`` reports to the model.

A failure is a *result*, not an exception the loop has to handle: "the site answered
404" and "the host is unreachable" are things the model reads and acts on, and the
UI renders the same fields. The handler turns this type into the ``{"error",
"reason", ...}`` shape the file tools and ``web_fetch`` already use, so a dead link
looks like a missing file to everything upstream.

The reference tool reports a failed navigation as a page whose *title* becomes
``HTTP 404`` or ``Error``. That title is kept - it is what a browser tab would say -
but the failure is still flagged with ``error``/``reason``, because a model that
sees only a title has to guess whether the page loaded.
"""

from __future__ import annotations

from typing import Any, Dict


class WebBrowserError(Exception):
    """Raised when a page cannot be opened."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}
