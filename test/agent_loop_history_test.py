"""Where a session's earlier turns land in the messages sent to the model.

A task in a session continues the conversation: the earlier turns have to sit
between the system prompt and the new query, in that order. Getting this wrong
(system prompt last, or the history after the query) makes a follow-up read as a
reply to itself.

Run from the repository root::

    uv run python test/agent_loop_history_test.py -v
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


class AgentLoopHistoryTest(unittest.TestCase):
    def run_loop(self, provider, **kwargs):
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", _Registry(), provider, []),
        ):
            return run_react_loop(
                task_id="task-history",
                max_steps=1,
                verbose=False,
                **kwargs,
            )

    def test_earlier_turns_sit_between_the_system_prompt_and_the_new_query(self):
        provider = _FakeProvider()

        self.run_loop(
            provider,
            user_query="add tests for that",
            history_messages=[
                {"role": "user", "content": "create add()"},
                {"role": "assistant", "content": "created add()"},
            ],
        )

        request = provider.requests[0]
        self.assertEqual(
            ["system", "user", "assistant", "user"],
            [message["role"] for message in request],
        )
        self.assertEqual("create add()", request[1]["content"])
        self.assertEqual("created add()", request[2]["content"])
        self.assertEqual("add tests for that", request[3]["content"])

    def test_without_history_the_request_is_system_plus_the_query(self):
        provider = _FakeProvider()

        self.run_loop(provider, user_query="standalone task")

        self.assertEqual(
            ["system", "user"],
            [message["role"] for message in provider.requests[0]],
        )

    def test_an_empty_history_changes_nothing(self):
        provider = _FakeProvider()

        self.run_loop(provider, user_query="standalone task", history_messages=[])

        self.assertEqual(2, len(provider.requests[0]))

    def test_a_caller_system_prompt_still_comes_first(self):
        provider = _FakeProvider()
        initial = [{"role": "system", "content": "custom prompt"}]

        self.run_loop(
            provider,
            user_query="continue",
            initial_messages=initial,
            history_messages=[{"role": "user", "content": "earlier"}],
        )

        request = provider.requests[0]
        self.assertEqual("custom prompt", request[0]["content"])
        self.assertEqual("earlier", request[1]["content"])
        # The caller's list is not edited by a run that merged history into it.
        self.assertEqual([{"role": "system", "content": "custom prompt"}], initial)


if __name__ == "__main__":
    unittest.main()
