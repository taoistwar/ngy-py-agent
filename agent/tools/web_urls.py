"""URL rules shared by ``web_fetch`` and the permission gate.

Two places need the same reading of "which URL is this":

* the tool refuses what it cannot fetch (a ``file:`` URL, an address with an
  embedded password, a string that is not a URL at all);
* :class:`~agent.tools.permissions.PermissionBroker` asks the user about the
  *host* before the request leaves the machine, and its rule key has to be the
  same value twice in a row.

Keeping both in one module is deliberate: when the gate and the tool disagree
about the host, the second fetch to an approved site asks again (or worse, a
different site inherits the approval). This module therefore lives at the
package root as shared infrastructure, not inside the tool package.

The rules are intentionally narrow:

* only ``http`` and ``https`` - anything else is a different tool's job;
* no user info in the URL, because it would end up in the result and in the
  event log as a plain-text password;
* the fragment is dropped, since it never reaches the server;
* a host is lowercased and loses its trailing dot, so ``Example.COM.`` and
  ``example.com`` are one permission target.

This is **not** a security boundary: the host is not resolved, so an approved
name may point at an internal address. ``exec_command`` can already reach the
same network, and a fetch tool that pretends to sandbox the network would only
mislead (see ``docs/decisions/0027-web-fetch-tool.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("http", "https")

# A URL longer than this is a bug in the caller, not a page to fetch. Kept well
# under the browser limit so the value still fits in a dialog and an event.
MAX_URL_CHARS = 4096

# Characters that would break the request line or let a value smuggle a second
# header. Spaces are allowed (they are percent-encoded below); these are not.
_FORBIDDEN_CHARS = ("\r", "\n", "\t", "\x00")


class UrlError(ValueError):
    """Raised when a string cannot be used as a fetch target."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> dict:
        return {"error": self.message, "reason": self.reason, **self.details}


@dataclass(frozen=True)
class FetchUrl:
    """A validated, normalized target: what to request and whom to ask about."""

    url: str
    scheme: str
    host: str

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}"


def _netloc(host: str, port: Optional[int], scheme: str) -> str:
    # IPv6 literals keep their brackets in a URL but not in ``hostname``.
    written = f"[{host}]" if ":" in host else host
    if port is None:
        return written
    default = 80 if scheme == "http" else 443
    return written if port == default else f"{written}:{port}"


def parse_url(raw: Any) -> FetchUrl:
    """Validate ``raw`` and return its normalized form, or raise :class:`UrlError`."""
    if not isinstance(raw, str):
        raise UrlError("'url' must be a string.", reason="invalid_argument", argument="url")
    text = raw.strip()
    if not text:
        raise UrlError("'url' must not be empty.", reason="invalid_argument", argument="url")
    if len(text) > MAX_URL_CHARS:
        raise UrlError(
            f"'url' is longer than {MAX_URL_CHARS} characters.",
            reason="invalid_url",
            url_length=len(text),
        )
    for char in _FORBIDDEN_CHARS:
        if char in text:
            raise UrlError(
                "'url' must not contain control characters or line breaks.", reason="invalid_url"
            )
    # Pasted links often carry spaces (a query value, a file name). Encoding them
    # is what a browser would do, so the fetch still means what the caller meant.
    text = text.replace(" ", "%20")

    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise UrlError(f"Cannot parse the URL: {exc}", reason="invalid_url") from exc

    scheme = (parts.scheme or "").lower()
    if not scheme:
        raise UrlError(
            "The URL has no scheme; start it with http:// or https://.", reason="invalid_url"
        )
    if scheme not in ALLOWED_SCHEMES:
        raise UrlError(
            f"Scheme {scheme!r} is not supported; only http and https URLs can be fetched.",
            reason="unsupported_scheme",
            scheme=scheme,
        )
    if parts.username or parts.password:
        raise UrlError(
            "URLs with embedded credentials are refused; a password in the URL would be "
            "echoed back in the result.",
            reason="credentials_in_url",
        )

    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UrlError("The URL has no host.", reason="invalid_url")
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlError(f"Cannot parse the URL port: {exc}", reason="invalid_url") from exc

    url = urlunsplit(
        (scheme, _netloc(host, port, scheme), parts.path or "/", parts.query, "")
    )
    return FetchUrl(url=url, scheme=scheme, host=host)


def host_of(raw: Any) -> Optional[str]:
    """The permission target for ``raw``, or ``None`` when it is not a fetch target.

    Never raises: the gate calls this while deciding whether to ask, and a
    malformed argument is answered by the tool with its own error, not by a
    dialog the user could approve.
    """
    try:
        return parse_url(raw).host
    except UrlError:
        return None


def same_host(left: FetchUrl, right: FetchUrl) -> bool:
    """Whether two targets sit on the same host (the scheme and port may differ).

    ``http://a.com`` -> ``https://a.com`` is the everyday redirect and must be
    followed; ``a.com`` -> ``b.com`` is a different site and must not inherit the
    approval the user gave for the first one.
    """
    return left.host == right.host
