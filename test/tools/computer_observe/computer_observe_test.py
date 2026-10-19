"""Tests for the ``computer_observe`` tool.

Run from the repository root::

    uv run python test/tools/computer_observe/computer_observe_test.py -v

The driver is mocked at ``computer_driver.call_tool``: these tests cover the
argument check, the session label, the screenshot path and the rendering that
decides how much of an accessibility tree the model gets to see.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import ToolOutcome  # noqa: E402
from agent.tools.computer_driver import ComputerDriverError  # noqa: E402
from agent.tools.computer_observe import make_observe_tool  # noqa: E402

_WINDOW_STATE = {
    "ok": True,
    "app": {"name": "Notepad"},
    "tree": [
        {
            "role": "Window",
            "title": "Untitled - Notepad",
            "children": [
                {
                    "role": "Button",
                    "name": "Save",
                    "element_token": "e1",
                    "bounds": {"x": 10, "y": 20, "width": 60, "height": 30},
                },
                {
                    "role": "Edit",
                    "name": "Text editor",
                    "value": "hello",
                    "element_token": "e2",
                },
            ],
        }
    ],
}


class ComputerObserveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output = Path(self._tmp.name)
        self.tool = make_observe_tool(task_id="task-1", output_directory=self.output)

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_window_state_reports_the_tree_and_a_screenshot_path(self):
        with patch("agent.tools.computer_driver.call_tool", return_value=_WINDOW_STATE) as call:
            outcome = self.tool(action="get_window_state", pid=123, window_id="0x2")

        self.assertIsInstance(outcome, ToolOutcome)
        self.assertIn("Button", outcome.model_text)
        self.assertIn("e1", outcome.model_text)
        self.assertIn("hello", outcome.model_text)

        request = call.call_args.args[1]
        self.assertEqual(request["pid"], 123)
        self.assertEqual(request["window_id"], 2)
        self.assertEqual(call.call_args.kwargs["session"], "task-1")
        shot = request["screenshot_out_file"]
        self.assertTrue(shot.endswith(".png"))
        self.assertIn(Path(shot).parent.name, ("computer",))
        self.assertEqual(outcome.details["screenshot"], shot)
        self.assertIn("Screenshot:", outcome.model_text)

    def test_a_written_screenshot_is_offered_to_the_model(self):
        def fake_call(name, payload, **kwargs):
            Path(payload["screenshot_out_file"]).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return _WINDOW_STATE

        with patch("agent.tools.computer_driver.call_tool", side_effect=fake_call):
            outcome = self.tool(action="get_window_state", pid=1, window_id=2)

        self.assertEqual(len(outcome.images), 1)
        self.assertEqual(outcome.images[0].path, outcome.details["screenshot"])

    def test_a_screenshot_the_driver_did_not_write_is_not_claimed(self):
        with patch("agent.tools.computer_driver.call_tool", return_value=_WINDOW_STATE):
            outcome = self.tool(action="get_window_state", pid=1, window_id=2)

        self.assertEqual(outcome.images, [])

    def test_screenshot_false_does_not_ask_the_driver_to_write_a_file(self):
        with patch("agent.tools.computer_driver.call_tool", return_value=_WINDOW_STATE) as call:
            outcome = self.tool(action="get_window_state", pid=1, window_id=2, screenshot=False)

        self.assertNotIn("screenshot_out_file", call.call_args.args[1])
        self.assertNotIn("screenshot", outcome.details)

    def test_list_windows_without_a_pid_fails_before_touching_the_driver(self):
        with patch("agent.tools.computer_driver.call_tool") as call:
            outcome = self.tool(action="list_windows")

        self.assertFalse(outcome.details["success"])
        self.assertIn("pid", outcome.model_text)
        call.assert_not_called()

    def test_list_apps_renders_readable_rows(self):
        payload = {
            "ok": True,
            "apps": [
                {"pid": 111, "name": "notepad", "title": "Untitled - Notepad"},
                {"pid": 222, "name": "calc", "title": "Calculator"},
            ],
        }
        with patch("agent.tools.computer_driver.call_tool", return_value=payload):
            outcome = self.tool(action="list_apps")

        self.assertIn("pid=111", outcome.model_text)
        self.assertIn("Calculator", outcome.model_text)
        self.assertEqual(outcome.details["listing_items"], 2)

    def test_desktop_state_needs_no_pid(self):
        with patch("agent.tools.computer_driver.call_tool", return_value={"ok": True}) as call:
            outcome = self.tool(action="get_desktop_state")

        self.assertIn("screenshot_out_file", call.call_args.args[1])
        self.assertEqual(outcome.details["action"], "get_desktop_state")

    def test_an_unknown_action_is_rejected(self):
        with patch("agent.tools.computer_driver.call_tool") as call:
            outcome = self.tool(action="rm_rf")

        self.assertFalse(outcome.details["success"])
        self.assertIn("Unknown action", outcome.model_text)
        call.assert_not_called()

    def test_a_driver_error_becomes_a_result_with_the_hint(self):
        error = ComputerDriverError("not_installed", "cua-driver was not found", hint="install it")
        with patch("agent.tools.computer_driver.call_tool", side_effect=error):
            outcome = self.tool(action="list_apps")

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["code"], "not_installed")
        self.assertIn("Hint: install it", outcome.model_text)

    def test_driver_stderr_reaches_the_model(self):
        error = ComputerDriverError(
            "driver_failed", "exited with code 9", details={"stderr": "panic: no daemon"}
        )
        with patch("agent.tools.computer_driver.call_tool", side_effect=error):
            outcome = self.tool(action="list_apps")

        self.assertIn("Driver stderr: panic: no daemon", outcome.model_text)
        self.assertEqual(outcome.details["error_details"]["stderr"], "panic: no daemon")

    def test_an_oversized_tree_is_persisted_and_previewed(self):
        nodes = [
            {"role": "Button", "name": f"button-{index}", "element_token": f"e{index}"}
            for index in range(600)
        ]
        tool = make_observe_tool(
            task_id="task-1", max_tokens=50, output_directory=self.output
        )
        with patch("agent.tools.computer_driver.call_tool", return_value={"tree": nodes}):
            outcome = tool(action="get_window_state", pid=1, window_id="0x2")

        self.assertTrue(outcome.details["state_truncated"])
        self.assertIn("state_file", outcome.details)
        self.assertTrue(Path(outcome.details["state_file"]).is_file())
        self.assertIn("state_json", outcome.details)
        self.assertLess(len(outcome.model_text), 4000)


if __name__ == "__main__":
    unittest.main()
