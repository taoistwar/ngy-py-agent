"""Shared plumbing for the ``cua-driver`` computer-use tools.

Both computer tools talk to the same local desktop driver, so the process
handling, the error vocabulary and the session label live here rather than in
either package (see ``AGENTS.md``: shared infrastructure stays at this level).

Two things about the driver shape the code below:

* Tools are invoked as ``cua-driver <snake_case_tool>`` with a JSON object on
  stdin. The driver answers with JSON on stdout; a non-zero exit code or an
  ``ok: false`` payload is a failure, not a result.
* Every call carries the same ``session`` label for one task. The driver keys
  its element-token cache on that label, so a snapshot taken by
  ``computer_observe`` stays valid for the ``computer_control`` call that acts
  on it. A session that changed per call would make every token stale.

The driver must run inside an interactive desktop session (Session 1 or later);
Session 0 has no usable UIA, screenshot or app activation. That is an
operational precondition, not something this module can work around, so the
error text says it plainly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

# Point at an already installed binary (the installer writes the standard
# location into PATH, so this is only needed for portable installs and tests).
DRIVER_BINARY_ENV = "CUA_DRIVER_BIN"
DRIVER_BINARY_NAME = "cua-driver"
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_SESSION = "ngy-default"

INSTALL_HINT = (
    "Install cua-driver and make sure it is on PATH (Windows: "
    "irm https://cua.ai/driver/install.ps1 | iex). The driver must run in an "
    "interactive desktop session: Session 0 has no usable UI automation."
)

# Driver error codes worth turning into an instruction the model can act on.
# Anything else keeps the driver's own message.
_HINTS: Dict[str, str] = {
    "background_unavailable": (
        "Retry this single action with delivery_mode='foreground'. Do not switch "
        "every action to foreground."
    ),
    "stale_element_token": (
        "The element token belongs to an older snapshot. Call computer_observe with "
        "get_window_state again and act on a token from that result."
    ),
    "window_not_found": (
        "The window handle is stale. Call computer_observe with list_windows for this "
        "pid and use a window_id from that result."
    ),
    "not_interactive": (
        "The driver is not running in an interactive desktop session. Start it from "
        "the logged-in desktop (Windows: schtasks /Run /TN cua-driver-serve)."
    ),
    "session0": (
        "The driver is running in Session 0, which cannot drive the desktop. Start it "
        "from the logged-in desktop session."
    ),
}


class ComputerDriverError(RuntimeError):
    """A driver call that did not produce a usable result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def _default_windows_binary() -> Optional[Path]:
    """The location the Windows installer writes, for a PATH-less process."""
    local = (os.getenv("LOCALAPPDATA") or "").strip()
    if not local:
        return None
    candidate = (
        Path(local) / "Programs" / "trycua" / "cua-driver-rs" / "bin" / "cua-driver.exe"
    )
    return candidate if candidate.is_file() else None


def driver_binary() -> str:
    """Resolve the driver executable, or explain why it cannot be found."""
    override = (os.getenv(DRIVER_BINARY_ENV) or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path)
        raise ComputerDriverError(
            "not_installed",
            f"{DRIVER_BINARY_ENV} points to '{override}', which is not a file.",
            hint=INSTALL_HINT,
        )

    found = shutil.which(DRIVER_BINARY_NAME)
    if found:
        return found

    if os.name == "nt":
        fallback = _default_windows_binary()
        if fallback is not None:
            return str(fallback)

    raise ComputerDriverError(
        "not_installed",
        "cua-driver was not found on PATH.",
        hint=INSTALL_HINT,
    )


def _creation_flags() -> int:
    # A console window per tool call would steal focus from whatever the user is
    # doing, which is exactly what the driver tries to avoid.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _parse_stdout(text: str) -> Any:
    """Parse the driver's answer, tolerating a log line before the payload."""
    body = (text or "").strip()
    if not body:
        return {}
    try:
        return json.loads(body)
    except ValueError:
        pass
    for line in reversed(body.splitlines()):
        candidate = line.strip()
        if not candidate.startswith(("{", "[")):
            continue
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return {"output": body}


def _error_from_stdout(text: str) -> Optional[ComputerDriverError]:
    payload = _parse_stdout(text)
    if isinstance(payload, dict):
        return error_from_payload(payload)
    return None


def describe_error(exc: Exception) -> str:
    """Model-facing text for a failed call, including the driver's own stderr."""
    text = f"Error: {exc}"
    hint = str(getattr(exc, "hint", "") or "")
    if hint:
        text = f"{text}\nHint: {hint}"

    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        stderr = str(details.get("stderr") or "").strip()
        if stderr:
            text = f"{text}\nDriver stderr: {stderr[:500]}"
    return text


def error_from_payload(payload: Any) -> Optional[ComputerDriverError]:
    """Turn an ``ok: false`` driver payload into an exception-shaped error."""
    if not isinstance(payload, dict):
        return None

    error = payload.get("error")
    code = "driver_error"
    message = ""

    if isinstance(error, dict):
        code = str(error.get("code") or code)
        message = str(error.get("message") or error.get("detail") or "").strip()
    elif isinstance(error, str):
        message = error.strip()

    if not message and payload.get("ok") is False:
        message = str(payload.get("message") or "The driver reported failure.")
    if not message and payload.get("success") is False:
        message = str(payload.get("message") or "The driver reported failure.")

    if not message:
        return None

    return ComputerDriverError(
        code,
        message,
        hint=_HINTS.get(code, ""),
        details={"payload": payload},
    )


def call_tool(
    name: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    session: str = "",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Run one driver tool and return its parsed JSON answer."""
    tool = str(name or "").strip()
    if not tool:
        raise ComputerDriverError("invalid_arguments", "A driver tool name is required.")

    request: Dict[str, Any] = {"session": session or DEFAULT_SESSION}
    for key, value in (payload or {}).items():
        if key == "session" or value is None:
            continue
        request[key] = value
    stdin_text = json.dumps(request, ensure_ascii=False)

    try:
        completed = subprocess.run(
            [driver_binary(), tool],
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_creation_flags(),
        )
    except FileNotFoundError as exc:
        raise ComputerDriverError(
            "not_installed", f"cua-driver could not be started: {exc}", hint=INSTALL_HINT
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ComputerDriverError(
            "timeout",
            f"cua-driver {tool} did not finish within {timeout:g} seconds.",
            hint="Check the desktop session and the driver daemon, then retry.",
            details={"tool": tool, "timeout_seconds": timeout},
        ) from exc
    except OSError as exc:
        raise ComputerDriverError(
            "driver_unavailable",
            f"cua-driver {tool} could not be started: {exc}",
            hint=INSTALL_HINT,
        ) from exc

    stdout = completed.stdout or ""
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        error = _error_from_stdout(stdout)
        if error is not None:
            error.details.setdefault("tool", tool)
            error.details.setdefault("exit_code", completed.returncode)
            raise error
        raise ComputerDriverError(
            "driver_failed",
            f"cua-driver {tool} exited with code {completed.returncode}.",
            details={
                "tool": tool,
                "exit_code": completed.returncode,
                "stderr": stderr[:2000],
                "stdout": stdout.strip()[:2000],
            },
        )

    return _parse_stdout(stdout)
