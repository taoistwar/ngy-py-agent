"""Tests for the global file access policy.

Run from the repository root::

    uv run python test/tools/file_access_test.py -v
"""

import os
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
    DEFAULT_WORKSPACE_ENV,
    AccessDenied,
    FileAccessConfig,
    enforce_policy,
    load_access_config,
    resolve_read_path,
    resolve_write_path,
)
from agent.tools.read_file import make_read_file_tool  # noqa: E402
from agent.tools.read_ledger import ReadLedger  # noqa: E402
from agent.tools.write_file import make_write_file_tool  # noqa: E402


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


class DefaultWorkspaceTest(unittest.TestCase):
    """Where a relative path starts when the session has no workspace bound."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "default_workspace"
        # Point the session default at a temporary folder: a test must never write
        # into the real one, which sits next to the repository.
        self._previous = os.environ.get(DEFAULT_WORKSPACE_ENV)
        os.environ[DEFAULT_WORKSPACE_ENV] = str(self.workspace)

    def tearDown(self):
        if self._previous is None:
            os.environ.pop(DEFAULT_WORKSPACE_ENV, None)
        else:
            os.environ[DEFAULT_WORKSPACE_ENV] = self._previous
        self._tmp.cleanup()

    def test_relative_read_resolves_into_the_session_default(self):
        self.workspace.mkdir(parents=True)
        (self.workspace / "notes.txt").write_text("hi", encoding="utf-8")

        path, root = resolve_read_path("notes.txt", base_dir="")

        self.assertEqual(path, (self.workspace / "notes.txt").resolve())
        self.assertIsNone(root, "the default is a base, not a workspace ceiling")

    def test_a_bound_workspace_still_wins(self):
        bound = self.root / "bound"
        bound.mkdir()

        path, root = resolve_read_path("notes.txt", base_dir=str(bound))

        self.assertEqual(path, (bound / "notes.txt").resolve())
        self.assertEqual(root, bound.resolve())

    def test_resolving_alone_never_creates_it(self):
        # Regression: the permission broker resolves the target too (to show it in
        # the dialog), so a lookup that created the folder left an empty directory
        # behind - for reads, and even for calls that were refused.
        resolve_read_path("notes.txt", base_dir="")
        resolve_write_path("notes.txt", base_dir="")

        self.assertFalse(self.workspace.exists(), "looking must not materialise a tree")

    def test_the_write_tool_creates_it_on_demand(self):
        path, _ = resolve_write_path("notes.txt", base_dir="", create_default=True)

        self.assertTrue(self.workspace.is_dir())
        self.assertEqual(path, (self.workspace / "notes.txt").resolve())

    def test_absolute_paths_are_unaffected(self):
        target = self.root / "absolute.txt"

        path, _ = resolve_read_path(str(target), base_dir="")

        self.assertEqual(path, target.resolve())


class DefaultWorkspaceRoundTripTest(unittest.TestCase):
    """The bug this exists for: a file written by an unbound session must be readable.

    Before the session default existed, ``write_file("test.py")`` from a session
    without a workspace landed in the process working directory (in practice the
    repository root), so the model's scratch file ended up mixed into the project.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "default_workspace"
        self._previous = os.environ.get(DEFAULT_WORKSPACE_ENV)
        os.environ[DEFAULT_WORKSPACE_ENV] = str(self.workspace)

    def tearDown(self):
        if self._previous is None:
            os.environ.pop(DEFAULT_WORKSPACE_ENV, None)
        else:
            os.environ[DEFAULT_WORKSPACE_ENV] = self._previous
        self._tmp.cleanup()

    def test_write_then_read_stays_inside_the_session_default(self):
        ledger = ReadLedger()
        write = make_write_file_tool(base_dir=None, ledger=ledger)
        read = make_read_file_tool(base_dir=None, ledger=ledger)

        written = write("test.py", "print('hi')", "utf-8")
        self.assertTrue(written.details["success"])
        self.assertTrue(
            (self.workspace / "test.py").is_file(),
            "a relative write must land in the session default",
        )
        # Asserted on the reported path rather than on ``Path.cwd()``: the working
        # directory is whatever the test runner was started in, and asserting
        # about it makes the test depend on the machine it runs on.
        self.assertEqual(written.details["file_path"], (self.workspace / "test.py").as_posix())

        back = read("test.py")
        self.assertIn("print", back["content"])


if __name__ == "__main__":
    unittest.main()
