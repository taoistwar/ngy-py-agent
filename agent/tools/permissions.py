"""Interactive permission confirmation for tool calls (see ADR 0006).

The gate is deliberately **not** part of any tool. ``EventSink`` is only reachable
from ``agent_loop`` (the glossary pins that down: "tools cannot reach it"), so the
question is asked by :class:`PermissionBroker`, which ``agent_loop`` hands to
``ToolRegistry``. ``ToolRegistry.execute_tool`` consults it for every call, which
is what makes the coverage complete instead of "whichever tools I remembered".

Three points worth stating up front, because getting them wrong makes the gate
either useless or infuriating:

* It is a **cooperative confirmation, not a security boundary**. Once a call is
  allowed, nothing new restricts it: ``exec_command`` is still an unrestricted shell.
* **Do not ask about what the static policy already refuses.** ``file_access``
  denials are hard denials; prompting first would imply the answer could be yes,
  and the tool would reject the call anyway. The policy runs first, silently.
* **Failing closed is the whole point.** Nobody answering means "no", not "yes".
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple
from uuid import uuid4

from agent.tools import file_access
from agent.tools.permission_rules import PermissionRuleStore

# Permission kinds declared by tool specs (see ``agent/tools/specs.py``).
PERMISSION_NONE = "none"
PERMISSION_READ = "read"
PERMISSION_WRITE = "write"
PERMISSION_EXEC = "exec"

PERMISSION_KINDS = (
    PERMISSION_NONE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    PERMISSION_EXEC,
)

# Decision reasons. Kept as plain strings so they can travel in event payloads
# without a translation step, and so the UI can branch on them.
REASON_NOT_REQUIRED = "not_required"
REASON_AUTO_APPROVED = "auto_approved"
REASON_DENY_ALL = "deny_all"
REASON_POLICY_DENIED = "policy_denied"
REASON_SESSION_RULE = "session_rule"
REASON_PERSISTENT_RULE = "persistent_rule"
REASON_USER_ALLOWED = "user_allowed"
REASON_USER_DENIED = "user_denied"
REASON_TIMEOUT = "timeout"
REASON_STOPPED = "stopped"

SCOPE_ONCE = "once"
SCOPE_SESSION = "session"
# Remembered in ``data/permission_rules.json``; survives the task and restarts.
SCOPE_ALWAYS = "always"
SCOPES = (SCOPE_ONCE, SCOPE_SESSION, SCOPE_ALWAYS)

TIMEOUT_ENV = "PERMISSION_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 120.0
# While waiting, poll instead of blocking outright so a stop request is honoured
# immediately rather than after the timeout (ADR 0006 D6).
_POLL_SECONDS = 0.25

# Arguments are attached to the request so the dialog can show what is about to
# happen. Truncated because a write payload can be megabytes (ADR 0006 D11).
MAX_PREVIEW_CHARS = 8192

# Reads are only questioned when the file itself is the risk. Everything else in
# the list is "the answer is probably a secret".
_SENSITIVE_NAMES = (
    r"\.env(\..+)?",
    r"\.netrc",
    r"\.npmrc",
    r"\.pypirc",
    r"\.git-credentials",
    r"secrets?(\..+)?",
    r"credentials?(\..+)?",
    r"id_rsa.*",
    r"id_dsa.*",
    r"id_ecdsa.*",
    r"id_ed25519.*",
    r".*\.pem",
    r".*\.key",
    r".*\.pfx",
    r".*\.p12",
    r".*\.keystore",
    r".*\.jks",
    r".*\.kdbx",
)
_SENSITIVE_NAME_PATTERNS = tuple(re.compile(rf"(?i)^{item}$") for item in _SENSITIVE_NAMES)
# Directories where a file name alone does not settle it: anything inside is a
# credential store regardless of how it is named.
_SENSITIVE_DIRS = (".ssh", ".aws", ".gnupg", ".docker")


class PermissionMode(str, Enum):
    """How the broker answers, before anyone is asked."""

    ASK = "ask"
    AUTO_APPROVE = "auto_approve"
    DENY_ALL = "deny_all"


def normalize_mode(value: Any) -> PermissionMode:
    """Coerce a config value into a mode, defaulting to ``ask``."""
    if isinstance(value, PermissionMode):
        return value
    text = str(value or "").strip().lower().replace("-", "_")
    for mode in PermissionMode:
        if text == mode.value:
            return mode
    return PermissionMode.ASK


def timeout_seconds() -> float:
    """Wait limit for a confirmation, overridable by ``PERMISSION_TIMEOUT_SECONDS``."""
    raw = (os.getenv(TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def is_sensitive_path(path: Path) -> bool:
    """Whether ``path`` looks like a credential store or key material."""
    parts = [part for part in path.parts if part not in (path.anchor, "/", "\\")]
    for part in parts[:-1]:
        if part.lower() in _SENSITIVE_DIRS:
            return True
    name = path.name
    return any(pattern.match(name) for pattern in _SENSITIVE_NAME_PATTERNS)


@dataclass(frozen=True)
class PermissionRequest:
    """One pending question, as handed to the UI."""

    request_id: str
    task_id: str
    tool: str
    kind: str
    summary: str
    target: str
    details: Dict[str, Any] = field(default_factory=dict)
    # Which answers this tool accepts. A tool that cannot take a standing approval
    # (``write_stdin``: its target is a random session id) narrows this, and the
    # dialog only offers what is listed here (ADR 0008).
    scopes: Tuple[str, ...] = SCOPES
    created_at: float = field(default_factory=time.time)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def to_payload(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "tool": self.tool,
            "kind": self.kind,
            "summary": self.summary,
            "target": self.target,
            "details": self.details,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class PermissionDenial:
    """A call the broker refused to let through.

    Returned instead of raised: a user saying "no" is a **result**, not a failure
    (ADR 0006 D4). Raising here would make the caller mark the step as failed and
    would teach the model that the tool is broken, so it would retry.
    """

    model_text: str
    details: Dict[str, Any]


class PermissionBroker:
    """Answers "may this call run?" for one task.

    Scope is one run, matching ``ToolRegistry`` and the read ledger. Session rules
    therefore die with the task, which is what "本任务内允许" means.
    """

    def __init__(
        self,
        *,
        task_id: str = "",
        emit: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        mode: Any = PermissionMode.ASK,
        base_dir: Optional[str] = None,
        extra_read_roots: Sequence[Any] = (),
        should_stop: Optional[Callable[[], bool]] = None,
        wait_seconds: Optional[float] = None,
        access_config: Optional[file_access.FileAccessConfig] = None,
        rules: Optional[PermissionRuleStore] = None,
    ) -> None:
        self.task_id = task_id
        self.mode = normalize_mode(mode)
        self.base_dir = base_dir
        self.extra_read_roots = tuple(extra_read_roots or ())
        self.should_stop = should_stop
        self.wait_seconds = wait_seconds if wait_seconds is not None else timeout_seconds()
        self._emit = emit
        self._lock = threading.Lock()
        self._waiters: Dict[str, "_Waiter"] = {}
        self._session_rules: set = set()
        # Mirrors the policy the file tools use, so "the policy already refuses
        # this" can be detected before asking (ADR 0006 D9). Injectable so tests
        # do not depend on the developer's ``data/file_access.json``.
        self._config = (
            access_config if access_config is not None else file_access.load_access_config()
        )
        # "Always allow" rules, re-read per lookup so the management API takes
        # effect immediately (see agent/tools/permission_rules.py).
        self._rules = rules if rules is not None else PermissionRuleStore()

    # ------------------------------------------------------------------ public

    def check(
        self,
        tool: str,
        kind: str,
        arguments: Dict[str, Any],
        preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        scopes: Optional[Sequence[str]] = None,
    ) -> Optional[PermissionDenial]:
        """Return a denial when the call must not run, else ``None``.

        ``None`` means "proceed" and covers two different situations that both end
        the same way: no confirmation was needed, or the confirmation was granted.
        """
        kind = kind or PERMISSION_NONE
        if kind == PERMISSION_NONE:
            return None

        target = self._target(tool, kind, arguments)
        if target is None:
            # The static policy already refuses this path, or the arguments are
            # malformed. Either way the tool produces the canonical error and the
            # user is not asked about something that cannot be approved.
            return None

        if self.mode is PermissionMode.AUTO_APPROVE:
            self._decision_event(tool, target, allowed=True, reason=REASON_AUTO_APPROVED)
            return None

        if self.mode is PermissionMode.DENY_ALL:
            self._decision_event(tool, target, allowed=False, reason=REASON_DENY_ALL)
            return self._denial(tool, kind, target, REASON_DENY_ALL)

        if kind == PERMISSION_READ and not self._read_needs_confirmation(target):
            return None

        rule = (tool, target)
        if rule in self._session_rules:
            self._decision_event(
                tool, target, allowed=True, reason=REASON_SESSION_RULE, scope=SCOPE_SESSION
            )
            return None

        if self._rules.match(tool, target):
            self._decision_event(
                tool, target, allowed=True, reason=REASON_PERSISTENT_RULE, scope=SCOPE_ALWAYS
            )
            return None

        return self._ask(tool, kind, target, arguments, preview, tuple(scopes or SCOPES))

    def resolve(self, request_id: str, allowed: bool, scope: str = SCOPE_ONCE) -> bool:
        """Answer a pending request. Returns whether it was still pending.

        Called from the API layer, i.e. from a *different* thread than the one
        blocked in :meth:`check` - hence the lock and the ``threading.Event``.
        """
        with self._lock:
            waiter = self._waiters.get(request_id)
        if waiter is None:
            return False
        # ``resolved`` first: a teardown racing with this call checks it, and must
        # not be able to turn an answer that already arrived into a refusal.
        waiter.resolved = True
        waiter.allowed = bool(allowed)
        # A scope this tool does not accept falls back to ``once``: that is the
        # conservative direction, and the user-facing path never reaches here
        # because the API rejects it outright instead of pretending.
        waiter.scope = scope if scope in waiter.request.scopes else SCOPE_ONCE
        waiter.event.set()
        return True

    def request_scopes(self, request_id: str) -> Optional[Tuple[str, ...]]:
        """Scopes a pending request accepts, or ``None`` when it is not pending."""
        with self._lock:
            waiter = self._waiters.get(request_id)
        return waiter.request.scopes if waiter is not None else None

    def pending(self) -> Optional[PermissionRequest]:
        """The request currently being waited on, if any."""
        with self._lock:
            for waiter in self._waiters.values():
                if not waiter.event.is_set():
                    return waiter.request
        return None

    def cancel_all(self, reason: str = REASON_STOPPED) -> None:
        """Release every waiter so no thread is stuck until the timeout.

        Leaves ``resolved`` untouched on purpose: a released waiter was *not*
        answered, and must not be reported as "the user denied it".
        """
        with self._lock:
            waiters = list(self._waiters.values())
        for waiter in waiters:
            if waiter.resolved:
                # Already answered; teardown must not overwrite that.
                continue
            waiter.allowed = False
            waiter.reason = reason
            waiter.event.set()

    # ----------------------------------------------------------------- private

    def _ask(
        self,
        tool: str,
        kind: str,
        target: str,
        arguments: Dict[str, Any],
        preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        scopes: Tuple[str, ...] = SCOPES,
    ) -> Optional[PermissionDenial]:
        request = self._build_request(tool, kind, target, arguments, preview, scopes)
        waiter = _Waiter(event=threading.Event(), request=request)
        with self._lock:
            self._waiters[request.request_id] = waiter
        self._emit_event(
            "permission_request",
            f"Permission required: {tool}",
            request.to_payload(),
        )

        deadline = time.monotonic() + self.wait_seconds
        answered = False
        while True:
            if waiter.event.wait(_POLL_SECONDS):
                answered = True
                break
            # Stop beats the timeout: the user asked for the task to end.
            if self.should_stop is not None and self.should_stop():
                waiter.allowed = False
                waiter.reason = REASON_STOPPED
                break
            if time.monotonic() >= deadline:
                waiter.allowed = False
                waiter.reason = REASON_TIMEOUT
                break

        with self._lock:
            self._waiters.pop(request.request_id, None)

        if not answered and waiter.reason is None:
            waiter.reason = REASON_TIMEOUT

        if waiter.resolved:
            # Someone actually answered the dialog.
            reason = REASON_USER_ALLOWED if waiter.allowed else REASON_USER_DENIED
            scope = waiter.scope if waiter.allowed else SCOPE_ONCE
        else:
            # Timed out, stopped, or released by teardown - all of them are
            # refusals, but they must not be mislabelled as a user decision.
            reason = waiter.reason or REASON_TIMEOUT
            scope = SCOPE_ONCE

        if waiter.resolved and waiter.allowed:
            if scope == SCOPE_SESSION:
                self._session_rules.add((tool, target))
            elif scope == SCOPE_ALWAYS and not self._rules.add(tool, target, kind):
                # The rule could not be written, so do not report a standing
                # approval that does not exist. This call still runs.
                scope = SCOPE_ONCE

        # Emitted after the persist step so ``scope`` is the effective one.
        self._decision_event(tool, target, allowed=waiter.allowed, reason=reason, scope=scope)

        if waiter.resolved and waiter.allowed:
            return None
        return self._denial(tool, kind, target, reason)

    def _build_request(
        self,
        tool: str,
        kind: str,
        target: str,
        arguments: Dict[str, Any],
        preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        scopes: Tuple[str, ...] = SCOPES,
    ) -> PermissionRequest:
        details: Dict[str, Any] = {"kind": kind}
        summary = f"Run {tool}"

        if kind == PERMISSION_EXEC and tool == "exec_command":
            command = str(arguments.get("command") or "")
            summary = str(arguments.get("description") or "").strip() or f"Run command: {command}"
            details["command"] = command
            details["description"] = str(arguments.get("description") or "")
        elif kind == PERMISSION_EXEC and tool == "write_stdin":
            session = str(arguments.get("session_id") or "")
            chars = str(arguments.get("chars") or "")
            summary = f"Write to session {session}" if chars else f"Poll session {session}"
            details["session_id"] = session
            details["chars"] = _truncate(chars)
        elif kind == PERMISSION_EXEC:
            code = str(arguments.get("code") or "")
            summary = "Run Python code"
            details["code"] = _truncate(code)
        elif kind == PERMISSION_WRITE and "content" in arguments:
            content = str(arguments.get("content") or "")
            details["content"] = _truncate(content)
            details["content_bytes"] = len(content.encode("utf-8", errors="replace"))
            summary = f"Write {target}"
        elif kind == PERMISSION_WRITE:
            old = str(arguments.get("old_string") or "")
            new = str(arguments.get("new_string") or "")
            details["old_string"] = _truncate(old)
            details["new_string"] = _truncate(new)
            summary = f"Edit {target}"
        elif kind == PERMISSION_READ:
            details["reason"] = "sensitive_path"
            summary = f"Read {target}"

        if preview is not None:
            # Enriches the dialog (e.g. edit_file's diff). A preview is a
            # convenience, never a gate: if it fails, the tool reports the real
            # error once it is allowed to run, so this only costs a missing block.
            try:
                extra = preview(dict(arguments))
            except Exception:  # noqa: BLE001 - a broken preview must not block the dialog
                extra = None
            if isinstance(extra, dict):
                details.update(extra)

        return PermissionRequest(
            request_id=uuid4().hex,
            task_id=self.task_id,
            tool=tool,
            kind=kind,
            summary=summary,
            target=target,
            details=details,
            scopes=tuple(scopes),
            timeout_seconds=self.wait_seconds,
        )

    def _target(self, tool: str, kind: str, arguments: Dict[str, Any]) -> Optional[str]:
        """The thing being acted on, or ``None`` when it must not be asked about."""
        if kind in (PERMISSION_READ, PERMISSION_WRITE):
            raw = arguments.get("file_path")
            if not isinstance(raw, str) or not raw.strip():
                return None
            resolver = (
                file_access.resolve_read_path
                if kind == PERMISSION_READ
                else file_access.resolve_write_path
            )
            try:
                path, _root = resolver(
                    raw,
                    base_dir=self.base_dir,
                    config=self._config,
                    extra_read_roots=self.extra_read_roots,
                )
            except file_access.AccessDenied:
                # Hard denial: never ask, the tool reports it (ADR 0006 D9).
                return None
            except OSError:
                return None
            return _display(path)

        if tool == "exec_command":
            command = arguments.get("command")
            if not isinstance(command, str) or not command.strip():
                return None
            return command

        if tool == "write_stdin":
            session = arguments.get("session_id")
            if not isinstance(session, str) or not session.strip():
                return None
            # Key on the session so one approval covers this terminal, not every
            # future write_stdin call.
            return f"session:{session.strip()}"

        if tool == "code_interpreter":
            code = arguments.get("code")
            if not isinstance(code, str) or not code.strip():
                return None
            # Session rules are keyed on the target, so use the whole code body:
            # "allow this code for the task" must not leak to different code.
            return code

        # An unknown tool declared as read/write/exec: fall back to a stable key so
        # the dialog still has something to show.
        return tool

    def _read_needs_confirmation(self, target: str) -> bool:
        """Whether reading ``target`` is worth interrupting the user for."""
        path = Path(target)
        if is_sensitive_path(path):
            return True
        return self._outside_workspace(path)

    def _outside_workspace(self, path: Path) -> bool:
        text = (self.base_dir or "").strip()
        if not text:
            # Unbound session: "outside the workspace" has no meaning, and the
            # glossary pins down that such sessions may read outside anyway.
            return False
        try:
            root = Path(text).resolve()
        except OSError:  # pragma: no cover - platform specific
            return False
        if any(file_access.is_within(path, extra) for extra in self._extra_roots()):
            # Scratch output from ``exec_command`` is deliberately readable (ADR 0005 D4).
            return False
        return not file_access.is_within(path, root)

    def _extra_roots(self) -> tuple:
        roots = []
        for item in self.extra_read_roots:
            text = str(item or "").strip()
            if text:
                try:
                    roots.append(Path(text).expanduser().resolve())
                except OSError:  # pragma: no cover - platform specific
                    continue
        return tuple(roots)

    def _denial(self, tool: str, kind: str, target: str, reason: str) -> PermissionDenial:
        instruction = {
            REASON_TIMEOUT: (
                "Nobody answered within the time limit, so the call was refused. "
                "Do not retry it."
            ),
            REASON_STOPPED: "The task was stopped while waiting for confirmation.",
            REASON_USER_DENIED: (
                "The user refused this call. Do not retry the same call; ask the user "
                "what to do instead, or continue with what you can do without it."
            ),
            REASON_DENY_ALL: (
                "Permissions are configured to refuse every confirmable tool call."
            ),
        }.get(reason, "The call was not approved.")

        model_text = (
            f"Permission denied for {tool} ({target!r}).\n"
            f"reason: {reason}\n"
            f"{instruction}"
        )
        return PermissionDenial(
            model_text=model_text,
            details={
                "reason": reason,
                "tool": tool,
                "kind": kind,
                "target": target,
                "allowed": False,
            },
        )

    def _decision_event(
        self,
        tool: str,
        target: str,
        *,
        allowed: bool,
        reason: str,
        scope: str = SCOPE_ONCE,
    ) -> None:
        self._emit_event(
            "permission_decision",
            f"Permission {'granted' if allowed else 'denied'}: {tool}",
            {
                "tool": tool,
                "target": target,
                "allowed": allowed,
                "reason": reason,
                "scope": scope,
            },
        )

    def _emit_event(self, category: str, title: str, data: Dict[str, Any]) -> None:
        """Hand one audit event to the caller-supplied emitter.

        ``category`` is the event category value (``permission_request`` /
        ``permission_decision``); ``emit`` is responsible for turning it into the
        real ``TaskEvent``, which keeps this module free of the task-store types.
        """
        if self._emit is None:
            return
        try:
            self._emit(category, title, data)
        except Exception:  # noqa: BLE001 - never break the call path (see below)
            # Event emission must never break the call path (same rule as _emit
            # in agent_loop).
            return


@dataclass
class _Waiter:
    """A pending question plus the thread waiting for its answer."""

    event: threading.Event
    request: PermissionRequest
    allowed: bool = False
    scope: str = SCOPE_ONCE
    reason: Optional[str] = None
    # True only when :meth:`PermissionBroker.resolve` answered it; a released
    # waiter stays ``False`` so it is not reported as a user decision.
    resolved: bool = False


def _display(resolved: Path) -> str:
    """Absolute path for the dialog; the model may have written a relative one."""
    return resolved.as_posix()


def _truncate(text: str, limit: int = MAX_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} characters total]"
