"""Tests for the server-sent-events parser both HTTP transports share.

Run from the repository root::

    uv run python test/agent/mcp/mcp_sse_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.mcp.sse import SseEvent, parse_events  # noqa: E402


def _events(*lines: str) -> list[SseEvent]:
    return list(parse_events(lines))


class ParseEventsTest(unittest.TestCase):
    def test_a_block_is_dispatched_on_the_blank_line(self):
        events = _events("event: message", 'data: {"id": 1}', "")

        self.assertEqual(events, [SseEvent(event="message", data='{"id": 1}')])

    def test_several_data_lines_are_joined_with_a_newline(self):
        events = _events("data: first", "data: second", "")

        self.assertEqual(events[0].data, "first\nsecond")

    def test_the_event_name_defaults_to_message(self):
        events = _events("data: payload", "")

        self.assertEqual(events[0].event, "message")

    def test_a_comment_is_ignored_and_does_not_dispatch(self):
        events = _events(": keep-alive", "", "data: payload", "")

        self.assertEqual([event.data for event in events], ["payload"])

    def test_crlf_line_endings_are_tolerated(self):
        events = _events("event: endpoint\r\n", "data: /messages\r\n", "\r\n")

        self.assertEqual(events, [SseEvent(event="endpoint", data="/messages")])

    def test_a_trailing_block_without_a_blank_line_is_still_yielded(self):
        # The stream can die mid-event; dropping the last block would hide the message
        # that explains why.
        events = _events("data: last")

        self.assertEqual([event.data for event in events], ["last"])

    def test_a_field_without_a_colon_is_skipped(self):
        events = _events("data:ok", "nonsense", "")

        self.assertEqual(events[0].data, "ok")

    def test_other_fields_are_read_and_dropped(self):
        events = _events("id: 42", "retry: 1000", "data: payload", "")

        self.assertEqual(events, [SseEvent(event="message", data="payload")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
