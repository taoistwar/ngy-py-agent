"""Server-sent events: the framing both HTTP MCP transports are built on.

The two transports use it differently - Streamable HTTP may answer a POST with either a
JSON body or an event stream, while the older SSE transport keeps one long GET stream
open and posts messages to a second URL - but the framing is identical, so it is parsed
once here.

Only ``event`` and ``data`` decide what a client does with a block; comments and the
remaining fields (``id``, ``retry``) are read and dropped, as the specification allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List


@dataclass(frozen=True)
class SseEvent:
    """One dispatched block: the event name and its joined ``data`` lines."""

    event: str
    data: str


def parse_events(lines: Iterable[str]) -> Iterator[SseEvent]:
    """Yield one event per blank-line-terminated block.

    ``lines`` is what ``requests`` gives with ``decode_unicode=True``: an iterator that
    drops the newline characters. A block that never completes (the stream died
    mid-event) is still yielded at the end - dropping it would hide the message that
    explains why the connection closed.
    """
    name = ""
    data: List[str] = []
    for raw in lines:
        line = str(raw).rstrip("\r\n")
        if not line:
            if data or name:
                yield SseEvent(event=name or "message", data="\n".join(data))
            name, data = "", []
            continue
        if line.startswith(":"):
            continue  # a comment, often a keep-alive
        field, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            data.append(value)
    if data or name:
        yield SseEvent(event=name or "message", data="\n".join(data))
