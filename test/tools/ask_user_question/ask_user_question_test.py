"""Tests for the ``ask_user_question`` tool: declaration, validation, output contract.

Two decisions are pinned here because they are the ones a future reader would
"fix" by accident:

* the numbers (1-3 questions, 2-3 options, a 12-character header) are **prose**;
  the tool does not refuse a call over them (see ``description.py``);
* the answer shape is JSON keyed by question id, with no ``user_note:`` prefix
  smuggled in front of free text (ADR 0010 D5).

Run from the repository root::

    uv run python test/tools/ask_user_question/ask_user_question_test.py -v
"""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.ask_user_question import (  # noqa: E402
    ASK_USER_QUESTION_DESCRIPTION,
    ASK_USER_QUESTION_PARAMETERS,
    ASK_USER_QUESTION_TOOL_NAME,
    make_ask_user_question_tool,
)
from agent.tools.ask_user_question import spec as ask_user_question_spec  # noqa: E402
from agent.tools.bindings import ToolBindings  # noqa: E402
from agent.tools.permissions import PERMISSION_NONE  # noqa: E402
from agent.tools.user_question import (  # noqa: E402
    STATUS_ANSWERED,
    STATUS_NO_CLIENT,
    STATUS_TIMEOUT,
    QuestionResult,
)

ONE_QUESTION = [
    {
        "id": "approach",
        "header": "Approach",
        "question": "Which way should I take?",
        "options": [
            {"label": "Rewrite (Recommended)", "description": "Cleaner core"},
            {"label": "Patch it", "description": "Smaller diff"},
        ],
    }
]


def payload_of(model_text: str):
    """The JSON the model reads, without the sentence explaining an empty answer set."""
    return json.loads(model_text.split("\n\n")[0])


class FakeChannel:
    """Stands in for the bound channel: records the questions, returns a scripted result."""

    def __init__(self, result: Optional[QuestionResult] = None) -> None:
        self.result = result or QuestionResult(answers={}, status=STATUS_ANSWERED)
        self.seen: List[Any] = []

    def __call__(self, questions: Any) -> QuestionResult:
        self.seen.append(questions)
        return self.result


class DeclarationTest(unittest.TestCase):
    def test_the_schema_describes_the_numbers_without_enforcing_them(self):
        properties = ASK_USER_QUESTION_PARAMETERS["properties"]
        question = properties["questions"]["items"]

        self.assertEqual(properties["questions"]["type"], "array")
        self.assertEqual(ASK_USER_QUESTION_PARAMETERS["required"], ["questions"])
        self.assertEqual(question["required"], ["id", "header", "question", "options"])
        # The numbers live in prose on purpose (ADR 0010 D7): a call that exceeds them
        # is verbose, not invalid, and the UI renders whatever arrives.
        self.assertNotIn("maxItems", properties["questions"])
        self.assertNotIn("minItems", properties["questions"])
        self.assertNotIn("maxLength", question["properties"]["header"])
        self.assertNotIn("maxItems", question["properties"]["options"])

    def test_the_description_states_the_three_disciplines(self):
        for clause in (
            "Do not use it to ask permission",
            "Do not add an 'Other' option",
            "(Recommended)",
            "one to three short questions",
            "decide yourself",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, ASK_USER_QUESTION_DESCRIPTION)


class SpecTest(unittest.TestCase):
    def test_the_spec_is_registered_without_a_gate_and_without_a_channel(self):
        spec = ask_user_question_spec.build_spec(ToolBindings())

        self.assertEqual(spec.name, ASK_USER_QUESTION_TOOL_NAME)
        self.assertEqual(ASK_USER_QUESTION_TOOL_NAME, "ask_user_question")
        # Asking is not a privileged action: a dialog in front of it would be exactly
        # the confusion the description forbids (ADR 0010 D6).
        self.assertEqual(spec.permission, PERMISSION_NONE)
        self.assertEqual(spec.parameters, ASK_USER_QUESTION_PARAMETERS)
        # A run with no channel still builds; the call answers "no_client".
        outcome = spec.handler(questions=ONE_QUESTION)
        self.assertEqual(outcome.details["status"], STATUS_NO_CLIENT)


