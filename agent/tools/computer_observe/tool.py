"""The ``computer_observe`` implementation.

The tool is a thin adapter: it validates the action's required arguments, asks
the driver, and renders the answer. Snapshot and listing rendering live in
``agent/tools/computer_state.py`` so the control tool can reuse them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.models import EventCategory, ToolImage, ToolOutcome
from agent.tools import computer_driver, computer_state

_OBSERVE_ACTIONS = (
    "list_apps",
    "list_windows",
    "get_window_state",
    "get_desktop_state",
    "get_browser_state",
)


class ComputerInputError(ValueError):
    """The model asked for something the action cannot be built from."""


def _as_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ComputerInputError(f"'screenshot' must be a boolean, got '{value}'.")


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ComputerInputError(f"'{field}' must be an integer.")
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        raise ComputerInputError(f"'{field}' is required for this action.")
    try:
        return int(text, 0)
    except ValueError as exc:
        raise ComputerInputError(f"'{field}' must be an integer, got '{value}'.") from exc


def _as_window_id(value: Any) -> Any:
    if isinstance(value, bool):
        raise ComputerInputError("'window_id' must be a window handle.")
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        raise ComputerInputError("'window_id' is required for this action.")
    try:
        return int(text, 0)
    except ValueError:
        # A platform that hands out non-numeric handles still works; the driver
        # gets the token back verbatim.
        return text


def _build_request(
    action: str,
    pid: Any,
    window_id: Any,
    screenshot: Any,
    output_directory: Optional[Path],
) -> Tuple[Dict[str, Any], Optional[str]]:
    wants_shot = _as_bool(screenshot, True)

    if action == "list_apps":
        return {}, None

    if action == "list_windows":
        return {"pid": _as_int(pid, "pid")}, None

    if action == "get_window_state":
        payload: Dict[str, Any] = {
            "pid": _as_int(pid, "pid"),
            "window_id": _as_window_id(window_id),
        }
        shot = computer_state.screenshot_path(output_directory) if wants_shot else None
        if shot is not None:
            payload["screenshot_out_file"] = shot
        return payload, shot

    if action == "get_desktop_state":
        shot = (
            computer_state.screenshot_path(output_directory, "computer-desktop-")
            if wants_shot
            else None
        )
        return ({"screenshot_out_file": shot} if shot is not None else {}), shot

    payload = {}
    if pid not in (None, ""):
        payload["pid"] = _as_int(pid, "pid")
    if window_id not in (None, ""):
        payload["window_id"] = _as_window_id(window_id)
    return payload, None


def _header_for(action: str, payload: Dict[str, Any]) -> str:
    pid = payload.get("pid")
    window_id = payload.get("window_id")
    if action == "get_window_state":
        return f"Window state (pid={pid}, window_id={window_id})."
    if action == "get_desktop_state":
        return "Desktop state."
    if action == "list_apps":
        return "Apps on this host."
    if action == "list_windows":
        return f"Windows of pid {pid}."
    if action == "get_browser_state":
        return f"Browser state (pid={pid}, window_id={window_id})."
    return "Host state."


def _is_state_action(action: str) -> bool:
    return action in ("get_window_state", "get_desktop_state")


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
        event_title=f"Computer observe failed: {action or '(missing action)'}",
        details=details,
    )


def make_observe_tool(
    *,
    task_id: str = "",
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    output_directory: Optional[Path] = None,
):
    """Bind the observation tool to one run's session and scratch directory."""
    session = task_id or computer_driver.DEFAULT_SESSION

    def computer_observe(
        action: str = "",
        pid: Any = None,
        window_id: Any = None,
        screenshot: Any = True,
    ) -> ToolOutcome:
        name = str(action or "").strip().lower()
        if name not in _OBSERVE_ACTIONS:
            return _failure(
                name,
                ComputerInputError(
                    f"Unknown action '{action}'. Use one of: {', '.join(_OBSERVE_ACTIONS)}."
                ),
            )

        try:
            request, shot = _build_request(
                name, pid, window_id, screenshot, output_directory
            )
            result = computer_driver.call_tool(name, request, session=session)
            error = computer_driver.error_from_payload(result)
            if error is not None:
                raise error
        except (computer_driver.ComputerDriverError, ComputerInputError) as exc:
            return _failure(name, exc)

        header = _header_for(name, request)
        if _is_state_action(name):
            text, details = computer_state.render_state(
                result,
                header=header,
                max_tokens=max_tokens,
                provider=provider,
                model=model,
                output_directory=output_directory,
            )
        else:
            text, details = computer_state.render_listing(
                result,
                header=header,
                max_tokens=max_tokens,
                provider=provider,
                model=model,
            )

        if shot is not None:
            text = f"{text}\nScreenshot: {shot}"

        payload_details: Dict[str, Any] = {
            "success": True,
            "action": name,
            "request": request,
            **details,
        }
        images: List[ToolImage] = []
        if shot is not None:
            payload_details["screenshot"] = shot
            # Only claim an attachment when the driver actually wrote the file.
            # A missing PNG must not turn a successful observation into an error.
            if Path(shot).is_file():
                images.append(ToolImage(path=shot))

        return ToolOutcome(
            model_text=text,
            event_category=EventCategory.COMPUTER,
            event_title=f"Computer: {name}",
            details=payload_details,
            images=images,
        )

    return computer_observe
