"""Tests for the timeout-guarded matcher.

The point of this module is one failure mode: a pattern whose matching never
finishes. ``(a|a)+$`` against a run of ``a`` is the shortest example that still
backtracks exponentially under ``regex`` (``(a+)+$`` no longer does), so it is
what the abort path is tested with.

Run from the repository root::

    uv run python test/tools/grep/regex_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.grep.errors import GrepError  # noqa: E402
from agent.tools.grep.regex import Matcher, MatchTimeout  # noqa: E402


class MatcherTest(unittest.TestCase):
    def test_line_mode_finds_the_matching_lines(self):
        matcher = Matcher("value")

        self.assertEqual(matcher.matching_lines(["a", "value = 1", "b"]), [1])
        self.assertTrue(matcher.has_line_match(["value"]))
        self.assertEqual(matcher.count_lines(["value", "value", "x"]), 2)

    def test_anchors_are_line_scoped_in_line_mode(self):
        matcher = Matcher("^def ")

        self.assertEqual(matcher.matching_lines(["def a():", "x = 1"]), [0])

    def test_multiline_spans_lines_and_keeps_anchors_per_line(self):
        matcher = Matcher(r"struct \{[\s\S]*?\}", multiline=True)
        text = "struct {\n  field,\n}\n"

        self.assertEqual(len(matcher.text_matches(text)), 1)
        self.assertEqual(matcher.matching_lines(["a", "b"]), [])  # line mode is separate
        self.assertEqual(Matcher("^b", multiline=True).count_text_matches("a\nb\n"), 1)

    def test_a_pathological_pattern_is_aborted(self):
        matcher = Matcher("(a|a)+$", timeout=0.05)

        with self.assertRaises(MatchTimeout):
            matcher.has_line_match(["a" * 200 + "!"])

    def test_the_timeout_does_not_affect_ordinary_patterns(self):
        matcher = Matcher("(a|a)+", timeout=0.05)

        self.assertTrue(matcher.has_line_match(["aaaa"]))

    def test_an_invalid_pattern_is_reported_as_such(self):
        with self.assertRaises(GrepError) as caught:
            Matcher("(unclosed")

        self.assertEqual(caught.exception.details["reason"], "invalid_pattern")


if __name__ == "__main__":
    unittest.main()
