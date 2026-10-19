"""The ``computer_control`` implementation.

One action per call, forwarded to ``cua-driver``. The tool validates only what
the driver would reject ambiguously - a click without a token or coordinates, a
launch without a target - and leaves the rest to the driver's own schema. The
driver's ``background_unavailable`` / ``stale_element_token`` / ``unverifiable``
answers are translated into an instruction the model can follow, because those
codes are the difference between a retry that works and one that types twice.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from agent.models import EventCategory, ToolOutcome
from agent.tools import computer_driver
from agent.tools.computer_control.description import CONTROL_ACTIONS

_CLICK_ACTIONS = ("click", "double_click", "right_click")
_TARGET_ACTIONS = (
    "click",
    "double_click",
    "right_click",
    "drag",
    "scroll",
    "press_key",
    "hotkey",
    "type_text",
    "set_window_frame",
    "invoke_menu",
    "bring_to_front",
)
_RESULT_PREVIEW_CHARS = 1500


class ComputerInputError(ValueError):
    """The action cannot be built from the arguments the model supplied."""


def _build_payload(fields: Dict[str, Any], params: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in fields.items():
        if key == "session" or value is None or value == "":
            continue
        if isinstance(value, str) and not value.strip():
            continue
        payload[key] = value

    if isinstance(params, dict):
        for key, value in params.items():
            if key == "session" or value is None:
                continue
            # Explicit named arguments win over the escape hatch.
            payload.setdefault(str(key), value)
    return payload


def _normalize(payload: Dict[str, Any]) -> None:
    window_id = payload.get("window_id")
    if isinstance(window_id, str):
        text = window_id.strip()
        try:
            payload["window_id"] = int(text, 0)
        except ValueError:
            payload["window_id"] = text

    mode = payload.get("delivery_mode")
    if mode is not None:
        text = str(mode).strip().lower()
        if text not in ("background", "foreground"):
            raise ComputerInputError(
                f"'delivery_mode' must be 'background' or 'foreground', got '{mode}'."
            )
        payload["delivery_mode"] = text

    keys = payload.get("keys")
    if isinstance(keys, str):
        payload["keys"] = [part for part in keys.replace(" ", "").split("+") if part]

    urls = payload.get("urls")
    if isinstance(urls, str):
        payload["urls"] = [urls]


def _require(payload: Dict[str, Any], key: str, action: str) -> Any:
    value = payload.get(key)
    if value is None or value == "":
        raise ComputerInputError(f"'{key}' is required for {action}.")
    return value


def _require_pid(payload: Dict[str, Any], action: str) -> None:
    pid = _require(payload, "pid", action)
    if isinstance(pid, bool):
        raise ComputerInputError(f"'pid' must be an integer for {action}.")
    if isinstance(pid, str):
        try:
            payload["pid"] = int(pid, 0)
        except ValueError as exc:
            raise ComputerInputError(f"'pid' must be an integer, got '{pid}'.") from exc


def _validate(action: str, payload: Dict[str, Any]) -> None:
    if action == "launch_app":
        targets = ("path", "name", "aumid", "urls")
        if not any(payload.get(key) for key in targets):
            raise ComputerInputError(
                "launch_app needs one of 'path', 'name', 'aumid' or 'urls'."
            )
        return

    if action in _TARGET_ACTIONS:
        _require_pid(payload, action)

    if action in _CLICK_ACTIONS:
        has_token = bool(str(payload.get("element_token") or "").strip())
        has_point = payload.get("x") is not None and payload.get("y") is not None
        if not has_token and not has_point:
            raise ComputerInputError(
                f"{action} needs either 'element_token' (preferred) or both 'x' and 'y'."
            )

    if action == "drag":
        for key in ("from_x", "from_y", "to_x", "to_y"):
            _require(payload, key, action)

    if action == "scroll":
        scroll_keys = ("delta_x", "delta_y", "direction", "amount")
        if not any(payload.get(key) is not None for key in scroll_keys):
            raise ComputerInputError(
                "scroll needs 'delta_y'/'delta_x', or 'direction' with 'amount'."
            )

    if action == "type_text":
        _require(payload, "text", action)

    if action == "press_key":
        _require(payload, "key", action)

    if action == "hotkey":
        keys = payload.get("keys")
        if not keys and not payload.get("key"):
            raise ComputerInputError("hotkey needs 'keys', e.g. ['ctrl', 'c'].")

    if action == "set_window_frame":
        if payload.get("width") is None or payload.get("height") is None:
            raise ComputerInputError("set_window_frame needs 'width' and 'height'.")

    if action == "bring_to_front" and payload.get("window_id") is None:
        raise ComputerInputError("bring_to_front needs 'window_id'.")


def _timeout_for(action: str) -> float:
    return 60.0 if action == "launch_app" else computer_driver.DEFAULT_TIMEOUT_SECONDS


def _render_result(action: str, result: Any) -> str:
    try:
        body = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        body = str(result)
    if len(body) > _RESULT_PREVIEW_CHARS:
        body = body[:_RESULT_PREVIEW_CHARS] + "..."

    text = f"{action} executed. Driver result: {body}"
    notes = []

    if isinstance(result, dict):
        if result.get("effect") == "unverifiable":
            notes.append(
                "the driver could not verify the effect (UWP apps can ignore synthetic "
                "input). Take a new snapshot before retrying, or you may act twice."
            )
        if result.get("route") == "synthetic_events":
            notes.append(
                "input was delivered as synthetic events; confirm with a new snapshot."
            )
        if result.get("ok") is True and result.get("changed") is False:
            notes.append("the driver reported no observable change.")

    notes.append("take a new computer_observe snapshot before the next decision.")
    return text + "\n" + "\n".join(f"Note: {note}" for note in notes)


def _failure(action: str, exc: Exception) -> ToolOutcome:
    code = str(getattr(exc, "code", "invalid_arguments"))
    hint = str(getattr(exc, "hint", "") or "")
    details: Dict[str, Any] = {
        "success": False,
        "action": action,
        "code": code,
        "hint": hint,
    }
    error_details = getattr(exc, "details", None)
    if isinstance(error_details, dict) and error_details:
        details["error_details"] = error_details

    return ToolOutcome(
        model_text=computer_driver.describe_error(exc),
        event_category=EventCategory.COMPUTER,
        event_title=f"Computer action failed: {action or '(missing action)'}",
        details=details,
    )


def make_control_tool(
    *,
    task_id: str = "",
):
    """Bind the control tool to one run's driver session."""
    session = task_id or computer_driver.DEFAULT_SESSION

    def computer_control(
        action: str = "",
        params: Optional[Dict[str, Any]] = None,
        **fields: Any,
    ) -> ToolOutcome:
        name = str(action or "").strip().lower()
        if name not in CONTROL_ACTIONS:
            return _failure(
                name,
                ComputerInputError(
                    f"Unknown action '{action}'. Use one of: {', '.join(CONTROL_ACTIONS)}."
                ),
            )

        try:
            payload = _build_payload(fields, params)
            _normalize(payload)
            _validate(name, payload)
            result = computer_driver.call_tool(
                name, payload, session=session, timeout=_timeout_for(name)
            )
            error = computer_driver.error_from_payload(result)
            if error is not None:
                raise error
        except (computer_driver.ComputerDriverError, ComputerInputError) as exc:
            return _failure(name, exc)

        return ToolOutcome(
            model_text=_render_result(name, result),
            event_category=EventCategory.COMPUTER,
            event_title=f"Computer: {name}",
            details={"success": True, "action": name, "request": payload, "result": result},
        )

    return computer_control
