"""Tests for ``exec_command``'s ``tty`` parameter: the declaration, the refusal, and
what a real pseudo terminal does to a command.

Split from ``exec_command_test.py`` because a terminal is a second execution
transport: same tool, same contract, different plumbing (ADR 0009). The integration
class is skipped where no terminal can be allocated; the declaration and refusal
tests run everywhere.

Run from the repository root::

    uv run python test/tools/exec_command/tty_test.py -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools import pty_session  # noqa: E402
from agent.tools.exec_command import EXEC_PARAMETERS, build_exec_description  # noqa: E402
from agent.tools.exec_command import runtime as runtime_module  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.shell_platform import FAMILY_POWERSHELL, detect_shell  # noqa: E402
from agent.tools.write_stdin import rules as rules_module  # noqa: E402

WRITE_YIELD_MS = 8_000


class TtyToolTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._out = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.env = mock.patch.dict(os.environ, {"EXEC_OUTPUT_DIR": str(self._out.name)})
        self.env.start()
        self.registry = ToolRegistry(base_dir=str(self.root), session_id="test")
        self.shell = detect_shell()
        if self.shell is None:
            self.skipTest("no supported shell on this platform")
        self.powershell = self.shell.family == FAMILY_POWERSHELL
        self.sessions = []

    def tearDown(self):
        for session_id in self.sessions:
            self.registry.execute_tool(
                "write_stdin", {"session_id": session_id, "chars": "\u0003", "yield_time_ms": 5_000}
            )
        self.env.stop()
        self._out.cleanup()
        self._tmp.cleanup()

    # --- helpers ----------------------------------------------------------

    def exec_cmd(self, arguments):
        return self.registry.execute_tool("exec_command", arguments)

    def script(self, source, name="tty_helper.py"):
        path = self.root / name
        path.write_text(source, encoding="utf-8")
        return path

    def run_script(self, path):
        """Quote ``python -u script`` for the shell the exec tool actually uses."""
        if self.powershell:
            return f'& "{sys.executable}" -u "{path}"'
        return f'"{sys.executable}" -u "{path}"'

    def fail_with(self, code: int) -> str:
        return f"exit {code}"

    def start_session(self, arguments):
        outcome = self.exec_cmd(arguments)
        self.assertTrue(outcome.details.get("background"), outcome.model_text)
        session_id = outcome.details["session_id"]
        self.sessions.append(session_id)
        return outcome, session_id

    def wait_for_output(self, session_id, needle, deadline_seconds=20.0):
        """Collect a session's output until ``needle`` shows up in it."""
        collected = ""
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            with mock.patch.object(rules_module, "POLL_MIN_YIELD_MS", 200):
                outcome = self.registry.execute_tool(
                    "write_stdin", {"session_id": session_id, "yield_time_ms": 5_000}
                )
            collected += outcome.details.get("output", "")
            if needle in collected:
                return collected
            if not outcome.details.get("running"):
                break
            time.sleep(0.2)
        self.fail(f"{needle!r} never appeared; saw {collected!r}")


class TtyDeclarationTest(TtyToolTestBase):
    """What the model is told, and how a bad or impossible request is answered."""

    def test_tty_is_declared_as_an_optional_boolean(self):
        properties = EXEC_PARAMETERS["properties"]

        self.assertEqual(properties["tty"]["type"], "boolean")
        self.assertIn("PTY", properties["tty"]["description"])
        self.assertIn("plain pipes", properties["tty"]["description"])
        self.assertNotIn("tty", EXEC_PARAMETERS["required"])

    def test_the_description_states_what_a_terminal_costs(self):
        description = build_exec_description(self.shell)

        # The three consequences that would otherwise surprise the model.
        self.assertIn("pseudo terminal", description)
        self.assertIn("merges stderr into stdout", description)
        self.assertIn("run_in_background", description)
        if self.powershell:
            self.assertIn("handshake", description)

    def test_non_boolean_tty_is_rejected(self):
        outcome = self.exec_cmd({"command": "x", "tty": "yes"})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "invalid_argument")
        self.assertEqual(outcome.details["argument"], "tty")

    def test_an_unavailable_terminal_is_refused_instead_of_downgraded(self):
        with mock.patch.object(
            pty_session, "availability", return_value=(False, "no terminal here")
        ):
            outcome = self.exec_cmd({"command": "echo ran-anyway", "tty": True})

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "tty_unavailable")
        self.assertIn("no terminal here", outcome.model_text)
        # Nothing ran on pipes behind the model's back: there is no result to read.
        self.assertNotIn("exit_code", outcome.details)

    def test_the_two_renderings_differ_only_for_a_terminal(self):
        model_text, stored_text = runtime_module._render_foreground_text(
            0, "a\r\nb\r\n", "", False, 1_000, True
        )

        self.assertNotIn("\r", model_text)
        self.assertIn("a\r\nb", stored_text)
        # Pipes keep exactly one rendering: their bytes are not normalised at all.
        pipe_model, pipe_stored = runtime_module._render_foreground_text(
            0, "a\r\nb", "", False, 1_000, False
        )
        self.assertEqual(pipe_model, pipe_stored)


