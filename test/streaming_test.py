"""Streaming is only useful if the folded result is the turn a one-shot call gives.

The loop parses complete turns; adapters answer in pieces. These tests pin the fold
between the two: content, reasoning, tool calls split across chunks, usage and the
timings shown next to them.

Run from the repository root::

    uv run python test/streaming_test.py -v
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.provider import StreamDelta  # noqa: E402
from agent.streaming import StreamAccumulator, consume_stream  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class ContentTest(unittest.TestCase):
    def test_pieces_become_one_message(self):
        accumulator = StreamAccumulator()
        accumulator.feed(StreamDelta(content="Hello"))
        accumulator.feed(StreamDelta(content=", "))
        accumulator.feed(StreamDelta(content="world"))
        accumulator.feed(StreamDelta(finish_reason="stop"))

        completion = accumulator.result()

        self.assertEqual("Hello, world", completion.content)
        self.assertEqual("stop", completion.finish_reason)
        self.assertEqual("assistant", completion.message["role"])

    def test_reasoning_is_carried_but_never_sent_back(self):
        accumulator = StreamAccumulator()
        accumulator.feed(StreamDelta(reasoning="first "))
        accumulator.feed(StreamDelta(reasoning="second"))
        accumulator.feed(StreamDelta(content="answer"))

        completion = accumulator.result()

        self.assertEqual("first second", completion.reasoning)
        self.assertEqual(
            "first second", completion.message["reasoning_content"]
        )
        # A gateway that receives its own reasoning back rejects or bills it.
        self.assertNotIn("reasoning_content", completion.request_message())

    def test_reasoning_alone_still_produces_a_message(self):
        # A model that thinks and then calls a tool says nothing in content.
        accumulator = StreamAccumulator()
        accumulator.feed(StreamDelta(reasoning="planning"))
        accumulator.feed(
            StreamDelta(
                tool_calls=[{"index": 0, "id": "call-1", "name": "read_file", "arguments": "{}"}]
            )
        )

        completion = accumulator.result()

        self.assertEqual("", completion.content)
        self.assertEqual("read_file", completion.message["tool_calls"][0]["function"]["name"])


class ToolCallTest(unittest.TestCase):
    def test_fragments_are_stitched_by_index(self):
        accumulator = StreamAccumulator()
        accumulator.feed(
            StreamDelta(
                tool_calls=[{"index": 0, "id": "call-1", "name": "read_file", "arguments": ""}]
            )
        )
        accumulator.feed(StreamDelta(tool_calls=[{"index": 0, "arguments": '{"path": '}]))
        accumulator.feed(StreamDelta(tool_calls=[{"index": 0, "arguments": '"a.txt"}'}]))

        calls = accumulator.result().message["tool_calls"]

        self.assertEqual(1, len(calls))
        self.assertEqual("call-1", calls[0]["id"])
        self.assertEqual("read_file", calls[0]["function"]["name"])
        self.assertEqual('{"path": "a.txt"}', calls[0]["function"]["arguments"])

    def test_parallel_calls_stay_separate(self):
        accumulator = StreamAccumulator()
        accumulator.feed(
            StreamDelta(
                tool_calls=[
                    {"index": 0, "id": "call-1", "name": "read_file", "arguments": '{"path": "a"}'},
                    {"index": 1, "id": "call-2", "name": "read_file", "arguments": '{"path": "b"}'},
                ]
            )
        )

        calls = accumulator.result().message["tool_calls"]

        self.assertEqual(["call-1", "call-2"], [call["id"] for call in calls])

    def test_a_restarted_index_does_not_merge_two_calls(self):
        # Some servers send every call at index 0; only the id tells them apart.
        accumulator = StreamAccumulator()
        accumulator.feed(
            StreamDelta(
                tool_calls=[{"index": 0, "id": "call-1", "name": "read_file", "arguments": "{}"}]
            )
        )
        accumulator.feed(
            StreamDelta(
                tool_calls=[{"index": 0, "id": "call-2", "name": "exec_command", "arguments": "{}"}]
            )
        )

        calls = accumulator.result().message["tool_calls"]

        self.assertEqual(["call-1", "call-2"], [call["id"] for call in calls])
        self.assertEqual(["read_file", "exec_command"], [call["function"]["name"] for call in calls])


class ReportingTest(unittest.TestCase):
    def test_usage_split_across_chunks_adds_up(self):
        # Anthropic sends input tokens at the start and output tokens at the end.
        accumulator = StreamAccumulator()
        accumulator.feed(StreamDelta(usage={"prompt_tokens": 40, "completion_tokens": 0}))
        accumulator.feed(StreamDelta(usage={"prompt_tokens": 0, "completion_tokens": 9}))

        usage = accumulator.result().usage

        self.assertEqual(40, usage["prompt_tokens"])
        self.assertEqual(9, usage["completion_tokens"])
        self.assertEqual(49, usage["total_tokens"])

    def test_usage_from_the_tail_chunk_is_kept(self):
        accumulator = StreamAccumulator()
        accumulator.feed(StreamDelta(content="done"))
        accumulator.feed(
            StreamDelta(usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        )

        completion = accumulator.result()

        self.assertEqual(18, completion.usage["total_tokens"])
        self.assertEqual(18, completion.raw_response()["usage"]["total_tokens"])
        self.assertEqual(2, completion.chunk_count)

    def test_timing_separates_time_to_first_token_from_total(self):
        clock = _Clock()
        accumulator = StreamAccumulator(clock=clock)

        clock.now = 0.4
        accumulator.feed(StreamDelta(reasoning="thinking"))
        clock.now = 1.9
        accumulator.feed(StreamDelta(content="done"))
        clock.now = 2.4
        completion = accumulator.result()

        # Waiting for the first token is the model; the rest is generation.
        self.assertEqual(400, completion.first_token_ms)
        self.assertEqual(2400, completion.duration_ms)

    def test_a_stream_without_content_reports_no_first_token(self):
        accumulator = StreamAccumulator()
        accumulator.feed(StreamDelta(finish_reason="stop"))

        self.assertIsNone(accumulator.result().first_token_ms)

    def test_consume_stream_drains_an_iterator(self):
        completion = consume_stream(iter([StreamDelta(content="a"), StreamDelta(content="b")]))

        self.assertEqual("ab", completion.content)
        self.assertEqual(2, completion.chunk_count)


if __name__ == "__main__":
    unittest.main()
