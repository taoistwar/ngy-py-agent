"""``AGENTS.md`` reaches the request the model actually receives.

The unit tests cover what a workspace contributes; this one covers the wiring into the
ReAct loop, plus the cases where it must *not* apply: a resumed or caller-owned
conversation already carries its system prompt, and a run with no workspace must not
adopt the repository it happens to be sitting in.

Run from the repository root::

    uv run python test/agent_loop_agents_md_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop import run_react_loop  # noqa: E402
from agent.agents_md import AgentsMdSettings  # noqa: E402


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        raise AssertionError("this test drives no tools")


class _FakeProvider:
    wire_compatible_with_openai = True

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        message = SimpleNamespace(role="assistant", content="final answer", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class AgentLoopAgentsMdTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)

    def write_agents_md(self, text: str) -> None:
        (self.workspace / "AGENTS.md").write_text(text, encoding="utf-8")

    def run_loop(self, provider, **kwargs):
        with patch(
            "agent.agent_loop.loop._build_runtime",
            return_value=("openai", _Registry(), provider, []),
        ):
            return run_react_loop(task_id="task-agents-md", max_steps=1, verbose=False, **kwargs)

    def test_the_system_prompt_carries_the_workspace_rules(self):
        self.write_agents_md("Always run `uv run pytest` before committing.")
        provider = _FakeProvider()

        self.run_loop(provider, user_query="do something", base_dir=str(self.workspace))

        system = provider.requests[0][0]
        self.assertEqual("system", system["role"])
        self.assertIn("Always run `uv run pytest` before committing.", system["content"])
        # The workspace root note still comes first: the rules are an addition, not a
        # replacement for the working directory the model needs to resolve paths.
        self.assertIn("## Working directory", system["content"])

    def test_a_workspace_without_the_file_changes_nothing(self):
        provider = _FakeProvider()

        self.run_loop(provider, user_query="do something", base_dir=str(self.workspace))

        self.assertNotIn("AGENTS.md", provider.requests[0][0]["content"])

    def test_the_global_setting_can_turn_the_block_off(self):
        self.write_agents_md("Always run `uv run pytest`.")
        provider = _FakeProvider()

        self.run_loop(
            provider,
            user_query="do something",
            base_dir=str(self.workspace),
            agents_md_settings=AgentsMdSettings(enabled=False),
        )

        self.assertNotIn("Always run `uv run pytest`.", provider.requests[0][0]["content"])

    def test_an_unbound_run_ignores_the_current_directory(self):
        # No workspace: the process merely sits in this repository, whose own AGENTS.md
        # is guidance for the people editing it. A run must not adopt it as its rules.
        self.write_agents_md("Always run `uv run pytest`.")
        provider = _FakeProvider()

        with patch("os.getcwd", return_value=str(self.workspace)):
            self.run_loop(provider, user_query="do something")

        self.assertNotIn("Always run `uv run pytest`.", provider.requests[0][0]["content"])

    def test_a_resumed_transcript_is_not_rewritten(self):
        self.write_agents_md("Always run `uv run pytest`.")
        provider = _FakeProvider()
        initial = [
            {"role": "system", "content": "as it was"},
            {"role": "user", "content": "carry on"},
        ]

        self.run_loop(
            provider,
            user_query="carry on",
            append_user_query=False,
            base_dir=str(self.workspace),
            initial_messages=initial,
        )

        self.assertEqual("as it was", provider.requests[0][0]["content"])
        self.assertEqual(2, len(provider.requests[0]))

    def test_the_task_log_names_the_files_that_were_loaded(self):
        self.write_agents_md("Root rule.")
        (self.workspace / "packages").mkdir()
        (self.workspace / "packages" / "foo").mkdir()
        (self.workspace / "packages" / "foo" / "AGENTS.md").write_text("Foo rule.", encoding="utf-8")
        events = []
        provider = _FakeProvider()

        self.run_loop(
            provider,
            user_query="do something",
            base_dir=str(self.workspace),
            event_sink=lambda task_id, event: events.append(event),
        )

        loaded = [event for event in events if event.title == "Loaded AGENTS.md"]
        self.assertEqual(1, len(loaded))
        self.assertEqual("AGENTS.md", loaded[0].data["root"])
        self.assertEqual(["packages/foo/AGENTS.md"], loaded[0].data["nested"])
        # The instructions themselves live in the prompt, not in the log.
        self.assertNotIn("Root rule.", str(loaded[0].data))


if __name__ == "__main__":
    unittest.main()
