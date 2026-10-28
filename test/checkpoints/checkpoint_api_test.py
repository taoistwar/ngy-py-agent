"""Integration tests for the undo endpoints (ADR 0020).

Run from the repository root::

    uv run python test/checkpoints/checkpoint_api_test.py -v

The process-wide stores are swapped for temporary ones, and the checkpoint root is
pointed at a temporary directory, so nothing here reads or writes the developer's
data.

The task in each test is created through the store and its change recorded through
the checkpoint store directly: the point under test is the routing between the two,
not the agent loop (``checkpoint_store_test.py`` covers that end).
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

from fastapi.testclient import TestClient  # noqa: E402

import app_state  # noqa: E402
import main  # noqa: E402
from agent.checkpoints import CheckpointStore  # noqa: E402
from agent.checkpoints import git as git_module  # noqa: E402
from agent.models import TaskStatus  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402


class CheckpointApiTest(unittest.TestCase):
    def setUp(self):
        if not git_module.available():
            self.skipTest("git is not installed on this machine")
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self._env = mock.patch.dict(
            os.environ, {"CHECKPOINT_ROOT": str(root / "checkpoints")}
        )
        self._env.start()

        self._previous_store = app_state.monitor_store
        self.store = _SqliteTaskStore(root / "tasks.db")
        app_state.monitor_store = self.store
        self.client = TestClient(main.app)

        self.workspace_id = self.store.create_workspace("ws", str(self.workspace))
        self.session_id = self.store.create_session("session", self.workspace_id)
        self.task_id = self.store.create_task("make it work", "openai", session_id=self.session_id)
        self.store.finish_task(self.task_id, success=True, result="Done.")

        self.path = self.workspace / "app.py"
        self.path.write_text("v0\n", encoding="utf-8")
        self.record("write_file", "app.py", "v1\n")

    def tearDown(self):
        self._env.stop()
        app_state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    # --- helpers ----------------------------------------------------------

    def record(self, tool: str, name: str, content: str) -> None:
        """Do what the registry does around one tool call."""
        checkpoint = CheckpointStore.for_run(str(self.workspace), self.task_id)
        checkpoint.begin(self.task_id, tool, {"file_path": name})
        (self.workspace / name).write_text(content, encoding="utf-8")
        checkpoint.end(self.task_id, tool, {"file_path": name})

    def changes(self):
        response = self.client.get(f"/api/tasks/{self.task_id}/changes")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # --- reading ----------------------------------------------------------

    def test_changes_lists_what_the_task_touched(self):
        payload = self.changes()

        self.assertTrue(payload["available"], payload["reason"])
        self.assertEqual([item["path"] for item in payload["files"]], ["app.py"])
        self.assertEqual(payload["files"][0]["status"], "modified")

    def test_diff_returns_the_patch_for_one_file(self):
        response = self.client.get(
            f"/api/tasks/{self.task_id}/changes/diff", params={"path": "app.py"}
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("-v0", response.json()["diff"])
        self.assertIn("+v1", response.json()["diff"])

    def test_unknown_task_is_a_404(self):
        response = self.client.get("/api/tasks/not-a-task/changes")

        self.assertEqual(response.status_code, 404)

    def test_a_run_without_checkpointing_says_so_instead_of_failing(self):
        with mock.patch.dict(os.environ, {"CHECKPOINT_ENABLED": "0"}):
            payload = self.changes()

        self.assertFalse(payload["available"])
        self.assertTrue(payload["reason"])
        self.assertEqual(payload["files"], [])

    # --- reverting --------------------------------------------------------

    def test_revert_restores_the_file_and_marks_the_task_reverted(self):
        response = self.client.post(f"/api/tasks/{self.task_id}/revert", json={})

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["restored"], ["app.py"])
        self.assertTrue(payload["clean"])
        self.assertEqual(payload["status"], TaskStatus.REVERTED.value)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "v0\n")

        task = self.store.get_task(self.task_id)
        self.assertEqual(task["status"], TaskStatus.REVERTED.value)

    def test_a_revert_is_recorded_as_an_event(self):
        self.client.post(f"/api/tasks/{self.task_id}/revert", json={})

        titles = [event["title"] for event in self.store.get_task(self.task_id)["events"]]

        self.assertIn("Task reverted", titles)

    def test_reverting_one_path_leaves_the_others_alone(self):
        self.record("write_file", "other.txt", "x\n")

        response = self.client.post(
            f"/api/tasks/{self.task_id}/revert", json={"paths": ["app.py"]}
        )

        payload = response.json()
        self.assertEqual(payload["restored"], ["app.py"])
        # A partial undo is not a final state: the task still has changes on disk.
        self.assertEqual(payload["status"], TaskStatus.SUCCESS.value)
        self.assertEqual(self.store.get_task(self.task_id)["status"], TaskStatus.SUCCESS.value)

    def test_a_conflict_is_reported_rather_than_forced(self):
        self.path.write_text("user edit\n", encoding="utf-8")

        response = self.client.post(f"/api/tasks/{self.task_id}/revert", json={})

        payload = response.json()
        self.assertEqual(payload["conflicts"], ["app.py"])
        self.assertEqual(payload["restored"], [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "user edit\n")


if __name__ == "__main__":
    unittest.main()
