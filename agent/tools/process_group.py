"""One OS handle per command, so a command *and everything it started* can stop.

Only the OS knows what a command spawned, so the group is the OS's own notion:

- **POSIX**: a new session / process group (``start_new_session=True``), stopped
  with ``killpg``.
- **Windows**: a Job Object, stopped with ``TerminateJobObject``. The prototype in
  ``docs/decisions/0005-exec-tool.md`` killed a child *and its grandchild* in a
  single call - no ``taskkill /T``, no pid bookkeeping.

Resource limits are deliberately uneven across platforms:

- Windows gets a job wide memory cap and an active process cap (both overridable
  through the environment). This is what stops a runaway command.
- POSIX gets **no** memory cap. The only ways to apply one per child are
  ``preexec_fn`` (documented as unsafe in a multi threaded process, and every task
  here runs in a thread) or ``resource.prlimit`` (Linux only). Left out on purpose
  rather than faked; POSIX still gets authoritative tree termination.

A pid file may be written next to the log for identification after a crash or a
restart. It is never the kill mechanism - pids get recycled and files go stale.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from agent.tools import pty_session

WINDOWS = os.name == "nt"

KIND_POSIX = "posix"
KIND_WINDOWS_JOB = "windows-job"
KIND_PLAIN = "plain"

DEFAULT_ACTIVE_PROCESS_LIMIT = 64
DEFAULT_JOB_MEMORY_LIMIT_BYTES = 2 * 1024 ** 3

ACTIVE_PROCESS_LIMIT_ENV = "EXEC_ACTIVE_PROCESS_LIMIT"
JOB_MEMORY_LIMIT_MB_ENV = "EXEC_JOB_MEMORY_LIMIT_MB"

# Keeps a headless agent from popping console windows on Windows.
CREATE_NO_WINDOW = 0x08000000

# How long a command may take to honour an interrupt before it is forced down.
INTERRUPT_GRACE_SECONDS = 3.0

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

if WINDOWS:  # pragma: no cover - platform specific
    import ctypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOB_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _JOB_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOB_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _handle(value: int):
        return ctypes.c_void_p(value)


def _env_int(name: str, default: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@dataclass
class RunningCommand:
    """A started command plus the handle needed to stop its whole tree.

    ``process`` is the ``Popen`` for every pipe command and for a POSIX terminal
    command. A Windows terminal command has none: ConPTY is created by ``pywinpty``,
    which hands back a terminal rather than a ``Popen``, and pid/liveness/exit code
    are answered from that terminal instead. Consumers never look at either field
    directly - they use the methods below, so both shapes behave the same.
    """

    process: Optional[subprocess.Popen]
    kind: str
    pgid: Optional[int] = None
    job: Optional[int] = None
    limits: Dict[str, Any] = field(default_factory=dict)
    terminal: Optional["pty_session.PtyTerminal"] = None
    reader: Optional["pty_session.PtyReader"] = None
    sink: Any = None

    @property
    def pid(self) -> int:
        if self.process is not None:
            return int(self.process.pid)
        return int(self.terminal.pid)

    @property
    def returncode(self) -> Optional[int]:
        """The exit code once the command is gone; ``None`` while it runs."""
        if self.process is not None:
            return self.process.returncode
        return self.terminal.exit_code()

    def poll(self) -> Optional[int]:
        if self.process is not None:
            return self.process.poll()
        return self.terminal.exit_code()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for the command; ``False`` when ``timeout`` runs out first."""
        if self.process is not None:
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return False
            return True
        return self.terminal.wait(timeout or 0.0)

    def has_stdin(self) -> bool:
        """Whether anything can be typed into this command at all."""
        if self.terminal is not None:
            return True
        return self.process is not None and self.process.stdin is not None

    def write_input(self, data: bytes) -> None:
        """Type into the command: the terminal, or the stdin pipe.

        One entry point on purpose. A terminal command has no ``process.stdin``, so
        leaving the choice to consumers would give them two code paths and a wrong
        answer on one of them (ADR 0009).
        """
        if self.terminal is not None:
            self.terminal.write(data)
            return
        stream = self.process.stdin if self.process is not None else None
        if stream is None:
            raise OSError("This command has no writable stdin.")
        stream.write(data)
        stream.flush()

    def close_input(self) -> None:
        """Close the stdin pipe. A terminal is closed with the command, not alone."""
        stream = self.process.stdin if self.process is not None else None
        if stream is None:
            return
        try:
            stream.close()
        except OSError:  # pragma: no cover - platform specific
            pass

    def stop(self) -> None:
        """Stop the command and everything it started.

        Windows has no graceful equivalent for a job, so there :meth:`stop` and
        :meth:`kill` end the tree the same way.
        """
        if self.kind == KIND_POSIX and self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            return
        if self.kind == KIND_WINDOWS_JOB and self.job:  # pragma: no cover - platform specific
            _KERNEL32.TerminateJobObject(_handle(self.job), 1)
            return
        if self.terminal is not None:  # pragma: no cover - platform specific
            self.terminal.terminate()
            return
        try:
            self.process.terminate()
        except OSError:
            pass

    def kill(self) -> None:
        """Force the whole tree down."""
        if self.kind == KIND_POSIX and self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            return
        if self.kind == KIND_WINDOWS_JOB and self.job:  # pragma: no cover - platform specific
            _KERNEL32.TerminateJobObject(_handle(self.job), 1)
            return
        if self.terminal is not None:  # pragma: no cover - platform specific
            self.terminal.terminate()
            return
        try:
            self.process.kill()
        except OSError:
            pass

    def interrupt(self) -> None:
        """Ask the command to stop the way Ctrl-C would.

        POSIX gets a real ``SIGINT`` to the whole process group, so a program may
        run its own cleanup. Windows has no signal for a job, so the tree is
        terminated - the same hard stop as :meth:`stop`.
        """
        if self.kind == KIND_POSIX and self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGINT)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            return
        self.stop()

    def release(self) -> None:
        """Close the OS handles without stopping anything.

        A Windows job is created with ``KILL_ON_JOB_CLOSE``, so releasing it kills
        the survivors: background commands deliberately keep their handle instead.

        A terminal is released in a fixed order, because closing it is also what ends
        the blocked read: drain the tail first (the command may have printed its last
        line and exited, leaving the bytes buffered), then close the terminal, then
        join the reader. Skipping the drain silently truncates the log.
        """
        if self.reader is not None:
            self.reader.settle()
        if self.terminal is not None:
            self.terminal.close()
        if self.reader is not None:
            self.reader.join()
            self.reader = None
        if self.kind == KIND_WINDOWS_JOB and self.job:  # pragma: no cover - platform specific
            _KERNEL32.CloseHandle(_handle(self.job))
            self.job = None


