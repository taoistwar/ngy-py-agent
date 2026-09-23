"""Rendering a ``write_stdin`` answer, and persisting what does not fit.

The header is the reference contract (ADR 0008): a reader tells a running command
from a finished one by ``session_id`` versus ``exit_code``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.tools import process_store
from agent.tools.output_store import describe_size, ensure_dir, new_stem, persist_text, preview
from agent.tools.token_budget import check_text
from agent.tools.write_stdin.rules import CTRL_C


def fit_output(
    text: str,
    budget: int,
    directory: Optional[Path],
) -> Tuple[str, int, bool, Optional[str]]:
    """Return ``(rendered, original_tokens, truncated, persisted_path)``.

    Over budget the whole chunk is written to disk and its path is returned: a
    truncated read with no way back is a dead end, and ``exec_command`` already
    promises the path for the same reason (ADR 0005 D4/D8).
    """
    report = check_text(text, budget)
    if report.ok:
        return text, report.tokens, False, None

    persisted: Optional[str] = None
    if directory is not None:
        path = persist_text(ensure_dir(directory), f"{new_stem()}-stdin.txt", text)
        persisted = path.as_posix()

    size = describe_size(text)
    where = (
        f"the full text is at {persisted}. Read it in slices with read_file (offset/limit)."
        if persisted
        else "it could not be persisted, so only this preview survives."
    )
    rendered = (
        f"The output was too large to return and was truncated (original token count: "
        f"{report.tokens}, {size['bytes']} bytes); {where}\n"
        f"--- preview ---\n{preview(text)}"
    )
    return rendered, report.tokens, True, persisted


def render(
    session: process_store.Session,
    rendered: str,
    tokens: int,
    truncated: bool,
    persisted: Optional[str],
    running: bool,
    exit_code: Any,
    wall_seconds: float,
    chars_sent: str,
    wait_ms: int,
) -> Tuple[str, Dict[str, Any]]:
    """The model-facing text plus the structured record for the UI."""
    status = (
        f"Process running with session ID {session.process_id}"
        if running
        else f"Process exited with code {exit_code}"
    )
    model_text = "\n".join(
        [
            f"Chunk ID: {uuid.uuid4().hex[:6]}",
            f"Wall time: {wall_seconds:.4f} seconds",
            status,
            f"Original token count: {tokens}",
            "Output:",
            rendered,
        ]
    )
    details: Dict[str, Any] = {
        "success": True,
        # A finished session can no longer be typed into, so do not advertise it.
        "session_id": session.process_id if running else None,
        "running": running,
        "exit_code": exit_code,
        "chars_sent": chars_sent,
        "interrupted": chars_sent == CTRL_C,
        "wall_time_seconds": round(wall_seconds, 4),
        "yield_time_ms": wait_ms,
        "original_token_count": tokens,
        "output": rendered,
        "output_truncated": truncated,
        "persistedOutputPath": persisted,
        "output_bytes": len(rendered.encode("utf-8", errors="replace")),
    }
    return model_text, details
