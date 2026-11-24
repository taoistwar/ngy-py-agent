"""Bounds and settings for one ``web_search`` call.

Two kinds of numbers live here, and they are here for different reasons:

* **Limits** keep a single search from taking the loop hostage: a provider that
  never answers, a response far larger than a result list, or a model asking for
  ten thousand hits all have to end the call with a reportable result.
* **Settings** are the knobs an operator turns without touching code: which
  backend to search, its key, and the endpoint override used by a gateway or by
  the tests.

Everything is read when a call runs, not when the module is imported, so a
``.env`` loaded at startup (or a test that patches the environment) takes effect
immediately. Invalid values fall back to the default instead of crashing a tool
call, and numeric values are clamped: a tool that refuses to run because a typo
set ``WEB_SEARCH_TIMEOUT_SECONDS=abc`` is worse than one that uses 15 seconds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Which backend answers. The default needs no key so the tool works out of the
# box; an API provider is opt-in with ``WEB_SEARCH_API_KEY``.
PROVIDER_ENV = "WEB_SEARCH_PROVIDER"
DEFAULT_PROVIDER = "duckduckgo"

API_KEY_ENV = "WEB_SEARCH_API_KEY"

# Replaces the chosen provider's endpoint outright (a corporate gateway, or a
# throwaway server in the tests). Empty means "the provider's own endpoint".
BASE_URL_ENV = "WEB_SEARCH_BASE_URL"

# Total wall clock for one search, including the response read.
TIMEOUT_ENV = "WEB_SEARCH_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TIMEOUT_SECONDS = 60.0

# Connecting to a dead endpoint is the common failure and must not eat the budget.
CONNECT_TIMEOUT_SECONDS = 8.0

# How many hits a call returns when the model does not say, and the hard cap.
NUM_RESULTS_ENV = "WEB_SEARCH_DEFAULT_NUM_RESULTS"
DEFAULT_NUM_RESULTS = 8
MAX_NUM_RESULTS = 20

# Characters of the rendered result list handed to the model.
DEFAULT_CONTEXT_MAX_CHARACTERS = 10000
MIN_CONTEXT_MAX_CHARACTERS = 500
MAX_CONTEXT_MAX_CHARACTERS = 50000

# A one-character query is a keystroke, not a question.
MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 1000

# Per-field caps, so one pathological page title cannot fill the result list.
MAX_TITLE_CHARS = 200
MAX_SNIPPET_CHARS = 500

# Provider responses are small; this only stops a misconfigured endpoint from
# streaming something enormous into memory.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

# Preview kept in the model's context when the rendered list is persisted.
PREVIEW_CHARS = 2000
MIN_PREVIEW_CHARS = 200

PERSIST_PREFIX = "search-"

# A plain, honest identifier: the tool is an agent, and saying so lets a provider
# operator see where the request came from.
USER_AGENT = "ngy-py-agent-web-search/0.1"


def _positive_float(raw: str, default: float, maximum: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def _positive_int(raw: str, default: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def timeout_seconds() -> float:
    """The per-call timeout, overridable by ``WEB_SEARCH_TIMEOUT_SECONDS``."""
    return _positive_float(
        (os.getenv(TIMEOUT_ENV) or "").strip(),
        DEFAULT_TIMEOUT_SECONDS,
        MAX_TIMEOUT_SECONDS,
    )


def default_num_results() -> int:
    """Hits returned when the model omits ``num_results``."""
    return _positive_int(
        (os.getenv(NUM_RESULTS_ENV) or "").strip(),
        DEFAULT_NUM_RESULTS,
        MAX_NUM_RESULTS,
    )


@dataclass(frozen=True)
class BackendSettings:
    """Where ``web_search`` goes: one backend, its key and its endpoint override."""

    provider: str
    api_key: str
    base_url: str


def env_backend() -> BackendSettings:
    """The backend described by the environment, or the keyless default."""
    return BackendSettings(
        provider=(os.getenv(PROVIDER_ENV) or "").strip() or DEFAULT_PROVIDER,
        api_key=(os.getenv(API_KEY_ENV) or "").strip(),
        base_url=(os.getenv(BASE_URL_ENV) or "").strip(),
    )


# The admin page's saved row, applied by the API at startup and on every write.
# A module-level value rather than a database read per call keeps the tool layer
# free of ``dao`` imports; a search takes one snapshot so a save that lands
# mid-call cannot mix the old provider with the new key.
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
    """The backend one search should use: the saved row, else the environment."""
    configured = _runtime
    if configured is not None:
        return configured
    return env_backend()


def provider_name() -> str:
    """The configured backend name, or the keyless default."""
    return backend().provider


def api_key() -> str:
    """The configured API key; empty for providers that need none."""
    return backend().api_key


def base_url() -> str:
    """The endpoint override, or empty to use the provider's own endpoint."""
    return backend().base_url
