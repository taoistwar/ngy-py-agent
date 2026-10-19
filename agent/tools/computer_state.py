"""Turn a driver snapshot into text a model can actually read.

A window accessibility tree is large: every control, its name, value, bounds and
the element token the next action needs. Sending it verbatim would burn the
context in one step, so the tree is rendered as one line per node and then put
through the same output budget the shell tool uses (see
``agent/tools/token_budget.py``). When it still does not fit, the full tree is
written next to the run's scratch output and the model gets a preview plus the
path, exactly like oversized command output (``agent/tools/output_store.py``).

The node shape is not pinned down by the driver documentation, so the reader is
deliberately tolerant: it accepts the common key spellings for role, name,
token, value, bounds and children, and falls back to JSON when it recognises
nothing. Being wrong here costs readability, not correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.tools import output_store, token_budget

# A tree can hold thousands of nodes; the model needs the controls it can act
# on, not every decorative panel.
MAX_STATE_NODES = 400
MAX_DEPTH = 12
MAX_NAME_CHARS = 80
MAX_VALUE_CHARS = 120
MAX_ITEM_CHARS = 120

_ROLE_KEYS = ("role", "control_type", "controlType", "type", "class_name", "class")
_NAME_KEYS = ("name", "title", "label", "automation_id", "automationId")
_TOKEN_KEYS = ("element_token", "elementToken", "token")
_VALUE_KEYS = ("value", "text")
_BOUNDS_KEYS = ("bounds", "frame", "rect", "rectangle")
_CHILDREN_KEYS = ("children", "nodes", "elements", "items")

_ITEM_KEYS = (
    "pid",
    "name",
    "title",
    "app",
    "window_id",
    "id",
    "aumid",
    "visible",
    "focused",
    "path",
)


def _first(node: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in node and node[key] is not None:
            return node[key]
    return None


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_bounds(value: Any) -> str:
    if isinstance(value, dict):
        x = _first(value, ("x", "left"))
        y = _first(value, ("y", "top"))
        width = _first(value, ("width", "w"))
        height = _first(value, ("height", "h"))
        if all(isinstance(number, (int, float)) for number in (x, y, width, height)):
            return f"@{x:g},{y:g} {width:g}x{height:g}"
        return ""
    if isinstance(value, (list, tuple)) and len(value) == 4:
        if all(isinstance(number, (int, float)) for number in value):
            return f"@{value[0]:g},{value[1]:g} {value[2]:g}x{value[3]:g}"
    return ""


def _looks_like_node(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    markers = _ROLE_KEYS + _NAME_KEYS + _TOKEN_KEYS + _CHILDREN_KEYS
    return any(key in value for key in markers)


def _as_node_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if _looks_like_node(value):
        return [value]
    return []


def _find_roots(payload: Dict[str, Any]) -> List[Any]:
    for key in ("tree", "root", "state", "accessibility_tree", "accessibilityTree"):
        nodes = _as_node_list(payload.get(key))
        if nodes:
            return nodes
    for key in ("elements", "nodes", "items", "children"):
        nodes = _as_node_list(payload.get(key))
        if nodes:
            return nodes
    if _looks_like_node(payload):
        return [payload]
    return []


def _find_items(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("apps", "windows", "items", "results", "result", "children"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _walk_node(node: Any, depth: int, lines: List[str], counter: List[int]) -> None:
    if counter[0] >= MAX_STATE_NODES:
        return
    if not isinstance(node, dict):
        line = _text(node, MAX_ITEM_CHARS)
        if line:
            lines.append(f"{'  ' * depth}- {line}")
            counter[0] += 1
        return

    counter[0] += 1
    role = _text(_first(node, _ROLE_KEYS), 40) or "node"
    name = _text(_first(node, _NAME_KEYS), MAX_NAME_CHARS)
    token = _text(_first(node, _TOKEN_KEYS), 80)
    value = _text(_first(node, _VALUE_KEYS), MAX_VALUE_CHARS)
    bounds = _format_bounds(_first(node, _BOUNDS_KEYS))

    parts = [f"{'  ' * depth}- {role}"]
    if name:
        parts.append(f'"{name}"')
    if token:
        parts.append(f"[{token}]")
    if value:
        parts.append(f'value="{value}"')
    if bounds:
        parts.append(bounds)
    if node.get("enabled") is False:
        parts.append("disabled")
    if node.get("focused") is True:
        parts.append("focused")
    if node.get("selected") is True:
        parts.append("selected")
    lines.append(" ".join(parts))

    if depth >= MAX_DEPTH:
        children = _first(node, _CHILDREN_KEYS)
        if children:
            lines.append(f"{'  ' * (depth + 1)}- ... deeper nodes omitted")
        return

    children = _first(node, _CHILDREN_KEYS)
    if isinstance(children, list):
        for child in children:
            _walk_node(child, depth + 1, lines, counter)
    elif _looks_like_node(children):
        _walk_node(children, depth + 1, lines, counter)


def compact_window_state(payload: Any) -> Tuple[str, Dict[str, Any]]:
    """Render a window snapshot as indented lines plus a small stats record."""
    if not isinstance(payload, dict):
        payload = {"items": payload}
    roots = _find_roots(payload)
    stats: Dict[str, Any] = {"nodes": 0, "truncated": False, "structured": bool(roots)}
    if not roots:
        return output_store.preview(json.dumps(payload, ensure_ascii=False, indent=2)), stats

    lines: List[str] = []
    counter = [0]
    for root in roots:
        _walk_node(root, 0, lines, counter)
    stats["nodes"] = counter[0]
    stats["truncated"] = counter[0] >= MAX_STATE_NODES
    if stats["truncated"]:
        lines.append(f"... node limit reached ({MAX_STATE_NODES}); full tree saved alongside this result")
    return "\n".join(lines), stats


def _persist(directory: Optional[Path], name: str, text: str) -> Optional[str]:
    if directory is None:
        return None
    path = output_store.persist_text(Path(directory) / "computer", name, text)
    return str(path)


def render_state(
    payload: Dict[str, Any],
    *,
    header: str = "",
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Model-facing text for a snapshot, persisting the full tree when needed."""
    tree_text, stats = compact_window_state(payload)
    full_text = f"{header}\n{tree_text}" if header else tree_text

    check = token_budget.check_text(full_text, max_tokens, provider=provider, model=model)
    details: Dict[str, Any] = {
        "state_nodes": stats["nodes"],
        "state_tokens": check.tokens,
        "state_truncated": bool(stats["truncated"]),
    }

    over_budget = not check.ok
    text = full_text
    if over_budget:
        details["state_truncated"] = True
        text = output_store.preview(full_text)

    if (over_budget or stats["truncated"]) and output_directory is not None:
        stamp = output_store.new_stem("computer-state-")
        details["state_json"] = _persist(
            output_directory,
            f"{stamp}.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        if over_budget:
            details["state_file"] = _persist(output_directory, f"{stamp}.txt", full_text)

    return text, details


def _render_item(item: Any) -> str:
    if not isinstance(item, dict):
        return f"- {_text(item, MAX_ITEM_CHARS)}"
    parts = []
    for key in _ITEM_KEYS:
        value = item.get(key)
        if value is None or value == "" or value is False:
            continue
        if isinstance(value, bool):
            parts.append(key)
        else:
            parts.append(f"{key}={_text(value, 80)}")
    if not parts:
        parts.append(_text(json.dumps(item, ensure_ascii=False), MAX_ITEM_CHARS))
    return "- " + " ".join(parts)


def render_listing(
    payload: Any,
    *,
    header: str = "",
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Model-facing text for ``list_apps``/``list_windows`` style answers."""
    items = _find_items(payload)
    if not items:
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        details: Dict[str, Any] = {"listing_items": 0, "listing_truncated": False}
    else:
        lines = [f"{len(items)} item(s):"]
        lines.extend(_render_item(item) for item in items[:200])
        if len(items) > 200:
            lines.append(f"... {len(items) - 200} more item(s) omitted")
        body = "\n".join(lines)
        details = {"listing_items": len(items), "listing_truncated": len(items) > 200}

    text = f"{header}\n{body}" if header else body
    check = token_budget.check_text(text, max_tokens, provider=provider, model=model)
    details["listing_tokens"] = check.tokens
    if not check.ok:
        details["listing_truncated"] = True
        text = output_store.preview(text)
    return text, details


def screenshot_path(output_directory: Optional[Path], prefix: str = "computer-shot-") -> Optional[str]:
    """A fresh PNG path under the run's scratch directory, or ``None``."""
    if output_directory is None:
        return None
    directory = output_store.ensure_dir(Path(output_directory) / "computer")
    return str(directory / f"{output_store.new_stem(prefix)}.png")
