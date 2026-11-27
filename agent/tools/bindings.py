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
from typing import Any, Callable, Optional, Sequence

from agent.tools.read_ledger import ReadLedger
from agent.tools.task_store import TaskBoard
from agent.tools.todo_store import TodoBoard


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
    # Whether this run has been asked to stop (ADR 0019). A callable rather than an
    # event so the tool layer keeps no dependency on the app's state module, and so a
    # run with no cancel channel (the CLI) simply passes ``None``.
    should_stop: Optional[Callable[[], bool]] = None
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
    # The plan the conversation is working through (``todo_write``). A board rather
    # than a store: it already carries the session and task ids, and ``None`` falls
    # back to an in-memory plan for this run (see ``agent/tools/todo_store.py``).
    todo_board: Optional[TodoBoard] = None
    # The project's task board (``task_*``): a bigger unit than the todo list - a
    # work item with prerequisites and an owner, shared by every conversation in the
    # workspace. ``None`` keeps the board in memory for this run.
    task_board: Optional[TaskBoard] = None
    # The channel a tool uses to ask the user something and wait for an answer:
    # questions in, a ``user_question.QuestionResult`` out (``None`` = nobody can be
    # asked). Bound as a callable because tools have no task identity and no event
    # sink of their own, and the registry fills it per call (ADR 0010 D1).
    ask_user: Optional[Callable[[Any], Any]] = None
    # The channel a tool uses to hand one self-contained task to a subagent
    # (``subagent``): a complete brief in, the final report out (``None`` = this run
    # cannot delegate). A callable for the same reason ``ask_user`` is - the nested
    # loop needs a provider and an event sink, and a tool is given neither (ADR 0032).
    run_subagent: Optional[Callable[[str], Optional[str]]] = None
