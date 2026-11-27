"""What the model is told about ``subagent``: its description and parameter schema.

The description carries the two facts a caller gets wrong on its own: the subagent
does not see this conversation, and its intermediate tool calls never come back. Both
are stated here rather than left to the system prompt because the model reads the
tool list at the moment it decides to delegate.
"""

from __future__ import annotations

from typing import Any, Dict

SUBAGENT_TOOL_NAME = "subagent"

# Delegation is one level deep: the child run never receives this tool, so a brief
# cannot turn into a tree of agents.
SUBAGENT_DESCRIPTION = (
    "Delegate one self-contained sub-task to a subagent that starts from a fresh "
    "conversation: it sees only the 'prompt' you give it, never this conversation. "
    "Use it when the work would otherwise flood this context with intermediate detail "
    "- tracing a call chain across many files, surveying a directory, or building and "
    "verifying one small piece in isolation. The subagent has the same tools (except "
    "this one), the same workspace and the same permission checks, but its tool calls "
    "and results never enter this conversation: you receive only its final report. "
    "Write 'prompt' as a complete brief - the goal, the paths or facts it needs, what "
    "to report back, and any constraints - and ask it to end with a short report. The "
    "subagent cannot delegate further, so do not ask it to spawn another agent. If the "
    "report shows the task was not done, correct the brief and delegate again instead "
    "of redoing every step here."
)

SUBAGENT_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": (
                "Complete instructions for the subagent. It knows nothing about this "
                "conversation, so include the goal, the context it needs, and the exact "
                "result to report back."
            ),
        }
    },
    "required": ["prompt"],
}
