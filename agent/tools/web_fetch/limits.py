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
from dataclasses import dataclass
from typing import Optional

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

# Which implementation reads the page. ``builtin`` is this process's own request
# plus HTML conversion, so a fresh checkout works without credentials;
# ``deepseek`` sends the URL to DeepSeek's Fetch API and gets Markdown back.
DEFAULT_PROVIDER = "builtin"
PROVIDER_ENV = "WEB_FETCH_PROVIDER"
API_KEY_ENV = "WEB_FETCH_API_KEY"
BASE_URL_ENV = "WEB_FETCH_BASE_URL"


@dataclass(frozen=True)
class BackendSettings:
    """Which fetcher answers, with its key and endpoint override."""

    provider: str
    api_key: str
    base_url: str


def env_backend() -> BackendSettings:
    """The backend described by the environment, or the local fetcher."""
    return BackendSettings(
        provider=(os.getenv(PROVIDER_ENV) or "").strip() or DEFAULT_PROVIDER,
        api_key=(os.getenv(API_KEY_ENV) or "").strip(),
        base_url=(os.getenv(BASE_URL_ENV) or "").strip(),
    )


# The admin page's saved row, applied at startup and on every write. A snapshot is
# returned so a save that lands mid-call cannot mix a new provider with an old key.
_runtime: Optional[BackendSettings] = None


def configure(backend: BackendSettings) -> None:
    """Install the saved backend for this process; called by the admin API."""
    global _runtime
    _runtime = backend


def reset() -> None:
    """Drop the saved backend and fall back to the environment (tests, reloads)."""
    global _runtime
    _runtime = None


def backend() -> BackendSettings:
    """The backend one fetch should use: the saved row, else the environment."""
    configured = _runtime
    if configured is not None:
        return configured
    return env_backend()


def provider_name() -> str:
    """The configured backend name, or the local fetcher."""
    return backend().provider


def api_key() -> str:
    """The configured API key; empty for the local fetcher."""
    return backend().api_key


def base_url() -> str:
    """The endpoint override, or empty to use the provider's own endpoint."""
    return backend().base_url


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
