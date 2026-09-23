"""A command attached to a pseudo terminal: the machinery behind ``tty``.

Two platforms, two mechanisms, one narrow contract (see
``docs/decisions/0009-exec-tty.md``):

- **Windows**: ``pywinpty``, which drives ConPTY (``CreatePseudoConsole``). Its
  ``read`` hands back *text*, so this module bridges the stream back to bytes: the
  rest of the codebase treats command output as bytes (``decode_capture``, the log
  file, the token budget).
- **POSIX**: the standard library's ``pty`` (``openpty``) plus an ordinary
  ``subprocess.Popen`` whose three standard streams are the slave end. The child
  gets its own process group but **no controlling terminal**: setting one up needs
  ``setsid`` + ``TIOCSCTTY`` from inside the child, and the only hook for that is
  ``preexec_fn``, which this project refuses to use in a threaded process (see
  :mod:`agent.tools.process_group`). Programs still see ``isatty() == True``; job
  control is not guaranteed, and Ctrl-C is delivered out of band (``killpg``)
  rather than by the terminal driver.

What this module deliberately does **not** do: decide liveness, or stop anything.
The Job Object / process group in :mod:`agent.tools.process_group` stays the single
authority for stopping a tree (ADR 0005 D2); a terminal only reads, writes and
closes.

``read`` blocks and has no deadline on either platform, so a consumer must never
read inline: :class:`PtyReader` reads on its own thread, and liveness is decided by
polling the child, never by waiting for a read to return. Because the read also
does not end when the child exits, a reader is finished off by *closing the
terminal*, which is why :meth:`PtyReader.settle` drains the tail first.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# Pseudo terminals are sized in character cells. Fixed at the reference default:
# the model cannot see a terminal, so columns/rows are not a tool parameter and
# there is no resize path (see ADR 0009).
DEFAULT_ROWS = 24
DEFAULT_COLS = 80

READ_CHUNK = 4096

# How often the read loop looks up when a platform's read returns "no data yet".
READ_POLL_SECONDS = 0.02

# How long a reader is given to wind down after its terminal is closed.
CLOSE_GRACE_SECONDS = 1.0

# A reader is considered drained once this long passes with no new bytes.
SETTLE_QUIET_SECONDS = 0.3
SETTLE_MAX_SECONDS = 3.0

WINDOWS = os.name == "nt"


class PtyUnavailable(Exception):
    """Raised when this machine cannot allocate a pseudo terminal."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> dict:
        return {"error": self.message, "reason": self.reason, **self.details}


_AVAILABILITY: Optional[Tuple[bool, str]] = None


def availability() -> Tuple[bool, str]:
    """``(available, why_not)`` for this machine.

    The reason is written for the model: it is what a rejected ``tty`` call says
    instead of silently running without a terminal, which would let the model go on
    believing it is talking to a TTY.
    """
    global _AVAILABILITY
    if _AVAILABILITY is not None:
        return _AVAILABILITY
    if WINDOWS:
        try:
            import winpty  # noqa: F401
        except ImportError:
            _AVAILABILITY = (
                False,
                "pywinpty is not installed, so no ConPTY can be allocated on Windows.",
            )
        else:
            _AVAILABILITY = (True, "")
    else:
        try:
            import pty  # noqa: F401
            import termios  # noqa: F401
        except ImportError:  # pragma: no cover - the stdlib has both on POSIX
            _AVAILABILITY = (False, "This platform's standard library has no pty module.")
        else:
            _AVAILABILITY = (True, "")
    return _AVAILABILITY


def normalize_windows_input(data: bytes) -> bytes:
    """Turn line feeds into the carriage return ConPTY treats as Enter.

    Pure and platform independent so it can be tested anywhere. Typing ``\\n`` under
    ConPTY is *not* Enter: the console echoes the character but never submits the
    line, which is why the model's habitual ``\\n`` is translated on the way in
    (verified against pywinpty 3.0.5, see ADR 0009).
    """
    return data.replace(b"\r\n", b"\r").replace(b"\n", b"\r")


