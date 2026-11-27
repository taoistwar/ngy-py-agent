"""A tool event title names the tool and the argument that identifies the call.

Run from the repository root::

    uv run python test/tool_titles_test.py -v
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.agent_loop.tool_titles import VALUE_LIMIT, tool_title  # noqa: E402


class ToolTitleTest(unittest.TestCase):
    def test_the_description_names_an_exec_call(self):
        title = tool_title(
            "exec_command",
            {"command": "ls -la", "description": "列出工作区内所有文件"},
        )

        self.assertEqual(title, "exec_command : 列出工作区内所有文件")

    def test_a_command_without_a_description_falls_back_to_the_command(self):
        self.assertEqual(
            tool_title("exec_command", {"command": "uv run pytest"}),
            "exec_command : uv run pytest",
        )

    def test_a_read_is_named_by_the_path_it_reads(self):
        self.assertEqual(
            tool_title("read_file", {"file_path": "test.py", "limit": 20}),
            "read_file : test.py",
        )

    def test_the_task_subject_wins_over_its_description(self):
        self.assertEqual(
            tool_title("task_create", {"subject": "Fix login", "description": "long body"}),
            "task_create : Fix login",
        )

    def test_a_tool_with_nothing_to_name_keeps_only_the_name(self):
        self.assertEqual(tool_title("task_list", {}), "task_list")
        self.assertEqual(tool_title("todo_write", {"todos": [{"content": "x"}]}), "todo_write")

    def test_an_unknown_tool_is_named_by_its_first_scalar_argument(self):
        self.assertEqual(tool_title("mcp_search", {"term": "panels"}), "mcp_search : panels")

    def test_the_value_is_one_clipped_line(self):
        title = tool_title("exec_command", {"description": "line one\nline two " + "x" * 200})

        self.assertNotIn("\n", title)
        self.assertEqual(title, "exec_command : " + ("line one line two " + "x" * 200)[: VALUE_LIMIT - 1] + "…")

    def test_a_non_dict_argument_payload_keeps_only_the_name(self):
        self.assertEqual(tool_title("exec_command", '{"command": "ls"}'), "exec_command")


if __name__ == "__main__":
    unittest.main()
