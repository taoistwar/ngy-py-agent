"""Tests for the checkpoint store: what a task changed, and what undoing it means.

Every test drives the real git binary against a throwaway workspace, because the
whole point of the store is that it agrees with what is actually on disk.

Run from the repository root::

    uv run python test/checkpoints/checkpoint_store_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.checkpoints import STATUS_ADDED, STATUS_MODIFIED, CheckpointStore  # noqa: E402
from agent.checkpoints import git as git_module  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402

TASK = "task-one"
OTHER_TASK = "task-two"

WRITE_CALL = ("write_file", {"file_path": "app.py"})
SHELL_CALL = ("exec_command", {"command": "true"})


class CheckpointStoreTest(unittest.TestCase):
    def setUp(self):
        self._workspace = tempfile.TemporaryDirectory()
        self._store = tempfile.TemporaryDirectory()
        self.workspace = Path(self._workspace.name)
        self.root = Path(self._store.name)
        if not git_module.available():
            self.skipTest("git is not installed on this machine")
        self.path = self.workspace / "app.py"
        self.path.write_text("v0\n", encoding="utf-8")
        self.store = CheckpointStore(self.workspace, self.root)

    def tearDown(self):
        self._workspace.cleanup()
        self._store.cleanup()

    # --- helpers ----------------------------------------------------------
    #
    # The registry brackets every mutating call: ``begin`` before it runs, ``end``
    # after. These helpers do the same around a direct disk change.

    def write(self, target: Path, content: str, task_id: str = TASK) -> None:
        tool, arguments = "write_file", {"file_path": target.name}
        self.store.begin(task_id, tool, arguments)
        target.write_text(content, encoding="utf-8")
        self.store.end(task_id, tool, arguments)

    def shell(self, task_id: str = TASK) -> None:
        self.store.begin(task_id, *SHELL_CALL)
        self.store.end(task_id, *SHELL_CALL)

    def changes(self, task_id: str = TASK):
        return {item.path: item for item in self.store.changes(task_id)}

    # --- recording --------------------------------------------------------

    def test_a_write_is_reported_with_its_status(self):
        self.write(self.path, "v1\n")

        changes = self.changes()

        self.assertEqual(list(changes), ["app.py"])
        self.assertEqual(changes["app.py"].status, STATUS_MODIFIED)
        self.assertEqual(changes["app.py"].additions, 1)
        self.assertEqual(changes["app.py"].deletions, 1)

    def test_the_baseline_is_the_first_state_not_the_latest(self):
        self.write(self.path, "v1\n")
        self.write(self.path, "v2\n")

        self.assertEqual(list(self.changes()), ["app.py"])
        self.assertEqual(self.store.revert(TASK).restored, ["app.py"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "v0\n")

    def test_a_file_created_outside_any_task_is_not_a_creation_of_the_next(self):
        """The baseline is the disk, not the last commit (ADR 0020 D3).

        A file the user created by hand between two tasks is on disk but not in
        ``HEAD``. Treating ``HEAD`` as the baseline would report the next task's edit
        to it as a creation, and undoing that task would delete the user's file.
        """
        # A first task on a different file, so the repository already has a HEAD.
        self.write(self.workspace / "first.txt", "a\n", task_id="earlier")
        # Then the user writes app.py themselves: no begin/end wraps this.
        self.path.write_text("user\n", encoding="utf-8")

        self.write(self.path, "task\n", task_id=TASK)

        self.assertEqual(self.changes()["app.py"].status, STATUS_MODIFIED)
        self.store.revert(TASK)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "user\n")

    def test_a_created_file_is_reported_as_added(self):
        created = self.workspace / "new.txt"
        self.write(created, "hello\n")

        self.assertEqual(self.changes()["new.txt"].status, STATUS_ADDED)

    def test_an_empty_workspace_has_a_baseline_too(self):
        """A task may be the thing that fills an empty directory."""
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder)
            store = CheckpointStore(empty, self.root)

            store.begin(TASK, "write_file", {"file_path": "first.txt"})
            (empty / "first.txt").write_text("x\n", encoding="utf-8")
            store.end(TASK, "write_file", {"file_path": "first.txt"})

            self.assertEqual([item.status for item in store.changes(TASK)], [STATUS_ADDED])

    def test_a_task_that_changed_nothing_has_no_changes(self):
        self.shell()

        self.assertEqual(self.store.changes(TASK), [])

    def test_a_shell_snapshot_captures_files_no_tool_named(self):
        """``exec_command`` can create anything, so its snapshot is the whole tree."""
        self.store.begin(TASK, *SHELL_CALL)
        (self.workspace / "made-by-shell.txt").write_text("x\n", encoding="utf-8")
        self.store.end(TASK, *SHELL_CALL)

        self.assertIn("made-by-shell.txt", self.changes())

    def test_one_task_does_not_claim_another_task_work(self):
        self.write(self.path, "v1\n")
        other = self.workspace / "other.txt"
        self.store.begin(OTHER_TASK, *SHELL_CALL)
        other.write_text("y\n", encoding="utf-8")
        self.store.end(OTHER_TASK, *SHELL_CALL)

        self.assertEqual(list(self.changes(TASK)), ["app.py"])
        self.assertEqual(list(self.changes(OTHER_TASK)), ["other.txt"])

    # --- reverting --------------------------------------------------------

    def test_revert_restores_the_previous_content(self):
        self.write(self.path, "v1\n")

        result = self.store.revert(TASK)

        self.assertEqual(result.restored, ["app.py"])
        self.assertTrue(result.clean)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "v0\n")
        # Nothing is left to undo.
        self.assertEqual(self.store.changes(TASK), [])

    def test_revert_removes_a_file_the_task_created(self):
        created = self.workspace / "new.txt"
        self.write(created, "hello\n")

        self.store.revert(TASK)

        self.assertFalse(created.exists())

    def test_revert_restores_a_file_the_task_deleted(self):
        self.store.begin(TASK, *SHELL_CALL)
        self.path.unlink()
        self.store.end(TASK, *SHELL_CALL)

        result = self.store.revert(TASK)

        self.assertEqual(result.restored, ["app.py"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "v0\n")

    def test_a_file_edited_after_the_task_is_a_conflict(self):
        self.write(self.path, "v1\n")
        self.path.write_text("user edit\n", encoding="utf-8")

        result = self.store.revert(TASK)

        self.assertEqual(result.restored, [])
        self.assertEqual(result.conflicts, ["app.py"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "user edit\n")

    def test_force_overwrites_a_conflict(self):
        self.write(self.path, "v1\n")
        self.path.write_text("user edit\n", encoding="utf-8")

        result = self.store.revert(TASK, force=True)

        self.assertEqual(result.restored, ["app.py"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "v0\n")

    def test_a_conflict_does_not_block_the_other_files(self):
        second = self.workspace / "second.py"
        second.write_text("s0\n", encoding="utf-8")
        self.write(self.path, "v1\n")
        self.write(second, "s1\n")
        self.path.write_text("user edit\n", encoding="utf-8")

        result = self.store.revert(TASK)

        self.assertEqual(result.restored, ["second.py"])
        self.assertEqual(result.conflicts, ["app.py"])
        self.assertEqual(second.read_text(encoding="utf-8"), "s0\n")

    def test_reverting_one_path_leaves_the_others_alone(self):
        second = self.workspace / "second.py"
        second.write_text("s0\n", encoding="utf-8")
        self.write(self.path, "v1\n")
        self.write(second, "s1\n")

        result = self.store.revert(TASK, paths=["app.py"])

        self.assertEqual(result.restored, ["app.py"])
        self.assertEqual(second.read_text(encoding="utf-8"), "s1\n")
        # The undone file leaves the list; the other one stays.
        self.assertEqual(list(self.changes()), ["second.py"])

    def test_a_diff_is_available_for_the_dialog(self):
        self.write(self.path, "v1\n")

        diff = self.store.diff(TASK, "app.py")

        self.assertIn("-v0", diff)
        self.assertIn("+v1", diff)

    def test_the_two_sides_are_the_full_texts_for_the_editor(self):
        """A side-by-side view needs the file, not only the hunks around them."""
        self.write(self.path, "v1\n")

        sides = self.store.sides(TASK, "app.py")

        # Line endings stay as they are on disk: Windows writes CRLF, and the
        # editor renders either.
        self.assertEqual(sides["before"].splitlines(), ["v0"])
        self.assertEqual(sides["after"].splitlines(), ["v1"])

    def test_a_created_file_has_an_empty_before_side(self):
        created = self.workspace / "new.py"
        self.write(created, "print(1)\n")

        sides = self.store.sides(TASK, "new.py")

        self.assertEqual(sides["before"], "")
        self.assertEqual(sides["after"].splitlines(), ["print(1)"])

    def test_a_binary_file_has_no_sides(self):
        """No text to render: the caller falls back to the patch."""
        tool, arguments = "write_file", {"file_path": "blob.bin"}
        self.store.begin(TASK, tool, arguments)
        (self.workspace / "blob.bin").write_bytes(b"\0\x01\x02")
        self.store.end(TASK, tool, arguments)

        sides = self.store.sides(TASK, "blob.bin")

        self.assertIsNone(sides["before"])
        self.assertIsNone(sides["after"])

    # --- conflicts --------------------------------------------------------

    def test_a_file_edited_after_the_task_is_flagged_as_a_conflict(self):
        """The UI has to know before the click, not only after the refusal."""
        self.write(self.path, "v1\n")
        self.assertFalse(self.changes()["app.py"].conflict)

        self.path.write_text("user edit\n", encoding="utf-8")

        self.assertTrue(self.changes()["app.py"].conflict)

    def test_a_file_the_task_created_is_flagged_once_someone_edits_it(self):
        created = self.workspace / "new.txt"
        self.write(created, "hello\n")
        self.assertFalse(self.changes()["new.txt"].conflict)

        created.write_text("someone else\n", encoding="utf-8")

        self.assertTrue(self.changes()["new.txt"].conflict)

    # --- plumbing ---------------------------------------------------------

    def test_the_store_never_touches_the_workspace_git_directory(self):
        (self.workspace / ".git").mkdir()
        self.store = CheckpointStore(self.workspace, self.root)

        self.write(self.path, "v1\n")

        self.assertEqual(list((self.workspace / ".git").iterdir()), [])

    def test_disabled_store_is_not_created(self):
        with mock.patch.dict(os.environ, {"CHECKPOINT_ENABLED": "0"}):
            self.assertIsNone(CheckpointStore.for_run(str(self.workspace), TASK))

    def test_a_run_without_a_task_id_gets_no_store(self):
        self.assertIsNone(CheckpointStore.for_run(str(self.workspace), ""))


class RegistryCheckpointTest(unittest.TestCase):
    """The hook that matters: a tool call through the registry is undoable."""

    def setUp(self):
        self._workspace = tempfile.TemporaryDirectory()
        self._store = tempfile.TemporaryDirectory()
        self.workspace = Path(self._workspace.name)
        if not git_module.available():
            self.skipTest("git is not installed on this machine")
        self.store = CheckpointStore(self.workspace, Path(self._store.name))
        self.registry = ToolRegistry(
            base_dir=str(self.workspace), task_id=TASK, checkpoint_store=self.store
        )

    def tearDown(self):
        self._workspace.cleanup()
        self._store.cleanup()

    def test_a_write_file_call_is_recorded_and_can_be_reverted(self):
        target = self.workspace / "app.py"
        target.write_text("v0\n", encoding="utf-8")
        # ``write_file`` refuses to overwrite content this run has not read, so the
        # real sequence is read first, then write.
        self.registry.execute_tool("read_file", {"file_path": "app.py"})

        self.registry.execute_tool(
            "write_file", {"file_path": "app.py", "content": "v1\n", "encoding": "utf-8"}
        )

        self.assertEqual([item.path for item in self.store.changes(TASK)], ["app.py"])
        self.store.revert(TASK)
        self.assertEqual(target.read_text(encoding="utf-8"), "v0\n")

    def test_a_creating_write_is_recorded_as_an_addition(self):
        self.registry.execute_tool(
            "write_file", {"file_path": "new.txt", "content": "hi\n", "encoding": "utf-8"}
        )

        self.assertEqual(self.store.changes(TASK)[0].status, STATUS_ADDED)

    def test_reading_a_file_records_nothing(self):
        (self.workspace / "app.py").write_text("v0\n", encoding="utf-8")

        self.registry.execute_tool("read_file", {"file_path": "app.py"})

        self.assertEqual(self.store.changes(TASK), [])


if __name__ == "__main__":
    unittest.main()
