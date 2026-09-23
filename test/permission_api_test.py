"""Integration tests for the permission endpoints (ADR 0006).

Run from the repository root::

    uv run python test/permission_api_test.py -v

These cover what the unit tests cannot reach: the decision endpoint that unblocks
a parked task thread, the global mode config, the rule CRUD, and the
``pendingPermission`` field the UI renders from.

The process-wide stores (task database, rule file, mode) are swapped for temporary
ones in ``setUp``, so nothing here reads or writes the developer's data.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.models import TaskStatus  # noqa: E402
from agent.tools.permission_rules import PermissionRuleStore  # noqa: E402
from agent.tools.permissions import (  # noqa: E402
    PERMISSION_EXEC,
    SCOPE_ONCE,
    PermissionBroker,
    PermissionMode,
)
from task_store import _SqliteTaskStore  # noqa: E402

WAIT_SECONDS = 30.0


class PermissionApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self._previous_store = main.monitor_store
        self._previous_rules = main.permission_rule_store
        self._previous_mode = main._agent_permission_mode
        self._previous_source = main._agent_permission_mode_source
        self.store = _SqliteTaskStore(root / "tasks.db")
        self.rules = PermissionRuleStore(root / "permission_rules.json")
        main.monitor_store = self.store
        main.permission_rule_store = self.rules
        main._agent_permission_mode = PermissionMode.ASK
        main._agent_permission_mode_source = "env"
        self.client = TestClient(main.app)

    def tearDown(self):
        with main._task_permission_lock:
            main._task_permission_brokers.clear()
        main.monitor_store = self._previous_store
        main.permission_rule_store = self._previous_rules
        main._agent_permission_mode = self._previous_mode
        main._agent_permission_mode_source = self._previous_source
        self.store.close()
        self._tmp.cleanup()

    # ------------------------------------------------------------------ helpers

    def register_broker(self, task_id="task-1"):
        # ``rules`` must be the swapped-in store: the default one points at the
        # repository's real rule file, and a test must not write there.
        broker = PermissionBroker(
            task_id=task_id, wait_seconds=WAIT_SECONDS, rules=main.permission_rule_store
        )
        main._register_task_permission(task_id, broker)
        return broker

    def park(self, broker, command="ls"):
        """Run a gated call in a thread, returning once the broker has asked."""
        box = {}

        def runner():
            box["result"] = broker.check("exec_command", PERMISSION_EXEC, {"command": command})

        thread = threading.Thread(target=runner)
        thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            pending = broker.pending()
            if pending is not None:
                return thread, box, pending
            time.sleep(0.01)
        raise AssertionError("the broker never asked")

    def decide(self, task_id, request_id, allowed=True, scope="once"):
        return self.client.post(
            f"/api/tasks/{task_id}/permission/{request_id}",
            json={"allowed": allowed, "scope": scope},
        )

    # ---------------------------------------------------------------- decisions

    def test_unknown_task_is_not_found(self):
        response = self.decide("nope", "abc")

        self.assertEqual(response.status_code, 404)

    def test_answering_unblocks_the_waiting_thread(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        response = self.decide("task-1", pending.request_id, allowed=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["allowed"], True)
        thread.join(timeout=5.0)
        self.assertIsNone(box["result"], "an approved call returns None to mean 'proceed'")
        self.assertIsNone(broker.pending())

    def test_a_denial_reaches_the_model_as_a_result_not_an_exception(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        response = self.decide("task-1", pending.request_id, allowed=False)

        self.assertEqual(response.status_code, 200)
        thread.join(timeout=5.0)
        self.assertIn("user_denied", box["result"].model_text)

    def test_answering_a_resolved_request_again_is_a_conflict(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)
        self.decide("task-1", pending.request_id, allowed=True)
        thread.join(timeout=5.0)

        again = self.decide("task-1", pending.request_id, allowed=True)

        self.assertEqual(again.status_code, 409)

    def test_always_scope_writes_a_rule_through_the_api(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        self.decide("task-1", pending.request_id, allowed=True, scope="always")
        thread.join(timeout=5.0)

        rules = self.client.get("/api/admin/permission-rules").json()["rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["tool"], "exec_command")
        self.assertEqual(rules[0]["target"], pending.target)

    # -------------------------------------------------------------- mode config

    def test_a_scope_the_tool_refuses_is_rejected_by_the_api(self):
        broker = self.register_broker()
        box = {}

        def runner():
            box["result"] = broker.check(
                "write_stdin",
                PERMISSION_EXEC,
                {"session_id": "abc123", "chars": "x\n"},
                scopes=(SCOPE_ONCE,),
            )

        thread = threading.Thread(target=runner)
        thread.start()
        deadline = time.monotonic() + 5.0
        pending = None
        while time.monotonic() < deadline:
            pending = broker.pending()
            if pending is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(pending)

        refused = self.decide("task-1", pending.request_id, allowed=True, scope="always")

        self.assertEqual(refused.status_code, 400)
        # Refused rather than applied: the task is still parked.
        self.assertIsNotNone(broker.pending())
        # A scope the tool does accept still works.
        accepted = self.decide("task-1", pending.request_id, allowed=True, scope="once")
        self.assertEqual(accepted.status_code, 200)
        thread.join(timeout=5.0)

    def test_an_unknown_scope_is_rejected_rather_than_downgraded_to_once(self):
        broker = self.register_broker()
        thread, box, pending = self.park(broker)

        response = self.decide("task-1", pending.request_id, allowed=True, scope="sometimes")

        self.assertEqual(response.status_code, 400)
        # Still parked, because the decision was refused rather than applied.
        self.assertIsNotNone(broker.pending())
        self.decide("task-1", pending.request_id, allowed=False)
        thread.join(timeout=5.0)

    def test_permission_mode_config_round_trips(self):
        self.assertEqual(self.client.get("/api/admin/permission-mode").json()["mode"], "ask")

        updated = self.client.put("/api/admin/permission-mode", json={"mode": "auto_approve"})

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["mode"], "auto_approve")
        self.assertEqual(updated.json()["source"], "database")
        self.assertEqual(
            self.client.get("/api/admin/permission-mode").json()["mode"], "auto_approve"
        )

    def test_an_unknown_permission_mode_is_rejected_rather_than_coerced(self):
        response = self.client.put("/api/admin/permission-mode", json={"mode": "whatever"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/admin/permission-mode").json()["mode"], "ask")

    # -------------------------------------------------------------- rule CRUD

    def test_rule_crud(self):
        self.assertEqual(self.client.get("/api/admin/permission-rules").json()["rules"], [])

        created = self.client.post(
            "/api/admin/permission-rules", json={"tool": "exec_command", "target": "git status"}
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["tool"], "exec_command")

        # Adding it twice must not duplicate it.
        self.client.post(
            "/api/admin/permission-rules", json={"tool": "exec_command", "target": "git status"}
        )
        self.assertEqual(len(self.client.get("/api/admin/permission-rules").json()["rules"]), 1)

        removed = self.client.delete(
            "/api/admin/permission-rules", params={"tool": "exec_command", "target": "git status"}
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.get("/api/admin/permission-rules").json()["rules"], [])

        again = self.client.delete(
            "/api/admin/permission-rules", params={"tool": "exec_command", "target": "git status"}
        )
        self.assertEqual(again.status_code, 404)

    # --------------------------------------------------------- waiting visibility

    def test_task_detail_and_list_expose_the_pending_permission(self):
        task_id = main.monitor_store.create_task("do something", "openai-compatible")
        broker = self.register_broker(task_id=task_id)
        thread, box, pending = self.park(broker)

        detail = self.client.get(f"/api/tasks/{task_id}").json()
        self.assertIsNotNone(detail["pending_permission"])
        self.assertEqual(detail["pending_permission"]["request_id"], pending.request_id)

        listed = self.client.get("/api/tasks").json()["tasks"]
        item = [entry for entry in listed if entry["task_id"] == task_id][0]
        self.assertEqual(item["pending_permission"]["request_id"], pending.request_id)

        self.decide(task_id, pending.request_id, allowed=False)
        thread.join(timeout=5.0)
        self.assertIsNone(self.client.get(f"/api/tasks/{task_id}").json()["pending_permission"])

    def test_a_waiting_task_reports_the_waiting_status(self):
        task_id = main.monitor_store.create_task("do something", "openai-compatible")

        main.monitor_store.set_task_status(task_id, TaskStatus.WAITING)

        self.assertEqual(self.client.get(f"/api/tasks/{task_id}").json()["status"], "waiting")


if __name__ == "__main__":
    unittest.main()
