"""Tests for the workspace scoped read_file tool.

Run from the repository root::

    uv run python test/tools/file_read_tool_test.py -v
"""

import random
import string
import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.file_read_tool import (  # noqa: E402
    MAX_FULL_READ_BYTES,
    make_read_file_tool,
)


class ReadFileToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tool = make_read_file_tool(base_dir=str(self.root), max_tokens=25000)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_whole_file_when_limit_omitted(self):
        self.write("notes.txt", "alpha\nbeta\ngamma\n")

        result = self.tool("notes.txt")

        self.assertEqual(result["start_line"], 1)
        self.assertEqual(result["returned_lines"], 3)
        self.assertEqual(result["total_lines"], 3)
        self.assertFalse(result["truncated"])
        self.assertIn("alpha", result["content"])

    def test_offset_zero_is_alias_for_first_line(self):
        self.write("notes.txt", "alpha\nbeta\ngamma\n")

        zero = self.tool("notes.txt", 0, 2)
        one = self.tool("notes.txt", 1, 2)

        self.assertEqual(zero["content"], one["content"])

    def test_limit_returns_requested_range(self):
        self.write("notes.txt", "l1\nl2\nl3\nl4\nl5\n")

        result = self.tool("notes.txt", 2, 2)

        self.assertEqual(result["start_line"], 2)
        self.assertEqual(result["end_line"], 3)
        self.assertEqual(result["returned_lines"], 2)
        self.assertTrue(result["truncated"])
        self.assertNotIn("l4", result["content"])

    def test_content_is_prefixed_with_line_numbers(self):
        self.write("notes.txt", "alpha\nbeta\n")

        content = self.tool("notes.txt")["content"].splitlines()

        self.assertEqual(content[0], "1\talpha")
        self.assertEqual(content[1], "2\tbeta")

    def test_offset_past_end_reports_total_lines(self):
        self.write("notes.txt", "alpha\nbeta\n")

        with_limit = self.tool("notes.txt", 50, 5)
        to_end = self.tool("notes.txt", 50)

        self.assertIn("error", with_limit)
        self.assertEqual(with_limit["total_lines"], 2)
        self.assertIn("error", to_end)
        self.assertEqual(to_end["total_lines"], 2)

    def test_total_lines_is_reported_when_starting_later(self):
        self.write("notes.txt", "l1\nl2\nl3\n")

        result = self.tool("notes.txt", 2)

        self.assertEqual(result["total_lines"], 3)
        self.assertEqual(result["returned_lines"], 2)
        self.assertIn("l2", result["content"])

    def test_rejects_path_outside_workspace(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("TOP_SECRET_CONTENT", encoding="utf-8")
        self.addCleanup(outside.unlink)

        relative = self.tool("../outside.txt")
        absolute = self.tool(str(outside))

        self.assertIn("error", relative)
        self.assertIn("error", absolute)
        self.assertNotIn("TOP_SECRET_CONTENT", str(relative))
        self.assertNotIn("TOP_SECRET_CONTENT", str(absolute))

    def test_unbound_session_honours_the_global_policy(self):
        outside = self.root.parent / "unbound.txt"
        outside.write_text("UNBOUND_CONTENT", encoding="utf-8")
        self.addCleanup(outside.unlink)
        config = FileAccessConfig(deny_files=(outside.resolve(),))

        blocked = make_read_file_tool(base_dir=None, access_config=config)(str(outside))
        allowed = make_read_file_tool(base_dir=None)(str(outside))

        self.assertIn("error", blocked)
        self.assertEqual(blocked["reason"], "deny_file")
        self.assertNotIn("error", allowed)
        self.assertIn("UNBOUND_CONTENT", allowed["content"])

    def test_rejects_missing_file_and_directory(self):
        (self.root / "sub").mkdir()

        self.assertIn("error", self.tool("nope.txt"))
        self.assertIn("error", self.tool("sub"))

    def test_rejects_binary_file(self):
        (self.root / "blob.bin").write_bytes(b"\x00\x01\x02binary")

        self.assertIn("error", self.tool("blob.bin"))

    def test_rejects_file_larger_than_max_size_without_limit(self):
        self.write("big.txt", "x" * (MAX_FULL_READ_BYTES + 10))

        result = self.tool("big.txt")

        self.assertIn("error", result)
        self.assertEqual(result["byte_limit"], MAX_FULL_READ_BYTES)

    def test_explicit_limit_still_works_on_large_file(self):
        row = "x" * 100 + "\n"
        self.write("big.txt", row * (MAX_FULL_READ_BYTES // len(row) + 1))

        result = self.tool("big.txt", 1, 3)

        self.assertNotIn("error", result)
        self.assertEqual(result["returned_lines"], 3)

    def test_rejects_range_over_token_budget_using_exact_count(self):
        random.seed(0)
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
        payload = "".join(random.choice(alphabet) for _ in range(700))
        self.write("dense.txt", payload)
        tool = make_read_file_tool(base_dir=str(self.root), max_tokens=200)

        result = tool("dense.txt")

        self.assertIn("error", result)
        self.assertTrue(result["exact"])

    def test_accepts_repetitive_text_after_exact_count(self):
        tool = make_read_file_tool(base_dir=str(self.root), max_tokens=1000)
        self.write("repeat.txt", "a" * 300)

        result = tool("repeat.txt")

        self.assertNotIn("error", result)
        self.assertTrue(result["token_budget"]["exact"])
        self.assertTrue(result["token_budget"]["ok"])


if __name__ == "__main__":
    unittest.main()
