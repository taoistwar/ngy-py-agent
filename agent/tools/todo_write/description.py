"""What the model is told about ``todo_write``: name, description and schema.

The limits (at most 20 items, exactly one step in progress) are stated here *and*
enforced in ``items.py``: unlike ``ask_user_question``'s style guidance these are
structural - a plan with two steps in progress cannot be rendered as "what is
happening now", and a 200-item list is a wall the UI cannot show. A rejected call
therefore never comes as a surprise.
"""

from __future__ import annotations

from typing import Any, Dict

TODO_WRITE_TOOL_NAME = "todo_write"

# The three paragraphs are one instruction each: plan before acting, one step at a
# time, and send the whole list every time (the call replaces, it does not append).
TODO_WRITE_DESCRIPTION = (
    "Create and maintain the plan for the current task as an ordered checklist. Call it "
    "before starting work that needs more than a couple of steps: write every step down as "
    "'pending' first, then mark the step you are on as 'in_progress', and switch it to "
    "'completed' as soon as it is done - keep exactly one step in progress, or none when "
    "everything is done or you are still planning. Each call replaces the whole list, so "
    "always send the complete plan: the steps you finished stay in it, marked 'completed'. "
    "The list belongs to the conversation, not to this call: it survives into the next task "
    "of the same conversation and is shown to the user, so keep each item short, concrete and "
    "in the user's language, and do not list steps you are not going to execute. At most 20 "
    "items; two to seven is right for most tasks. The result echoes the normalized list, "
    "which is what 'the plan' now is."
)

TODO_WRITE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "description": (
                "The complete plan in order. Replaces the previous list; send finished steps "
                "too, marked 'completed'."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "One short imperative sentence naming the step.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                        "description": (
                            "'pending' not started, 'in_progress' being worked on now (at most "
                            "one), 'completed' done."
                        ),
                    },
                },
                "required": ["content", "status"],
            },
        }
    },
    "required": ["todos"],
}
