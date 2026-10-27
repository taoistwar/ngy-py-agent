"""Tests for glob pattern semantics.

The rules under test are the ones the model relies on when it writes a pattern
(see ``agent/tools/glob_pattern.py``): ``*`` does not cross a separator, ``**``
does, ``**/`` also matches zero directories, a pattern without a separator is a
file name, and an absolute pattern carries its own root.

Run from the repository root::

    uv run python test/tools/glob_pattern_test.py -v
"""

import os
import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.glob_pattern import (  # noqa: E402
    GlobPattern,
    split_absolute_pattern,
)


def matches(pattern: str, path: str, case_sensitive: bool = True) -> bool:
    """Match ``path`` (a POSIX style relative path) against ``pattern``."""
    return GlobPattern(pattern, case_sensitive=case_sensitive).matches(path, path.rsplit("/", 1)[-1])


class SegmentTest(unittest.TestCase):
    def test_star_stays_inside_one_segment(self):
        self.assertTrue(matches("src/*.ts", "src/a.ts"))
        self.assertFalse(matches("src/*.ts", "src/deep/a.ts"))

    def test_question_mark_matches_one_character(self):
        self.assertTrue(matches("a?.py", "ab.py"))
        self.assertFalse(matches("a?.py", "abc.py"))
        self.assertFalse(matches("a?.py", "a/b.py"))

    def test_double_star_crosses_segments(self):
        self.assertTrue(matches("src/**/*.ts", "src/deep/nested/a.ts"))

    def test_double_star_slash_also_matches_zero_directories(self):
        self.assertTrue(matches("src/**/*.ts", "src/a.ts"))

    def test_trailing_double_star_matches_everything_below(self):
        self.assertTrue(matches("src/**", "src/a/b/c.py"))
        self.assertFalse(matches("src/**", "src"))


class BasenameTest(unittest.TestCase):
    def test_pattern_without_a_separator_matches_the_file_name_at_any_depth(self):
        for path in ("a.py", "deep/a.py", "deep/nested/a.py"):
            with self.subTest(path=path):
                self.assertTrue(matches("*.py", path))

    def test_pattern_with_a_separator_is_anchored_at_the_search_root(self):
        self.assertTrue(matches("pkg/*.py", "pkg/a.py"))
        self.assertFalse(matches("pkg/*.py", "other/pkg/a.py"))


class ClassAndBraceTest(unittest.TestCase):
    def test_character_class(self):
        self.assertTrue(matches("[ab].py", "a.py"))
        self.assertFalse(matches("[ab].py", "c.py"))

    def test_negated_character_class(self):
        self.assertTrue(matches("[!ab].py", "c.py"))
        self.assertFalse(matches("[!ab].py", "a.py"))

    def test_character_range_is_not_escaped_away(self):
        self.assertTrue(matches("[a-c].py", "b.py"))
        self.assertFalse(matches("[a-c].py", "d.py"))

    def test_brace_alternatives(self):
        self.assertTrue(matches("**/*.{py,txt}", "deep/a.txt"))
        self.assertFalse(matches("**/*.{py,txt}", "deep/a.md"))

    def test_single_alternative_brace_still_matches(self):
        self.assertTrue(matches("*.{py}", "a.py"))

    def test_unterminated_brace_is_literal(self):
        self.assertTrue(matches("a{b.py", "a{b.py"))


class AnchoredTest(unittest.TestCase):
    def test_anchored_makes_a_bare_name_match_only_its_own_level(self):
        anchored = GlobPattern("build", anchored=True)

        self.assertTrue(anchored.matches("build", "build"))
        self.assertFalse(anchored.matches("deep/build", "build"))

    def test_unanchored_keeps_the_file_name_rule(self):
        pattern = GlobPattern("build")

        self.assertTrue(pattern.matches("deep/build", "build"))


class CaseTest(unittest.TestCase):
    def test_case_sensitivity_is_explicit(self):
        self.assertFalse(matches("SRC/*.py", "src/a.py", case_sensitive=True))
        self.assertTrue(matches("SRC/*.py", "src/a.py", case_sensitive=False))

    def test_default_follows_the_filesystem(self):
        expected = os.name != "nt"
        self.assertEqual(GlobPattern("*.py").case_sensitive, expected)


class AbsolutePatternTest(unittest.TestCase):
    # ``/`` on POSIX, ``C:/`` on Windows: the tests must not assume either.
    ANCHOR = Path(Path.cwd().anchor).as_posix()

    def absolute(self, tail: str) -> str:
        return f"{self.ANCHOR}w/src/{tail}"

    def test_relative_pattern_has_no_root_of_its_own(self):
        self.assertIsNone(split_absolute_pattern("src/**/*.py"))

    def test_absolute_pattern_splits_at_the_first_wildcard_segment(self):
        base, rest = split_absolute_pattern(self.absolute("**/*.py"))

        self.assertEqual(base, f"{self.ANCHOR}w/src")
        self.assertEqual(rest, "**/*.py")

    def test_absolute_pattern_without_a_wildcard_points_at_one_file(self):
        base, rest = split_absolute_pattern(self.absolute("a.py"))

        self.assertEqual(base, f"{self.ANCHOR}w/src")
        self.assertEqual(rest, "a.py")

    def test_wildcard_in_the_first_segment_keeps_the_anchor(self):
        base, rest = split_absolute_pattern(f"{self.ANCHOR}*/a.py")

        self.assertEqual(base, self.ANCHOR)
        self.assertEqual(rest, "*/a.py")


if __name__ == "__main__":
    unittest.main()
