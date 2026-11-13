"""The loop reads streamed turns, and the event log keeps the reasoning.

Two things have to hold: the assistant message that goes back into the conversation
carries no reasoning (gateways reject it), and the event the UI reads carries the
reasoning plus how long the answer took to start.

Run from the repository root::

    uv run python test/agent_loop_stream_test.py -v
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
from agent.models import EventCategory  # noqa: E402
from agent.provider import StreamDelta  # noqa: E402


class _Registry:
    base_dir = None
    read_only_roots = ()
    permission_broker = None
    user_question_broker = None

    def __init__(self):
        self.executed = []

    def get_tool_schemas(self, provider):
        return []

    def execute_tool(self, name, arguments):
        self.executed.append((name, arguments))
        return "file body"


class _StreamingProvider:
    wire_compatible_with_openai = True
    supports_streaming = True

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")
        self.requests = []

    def build_request_payload(self, messages, tools=None, **kwargs):
        self.requests.append([dict(message) for message in messages])
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        raise AssertionError("streaming provider must be read through the stream")

    def stream_chat_completion(self, messages, tools=None, **kwargs):
        if len(self.requests) == 1:
            yield StreamDelta(reasoning="I should read the file. ")
            yield StreamDelta(reasoning="Then answer.")
            yield StreamDelta(content="Reading.")
            yield StreamDelta(
                tool_calls=[{"index": 0, "id": "call-1", "name": "read_file", "arguments": ""}]
            )
            yield StreamDelta(tool_calls=[{"index": 0, "arguments": '{"path": "a.txt"}'}])
            yield StreamDelta(finish_reason="tool_calls")
            yield StreamDelta(
                usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
            )
            return
        yield StreamDelta(reasoning="The file is short.")
        yield StreamDelta(content="done")
        yield StreamDelta(finish_reason="stop")


class _OneShotProvider:
    """An adapter with no stream mode: the loop must still complete the turn."""

    wire_compatible_with_openai = True

    def __init__(self):
        self.config = SimpleNamespace(provider="openai", model="fake-model")

    def build_request_payload(self, messages, tools=None, **kwargs):
        return {"messages": messages, "tools": tools or []}

    def chat_completion(self, messages, tools=None, **kwargs):
        message = SimpleNamespace(
            role="assistant",
            content="one shot",
            tool_calls=[],
            reasoning="quiet thinking",
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )


def _run(provider, *, stream=True, max_steps=2):
    registry = _Registry()
    events = []
    with patch(
        "agent.agent_loop.loop._build_runtime",
        return_value=("openai", registry, provider, []),
    ):
        result = run_react_loop(
            user_query="read a.txt",
            task_id="task-stream",
            max_steps=max_steps,
            verbose=False,
            stream=stream,
            event_sink=lambda task_id, event: events.append(event),
        )
    return result, registry, events


class StreamedTurnTest(unittest.TestCase):
    def test_the_response_event_carries_the_reasoning(self):
        provider = _StreamingProvider()

        _, _, events = _run(provider)

        responses = [e for e in events if e.category == EventCategory.LLM_RESPONSE]
        self.assertTrue(responses)
        data = responses[0].data
        self.assertEqual("I should read the file. Then answer.", data["reasoning"])
        self.assertTrue(data["stream"])
        self.assertEqual("tool_calls", data["finish_reason"])
        self.assertEqual(1, data["tool_call_count"])
        self.assertEqual(7, data["chunk_count"])

    def test_the_raw_response_keeps_usage_and_reasoning(self):
        provider = _StreamingProvider()

        _, _, events = _run(provider)

        data = [e for e in events if e.category == EventCategory.LLM_RESPONSE][0].data
        raw = data["raw_response"]
        self.assertEqual(18, raw["usage"]["total_tokens"])
        self.assertEqual(
            "I should read the file. Then answer.",
            raw["choices"][0]["message"]["reasoning_content"],
        )

    def test_the_reasoning_never_goes_back_to_the_model(self):
        provider = _StreamingProvider()

        _run(provider)

        second_request = provider.requests[1]
        assistant = [m for m in second_request if m.get("role") == "assistant"][0]
        self.assertNotIn("reasoning_content", assistant)
        self.assertEqual("Reading.", assistant["content"])

    def test_the_streamed_tool_call_runs_with_stitched_arguments(self):
        provider = _StreamingProvider()

        result, registry, _ = _run(provider)

        self.assertEqual([("read_file", {"path": "a.txt"})], registry.executed)
        self.assertEqual("done", result)

    def test_the_request_event_reports_the_stream_mode(self):
        provider = _StreamingProvider()

        _, _, events = _run(provider)

        data = [e for e in events if e.category == EventCategory.LLM_REQUEST][0].data
        self.assertTrue(data["stream"])
        self.assertTrue(data["raw_request"]["stream"])


class OneShotFallbackTest(unittest.TestCase):
    def test_an_adapter_without_a_stream_mode_still_completes_the_turn(self):
        provider = _OneShotProvider()

        result, _, events = _run(provider)

        self.assertEqual("one shot", result)
        data = [e for e in events if e.category == EventCategory.LLM_RESPONSE][0].data
        self.assertFalse(data["stream"])
        self.assertEqual("quiet thinking", data["reasoning"])
        self.assertEqual(5, data["raw_response"]["usage"]["total_tokens"])

    def test_opting_out_of_streaming_uses_the_one_shot_call(self):
        provider = _OneShotProvider()

        result, _, events = _run(provider, stream=False)

        self.assertEqual("one shot", result)
        data = [e for e in events if e.category == EventCategory.LLM_REQUEST][0].data
        self.assertFalse(data["stream"])
        self.assertNotIn("stream", data["raw_request"])


if __name__ == "__main__":
    unittest.main()
