"""Tests for the file walk shared by ``glob`` and ``grep``.

The walk is where the two tools' guarantees actually live - confinement, the
entry cap, and honest reporting when the cap is hit - so it is tested directly
rather than only through the tools.

Run from the repository root::

    uv run python test/tools/file_walk_test.py -v
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

from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.file_walk import FileWalk, is_generated_path  # noqa: E402


class FileWalkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        return path

    def names(self, **options) -> set:
        return {path.name for path in FileWalk(self.root, **options)}

    def test_yields_only_regular_files(self):
        self.write("a.py")
        self.write("pkg/b.py")

        self.assertEqual(self.names(), {"a.py", "b.py"})

    def test_skip_dirs_drops_whole_subtrees(self):
        self.write(".git/config")
        self.write("pkg/.git/HEAD")
        self.write("a.py")

        self.assertEqual(self.names(skip_dirs=(".git",)), {"a.py"})

    def test_denied_directories_are_pruned(self):
        private = self.root / "private"
        self.write("private/secret.py")
        self.write("a.py")
        policy = FileAccessConfig(deny_dirs=(private.resolve(),))

        self.assertEqual(self.names(policy=policy), {"a.py"})

    def test_denied_files_are_skipped(self):
        blocked = self.write("blocked.py")
        self.write("a.py")
        policy = FileAccessConfig(deny_files=(blocked.resolve(),))

        self.assertEqual(self.names(policy=policy), {"a.py"})

    def test_accept_can_prune_by_whole_path(self):
        self.write("keep/a.py")
        self.write("drop/a.py")
        accept = lambda path, is_dir: path.name != "drop"  # noqa: E731

        self.assertEqual(self.names(accept=accept), {"a.py"})
        self.assertEqual(
            {path.parent.name for path in FileWalk(self.root, accept=accept)}, {"keep"}
        )

    def test_the_cap_stops_the_walk_and_says_so(self):
        for index in range(5):
            self.write(f"f{index}.py")
        walk = FileWalk(self.root, max_scanned=2)

        found = list(walk)

        self.assertEqual(len(found), 2)
        self.assertEqual(walk.scanned, 2)
        self.assertTrue(walk.stopped_early)

    def test_a_finished_walk_is_not_marked_as_stopped(self):
        self.write("a.py")
        walk = FileWalk(self.root)

        list(walk)

        self.assertEqual(walk.scanned, 1)
        self.assertFalse(walk.stopped_early)

    def test_an_empty_root_yields_nothing(self):
        self.assertEqual(self.names(), set())


class GeneratedPathTest(unittest.TestCase):
    def test_generated_directories_are_detected_at_any_depth(self):
        for path in ("node_modules/a.py", "web/node_modules/b.js", "dist/x.js", ".git/HEAD"):
            with self.subTest(path=path):
                self.assertTrue(is_generated_path(path))

    def test_a_file_named_like_a_generated_directory_is_still_source(self):
        self.assertFalse(is_generated_path("scripts/build"))
        self.assertFalse(is_generated_path("target"))

    def test_ordinary_paths_are_source(self):
        self.assertFalse(is_generated_path("agent/tools/grep/tool.py"))


if __name__ == "__main__":
    unittest.main()
