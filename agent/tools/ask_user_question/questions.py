"""Structural validation of the questions the model submits.

Only what cannot be shown or answered is refused:

* an empty question list (nothing to render);
* a question with no ``id`` (the answer contract is keyed by id), or a repeated id
  (the answers would be ambiguous the moment two questions share a key);
* a question with no prompt (nothing to ask);
* a question with no options, or an option with no label (the dialog would render a
  choice nobody can pick). This is the one check the reference implementation also
  makes.

Everything else is guidance, not a gate: the number of questions, the length of a
header, how many options, whether they are "mutually exclusive". Those live in the
tool description, and a call that breaks them still runs (see ``description.py``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# A missing header is not worth rejecting: the dialog needs a chip, not a decision.
_HEADER_FALLBACK_CHARS = 40


def normalize_questions(raw: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """``(questions, error)``: the questions the client will actually render."""
    if not isinstance(raw, list) or not raw:
        return None, "'questions' must be a non-empty array of questions."

    questions: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            return None, f"Question {index} must be an object."

        question_id = str(item.get("id") or "").strip()
        if not question_id:
            return None, f"Question {index} needs a non-empty 'id'."
        if question_id in seen:
            return None, (
                f"Duplicate question id: {question_id!r}. Ids key the answers, so each "
                "question needs its own."
            )
        seen.add(question_id)

        prompt = str(item.get("question") or "").strip()
        if not prompt:
            return None, f"Question {question_id!r} needs a non-empty 'question'."

        options, error = _normalize_options(item.get("options"), question_id)
        if error:
            return None, error

        questions.append(
            {
                "id": question_id,
                "header": str(item.get("header") or "").strip() or prompt[:_HEADER_FALLBACK_CHARS],
                "question": prompt,
                "options": options,
            }
        )
    return questions, None


def _normalize_options(
    raw: Any, question_id: str
) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    if not isinstance(raw, list) or not raw:
        return None, (
            f"Question {question_id!r} needs at least one option: a question with no "
            "options gives the user nothing to pick."
        )
    options: List[Dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            return None, f"Option {index} of question {question_id!r} must be an object."
        label = str(item.get("label") or "").strip()
        if not label:
            return None, f"Option {index} of question {question_id!r} needs a non-empty 'label'."
        options.append(
            {"label": label, "description": str(item.get("description") or "").strip()}
        )
    return options, None
