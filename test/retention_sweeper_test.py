"""The retention sweep is periodic: the app's lifespan owns one hourly thread.

Request handlers no longer purge on their way in - a busy API would pay for the check
on every call. These tests pin the thread itself: it repeats on the interval, survives
a failed sweep, starts only once, and is started/stopped by the lifespan.

Run from the repository root::

    uv run python test/retention_sweeper_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.runtime import purge  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402


class _FakeStop:
    """Stands in for the module's ``threading.Event`` so ``_run`` returns."""

    def __init__(self, waits: int):
        self._waits_before_stop = waits
        self.waits = 0
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, _timeout: float) -> bool:
        self.waits += 1
        if self.waits >= self._waits_before_stop:
            self._set = True
        return self._set


class PurgeLoopTest(unittest.TestCase):
    def test_the_sweep_repeats_on_the_interval(self):
        fake = _FakeStop(3)
        with mock.patch.object(purge, "_stop", fake), mock.patch.object(
            purge, "purge_expired_tasks_with_log"
        ) as sweep:
            purge._run()

        self.assertEqual(3, sweep.call_count)
        self.assertEqual(3, fake.waits)

    def test_a_failed_sweep_does_not_kill_the_timer(self):
        fake = _FakeStop(2)
        with mock.patch.object(purge, "_stop", fake), mock.patch.object(
            purge,
            "purge_expired_tasks_with_log",
            side_effect=[RuntimeError("boom"), 0],
        ) as sweep:
            purge._run()

        self.assertEqual(2, sweep.call_count)

    def test_the_thread_starts_only_once_and_can_be_restarted(self):
        self.addCleanup(purge.stop_retention_sweeper)
        with mock.patch.object(
            purge, "purge_expired_tasks_with_log", return_value=0
        ), mock.patch.object(purge, "PURGE_INTERVAL_SECONDS", 0.01):
            self.assertTrue(purge.start_retention_sweeper())
            self.assertFalse(purge.start_retention_sweeper())
            purge.stop_retention_sweeper()

            self.assertTrue(purge.start_retention_sweeper())
            purge.stop_retention_sweeper()


class LifespanTest(unittest.TestCase):
    """The timed sweep must be wired to the app, or it would never fire."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._previous_store = state.monitor_store
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        state.monitor_store = self.store

    def tearDown(self):
        state.monitor_store = self._previous_store
        self.store.close()
        self._tmp.cleanup()

    def test_the_lifespan_starts_and_stops_the_sweeper(self):
        self.assertFalse(purge.is_running())
        with TestClient(main.app):
            self.assertTrue(purge.is_running())
        self.assertFalse(purge.is_running())


if __name__ == "__main__":
    unittest.main()
