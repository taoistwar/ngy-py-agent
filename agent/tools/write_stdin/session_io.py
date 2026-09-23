"""Typing into a session's stdin and reading back what it said.

A session is not a source file: a mis-decode must not stop the reply, so decoding
falls back to a replacement marker instead of raising.
"""

from __future__ import annotations

import time
from typing import List

from agent.tools import process_store
from agent.tools.text_encoding import DecodeError, decode_file_bytes
from agent.tools.write_stdin.errors import WriteStdinError
from agent.tools.write_stdin.rules import POLL_INTERVAL_SECONDS


def decode_output(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        return decode_file_bytes(raw, "utf-8").text
    except DecodeError:
        return raw.decode("utf-8", errors="replace")


def write_to_session(session: process_store.Session, chars: str) -> None:
    stream = session.command.process.stdin
    if stream is None:
        raise WriteStdinError(
            "This session has no writable stdin.",
            reason="no_stdin",
            session_id=session.process_id,
        )
    try:
        stream.write(chars.encode("utf-8"))
        stream.flush()
    except (OSError, ValueError) as exc:
        raise WriteStdinError(
            f"Could not write to the session: {exc}",
            reason="write_failed",
            session_id=session.process_id,
        ) from exc


def collect_output(session: process_store.Session, wait_ms: int) -> str:
    """Wait up to ``wait_ms`` for new output, returning as soon as there is some."""
    deadline = time.monotonic() + (wait_ms / 1000)
    chunks: List[bytes] = []
    while True:
        data = process_store.read_new(session)
        if data:
            chunks.append(data)
            break
        if session.command.poll() is not None:
            # Drain whatever the command printed on its way out.
            tail = process_store.read_new(session)
            if tail:
                chunks.append(tail)
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    return decode_output(b"".join(chunks))
