"""Tests for the read ledger that guards whole-file writes.

Run from the repository root::

    uv run python test/tools/read_ledger_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.read_ledger import ReadLedger  # noqa: E402


class ReadLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = ReadLedger()

    def tearDown(self):
        self._tmp.cleanup()

    def test_unknown_path_has_no_entry(self):
        self.assertIsNone(self.ledger.lookup(self.root / "nope.txt"))

    def test_recorded_fingerprint_is_returned_verbatim(self):
        target = self.root / "notes.txt"
        self.ledger.record(target, 1234, 56)

        self.assertEqual(self.ledger.lookup(target), (1234, 56))

    def test_entries_are_per_path(self):
        first = self.root / "a.txt"
        second = self.root / "a.txt.bak"
        self.ledger.record(first, 1, 2)

        self.assertEqual(self.ledger.lookup(first), (1, 2))
        self.assertIsNone(self.ledger.lookup(second))

    def test_forget_drops_the_entry(self):
        target = self.root / "notes.txt"
        self.ledger.record(target, 1, 2)

        self.ledger.forget(target)

        self.assertIsNone(self.ledger.lookup(target))

    def test_recording_again_replaces_the_previous_fingerprint(self):
        target = self.root / "notes.txt"
        self.ledger.record(target, 1, 2)
        self.ledger.record(target, 3, 4)

        self.assertEqual(self.ledger.lookup(target), (3, 4))

    def test_separate_ledgers_do_not_share_entries(self):
        target = self.root / "notes.txt"
        self.ledger.record(target, 1, 2)

        self.assertIsNone(ReadLedger().lookup(target))


if __name__ == "__main__":
    unittest.main()
