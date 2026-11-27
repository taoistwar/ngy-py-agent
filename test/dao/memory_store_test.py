"""Task store contracts for the cross-session memory library (``memory_*``, ADR 0035).

The name is the identity of a note, so the parts the tools and the page depend on are
pinned here: one row per name, a save replaces it, ``created_at`` survives the
replacement, and two notes never share a name.

Run from the repository root::

    uv run python test/dao/memory_store_test.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dao import _SqliteTaskStore  # noqa: E402


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_an_empty_library_reads_as_an_empty_list(self):
        self.assertEqual(self.store.list_memories(), [])
        self.assertEqual(self.store.count_memories(), 0)

    def test_a_memory_round_trips(self):
        record = self.store.upsert_memory(
            "user-prefers-tabs", "user", "User prefers tabs", "Use tabs, not spaces.", "task-1"
        )

        self.assertEqual(record["name"], "user-prefers-tabs")
        self.assertEqual(record["type"], "user")
        self.assertEqual(record["body"], "Use tabs, not spaces.")
        self.assertEqual(record["source_task_id"], "task-1")
        self.assertTrue(record["memory_id"])
        self.assertEqual(self.store.count_memories(), 1)

    def test_saving_the_same_name_replaces_the_note_and_keeps_when_it_was_learned(self):
        first = self.store.upsert_memory("auth-rewrite", "project", "Why", "Compliance.", "task-1")

        second = self.store.upsert_memory("auth-rewrite", "project", "Why", "Compliance, EU.", "task-2")

        self.assertEqual(self.store.count_memories(), 1)
        self.assertEqual(second["body"], "Compliance, EU.")
        self.assertEqual(second["memory_id"], first["memory_id"])
        self.assertEqual(second["created_at"], first["created_at"])
        self.assertEqual(second["source_task_id"], "task-2")

    def test_memories_are_listed_by_name_so_the_prompt_index_is_stable(self):
        for name in ("zeta", "alpha", "mike"):
            self.store.upsert_memory(name, "project", f"{name} note", f"{name} body")

        self.assertEqual([record["name"] for record in self.store.list_memories()], ["alpha", "mike", "zeta"])

    def test_lookup_by_name_is_what_a_save_then_edits(self):
        record = self.store.upsert_memory("tabs", "user", "Tabs", "Use tabs.")

        self.assertEqual(self.store.get_memory_by_name("tabs")["memory_id"], record["memory_id"])
        self.assertIsNone(self.store.get_memory_by_name("nope"))
        self.assertIsNone(self.store.get_memory(""))

    def test_an_update_changes_only_what_it_was_given(self):
        record = self.store.upsert_memory("tabs", "user", "Tabs", "Use tabs.")

        updated = self.store.update_memory(record["memory_id"], body="Use tabs everywhere.")

        self.assertEqual(updated["body"], "Use tabs everywhere.")
        self.assertEqual(updated["description"], "Tabs")
        self.assertEqual(updated["type"], "user")

    def test_a_rename_moves_the_note_rather_than_copying_it(self):
        record = self.store.upsert_memory("tabss", "user", "Tabs", "Use tabs.")

        updated = self.store.update_memory(record["memory_id"], name="tabs")

        self.assertEqual(updated["name"], "tabs")
        self.assertEqual(self.store.count_memories(), 1)
        self.assertIsNone(self.store.get_memory_by_name("tabss"))

    def test_updating_an_unknown_id_reads_as_missing(self):
        self.assertIsNone(self.store.update_memory("no-such-id", body="x"))

    def test_deleting_removes_exactly_one_note(self):
        keep = self.store.upsert_memory("keep", "project", "Keep", "keep body")
        drop = self.store.upsert_memory("drop", "project", "Drop", "drop body")

        self.assertTrue(self.store.delete_memory(drop["memory_id"]))
        self.assertFalse(self.store.delete_memory(drop["memory_id"]))
        self.assertEqual([record["memory_id"] for record in self.store.list_memories()], [keep["memory_id"]])

    def test_a_newer_database_gets_the_table_without_a_migration(self):
        # The table is created by ``_init_schema`` on every open, so an older file that
        # never had memories simply grows one; opening twice must not fail either.
        again = _SqliteTaskStore(Path(self._tmp.name) / "tasks.db")
        self.addCleanup(again.close)

        self.assertEqual(again.list_memories(), [])


if __name__ == "__main__":
    unittest.main()
