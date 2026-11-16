"""Per-endpoint request rate limiting, in requests per minute (RPM).

The budget belongs to an **endpoint**, not to a model and not to a provider name alone:
the canonical provider plus the base URL it actually posts to. Two models served by one
Ollama share one quota (they are one API key on one server), while ``openai`` pointed at
a local gateway and at ``api.openai.com`` are two endpoints with two quotas (ADR 0014).

The bucket cannot live on a provider instance: it is rebuilt for every task
(``agent_loop.runtime``, ``agent.runtime``), so an instance-owned counter would restart
at zero on every run and two tasks would each think they own the whole minute. It lives
here instead, one bucket per endpoint, shared by every thread in the process.

A bucket is a sliding window, not a fixed one: the N-th request of a minute waits until
the oldest of the previous N is 60 seconds old. That is the shape a provider's own quota
has (any 60-second span), and it avoids the burst a fixed window allows at the boundary.

Waiting is bounded: a request that would have to wait longer than
:data:`DEFAULT_WAIT_CAP_SECONDS` fails instead, because "the limit is 1 RPM and we need
three calls" must read as an error, not as a task that looks hung.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Iterable, Mapping, Optional

WINDOW_SECONDS = 60.0
DEFAULT_WAIT_CAP_SECONDS = 60.0

# Ceiling for one endpoint's limit: 6000 RPM is 100 requests per second, already past
# anything a real endpoint answers without throttling us itself.
RPM_LIMIT_MAX = 6000


class RpmLimitError(RuntimeError):
    """The wait needed to respect the limit is longer than the caller allows."""

    def __init__(
        self,
        provider: str,
        base_url: str,
        limit: int,
        wait_seconds: float,
        cap_seconds: float,
    ) -> None:
        endpoint = base_url or "the adapter default endpoint"
        super().__init__(
            f"Provider '{provider}' at {endpoint} allows {limit} requests per minute; the "
            f"next slot is {wait_seconds:.0f}s away, beyond the {cap_seconds:.0f}s wait "
            "limit. Raise the RPM limit (Web Admin -> Providers) or retry later."
        )
        self.provider = provider
        self.base_url = base_url
        self.limit = limit
        self.wait_seconds = wait_seconds
        self.cap_seconds = cap_seconds


def endpoint_identity(provider: Any, base_url: Any = "") -> tuple[str, str]:
    """(canonical provider, normalised URL) - the identity of one request budget.

    Both sides go through the provider module's normalisation, because the adapters
    rewrite what they are given (an OpenAI-compatible URL always ends in ``/v1``): a
    limit stored with the URL an operator typed must still match the URL the adapter
    posts to.
    """
    from agent.provider import canonicalize_provider, normalize_base_url

    name = canonicalize_provider(provider)
    return name, normalize_base_url(name, base_url)


def bucket_key(provider: Any, base_url: Any = "") -> str:
    """The string a limit and a request are matched by."""
    name, url = endpoint_identity(provider, base_url)
    return f"{name}|{url}"


def _sanitize(value: Any) -> int:
    """A limit of ``0`` (or anything unusable) means "not limited"."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


class ProviderThrottle:
    """Sliding-window request budget, one bucket per provider endpoint."""

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

    def configure(self, limits: Optional[Mapping[str, Any]]) -> None:
        """Replace the policy, keyed by :func:`bucket_key`.

        Requests already on record keep counting: a limit is a statement about the
        endpoint, not a reason to hand out a fresh minute.
        """
        normalized: Dict[str, int] = {}
        for key, value in (limits or {}).items():
            name = str(key or "").strip()
            if not name:
                continue
            normalized[name] = _sanitize(value)
        with self._lock:
            self._limits = normalized

    def configure_endpoints(self, endpoints: Iterable[Mapping[str, Any]]) -> None:
        """Configure one bucket per stored endpoint record.

        ``endpoints`` items name the protocol, the base URL and the limit, i.e. the
        shape ``dao.llm`` hands out, so every caller builds the keys the same way.
        """
        limits: Dict[str, int] = {}
        for item in endpoints:
            key = bucket_key(item.get("protocol"), item.get("base_url"))
            limits[key] = _sanitize(item.get("rpm_limit"))
        self.configure(limits)

    def limits(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._limits)

    def limit_for(self, provider: Any, base_url: Any = "") -> int:
        key = bucket_key(provider, base_url)
        with self._lock:
            return self._limits.get(key, 0)

    def acquire(self, provider: Any, base_url: Any = "") -> float:
        """Block until this endpoint has room; returns the seconds waited.

        Raises :class:`RpmLimitError` when the wait would exceed the cap, which also
        covers "two tasks need a 1 RPM endpoint at the same moment".
        """
        name, url = endpoint_identity(provider, base_url)
        key = f"{name}|{url}"
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
                raise RpmLimitError(name, url, limit, waited + wait, self._wait_cap)
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
# endpoint's minute is shared by every caller (the ReAct loop and the task-naming
# thread both ask the same server).
provider_throttle = ProviderThrottle()
