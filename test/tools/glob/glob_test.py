"""Tests for the workspace scoped glob tool.

Run from the repository root::

    uv run python test/tools/glob/glob_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.glob import MAX_RESULTS, make_glob_tool  # noqa: E402
from agent.tools.glob.search import search_files  # noqa: E402
from agent.tools.glob_pattern import GlobPattern  # noqa: E402
from agent.tools.read_file import make_read_file_tool  # noqa: E402


class GlobToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tool = make_glob_tool(base_dir=str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str = "x") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def found(self, **arguments) -> set:
        return set(self.tool(**arguments)["filenames"])

    # ----------------------------------------------------------------- matching

    def test_finds_files_at_any_depth(self):
        for name in ("a.py", "pkg/b.py", "pkg/deep/c.py", "notes.txt"):
            self.write(name)

        result = self.tool("**/*.py")

        self.assertEqual(set(result["filenames"]), {"a.py", "pkg/b.py", "pkg/deep/c.py"})
        self.assertEqual(result["num_files"], 3)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["path"], ".")

    def test_pattern_without_a_separator_matches_the_file_name(self):
        for name in ("a.py", "pkg/b.py"):
            self.write(name)
        self.write("pkg/c.txt")

        self.assertEqual(self.found(pattern="*.py"), {"a.py", "pkg/b.py"})

    def test_brace_alternatives(self):
        self.write("a.py")
        self.write("b.txt")
        self.write("c.md")

        self.assertEqual(self.found(pattern="**/*.{py,txt}"), {"a.py", "b.txt"})

    def test_only_files_are_returned(self):
        self.write("pkg/a.py")

        self.assertEqual(self.found(pattern="**/*"), {"pkg/a.py"})

    # --------------------------------------------------------------- the search
    def test_path_narrows_the_root_but_results_stay_workspace_relative(self):
        self.write("pkg/a.py")
        self.write("other/b.py")

        result = self.tool("*.py", path="pkg")

        self.assertEqual(result["filenames"], ["pkg/a.py"])
        self.assertEqual(result["path"], "pkg")

    def test_hidden_and_ignored_files_are_listed(self):
        self.write(".env")
        self.write(".gitignore", "*.log\n")
        self.write("debug.log")

        self.assertEqual(self.found(pattern="*.log"), {"debug.log"})
        self.assertIn(".env", self.found(pattern=".*"))

    def test_denied_directories_are_not_listed(self):
        private = self.root / "private"
        self.write("private/secret.py")
        self.write("public.py")
        blocked = make_glob_tool(
            base_dir=str(self.root),
            access_config=FileAccessConfig(deny_dirs=(private.resolve(),)),
        )

        result = blocked("**/*.py")

        self.assertEqual(result["filenames"], ["public.py"])

    def test_absolute_pattern_carries_its_own_root(self):
        self.write("pkg/a.py")
        self.write("other/b.py")

        result = self.tool((self.root / "pkg" / "*.py").as_posix(), path="other")

        self.assertEqual(result["filenames"], ["pkg/a.py"])
        self.assertEqual(result["pattern"], "*.py")

    # ------------------------------------------------------------------ ordering

    def test_newest_file_comes_first(self):
        old = self.write("old.py")
        new = self.write("new.py")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (1_000_100, 1_000_100))

        result = self.tool("*.py")

        self.assertEqual(result["filenames"], ["new.py", "old.py"])

    def test_results_are_capped_and_flagged_truncated(self):
        for index in range(MAX_RESULTS + 5):
            self.write(f"f{index:03d}.txt")

        result = self.tool("*.txt")

        self.assertEqual(result["num_files"], MAX_RESULTS)
        self.assertTrue(result["truncated"])
        self.assertIn("hint", result)

    def test_scan_cap_is_reported_instead_of_hidden(self):
        for index in range(5):
            self.write(f"f{index}.txt")

        result = search_files(self.root, GlobPattern("*.txt"), max_scanned=2)

        self.assertTrue(result.scan_truncated)
        self.assertTrue(result.truncated)

    # -------------------------------------------------------------------- errors

    def test_missing_path_reports_an_error(self):
        result = self.tool("*.py", path="nope")

        self.assertEqual(result["reason"], "path_not_found")
        self.assertIn("error", result)

    def test_a_file_as_path_is_rejected(self):
        self.write("a.py")

        result = self.tool("*.py", path="a.py")

        self.assertEqual(result["reason"], "not_a_directory")

    def test_empty_pattern_is_rejected(self):
        result = self.tool("   ")

        self.assertEqual(result["reason"], "invalid_argument")
        self.assertEqual(result["argument"], "pattern")

    def test_search_outside_the_workspace_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)

        result = self.tool("*.py", path=outside.name)

        self.assertEqual(result["reason"], "outside_workspace")

    def test_no_match_is_an_empty_list_not_an_error(self):
        self.write("a.py")

        result = self.tool("**/*.rs")

        self.assertEqual(result["filenames"], [])
        self.assertEqual(result["num_files"], 0)
        self.assertFalse(result["truncated"])
        self.assertNotIn("error", result)

    # ------------------------------------------------------- reading it back

    def test_returned_paths_can_be_read_by_read_file(self):
        self.write("pkg/mod.py", "value = 1\n")
        read_file = make_read_file_tool(base_dir=str(self.root), max_tokens=25000)

        paths = self.tool("**/*.py")["filenames"]

        self.assertEqual(paths, ["pkg/mod.py"])
        self.assertIn("value = 1", read_file(paths[0], encoding="utf-8")["content"])


if __name__ == "__main__":
    unittest.main()
