"""What the model is told about ``ask_user_question``: name, description and schema.

The numbers - one question preferred and at most three, two or three options, a header
of twelve characters or fewer - live in the **prose only**. That is what the reference
implementation does, and it is deliberate: they are style guidance for the model, not
properties worth refusing a call over. Prose does not go unread: the two things the
tool *does* enforce (a question must have a prompt and options, ids must be unique) are
stated here too, so a rejected call is never a surprise. See ``questions.py``.
"""

from __future__ import annotations

from typing import Any, Dict

ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"

# Said once, in the tool description, because every clause of it has been a real
# failure mode somewhere: asking permission through this tool, asking one question per
# turn, and treating "nobody answered" as a reason to ask again.
ASK_USER_QUESTION_DESCRIPTION = (
    "Ask the user one to three short questions and wait for the answers. Use it when the "
    "decision is genuinely the user's - which of two designs to take, which environment to "
    "target, whether to replace something - and the answer changes what you do next. Do not "
    "use it to ask permission: tool calls are confirmed by the client, not by you. Ask every "
    "question you need in one call (at most three), keep each to a single sentence, give two "
    "or three mutually exclusive options, and put the option you recommend first with "
    "'(Recommended)' at the end of its label. Do not add an 'Other' option: the client adds a "
    "free-form one to every question. The result is JSON keyed by each question's id "
    "('{\"answers\": {\"<id>\": {\"answers\": [...]}}}'); an option the user picked appears as "
    "its label, anything they typed appears as another entry, and a question they skipped has "
    "an empty list. When nobody answers - no client is connected, or the wait times out - the "
    "answer set is empty and the result says why: decide yourself with the information you "
    "have, state the assumption you made, and do not ask again."
)

ASK_USER_QUESTION_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "Questions to show the user. Prefer 1 and do not exceed 3.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Stable identifier for mapping answers (snake_case).",
                    },
                    "header": {
                        "type": "string",
                        "description": "Short header label shown in the UI (12 or fewer chars).",
                    },
                    "question": {
                        "type": "string",
                        "description": "Single-sentence prompt shown to the user.",
                    },
                    "options": {
                        "type": "array",
                        "description": (
                            "Provide 2-3 mutually exclusive choices, and at least one: a question "
                            "with no options cannot be rendered as a choice. Put the recommended "
                            "option first and suffix its label with \"(Recommended)\". Do not "
                            "include an \"Other\" option in this list; the client will add a "
                            "free-form \"Other\" option automatically."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "User-facing label (1-5 words).",
                                },
                                "description": {
                                    "type": "string",
                                    "description": (
                                        "One short sentence explaining impact/tradeoff if "
                                        "selected."
                                    ),
                                },
                            },
                            "required": ["label"],
                        },
                    },
                },
                "required": ["id", "header", "question", "options"],
            },
        }
    },
    "required": ["questions"],
}
