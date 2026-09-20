"""Tests for the exec (shell command) tool and its containment.

The commands are written per platform so the same expectations hold under
PowerShell on Windows and bash on Linux (CI runs the latter).

Run from the repository root::

    uv run python test/tools/exec_tool_test.py -v
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import EventCategory  # noqa: E402
from agent.tools.exec_tool import (  # noqa: E402
    EXEC_PARAMETERS,
    build_exec_description,
    list_background,
    stop_background,
)
from agent.tools.output_store import output_root_path  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402
from agent.tools.shell_platform import FAMILY_POWERSHELL, detect_shell  # noqa: E402


class ExecToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._out = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.outputs = Path(self._out.name)
        self.env = mock.patch.dict(os.environ, {"EXEC_OUTPUT_DIR": str(self.outputs)})
        self.env.start()
        self.registry = ToolRegistry(base_dir=str(self.root), session_id="test")
        self.shell = detect_shell()
        if self.shell is None:
            self.skipTest("no supported shell on this platform")
        self.powershell = self.shell.family == FAMILY_POWERSHELL

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()
        self._out.cleanup()

    # --- command helpers so the same test runs in both dialects -------------

    def echo(self, text: str) -> str:
        return f"Write-Output '{text}'" if self.powershell else f"echo '{text}'"

    def fail_with(self, code: int) -> str:
        return f"exit {code}"

    def sleep(self, seconds: int) -> str:
        return f"Start-Sleep -Seconds {seconds}" if self.powershell else f"sleep {seconds}"

    def touch(self, name: str) -> str:
        target = (self.root / name).as_posix()
        if self.powershell:
            return f"New-Item -ItemType File -Path '{target}' -Force | Out-Null"
        return f"touch '{target}'"

    def exec_cmd(self, arguments):
        """Call the tool. Named ``exec_cmd``, not ``run``: ``TestCase.run`` is how
        unittest executes the test itself."""
        return self.registry.execute_tool("exec", arguments)

    def read_file(self, arguments):
        """``read_file`` returns a dict, which ``execute_tool`` hands back as JSON."""
        return json.loads(self.registry.execute_tool("read_file", arguments))

    # --- description and schema -------------------------------------------

    def test_description_is_written_for_the_detected_shell(self):
        description = build_exec_description(self.shell)

        if self.powershell:
            self.assertIn("PowerShell", description)
        else:
            self.assertIn("POSIX shell", description)
        # The dialect hint and the millisecond contract must both reach the model.
        self.assertIn("MILLISECONDS", description)
        self.assertIn("read_file", description)

    def test_only_command_is_required(self):
        self.assertEqual(EXEC_PARAMETERS["required"], ["command"])

    def test_registry_exposes_exec(self):
        schemas = {item["function"]["name"]: item for item in self.registry.get_tool_schemas("openai")}

        self.assertIn("exec", schemas)
        self.assertEqual(schemas["exec"]["function"]["parameters"]["required"], ["command"])

    # --- running commands --------------------------------------------------

    def test_captures_stdout_stderr_and_exit_code(self):
        outcome = self.exec_cmd({"command": f"{self.echo('hello')}; {self.fail_with(2)}", "description": "Say hello"})

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.event_category, EventCategory.EXEC)
        self.assertEqual(outcome.details["exit_code"], 2)
        self.assertIn("hello", outcome.details["stdout"])
        self.assertFalse(outcome.details["interrupted"])
        self.assertEqual(outcome.details["cwd"], str(self.root))
        self.assertIn("Say hello", outcome.event_title)

    def test_runs_in_the_workspace_root(self):
        command = "Get-Location | Select-Object -ExpandProperty Path" if self.powershell else "pwd"
        outcome = self.exec_cmd({"command": command})

        # Windows reports the path with backslashes; compare on the directory name.
        self.assertIn(self.root.name, outcome.details["stdout"])
        self.assertEqual(outcome.details["cwd"], str(self.root))

    def test_timeout_stops_the_tree_and_reports_interrupted(self):
        outcome = self.exec_cmd(
            {"command": f"{self.sleep(20)}; {self.touch('finished.txt')}", "timeout": 1500}
        )

        self.assertTrue(outcome.details["interrupted"])
        self.assertFalse((self.root / "finished.txt").exists())

    def test_timeout_is_clamped_to_the_documented_range(self):
        outcome = self.exec_cmd({"command": self.echo("x"), "timeout": 1})

        self.assertTrue(outcome.details["success"])

    def test_invalid_arguments_are_structured_errors(self):
        cases = (
            {},
            {"command": ""},
            {"command": "x", "timeout": "soon"},
            {"command": "x", "run_in_background": "yes"},
            {"command": "x", "dangerouslyDisableSandbox": "yes"},
            {"command": "x", "description": 5},
        )

        for arguments in cases:
            with self.subTest(arguments=arguments):
                outcome = self.exec_cmd(arguments)
                self.assertFalse(outcome.details["success"])
                self.assertEqual(outcome.details["reason"], "invalid_argument")

    # --- containment reporting --------------------------------------------

    def test_containment_is_reported_honestly(self):
        outcome = self.exec_cmd({"command": self.echo("x")})
        containment = outcome.details["containment"]

        if os.name == "nt":
            self.assertEqual(containment["process_tree"], "job-object")
            self.assertIsNotNone(containment["resource_limits"])
        else:
            self.assertEqual(containment["process_tree"], "process-group")
            self.assertIsNone(containment["resource_limits"])
        # The integrity layer is not implemented yet and must not be claimed.
        self.assertEqual(containment["integrity_level"], "unchanged")
        self.assertIn("not a security boundary", containment["note"])

    def test_disable_sandbox_flag_is_reported(self):
        outcome = self.exec_cmd({"command": self.echo("x"), "dangerouslyDisableSandbox": True})

        self.assertTrue(outcome.details["containment"]["disabled_by_caller"])

    def test_secret_environment_variables_are_withheld(self):
        with mock.patch.dict(os.environ, {"DEMO_API_KEY": "secret-value"}):
            command = (
                "if ($env:DEMO_API_KEY) { 'present' } else { 'absent' }"
                if self.powershell
                else 'if [ -n "$DEMO_API_KEY" ]; then echo present; else echo absent; fi'
            )
            outcome = self.exec_cmd({"command": command})

        self.assertIn("absent", outcome.details["stdout"])
        self.assertGreaterEqual(outcome.details["withheld_env_vars"], 1)

    # --- large output and the read-only scratch root ----------------------

    def test_large_output_is_persisted_and_readable_again(self):
        if self.powershell:
            command = "1..20000 | ForEach-Object { \"line $_\" }"
        else:
            command = "seq 1 20000"
        outcome = self.exec_cmd({"command": command})

        self.assertTrue(outcome.details["output_truncated"])
        path = outcome.details["persistedOutputPath"]
        self.assertTrue(Path(path).is_file())
        self.assertIn("read_file", outcome.model_text)

        # The persisted file starts with the two header lines of _foreground_text,
        # so the last output line is 20000 + 2.
        tail = self.read_file({"file_path": path, "encoding": "utf-8", "offset": 20001, "limit": 2})
        self.assertNotIn("error", tail)
        self.assertIn("line 20000", tail["content"])

    def test_the_scratch_directory_can_be_read_but_not_written(self):
        scratch_dir = self.registry.output_directory

        readable = self.read_file({"file_path": (scratch_dir / "nope.txt").as_posix(), "encoding": "utf-8"})
        # Missing, but reached through the readable root instead of being refused.
        self.assertEqual(readable["reason"], "file_not_found")

        edited = self.registry.execute_tool(
            "edit_file",
            {
                "file_path": (scratch_dir / "nope.txt").as_posix(),
                "old_string": "a",
                "new_string": "b",
                "encoding": "utf-8",
            },
        )
        self.assertEqual(edited.details["reason"], "read_only_root")

        written = self.registry.execute_tool(
            "write_file",
            {"file_path": (scratch_dir / "new.txt").as_posix(), "content": "x\n", "encoding": "utf-8"},
        )
        self.assertEqual(written.details["reason"], "read_only_root")

    def test_binary_output_is_persisted_instead_of_inlined(self):
        if self.powershell:
            command = "[Console]::OpenStandardOutput().Write([byte[]](1,0,2,0,3),0,5)"
        else:
            command = "printf '\\001\\000\\002\\000\\003'"
        outcome = self.exec_cmd({"command": command})

        self.assertTrue(outcome.details["output_binary"])
        self.assertEqual(outcome.details["stdout"], "")
        self.assertTrue(Path(outcome.details["persistedOutputPath"]).is_file())
        self.assertIn("binary output", outcome.model_text)

    # --- background -------------------------------------------------------

    def test_background_command_returns_a_pid_and_a_log(self):
        outcome = self.exec_cmd(
            {"command": f"{self.echo('bg-1')}; {self.sleep(1)}; {self.echo('bg-2')}", "run_in_background": True}
        )

        self.assertTrue(outcome.details["background"])
        self.assertIsInstance(outcome.details["pid"], int)
        log_path = Path(outcome.details["persistedOutputPath"])
        self.assertEqual(log_path.suffix, ".log")
        self.assertTrue(Path(outcome.details["pidFile"]).is_file())

        deadline = time.monotonic() + 20
        content = ""
        while time.monotonic() < deadline:
            content = log_path.read_text(encoding="utf-8", errors="replace")
            if "bg-2" in content:
                break
            time.sleep(0.3)
        self.assertIn("bg-2", content)

    def test_background_commands_can_be_stopped(self):
        outcome = self.exec_cmd({"command": self.sleep(60), "run_in_background": True})
        pid = outcome.details["pid"]

        self.assertTrue(any(item["pid"] == pid for item in list_background()))
        self.assertTrue(stop_background(pid))
        self.assertFalse(stop_background(pid))

    def test_output_directory_is_scoped_per_workspace_and_session(self):
        mine = output_root_path(str(self.root), "test")

        self.assertEqual(mine, self.registry.output_directory)
        self.assertNotEqual(mine, output_root_path(str(self.root), "other"))
        self.assertNotEqual(mine, output_root_path(str(self.root.parent), "test"))


if __name__ == "__main__":
    unittest.main()
