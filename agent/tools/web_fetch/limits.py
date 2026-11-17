"""Bounds for one ``web_fetch`` call.

Every limit here exists to keep a single fetch from taking the loop hostage: an
unreachable host, a server that never finishes its body, or a page far larger than
the model's context all have to end the call with a reportable result instead of a
hang or an enormous tool message.

The numbers are deliberately generous compared with what a text page needs (2 MiB
of markup is roughly a 500 KB article) and deliberately small compared with what a
download tool would allow: this is a reading tool, not a downloader.
"""

from __future__ import annotations

import os

# Total wall clock for one fetch, including redirects and the body read.
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 120.0
TIMEOUT_ENV = "WEB_FETCH_TIMEOUT_SECONDS"

# Connecting to a dead host is the common failure and must not eat the whole budget.
CONNECT_TIMEOUT_SECONDS = 10.0

# Body bytes kept. Beyond this the response is cut and reported as truncated.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

# Same-host hops followed before the tool gives up. Cross-host redirects are
# reported rather than followed (see ``agent/tools/web_fetch/fetch.py``).
MAX_REDIRECTS = 5

# Preview kept in the model's context when the text is persisted instead.
PREVIEW_CHARS = 2000
MIN_PREVIEW_CHARS = 200

# Persisted page text and binary downloads share one prefix.
PERSIST_PREFIX = "fetch-"

# A plain, honest identifier: the tool is an agent, and saying so lets a site
# operator see where the request came from.
USER_AGENT = "ngy-py-agent-web-fetch/0.1"
ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "text/plain;q=0.9,application/json;q=0.8,*/*;q=0.5"
)
ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"


def timeout_seconds() -> float:
    """The per-call timeout, overridable by ``WEB_FETCH_TIMEOUT_SECONDS``."""
    raw = (os.getenv(TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    if value <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return min(value, MAX_TIMEOUT_SECONDS)
