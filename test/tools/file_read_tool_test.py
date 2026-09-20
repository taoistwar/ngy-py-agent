"""Tests for the workspace scoped read_file tool.

Run from the repository root::

    uv run python test/tools/file_read_tool_test.py -v
"""

import codecs
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

    def test_preserves_crlf_line_endings(self):
        (self.root / "win.txt").write_bytes(b"alpha\r\nbeta\r\n")

        result = self.tool("win.txt")

        self.assertEqual(result["content"], "1\talpha\r\n2\tbeta\r\n")

    def test_preserves_a_missing_final_newline(self):
        (self.root / "tail.txt").write_bytes(b"alpha\nbeta")

        result = self.tool("tail.txt")

        self.assertEqual(result["content"], "1\talpha\n2\tbeta")

    def test_output_is_byte_identical_once_prefixes_are_stripped(self):
        (self.root / "win.txt").write_bytes(b"alpha\r\nbeta\r\n")

        content = self.tool("win.txt")["content"]
        stripped = "".join(line.split("\t", 1)[1] for line in content.splitlines(keepends=True))

        self.assertEqual(stripped.encode("utf-8"), b"alpha\r\nbeta\r\n")

    def test_bom_is_stripped_from_the_content(self):
        (self.root / "bom.txt").write_bytes(codecs.BOM_UTF8 + b"alpha\n")

        result = self.tool("bom.txt")

        self.assertTrue(result["bom"])
        self.assertEqual(result["encoding"], "utf-8")
        # The BOM is kept aside for a byte-faithful write, never handed to the model.
        self.assertEqual(result["content"], "1\talpha\n")

    def test_utf16_file_is_read_through_its_bom(self):
        # UTF-16 text always contains NUL bytes, so the BOM check has to run
        # before the binary sniff or the file would never be readable.
        (self.root / "u16.txt").write_bytes("hello\n世界\n".encode("utf-16"))

        result = self.tool("u16.txt")

        self.assertNotIn("error", result)
        self.assertEqual(result["encoding"], "utf-16-le")
        self.assertTrue(result["bom"])
        self.assertIn("世界", result["content"])

    def test_encoding_argument_decodes_other_encodings(self):
        (self.root / "gbk.txt").write_bytes("第一行：中文\n第二行：内容\n".encode("gbk"))

        result = self.tool("gbk.txt", 1, None, "gbk")

        self.assertNotIn("error", result)
        self.assertEqual(result["encoding"], "gbk")
        self.assertIn("第二行：内容", result["content"])

    def test_decode_failure_lists_candidate_encodings(self):
        (self.root / "gbk.txt").write_bytes("第一行：中文\n".encode("gbk"))

        result = self.tool("gbk.txt")

        self.assertEqual(result["reason"], "decode_failed")
        self.assertEqual(result["encoding"], "utf-8")
        self.assertIn("error", result)
        # Detection only produces a hint: the bytes are never silently re-read.
        candidates = {item["encoding"] for item in result["suggested_encodings"]}
        self.assertIn("gb18030", candidates)

    def test_unknown_encoding_is_reported(self):
        (self.root / "notes.txt").write_text("alpha\n", encoding="utf-8")

        result = self.tool("notes.txt", 1, None, "not-a-codec")

        self.assertEqual(result["reason"], "unknown_encoding")

    def test_form_feed_does_not_start_a_new_line(self):
        # ``str.splitlines`` treats \x0c as a line break, the file stream does not.
        # The two must agree or patch line numbers drift away from what was read.
        (self.root / "ff.txt").write_bytes(b"1\n2\n\x0c3\n4\n")

        result = self.tool("ff.txt")

        self.assertEqual(result["total_lines"], 4)
        self.assertEqual(result["content"], "1\t1\n2\t2\n3\t\x0c3\n4\t4\n")

    def test_file_path_keeps_surrounding_whitespace(self):
        (self.root / " spaced.txt").write_bytes(b"alpha\n")

        found = self.tool(" spaced.txt")
        missing = self.tool("nomatch.txt ")

        self.assertNotIn("error", found)
        self.assertEqual(found["path"], " spaced.txt")
        self.assertEqual(missing["reason"], "file_not_found")
        self.assertIn("whitespace", missing["hint"])


if __name__ == "__main__":
    unittest.main()
