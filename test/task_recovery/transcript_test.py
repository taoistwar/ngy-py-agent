"""Rebuilding an interrupted task's conversation from its event log.

The whole point of the resume is that it *does not redo work*: a tool result that
was recorded is reused, and a call whose result never reached the log is reported
to the model instead of being executed a second time. These tests pin that rule,
because it is the only thing standing between a crash and a duplicated edit.

Run from the repository root::

    uv run python test/task_recovery/transcript_test.py -v
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import TaskStatus  # noqa: E402
from task_recovery.transcript import (  # noqa: E402
    INTERRUPTED_TOOL_NOTE,
    MAX_STEPS_RESULT,
    ResumeMode,
    build_resume_plan,
)

SYSTEM = {"role": "system", "content": "you are an agent"}
QUERY = {"role": "user", "content": "rename the file"}


def _event(category, title, data):
    return {
        "event_id": f"{category}-{title}-{data.get('step', 0)}",
        "task_id": "task-1",
        "category": category,
        "title": title,
        "source": "agent",
        "data": data,
        "collapsed": True,
    }


def _starting(max_steps=8, initial_messages=None):
    data = {"max_steps": max_steps, "query": QUERY["content"]}
    if initial_messages is not None:
        data["initial_messages"] = initial_messages
    return _event("debug", "Starting ReAct loop", data)


def _request(step, messages, provider="openai-compatible"):
    return _event(
        "llm_request",
        f"LLM request Step {step}",
        {
            "step": step,
            "provider": provider,
            "raw_request": {"model": "m", "messages": messages},
        },
    )


def _response(step, message, content=None):
    return _event(
        "llm_response",
        f"LLM response Step {step}",
        {
            "step": step,
            "content": message.get("content", "") if content is None else content,
            "raw_response": {
                "object": "chat.completion",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            },
        },
    )


def _tool_result(step, name, call_id, result):
    return _event(
        "tool_result",
        f"Tool result: {name}",
        {"step": step, "name": name, "tool_call_id": call_id, "result": result},
    )


def _tool_call_message(call_id, name, arguments="{}"):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


class ResumePlanTest(unittest.TestCase):
    def test_no_model_request_restarts_from_the_beginning(self):
        plan = build_resume_plan([_starting()], QUERY["content"])

        self.assertEqual(ResumeMode.RESTART, plan.mode)
        self.assertEqual(8, plan.max_steps)
        self.assertEqual([], plan.messages)

    def test_a_request_without_a_response_is_asked_again(self):
        """Nothing was executed for that step, so the same step may simply be retried."""
        plan = build_resume_plan(
            [_starting(initial_messages=[SYSTEM, QUERY]), _request(1, [SYSTEM, QUERY])],
            QUERY["content"],
        )

        self.assertEqual(ResumeMode.CONTINUE, plan.mode)
        self.assertEqual(1, plan.next_step)
        self.assertEqual([SYSTEM, QUERY], plan.messages)
        self.assertEqual(0, plan.reused_results)
        self.assertEqual(0, plan.unresolved_calls)

    def test_a_recorded_tool_result_is_reused_never_re_executed(self):
        messages = [SYSTEM, QUERY]
        events = [
            _starting(initial_messages=messages),
            _request(1, messages),
            _response(1, _tool_call_message("call-1", "edit_file")),
            _tool_result(1, "edit_file", "call-1", "file renamed"),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.CONTINUE, plan.mode)
        self.assertEqual(2, plan.next_step)
        self.assertEqual(1, plan.reused_results)
        self.assertEqual(0, plan.unresolved_calls)
        self.assertEqual(
            {"role": "tool", "tool_call_id": "call-1", "name": "edit_file", "content": "file renamed"},
            plan.messages[-1],
        )

    def test_a_call_without_a_result_is_reported_not_replayed(self):
        """The dangerous window: the tool may have run, the process died before logging it."""
        messages = [SYSTEM, QUERY]
        events = [
            _starting(initial_messages=messages),
            _request(1, messages),
            _response(1, _tool_call_message("call-1", "exec_command")),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.CONTINUE, plan.mode)
        self.assertEqual(1, plan.unresolved_calls)
        self.assertEqual(0, plan.reused_results)
        self.assertEqual(INTERRUPTED_TOOL_NOTE, plan.messages[-1]["content"])
        self.assertEqual("call-1", plan.messages[-1]["tool_call_id"])
        # Everything before it is untouched, so the model still sees its own plan.
        self.assertEqual(_tool_call_message("call-1", "exec_command"), plan.messages[-1 - 1])

    def test_a_final_answer_that_was_never_closed_settles_the_task(self):
        messages = [SYSTEM, QUERY]
        events = [
            _starting(initial_messages=messages),
            _request(1, messages),
            _response(1, {"role": "assistant", "content": "done, file renamed"}, "done, file renamed"),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.SETTLE, plan.mode)
        self.assertEqual(TaskStatus.SUCCESS, plan.status)
        self.assertEqual("done, file renamed", plan.result)

    def test_a_task_that_already_concluded_is_only_settled(self):
        events = [
            _starting(initial_messages=[SYSTEM, QUERY]),
            _request(1, [SYSTEM, QUERY]),
            _response(1, {"role": "assistant", "content": "all done"}),
            _event("debug", "Task finished", {"result": "all done"}),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.SETTLE, plan.mode)
        self.assertEqual(TaskStatus.SUCCESS, plan.status)
        self.assertEqual("all done", plan.result)

    def test_a_failed_task_is_not_restarted(self):
        events = [
            _starting(initial_messages=[SYSTEM, QUERY]),
            _event("debug", "Task failed", {"error": "provider exploded"}),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.SETTLE, plan.mode)
        self.assertEqual(TaskStatus.FAILED, plan.status)

    def test_an_exhausted_task_is_not_run_again(self):
        messages = [SYSTEM, QUERY]
        events = [
            _starting(max_steps=2, initial_messages=messages),
            _request(1, messages),
            _response(1, _tool_call_message("call-1", "read_file")),
            _tool_result(1, "read_file", "call-1", "contents"),
            _request(2, messages),
            _response(2, _tool_call_message("call-2", "read_file")),
            _tool_result(2, "read_file", "call-2", "contents"),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.SETTLE, plan.mode)
        self.assertEqual(MAX_STEPS_RESULT, plan.result)

    def test_the_last_request_is_the_baseline_and_earlier_steps_are_not_replayed(self):
        """A multi-step task resumes from the request it had reached, not from step one."""
        first_messages = [SYSTEM, QUERY]
        second_messages = [
            SYSTEM,
            QUERY,
            _tool_call_message("call-1", "read_file"),
            {"role": "tool", "tool_call_id": "call-1", "name": "read_file", "content": "v1"},
        ]
        events = [
            _starting(initial_messages=first_messages),
            _request(1, first_messages),
            _response(1, _tool_call_message("call-1", "read_file")),
            _tool_result(1, "read_file", "call-1", "v1"),
            _request(2, second_messages),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.CONTINUE, plan.mode)
        self.assertEqual(2, plan.next_step)
        self.assertEqual(second_messages, plan.messages)

    def test_a_rewriting_adapter_falls_back_to_the_recorded_starting_point(self):
        """Anthropic-style requests hold wire payloads, not a chat transcript."""
        messages = [SYSTEM, QUERY]
        events = [
            _starting(initial_messages=messages),
            _request(1, messages, provider="anthropic"),
            _response(1, _tool_call_message("call-1", "read_file")),
            _tool_result(1, "read_file", "call-1", "v1"),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        self.assertEqual(ResumeMode.CONTINUE, plan.mode)
        self.assertEqual(2, plan.next_step)
        self.assertEqual("v1", plan.messages[-1]["content"])

    def test_a_legacy_task_without_a_starting_point_cannot_be_resumed(self):
        events = [
            _request(1, [QUERY], provider="anthropic"),
        ]

        self.assertIsNone(build_resume_plan(events, QUERY["content"]))

    def test_an_unknown_tool_call_id_is_given_one_so_the_pair_lines_up(self):
        messages = [SYSTEM, QUERY]
        events = [
            _starting(initial_messages=messages),
            _request(1, messages),
            _response(
                1,
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "read_file", "arguments": "{}"}}],
                },
            ),
        ]

        plan = build_resume_plan(events, QUERY["content"])

        assistant = plan.messages[-2]
        tool_message = plan.messages[-1]
        self.assertEqual(assistant["tool_calls"][0]["id"], tool_message["tool_call_id"])
        self.assertEqual("recovered-1-0", tool_message["tool_call_id"])


if __name__ == "__main__":
    unittest.main()
