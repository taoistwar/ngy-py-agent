"""What the model is told about ``memory_save``: name, description and schema.

The index/body split is the one rule the description has to teach, because it decides
what the model writes: the description is what every later session sees, the body is
what a later session reads only when it asks. The limits stated here match
``agent/tools/memory_notes.py``, which enforces them, so a rejected call never comes as
a surprise.
"""

from __future__ import annotations

from typing import Any, Dict

from agent.tools.memory_notes import (
    MAX_BODY_CHARS,
    MAX_DESCRIPTION_CHARS,
    MEMORY_TYPES,
    SCOPES,
    TYPE_HINTS,
)

MEMORY_SAVE_TOOL_NAME = "memory_save"

# One instruction per paragraph: what to keep, what not to keep, and the shape of a note.
MEMORY_SAVE_DESCRIPTION = (
    "Save one durable note so a later conversation does not have to be told again. Call it "
    "when the user states a lasting preference or a standing rule about how work should be "
    "done, when you learn a stable fact about the project (a decision and why, a constraint, "
    "where something lives), or when the user asks you to remember something.\n\n"
    "Do not save what only matters for this task: the command that worked once, a temporary "
    "path, an intermediate finding. Say so with scope 'current_task' and the note is refused "
    "on purpose - keep following it yourself, but do not turn it into a standing rule.\n\n"
    "One memory is one idea: a short slug name, a single index line, and a body of a few "
    "sentences that a later session can act on without reading this conversation. The whole "
    "library is already listed in your system prompt by name and description, and only bodies "
    "are read with memory_search - so make the description say what the note is about and put "
    "the details in the body. Saving the same name again replaces it, which is how a memory is "
    "corrected. The result says whether the note was saved, replaced, or refused and why."
)

MEMORY_SAVE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "Short identifier used as the key, such as 'user-prefers-tabs' or "
                "'auth-rewrite-driven-by-compliance'. Saving the same name replaces what it held."
            ),
        },
        "type": {
            "type": "string",
            "enum": list(MEMORY_TYPES),
            "description": "; ".join(f"{kind} = {hint}" for kind, hint in TYPE_HINTS.items()) + ".",
        },
        "description": {
            "type": "string",
            "description": (
                "One line for the memory index: what this note is about, not a summary of the "
                f"whole body. At most {MAX_DESCRIPTION_CHARS} characters."
            ),
        },
        "body": {
            "type": "string",
            "description": (
                "The note itself, in the user's language: what was learned and what a later "
                f"session needs in order to act on it. At most {MAX_BODY_CHARS} characters."
            ),
        },
        "scope": {
            "type": "string",
            "enum": list(SCOPES),
            "description": (
                "'persistent' when the fact still matters in a later session (this is the only "
                "value that gets stored); 'current_task' when it only constrains the work at hand."
            ),
        },
    },
    "required": ["name", "type", "description", "body", "scope"],
}
