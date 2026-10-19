"""Tests for the shared cua-driver process plumbing.

Run from the repository root::

    uv run python test/tools/computer_driver_test.py -v

The driver itself is not installed on most machines, so the process boundary is
mocked: what matters here is the request the tools send, and how a failed call
is turned into something the model can act on.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools import computer_driver  # noqa: E402
from agent.tools.computer_driver import (  # noqa: E402
    ComputerDriverError,
    call_tool,
    error_from_payload,
)

_COMPLETED = subprocess.CompletedProcess


class CallToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # A real file is enough: the subprocess itself is mocked below.
        self.env = patch.dict(os.environ, {"CUA_DRIVER_BIN": __file__})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def run_with(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        with patch("agent.tools.computer_driver.subprocess.run") as run:
            run.return_value = _COMPLETED(
                args=["cua-driver"], returncode=returncode, stdout=stdout, stderr=stderr
            )
            return run, call_tool("list_windows", {"pid": 10}, session="task-1")

    def test_the_tool_name_and_session_travel_on_the_process_boundary(self):
        run, result = self.run_with('{"ok": true, "windows": []}')

        self.assertEqual(run.call_args.args[0][1], "list_windows")
        self.assertEqual(
            json.loads(run.call_args.kwargs["input"]),
            {"session": "task-1", "pid": 10},
        )
        self.assertEqual(result["ok"], True)

    def test_an_empty_session_still_gets_a_stable_label(self):
        with patch("agent.tools.computer_driver.subprocess.run") as run:
            run.return_value = _COMPLETED(args=[], returncode=0, stdout="{}", stderr="")
            call_tool("list_apps", {}, session="")

        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["session"], computer_driver.DEFAULT_SESSION)

    def test_a_missing_binary_is_reported_with_the_install_hint(self):
        with patch.dict(os.environ, {"CUA_DRIVER_BIN": str(Path(self._tmp.name) / "nope.exe")}):
            with self.assertRaises(ComputerDriverError) as caught:
                call_tool("list_apps", {}, session="task-1")

        self.assertEqual(caught.exception.code, "not_installed")
        self.assertIn("cua-driver", caught.exception.hint)

    def test_a_structured_failure_keeps_the_driver_code_and_its_hint(self):
        stdout = (
            '{"ok": false, "error": {"code": "background_unavailable", '
            '"message": "target is occluded"}}'
        )
        with patch("agent.tools.computer_driver.subprocess.run") as run:
            run.return_value = _COMPLETED(args=[], returncode=3, stdout=stdout, stderr="")
            with self.assertRaises(ComputerDriverError) as caught:
                call_tool("click", {"pid": 1}, session="task-1")

        self.assertEqual(caught.exception.code, "background_unavailable")
        self.assertIn("foreground", caught.exception.hint)

    def test_a_crash_without_json_still_names_the_exit_code(self):
        with patch("agent.tools.computer_driver.subprocess.run") as run:
            run.return_value = _COMPLETED(
                args=[], returncode=9, stdout="", stderr="panic: no daemon"
            )
            with self.assertRaises(ComputerDriverError) as caught:
                call_tool("list_apps", {}, session="task-1")

        self.assertEqual(caught.exception.code, "driver_failed")
        self.assertIn("9", str(caught.exception))
        self.assertIn("no daemon", caught.exception.details["stderr"])

    def test_a_timeout_is_its_own_error(self):
        with patch("agent.tools.computer_driver.subprocess.run") as run:
            run.side_effect = subprocess.TimeoutExpired(cmd="cua-driver", timeout=1)
            with self.assertRaises(ComputerDriverError) as caught:
                call_tool("list_apps", {})

        self.assertEqual(caught.exception.code, "timeout")

    def test_plain_text_output_is_wrapped_not_dropped(self):
        _run, result = self.run_with("driver says hello\n")

        self.assertEqual(result, {"output": "driver says hello"})

    def test_a_log_line_before_the_json_payload_is_tolerated(self):
        _run, result = self.run_with('starting driver\n{"ok": true}\n')

        self.assertEqual(result, {"ok": True})


class PayloadErrorTest(unittest.TestCase):
    def test_ok_false_with_a_message_is_an_error(self):
        error = error_from_payload({"ok": False, "message": "window closed"})

        self.assertIsNotNone(error)
        self.assertEqual(error.code, "driver_error")
        self.assertIn("window closed", str(error))

    def test_success_false_with_a_string_error_is_an_error(self):
        error = error_from_payload({"success": False, "error": "no such pid"})

        self.assertIsNotNone(error)
        self.assertIn("no such pid", str(error))

    def test_a_normal_result_is_not_an_error(self):
        self.assertIsNone(error_from_payload({"ok": True, "pid": 1}))
        self.assertIsNone(error_from_payload("plain"))


if __name__ == "__main__":
    unittest.main()
