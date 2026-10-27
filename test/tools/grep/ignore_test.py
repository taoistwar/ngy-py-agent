"""Tests for the ``.gitignore`` layer used by ``grep``.

The dialect is a subset of git's, and these tests pin the parts that change an
answer: basename patterns matching at any depth, deeper files adding to (and
overriding) shallower ones, ``!`` re-inclusion, ``dir/`` and ``/anchored``, and
the boundary that rules never come from *above* the search root.

Run from the repository root::

    uv run python test/tools/grep/ignore_test.py -v
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

from agent.tools.grep.ignore import IgnoreRules  # noqa: E402


class IgnoreRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def ignored(self, name: str, is_dir: bool = False, root: Path = None) -> bool:
        base = root or self.root
        return IgnoreRules(base).ignored(base / name, is_dir)

    def test_without_a_gitignore_nothing_is_ignored(self):
        self.assertFalse(self.ignored("a.log"))

    def test_basename_pattern_matches_at_any_depth(self):
        self.write(".gitignore", "*.log\n")

        self.assertTrue(self.ignored("a.log"))
        self.assertTrue(self.ignored("deep/nested/a.log"))
        self.assertFalse(self.ignored("a.py"))

    def test_pattern_with_a_separator_is_anchored_to_its_directory(self):
        self.write(".gitignore", "out/*.txt\n")

        self.assertTrue(self.ignored("out/a.txt"))
        self.assertFalse(self.ignored("deep/out/a.txt"))

    def test_a_deeper_gitignore_adds_its_own_rules(self):
        self.write(".gitignore", "*.log\n")
        self.write("pkg/.gitignore", "*.tmp\n")

        self.assertTrue(self.ignored("pkg/a.log"))
        self.assertTrue(self.ignored("pkg/a.tmp"))
        self.assertFalse(self.ignored("other/a.tmp"))

    def test_negation_re_includes_a_file(self):
        self.write(".gitignore", "*.log\n!keep.log\n")

        self.assertTrue(self.ignored("drop.log"))
        self.assertFalse(self.ignored("keep.log"))

    def test_a_deeper_negation_overrides_a_shallower_rule(self):
        self.write(".gitignore", "*.log\n")
        self.write("pkg/.gitignore", "!important.log\n")

        self.assertTrue(self.ignored("drop.log"))
        self.assertFalse(self.ignored("pkg/important.log"))

    def test_trailing_slash_matches_directories_only(self):
        self.write(".gitignore", "out/\n")

        self.assertTrue(self.ignored("out", is_dir=True))
        self.assertTrue(self.ignored("deep/out", is_dir=True))
        self.assertFalse(self.ignored("out"))

    def test_leading_slash_anchors_to_the_declaring_directory(self):
        self.write(".gitignore", "/only.txt\n")

        self.assertTrue(self.ignored("only.txt"))
        self.assertFalse(self.ignored("deep/only.txt"))

    def test_comments_and_blank_lines_declare_nothing(self):
        self.write(".gitignore", "# comment\n\n   \n*.log\n")

        self.assertTrue(self.ignored("a.log"))
        self.assertFalse(self.ignored("# comment"))

    def test_rules_are_not_read_from_above_the_search_root(self):
        self.write(".gitignore", "*.log\n")

        # A search rooted at ``pkg`` does not consult the workspace ``.gitignore``:
        # pointing ``path`` at an ignored directory is how it gets searched.
        self.assertFalse(self.ignored("a.log", root=self.root / "pkg"))


if __name__ == "__main__":
    unittest.main()
