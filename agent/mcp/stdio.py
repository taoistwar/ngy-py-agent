"""One MCP server process, spoken to over the stdio transport.

A probe is a single short conversation - spawn the command, ``initialize``,
``tools/list``, shut it down - so the session is built for exactly that and closed
even when it fails. Nothing here is per-run state; connecting a whole task to a
server is a separate job.
"""

from __future__ import annotations

import io
import locale
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from typing import Any

from agent.mcp.jsonrpc import (
    METHOD_NOT_FOUND,
    decode_message,
    encode_error,
    encode_notification,
    encode_request,
)

# End of the stderr tail kept for diagnostics: an npx shim that cannot find its
# package says so on stderr, and that text is the whole answer to "why did it fail".
_STDERR_LINES = 40
# How long a dying process gets before it is killed outright.
_TERMINATE_GRACE_SECONDS = 1.0
# How long the stderr reader gets once the process has exited, so the error message
# can quote what it said before the pipes closed.
_STDERR_DRAIN_SECONDS = 0.5


class McpSessionError(Exception):
    """The server could not be started, or stopped answering."""


def _platform_options() -> dict[str, Any]:
    """Keep a spawned server out of the user's face and killable as a group."""
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        return {"creationflags": flags}
    return {"start_new_session": True}


def _diagnostic_encoding() -> str:
    """Encoding of a server's own diagnostics (``stderr``).

    On Windows a shim such as ``npx.cmd`` is run by ``cmd.exe``, which writes its
    messages in the console code page; everywhere else a server writes UTF-8. Decoding
    both pipes the same way would garble exactly the "command not found" text that
    explains a failed probe on a Chinese Windows install.
    """
    if os.name == "nt":
        return locale.getencoding()
    return "utf-8"


def _first_word(command: str) -> str:
    """The program the command line names, with quotes removed."""
    text = command.lstrip()
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 0 else text[1:]
    return text.split(maxsplit=1)[0]


def _child_env(command: str) -> dict[str, str] | None:
    """Environment for the server, with the command's own folder first on ``PATH``.

    A command given by full path - ``C:\\...\\npx.cmd -y pkg`` - runs a shim that calls
    ``node`` by name. Unless that folder is on ``PATH`` the shim fails with "not
    recognized", which reads like a broken preset instead of a ``PATH`` that differs
    from the user's shell. ``None`` means "inherit the environment unchanged".
    """
    directory = os.path.dirname(_first_word(command))
    if not directory:
        return None
    env = dict(os.environ)
    env["PATH"] = directory + os.pathsep + env.get("PATH", "")
    return env


def _command_argv(command: str) -> tuple[Any, bool]:
    """Turn the configured command line into something ``Popen`` accepts.

    On Windows ``npx`` and friends are ``.cmd`` shims that ``CreateProcess`` will not
    resolve, so the line has to go through ``cmd.exe``; elsewhere it is split and run
    directly, which keeps the server a child this process can signal.
    """
    if os.name == "nt":
        return command, True
    return shlex.split(command), False


def _describe_error(error: dict[str, Any]) -> str:
    code = error.get("code")
    message = str(error.get("message") or "no message").strip()
    return f"{message} (code {code})" if code is not None else message


