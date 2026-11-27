"""A finished background command is in the context before the model answers.

The placeholder already answered the tool call, so the report travels as its own
``user`` message. What matters at loop level is *when*: it has to be part of the
messages the step's request is built from, not something the model hears a turn
later (ADR 0034).

Run from the repository root::

    uv run python test/agent_loop_background_test.py -v
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.tools.background import BackgroundCommand, BackgroundResult  # noqa: E402


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        raise AssertionError("this test drives no tools")


class _Message:
    role = "assistant"

    def __init__(self, content=""):
        self.content = content
        self.tool_calls = []


class _Response:
    def __init__(self, message):
        self.choices = [SimpleNamespace(message=message, finish_reason="stop")]


class _FakeProvider:
    wire_compatible_with_openai = True

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        return _Response(_Message(content="final answer"))


class _Ledger:
    """A ledger whose finished commands are decided by the test."""

    def __init__(self, results):
        self._results = list(results)
        self.collect_calls = 0

    def collect(self):
        self.collect_calls += 1
        collected, self._results = self._results, []
        return collected

    def pending(self):
        return len(self._results)


def result(session_id="4a9c1e02"):
    return BackgroundResult(
        record=BackgroundCommand(
            session_id=session_id,
            pid=18344,
            command="npm install",
            description="Install dependencies",
            log_path="C:/out/20260101.log",
        ),
        exit_code=0,
        tail="added 212 packages in 8s",
    )


class LoopInjectionTest(unittest.TestCase):
    def run_loop(self, ledger, user_query="run the build"):
        provider = _FakeProvider()
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", _Registry(), provider, []),
        ):
            run_react_loop(
                task_id="task-background",
                max_steps=1,
                verbose=False,
                user_query=user_query,
                background=ledger,
            )
        self.assertEqual(len(provider.requests), 1, "the step never asked the model")
        return provider.requests[0]

    def test_the_notification_is_in_the_request_of_the_step_it_arrived_in(self):
        messages = self.run_loop(_Ledger([result()]))

        notification = messages[-1]
        self.assertEqual(notification["role"], "user")
        self.assertIn("<task_notification>", notification["content"])
        self.assertIn("Install dependencies", notification["content"])
        self.assertIn("exit code 0", notification["content"])
        # Not a second result for the placeholder call: nothing ties it to an id.
        self.assertNotIn("tool_call_id", notification)

    def test_the_query_comes_before_the_report(self):
        messages = self.run_loop(_Ledger([result()]), user_query="run the build")

        query_at = next(
            index for index, message in enumerate(messages) if message.get("content") == "run the build"
        )

        self.assertGreater(len(messages) - 1, query_at)

    def test_nothing_finished_means_the_context_is_untouched(self):
        messages = self.run_loop(_Ledger([]))

        self.assertFalse(any("<task_notification>" in str(message.get("content")) for message in messages))

    def test_the_ledger_is_asked_once_per_step(self):
        ledger = _Ledger([result()])

        self.run_loop(ledger)

        self.assertEqual(ledger.collect_calls, 1)


if __name__ == "__main__":
    unittest.main()
