"""Tests for the workspace scoped edit_file tool.

Run from the repository root::

    uv run python test/tools/edit_file/edit_file_test.py -v
"""

import codecs
import json
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
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import EventCategory, ToolOutcome  # noqa: E402
from agent.tools.edit_file import make_edit_file_tool  # noqa: E402
from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.file_patch import CONTEXT_LINES  # noqa: E402


class EditFileToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tool = make_edit_file_tool(base_dir=str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def write_text(self, name: str, text: str) -> Path:
        return self.write_bytes(name, text.encode("utf-8"))

    def read_bytes(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def test_replaces_unique_match_and_returns_a_one_line_summary(self):
        self.write_text("notes.txt", "alpha\nbeta\ngamma\n")

        outcome = self.tool("notes.txt", "beta", "BETA")

        self.assertEqual(outcome.model_text, "The file notes.txt has been updated successfully.")
        self.assertEqual(outcome.event_category, EventCategory.FILE_EDIT)
        self.assertEqual(outcome.event_title, "File edit: notes.txt")
        self.assertEqual(self.read_bytes("notes.txt"), b"alpha\nBETA\ngamma\n")
        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.details["match_count"], 1)

    def test_details_carry_the_original_file_and_the_arguments(self):
        self.write_text("notes.txt", "alpha\nbeta\n")

        details = self.tool("notes.txt", "beta", "BETA").details

        self.assertEqual(details["file_path"], "notes.txt")
        self.assertEqual(details["old_string"], "beta")
        self.assertEqual(details["new_string"], "BETA")
        self.assertFalse(details["replace_all"])
        self.assertEqual(details["original_file"], "alpha\nbeta\n")

    def test_structured_patch_reports_three_lines_of_context(self):
        self.write_text("notes.txt", "l1\nl2\nl3\nl4\nl5\nl6\nl7\nl8\n")

        hunk = self.tool("notes.txt", "l4", "X4").details["structured_patch"][0]

        self.assertEqual(hunk["oldStart"], 1)
        self.assertEqual(hunk["oldLines"], 7)
        self.assertEqual(hunk["newStart"], 1)
        self.assertEqual(hunk["newLines"], 7)
        self.assertEqual(hunk["lines"][0], " l1")
        self.assertIn("-l4", hunk["lines"])
        self.assertIn("+X4", hunk["lines"])
        self.assertEqual(hunk["lines"][-1], " l7")

    def test_git_diff_is_a_valid_unified_patch(self):
        self.write_text("notes.txt", "l1\nl2\nl3\nl4\nl5\nl6\nl7\nl8\n")

        diff = self.tool("notes.txt", "l4", "X4").details["gitDiff"]

        self.assertIn("diff --git a/notes.txt b/notes.txt", diff)
        self.assertIn("--- a/notes.txt", diff)
        self.assertIn("+++ b/notes.txt", diff)
        self.assertIn("@@ -1,7 +1,7 @@", diff)

    def test_multiple_matches_are_rejected_without_replace_all(self):
        self.write_text("notes.txt", "x\nx\n")

        outcome = self.tool("notes.txt", "x", "y")

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "multiple_matches")
        self.assertEqual(outcome.details["match_count"], 2)
        self.assertIn("more surrounding context", outcome.model_text)
        self.assertEqual(self.read_bytes("notes.txt"), b"x\nx\n")

    def test_replace_all_rewrites_every_occurrence(self):
        self.write_text("notes.txt", "x\nx\n")

        outcome = self.tool("notes.txt", "x", "y", True)

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.details["match_count"], 2)
        self.assertEqual(self.read_bytes("notes.txt"), b"y\ny\n")

    def test_adjacent_matches_merge_into_one_git_diff_hunk(self):
        self.write_text("notes.txt", "head\nfoo\nmid\nfoo\ntail\n")

        details = self.tool("notes.txt", "foo", "bar", True).details
        diff = details["gitDiff"]

        self.assertEqual(len(details["structured_patch"]), 2)
        self.assertEqual(sum(1 for line in diff.splitlines() if line.startswith("@@")), 1)
        self.assertEqual(diff.count("-foo"), 2)
        self.assertEqual(diff.count("+bar"), 2)

    def test_distant_matches_produce_two_git_diff_hunks(self):
        self.write_text("notes.txt", "x1\nL\nx2\nx3\nx4\nx5\nx6\nx7\nx8\nL\nx9\n")

        diff = self.tool("notes.txt", "L", "M", True).details["gitDiff"]

        self.assertEqual(sum(1 for line in diff.splitlines() if line.startswith("@@")), 2)
        self.assertIn("@@ -1,5 +1,5 @@", diff)
        self.assertIn("@@ -7,5 +7,5 @@", diff)

    def test_replace_all_shifts_new_start_of_later_hunks(self):
        self.write_text("notes.txt", "a\nL\nc\nd\ne\nf\ng\nh\ni\nL\nk\n")

        hunks = self.tool("notes.txt", "L", "L1\nL2", True).details["structured_patch"]

        self.assertEqual(hunks[0]["oldStart"], 1)
        self.assertEqual(hunks[0]["newStart"], 1)
        self.assertEqual(hunks[1]["oldStart"], 7)
        self.assertEqual(hunks[1]["newStart"], 8)

    def test_missing_match_is_reported(self):
        self.write_text("notes.txt", "alpha\n")

        outcome = self.tool("notes.txt", "nope", "yes")

        self.assertEqual(outcome.details["reason"], "no_match")
        self.assertEqual(outcome.details["match_count"], 0)
        self.assertEqual(self.read_bytes("notes.txt"), b"alpha\n")

    def test_empty_and_identical_strings_are_rejected(self):
        self.write_text("notes.txt", "alpha\n")

        self.assertEqual(self.tool("notes.txt", "", "x").details["reason"], "empty_old_string")
        self.assertEqual(self.tool("notes.txt", "alpha", "alpha").details["reason"], "identical_strings")

    def test_empty_new_string_deletes_the_match(self):
        self.write_text("notes.txt", "alpha\nbeta\n")

        self.tool("notes.txt", "alpha\n", "")

        self.assertEqual(self.read_bytes("notes.txt"), b"beta\n")

    def test_crlf_line_endings_are_preserved(self):
        self.write_bytes("win.txt", b"a\r\nb\r\n")

        outcome = self.tool("win.txt", "a\r\nb\r\n", "a\r\nB\r\n")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(self.read_bytes("win.txt"), b"a\r\nB\r\n")

    def test_matching_is_strict_about_line_endings(self):
        self.write_bytes("win.txt", b"a\r\nb\r\n")

        outcome = self.tool("win.txt", "a\nb\n", "x")

        self.assertEqual(outcome.details["reason"], "no_match")
        self.assertEqual(self.read_bytes("win.txt"), b"a\r\nb\r\n")

    def test_bom_is_preserved(self):
        self.write_bytes("bom.txt", codecs.BOM_UTF8 + b"alpha\n")

        outcome = self.tool("bom.txt", "alpha", "beta")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(self.read_bytes("bom.txt"), codecs.BOM_UTF8 + b"beta\n")

    def test_non_utf8_files_are_reported_with_encoding_hints(self):
        self.write_bytes("latin.txt", b"caf\xe9\n")

        outcome = self.tool("latin.txt", "caf", "tea")

        self.assertEqual(outcome.details["reason"], "decode_failed")
        self.assertTrue(outcome.details["suggested_encodings"])
        self.assertEqual(self.read_bytes("latin.txt"), b"caf\xe9\n")

    def test_other_encodings_can_be_edited_with_an_explicit_encoding(self):
        payload = "第一行：中文\n第二行：内容\n".encode("gbk")
        self.write_bytes("gbk.txt", payload)

        outcome = self.tool("gbk.txt", "第二行", "第二行(改)", False, "gbk")

        self.assertTrue(outcome.details["success"])
        self.assertEqual(outcome.details["encoding"], "gbk")
        self.assertEqual(
            self.read_bytes("gbk.txt"),
            payload.replace("第二行".encode("gbk"), "第二行(改)".encode("gbk")),
        )

    def test_missing_file_is_reported(self):
        outcome = self.tool("nope.txt", "a", "b")

        self.assertEqual(outcome.details["reason"], "file_not_found")

    def test_edits_outside_the_workspace_are_denied(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("SECRET", encoding="utf-8")
        self.addCleanup(outside.unlink)

        outcome = self.tool(str(outside), "SECRET", "LEAKED")

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "outside_workspace")
        self.assertEqual(outside.read_text(encoding="utf-8"), "SECRET")

    def test_unbound_session_honours_the_global_policy(self):
        target = self.root / "blocked.txt"
        target.write_text("CONTENT", encoding="utf-8")
        config = FileAccessConfig(deny_files=(target.resolve(),))

        blocked = make_edit_file_tool(base_dir=None, access_config=config)(str(target), "CONTENT", "CHANGED")

        self.assertEqual(blocked.details["reason"], "deny_file")
        self.assertEqual(target.read_text(encoding="utf-8"), "CONTENT")

    def test_registry_returns_the_outcome_untouched(self):
        from agent.tools.registry import ToolRegistry

        self.write_text("notes.txt", "alpha\n")
        registry = ToolRegistry(base_dir=str(self.root))

        outcome = registry.execute_tool(
            "edit_file", {"file_path": "notes.txt", "old_string": "alpha", "new_string": "beta"}
        )

        self.assertIsInstance(outcome, ToolOutcome)
        self.assertEqual(outcome.event_category, EventCategory.FILE_EDIT)
        self.assertEqual(outcome.model_text, "The file notes.txt has been updated successfully.")

    def test_details_are_json_serializable_for_event_storage(self):
        self.write_text("notes.txt", "alpha\n")

        details = self.tool("notes.txt", "alpha", "beta").details

        self.assertIsInstance(json.dumps(details), str)

    def test_context_lines_constant_matches_the_documented_value(self):
        self.assertEqual(CONTEXT_LINES, 3)

    def assert_patch_applies(self, name, original, details):
        """Ask git whether the emitted diff really applies to the pre-image."""
        git = shutil.which("git")
        if not git:
            self.skipTest("git is not available")
        subprocess.run([git, "init", "-q"], cwd=self.root, check=False, capture_output=True)
        self.write_bytes(name, original)
        patch = self.root / "check.patch"
        # newline="" keeps the patch bytes intact on Windows.
        patch.write_text(details["gitDiff"], encoding="utf-8", newline="")
        result = subprocess.run(
            [git, "apply", "--check", "-p1", patch.name],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sub_line_match_produces_a_whole_line_hunk(self):
        self.write_bytes("sub.txt", b"xfooy\n")

        details = self.tool("sub.txt", "foo", "bar").details

        self.assertEqual(details["structured_patch"][0]["lines"], ["-xfooy", "+xbary"])
        self.assertEqual(self.read_bytes("sub.txt"), b"xbary\n")

    def test_matches_on_one_line_collapse_into_a_single_hunk(self):
        self.write_bytes("same.txt", b"aaa\n")

        details = self.tool("same.txt", "a", "b", True).details

        self.assertEqual(len(details["structured_patch"]), 1)
        self.assertEqual(details["structured_patch"][0]["lines"], ["-aaa", "+bbb"])
        self.assertEqual(self.read_bytes("same.txt"), b"bbb\n")

    def test_git_diff_applies_to_the_original_file(self):
        cases = (
            ("lf.txt", b"one\ntwo\nthree\n", "two", "TWO", False),
            ("sub.txt", b"xfooy\n", "foo", "bar", False),
            ("same.txt", b"aaa\n", "a", "b", True),
            ("crlf.txt", b"alpha\r\nbeta\r\n", "beta", "BETA", False),
            ("crlf2.txt", b"a\r\nb\r\nc\r\n", "a\r\nb\r\n", "x\r\n", False),
            ("multi.txt", b"head\nfoo\nmid\nfoo\ntail\n", "foo", "bar", True),
        )

        for name, original, old, new, replace_all in cases:
            with self.subTest(name=name):
                self.write_bytes(name, original)
                details = self.tool(name, old, new, replace_all).details
                self.assertTrue(details["success"], details)
                self.assert_patch_applies(name, original, details)

    def test_structured_patch_drops_carriage_returns_but_git_diff_keeps_them(self):
        self.write_bytes("crlf.txt", b"alpha\r\nbeta\r\n")

        details = self.tool("crlf.txt", "beta", "BETA").details

        self.assertNotIn("\r", "".join(details["structured_patch"][0]["lines"]))
        self.assertIn("-beta\r", details["gitDiff"])

    def test_inserted_text_adopts_the_file_line_ending(self):
        self.write_bytes("crlf.txt", b"a\r\nb\r\n")

        details = self.tool("crlf.txt", "a", "x\ny").details

        self.assertEqual(details["inserted_line_ending"], "\r\n")
        self.assertEqual(self.read_bytes("crlf.txt"), b"x\r\ny\r\nb\r\n")

    def test_untouched_bytes_survive_a_non_bijective_encoding(self):
        # cp932 decodes b'\x87\x90' and re-encodes it as b'\x81\xe0', so rewriting
        # the whole file would silently change a neighbour the edit never touched.
        payload = "漢字".encode("cp932") + b"\x87\x90" + "です".encode("cp932")
        self.write_bytes("cp932.txt", payload)

        details = self.tool("cp932.txt", "漢字", "漢字X", False, "cp932").details

        self.assertTrue(details["success"])
        self.assertEqual(
            self.read_bytes("cp932.txt"),
            "漢字X".encode("cp932") + b"\x87\x90" + "です".encode("cp932"),
        )

    def test_strings_the_encoding_cannot_represent_are_rejected(self):
        original = "内容\n".encode("gbk")
        self.write_bytes("gbk.txt", original)

        details = self.tool("gbk.txt", "内容", "内容😀", False, "gbk").details

        self.assertEqual(details["reason"], "unencodable_text")
        self.assertEqual(self.read_bytes("gbk.txt"), original)

    def test_non_string_arguments_are_rejected_instead_of_raising(self):
        self.write_text("notes.txt", "alpha\n")

        self.assertEqual(self.tool("notes.txt", "alpha", 123).details["reason"], "invalid_argument")
        self.assertEqual(
            self.tool("notes.txt", "alpha", "beta", "true").details["reason"], "invalid_argument"
        )

    def test_concurrent_change_is_detected_before_writing(self):
        from unittest import mock

        import agent.tools.edit_file.replace as replace_module

        self.write_text("race.txt", "alpha\n")
        original_splice = replace_module.splice_bytes

        def splice_then_someone_else_writes(*args, **kwargs):
            result = original_splice(*args, **kwargs)
            self.write_text("race.txt", "overwritten by another process\n")
            return result

        with mock.patch.object(replace_module, "splice_bytes", splice_then_someone_else_writes):
            details = self.tool("race.txt", "alpha", "beta").details

        self.assertEqual(details["reason"], "file_changed")
        self.assertEqual(self.read_bytes("race.txt"), b"overwritten by another process\n")

    def test_file_mode_is_carried_over_to_the_new_inode(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions only")
        target = self.write_bytes("script.sh", b"#!/bin/sh\necho hi\n")
        os.chmod(target, 0o755)

        self.tool("script.sh", "hi", "bye")

        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)


if __name__ == "__main__":
    unittest.main()
