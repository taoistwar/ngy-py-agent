"""How a task and its session get the short labels the lists show.

A query that already fits in the name length is its own name; anything longer is
summarized by the model, and the fallback keeps the name on one line when the
model is unavailable. The session is named by its first task only: a follow-up
continues that thread, so it must not relabel the session.

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

from agent.runtime import naming  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402


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
        self._previous_store = state.monitor_store
        state.monitor_store = self.store
        self.task_id = self.store.create_task("placeholder", "openai")

    def tearDown(self):
        state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _name(self):
        return self.store.get_task(self.task_id)["name"]

    def test_a_short_query_is_its_own_name(self):
        with mock.patch.object(naming, "_summarize") as summarize:
            naming.update_task_name(self.task_id, "openai", None, "统计一下日志")

        summarize.assert_not_called()
        self.assertEqual("统计一下日志", self._name())

    def test_a_query_of_exactly_the_limit_is_not_summarized(self):
        query = "x" * naming._TASK_NAME_MAX_LENGTH

        with mock.patch.object(naming, "_summarize") as summarize:
            naming.update_task_name(self.task_id, "openai", None, query)

        summarize.assert_not_called()
        self.assertEqual(query, self._name())

    def test_a_long_query_is_named_by_the_model(self):
        query = "创建一个 test.py 里面添加一个函数 add，用于计算两个整数的和"

        with mock.patch.object(naming, "_summarize", return_value="加法函数") as summarize:
            naming.update_task_name(self.task_id, "openai", None, query)

        summarize.assert_called_once()
        self.assertEqual("加法函数", self._name())

    def test_the_model_reply_is_cleaned_and_capped(self):
        query = "y" * 50

        with mock.patch.object(
            naming,
            "build_provider",
            return_value=_FakeProvider('  "「' + "一" * 30 + '」"  '),
        ):
            naming.update_task_name(self.task_id, "openai", None, query)

        name = self._name()
        self.assertEqual(naming._TASK_NAME_MAX_LENGTH, len(name))
        self.assertFalse(name.startswith('"'))

    def test_a_line_break_in_the_query_does_not_reach_the_name(self):
        naming.update_task_name(self.task_id, "openai", None, "第一行\n第二行")

        self.assertEqual("第一行 第二行", self._name())

    def test_an_empty_query_leaves_the_task_unnamed(self):
        naming.update_task_name(self.task_id, "openai", None, "   ")

        self.assertEqual("", self._name())


class SessionNamingTest(unittest.TestCase):
    """The session is named once, by the task that opened it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self._previous_store = state.monitor_store
        state.monitor_store = self.store

    def tearDown(self):
        state.monitor_store = self._previous_store
        self._tmp.cleanup()

    def _session_name(self, session_id):
        return self.store.get_session(session_id)["name"]

    def test_the_first_task_names_the_session(self):
        session_id = self.store.create_session(naming.default_session_name())
        task_id = self.store.create_task("placeholder", "openai", session_id=session_id)
        query = "创建一个 test.py 里面添加一个函数 add，用于计算两个整数的和"

        with mock.patch.object(
            naming,
            "build_provider",
            side_effect=[_FakeProvider("加法函数"), _FakeProvider("加法需求")],
        ):
            naming.name_task_and_session(task_id, session_id, "openai", None, query)

        self.assertEqual("加法函数", self.store.get_task(task_id)["name"])
        self.assertEqual("加法需求", self._session_name(session_id))

    def test_a_follow_up_task_does_not_rename_the_session(self):
        session_id = self.store.create_session("登录页改造")
        self.store.create_task("第一个任务", "openai", session_id=session_id)
        task_id = self.store.create_task("第二个任务", "openai", session_id=session_id)

        with mock.patch.object(naming, "build_provider") as build_provider:
            naming.name_task_and_session(task_id, session_id, "openai", None, "第二个任务")

        build_provider.assert_not_called()
        self.assertEqual("登录页改造", self._session_name(session_id))
        self.assertEqual("第二个任务", self.store.get_task(task_id)["name"])

    def test_a_follow_up_task_is_named_without_asking_for_a_session_title(self):
        session_id = self.store.create_session("登录页改造")
        self.store.create_task("第一个任务", "openai", session_id=session_id)
        task_id = self.store.create_task("第二个任务", "openai", session_id=session_id)
        query = "把登录页的按钮改成主色并且给表单加上回车提交"

        with mock.patch.object(
            naming, "build_provider", return_value=_FakeProvider("登录按钮")
        ) as build_provider:
            naming.name_task_and_session(task_id, session_id, "openai", None, query)

        self.assertEqual(1, build_provider.call_count)
        self.assertEqual("登录页改造", self._session_name(session_id))
        self.assertEqual("登录按钮", self.store.get_task(task_id)["name"])

    def test_a_task_without_a_session_is_only_named(self):
        task_id = self.store.create_task("placeholder", "openai")

        naming.name_task_and_session(task_id, None, "openai", None, "统计一下日志")

        self.assertEqual("统计一下日志", self.store.get_task(task_id)["name"])


if __name__ == "__main__":
    unittest.main()
