"""The ``ask_user_question`` call itself: validate, ask, render.

The tool owns its arguments and the text the model reads. The question and the answer
reach the UI as ``user_question`` / ``user_answer`` events emitted by the broker in
:mod:`agent.tools.user_question`, so this tool adds no event of its own: the timeline
already says who asked what and what came back, and a third event would only be a
second place for the same payload to drift (ADR 0010 D3).

The channel arrives as a callable (``ToolBindings.ask_user``) rather than as a broker
the tool reaches for. A tool has no task identity and no event sink - that is the
invariant the glossary pins down - and a callable keeps it that way while letting the
registry decide, at call time, whether anyone can be asked at all.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

from agent.models import ToolOutcome
from agent.tools.ask_user_question.errors import AskUserQuestionError
from agent.tools.ask_user_question.questions import normalize_questions
from agent.tools.user_question import STATUS_NO_CLIENT, QuestionResult

# The channel: questions in, a result with the answers (possibly none) out.
AskUser = Callable[[Any], QuestionResult]


def ask_user_question_impl(questions_raw: Any, ask_user: Optional[AskUser]) -> Tuple[str, Dict[str, Any]]:
    """Ask the user; return ``(model_text, details)``."""
    questions, error = normalize_questions(questions_raw)
    if error:
        raise AskUserQuestionError(error, reason="invalid_argument", argument="questions")

    if ask_user is None:
        # No channel was bound to this run (a library caller, or a registry nobody
        # wired a broker into). Saying so is the honest answer: it is not a failure,
        # and it is definitely not a reason to block.
        result = QuestionResult(answers={}, status=STATUS_NO_CLIENT)
    else:
        result = ask_user(questions)

    # The output contract: JSON keyed by question id, exactly as the description
    # promises, with the reason spelled out when the answer set is empty.
    model_text = json.dumps(result.response(), ensure_ascii=False)
    note = result.note()
    if note:
        model_text = f"{model_text}\n\n{note}"

    details: Dict[str, Any] = {
        "success": True,
        "status": result.status,
        "answers": result.answers,
        "questions": questions,
        "answered_count": len(result.answers),
        "question_count": len(questions),
        "timeout_seconds": result.timeout_seconds,
    }
    return model_text, details


def make_ask_user_question_tool(ask_user: Optional[AskUser] = None):
    """Bind the question tool to this run's channel (may be ``None``)."""

    def ask_user_question(questions: Any = None) -> ToolOutcome:
        try:
            model_text, details = ask_user_question_impl(questions, ask_user)
        except AskUserQuestionError as exc:
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                details={"success": False, **exc.to_dict()},
            )
        return ToolOutcome(model_text=model_text, details=details)

    return ask_user_question
