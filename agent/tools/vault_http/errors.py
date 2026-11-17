"""The one exception ``vault_http`` raises internally.

It carries a machine-readable ``reason`` and nothing that could be a secret: the
tool catches it and returns :meth:`to_dict` as the tool result, which is the same
``{"error", "reason", ...}`` shape the file tools use. A raised tool exception would
mark the step as failed in the loop and teach the model that the tool is broken; a
returned error is a result it can act on instead.
"""

from __future__ import annotations

from typing import Any, Dict


class VaultHttpError(Exception):
    """A refused or failed call, with a reason the model can act on."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}

    def scrubbed(self, scrub) -> "VaultHttpError":
        """A copy with ``scrub`` applied to the message and every detail value.

        Used on transport errors and anything else that may echo a header back: the
        secret is in the request by the time a connection fails, and a ``requests``
        message routinely quotes what it was asked to send.
        """
        details = {
            key: (scrub(value) if isinstance(value, str) else value)
            for key, value in self.details.items()
        }
        return VaultHttpError(scrub(self.message), self.reason, **details)
