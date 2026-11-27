"""How a finished background command enters the conversation.

The contract with the provider: one tool call, one tool result. The placeholder already
answered the call, so the notification travels as its own ``user`` message - never as a
second ``tool`` result for the same call id.

Run from the repository root::

    uv run python test/agent/background_context_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop.background_context import inject_background_results  # noqa: E402
from agent.tools.background import BackgroundCommand, BackgroundResult  # noqa: E402


def result(session_id, exit_code=0, tail="ok"):
    return BackgroundResult(
        record=BackgroundCommand(
            session_id=session_id,
            pid=7,
            command="npm install",
            description="Install dependencies",
            log_path="/out/log",
        ),
        exit_code=exit_code,
        tail=tail,
    )


class StubLedger:
    def __init__(self, results):
        self._results = list(results)

    def collect(self):
        collected, self._results = self._results, []
        return collected


class InjectTest(unittest.TestCase):
    def test_nothing_finished_means_no_message(self):
        messages = []

        self.assertEqual(inject_background_results(messages, StubLedger([])), 0)
        self.assertEqual(messages, [])

    def test_a_run_without_a_ledger_is_a_no_op(self):
        messages = []

        self.assertEqual(inject_background_results(messages, None), 0)
        self.assertEqual(messages, [])

    def test_finished_commands_arrive_as_one_user_message(self):
        messages = [{"role": "tool", "tool_call_id": "call-1", "content": "started"}]
        ledger = StubLedger([result("aaaa1111"), result("bbbb2222", exit_code=1)])

        count = inject_background_results(messages, ledger)

        self.assertEqual(count, 2)
        self.assertEqual(len(messages), 2)
        notification = messages[1]
        self.assertEqual(notification["role"], "user")
        # No tool_call_id: this is not a second result for the placeholder call.
        self.assertNotIn("tool_call_id", notification)
        self.assertEqual(notification["content"].count("<task_notification>"), 2)
        self.assertIn("exit code 1", notification["content"])

    def test_a_second_turn_does_not_repeat_the_same_report(self):
        ledger = StubLedger([result("aaaa1111")])
        messages = []

        inject_background_results(messages, ledger)
        inject_background_results(messages, ledger)

        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()