@unittest.skipUnless(pty_session.availability()[0], "no pseudo terminal on this machine")
class TtyIntegrationTest(TtyToolTestBase):
    """A real terminal: the only tests that can prove tty is not a rename of pipes."""

    def test_a_tty_program_sees_a_terminal(self):
        path = self.script("import sys\nprint('isatty', sys.stdout.isatty())\n")

        outcome = self.exec_cmd({"command": self.run_script(path), "tty": True})

        self.assertTrue(outcome.details["success"], outcome.model_text)
        self.assertIn("isatty True", outcome.details["stdout"])
        # The flag is reported back, and the model gets LF lines, not CRLF.
        self.assertTrue(outcome.details["tty"])
        self.assertNotIn("\r", outcome.model_text)

    def test_a_pipe_program_does_not_see_a_terminal(self):
        path = self.script("import sys\nprint('isatty', sys.stdout.isatty())\n")

        outcome = self.exec_cmd({"command": self.run_script(path)})

        self.assertFalse(outcome.details["tty"])
        self.assertIn("isatty False", outcome.details["stdout"])

    def test_stderr_is_merged_into_stdout(self):
        path = self.script(
            "import sys\n"
            "sys.stderr.write('trouble\\n')\n"
            "sys.stderr.flush()\n"
            "sys.stdout.write('visible\\n')\n"
        )

        outcome = self.exec_cmd({"command": self.run_script(path), "tty": True})

        self.assertTrue(outcome.details["success"], outcome.model_text)
        # A terminal is one stream: there is no stderr left to report separately.
        self.assertEqual(outcome.details["stderr"], "")
        self.assertIn("trouble", outcome.details["stdout"])
        self.assertIn("visible", outcome.details["stdout"])

    def test_the_exit_code_survives_the_terminal(self):
        # ``exit N`` is the shell's own builtin, so the number is the shell's answer.
        # A *native* command's non-zero code is not asserted here: pwsh turns a
        # failing native command that wrote to stderr into exit code 1 on both
        # transports, so that is the shell's policy, not the terminal's.
        outcome = self.exec_cmd({"command": self.fail_with(2), "tty": True})

        self.assertEqual(outcome.details["exit_code"], 2)
        self.assertTrue(outcome.details["tty"])

    def test_a_foreground_terminal_times_out_like_a_pipe(self):
        path = self.script("import time\ntime.sleep(30)\n")

        outcome = self.exec_cmd({"command": self.run_script(path), "tty": True, "timeout": 2_000})

        self.assertTrue(outcome.details["interrupted"])
        self.assertTrue(outcome.details["tty"])

    def test_a_background_terminal_pumps_its_output_into_the_log(self):
        path = self.script(
            "import sys, time\n"
            "print('pumped')\n"
            "sys.stdout.flush()\n"
            "time.sleep(10)\n"
        )

        outcome, _ = self.start_session(
            {"command": self.run_script(path), "tty": True, "run_in_background": True}
        )

        self.assertTrue(outcome.details["tty"])
        log_path = Path(outcome.details["persistedOutputPath"])
        deadline = time.monotonic() + 20
        content = ""
        while time.monotonic() < deadline:
            content = log_path.read_text(encoding="utf-8", errors="replace")
            if "pumped" in content:
                break
            time.sleep(0.3)
        self.assertIn("pumped", content)

    def test_a_background_terminal_session_answers_write_stdin(self):
        path = self.script(
            "import sys\n"
            "line = sys.stdin.readline()\n"
            "sys.stdout.write('echo:' + line.strip() + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        _, session_id = self.start_session(
            {"command": self.run_script(path), "tty": True, "run_in_background": True}
        )

        # A plain newline is what the model sends; on Windows the terminal path turns
        # it into the carriage return ConPTY treats as Enter (ADR 0009).
        written = self.registry.execute_tool(
            "write_stdin", {"session_id": session_id, "chars": "hello\n", "yield_time_ms": WRITE_YIELD_MS}
        )
        self.assertTrue(written.details["success"], written.model_text)
        self.assertTrue(written.details["tty"])

        collected = written.details.get("output", "")
        if "echo:hello" not in collected:
            collected += self.wait_for_output(session_id, "echo:hello")
        self.assertIn("echo:hello", collected)


if __name__ == "__main__":
    unittest.main()
