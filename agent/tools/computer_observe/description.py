"""What the model is told about ``computer_observe``: name, description, schema.

Observation is split from action because the permission gate is per tool: reading
the desktop is a constant need, while clicking and typing must be confirmed. The
description carries the driver's snapshot rule, because the model - not the tool -
decides when to look again.
"""

from __future__ import annotations

from typing import Any, Dict

OBSERVE_TOOL_NAME = "computer_observe"

OBSERVE_DESCRIPTION = (
    "Inspect the host desktop through the local cua-driver. This reads the real "
    "machine the agent runs on, not a sandbox. Actions: "
    "'list_apps' (running apps with pids), "
    "'list_windows' (windows of one pid; requires pid), "
    "'get_window_state' (accessibility tree and a screenshot of one window; requires "
    "pid and window_id), "
    "'get_desktop_state' (whole desktop), "
    "'get_browser_state' (page-level state of a browser window). "
    "Call 'get_window_state' before and after every computer_control action: element "
    "tokens are only valid for the snapshot that produced them, and an action can "
    "report success without the UI having changed. Address a window by pid + "
    "window_id, never by title. The text result is the accessibility tree rendered "
    "one control per line; the screenshot is written to a PNG file whose path is "
    "reported in the result, and is also attached to your next turn when the "
    "configured model accepts image input."
)

OBSERVE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "list_apps",
                "list_windows",
                "get_window_state",
                "get_desktop_state",
                "get_browser_state",
            ],
            "description": "Which observation to perform.",
        },
        "pid": {
            "type": "integer",
            "description": "Process id of the target app (from list_apps or launch_app).",
        },
        "window_id": {
            "type": "integer",
            "description": (
                "Window handle from list_windows, not the window title. Decimal or "
                "0x-prefixed hex are both accepted."
            ),
        },
        "screenshot": {
            "type": "boolean",
            "default": True,
            "description": (
                "Write a PNG screenshot next to the run's scratch output and report its "
                "path. Defaults to true; the accessibility tree is returned either way."
            ),
        },
    },
    "required": ["action"],
}
