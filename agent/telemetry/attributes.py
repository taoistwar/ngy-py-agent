"""Span attribute hygiene: small values, no secrets, no exceptions.

Traces leave the process, so the same caution the event stream already applies to
screenshots (``redact_image_payload``) applies here to credentials and to anything
that could be megabytes of model context.
"""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry.trace import Span, Status, StatusCode

MAX_ATTRIBUTE_TEXT = 512
REDACTED = "***"

# Segment match, not substring: ``gen_ai.usage.input_tokens`` is a token *count*,
# while ``access_token`` is a credential. Matching substrings would redact both.
SENSITIVE_SEGMENTS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "passwd",
        "password",
        "secret",
        "token",
    }
)
SENSITIVE_COMPOUNDS = ("api_key", "access_key", "private_key", "secret_key")


def is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower())
    segments = {segment for segment in normalized.split("_") if segment}
    if segments & SENSITIVE_SEGMENTS:
        return True
    return any(compound in normalized for compound in SENSITIVE_COMPOUNDS)


def truncate(text: str, limit: int = MAX_ATTRIBUTE_TEXT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def preview_text(value: Any, limit: int = MAX_ATTRIBUTE_TEXT) -> str:
    """A short, printable stand-in for a value that may be huge."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return truncate(text, limit)


def _json_safe_value(value: Any, limit: int) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return truncate(value, limit)
    if isinstance(value, Mapping):
        # Nested mappings are redacted too: a credential can sit one level down.
        return {
            str(key): REDACTED
            if is_sensitive_key(key)
            else _json_safe_value(item, limit)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_json_safe_value(item, limit) for item in value]
    return preview_text(value, limit)


def summarize_arguments(arguments: Any, limit: int = MAX_ATTRIBUTE_TEXT) -> str:
    """Render tool arguments for a span: redacted, truncated, JSON when possible."""
    if arguments is None:
        return ""
    if not isinstance(arguments, Mapping):
        return preview_text(arguments, limit)

    redacted = _json_safe_value(arguments, limit)
    return json.dumps(redacted, ensure_ascii=False, sort_keys=True, default=str)


def safe_attributes(values: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a mapping into values OpenTelemetry accepts, redacting secrets."""
    attributes: dict[str, Any] = {}
    for key, value in values.items():
        name = str(key)
        if value is None:
            continue
        attributes[name] = REDACTED if is_sensitive_key(name) else _json_safe_value(
            value, MAX_ATTRIBUTE_TEXT
        )
    return attributes


def set_error_status(span: Span | None, error: BaseException) -> None:
    """Mark a span as failed without letting telemetry raise on its own."""
    if span is None:
        return
    try:
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, preview_text(error, 256)))
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return