def _create_job() -> tuple[Optional[int], Dict[str, Any]]:  # pragma: no cover - platform specific
    """Create a job with a memory cap and an active process cap."""
    import ctypes

    active_limit = _env_int(ACTIVE_PROCESS_LIMIT_ENV, DEFAULT_ACTIVE_PROCESS_LIMIT)
    memory_mb = _env_int(JOB_MEMORY_LIMIT_MB_ENV, DEFAULT_JOB_MEMORY_LIMIT_BYTES // (1024 * 1024))

    job = _KERNEL32.CreateJobObjectW(None, None)
    if not job:
        return None, {}

    info = _JOB_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | _JOB_OBJECT_LIMIT_JOB_MEMORY
    )
    info.BasicLimitInformation.ActiveProcessLimit = active_limit
    info.JobMemoryLimit = memory_mb * 1024 * 1024

    if not _KERNEL32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        _KERNEL32.CloseHandle(job)
        return None, {}

    return job, {"active_process_limit": active_limit, "job_memory_limit_mb": memory_mb}


def _assign_to_job(job: int, pid: int) -> bool:  # pragma: no cover - platform specific
    handle = _KERNEL32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return False
    try:
        return bool(
            _KERNEL32.AssignProcessToJobObject(_handle(job), _handle(handle))
        )
    finally:
        _KERNEL32.CloseHandle(_handle(handle))


def _attach_job(pid: int) -> Tuple[Optional[int], Dict[str, Any]]:
    """Put ``pid`` in a capped job, or give up.

    Shared by the pipe path and the ConPTY path: a terminal command must be capped
    and killable as a tree exactly like every other command (ADR 0009 keeps L1).
    """
    job, limits = _create_job()
    if not job:  # pragma: no cover - platform specific
        return None, {}
    if _assign_to_job(job, pid):
        return job, limits
    _KERNEL32.CloseHandle(_handle(job))
    return None, {}


def _spawn(
    argv: Sequence[str],
    cwd: Optional[str],
    env: Optional[Dict[str, str]],
    stdout: Any,
    stderr: Any,
    stdin: Any = None,
) -> RunningCommand:
    # ``None`` means "no input at all"; a pipe is only wired up when a caller wants
    # to type into the command later (see ``process_store``).
    stdin_target = subprocess.DEVNULL if stdin is None else stdin
    if WINDOWS:  # pragma: no cover - platform specific
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=stdin_target,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
        )
        job, limits = _attach_job(process.pid)
        if job:
            return RunningCommand(process=process, kind=KIND_WINDOWS_JOB, job=job, limits=limits)
        return RunningCommand(process=process, kind=KIND_PLAIN)

    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=stdin_target,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    try:
        pgid: Optional[int] = os.getpgid(process.pid)
    except OSError:
        pgid = process.pid
    return RunningCommand(process=process, kind=KIND_POSIX, pgid=pgid)


