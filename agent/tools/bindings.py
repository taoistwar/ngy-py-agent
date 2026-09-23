"""What a run binds its tools to.

Tools differ in what they need at construction time: a lookup needs nothing, the
file tools need a workspace root and a read ledger, ``exec_command`` needs a task
and an output directory, ``write_stdin`` needs the task *and* the workspace so it
can refuse a session that belongs to someone else.

Rather than give every ``build_spec`` a different signature, the run collects these
once into a :class:`ToolBindings` and hands the same object to each tool. Every
field has a default, so ``ToolBindings()`` is a valid "nothing bound" run (which is
what tests and the CLI use).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from agent.tools.read_ledger import ReadLedger


@dataclass(frozen=True)
class ToolBindings:
    """The run-scoped things a tool may be bound to."""

    # Workspace root for path resolution (``None`` = unbound session, ADR 0007).
    base_dir: Optional[str] = None
    # Output-directory scope for this run: names the scratch directory.
    session_id: str = ""
    # The task that owns this run; background sessions are stamped with it so the
    # task can stop them when it ends (ADR 0008).
    task_id: str = ""
    # Output token budget for one tool result.
    max_tokens: int = 0
    # Tokenizer hints for the budget check.
    provider: str = ""
    model: str = ""
    # Where large output is persisted (readable by read_file, never writable).
    output_directory: Optional[Path] = None
    # Shared by read/edit/write so write_file can tell whether this run already
    # held the whole content it is about to replace.
    ledger: Optional[ReadLedger] = None
    # Extra roots the file tools may read from (the output directory).
    extra_read_roots: Sequence[str] = ()
