"""Task store contracts: list order, task names, and the provider migration.

The web admin renders the list top to bottom, so the store hands the tasks back
oldest first. That is a contract the UI depends on, which is why it is pinned
here instead of being left to whatever order the query happens to produce.

The last group covers the one-time split of the legacy ``models`` table into
providers plus models (ADR 0014): an existing database must keep working.

Run from the repository root::

    uv run python test/task_store_test.py -v
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from task_store import _SqliteTaskStore  # noqa: E402

# The models table as it was before providers existed (ADR 0014): the endpoint sat on
# every model, so two models on one server were two rows with the same URL and key.
_LEGACY_MODELS_TABLE = """
CREATE TABLE models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '',
    supports_tool_calls INTEGER NOT NULL DEFAULT 1,
    supports_image_input INTEGER NOT NULL DEFAULT 0,
    thinking_mode INTEGER NOT NULL DEFAULT 0,
    max_input_tokens INTEGER NOT NULL DEFAULT 0,
    max_output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class TaskListOrderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")

    def tearDown(self):
        self._tmp.cleanup()

    def _create_task(self, query: str, created_at: str) -> str:
        """Create a task and pin its creation time, so the order is not wall-clock luck."""
        task_id = self.store.create_task(query, "openai")
        self.store._conn.execute(
            "UPDATE tasks SET created_at = ? WHERE task_id = ?",
            (created_at, task_id),
        )
        self.store._conn.commit()
        return task_id

    def test_the_list_is_oldest_first(self):
        newer = self._create_task("second", "2026-10-22T06:00:00+00:00")
        older = self._create_task("first", "2026-10-22T04:00:00+00:00")

        order = [task["task_id"] for task in self.store.list_tasks()]

        self.assertEqual([older, newer], order)

    def test_the_session_scoped_list_is_oldest_first(self):
        newer = self._create_task("second", "2026-10-22T06:00:00+00:00")
        older = self._create_task("first", "2026-10-22T04:00:00+00:00")
        session_id = self.store.ensure_default_session()

        order = [
            task["task_id"]
            for task in self.store.list_tasks(session_id=session_id)
        ]

        self.assertEqual([older, newer], order)


class TaskNameTest(unittest.TestCase):
    """The list shows a task name; the raw query stays available for the detail view."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_new_task_has_no_name_yet(self):
        task_id = self.store.create_task("build a report", "openai")

        self.assertEqual("", self.store.get_task(task_id)["name"])
        self.assertEqual("", self.store.list_tasks()[0]["name"])

    def test_the_name_survives_in_both_read_paths(self):
        task_id = self.store.create_task("build a report", "openai")

        self.store.set_task_name(task_id, "report draft")

        self.assertEqual("report draft", self.store.get_task(task_id)["name"])
        self.assertEqual("report draft", self.store.list_tasks()[0]["name"])
        self.assertEqual("build a report", self.store.get_task(task_id)["query"])

    def test_naming_a_missing_task_is_a_no_op(self):
        self.assertFalse(self.store.set_task_name("missing-task", "name"))


class ProviderMigrationTest(unittest.TestCase):
    """A database written before providers existed must keep its models usable."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = Path(self._tmp.name) / "tasks.db"
        self._write_legacy_models()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_legacy_models(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(_LEGACY_MODELS_TABLE)
        rows = [
            ("m1", "qwen3:0.6b", "openai-compatible", "http://127.0.0.1:11434/v1", "k"),
            ("m2", "qwen3:8b", "openai", "http://127.0.0.1:11434/v1", "k"),
            ("m3", "claude", "anthropic", "", "a"),
        ]
        for model_id, name, provider, base_url, api_key in rows:
            conn.execute(
                """
                INSERT INTO models (
                    model_id, name, provider, base_url, api_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    name,
                    provider,
                    base_url,
                    api_key,
                    "2026-10-20T00:00:00+00:00",
                    "2026-10-20T00:00:00+00:00",
                ),
            )
        conn.commit()
        conn.close()

    def test_models_are_grouped_by_the_endpoint_they_used(self):
        store = _SqliteTaskStore(self._db_path)
        self.addCleanup(store.close)

        providers = store.llm.list_providers()
        models = {item["model_id"]: item for item in store.llm.list_models()}

        # Two spellings of the same Ollama endpoint collapse into one provider, which
        # is also the new unit of the RPM budget.
        self.assertEqual(2, len(providers))
        self.assertEqual(
            models["m1"]["provider_id"],
            models["m2"]["provider_id"],
        )
        self.assertNotEqual(
            models["m1"]["provider_id"],
            models["m3"]["provider_id"],
        )
        by_id = {provider["provider_id"]: provider for provider in providers}
        self.assertEqual("openai", by_id[models["m1"]["provider_id"]]["protocol"])
        self.assertEqual("http://127.0.0.1:11434/v1", by_id[models["m1"]["provider_id"]]["base_url"])
        self.assertEqual("anthropic", by_id[models["m3"]["provider_id"]]["protocol"])

    def test_the_limits_start_unlimited(self):
        store = _SqliteTaskStore(self._db_path)
        self.addCleanup(store.close)

        self.assertEqual(
            [0] * 2,
            [provider["rpm_limit"] for provider in store.llm.list_providers()],
        )


if __name__ == "__main__":
    unittest.main()
