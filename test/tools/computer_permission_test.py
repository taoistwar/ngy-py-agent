"""Tests for the ``computer`` permission kind (ADR 0011).

Run from the repository root::

    uv run python test/tools/computer_permission_test.py -v

The kind exists so the dialog can say "click on pid 10, window 0x2" instead of
"run computer_control", and so a session approval covers that window rather than
the whole desktop. These tests pin both down, plus the fail-closed timeout.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.permission_rules import PermissionRuleStore  # noqa: E402
from agent.tools.permissions import (  # noqa: E402
    PERMISSION_COMPUTER,
    REASON_TIMEOUT,
    SCOPE_SESSION,
    PermissionBroker,
    PermissionMode,
)

_CLICK = {
    "action": "click",
    "pid": 10,
    "window_id": "0x2",
    "element_token": "e1",
}


class ComputerPermissionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.events = []
        self.broker = PermissionBroker(
            task_id="task-1",
            emit=lambda category, title, data: self.events.append((category, title, data)),
            base_dir=str(self.root),
            wait_seconds=0.3,
            rules=PermissionRuleStore(path=self.root / "rules.json"),
            mode=PermissionMode.ASK,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def requests(self):
        return [event for event in self.events if event[0] == "permission_request"]

    def decisions(self):
        return [event for event in self.events if event[0] == "permission_decision"]

    def call_in_thread(self, arguments):
        box = {}

        def runner():
            box["result"] = self.broker.check(
                "computer_control", PERMISSION_COMPUTER, dict(arguments)
            )

        thread = threading.Thread(target=runner)
        thread.start()
        return thread, box

    def answer(self, allowed=True, scope="once", timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = self.broker.pending()
            if pending is not None:
                return self.broker.resolve(pending.request_id, allowed, scope)
            time.sleep(0.01)
        raise AssertionError("the broker never asked")

    def test_the_dialog_names_the_action_and_the_window(self):
        thread, box = self.call_in_thread(_CLICK)
        self.answer(allowed=False)
        thread.join(timeout=5.0)

        payload = self.requests()[0][2]
        self.assertEqual(payload["target"], "click:pid=10:window=0x2")
        self.assertEqual(payload["details"]["action"], "click")
        self.assertEqual(payload["details"]["pid"], 10)
        self.assertEqual(payload["details"]["window_id"], "0x2")
        self.assertIn("click", payload["summary"])
        self.assertIsNotNone(box["result"])

    def test_a_session_approval_covers_the_window_not_the_whole_desktop(self):
        thread, _box = self.call_in_thread(_CLICK)
        self.answer(allowed=True, scope=SCOPE_SESSION)
        thread.join(timeout=5.0)

        same_window = self.broker.check(
            "computer_control",
            PERMISSION_COMPUTER,
            {**_CLICK, "element_token": "e2"},
        )
        self.assertIsNone(same_window)
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(self.decisions()[-1][2]["reason"], "session_rule")

        other_window = self.call_in_thread({**_CLICK, "window_id": "0x9"})
        self.answer(allowed=False)
        other_window[0].join(timeout=5.0)

        self.assertEqual(len(self.requests()), 2, "another window must ask again")

    def test_launch_app_is_keyed_on_the_app_identity(self):
        thread, _box = self.call_in_thread(
            {"action": "launch_app", "aumid": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"}
        )
        self.answer(allowed=True, scope=SCOPE_SESSION)
        thread.join(timeout=5.0)

        self.assertIn("WindowsCalculator", self.requests()[0][2]["target"])

        again = self.broker.check(
            "computer_control",
            PERMISSION_COMPUTER,
            {"action": "launch_app", "aumid": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
        )
        self.assertIsNone(again)

        other = self.call_in_thread({"action": "launch_app", "name": "notepad"})
        self.answer(allowed=False)
        other[0].join(timeout=5.0)
        self.assertEqual(len(self.requests()), 2)

    def test_nobody_answering_means_no(self):
        denial = self.broker.check("computer_control", PERMISSION_COMPUTER, dict(_CLICK))

        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], REASON_TIMEOUT)
        self.assertEqual(denial.details["kind"], PERMISSION_COMPUTER)
        self.assertIn("Do not retry", denial.model_text)

    def test_a_malformed_action_is_not_asked_about(self):
        self.assertIsNone(
            self.broker.check("computer_control", PERMISSION_COMPUTER, {"pid": 1})
        )
        self.assertEqual(self.requests(), [])


if __name__ == "__main__":
    unittest.main()
