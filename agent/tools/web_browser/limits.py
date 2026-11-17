"""Bounds for one ``web_browser`` call.

The numbers are the reference tool's, plus the two that this project always adds:

* **5 redirects**, same host only - a hop to another site is a different permission
  target and is reported instead of followed (ADR 0027 D3);
* **2 MiB of body**, cut while reading, because a server that streams forever must
  end the call with a report rather than with a full memory;
* **50,000 characters of page text**, which is the reference tool's cap and the
  point where ``[truncated]`` appears - the model is told the view is partial
  instead of being handed a silently shortened page;
* **the output token budget** (``TOOL_OUTPUT_MAX_TOKENS``), which may persist the
  text to a file even below the character cap.

The user agent is the project's own name, not a browser's: ``web_fetch`` already
decided against pretending to be Chrome (ADR 0027), and a site operator reading the
logs should see who actually came.
"""

from __future__ import annotations

import os

# Total wall clock for one navigation, including redirects and the body read.
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 120.0
TIMEOUT_ENV = "WEB_BROWSER_TIMEOUT_SECONDS"

# Connecting to a dead host is the common failure and must not eat the whole budget.
CONNECT_TIMEOUT_SECONDS = 10.0

# Body bytes kept. Beyond this the response is cut and reported as truncated.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

# Same-host hops followed before the tool gives up.
MAX_REDIRECTS = 5

# The reference tool's character cap for ``content``.
MAX_CONTENT_CHARS = 50_000
TRUNCATION_MARKER = "[truncated]"

# Preview kept in the model's context when the text is persisted instead.
PREVIEW_CHARS = 2000
MIN_PREVIEW_CHARS = 200

PERSIST_PREFIX = "browse-"

USER_AGENT = "ngy-py-agent-web-browser/0.1"
ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "text/plain;q=0.9,application/json;q=0.8,*/*;q=0.5"
)
ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"

# ``navigate`` opens the page; ``screenshot`` is the reference tool's second value,
# kept because it is part of that contract - it cannot capture pixels, and the
# result says so instead of pretending.
ACTION_NAVIGATE = "navigate"
ACTION_SCREENSHOT = "screenshot"
ACTIONS = (ACTION_NAVIGATE, ACTION_SCREENSHOT)
DEFAULT_ACTION = ACTION_NAVIGATE


def timeout_seconds() -> float:
    """The per-call timeout, overridable by ``WEB_BROWSER_TIMEOUT_SECONDS``."""
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
