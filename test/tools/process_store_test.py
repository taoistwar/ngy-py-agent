"""Tests for the session store: ownership, limits, sweeps and task-end reaping.

A stub command stands in for a real process, so the guarantees (who may touch a
session, how many a task may hold, when one is dropped) are checked directly
instead of through timing.

Run from the repository root::

    uv run python test/tools/process_store_test.py -v
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import _reaps_task_sessions  # noqa: E402
from agent.tools import process_group, process_store  # noqa: E402


class StubProcess:
    """Just enough of ``subprocess.Popen`` for the store and its stop paths."""

    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.stdin = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = 1


def fake_loop(task_id=None, base_dir=None):
    """A stand-in for ``run_react_loop``'s signature, for the reaping wrapper."""
    return "done"


class ProcessStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._next_pid = 1000

    def tearDown(self):
        for session in process_store.list_sessions():
            process_store.forget(session.process_id)
        self._tmp.cleanup()

    def register(self, task_id="", workspace="/ws", running=True):
        self._next_pid += 1
        process = StubProcess(self._next_pid)
        if not running:
            process.returncode = 0
        log = self.root / f"{process.pid}.log"
        log.write_bytes(b"")
        command = process_group.RunningCommand(process=process, kind=process_group.KIND_PLAIN)
        return process_store.register(command, log, task_id=task_id, workspace=workspace)

    # --- ownership is a capability check ----------------------------------

    def test_get_matches_both_task_and_workspace(self):
        session = self.register(task_id="task-a", workspace="/ws")

        found = process_store.get(session.process_id, task_id="task-a", workspace="/ws")

        self.assertIs(found, session)

    def test_get_rejects_another_task(self):
        session = self.register(task_id="task-a", workspace="/ws")

        self.assertIsNone(process_store.get(session.process_id, task_id="task-b", workspace="/ws"))

    def test_get_rejects_another_workspace(self):
        session = self.register(task_id="task-a", workspace="/ws")

        self.assertIsNone(process_store.get(session.process_id, task_id="task-a", workspace="/other"))

    def test_get_without_a_scope_returns_the_session(self):
        session = self.register(task_id="task-a", workspace="/ws")

        self.assertIs(process_store.get(session.process_id), session)

    # --- limits and sweeps ------------------------------------------------

    def test_limit_refuses_the_next_live_session_for_the_same_task(self):
        for _ in range(process_store.MAX_LIVE_SESSIONS_PER_TASK):
            self.register(task_id="task-a")

        with self.assertRaises(process_store.SessionLimitReached):
            self.register(task_id="task-a")

        # The refusal is per task, not global.
        self.assertIsNotNone(self.register(task_id="task-b"))

    def test_finished_sessions_do_not_consume_a_slot(self):
        for _ in range(process_store.MAX_LIVE_SESSIONS_PER_TASK):
            self.register(task_id="task-a", running=False)

        self.assertIsNotNone(self.register(task_id="task-a"))

    def test_register_sweeps_finished_sessions(self):
        alive = self.register(task_id="task-a")
        dead = self.register(task_id="task-a", running=False)

        self.register(task_id="task-a")

        self.assertIsNone(process_store.get(dead.process_id))
        self.assertIsNotNone(process_store.get(alive.process_id))

    def test_sweep_stops_sessions_past_the_ttl(self):
        session = self.register(task_id="task-a")
        time.sleep(0.01)

        with mock.patch.object(process_store, "SESSION_TTL_SECONDS", 0.0):
            self.assertEqual(process_store.sweep(), 1)

        self.assertIsNone(process_store.get(session.process_id))
        self.assertIsNotNone(session.command.process.returncode)

    def test_stop_task_stops_only_its_own_sessions(self):
        mine = self.register(task_id="task-a")
        theirs = self.register(task_id="task-b")

        self.assertEqual(process_store.stop_task("task-a"), 1)

        self.assertIsNone(process_store.get(mine.process_id))
        self.assertIsNotNone(mine.command.process.returncode)
        self.assertIsNotNone(process_store.get(theirs.process_id))

    def test_stop_task_with_an_empty_id_is_a_noop(self):
        session = self.register(task_id="")

        self.assertEqual(process_store.stop_task(""), 0)
        self.assertIsNotNone(process_store.get(session.process_id))

    # --- reading the log --------------------------------------------------

    def test_read_new_returns_only_what_was_appended(self):
        session = self.register(task_id="task-a")
        session.log_path.write_bytes(b"first")

        self.assertEqual(process_store.read_new(session), b"first")
        self.assertEqual(process_store.read_new(session), b"")

        session.log_path.write_bytes(b"firstsecond")
        self.assertEqual(process_store.read_new(session), b"second")

    # --- the loop's task-end reaping --------------------------------------

    def test_the_loop_wrapper_reaps_its_task_sessions(self):
        session = self.register(task_id="task-a")
        wrapped = _reaps_task_sessions(fake_loop)

        self.assertEqual(wrapped(task_id="task-a"), "done")

        self.assertIsNone(process_store.get(session.process_id))
        self.assertIsNotNone(session.command.process.returncode)

    def test_the_loop_wrapper_keeps_unbound_sessions(self):
        session = self.register(task_id="")
        wrapped = _reaps_task_sessions(fake_loop)

        wrapped(task_id=None)

        self.assertIsNotNone(process_store.get(session.process_id))


if __name__ == "__main__":
    unittest.main()
