"""The ``vault_http`` call, validated before anything leaves the machine.

The schema is closed: the accepted names are exactly the eight in
:mod:`agent.tools.vault_http.description`, and anything else is refused with
``unknown_argument`` instead of being dropped. A silently ignored argument is how a
credential ends up in the wrong place - ``auth_header`` misspelled would fall back to
a bare ``Bearer`` header and look like an authentication failure at the server.

Validation order follows the damage each argument can do: the URL first (a non-HTTPS
target never happens), then the key name, then the reason, then the request shape.
Every refusal is a :class:`~agent.tools.vault_http.errors.VaultHttpError` carrying a
reason code, so the model can fix the call without guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agent.tools.vault_http.auth import (
    AUTH_SCHEMES,
    DEFAULT_AUTH_SCHEME,
    SCHEME_CUSTOM,
    normalize_scheme,
    valid_header_name,
)
from agent.tools.vault_http.errors import VaultHttpError
from agent.tools.web_urls import FetchUrl, UrlError, parse_url

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
DEFAULT_METHOD = "GET"
# A body on GET is forbidden by HTTP: servers may ignore it or reject the message,
# and either way the payload silently did not arrive.
BODY_METHODS = ("POST", "PUT", "PATCH", "DELETE")

DEFAULT_BODY_CONTENT_TYPE = "application/json"
MAX_BODY_CONTENT_TYPE_CHARS = 128
MAX_KEY_CHARS = 128
MAX_REASON_CHARS = 500

REQUIRED_ARGUMENTS = ("url", "vault_auth_key", "reason")
OPTIONAL_ARGUMENTS = (
    "method",
    "auth_scheme",
    "auth_header_name",
    "body",
    "body_content_type",
)
ACCEPTED_ARGUMENTS = REQUIRED_ARGUMENTS + OPTIONAL_ARGUMENTS

# A vault key is a name, not a phrase: the store is keyed by it and the permission
# rule embeds it, so whitespace and punctuation that would need quoting are refused.
_KEY_NAME = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# Control characters would break a request line or a header value.
_FORBIDDEN_CHARS = ("\r", "\n", "\t", "\x00")


@dataclass(frozen=True)
class VaultCall:
    """One validated call: what to request, with which secret, and why."""

    target: FetchUrl
    method: str
    vault_auth_key: str
    reason: str
    auth_scheme: str
    auth_header_name: Optional[str]
    body: Optional[str]
    body_content_type: str


def _text(raw: Any, name: str) -> str:
    if not isinstance(raw, str):
        raise VaultHttpError(
            f"'{name}' must be a string.", reason="invalid_argument", argument=name
        )
    return raw


def _clean(raw: Any, name: str, limit: int) -> str:
    text = _text(raw, name).strip()
    for char in _FORBIDDEN_CHARS:
        if char in text:
            raise VaultHttpError(
                f"'{name}' must not contain control characters or line breaks.",
                reason="invalid_argument",
                argument=name,
            )
    if not text:
        raise VaultHttpError(f"'{name}' must not be empty.", reason="invalid_argument", argument=name)
    if len(text) > limit:
        raise VaultHttpError(
            f"'{name}' is longer than {limit} characters.",
            reason="invalid_argument",
            argument=name,
            max_chars=limit,
        )
    return text


def _reject_unknown(raw: Dict[str, Any]) -> None:
    unknown = sorted(set(raw) - set(ACCEPTED_ARGUMENTS))
    if unknown:
        raise VaultHttpError(
            "Unsupported argument(s): " + ", ".join(unknown) + ". Accepted arguments are "
            + ", ".join(ACCEPTED_ARGUMENTS) + ".",
            reason="unknown_argument",
            unknown_arguments=unknown,
        )


def _target(raw: Any) -> FetchUrl:
    text = _text(raw, "url")
    try:
        target = parse_url(text)
    except UrlError as exc:
        raise VaultHttpError(exc.message, exc.reason, **exc.details) from None
    if target.scheme != "https":
        # The whole tool exists to put a secret on a request; plaintext would put it
        # on every hop in between. Refused before anything is read from the vault.
        raise VaultHttpError(
            "Only https:// URLs are allowed: a vault key must never be sent over "
            f"plaintext HTTP (got {target.scheme}://).",
            reason="https_required",
            scheme=target.scheme,
            url=target.url,
        )
    return target


def _method(raw: Any) -> str:
    if raw is None or raw == "":
        return DEFAULT_METHOD
    text = str(raw).strip().upper()
    if text not in METHODS:
        raise VaultHttpError(
            f"Unsupported method {raw!r}; use one of " + ", ".join(METHODS) + ".",
            reason="invalid_argument",
            argument="method",
            allowed_methods=list(METHODS),
        )
    return text


def _scheme_and_header(raw_scheme: Any, raw_header: Any) -> tuple[str, Optional[str]]:
    if raw_scheme is None or raw_scheme == "":
        scheme = DEFAULT_AUTH_SCHEME
    else:
        scheme = normalize_scheme(raw_scheme)
        if scheme is None:
            raise VaultHttpError(
                f"Unsupported auth_scheme {raw_scheme!r}; use one of " + ", ".join(AUTH_SCHEMES) + ".",
                reason="invalid_argument",
                argument="auth_scheme",
                allowed_auth_schemes=list(AUTH_SCHEMES),
            )

    if scheme != SCHEME_CUSTOM:
        if raw_header not in (None, ""):
            raise VaultHttpError(
                "auth_header_name is only used with auth_scheme=custom; drop it or set "
                "auth_scheme=custom.",
                reason="invalid_argument",
                argument="auth_header_name",
            )
        return scheme, None

    if raw_header in (None, ""):
        raise VaultHttpError(
            "auth_scheme=custom needs auth_header_name (the header that carries the key).",
            reason="missing_argument",
            argument="auth_header_name",
        )
    if not valid_header_name(raw_header):
        raise VaultHttpError(
            "auth_header_name must be 1-64 letters, digits, '_' or '-' and must not be a "
            "message-framing header such as host or content-length.",
            reason="invalid_argument",
            argument="auth_header_name",
        )
    return scheme, str(raw_header).strip()


def _body(raw_body: Any, raw_content_type: Any, method: str) -> tuple[Optional[str], str]:
    content_type = DEFAULT_BODY_CONTENT_TYPE
    if raw_content_type not in (None, ""):
        content_type = _clean(raw_content_type, "body_content_type", MAX_BODY_CONTENT_TYPE_CHARS)

    if raw_body in (None, ""):
        return None, content_type

    body = _text(raw_body, "body")
    if method not in BODY_METHODS:
        raise VaultHttpError(
            f"A {method} request cannot carry a body; use one of " + ", ".join(BODY_METHODS) + ".",
            reason="body_not_allowed",
            method=method,
            body_methods=list(BODY_METHODS),
        )
    return body, content_type


def parse_call(raw: Dict[str, Any]) -> VaultCall:
    """Validate raw tool arguments into a :class:`VaultCall`."""
    _reject_unknown(raw)

    missing = [name for name in REQUIRED_ARGUMENTS if raw.get(name) in (None, "")]
    if missing:
        raise VaultHttpError(
            "Missing required argument(s): " + ", ".join(missing) + ".",
            reason="missing_argument",
            missing_arguments=missing,
        )

    target = _target(raw.get("url"))
    key = _clean(raw.get("vault_auth_key"), "vault_auth_key", MAX_KEY_CHARS)
    if not _KEY_NAME.match(key):
        raise VaultHttpError(
            "vault_auth_key must be 1-128 letters, digits, '.', '_', ':' or '-'.",
            reason="invalid_argument",
            argument="vault_auth_key",
        )
    reason = _clean(raw.get("reason"), "reason", MAX_REASON_CHARS)
    method = _method(raw.get("method"))
    scheme, header_name = _scheme_and_header(raw.get("auth_scheme"), raw.get("auth_header_name"))
    body, content_type = _body(raw.get("body"), raw.get("body_content_type"), method)

    return VaultCall(
        target=target,
        method=method,
        vault_auth_key=key,
        reason=reason,
        auth_scheme=scheme,
        auth_header_name=header_name,
        body=body,
        body_content_type=content_type,
    )
