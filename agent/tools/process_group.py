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
from typing import Any, Dict, List, Optional, Sequence

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

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

if WINDOWS:  # pragma: no cover - platform specific
    import ctypes
    import ctypes.wintypes as wt

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
    """A started command plus the handle needed to stop its whole tree."""

    process: subprocess.Popen
    kind: str
    pgid: Optional[int] = None
    job: Optional[int] = None
    limits: Dict[str, Any] = field(default_factory=dict)

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    def poll(self) -> Optional[int]:
        return self.process.poll()

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
        try:
            self.process.kill()
        except OSError:
            pass

    def release(self) -> None:
        """Close the OS handle without stopping anything.

        A Windows job is created with ``KILL_ON_JOB_CLOSE``, so releasing it kills
        the survivors: background commands deliberately keep their handle instead.
        """
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


def _spawn(
    argv: Sequence[str],
    cwd: Optional[str],
    env: Optional[Dict[str, str]],
    stdout: Any,
    stderr: Any,
) -> RunningCommand:
    if WINDOWS:  # pragma: no cover - platform specific
        job, limits = _create_job()
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
        )
        if job:
            if _assign_to_job(job, process.pid):
                return RunningCommand(process=process, kind=KIND_WINDOWS_JOB, job=job, limits=limits)
            _KERNEL32.CloseHandle(_handle(job))
        return RunningCommand(process=process, kind=KIND_PLAIN)

    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
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
) -> RunningCommand:
    """Start ``argv`` with output appended straight to ``stdout_path``.

    Used for background commands: nothing is piped back, so the process cannot
    stall on a full pipe buffer once the caller stops reading.
    """
    handle = open(stdout_path, "ab", buffering=0)
    try:
        return _spawn(argv, cwd, env, handle, subprocess.STDOUT)
    finally:
        handle.close()


def describe_group(command: RunningCommand) -> Dict[str, Any]:
    """Report the containment in force, for the result details."""
    details: Dict[str, Any] = {"kind": command.kind, "pid": command.pid}
    if command.pgid:
        details["pgid"] = command.pgid
    if command.limits:
        details.update(command.limits)
    return details
