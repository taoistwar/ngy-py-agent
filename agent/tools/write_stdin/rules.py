"""The waiting and budget rules behind ``write_stdin``.

Defaults and ranges follow the reference design (ADR 0008): a poll waits longer than
a write, because a poll is waiting for the program to speak while a write is waiting
for its own responsiveness.
"""

from __future__ import annotations

from typing import Any

from agent.tools.token_budget import resolve_max_tokens
from agent.tools.write_stdin.errors import WriteStdinError

DEFAULT_YIELD_MS = 250
POLL_MIN_YIELD_MS = 5_000
POLL_MAX_YIELD_MS = 300_000
WRITE_MAX_YIELD_MS = 30_000
DEFAULT_MAX_OUTPUT_TOKENS = 10_000

# A write of exactly this byte means "interrupt", not "input".
CTRL_C = "\u0003"

# How often the wait loop checks for new output or an exited process.
POLL_INTERVAL_SECONDS = 0.05


def as_chars(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WriteStdinError(
            "'chars' must be a string.", reason="invalid_argument", argument="chars"
        )
    return value


def effective_yield_ms(value: Any, is_write: bool) -> int:
    """Clamp the wait so a poll is patient and a write stays responsive."""
    if value is None:
        raw = DEFAULT_YIELD_MS
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WriteStdinError(
                "'yield_time_ms' must be a number of milliseconds.",
                reason="invalid_argument",
                argument="yield_time_ms",
            )
        raw = int(value)
    if is_write:
        return max(0, min(raw, WRITE_MAX_YIELD_MS))
    return max(POLL_MIN_YIELD_MS, min(raw, POLL_MAX_YIELD_MS))


def output_budget(requested: Any, configured: int) -> int:
    """Resolve the output budget, capped by the run's own budget."""
    if requested is None:
        want = DEFAULT_MAX_OUTPUT_TOKENS
    else:
        if isinstance(requested, bool) or not isinstance(requested, (int, float)):
            raise WriteStdinError(
                "'max_output_tokens' must be a positive number.",
                reason="invalid_argument",
                argument="max_output_tokens",
            )
        want = int(requested)
    if want < 1:
        raise WriteStdinError(
            "'max_output_tokens' must be at least 1.",
            reason="invalid_argument",
            argument="max_output_tokens",
        )
    # A larger request can be pulled back by the run's configured budget.
    return max(1, min(want, resolve_max_tokens(configured)))
