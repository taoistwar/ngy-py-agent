"""Tests for the workspace scoped write_file tool.

Run from the repository root::

    uv run python test/tools/file_write_tool_test.py -v
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import EventCategory  # noqa: E402
from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.read_file import make_read_file_tool  # noqa: E402
from agent.tools.file_write_tool import make_write_file_tool  # noqa: E402
from agent.tools.read_ledger import ReadLedger  # noqa: E402


class WriteFileToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = ReadLedger()
        self.read = make_read_file_tool(base_dir=str(self.root), max_tokens=25000, ledger=self.ledger)
        self.tool = make_write_file_tool(base_dir=str(self.root), ledger=self.ledger)

    def tearDown(self):
        self._tmp.cleanup()

    def write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def read_bytes(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def read_whole(self, name: str, encoding: str = "utf-8") -> None:
        """Read the file the way the write guard expects."""
        result = self.read(name, 1, None, encoding)
        self.assertNotIn("error", result, result)

    def assert_patch_reverses(self, name: str, details) -> None:
        """The emitted diff describes old -> new, so it must reverse-apply now."""
        git = shutil.which("git")
        if not git:
            self.skipTest("git is not available")
        subprocess.run([git, "init", "-q"], cwd=self.root, check=False, capture_output=True)
        patch = self.root / "check.patch"
        patch.write_text(details["gitDiff"], encoding="utf-8", newline="")
        result = subprocess.run(
            [git, "apply", "--check", "--reverse", "-p1", patch.name],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_creates_a_new_file(self):
        outcome = self.tool("notes.txt", "alpha\nbeta\n", "utf-8")

        self.assertTrue(outcome.details["success"])
        self.assertTrue(outcome.details["created"])
        self.assertEqual(outcome.event_category, EventCategory.FILE_WRITE)
        self.assertEqual(self.read_bytes("notes.txt"), b"alpha\nbeta\n")
        self.assertEqual(outcome.model_text, "The file notes.txt has been created successfully.")
        # Nothing existed, so there is nothing to undo back to.
        self.assertNotIn("original_file", outcome.details)
        self.assertNotIn("gitDiff", outcome.details)

    def test_creation_reports_a_missing_parent_directory(self):
        outcome = self.tool("nested/deep/notes.txt", "x\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "parent_missing")
        # The hint must name a tool that actually exists.
        self.assertIn("code_interpreter", outcome.details["error"])
        self.assertFalse((self.root / "nested").exists())

    def test_replacing_a_file_that_was_never_read_is_refused(self):
        self.write_bytes("notes.txt", b"content from the user\n")

        outcome = self.tool("notes.txt", "mine\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "read_required")
        self.assertEqual(self.read_bytes("notes.txt"), b"content from the user\n")

    def test_a_partial_read_does_not_unlock_the_replacement(self):
        self.write_bytes("notes.txt", b"".join(f"line {index}\n".encode() for index in range(40)))
        partial = self.read("notes.txt", 1, 3, "utf-8")
        self.assertNotIn("error", partial)

        outcome = self.tool("notes.txt", "mine\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "read_required")

    def test_reading_from_line_one_without_limit_unlocks_the_replacement(self):
        self.write_bytes("notes.txt", b"alpha\nbeta\n")
        self.read_whole("notes.txt")

        outcome = self.tool("notes.txt", "GAMMA\n", "utf-8")

        self.assertTrue(outcome.details["success"])
        self.assertFalse(outcome.details["created"])
        self.assertTrue(outcome.details["content_changed"])
        self.assertEqual(self.read_bytes("notes.txt"), b"GAMMA\n")
        self.assertEqual(outcome.details["original_file"], "alpha\nbeta\n")
        self.assert_patch_reverses("notes.txt", outcome.details)

    def test_an_offset_read_does_not_unlock_the_replacement(self):
        self.write_bytes("notes.txt", b"alpha\nbeta\n")
        self.read("notes.txt", 2, None, "utf-8")

        outcome = self.tool("notes.txt", "mine\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "read_required")

    def test_a_change_between_read_and_write_is_detected(self):
        target = self.write_bytes("notes.txt", b"original\n")
        self.read_whole("notes.txt")
        target.write_bytes(b"someone else wrote a longer content\n")

        outcome = self.tool("notes.txt", "mine\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "file_changed")
        self.assertEqual(self.read_bytes("notes.txt"), b"someone else wrote a longer content\n")

    def test_written_content_replaces_rather_than_appends(self):
        self.write_bytes("notes.txt", b"alpha\n")
        self.read_whole("notes.txt")

        self.tool("notes.txt", "beta\n", "utf-8")

        self.assertEqual(self.read_bytes("notes.txt"), b"beta\n")

    def test_empty_content_empties_the_file(self):
        self.write_bytes("notes.txt", b"alpha\n")
        self.read_whole("notes.txt")

        self.tool("notes.txt", "", "utf-8")

        self.assertEqual(self.read_bytes("notes.txt"), b"")

    def test_identical_content_is_still_written_and_reported(self):
        target = self.write_bytes("notes.txt", b"alpha\n")
        self.read_whole("notes.txt")
        before = target.stat().st_mtime_ns

        outcome = self.tool("notes.txt", "alpha\n", "utf-8")

        self.assertTrue(outcome.details["success"])
        self.assertFalse(outcome.details["content_changed"])
        self.assertGreaterEqual(target.stat().st_mtime_ns, before)

    def test_replacing_keeps_the_crlf_line_endings(self):
        self.write_bytes("win.txt", b"a\r\nb\r\n")
        self.read_whole("win.txt")

        outcome = self.tool("win.txt", "x\ny\n", "utf-8")

        self.assertEqual(outcome.details["inserted_line_ending"], "\r\n")
        self.assertEqual(self.read_bytes("win.txt"), b"x\r\ny\r\n")

    def test_replacing_keeps_the_byte_order_mark(self):
        self.write_bytes("bom.txt", b"\xef\xbb\xbfalpha\n")
        self.read_whole("bom.txt")

        outcome = self.tool("bom.txt", "beta\n", "utf-8")

        self.assertTrue(outcome.details["bom"])
        self.assertEqual(self.read_bytes("bom.txt"), b"\xef\xbb\xbfbeta\n")

    def test_content_written_into_a_new_file_keeps_the_encoding(self):
        outcome = self.tool("gbk.txt", "第一行：内容\n", "gbk")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.details["encoding"], "gbk")
        self.assertEqual(self.read_bytes("gbk.txt"), "第一行：内容\n".encode("gbk"))

    def test_other_encodings_can_be_replaced_with_an_explicit_encoding(self):
        self.write_bytes("gbk.txt", "第一行：内容\n".encode("gbk"))
        self.read_whole("gbk.txt", "gbk")

        outcome = self.tool("gbk.txt", "第二行：新内容\n", "gbk")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.details["encoding"], "gbk")
        self.assertEqual(self.read_bytes("gbk.txt"), "第二行：新内容\n".encode("gbk"))

    def test_unknown_encoding_is_rejected(self):
        outcome = self.tool("notes.txt", "alpha\n", "not-a-codec")

        self.assertEqual(outcome.details["reason"], "unknown_encoding")

    def test_content_the_encoding_cannot_represent_is_rejected(self):
        self.write_bytes("gbk.txt", "内容\n".encode("gbk"))
        self.read_whole("gbk.txt", "gbk")

        outcome = self.tool("gbk.txt", "内容😀\n", "gbk")

        self.assertEqual(outcome.details["reason"], "unencodable_text")
        self.assertEqual(self.read_bytes("gbk.txt"), "内容\n".encode("gbk"))

    def test_a_directory_target_is_rejected(self):
        (self.root / "sub").mkdir()

        outcome = self.tool("sub", "x\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "not_a_file")

    def test_non_string_arguments_are_rejected_instead_of_raising(self):
        self.assertEqual(self.tool("notes.txt", 123, "utf-8").details["reason"], "invalid_argument")
        self.assertEqual(self.tool("", "x", "utf-8").details["reason"], "invalid_argument")
        self.assertEqual(self.tool("notes.txt", "x", 5).details["reason"], "invalid_argument")

    def test_writing_twice_in_a_row_is_allowed(self):
        self.tool("notes.txt", "first\n", "utf-8")

        outcome = self.tool("notes.txt", "second\n", "utf-8")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(self.read_bytes("notes.txt"), b"second\n")

    def test_an_edit_after_a_full_read_keeps_the_write_unlocked(self):
        from agent.tools.edit_file import make_edit_file_tool

        self.write_bytes("notes.txt", b"one\ntwo\n")
        self.read_whole("notes.txt")
        edit = make_edit_file_tool(base_dir=str(self.root), ledger=self.ledger)
        edited = edit("notes.txt", "two", "TWO", False, "utf-8")
        self.assertTrue(edited.details["success"])

        outcome = self.tool("notes.txt", "rewritten\n", "utf-8")

        self.assertTrue(outcome.details["success"], outcome.details)
        self.assertEqual(self.read_bytes("notes.txt"), b"rewritten\n")

    def test_an_edit_without_a_full_read_does_not_unlock_the_write(self):
        from agent.tools.edit_file import make_edit_file_tool

        self.write_bytes("notes.txt", b"one\ntwo\n")
        edit = make_edit_file_tool(base_dir=str(self.root), ledger=self.ledger)
        self.assertTrue(edit("notes.txt", "two", "TWO", False, "utf-8").details["success"])

        outcome = self.tool("notes.txt", "rewritten\n", "utf-8")

        self.assertEqual(outcome.details["reason"], "read_required")

    def test_file_mode_is_carried_over_to_the_new_inode(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions only")
        target = self.write_bytes("script.sh", b"#!/bin/sh\necho hi\n")
        os.chmod(target, 0o755)
        self.read_whole("script.sh")

        self.tool("script.sh", "#!/bin/sh\necho bye\n", "utf-8")

        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)

    def test_writes_outside_the_workspace_are_denied(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("SECRET", encoding="utf-8")
        self.addCleanup(outside.unlink)

        outcome = self.tool(str(outside), "LEAKED", "utf-8")

        self.assertEqual(outcome.details["reason"], "outside_workspace")
        self.assertEqual(outside.read_text(encoding="utf-8"), "SECRET")

    def test_unbound_session_honours_the_global_policy(self):
        target = self.root / "blocked.txt"
        target.write_text("CONTENT", encoding="utf-8")
        config = FileAccessConfig(deny_files=(target.resolve(),))
        ledger = ReadLedger()
        read = make_read_file_tool(base_dir=None, access_config=config, ledger=ledger)

        blocked = make_write_file_tool(base_dir=None, access_config=config, ledger=ledger)(
            str(target), "CHANGED", "utf-8"
        )

        self.assertEqual(blocked.details["reason"], "deny_file")
        self.assertEqual(target.read_text(encoding="utf-8"), "CONTENT")
        self.assertIn("error", read(str(target)))

    def test_registry_pairs_read_and_write_of_one_run(self):
        from agent.tools.registry import ToolRegistry

        self.write_bytes("notes.txt", b"alpha\n")
        registry = ToolRegistry(base_dir=str(self.root))

        registry.execute_tool("read_file", {"file_path": "notes.txt", "encoding": "utf-8"})
        outcome = registry.execute_tool(
            "write_file", {"file_path": "notes.txt", "content": "beta\n", "encoding": "utf-8"}
        )

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.event_category, EventCategory.FILE_WRITE)
        self.assertEqual(self.read_bytes("notes.txt"), b"beta\n")

    def test_the_read_ledger_is_scoped_to_one_run(self):
        from agent.tools.registry import ToolRegistry

        self.write_bytes("notes.txt", b"alpha\n")
        first = ToolRegistry(base_dir=str(self.root))
        first.execute_tool("read_file", {"file_path": "notes.txt", "encoding": "utf-8"})

        # A different run has its own ledger, so it must read the file itself.
        second = ToolRegistry(base_dir=str(self.root))
        outcome = second.execute_tool(
            "write_file", {"file_path": "notes.txt", "content": "beta\n", "encoding": "utf-8"}
        )

        self.assertEqual(outcome.details["reason"], "read_required")
        self.assertEqual(self.read_bytes("notes.txt"), b"alpha\n")

    def test_registry_exposes_the_write_tool_with_a_required_encoding(self):
        from agent.tools.registry import ToolRegistry

        registry = ToolRegistry(base_dir=str(self.root))

        self.assertIn("write_file", registry.tools)
        schemas = {item["function"]["name"]: item for item in registry.get_tool_schemas("openai")}
        self.assertEqual(
            schemas["write_file"]["function"]["parameters"]["required"],
            ["file_path", "content", "encoding"],
        )


if __name__ == "__main__":
    unittest.main()
