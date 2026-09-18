"""Three step token budget check for tool output.

Counting tokens exactly is expensive, so the check is staged:

1. **Byte lower bound** - a token never covers more than
   :data:`~agent.tools.tokenizers.MAX_BYTES_PER_TOKEN` bytes, so
   ``bytes > max_tokens * 4`` cannot fit no matter how it is tokenized. Reject
   without touching a tokenizer.
2. **Byte upper bound** - a byte never expands into more than
   :data:`~agent.tools.tokenizers.MAX_TOKENS_PER_BYTE` tokens, so
   ``bytes * 4 <= max_tokens`` always fits. Accept without a tokenizer.
3. **Exact count** - only for the ambiguous middle band, ask the offline
   tokenizer (see :class:`~agent.tools.tokenizers.TokenCounter`).
"""

import os
from dataclasses import dataclass

from agent.tools.tokenizers import (
    MAX_BYTES_PER_TOKEN,
    MAX_TOKENS_PER_BYTE,
    TokenCounter,
    estimate_tokens,
)

# Budget applied when neither the caller nor the model config sets one.
DEFAULT_MAX_TOKENS = 25000

# Optional override for the default budget.
MAX_TOKENS_ENV = "TOOL_OUTPUT_MAX_TOKENS"

REASON_TOO_LARGE = "too_large"
REASON_EXACT_EXCEEDED = "exact_exceeded"
REASON_WITHIN_BOUNDS = "within_bounds"
REASON_WITHIN_BYTE_BOUND = "within_byte_bound"


@dataclass(frozen=True)
class TokenCheck:
    """Outcome of a budget check."""

    ok: bool
    tokens: int
    max_tokens: int
    exact: bool
    backend: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tokens": self.tokens,
            "max_tokens": self.max_tokens,
            "exact": self.exact,
            "backend": self.backend,
            "reason": self.reason,
        }


def _env_default() -> int:
    try:
        value = int((os.getenv(MAX_TOKENS_ENV) or "").strip())
    except (TypeError, ValueError):
        return DEFAULT_MAX_TOKENS
    return value if value > 0 else DEFAULT_MAX_TOKENS


def resolve_max_tokens(configured: int = 0) -> int:
    """Resolve the output budget, falling back to :data:`DEFAULT_MAX_TOKENS`."""
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else _env_default()


def check_text(
    text: str,
    max_tokens: int,
    provider: str = "",
    model: str = "",
    counter: TokenCounter | None = None,
) -> TokenCheck:
    """Check whether ``text`` fits into ``max_tokens``."""
    budget = resolve_max_tokens(max_tokens)
    size = len(text.encode("utf-8"))

    # Step 1: even the most compact tokenization exceeds the budget.
    if size > budget * MAX_BYTES_PER_TOKEN:
        return TokenCheck(
            ok=False,
            tokens=max(1, size // MAX_BYTES_PER_TOKEN),
            max_tokens=budget,
            exact=False,
            backend="byte-bound",
            reason=REASON_TOO_LARGE,
        )

    # Step 2: even the most pessimistic tokenization stays inside the budget.
    if size * MAX_TOKENS_PER_BYTE <= budget:
        return TokenCheck(
            ok=True,
            tokens=estimate_tokens(text),
            max_tokens=budget,
            exact=False,
            backend="byte-bound",
            reason=REASON_WITHIN_BYTE_BOUND,
        )

    # Step 3: ambiguous middle band, count for real.
    token_counter = counter or TokenCounter(provider=provider, model=model)
    tokens = token_counter.count(text)
    return TokenCheck(
        ok=tokens <= budget,
        tokens=tokens,
        max_tokens=budget,
        exact=True,
        backend=token_counter.backend,
        reason=REASON_WITHIN_BOUNDS if tokens <= budget else REASON_EXACT_EXCEEDED,
    )