class StdioSession:
    """A spawned MCP server, addressed by newline-delimited JSON-RPC messages."""

    def __init__(self, command: str) -> None:
        self.command = command
        self._process: subprocess.Popen[bytes] | None = None
        # ``None`` in the queue means "stdout reached EOF": the process is gone.
        self._inbox: queue.Queue[str | None] = queue.Queue()
        self._stderr_tail: list[str] = []
        self._stdin: io.TextIOWrapper | None = None
        self._stdout: io.TextIOWrapper | None = None
        self._stderr: io.TextIOWrapper | None = None
        self._stdout_reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._next_id = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Spawn the configured command and start draining both output pipes."""
        command = self.command.strip()
        if not command:
            raise McpSessionError("The MCP target is empty, so there is no command to run.")
        argv, shell = _command_argv(command)
        try:
            self._process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                env=_child_env(command),
                **_platform_options(),
            )
        except (OSError, ValueError) as exc:
            raise McpSessionError(f"The MCP command could not be started: {exc}") from exc
        self._wrap_pipes(self._process)
        self._stdout_reader = threading.Thread(target=self._read_stdout, name="mcp-stdout", daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, name="mcp-stderr", daemon=True)
        self._stdout_reader.start()
        self._stderr_reader.start()

    def _wrap_pipes(self, process: subprocess.Popen[bytes]) -> None:
        """Decode the pipes separately: protocol messages are UTF-8, diagnostics are not.

        ``Popen(text=True)`` would apply one encoding to all three pipes, which cannot
        be right for a Windows shim: the MCP messages are UTF-8 by specification while
        ``cmd.exe`` reports its own errors in the console code page.
        """
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise McpSessionError("The MCP server's pipes could not be opened.")
        # LF in, whatever the server sends out: ``decode_message`` strips the line.
        self._stdin = io.TextIOWrapper(process.stdin, encoding="utf-8", newline="\n", write_through=True)
        self._stdout = io.TextIOWrapper(process.stdout, encoding="utf-8", errors="replace")
        self._stderr = io.TextIOWrapper(
            process.stderr, encoding=_diagnostic_encoding(), errors="replace"
        )

    def close(self) -> None:
        """Shut the server down, child processes included. Safe to call twice."""
        process = self._process
        self._process = None
        if process is None:
            return
        _close_stream(self._stdin)
        self._stdin = None
        # The pipes are only closed once the readers have seen the process end;
        # closing a stream another thread is reading would raise inside that thread.
        _terminate_tree(process)
        for reader in (self._stdout_reader, self._stderr_reader):
            if reader is not None:
                reader.join(timeout=_STDERR_DRAIN_SECONDS)
        _close_stream(self._stdout)
        _close_stream(self._stderr)
        self._stdout = None
        self._stderr = None

    # -- messages ----------------------------------------------------------

    def request(self, method: str, params: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        """Send one request and return its ``result``.

        Raises ``McpSessionError`` when the server refuses, stays silent, or exits,
        and ``McpProtocolError`` when it answers with something that is not JSON-RPC.
        """
        self._next_id += 1
        request_id = self._next_id
        self._send(encode_request(request_id, method, params))
        deadline = time.monotonic() + timeout
        while True:
            message = self._next_message(deadline, method)
            if message.get("id") != request_id:
                self._answer_unsolicited(message)
                continue
            error = message.get("error")
            if isinstance(error, dict):
                raise McpSessionError(f"The MCP server rejected '{method}': {_describe_error(error)}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a notification (no answer expected)."""
        self._send(encode_notification(method, params))

    # -- internals ---------------------------------------------------------

    def _send(self, payload: str) -> None:
        stream = self._stdin
        if stream is None:
            raise McpSessionError("The MCP server is not running.")
        try:
            stream.write(f"{payload}\n")
            stream.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise McpSessionError(
                f"The MCP server stopped accepting input: {exc}{self._stderr_text()}"
            ) from exc

    def _next_message(self, deadline: float, method: str) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise McpSessionError(
                f"The MCP server did not answer '{method}' in time.{self._stderr_text()}"
            )
        try:
            line = self._inbox.get(timeout=remaining)
        except queue.Empty as exc:
            raise McpSessionError(
                f"The MCP server did not answer '{method}' in time.{self._stderr_text()}"
            ) from exc
        if line is None:
            # Let the process be reaped first, so the stderr tail quoted below is the
            # whole story rather than whatever had been read at that instant.
            self._wait_for_exit()
            raise McpSessionError(
                f"The MCP server exited before answering '{method}'.{self._stderr_text()}"
            )
        return decode_message(line)

    def _answer_unsolicited(self, message: dict[str, Any]) -> None:
        """Refuse a server-initiated request; drop anything else.

        A server may ask this client to sample from a model or to list roots. A probe
        has nothing useful to say to those, but leaving the request unanswered makes a
        well-behaved server wait, so it is explicitly refused.
        """
        method = message.get("method")
        request_id = message.get("id")
        if method is None or request_id is None:
            return  # a notification, or a late reply to something that timed out
        self._send(
            encode_error(request_id, METHOD_NOT_FOUND, f"'{method}' is not supported by this client.")
        )

    def _read_stdout(self) -> None:
        stream = self._stdout
        if stream is None:
            self._inbox.put(None)
            return
        try:
            for line in stream:
                self._inbox.put(line)
        except (OSError, ValueError):
            # The pipe went away under us; the EOF marker below is the signal the
            # caller reads, so this needs no separate report.
            pass
        finally:
            self._inbox.put(None)

    def _read_stderr(self) -> None:
        stream = self._stderr
        if stream is None:
            return
        try:
            for line in stream:
                self._stderr_tail.append(line.rstrip())
                del self._stderr_tail[:-_STDERR_LINES]
        except (OSError, ValueError):
            # A half-read stderr tail costs nothing: diagnostics only.
            return

    def _stderr_text(self) -> str:
        """The tail of what the server printed, formatted for an error message."""
        self._drain_stderr()
        tail = "\n".join(line for line in self._stderr_tail if line.strip())
        return f"\nstderr:\n{tail}" if tail else ""

    def _wait_for_exit(self) -> None:
        """Reap the process if it is on its way out, without waiting long for it."""
        process = self._process
        if process is None:
            return
        try:
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # Still alive with its stdout closed - unusual, and the error that follows
            # already says the conversation failed.
            return

    def _drain_stderr(self) -> None:
        """Wait a moment for the stderr reader once the process has exited."""
        process = self._process
        reader = self._stderr_reader
        if process is None or reader is None or process.poll() is None:
            return
        reader.join(timeout=_STDERR_DRAIN_SECONDS)


def _close_stream(stream: Any) -> None:
    """Close one pipe, tolerating one that is already gone."""
    if stream is None:
        return
    try:
        stream.close()
    except (OSError, ValueError):
        # Already broken by whatever failure brought us here.
        pass


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop the process and everything it started.

    ``npx`` runs the real server as a child of ``cmd.exe``/``node``, so killing only
    the process ``Popen`` handed back would leave the server running; on Windows the
    tree is ended with ``taskkill /T`` and on POSIX the whole session group is
    signalled.
    """
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
                **_platform_options(),
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except OSError:
        # It exited between the check and the kill, which is the outcome we wanted.
        pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            # Nothing left to kill.
            pass
