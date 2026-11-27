"""The run's background ledger: what it reports, once, and in what shape.

``exec_command(run_in_background=True)`` answers with a placeholder; this ledger is
how the *end* of that command reaches the model, so the two things that matter are
"each command is reported exactly once" and "the report is useful on its own" (exit
code plus the tail of the output, not just a path).

Run from the repository root::

    uv run python test/tools/background_test.py -v
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools import process_store  # noqa: E402
from agent.tools.background import BackgroundCommand, BackgroundResult, BackgroundTasks  # noqa: E402
from agent.tools.exec_command.tool import make_exec_tool  # noqa: E402


class _Running:
    def running(self):
        return True


class _Finished:
    def __init__(self, exit_code):
        self.command = type("Command", (), {"poll": staticmethod(lambda: exit_code)})()

    def running(self):
        return False


class NotificationShapeTest(unittest.TestCase):
    def build(self, exit_code=0, tail="done"):
        record = BackgroundCommand(
            session_id="1a2b3c4d",
            pid=4242,
            command="npm install",
            description="Install dependencies",
            log_path="C:/out/20260101.log",
        )
        return BackgroundResult(record=record, exit_code=exit_code, tail=tail).as_notification()

    def test_the_notification_says_what_finished_and_how(self):
        text = self.build()

        self.assertTrue(text.startswith("<task_notification>"))
        self.assertTrue(text.endswith("</task_notification>"))
        self.assertIn("Install dependencies", text)
        self.assertIn("exit code 0", text)
        self.assertIn("1a2b3c4d", text)
        self.assertIn("C:/out/20260101.log", text)
        self.assertIn("Last output:\ndone", text)

    def test_a_failure_is_visible_as_the_exit_code(self):
        self.assertIn("exit code 1", self.build(exit_code=1))

    def test_a_session_already_closed_reports_no_exit_code_instead_of_guessing(self):
        self.assertIn("exit code unknown", self.build(exit_code=None))

    def test_a_silent_command_says_so_instead_of_an_empty_section(self):
        text = self.build(tail="")

        self.assertIn("It printed nothing.", text)
        self.assertNotIn("Last output:", text)


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.ledger = BackgroundTasks(task_id="task-bg-test")

    def track(self, session_id="abc12345"):
        return self.ledger.track(
            session_id=session_id,
            pid=1,
            command="run the suite",
            description="",
            log_path="",
        )

    def test_a_running_command_is_not_reported(self):
        self.track()

        with patch.object(process_store, "get", return_value=_Running()):
            self.assertEqual(self.ledger.collect(), [])

        self.assertEqual(self.ledger.pending(), 1)

    def test_a_finished_command_is_reported_once_with_its_exit_code(self):
        self.track()

        with patch.object(process_store, "get", return_value=_Finished(2)):
            with patch.object(process_store, "retire") as retire:
                results = self.ledger.collect()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].exit_code, 2)
        # The ledger is what reports the end, so it also releases the session.
        retire.assert_called_once()
        self.assertEqual(self.ledger.collect(), [])
        self.assertEqual(self.ledger.pending(), 0)

    def test_a_session_closed_elsewhere_is_still_reported(self):
        # ``write_stdin`` retires a session once it sees the process exit; the
        # notification must not go missing because of who noticed first.
        self.track()

        with patch.object(process_store, "get", return_value=None):
            results = self.ledger.collect()

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].exit_code)

    def test_tracking_the_same_session_twice_does_not_double_report(self):
        self.track()
        self.track()

        with patch.object(process_store, "get", return_value=_Finished(0)):
            with patch.object(process_store, "retire"):
                results = self.ledger.collect()

        self.assertEqual(len(results), 1)


class RealCommandTest(unittest.TestCase):
    """One real background command, end to end through the tool that starts it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.task_id = f"bg-integration-{time.monotonic_ns()}"
        self.ledger = BackgroundTasks(task_id=self.task_id)

    def tearDown(self):
        # Never leave a command behind, even when an assertion failed above.
        process_store.stop_task(self.task_id)
        self._tmp.cleanup()

    def test_a_real_background_command_reports_its_output_and_exit_code(self):
        exec_command = make_exec_tool(
            base_dir=None,
            task_id=self.task_id,
            output_directory=Path(self._tmp.name),
            background=self.ledger,
        )

        started = exec_command(command="echo bg-marker-42", run_in_background=True)

        self.assertTrue(started.details["background"], started.model_text)
        self.assertEqual(self.ledger.pending(), 1)

        results = []
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not results:
            results = self.ledger.collect()
            if not results:
                time.sleep(0.1)

        self.assertEqual(len(results), 1, "the finished command was never collected")
        self.assertEqual(results[0].exit_code, 0)
        self.assertIn("bg-marker-42", results[0].tail)
        self.assertEqual(self.ledger.collect(), [])


if __name__ == "__main__":
    unittest.main()
