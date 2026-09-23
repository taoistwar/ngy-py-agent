"""Tests for the write_stdin tool and the sessions exec_command hands out.

The interactive command is a tiny Python helper written to a temp dir and run by
the same interpreter as the test, so the expectations hold under PowerShell on
Windows and bash on Linux (CI runs the latter).

Writes pass a generous ``yield_time_ms`` on purpose: the tool returns as soon as
output arrives, so a large bound costs nothing but absorbs a slow interpreter
start-up under load.

Run from the repository root::

    uv run python test/tools/write_stdin_tool_test.py -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools import write_stdin_tool  # noqa: E402
from agent.tools.permissions import PERMISSION_EXEC  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.shell_platform import FAMILY_POWERSHELL, detect_shell  # noqa: E402

# Reads exactly two lines, echoes each with a prefix, then says goodbye and exits.
ECHO_TWICE = (
    "import sys\n"
    "for _ in range(2):\n"
    "    line = sys.stdin.readline()\n"
    "    if not line:\n"
    "        break\n"
    "    sys.stdout.write('echo:' + line.rstrip('\\n') + '\\n')\n"
    "    sys.stdout.flush()\n"
    "sys.stdout.write('bye\\n')\n"
    "sys.stdout.flush()\n"
)

# Blocks on stdin forever, so the session stays alive for polls and interrupts.
WAIT_FOREVER = "import sys\nsys.stdin.readline()\n"

# Prints once, lingers a moment, then exits with code 0.
EXIT_AFTER_PRINT = (
    "import sys, time\n"
    "sys.stdout.write('done\\n')\n"
    "sys.stdout.flush()\n"
    "time.sleep(1)\n"
)

# Prints a large block, then lingers so the budget can be observed while alive.
BIG_OUTPUT = (
    "import sys, time\n"
    "sys.stdout.write('x' * 200000)\n"
    "sys.stdout.flush()\n"
    "time.sleep(5)\n"
)

# A write returns as soon as output arrives, so this is a ceiling, not a delay.
WRITE_YIELD_MS = 8_000


def _run_command(executable, script):
    """Quote ``executable script`` for the shell the exec tool actually uses.

    PowerShell needs the call operator when the command is a quoted path; cmd and
    POSIX shells are happy with the path on its own.
    """
    shell = detect_shell()
    if shell is not None and shell.family == FAMILY_POWERSHELL:
        return f'& "{executable}" "{script}"'
    return f'"{executable}" "{script}"'


class WriteStdinTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._out = tempfile.TemporaryDirectory()
        self.outputs = Path(self._out.name)
        self.env = mock.patch.dict(os.environ, {"EXEC_OUTPUT_DIR": str(self.outputs)})
        self.env.start()
        self.registry = ToolRegistry(base_dir=str(self.root), session_id="test")
        self.sessions = []

    def tearDown(self):
        for session_id in self.sessions:
            self.registry.execute_tool(
                "write_stdin", {"session_id": session_id, "chars": "\u0003", "yield_time_ms": 5000}
            )
        self.env.stop()
        self._out.cleanup()
        self._tmp.cleanup()

    # --- helpers ----------------------------------------------------------

    def start(self, source, name="helper.py"):
        """Run ``source`` as a background session and return its session_id."""
        script = self.root / name
        script.write_text(source, encoding="utf-8")
        outcome = self.registry.execute_tool(
            "exec_command",
            {"command": _run_command(sys.executable, script), "run_in_background": True},
        )
        self.assertTrue(outcome.details["background"], outcome.model_text)
        session_id = outcome.details["session_id"]
        self.sessions.append(session_id)
        return session_id

    def write_stdin(self, arguments):
        return self.registry.execute_tool("write_stdin", arguments)

    def poll(self, session_id, **extra):
        """Poll with a short floor so the tests do not wait five seconds."""
        with mock.patch.object(write_stdin_tool, "POLL_MIN_YIELD_MS", 200):
            return self.write_stdin({"session_id": session_id, **extra})

    def wait_for(self, session_id, predicate, deadline_seconds=20.0, **extra):
        deadline = time.monotonic() + deadline_seconds
        outcome = None
        while time.monotonic() < deadline:
            outcome = self.poll(session_id, **extra)
            if predicate(outcome):
                return outcome
            time.sleep(0.2)
        self.fail(f"the condition never held: {getattr(outcome, 'model_text', '')}")

    # --- schema and validation -------------------------------------------

    def test_registry_exposes_write_stdin(self):
        schemas = {item["function"]["name"]: item for item in self.registry.get_tool_schemas("openai")}

        self.assertIn("write_stdin", schemas)
        self.assertEqual(schemas["write_stdin"]["function"]["parameters"]["required"], ["session_id"])
        self.assertEqual(self.registry.tools["write_stdin"]["permission"], PERMISSION_EXEC)

    def test_unknown_session_is_rejected(self):
        outcome = self.write_stdin({"session_id": "deadbeef"})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "unknown_session")
        self.assertIn("Unknown session", outcome.model_text)

    def test_missing_session_id_is_rejected(self):
        outcome = self.write_stdin({})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "invalid_argument")

    def test_non_string_chars_is_rejected(self):
        session_id = self.start(WAIT_FOREVER)

        outcome = self.write_stdin({"session_id": session_id, "chars": 5})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "invalid_argument")

    # --- writing and polling ---------------------------------------------

    def test_write_is_echoed_back_and_the_session_stays_open(self):
        session_id = self.start(ECHO_TWICE)

        outcome = self.write_stdin(
            {"session_id": session_id, "chars": "hello\n", "yield_time_ms": WRITE_YIELD_MS}
        )

        self.assertTrue(outcome.details["success"], outcome.model_text)
        self.assertIn("echo:hello", outcome.details["output"])
        self.assertTrue(outcome.details["running"])
        self.assertIn(f"Process running with session ID {session_id}", outcome.model_text)

    def test_poll_returns_nothing_new_when_idle(self):
        session_id = self.start(ECHO_TWICE)
        self.write_stdin(
            {"session_id": session_id, "chars": "alpha\n", "yield_time_ms": WRITE_YIELD_MS}
        )

        second = self.poll(session_id)

        self.assertEqual(second.details["output"], "")
        self.assertTrue(second.details["running"])

    def test_process_exit_is_reported_and_the_session_is_forgotten(self):
        session_id = self.start(EXIT_AFTER_PRINT)

        # The first look may land before the command has printed anything.
        seen = self.wait_for(
            session_id, lambda outcome: "done" in outcome.details.get("output", "")
        )
        self.assertIn("done", seen.details["output"])

        if seen.details.get("running"):
            finished = self.wait_for(
                session_id,
                lambda outcome: bool(outcome.details.get("success"))
                and not outcome.details.get("running"),
            )
        else:
            # The command had already finished by the time we first looked.
            finished = seen

        self.assertEqual(finished.details["exit_code"], 0, finished.model_text)
        self.assertIn("Process exited with code 0", finished.model_text)
        # A finished session cannot be reused.
        again = self.write_stdin({"session_id": session_id})
        self.assertEqual(again.details["reason"], "unknown_session")

    def test_ctrl_c_interrupts_the_command(self):
        session_id = self.start(WAIT_FOREVER)

        with mock.patch.object(write_stdin_tool, "POLL_MIN_YIELD_MS", 200):
            outcome = self.write_stdin(
                {"session_id": session_id, "chars": "\u0003", "yield_time_ms": 5_000}
            )

        self.assertTrue(outcome.details["interrupted"])
        self.assertFalse(outcome.details["running"], outcome.model_text)
        self.assertIn("Process exited with code", outcome.model_text)

    def test_large_output_is_truncated_to_the_budget(self):
        session_id = self.start(BIG_OUTPUT)

        outcome = self.wait_for(
            session_id,
            lambda result: bool(result.details.get("output_truncated")),
            max_output_tokens=50,
        )

        self.assertTrue(outcome.details["output_truncated"])
        self.assertIn("was truncated", outcome.details["output"])
        self.assertGreater(outcome.details["original_token_count"], 50)
        # Over budget the whole chunk lands on disk and the path is reported, so the
        # model can read the rest instead of being stuck with a preview (ADR 0005 D4/D8).
        persisted = Path(outcome.details["persistedOutputPath"])
        self.assertTrue(persisted.is_file())
        saved = persisted.read_text(encoding="utf-8")
        self.assertGreater(len(saved), 200)
        self.assertEqual(set(saved), {"x"})

    # --- ownership --------------------------------------------------------

    def test_another_task_cannot_touch_the_session(self):
        session_id = self.start(WAIT_FOREVER)
        other = ToolRegistry(base_dir=str(self.root), task_id="another-task")

        outcome = other.execute_tool("write_stdin", {"session_id": session_id, "chars": "x\n"})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "unknown_session")

    def test_another_workspace_cannot_touch_the_session(self):
        session_id = self.start(WAIT_FOREVER)
        other_root = tempfile.TemporaryDirectory()
        self.addCleanup(other_root.cleanup)
        other = ToolRegistry(base_dir=other_root.name)

        outcome = other.execute_tool("write_stdin", {"session_id": session_id, "chars": "x\n"})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "unknown_session")

    # --- yield rules (the reference's ranges) -----------------------------

    def test_yield_time_is_clamped_by_mode(self):
        # A poll is patient: at least five seconds, at most five minutes.
        self.assertEqual(write_stdin_tool._effective_yield_ms(None, is_write=False), 5_000)
        self.assertEqual(write_stdin_tool._effective_yield_ms(1, is_write=False), 5_000)
        self.assertEqual(write_stdin_tool._effective_yield_ms(10 ** 9, is_write=False), 300_000)
        # A write stays responsive: a quarter second by default, thirty at most.
        self.assertEqual(write_stdin_tool._effective_yield_ms(None, is_write=True), 250)
        self.assertEqual(write_stdin_tool._effective_yield_ms(10 ** 9, is_write=True), 30_000)


if __name__ == "__main__":
    unittest.main()
