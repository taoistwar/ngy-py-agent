"""Tests for the ``computer_control`` tool.

Run from the repository root::

    uv run python test/tools/computer_control/computer_control_test.py -v

The interesting behaviour is not the forwarding itself but the argument check
and the translation of driver codes (``background_unavailable``,
``stale_element_token``, ``unverifiable``) into an instruction the model can
follow on the next step.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import ToolOutcome  # noqa: E402
from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.computer_control import build_preview, make_control_tool  # noqa: E402
from agent.tools.computer_control.spec import build_spec  # noqa: E402
from agent.tools.permissions import (  # noqa: E402
    PERMISSION_COMPUTER,
    SCOPE_ONCE,
    SCOPE_SESSION,
)


class ComputerControlTest(unittest.TestCase):
    def setUp(self):
        self.tool = make_control_tool(task_id="task-1")

    def test_click_prefers_the_element_token_and_forwards_the_session(self):
        with patch(
            "agent.tools.computer_driver.call_tool",
            return_value={"ok": True, "route": "accessibility"},
        ) as call:
            outcome = self.tool(
                action="click", pid=10, window_id="0x2", element_token="e1"
            )

        self.assertIsInstance(outcome, ToolOutcome)
        request = call.call_args.args[1]
        self.assertEqual(
            {key: request[key] for key in ("pid", "window_id", "element_token")},
            {"pid": 10, "window_id": 2, "element_token": "e1"},
        )
        self.assertEqual(call.call_args.kwargs["session"], "task-1")
        self.assertTrue(outcome.details["success"])

    def test_click_without_a_token_or_a_point_is_rejected(self):
        with patch("agent.tools.computer_driver.call_tool") as call:
            outcome = self.tool(action="click", pid=10, window_id="0x2")

        self.assertFalse(outcome.details["success"])
        self.assertIn("element_token", outcome.model_text)
        call.assert_not_called()

    def test_click_with_coordinates_is_allowed(self):
        with patch(
            "agent.tools.computer_driver.call_tool", return_value={"ok": True}
        ) as call:
            self.tool(action="click", pid=10, window_id="0x2", x=5, y=6)

        self.assertEqual(call.call_args.args[1]["x"], 5)

    def test_launch_app_needs_a_target(self):
        with patch("agent.tools.computer_driver.call_tool") as call:
            outcome = self.tool(action="launch_app")

        self.assertFalse(outcome.details["success"])
        self.assertIn("launch_app", outcome.model_text)
        call.assert_not_called()

    def test_launch_app_by_aumid_is_forwarded(self):
        with patch(
            "agent.tools.computer_driver.call_tool", return_value={"ok": True, "pid": 42}
        ) as call:
            outcome = self.tool(
                action="launch_app",
                aumid="Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
            )

        self.assertEqual(
            call.call_args.args[1]["aumid"],
            "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        )
        self.assertEqual(outcome.details["result"]["pid"], 42)
        self.assertIn("snapshot", outcome.model_text)

    def test_type_text_requires_text(self):
        with patch("agent.tools.computer_driver.call_tool") as call:
            outcome = self.tool(action="type_text", pid=1, window_id=2)

        self.assertFalse(outcome.details["success"])
        call.assert_not_called()

    def test_hotkey_accepts_a_plus_separated_string(self):
        with patch(
            "agent.tools.computer_driver.call_tool", return_value={"ok": True}
        ) as call:
            self.tool(action="hotkey", pid=1, keys="Ctrl+S")

        self.assertEqual(call.call_args.args[1]["keys"], ["Ctrl", "S"])

    def test_an_unknown_delivery_mode_is_rejected(self):
        with patch("agent.tools.computer_driver.call_tool") as call:
            outcome = self.tool(
                action="click", pid=1, window_id=2, element_token="e1",
                delivery_mode="auto",
            )

        self.assertFalse(outcome.details["success"])
        self.assertIn("background", outcome.model_text)
        call.assert_not_called()

    def test_background_unavailable_tells_the_model_to_escalate_this_call(self):
        failure = {
            "ok": False,
            "error": {"code": "background_unavailable", "message": "target is occluded"},
        }
        with patch("agent.tools.computer_driver.call_tool", return_value=failure):
            outcome = self.tool(
                action="click", pid=1, window_id=2, element_token="e1"
            )

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["code"], "background_unavailable")
        self.assertIn("foreground", outcome.model_text)

    def test_stale_element_token_tells_the_model_to_snapshot_again(self):
        failure = {
            "ok": False,
            "error": {"code": "stale_element_token", "message": "token expired"},
        }
        with patch("agent.tools.computer_driver.call_tool", return_value=failure):
            outcome = self.tool(
                action="click", pid=1, window_id=2, element_token="e0"
            )

        self.assertIn("get_window_state", outcome.model_text)

    def test_unverifiable_effects_are_called_out(self):
        with patch(
            "agent.tools.computer_driver.call_tool",
            return_value={"ok": True, "effect": "unverifiable"},
        ):
            outcome = self.tool(action="type_text", pid=1, window_id=2, text="hi")

        self.assertIn("could not verify", outcome.model_text)
        self.assertIn("new snapshot", outcome.model_text)

    def test_params_is_an_escape_hatch_but_named_arguments_win(self):
        with patch(
            "agent.tools.computer_driver.call_tool", return_value={"ok": True}
        ) as call:
            self.tool(
                action="click",
                pid=1,
                window_id=2,
                element_token="e1",
                params={"button": "left", "pid": 999, "session": "hijack"},
            )

        request = call.call_args.args[1]
        self.assertEqual(request["button"], "left")
        self.assertEqual(request["pid"], 1)
        self.assertEqual(call.call_args.kwargs["session"], "task-1")


class ControlSpecTest(unittest.TestCase):
    def test_every_control_call_is_gated_without_a_standing_rule(self):
        spec = build_spec(ToolBindings(task_id="task-1"))

        self.assertEqual(spec.permission, PERMISSION_COMPUTER)
        self.assertEqual(spec.scopes, (SCOPE_ONCE, SCOPE_SESSION))
        self.assertIsNotNone(spec.preview)


class PreviewTest(unittest.TestCase):
    def test_text_is_trimmed_and_no_driver_is_touched(self):
        details = build_preview(
            {"action": "type_text", "pid": 7, "window_id": "0x2", "text": "x" * 500}
        )

        self.assertEqual(details["action"], "type_text")
        self.assertEqual(details["pid"], 7)
        self.assertIn("truncated", details["text"])
        self.assertLess(len(details["text"]), 300)

    def test_launch_details_identify_the_target(self):
        details = build_preview({"action": "launch_app", "path": "C:/Windows/notepad.exe"})

        self.assertEqual(details["path"], "C:/Windows/notepad.exe")


if __name__ == "__main__":
    unittest.main()
