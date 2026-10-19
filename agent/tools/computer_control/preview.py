"""The confirmation-dialog summary for ``computer_control``.

This runs before the call is allowed, so it must not touch the driver: it only
echoes back the arguments the model supplied, trimmed so a long ``type_text``
does not turn the dialog into a wall of text.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

TEXT_PREVIEW_CHARS = 200
PARAMS_PREVIEW_CHARS = 300

_SIMPLE_KEYS = (
    "pid",
    "window_id",
    "element_token",
    "x",
    "y",
    "from_x",
    "from_y",
    "to_x",
    "to_y",
    "delta_x",
    "delta_y",
    "direction",
    "amount",
    "key",
    "keys",
    "path",
    "name",
    "aumid",
    "urls",
    "width",
    "height",
    "delivery_mode",
)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} characters total]"


def _compact_json(value: Any, limit: int) -> Optional[str]:
    try:
        body = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    return _truncate(body, limit)


def build_preview(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """A side-effect free description of what the pending call will do."""
    action = str(arguments.get("action") or "").strip().lower() or "computer action"
    details: Dict[str, Any] = {"action": action}

    for key in _SIMPLE_KEYS:
        value = arguments.get(key)
        if value is None or value == "":
            continue
        details[key] = value

    text = arguments.get("text")
    if isinstance(text, str) and text:
        details["text"] = _truncate(text, TEXT_PREVIEW_CHARS)

    params = arguments.get("params")
    if isinstance(params, dict) and params:
        compact = _compact_json(params, PARAMS_PREVIEW_CHARS)
        if compact:
            details["params"] = compact

    return details
