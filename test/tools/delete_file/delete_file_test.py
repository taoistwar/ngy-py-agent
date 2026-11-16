"""Tests for the workspace scoped delete_file tool.

Run from the repository root::

    uv run python test/tools/delete_file/delete_file_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import EventCategory  # noqa: E402
from agent.tools.delete_file import make_delete_file_tool  # noqa: E402
from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.file_limits import MAX_FULL_READ_BYTES  # noqa: E402
from agent.tools.read_file import make_read_file_tool  # noqa: E402
from agent.tools.read_ledger import ReadLedger  # noqa: E402
from agent.tools.write_file import make_write_file_tool  # noqa: E402


class DeleteFileToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = ReadLedger()
        self.read = make_read_file_tool(
            base_dir=str(self.root), max_tokens=25000, ledger=self.ledger
        )
        self.write = make_write_file_tool(base_dir=str(self.root), ledger=self.ledger)
        self.tool = make_delete_file_tool(base_dir=str(self.root), ledger=self.ledger)

    def tearDown(self):
        self._tmp.cleanup()

    def write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def read_whole(self, name: str, encoding: str = "utf-8") -> None:
        """Read the file the way the delete guard expects."""
        result = self.read(name, 1, None, encoding)
        self.assertNotIn("error", result, result)

    def test_deletes_a_file_read_in_full_in_this_run(self):
        target = self.write_bytes("notes.txt", b"alpha\nbeta\n")
        self.read_whole("notes.txt")

        outcome = self.tool("notes.txt")

        self.assertTrue(outcome.details["success"])
        self.assertTrue(outcome.details["content_verified"])
        self.assertEqual(outcome.details["file_path"], "notes.txt")
        self.assertEqual(outcome.details["file_bytes"], 11)
        self.assertEqual(outcome.event_category, EventCategory.FILE_DELETE)
        self.assertEqual(outcome.model_text, "The file notes.txt has been deleted successfully.")
        self.assertFalse(target.exists())

    def test_deleting_a_file_that_was_never_read_is_refused(self):
        target = self.write_bytes("notes.txt", b"content from the user\n")

        outcome = self.tool("notes.txt")

        self.assertEqual(outcome.details["reason"], "read_required")
        self.assertFalse(outcome.details["success"])
        self.assertTrue(target.exists())

    def test_a_partial_read_does_not_unlock_the_delete(self):
        target = self.write_bytes(
            "notes.txt", b"".join(f"line {index}\n".encode() for index in range(40))
        )
        self.assertNotIn("error", self.read("notes.txt", 1, 3, "utf-8"))

        outcome = self.tool("notes.txt")

        self.assertEqual(outcome.details["reason"], "read_required")
        self.assertTrue(target.exists())

    def test_a_change_between_read_and_delete_is_detected(self):
        target = self.write_bytes("notes.txt", b"original\n")
        self.read_whole("notes.txt")
        target.write_bytes(b"someone else wrote a longer content\n")

        outcome = self.tool("notes.txt")

        self.assertEqual(outcome.details["reason"], "file_changed")
        self.assertTrue(target.exists())

    def test_a_file_this_run_wrote_can_be_deleted_without_reading_it(self):
        self.assertTrue(self.write("notes.txt", "scratch\n", "utf-8").details["success"])

        outcome = self.tool("notes.txt")

        self.assertTrue(outcome.details["success"], outcome.details)
        self.assertFalse((self.root / "notes.txt").exists())

    def test_an_empty_file_needs_no_read(self):
        target = self.write_bytes("empty.txt", b"")

        outcome = self.tool("empty.txt")

        self.assertTrue(outcome.details["success"], outcome.details)
        self.assertEqual(outcome.details["file_bytes"], 0)
        self.assertTrue(outcome.details["content_verified"])
        self.assertFalse(target.exists())

    def test_a_file_too_large_to_read_is_deleted_and_reported_as_unverified(self):
        # A file the reader refuses to read in full could never be deleted if the
        # guard were absolute, and the model would fall back to a shell command that
        # escapes the file policy entirely.
        target = self.write_bytes("big.log", b"x" * (MAX_FULL_READ_BYTES + 1))

        outcome = self.tool("big.log")

        self.assertTrue(outcome.details["success"], outcome.details)
        self.assertFalse(outcome.details["content_verified"])
        self.assertEqual(outcome.details["file_bytes"], MAX_FULL_READ_BYTES + 1)
        self.assertFalse(target.exists())

    def test_a_missing_file_is_reported_instead_of_silently_succeeding(self):
        outcome = self.tool("notes.txt")

        self.assertEqual(outcome.details["reason"], "not_found")
        self.assertIn("glob", outcome.details["error"])

    def test_a_directory_target_is_refused(self):
        (self.root / "sub").mkdir()

        outcome = self.tool("sub")

        self.assertEqual(outcome.details["reason"], "not_a_file")
        self.assertTrue((self.root / "sub").is_dir())
        # The hint must name a tool that actually exists.
        self.assertIn("code_interpreter", outcome.details["error"])

    def test_non_string_arguments_are_rejected_instead_of_raising(self):
        self.assertEqual(self.tool("").details["reason"], "invalid_argument")
        self.assertEqual(self.tool(123).details["reason"], "invalid_argument")
        self.assertEqual(self.tool(None).details["reason"], "invalid_argument")

    def test_deletes_outside_the_workspace_are_denied(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("SECRET", encoding="utf-8")
        self.addCleanup(outside.unlink)

        outcome = self.tool(str(outside))

        self.assertEqual(outcome.details["reason"], "outside_workspace")
        self.assertTrue(outside.exists())

    def test_a_read_only_root_cannot_be_deleted_from(self):
        read_only = tempfile.TemporaryDirectory()
        self.addCleanup(read_only.cleanup)
        target = Path(read_only.name) / "result.txt"
        target.write_text("persisted\n", encoding="utf-8")
        tool = make_delete_file_tool(
            base_dir=str(self.root), ledger=self.ledger, extra_read_roots=(read_only.name,)
        )

        outcome = tool(str(target))

        self.assertEqual(outcome.details["reason"], "read_only_root")
        self.assertTrue(target.exists())

    def test_the_ledger_entry_is_forgotten_after_the_delete(self):
        target = self.write_bytes("notes.txt", b"alpha\n")
        self.read_whole("notes.txt")
        self.assertTrue(self.tool("notes.txt").details["success"])
        # Re-created by something outside the tools: the old read no longer counts.
        target.write_bytes(b"alpha\n")

        outcome = self.tool("notes.txt")

        self.assertEqual(outcome.details["reason"], "read_required")
        self.assertTrue(target.exists())

    def test_unbound_session_honours_the_global_policy(self):
        target = self.root / "blocked.txt"
        target.write_text("CONTENT", encoding="utf-8")
        config = FileAccessConfig(deny_files=(target.resolve(),))

        blocked = make_delete_file_tool(
            base_dir=None, access_config=config, ledger=ReadLedger()
        )(str(target))

        self.assertEqual(blocked.details["reason"], "deny_file")
        self.assertTrue(target.exists())

    def test_registry_pairs_the_read_and_the_delete_of_one_run(self):
        from agent.tools.registry import ToolRegistry

        target = self.write_bytes("notes.txt", b"alpha\n")
        registry = ToolRegistry(base_dir=str(self.root))

        registry.execute_tool("read_file", {"file_path": "notes.txt", "encoding": "utf-8"})
        outcome = registry.execute_tool("delete_file", {"file_path": "notes.txt"})

        self.assertTrue(outcome.details["success"], outcome.details)
        self.assertEqual(outcome.event_category, EventCategory.FILE_DELETE)
        self.assertFalse(target.exists())

    def test_the_read_ledger_is_still_scoped_to_one_run(self):
        from agent.tools.registry import ToolRegistry

        target = self.write_bytes("notes.txt", b"alpha\n")
        first = ToolRegistry(base_dir=str(self.root))
        first.execute_tool("read_file", {"file_path": "notes.txt", "encoding": "utf-8"})

        second = ToolRegistry(base_dir=str(self.root))
        outcome = second.execute_tool("delete_file", {"file_path": "notes.txt"})

        self.assertEqual(outcome.details["reason"], "read_required")
        self.assertTrue(target.exists())

    def test_registry_exposes_the_tool_as_a_confirmable_write(self):
        from agent.tools.registry import ToolRegistry

        registry = ToolRegistry(base_dir=str(self.root))

        self.assertIn("delete_file", registry.tools)
        self.assertEqual(registry.tools["delete_file"]["permission"], "write")
        # A persisted "always" rule would outlive the file it was granted for.
        self.assertEqual(set(registry.tools["delete_file"]["scopes"]), {"once", "session"})
        schemas = {item["function"]["name"]: item for item in registry.get_tool_schemas("openai")}
        self.assertEqual(
            schemas["delete_file"]["function"]["parameters"]["required"], ["file_path"]
        )


if __name__ == "__main__":
    unittest.main()
