"""Continue tasks whose process died mid-run.

A task runs on a thread, and a thread does not survive the process that owns it.
The event log does, though: it holds the prompt the task started from, every model
answer, and every tool result that was recorded. This package turns that log back
into the two things a task needs to go on - its conversation and its step number -
so the restarted process resumes the work instead of replaying it.

The public entry point is :func:`resume_interrupted_tasks`, called once at startup.
What counts as "interrupted" and how the conversation is rebuilt lives in
:mod:`task_recovery.transcript`; starting the threads lives in
:mod:`task_recovery.launch`.
"""

from task_recovery.launch import resume_interrupted_tasks
from task_recovery.transcript import (
    INTERRUPTED_TOOL_NOTE,
    ResumeMode,
    ResumePlan,
    build_resume_plan,
)

__all__ = [
    "INTERRUPTED_TOOL_NOTE",
    "ResumeMode",
    "ResumePlan",
    "build_resume_plan",
    "resume_interrupted_tasks",
]