def start(
    argv: Sequence[str],
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> RunningCommand:
    """Start ``argv`` in its own process group, capturing its output."""
    return _spawn(argv, cwd, env, subprocess.PIPE, subprocess.PIPE)


def start_with_log(
    argv: Sequence[str],
    stdout_path: str,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    stdin: Any = None,
) -> RunningCommand:
    """Start ``argv`` with output appended straight to ``stdout_path``.

    Used for background commands: nothing is piped back, so the process cannot
    stall on a full pipe buffer once the caller stops reading. Pass
    ``stdin=subprocess.PIPE`` to keep the command's input open for
    :mod:`agent.tools.write_stdin_tool`.
    """
    handle = open(stdout_path, "ab", buffering=0)
    try:
        return _spawn(argv, cwd, env, handle, subprocess.STDOUT, stdin=stdin)
    finally:
        handle.close()


def _attach_reader(
    terminal: "pty_session.PtyTerminal", sink: Any
) -> "pty_session.PtyReader":
    """Start reading ``terminal`` on its own thread and remember it on the command."""
    reader = pty_session.PtyReader(terminal, sink)
    terminal.reader = reader
    return reader


def _running_from_terminal(
    terminal: "pty_session.PtyTerminal", sink: Any
) -> RunningCommand:
    """Wrap a terminal in a :class:`RunningCommand`, capped and killable as a tree.

    On POSIX the terminal's child *is* the ``Popen``, so the usual process-group path
    applies unchanged. On Windows there is no ``Popen`` at all, so the command is
    identified by pid and either joins a job or falls back to a plain (uncapped)
    command - the same fallback the pipe path takes when a job cannot be created.
    """
    reader = _attach_reader(terminal, sink)
    if WINDOWS:  # pragma: no cover - platform specific
        job, limits = _attach_job(terminal.pid)
        if job:
            return RunningCommand(
                process=None,
                kind=KIND_WINDOWS_JOB,
                job=job,
                limits=limits,
                terminal=terminal,
                reader=reader,
                sink=sink,
            )
        return RunningCommand(process=None, kind=KIND_PLAIN, terminal=terminal, reader=reader, sink=sink)

    child = terminal.child
    try:
        pgid: Optional[int] = os.getpgid(int(child.pid))
    except OSError:  # pragma: no cover - the child is already gone
        pgid = int(child.pid)
    return RunningCommand(
        process=child,
        kind=KIND_POSIX,
        pgid=pgid,
        terminal=terminal,
        reader=reader,
        sink=sink,
    )


def start_pty(
    argv: Sequence[str],
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> RunningCommand:
    """Start ``argv`` on a pseudo terminal, keeping its output in memory.

    The foreground shape: nothing is written to a log, the caller reads
    ``command.sink.bytes()`` once it has released the command.
    """
    terminal = pty_session.spawn(argv, cwd=cwd, env=env)
    return _running_from_terminal(terminal, pty_session.BytesSink())


def start_pty_with_log(
    argv: Sequence[str],
    stdout_path: str,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> RunningCommand:
    """Start ``argv`` on a pseudo terminal with output appended to ``stdout_path``.

    A terminal cannot be redirected into a file the way a pipe can, so a reader
    thread pumps the master into the log. This is the one place a command output is
    read on a thread, and only for terminal sessions (ADR 0009 revises ADR 0008 D3
    for exactly this case).
    """
    log_path = Path(stdout_path)
    # Created before the command starts, exactly like the pipe path: the path is
    # handed to the model, so it must exist even before anything is printed.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    terminal = pty_session.spawn(argv, cwd=cwd, env=env)
    return _running_from_terminal(terminal, pty_session.FileSink(log_path))


def interrupt(
    command: RunningCommand, grace_seconds: float = INTERRUPT_GRACE_SECONDS
) -> None:
    """Ctrl-C a command and escalate when it ignores the hint.

    A program is allowed to catch ``SIGINT`` and take a moment to clean up; it is
    not allowed to stay alive after the model asked it to stop.
    """
    command.interrupt()
    if not command.wait(grace_seconds):
        command.kill()


def describe_group(command: RunningCommand) -> Dict[str, Any]:
    """Report the containment in force, for the result details."""
    details: Dict[str, Any] = {"kind": command.kind, "pid": command.pid}
    if command.pgid:
        details["pgid"] = command.pgid
    if command.limits:
        details.update(command.limits)
    return details
