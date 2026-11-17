"""Secret redaction for everything a ``vault_http`` call reports.

The secret leaves the vault exactly once - into the request header - and comes back
in the response, the response headers, an exception message, and the audit event.
Scrubbing therefore runs over all of them, and it matches more than the raw value:

* the raw secret;
* its URL-encoded form (a server may echo it back inside a URL or a form);
* its base64 form, padded and unpadded (that is what ``basic`` auth sends, so the
  header value is the encoding, not the secret);
* its JSON-escaped form (``"`` and ``\\`` inside a JSON document);
* for ``user:password`` secrets, each half on its own, because a server that
  reports "invalid password for user" quotes one half.

Longest variant first, so a base64 form is replaced before its prefix would be
split by the raw value. Replacement is a fixed marker: what the model needs to know
is that a value was removed, not what it was.
"""

from __future__ import annotations

import base64
import json
from typing import Dict, Iterable, Mapping, Tuple
from urllib.parse import quote

REDACTED = "[REDACTED]"

# Variants shorter than this are only scrubbed when they are the secret itself: a
# three-character fragment ("set", "123") would mangle the response without
# protecting anything. The raw secret is always scrubbed, however short.
MIN_FRAGMENT_CHARS = 4

# A header value kept in the result. A server can send a megabyte of cookie; the
# model needs the notable ones, and the token budget must not be spent on headers.
MAX_HEADER_COUNT = 60
MAX_HEADER_CHARS = 1000


def variants_of(secret: str) -> Tuple[str, ...]:
    """Every form of ``secret`` that must not appear in a result, longest first."""
    text = str(secret or "")
    if not text:
        return ()

    found = {text}
    found.add(quote(text, safe=""))
    found.add(quote(text, safe="/"))
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    found.add(encoded)
    found.add(encoded.rstrip("="))
    found.add(quote(encoded, safe=""))
    found.add(json.dumps(text)[1:-1])

    if ":" in text:
        user, _sep, password = text.partition(":")
        for part in (user, password):
            if len(part) >= MIN_FRAGMENT_CHARS:
                found.add(part)

    ordered = [item for item in found if item]
    ordered.sort(key=len, reverse=True)
    return tuple(ordered)


def scrub_text(text: str, variants: Iterable[str]) -> str:
    """Replace every occurrence of every variant in ``text``."""
    result = str(text or "")
    for variant in variants:
        if variant and variant in result:
            result = result.replace(variant, REDACTED)
    return result


def scrub_headers(headers: Mapping[str, str], variants: Iterable[str]) -> Dict[str, str]:
    """Response headers, values scrubbed, count and length bounded.

    Header *names* are kept as sent: they are not attacker-controlled in a way this
    tool can act on, and a renamed header would hide what the server actually said.
    """
    scrubbed: Dict[str, str] = {}
    for index, (name, value) in enumerate(headers.items()):
        if index >= MAX_HEADER_COUNT:
            scrubbed["x-truncated"] = f"{len(headers) - MAX_HEADER_COUNT} more headers not shown"
            break
        text = scrub_text(str(value), variants)
        if len(text) > MAX_HEADER_CHARS:
            text = text[:MAX_HEADER_CHARS] + f"... [{len(text) - MAX_HEADER_CHARS} more characters]"
        scrubbed[str(name)] = text
    return scrubbed
