"""Tests for the pseudo-terminal layer behind ``exec_command``'s ``tty``.

Everything that must hold on every platform - the reader thread ending when the
terminal closes, the log sink, the Windows newline translation, the refusal when no
terminal can be allocated - is tested against a fake terminal. The OS allocation
itself is tested against the real thing, and skipped when this machine has none.

Run from the repository root::

    uv run python test/tools/pty_session_test.py -v
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools import pty_session  # noqa: E402


class FakeTerminal:
    """The reader's whole view of a terminal: ``read`` and one flag.

    ``ends_on_empty_read`` models the platform difference the reader has to live
    with: POSIX ends its stream with an empty read, Windows reports "nothing yet"
    with one and ends by closing (an ``EOFError``).
    """

    def __init__(self, chunks=(), ends_on_empty_read=False):
        self.chunks = list(chunks)
        self.ends_on_empty_read = ends_on_empty_read
        self.closed = threading.Event()

    def read(self) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        if self.closed.is_set():
            raise EOFError("The terminal is closed.")
        if self.ends_on_empty_read:
            return b""
        time.sleep(0.005)
        return b""

    def close(self) -> None:
        self.closed.set()


def wait_for(predicate, deadline_seconds=5.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ReaderTest(unittest.TestCase):
    def test_reader_collects_every_chunk_in_order(self):
        terminal = FakeTerminal([b"one", b"two", b"three"], ends_on_empty_read=True)
        sink = pty_session.BytesSink()

        reader = pty_session.PtyReader(terminal, sink)

        self.assertTrue(wait_for(lambda: reader.size == 11))
        reader.settle()
        self.assertEqual(sink.bytes(), b"onetwothree")

    def test_an_empty_read_that_is_not_the_end_does_not_stop_the_reader(self):
        # The Windows shape: a quiet moment must not look like end of output.
        terminal = FakeTerminal([b"first"], ends_on_empty_read=False)
        sink = pty_session.BytesSink()
        reader = pty_session.PtyReader(terminal, sink)
        self.assertTrue(wait_for(lambda: reader.size == 5))

        terminal.chunks.append(b"second")

        self.assertTrue(wait_for(lambda: reader.size == 11))
        self.assertTrue(reader.alive())
        self.assertEqual(sink.bytes(), b"firstsecond")

        terminal.close()
        self.assertTrue(reader.join(2.0))

    def test_settle_is_bounded_even_when_output_never_stops(self):
        class Chatty(FakeTerminal):
            def read(self) -> bytes:
                if self.closed.is_set():
                    raise EOFError("The terminal is closed.")
                return b"x" * 64

        terminal = Chatty()
        reader = pty_session.PtyReader(terminal, pty_session.BytesSink())

        started = time.monotonic()
        reader.settle(quiet_seconds=0.01, limit_seconds=0.2)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 2.0)
        terminal.close()
        self.assertTrue(reader.join(2.0))


class SinkTest(unittest.TestCase):
    def test_the_file_sink_appends_every_chunk_to_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.log"
            sink = pty_session.FileSink(path)

            sink(b"one ")
            sink(b"two")
            sink(b"\x00binary\xff")

            self.assertEqual(path.read_bytes(), b"one two\x00binary\xff")

    def test_a_log_that_cannot_be_written_is_not_an_error(self):
        sink = pty_session.FileSink(Path(tempfile.gettempdir()) / "missing-dir" / "x.log")

        sink(b"lost")  # must not raise: "no output" is never a failed session


class WindowsInputTest(unittest.TestCase):
    def test_newlines_become_the_carriage_return_conpty_needs(self):
        cases = (
            (b"hi\n", b"hi\r"),
            (b"hi\r\n", b"hi\r"),
            (b"hi\r", b"hi\r"),
            (b"a\nb\n", b"a\rb\r"),
            (b"plain", b"plain"),
            (b"", b""),
        )

        for given, expected in cases:
            with self.subTest(given=given):
                self.assertEqual(pty_session.normalize_windows_input(given), expected)


class AvailabilityTest(unittest.TestCase):
    def test_a_missing_dependency_is_reported_with_a_reason(self):
        with mock.patch.object(pty_session, "_AVAILABILITY", None), mock.patch.dict(
            sys.modules, {"winpty": None}
        ), mock.patch.object(pty_session, "WINDOWS", True):
            available, why_not = pty_session.availability()

        self.assertFalse(available)
        self.assertIn("pywinpty", why_not)

    def test_spawn_refuses_before_touching_the_os(self):
        with mock.patch.object(
            pty_session, "availability", return_value=(False, "no terminal here")
        ):
            with self.assertRaises(pty_session.PtyUnavailable) as caught:
                pty_session.spawn([sys.executable, "-c", "pass"])

        self.assertEqual(caught.exception.reason, "tty_unavailable")
        self.assertIn("no terminal here", caught.exception.message)
        self.assertEqual(caught.exception.to_dict()["platform"], os.name)

    def test_this_machine_answers_yes_or_says_why_not(self):
        available, why_not = pty_session.availability()

        if available:
            self.assertEqual(why_not, "")
        else:
            self.assertTrue(why_not)


@unittest.skipUnless(pty_session.availability()[0], "no pseudo terminal on this machine")
class RealTerminalTest(unittest.TestCase):
    def test_a_command_reports_itself_as_a_terminal(self):
        terminal = pty_session.spawn(
            [sys.executable, "-u", "-c", "import sys; print('isatty', sys.stdout.isatty())"]
        )
        sink = pty_session.BytesSink()
        reader = pty_session.PtyReader(terminal, sink)
        try:
            self.assertTrue(terminal.wait(20.0), "the command never finished")
            reader.settle()
        finally:
            terminal.close()
            reader.join(2.0)

        self.assertIn(b"isatty True", sink.bytes())
        self.assertEqual(terminal.exit_code(), 0)

    def test_closing_the_terminal_ends_a_reader_that_is_still_reading(self):
        # The mechanism release() depends on: a read never ends by itself, so the
        # close is what frees the thread (ADR 0009).
        terminal = pty_session.spawn([sys.executable, "-u", "-c", "import time; time.sleep(5)"])
        reader = pty_session.PtyReader(terminal, pty_session.BytesSink())
        time.sleep(0.3)
        self.assertTrue(reader.alive())

        terminal.close()

        self.assertTrue(reader.join(3.0))


if __name__ == "__main__":
    unittest.main()
