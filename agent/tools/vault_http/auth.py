"""How the secret is attached to the request: the four auth schemes.

A scheme is not a decoration - it decides *where* the secret goes, and the model has
to say which one the endpoint expects. The set is the reference tool's set, because
those four cover every token-authenticated API this agent is likely to call:

* ``bearer`` -> ``Authorization: Bearer <secret>``;
* ``basic`` -> ``Authorization: Basic base64(<secret>)``, where the stored secret is
  ``user:password`` (that is what the wire format encodes);
* ``header_x_api_key`` -> ``X-Api-Key: <secret>``;
* ``custom`` -> ``<auth_header_name>: <secret>``.

Names are validated rather than trusted: a header name with a colon or a newline can
smuggle a second header, and names that describe the message framing (``host``,
``content-length``, ...) must not be overwritten by a credential.
"""

from __future__ import annotations

import base64
import re
from typing import Dict, Optional

SCHEME_BEARER = "bearer"
SCHEME_BASIC = "basic"
SCHEME_X_API_KEY = "header_x_api_key"
SCHEME_CUSTOM = "custom"
AUTH_SCHEMES = (SCHEME_BEARER, SCHEME_BASIC, SCHEME_X_API_KEY, SCHEME_CUSTOM)
DEFAULT_AUTH_SCHEME = SCHEME_BEARER

MAX_HEADER_NAME_CHARS = 64
_HEADER_NAME = re.compile(rf"^[A-Za-z0-9_-]{{1,{MAX_HEADER_NAME_CHARS}}}$")

# Framing headers a credential must never replace: overriding one of these breaks
# the message itself, which shows up as an unexplainable transport error.
_FORBIDDEN_HEADER_NAMES = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "te", "upgrade"}
)

X_API_KEY_HEADER = "X-Api-Key"
AUTHORIZATION_HEADER = "Authorization"


def normalize_scheme(raw: object) -> Optional[str]:
    """The canonical scheme name, or ``None`` when it is not one of the four."""
    text = str(raw or "").strip().lower().replace("-", "_")
    return text if text in AUTH_SCHEMES else None


def valid_header_name(raw: object) -> bool:
    """Whether ``raw`` can be used as a custom header name."""
    if not isinstance(raw, str):
        return False
    text = raw.strip()
    return bool(_HEADER_NAME.match(text)) and text.lower() not in _FORBIDDEN_HEADER_NAMES


def auth_headers(scheme: str, secret: str, header_name: Optional[str] = None) -> Dict[str, str]:
    """The single header that carries ``secret``.

    Callers validate the scheme and the header name first; this function trusts its
    arguments so it can stay a lookup table. ``basic`` encodes the stored
    ``user:password`` pair, which is why the base64 form of the secret is one of the
    variants :mod:`agent.tools.vault_http.scrub` removes from the response.
    """
    if scheme == SCHEME_BEARER:
        return {AUTHORIZATION_HEADER: f"Bearer {secret}"}
    if scheme == SCHEME_BASIC:
        encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        return {AUTHORIZATION_HEADER: f"Basic {encoded}"}
    if scheme == SCHEME_X_API_KEY:
        return {X_API_KEY_HEADER: secret}
    name = (header_name or "").strip()
    if scheme == SCHEME_CUSTOM and name:
        return {name: secret}
    raise ValueError(f"unsupported auth scheme: {scheme!r}")
