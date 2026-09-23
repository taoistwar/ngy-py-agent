"""Rendering a finished command for the model, and persisting what does not fit.

Command output is unbounded by nature (unlike a source file), so what cannot be
returned is written to disk and reported as a path the model can read back
(ADR 0005 D4/D8).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from agent.tools.output_store import persist_text, preview


def foreground_text(
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
    interrupted: bool,
    timeout_ms: int,
) -> str:
    """The readable rendering of a finished command."""
    lines: List[str] = [f"exit_code: {exit_code if exit_code is not None else 'unknown'}"]
    if interrupted:
        lines.append(
            f"The command was stopped after {timeout_ms} ms and its process tree was terminated."
        )
    if stdout:
        lines.extend(["--- stdout ---", stdout.rstrip("\n")])
    if stderr:
        lines.extend(["--- stderr ---", stderr.rstrip("\n")])
    if not stdout and not stderr and not interrupted:
        lines.append("(no output)")
    return "\n".join(lines)


def persist_and_preview(directory: Path, stem: str, text: str) -> Tuple[str, str]:
    """Write the full text to disk and return ``(preview, path)``."""
    path = persist_text(directory, f"{stem}.txt", text)
    return preview(text), path.as_posix()
