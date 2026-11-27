"""The rules of the task board, without a store, a model or a database.

Three behaviours are pinned because they are the whole reason the board exists:

* a task may start only when every prerequisite is completed (a missing one blocks);
* only the conversation that claimed a task may complete it;
* completion reports exactly the tasks it *newly* unblocked, not everything ready.

Run from the repository root::

    uv run python test/tools/task_board_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.task_board import (  # noqa: E402
    MAX_SUBJECT_CHARS,
    TaskBoardError,
    board_state,
    incomplete_blockers,
    is_ready,
    merged_dependencies,
    plan_claim,
    plan_complete,
    render_list,
    render_task,
    validate_description,
    validate_subject,
)


def task(task_id, status="pending", blocked_by=(), owner=None, subject=None, description=""):
    return {
        "task_id": task_id,
        "subject": subject or task_id,
        "description": description,
        "status": status,
        "owner": owner,
        "blocked_by": list(blocked_by),
    }


class ReadinessTest(unittest.TestCase):
    def test_a_task_with_no_prerequisites_is_ready(self):
        tasks = [task("task_a")]

        self.assertTrue(is_ready(tasks[0], {tasks[0]["task_id"]: tasks[0]}))
        self.assertEqual(incomplete_blockers(tasks[0], {"task_a": tasks[0]}), [])

    def test_only_completed_prerequisites_stop_blocking(self):
        tasks = [
            task("task_a", status="completed"),
            task("task_b", status="in_progress"),
            task("task_c", blocked_by=["task_a", "task_b"]),
        ]
        index = {item["task_id"]: item for item in tasks}

        self.assertEqual(incomplete_blockers(tasks[2], index), ["task_b"])
        self.assertFalse(is_ready(tasks[2], index))

    def test_a_missing_prerequisite_blocks_instead_of_freeing_the_task(self):
        tasks = [task("task_b", blocked_by=["task_gone"])]

        self.assertEqual(incomplete_blockers(tasks[0], {"task_b": tasks[0]}), ["task_gone"])

    def test_a_claimed_task_is_not_ready(self):
        tasks = [task("task_a", status="in_progress", owner="s1")]

        self.assertFalse(is_ready(tasks[0], {"task_a": tasks[0]}))

    def test_board_state_carries_the_subjects_a_reader_cannot_resolve(self):
        tasks = [
            task("task_a", subject="setup schema"),
            task("task_b", blocked_by=["task_a"], subject="API"),
        ]

        view = board_state(tasks)

        self.assertEqual(view[1]["blocked_by_subjects"], ["setup schema"])
        self.assertEqual(view[1]["incomplete_blockers"], ["task_a"])
        self.assertFalse(view[1]["ready"])
        self.assertEqual(view[0]["blocked_by_subjects"], [])
        self.assertTrue(view[0]["ready"])


class ValidationTest(unittest.TestCase):
    def test_a_subject_is_required_and_bounded(self):
        self.assertEqual(validate_subject("  setup schema  "), "setup schema")
        for subject in ("", "   ", None):
            with self.subTest(subject=subject):
                with self.assertRaises(TaskBoardError):
                    validate_subject(subject)
        with self.assertRaises(TaskBoardError):
            validate_subject("x" * (MAX_SUBJECT_CHARS + 1))

    def test_a_description_is_optional_and_bounded(self):
        self.assertEqual(validate_description(None), "")
        self.assertEqual(validate_description("  criteria  "), "criteria")
        with self.assertRaises(TaskBoardError):
            validate_description("x" * 5000)


class DependenciesTest(unittest.TestCase):
    def test_edges_are_added_without_duplicates(self):
        tasks = [task("task_a"), task("task_b")]

        merged = merged_dependencies(tasks, "task_b", ["task_a", "task_a"])

        self.assertEqual(merged, ["task_a"])

    def test_a_task_cannot_depend_on_itself(self):
        with self.assertRaises(TaskBoardError) as caught:
            merged_dependencies([task("task_a")], "task_a", ["task_a"])

        self.assertEqual(caught.exception.reason, "conflict")

    def test_an_unknown_dependency_is_refused(self):
        with self.assertRaises(TaskBoardError) as caught:
            merged_dependencies([task("task_a")], "task_a", ["task_nope"])

        self.assertEqual(caught.exception.reason, "not_found")

    def test_a_cycle_is_refused(self):
        tasks = [task("task_a", blocked_by=["task_b"]), task("task_b")]

        with self.assertRaises(TaskBoardError) as caught:
            merged_dependencies(tasks, "task_b", ["task_a"])

        self.assertEqual(caught.exception.reason, "conflict")
        self.assertIn("cycle", caught.exception.message)

    def test_only_a_pending_unclaimed_task_accepts_new_edges(self):
        tasks = [task("task_a"), task("task_b", status="in_progress", owner="s1")]

        with self.assertRaises(TaskBoardError) as caught:
            merged_dependencies(tasks, "task_b", ["task_a"])

        self.assertEqual(caught.exception.reason, "conflict")

    def test_an_empty_or_malformed_addition_is_refused(self):
        for add in ([], None, "task_a"):
            with self.subTest(add=add):
                with self.assertRaises(TaskBoardError):
                    merged_dependencies([task("task_a")], "task_a", add)


class ClaimAndCompleteTest(unittest.TestCase):
    def test_a_ready_task_is_claimed_by_its_owner(self):
        changes = plan_claim([task("task_a")], "task_a", "session-1")

        self.assertEqual(changes, {"status": "in_progress", "owner": "session-1"})

    def test_a_blocked_task_cannot_be_claimed(self):
        tasks = [task("task_a", subject="schema"), task("task_b", blocked_by=["task_a"])]

        with self.assertRaises(TaskBoardError) as caught:
            plan_claim(tasks, "task_b", "session-1")

        self.assertEqual(caught.exception.reason, "blocked")
        self.assertIn("task_a", caught.exception.message)

    def test_a_task_that_is_not_pending_cannot_be_claimed(self):
        tasks = [task("task_a", status="completed")]

        with self.assertRaises(TaskBoardError) as caught:
            plan_claim(tasks, "task_a", "session-1")

        self.assertEqual(caught.exception.reason, "conflict")

    def test_only_the_owner_can_complete(self):
        tasks = [task("task_a", status="in_progress", owner="session-1")]

        with self.assertRaises(TaskBoardError) as caught:
            plan_complete(tasks, "task_a", "session-2")

        self.assertEqual(caught.exception.reason, "owner_mismatch")

    def test_completion_reports_only_what_it_newly_unblocked(self):
        tasks = [
            task("task_a", status="in_progress", owner="session-1"),
            # Ready before and after this completion: it was not waiting for it.
            task("task_free"),
            task("task_b", blocked_by=["task_a"]),
            # Still blocked by "task_free", so this completion did not release it.
            task("task_waiting", blocked_by=["task_free"]),
            task("task_c", blocked_by=["task_a"]),
        ]

        changes, unblocked = plan_complete(tasks, "task_a", "session-1")

        self.assertEqual(changes, {"status": "completed"})
        self.assertEqual(
            [item["task_id"] for item in unblocked], ["task_b", "task_c"]
        )

    def test_completion_of_a_task_nothing_waits_on_unblocks_nothing(self):
        tasks = [task("task_a", status="in_progress", owner="session-1"), task("task_b")]

        _, unblocked = plan_complete(tasks, "task_a", "session-1")

        self.assertEqual(unblocked, [])

    def test_completing_a_task_that_is_not_in_progress_is_refused(self):
        with self.assertRaises(TaskBoardError) as caught:
            plan_complete([task("task_a")], "task_a", "session-1")

        self.assertEqual(caught.exception.reason, "conflict")


class RenderingTest(unittest.TestCase):
    def test_the_list_says_what_is_ready_and_what_blocks(self):
        tasks = [
            task("task_a", status="completed", subject="schema"),
            task("task_b", status="in_progress", owner="me", subject="API"),
            task("task_c", blocked_by=["task_b"], subject="tests"),
            task("task_d", subject="docs"),
        ]

        text = render_list(tasks, "me")

        lines = text.splitlines()
        self.assertIn("(1/4 completed)", lines[0])
        self.assertIn("[x] task_a: schema", lines[1])
        self.assertIn("owner: this conversation", lines[2])
        self.assertIn("blocked by task_b", lines[3])
        self.assertIn("ready to claim", lines[4])

    def test_the_list_of_an_empty_board_points_at_the_right_tool(self):
        self.assertIn("task_create", render_list([], ""))

    def test_one_task_in_full_carries_its_description(self):
        text = render_task(
            task(
                "task_a",
                status="in_progress",
                owner="other",
                blocked_by=["task_b"],
                subject="API",
                description="CRUD over the schema",
            ),
            "me",
        )

        self.assertIn("Task task_a: API", text)
        self.assertIn("status: in_progress (owner: another conversation)", text)
        self.assertIn("blocked by: task_b", text)
        self.assertIn("CRUD over the schema", text)


if __name__ == "__main__":
    unittest.main()
