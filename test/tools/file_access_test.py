"""Tests for the global file access policy.

Run from the repository root::

    uv run python test/tools/file_access_test.py -v
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

from agent.tools.file_access import (  # noqa: E402
    AccessDenied,
    FileAccessConfig,
    enforce_policy,
    load_access_config,
    resolve_read_path,
)


class FileAccessPolicyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.allowed = self.root / "allowed"
        self.blocked = self.root / "blocked"
        (self.blocked / "nested").mkdir(parents=True)
        self.allowed.mkdir()
        (self.allowed / "ok.txt").write_text("ok", encoding="utf-8")
        (self.blocked / "no.txt").write_text("no", encoding="utf-8")
        (self.blocked / "nested" / "deep.txt").write_text("deep", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_unbound_session_without_policy_allows_anything(self):
        path, root = resolve_read_path(str(self.blocked / "no.txt"), base_dir="")

        self.assertIsNone(root)
        self.assertEqual(path, (self.blocked / "no.txt").resolve())

    def test_deny_dirs_blocks_subtree(self):
        config = FileAccessConfig(deny_dirs=(self.blocked.resolve(),))

        with self.assertRaises(AccessDenied):
            enforce_policy((self.blocked / "no.txt").resolve(), config)
        with self.assertRaises(AccessDenied):
            enforce_policy((self.blocked / "nested" / "deep.txt").resolve(), config)

    def test_deny_files_blocks_only_that_file(self):
        config = FileAccessConfig(deny_files=((self.allowed / "ok.txt").resolve(),))

        with self.assertRaises(AccessDenied):
            enforce_policy((self.allowed / "ok.txt").resolve(), config)
        enforce_policy((self.blocked / "no.txt").resolve(), config)

    def test_allow_dirs_limits_reads(self):
        config = FileAccessConfig(allow_dirs=(self.allowed.resolve(),))

        enforce_policy((self.allowed / "ok.txt").resolve(), config)
        with self.assertRaises(AccessDenied):
            enforce_policy((self.blocked / "no.txt").resolve(), config)

    def test_deny_wins_over_allow(self):
        config = FileAccessConfig(
            allow_dirs=(self.root.resolve(),),
            deny_dirs=(self.blocked.resolve(),),
        )

        enforce_policy((self.allowed / "ok.txt").resolve(), config)
        with self.assertRaises(AccessDenied):
            enforce_policy((self.blocked / "no.txt").resolve(), config)

    def test_workspace_root_is_enforced_alongside_the_policy(self):
        config = FileAccessConfig(allow_dirs=(self.root.resolve(),))

        with self.assertRaises(AccessDenied):
            resolve_read_path("../outside.txt", base_dir=str(self.allowed), config=config)

    def test_global_policy_also_applies_inside_a_workspace(self):
        config = FileAccessConfig(deny_files=((self.allowed / "ok.txt").resolve(),))

        with self.assertRaises(AccessDenied):
            resolve_read_path("ok.txt", base_dir=str(self.allowed), config=config)

    def test_global_policy_keeps_other_workspace_files_readable(self):
        config = FileAccessConfig(deny_files=((self.root / "elsewhere.txt").resolve(),))

        path, root = resolve_read_path("ok.txt", base_dir=str(self.allowed), config=config)

        self.assertEqual(path, (self.allowed / "ok.txt").resolve())
        self.assertEqual(root, self.allowed.resolve())

    def test_load_access_config_reads_json(self):
        target = self.root / "policy.json"
        target.write_text(
            '{"deny_dirs": ["' + self.blocked.as_posix() + '"]}',
            encoding="utf-8",
        )

        config = load_access_config(target)

        self.assertEqual(config.deny_dirs, (self.blocked.resolve(),))

    def test_load_access_config_falls_back_when_missing(self):
        config = load_access_config(self.root / "nope.json")

        self.assertEqual(config, FileAccessConfig())


if __name__ == "__main__":
    unittest.main()
