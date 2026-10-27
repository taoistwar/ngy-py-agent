"""Tests for the workspace scoped grep tool.

Run from the repository root::

    uv run python test/tools/grep/grep_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.grep import make_grep_tool  # noqa: E402
from agent.tools.grep import tool as grep_tool  # noqa: E402


class GrepToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tool = make_grep_tool(base_dir=str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def lines_of(self, pattern: str, **arguments) -> list:
        return self.tool(pattern, output_mode="content", **arguments)["content"].splitlines()

    # ---------------------------------------------------------------- content

    def test_content_mode_reports_path_line_and_text(self):
        self.write("src/app.py", "first\nvalue = 1\nthird\n")

        result = self.tool("value", output_mode="content")

        self.assertEqual(result["content"], "src/app.py:2:value = 1")
        self.assertEqual(result["num_lines"], 1)
        self.assertFalse(result["truncated"])

    def test_line_numbers_can_be_turned_off(self):
        self.write("app.py", "value = 1\n")

        result = self.tool("value", output_mode="content", line_numbers=False)

        self.assertEqual(result["content"], "app.py:value = 1")

    def test_context_lines_use_a_dash_and_groups_are_separated(self):
        self.write("app.py", "one\ntwo\nvalue = 1\nfour\nfive\nsix\nseven\nvalue = 2\n")

        lines = self.lines_of("value", context=1)

        self.assertEqual(
            lines,
            [
                "app.py-2-two",
                "app.py:3:value = 1",
                "app.py-4-four",
                "--",
                "app.py-7-seven",
                "app.py:8:value = 2",
            ],
        )

    def test_context_wins_over_the_one_sided_knobs(self):
        self.write("app.py", "one\nvalue\nthree\n")

        lines = self.lines_of("value", context=1, before_context=0, after_context=0)

        self.assertEqual(lines, ["app.py-1-one", "app.py:2:value", "app.py-3-three"])

    def test_long_lines_are_clipped(self):
        self.write("app.py", "needle" + "x" * 900 + "\n")

        content = self.tool("needle", output_mode="content")["content"]

        self.assertTrue(content.endswith("..."))
        self.assertLess(len(content), 600)

    def test_head_limit_truncates_and_reports_the_page(self):
        self.write("app.py", "value\n" * 5)

        result = self.tool("value", output_mode="content", head_limit=2)

        self.assertEqual(result["num_lines"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["applied_limit"], 2)
        self.assertEqual(result["applied_offset"], 0)
        self.assertIn("hint", result)

    def test_offset_pages_through_the_same_answer(self):
        self.write("app.py", "value\n" * 5)

        first = self.tool("value", output_mode="content", head_limit=2)
        second = self.tool("value", output_mode="content", head_limit=2, offset=2)

        self.assertEqual(first["content"], "app.py:1:value\napp.py:2:value")
        self.assertEqual(second["content"], "app.py:3:value\napp.py:4:value")
        self.assertEqual(second["applied_offset"], 2)

    def test_head_limit_zero_means_no_limit(self):
        self.write("app.py", "value\n" * 300)

        result = self.tool("value", output_mode="content", head_limit=0)

        self.assertEqual(result["num_lines"], 300)
        self.assertFalse(result["truncated"])

    # ------------------------------------------------------------------ files

    def test_files_with_matches_is_the_default(self):
        self.write("a.py", "value = 1\n")
        self.write("b.py", "nothing here\n")
        self.write("pkg/c.py", "value = 2\n")

        result = self.tool("value")

        self.assertEqual(result["mode"], "files_with_matches")
        self.assertEqual(set(result["filenames"]), {"a.py", "pkg/c.py"})
        self.assertEqual(result["num_files"], 2)
        self.assertNotIn("content", result)

    def test_files_are_newest_first(self):
        old = self.write("old.py", "value\n")
        new = self.write("new.py", "value\n")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (1_000_100, 1_000_100))

        self.assertEqual(self.tool("value")["filenames"], ["new.py", "old.py"])

    def test_glob_filter_narrows_the_search(self):
        self.write("a.py", "value\n")
        self.write("b.ts", "value\n")
        self.write("c.js", "value\n")

        result = self.tool("value", glob="*.{ts,js}")

        self.assertEqual(set(result["filenames"]), {"b.ts", "c.js"})

    def test_several_glob_patterns_may_be_listed(self):
        self.write("a.py", "value\n")
        self.write("b.ts", "value\n")
        self.write("c.md", "value\n")

        result = self.tool("value", glob="*.py, *.ts")

        self.assertEqual(set(result["filenames"]), {"a.py", "b.ts"})

    def test_type_filter_uses_the_extension_table(self):
        self.write("a.py", "value\n")
        self.write("b.js", "value\n")

        self.assertEqual(self.tool("value", type="python")["filenames"], ["a.py"])

    def test_unknown_type_is_refused_with_the_supported_list(self):
        result = self.tool("value", type="brainfuck")

        self.assertEqual(result["reason"], "unknown_type")
        self.assertIn("py", result["supported"])

    # ------------------------------------------------------------------ count

    def test_files_mode_pages_and_reports_the_page(self):
        for name in ("a.py", "b.py", "c.py"):
            self.write(name, "value\n")

        result = self.tool("value", head_limit=2)

        self.assertEqual(result["num_files"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["applied_limit"], 2)

    def test_count_mode_pages_the_counts(self):
        for name in ("a.py", "b.py", "c.py"):
            self.write(name, "value\n")

        result = self.tool("value", output_mode="count", head_limit=2)

        self.assertEqual(result["num_files"], 2)
        self.assertTrue(result["truncated"])
        # The total still describes every match, not just the returned page.
        self.assertEqual(result["num_matches"], 3)

    def test_count_mode_counts_matching_lines_per_file(self):
        self.write("a.py", "value\nvalue\nvalue\n")
        self.write("b.py", "value\nnothing\n")

        result = self.tool("value", output_mode="count")

        self.assertEqual(result["content"], "a.py:3\nb.py:1")
        self.assertEqual(result["num_matches"], 4)
        self.assertEqual(result["num_files"], 2)

    # ------------------------------------------------------- flags and errors

    def test_case_insensitive_flag(self):
        self.write("a.py", "VALUE\n")

        self.assertEqual(self.tool("value")["num_files"], 0)
        self.assertEqual(self.tool("value", case_insensitive=True)["num_files"], 1)

    def test_multiline_lets_the_pattern_span_lines(self):
        self.write("a.rs", "struct Foo {\n    field: u32,\n}\n")
        pattern = r"struct Foo \{[\s\S]*?\}"

        single = self.tool(pattern, output_mode="content")
        spanning = self.tool(pattern, output_mode="content", multiline=True)

        self.assertEqual(single["num_lines"], 0)
        # One match, rendered as one entry whose text keeps its newlines.
        self.assertEqual(spanning["num_lines"], 1)
        self.assertTrue(spanning["content"].startswith("a.rs:1:struct Foo {"))
        self.assertIn("field: u32", spanning["content"])

    def test_invalid_regular_expression_is_reported(self):
        result = self.tool("(unclosed", output_mode="content")

        self.assertEqual(result["reason"], "invalid_pattern")
        self.assertIn("error", result)

    def test_offset_past_the_end_says_so_instead_of_no_matches(self):
        self.write("app.py", "value\n")

        result = self.tool("value", output_mode="content", offset=5)

        self.assertEqual(result["content"], "")
        # "No matches" would send the model off to rewrite a correct pattern.
        self.assertNotIn("No matches found", result["hint"])
        self.assertIn("offset", result["hint"])

    def test_a_paged_answer_does_not_open_with_a_group_separator(self):
        # Two matches, far apart, one context line each: the page starts after the
        # first group, exactly where the separator would fall.
        self.write("app.py", "one\ntwo\nvalue\nfour\nfive\nsix\nseven\neight\nvalue\nten\n")

        result = self.tool("value", output_mode="content", context=1, offset=3)

        self.assertTrue(result["content"].startswith("app.py-"))
        self.assertNotIn("--", result["content"].splitlines()[0])

    def test_no_match_comes_with_a_hint(self):
        self.write("a.py", "value\n")

        result = self.tool("absent")

        self.assertEqual(result["filenames"], [])
        self.assertFalse(result["truncated"])
        self.assertIn("hint", result)

    # ----------------------------------------------------------------- safety

    def test_vcs_directories_are_skipped(self):
        self.write(".git/config", "value\n")
        self.write("a.py", "value\n")

        self.assertEqual(self.tool("value")["filenames"], ["a.py"])

    def test_installed_dependencies_are_skipped(self):
        self.write("node_modules/pkg/index.js", "value\n")
        self.write(".venv/lib/mod.py", "value\n")
        self.write("a.py", "value\n")

        self.assertEqual(self.tool("value")["filenames"], ["a.py"])

    def test_pointing_path_at_a_skipped_directory_searches_it(self):
        self.write("node_modules/pkg/index.js", "value\n")

        result = self.tool("value", path="node_modules/pkg")

        self.assertEqual(result["filenames"], ["node_modules/pkg/index.js"])

    def test_gitignored_files_are_not_searched(self):
        self.write(".gitignore", "*.log\n")
        self.write("debug.log", "value\n")
        self.write("a.py", "value\n")

        self.assertEqual(self.tool("value")["filenames"], ["a.py"])

    def test_gitignore_negation_still_searches_the_file(self):
        self.write(".gitignore", "*.log\n!keep.log\n")
        self.write("drop.log", "value\n")
        self.write("keep.log", "value\n")

        self.assertEqual(self.tool("value")["filenames"], ["keep.log"])

    def test_pointing_path_at_an_ignored_directory_searches_it(self):
        self.write(".gitignore", "data/\n")
        self.write("data/notes.txt", "value\n")

        self.assertEqual(self.tool("value")["filenames"], [])
        self.assertEqual(
            self.tool("value", path="data")["filenames"], ["data/notes.txt"]
        )

    def test_binary_files_are_skipped(self):
        (self.root / "blob.bin").write_bytes(b"value\x00\x01\x02")

        self.assertEqual(self.tool("value")["num_files"], 0)

    def test_credential_files_are_skipped_and_named(self):
        self.write(".env", "SECRET=value\n")
        self.write("a.py", "value\n")

        result = self.tool("value")

        self.assertEqual(result["filenames"], ["a.py"])
        self.assertIn(".env", result["skipped_sensitive"])

    def test_only_skipped_credentials_produce_their_own_hint(self):
        self.write(".env", "SECRET=value\n")

        result = self.tool("value")

        self.assertEqual(result["filenames"], [])
        self.assertIn("read_file", result["hint"])

    def test_denied_directories_are_never_searched(self):
        private = self.root / "private"
        self.write("private/secret.py", "value\n")
        self.write("public.py", "value\n")
        tool = make_grep_tool(
            base_dir=str(self.root),
            access_config=FileAccessConfig(deny_dirs=(private.resolve(),)),
        )

        self.assertEqual(tool("value")["filenames"], ["public.py"])

    def test_search_outside_the_workspace_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)

        result = self.tool("value", path=outside.name)

        self.assertEqual(result["reason"], "outside_workspace")

    # -------------------------------------------------------------- targeting

    def test_a_file_path_searches_only_that_file(self):
        self.write("a.py", "value\n")
        self.write("b.py", "value\n")

        self.assertEqual(self.tool("value", path="b.py")["filenames"], ["b.py"])

    def test_directory_path_narrows_the_root(self):
        self.write("src/a.py", "value\n")
        self.write("other/b.py", "value\n")

        self.assertEqual(self.tool("value", path="src")["filenames"], ["src/a.py"])

    def test_missing_path_is_reported(self):
        result = self.tool("value", path="nope")

        self.assertEqual(result["reason"], "path_not_found")

    def test_exhausted_time_budget_is_reported_not_hidden(self):
        self.write("a.py", "value\n")

        with patch.object(grep_tool, "MAX_DURATION_SECONDS", -1.0):
            result = self.tool("value")

        # A partial answer is allowed; pretending it is complete is not.
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["num_files"], 0)


if __name__ == "__main__":
    unittest.main()
