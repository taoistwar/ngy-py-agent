"""How a task gets the short name the task list shows.

A query that already fits in the name length is its own name; anything longer is
summarized by the model, and the fallback keeps the name on one line when the
model is unavailable.

Run from the repository root::

    uv run python test/task_naming_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import app_state  # noqa: E402
import task_runtime  # noqa: E402
from task_store import _SqliteTaskStore  # noqa: E402


class _FakeProvider:
    """Stands in for a provider: returns a fixed completion, counts nothing."""

    def __init__(self, content):
        self._content = content

    def chat_completion(self, messages):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class TaskNamingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = app_state.monitor_store
        app_state.monitor_store = self.store
        self.task_id = self.store.create_task("placeholder", "openai")

    def tearDown(self):
        app_state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _name(self):
        return self.store.get_task(self.task_id)["name"]

    def test_a_short_query_is_its_own_name(self):
        with mock.patch.object(task_runtime, "_summarize") as summarize:
            task_runtime.update_task_name(self.task_id, "openai", None, "统计一下日志")

        summarize.assert_not_called()
        self.assertEqual("统计一下日志", self._name())

    def test_a_query_of_exactly_the_limit_is_not_summarized(self):
        query = "x" * task_runtime._TASK_NAME_MAX_LENGTH

        with mock.patch.object(task_runtime, "_summarize") as summarize:
            task_runtime.update_task_name(self.task_id, "openai", None, query)

        summarize.assert_not_called()
        self.assertEqual(query, self._name())

    def test_a_long_query_is_named_by_the_model(self):
        query = "创建一个 test.py 里面添加一个函数 add，用于计算两个整数的和"

        with mock.patch.object(task_runtime, "_summarize", return_value="加法函数") as summarize:
            task_runtime.update_task_name(self.task_id, "openai", None, query)

        summarize.assert_called_once()
        self.assertEqual("加法函数", self._name())

    def test_the_model_reply_is_cleaned_and_capped(self):
        query = "y" * 50

        with mock.patch.object(
            task_runtime,
            "build_provider",
            return_value=_FakeProvider('  "「' + "一" * 30 + '」"  '),
        ):
            task_runtime.update_task_name(self.task_id, "openai", None, query)

        name = self._name()
        self.assertEqual(task_runtime._TASK_NAME_MAX_LENGTH, len(name))
        self.assertFalse(name.startswith('"'))

    def test_a_line_break_in_the_query_does_not_reach_the_name(self):
        task_runtime.update_task_name(self.task_id, "openai", None, "第一行\n第二行")

        self.assertEqual("第一行 第二行", self._name())

    def test_an_empty_query_leaves_the_task_unnamed(self):
        task_runtime.update_task_name(self.task_id, "openai", None, "   ")

        self.assertEqual("", self._name())


if __name__ == "__main__":
    unittest.main()
