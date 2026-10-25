"""Per-provider request rate limiting, in requests per minute (RPM).

The provider instance is rebuilt for every task (``agent_loop.runtime``,
``task_runtime``), so the budget cannot live on it: it would restart at zero on every
run and two tasks would each think they own the whole minute. It lives here instead,
one bucket per provider name, shared by every thread in the process.

A bucket is a sliding window, not a fixed one: the N-th request of a minute waits
until the oldest of the previous N is 60 seconds old. That is the shape a provider's
own quota has (any 60-second span), and it avoids the burst a fixed window allows at
the boundary.

Waiting is bounded: a request that would have to wait longer than
:data:`DEFAULT_WAIT_CAP_SECONDS` fails instead, because "the limit is 1 RPM and we need
three calls" must read as an error, not as a task that looks hung.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

WINDOW_SECONDS = 60.0
DEFAULT_WAIT_CAP_SECONDS = 60.0

# ``LLM_RPM="openai=60,anthropic=20"``; providers left out are not limited.
RPM_ENV = "LLM_RPM"


class RpmLimitError(RuntimeError):
    """The wait needed to respect the limit is longer than the caller allows."""

    def __init__(
        self,
        provider: str,
        limit: int,
        wait_seconds: float,
        cap_seconds: float,
    ) -> None:
        super().__init__(
            f"Provider '{provider}' allows {limit} requests per minute; the next slot is "
            f"{wait_seconds:.0f}s away, beyond the {cap_seconds:.0f}s wait limit. Raise the "
            "RPM limit (LLM_RPM / Admin -> Rate limit) or retry later."
        )
        self.provider = provider
        self.limit = limit
        self.wait_seconds = wait_seconds
        self.cap_seconds = cap_seconds


def parse_rpm_limits(text: str) -> Dict[str, int]:
    """Read ``"openai=60,anthropic=20"``; malformed pairs are skipped, not fatal."""
    parsed: Dict[str, int] = {}
    for chunk in str(text or "").split(","):
        name, separator, raw = chunk.partition("=")
        if not separator:
            continue
        key = name.strip()
        try:
            value = int(raw.strip())
        except (TypeError, ValueError):
            continue
        if key:
            parsed[key] = value
    return parsed


def _canonical(provider: Any) -> str:
    """The provider name every bucket is keyed by.

    Imported here rather than at module level because ``agent.provider`` imports this
    module for its wire-level hook; resolving the name lazily keeps the dependency
    one-directional without a second spelling table that would drift.
    """
    from agent.provider import canonicalize_provider

    return canonicalize_provider(provider)


def _sanitize(value: Any) -> int:
    """A limit of ``0`` (or anything unusable) means "not limited"."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


class ProviderThrottle:
    """Sliding-window request budget, one bucket per provider."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wait_cap_seconds: float = DEFAULT_WAIT_CAP_SECONDS,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._wait_cap = wait_cap_seconds
        self._lock = threading.Lock()
        self._limits: Dict[str, int] = {}
        self._hits: Dict[str, Deque[float]] = {}
        # Waits are reported per request, so the reading side must not see the wait
        # of some other thread's call.
        self._local = threading.local()

    def configure(self, limits: Optional[Dict[str, Any]]) -> None:
        """Replace the policy. Requests already on record keep counting."""
        normalized: Dict[str, int] = {}
        for provider, value in (limits or {}).items():
            name = _canonical(provider) if str(provider or "").strip() else ""
            if not name:
                continue
            normalized[name] = _sanitize(value)
        with self._lock:
            self._limits = normalized

    def limits(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._limits)

    def limit_for(self, provider: Any) -> int:
        key = _canonical(provider)
        with self._lock:
            return self._limits.get(key, 0)

    def acquire(self, provider: Any) -> float:
        """Block until this provider has room; returns the seconds waited.

        Raises :class:`RpmLimitError` when the wait would exceed the cap, which also
        covers "two tasks need a 1 RPM provider at the same moment".
        """
        key = _canonical(provider)
        with self._lock:
            limit = self._limits.get(key, 0)
        if limit <= 0:
            self._local.last_wait = 0.0
            return 0.0

        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                hits = self._prune(key, now)
                if len(hits) < limit:
                    hits.append(now)
                    self._local.last_wait = waited
                    return waited
                # Oldest request of the window decides when the slot frees up.
                next_slot = hits[0] + WINDOW_SECONDS - now
            wait = max(next_slot, 0.001)
            if waited + wait > self._wait_cap:
                self._local.last_wait = waited
                raise RpmLimitError(key, limit, waited + wait, self._wait_cap)
            self._sleep(wait)
            waited += wait

    def take_last_wait(self) -> float:
        """Seconds this thread waited for its last request, read once."""
        waited = float(getattr(self._local, "last_wait", 0.0) or 0.0)
        self._local.last_wait = 0.0
        return waited

    def _prune(self, key: str, now: float) -> Deque[float]:
        hits = self._hits.setdefault(key, deque())
        cutoff = now - WINDOW_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits


# One budget for the whole process: a task may build its own provider, but the
# provider's minute is shared by every caller (the ReAct loop and the task-naming
# thread both ask the same endpoint).
provider_throttle = ProviderThrottle()
provider_throttle.configure(parse_rpm_limits(os.getenv(RPM_ENV, "")))