@dataclass
class PtyTerminal:
    """One child attached to a pseudo terminal.

    Subclasses are per platform; everything above this class treats a terminal as
    "read bytes, write bytes, is it alive, close it".
    """

    child: Any
    reader: Optional["PtyReader"] = None

    # ``True`` when an empty read means end of output (POSIX); ``False`` when it only
    # means "nothing yet" (Windows, where the stream ends by the socket closing).
    ends_on_empty_read: bool = False

    @property
    def pid(self) -> Optional[int]:  # pragma: no cover - overridden
        raise NotImplementedError

    def read(self) -> bytes:  # pragma: no cover - overridden
        raise NotImplementedError

    def write(self, data: bytes) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def alive(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def exit_code(self) -> Optional[int]:  # pragma: no cover - overridden
        raise NotImplementedError

    def wait(self, timeout: float) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def terminate(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass
class _PosixTerminal(PtyTerminal):
    """A ``pty.openpty`` master plus the ``Popen`` holding the slave end."""

    master: int = -1
    ends_on_empty_read: bool = True
    _closed: bool = False

    @property
    def pid(self) -> Optional[int]:
        return int(self.child.pid)

    def read(self) -> bytes:
        if self._closed:
            raise EOFError("The terminal is closed.")
        try:
            return os.read(self.master, READ_CHUNK)
        except OSError:
            # EIO once the last writer on the slave side is gone: end of output.
            return b""

    def write(self, data: bytes) -> None:
        try:
            os.write(self.master, data)
        except OSError as exc:
            raise OSError(f"The terminal is no longer writable: {exc}") from exc

    def alive(self) -> bool:
        return self.child.poll() is None

    def exit_code(self) -> Optional[int]:
        return self.child.returncode

    def wait(self, timeout: float) -> bool:
        import subprocess

        try:
            self.child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self.master)
        except OSError:  # pragma: no cover - the master is ours
            pass

    def terminate(self) -> None:
        try:
            self.child.terminate()
        except OSError:  # pragma: no cover - already gone
            pass


@dataclass
class _WindowsTerminal(PtyTerminal):
    """A ``winpty.PtyProcess`` (ConPTY behind a text-level API)."""

    ends_on_empty_read: bool = False
    _closed: bool = False

    @property
    def pid(self) -> Optional[int]:
        return int(self.child.pid) if self.child.pid is not None else None

    def read(self) -> bytes:
        if self._closed:
            raise EOFError("The terminal is closed.")
        # pywinpty answers "nothing to report right now" with an empty string rather
        # than blocking again, so an empty read is not an end of stream here: the
        # stream ends when the socket closes, which is reported as EOFError.
        chunk = self.child.read(READ_CHUNK)
        return chunk.encode("utf-8") if chunk else b""

    def write(self, data: bytes) -> None:
        payload = normalize_windows_input(data).decode("utf-8", errors="replace")
        try:
            self.child.write(payload)
        except EOFError as exc:
            # Callers catch OSError; keep one failure shape across platforms.
            raise OSError("The terminal is no longer writable.") from exc

    def alive(self) -> bool:
        return bool(self.child.isalive())

    def exit_code(self) -> Optional[int]:
        if self.alive():
            return None
        try:
            return int(self.child.exitstatus)
        except Exception:  # noqa: BLE001  # pragma: no cover - defensive
            return None

    def wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if not self.alive():
                return True
            time.sleep(READ_POLL_SECONDS)
        return not self.alive()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            # Closing the ConPTY also stops whatever still holds the console, the same
            # way releasing a Windows job does (``KILL_ON_JOB_CLOSE``).
            self.child.close()
        except Exception:  # noqa: BLE001  # pragma: no cover - teardown
            pass

    def terminate(self) -> None:
        try:
            self.child.terminate(force=True)
        except Exception:  # noqa: BLE001  # pragma: no cover - teardown
            pass


def spawn(
    argv: Any,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    rows: int = DEFAULT_ROWS,
    cols: int = DEFAULT_COLS,
) -> PtyTerminal:
    """Start ``argv`` attached to a fresh pseudo terminal.

    Raises :class:`PtyUnavailable` when this machine cannot give us one.
    """
    ok, why_not = availability()
    if not ok:
        raise PtyUnavailable(why_not, reason="tty_unavailable", platform=os.name)
    argv = list(argv)
    if WINDOWS:
        return _spawn_windows(argv, cwd, env, rows, cols)
    return _spawn_posix(argv, cwd, env, rows, cols)


def _spawn_windows(
    argv: list, cwd: Optional[str], env: Optional[dict], rows: int, cols: int
) -> PtyTerminal:  # pragma: no cover - platform specific
    import winpty

    try:
        child = winpty.PtyProcess.spawn(
            argv, cwd=cwd, env=env, dimensions=(rows, cols)
        )
    except Exception as exc:  # noqa: BLE001 - winpty raises bare exceptions
        raise PtyUnavailable(
            f"The command could not be attached to a ConPTY: {exc}",
            reason="tty_spawn_failed",
            platform=os.name,
        ) from exc
    return _WindowsTerminal(child=child)


def _spawn_posix(
    argv: list, cwd: Optional[str], env: Optional[dict], rows: int, cols: int
) -> PtyTerminal:
    import fcntl
    import pty
    import struct
    import subprocess
    import termios

    master, slave = pty.openpty()
    try:
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:  # pragma: no cover - sizing is best effort
            pass
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            # A session of its own, like every other command this project runs; the
            # terminal is not made the controlling one (see the module docstring).
            start_new_session=True,
        )
    except Exception:
        os.close(slave)
        os.close(master)
        raise
    os.close(slave)
    return _PosixTerminal(child=child, master=master)


