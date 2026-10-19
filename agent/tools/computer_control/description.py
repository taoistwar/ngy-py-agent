"""What the model is told about ``computer_control``: name, description, schema.

The driver has invariants the tool cannot enforce on the model's behalf, so they
are stated in the description rather than left to trial and error:

* snapshot before and after every action,
* prefer ``element_token`` over pixel coordinates,
* start with ``background`` delivery and escalate only the failing action.

The last paragraph exists because ``exec_command`` is right next to this tool and
would happily launch an app via ``Start-Process`` - which steals focus and skips
everything the driver does to keep the user's desktop stable.
"""

from __future__ import annotations

from typing import Any, Dict

CONTROL_TOOL_NAME = "computer_control"

CONTROL_ACTIONS = (
    "launch_app",
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

CONTROL_DESCRIPTION = (
    "Operate the host desktop through the local cua-driver. This acts on the real "
    "machine the agent runs on, not a sandbox. "
    "Actions: 'launch_app' (start a Win32 app by path/name, a packaged app by aumid, "
    "or URLs with urls), 'click'/'double_click'/'right_click' (pid, window_id, plus "
    "either element_token or x/y), 'drag', 'scroll', 'press_key', 'hotkey', "
    "'type_text', 'set_window_frame', 'invoke_menu', 'bring_to_front'. "
    "Rules: (1) call computer_observe get_window_state before acting and again after "
    "it; element tokens are only valid for the snapshot that produced them. "
    "(2) Prefer element_token over x/y: it uses the accessibility invoke path, which "
    "does not move the cursor or change focus. (3) delivery_mode defaults to "
    "'background', which never steals the foreground window; if a call returns "
    "background_unavailable, retry only that single action with "
    "delivery_mode='foreground'. (4) An action may report success without the UI "
    "having changed (UWP apps silently ignore synthetic events, effect='unverifiable'): "
    "take a new snapshot before retrying, or you may type or click twice. "
    "(5) If a call returns stale_element_token, take a new snapshot. "
    "Some actions accept driver-native fields not listed here through 'params'. "
    "Do NOT launch or drive GUI apps with exec_command (Start-Process, cmd /c start, "
    "explorer.exe shell:...) - those paths steal focus and bypass the driver's "
    "background-input handling; use this tool instead."
)

CONTROL_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(CONTROL_ACTIONS),
            "description": "Which desktop action to perform.",
        },
        "pid": {
            "type": "integer",
            "description": "Target process id (from list_apps or launch_app).",
        },
        "window_id": {
            "type": "integer",
            "description": "Target window handle from list_windows (decimal or 0x-prefixed hex).",
        },
        "element_token": {
            "type": "string",
            "description": (
                "Token for a control in the last get_window_state snapshot. Preferred "
                "over coordinates; it becomes stale after any new snapshot or UI change."
            ),
        },
        "x": {"type": "number", "description": "Client-area x coordinate (pixel path)."},
        "y": {"type": "number", "description": "Client-area y coordinate (pixel path)."},
        "from_x": {"type": "number", "description": "Drag start x."},
        "from_y": {"type": "number", "description": "Drag start y."},
        "to_x": {"type": "number", "description": "Drag end x."},
        "to_y": {"type": "number", "description": "Drag end y."},
        "delta_x": {"type": "number", "description": "Horizontal scroll delta."},
        "delta_y": {"type": "number", "description": "Vertical scroll delta."},
        "direction": {
            "type": "string",
            "description": "Scroll direction when the driver expects a direction rather than a delta.",
        },
        "amount": {"type": "number", "description": "Scroll amount."},
        "text": {"type": "string", "description": "Text to type (type_text)."},
        "key": {"type": "string", "description": "Single key to press (press_key)."},
        "keys": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key combination for hotkey, e.g. ['alt', 'f4'].",
        },
        "path": {"type": "string", "description": "Executable path (launch_app)."},
        "name": {"type": "string", "description": "App name (launch_app)."},
        "aumid": {
            "type": "string",
            "description": "Application user model id for packaged Windows apps (launch_app).",
        },
        "urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLs to open, one window each (launch_app).",
        },
        "width": {"type": "number", "description": "Window width (set_window_frame)."},
        "height": {"type": "number", "description": "Window height (set_window_frame)."},
        "delivery_mode": {
            "type": "string",
            "enum": ["background", "foreground"],
            "default": "background",
            "description": (
                "Input delivery. Keep 'background' (never steals focus); use "
                "'foreground' only for a single action that returned "
                "background_unavailable."
            ),
        },
        "params": {
            "type": "object",
            "description": "Driver-native fields for an action not covered by the named parameters.",
        },
    },
    "required": ["action"],
}
