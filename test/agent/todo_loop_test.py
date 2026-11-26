"""The two places the loop touches the plan: the prompt and the reminder.

Both are pure functions over state, which is the point: "the plan an earlier task
left" and "three rounds without an update" are testable without a model, a task
thread or a database.

Run from the repository root::

    uv run python test/agent/todo_loop_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop.todo_context import append_todo_context  # noqa: E402
from agent.agent_loop.todo_reminder import (  # noqa: E402
    REMINDER_TEXT,
    TodoReminder,
    append_to_last_tool_message,
)

PLAN = [
    {"content": "Read the parser", "status": "completed"},
    {"content": "Fix the parser", "status": "in_progress"},
]


class TodoContextTest(unittest.TestCase):
    def test_a_new_conversation_prompt_is_untouched(self):
        self.assertEqual(append_todo_context("base prompt", []), "base prompt")

    def test_a_left_plan_is_appended_with_an_instruction_to_continue_it(self):
        prompt = append_todo_context("base prompt", PLAN)

        self.assertTrue(prompt.startswith("base prompt"))
        self.assertIn("Plan left by an earlier task", prompt)
        self.assertIn("Continue it instead of starting over", prompt)
        self.assertIn("[x] Read the parser", prompt)
        self.assertIn("[>] Fix the parser", prompt)

    def test_entries_that_are_not_objects_are_ignored(self):
        self.assertEqual(append_todo_context("base", ["junk"]), "base")


class TodoReminderTest(unittest.TestCase):
    def test_only_the_third_round_without_an_update_is_nudged(self):
        reminder = TodoReminder()

        self.assertIsNone(reminder.record(["read_file"]))
        self.assertIsNone(reminder.record(["read_file", "grep"]))
        self.assertEqual(reminder.record(["exec_command"]), REMINDER_TEXT)

    def test_updating_the_plan_restarts_the_count(self):
        reminder = TodoReminder()

        reminder.record(["read_file"])
        reminder.record(["read_file"])
        self.assertIsNone(reminder.record(["todo_write", "read_file"]))
        self.assertIsNone(reminder.record(["read_file"]))
        self.assertIsNone(reminder.record(["read_file"]))
        self.assertEqual(reminder.record(["read_file"]), REMINDER_TEXT)

    def test_the_next_reminder_is_three_rounds_later(self):
        reminder = TodoReminder()

        for _ in range(3):
            reminder.record(["read_file"])
        self.assertIsNone(reminder.record(["read_file"]))
        self.assertIsNone(reminder.record(["read_file"]))
        self.assertEqual(reminder.record(["read_file"]), REMINDER_TEXT)


class AppendReminderTest(unittest.TestCase):
    def test_the_nudge_rides_on_the_last_tool_result_of_the_round(self):
        messages = [
            {"role": "assistant", "content": ""},
            {"role": "tool", "content": "first result"},
            {"role": "tool", "content": "second result"},
        ]

        self.assertTrue(append_to_last_tool_message(messages, 1, REMINDER_TEXT))

        self.assertEqual(messages[1]["content"], "first result")
        self.assertEqual(messages[2]["content"], f"second result\n\n{REMINDER_TEXT}")

    def test_a_round_without_tool_results_is_left_alone(self):
        messages = [{"role": "assistant", "content": ""}]

        self.assertFalse(append_to_last_tool_message(messages, 1, REMINDER_TEXT))
        self.assertEqual(messages, [{"role": "assistant", "content": ""}])


if __name__ == "__main__":
    unittest.main()