class OutputContractTest(unittest.TestCase):
    def ask(self, questions=ONE_QUESTION, channel=None):
        channel = channel or FakeChannel()
        tool = make_ask_user_question_tool(channel)
        return tool(questions=questions), channel

    def test_the_model_gets_json_keyed_by_question_id(self):
        channel = FakeChannel(
            QuestionResult(
                answers={"approach": {"answers": ["Rewrite (Recommended)"]}},
                status=STATUS_ANSWERED,
            )
        )

        outcome, _ = self.ask(channel=channel)

        self.assertEqual(
            json.loads(outcome.model_text),
            {"answers": {"approach": {"answers": ["Rewrite (Recommended)"]}}},
        )
        self.assertEqual(outcome.details["status"], STATUS_ANSWERED)
        self.assertEqual(outcome.details["answered_count"], 1)
        self.assertEqual(outcome.details["question_count"], 1)
        # The events belong to the broker: a second category here would be a second
        # place for the same payload to drift (ADR 0010 D3).
        self.assertIsNone(outcome.event_category)

    def test_free_text_is_its_own_entry_with_no_prefix(self):
        channel = FakeChannel(
            QuestionResult(
                answers={"approach": {"answers": ["Patch it", "only in the parser"]}},
                status=STATUS_ANSWERED,
            )
        )

        outcome, _ = self.ask(channel=channel)

        self.assertEqual(
            json.loads(outcome.model_text)["answers"]["approach"]["answers"],
            ["Patch it", "only in the parser"],
        )

    def test_a_skipped_question_keeps_an_empty_list(self):
        channel = FakeChannel(
            QuestionResult(answers={"approach": {"answers": []}}, status=STATUS_ANSWERED)
        )

        outcome, _ = self.ask(channel=channel)

        self.assertEqual(json.loads(outcome.model_text), {"answers": {"approach": {"answers": []}}})

    def test_the_numbers_are_guidance_even_when_the_model_ignores_them(self):
        noisy: List[Dict[str, Any]] = []
        for index in range(5):
            noisy.append(
                {
                    "id": f"q{index}",
                    "header": "h" * 200,
                    "question": "Which one?",
                    "options": [{"label": f"option {n}"} for n in range(8)],
                }
            )

        outcome, channel = self.ask(questions=noisy)

        self.assertEqual(len(channel.seen[0]), 5)
        self.assertEqual(len(channel.seen[0][0]["options"]), 8)
        self.assertTrue(outcome.details["success"])

    def test_a_missing_header_is_derived_from_the_question(self):
        without_header = [
            {"id": "q", "question": "Which one?", "options": [{"label": "A"}]},
        ]

        _, channel = self.ask(questions=without_header)

        self.assertEqual(channel.seen[0][0]["header"], "Which one?")

    def test_an_option_without_a_label_is_reported_not_invented(self):
        broken = [
            {
                "id": "q",
                "header": "H",
                "question": "Which one?",
                "options": [{"description": "no label"}],
            }
        ]

        outcome, channel = self.ask(questions=broken)

        self.assertFalse(outcome.details["success"])
        self.assertEqual(outcome.details["reason"], "invalid_argument")
        self.assertEqual(channel.seen, [])


class ValidationTest(unittest.TestCase):
    CASES = (
        (None, "non-empty array"),
        ([], "non-empty array"),
        ("questions", "non-empty array"),
        ([{"header": "H", "question": "Q", "options": [{"label": "A"}]}], "non-empty 'id'"),
        (
            [
                {"id": "q", "header": "H", "question": "Q", "options": [{"label": "A"}]},
                {"id": "q", "header": "H", "question": "Other", "options": [{"label": "B"}]},
            ],
            "Duplicate question id",
        ),
        ([{"id": "q", "header": "H", "question": "   ", "options": [{"label": "A"}]}], "'question'"),
        ([{"id": "q", "header": "H", "question": "Q", "options": []}], "at least one option"),
        ([{"id": "q", "header": "H", "question": "Q", "options": "A"}], "at least one option"),
        ([{"id": "q", "header": "H", "question": "Q", "options": [{"description": "x"}]}], "'label'"),
        (["not an object"], "must be an object"),
    )

    def test_what_cannot_be_rendered_is_refused(self):
        channel = FakeChannel()
        tool = make_ask_user_question_tool(channel)

        for questions, expected in self.CASES:
            with self.subTest(questions=questions):
                outcome = tool(questions=questions)

                self.assertFalse(outcome.details["success"])
                self.assertEqual(outcome.details["reason"], "invalid_argument")
                self.assertIn(expected, outcome.model_text)

        self.assertEqual(channel.seen, [], "a rejected call must not reach the user")


class NoChannelTest(unittest.TestCase):
    def test_without_a_channel_the_answer_says_so_instead_of_blocking(self):
        tool = make_ask_user_question_tool(None)

        outcome = tool(questions=ONE_QUESTION)

        self.assertEqual(payload_of(outcome.model_text), {"answers": {}})
        self.assertIn("No client is connected", outcome.model_text)
        self.assertEqual(outcome.details["status"], STATUS_NO_CLIENT)
        self.assertEqual(outcome.details["answered_count"], 0)

    def test_a_timeout_is_reported_with_the_reason(self):
        channel = FakeChannel(QuestionResult(answers={}, status=STATUS_TIMEOUT, timeout_seconds=30.0))

        outcome = make_ask_user_question_tool(channel)(questions=ONE_QUESTION)

        self.assertEqual(payload_of(outcome.model_text), {"answers": {}})
        self.assertIn("within 30 seconds", outcome.model_text)
        self.assertEqual(outcome.details["status"], STATUS_TIMEOUT)
        self.assertEqual(outcome.details["timeout_seconds"], 30.0)


if __name__ == "__main__":
    unittest.main()