class PtyReader:
    """Reads a terminal on its own thread, pushing bytes into a sink."""

    def __init__(self, terminal: PtyTerminal, sink: Callable[[bytes], None]) -> None:
        self._terminal = terminal
        self._sink = sink
        self._thread = threading.Thread(
            target=self._run, name="pty-reader", daemon=True
        )
        self._lock = threading.Lock()
        self._size = 0
        self._finished = False
        self._thread.start()

    @property
    def size(self) -> int:
        with self._lock:
            return self._size

    def alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            while True:
                chunk = self._terminal.read()
                if chunk:
                    with self._lock:
                        self._size += len(chunk)
                    self._sink(chunk)
                    continue
                if self._terminal.ends_on_empty_read:
                    return
                time.sleep(READ_POLL_SECONDS)
        except Exception:  # noqa: BLE001 - a read failure means "no more output"
            pass
        finally:
            self._finished = True

    def settle(
        self,
        quiet_seconds: float = SETTLE_QUIET_SECONDS,
        limit_seconds: float = SETTLE_MAX_SECONDS,
    ) -> None:
        """Drain the tail: return once no new bytes arrive for a moment.

        Closing a terminal ends a read, so closing before the buffered output has
        been consumed would silently drop the last thing a command printed. Bounded,
        because a terminal that never goes quiet must not hold up a release.
        """
        deadline = time.monotonic() + limit_seconds
        last = self.size
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            if not self.alive():
                return
            current = self.size
            if current != last:
                last = current
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= quiet_seconds:
                return
            time.sleep(READ_POLL_SECONDS)

    def join(self, timeout: float = CLOSE_GRACE_SECONDS) -> bool:
        """Wait for the thread to end; ``False`` if it is still reading."""
        self._thread.join(timeout=max(0.0, timeout))
        return not self._thread.is_alive()


class FileSink:
    """Appends every chunk to a log file, which is what background sessions read."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def __call__(self, chunk: bytes) -> None:
        try:
            with self.path.open("ab", buffering=0) as handle:
                handle.write(chunk)
        except OSError:
            # A log we cannot append to is "no output", not a failed session.
            pass


@dataclass
class BytesSink:
    """Keeps every chunk in memory, for a foreground command's captured output."""

    _chunks: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, chunk: bytes) -> None:
        with self._lock:
            self._chunks.append(chunk)

    def bytes(self) -> bytes:
        with self._lock:
            return b"".join(self._chunks)
