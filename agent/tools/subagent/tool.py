"""The ``subagent`` call itself: validate the brief, hand it to the run's runner.

The nested loop belongs to :mod:`agent.agent_loop.subagent`; this module only owns
the tool's contract. The runner arrives as a callable (``ToolBindings.run_subagent``)
for the same reason ``ask_user`` does: a tool has no provider and no event sink, and
both are the loop's knowledge, not the tool's. A run with no runner bound (a library
call, the CLI, a test) says so instead of raising - the model then continues itself.
"""

from __future__ import annotations

from typing import Callable, Optional

from agent.tools.subagent.errors import SubagentError

# The channel: a complete brief in, the subagent's final report out. ``None`` means
# this run cannot delegate.
SubagentRunner = Callable[[str], Optional[str]]

NO_RUNNER_TEXT = (
    "The subagent tool is not available in this run (no subagent runner is bound). "
    "Continue the task yourself without delegating."
)


def subagent_impl(prompt: object, runner: Optional[object]) -> str:
    """Run one delegated task and return the subagent's final report."""
    text = str(prompt or "").strip()
    if not text:
        raise SubagentError("The 'prompt' argument is required and cannot be blank.")

    if runner is None:
        return NO_RUNNER_TEXT

    report = runner(text)
    if report is None:
        return NO_RUNNER_TEXT
    return str(report)


def make_subagent_tool(run_subagent: Optional[object] = None):
    """Bind the tool to this run's subagent runner (may be ``None``)."""

    def subagent(prompt: object = None) -> str:
        return subagent_impl(prompt, run_subagent)

    return subagent
