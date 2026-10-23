"""Read token usage out of a provider response without knowing the provider.

OpenAI-compatible responses report ``prompt_tokens``/``completion_tokens``; Anthropic
reports ``input_tokens``/``output_tokens``. Both are plain payloads by the time the
loop sees them, so one tolerant reader covers every adapter.
"""

from typing import Any, Mapping


def _read(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _first_count(usage: Any, *keys: str) -> int | None:
    for key in keys:
        raw = _read(usage, key)
        # ``bool`` is an ``int``; a flag is not a token count.
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
    return None


def extract_token_usage(payload: Any) -> dict[str, int]:
    """Map a response's usage block onto ``input_tokens``/``output_tokens``."""
    usage = _read(payload, "usage")
    if usage is None:
        return {}

    usage_names = {
        "input_tokens": ("prompt_tokens", "input_tokens"),
        "output_tokens": ("completion_tokens", "output_tokens"),
    }
    counts: dict[str, int] = {}
    for attribute, keys in usage_names.items():
        value = _first_count(usage, *keys)
        if value is not None:
            counts[attribute] = value
    return counts
