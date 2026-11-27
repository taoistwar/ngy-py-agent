"""Tests for the memory endpoints behind the Memory page (``routes/memory_api.py``).

Two things are pinned here beyond the status codes: a page edit and an agent write are
the same store (so a wrong note the model kept can be corrected by hand), and the
config PUT takes effect on the next run rather than on the next restart.

Run from the repository root::

    uv run python test/memory_api_test.py -v

The process-wide task store is swapped for a temporary one so nothing here reads or
writes the developer's own memory library.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent.tools.memory_notes import MAX_MEMORIES  # noqa: E402
from commons import state  # noqa: E402
from dao import _SqliteTaskStore  # noqa: E402

NOTE = {
    "name": "user-prefers-tabs",
    "type": "user",
    "description": "User prefers tabs for indentation",
    "body": "Use tabs, not spaces, in Python files.",
}


class MemoryApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        # The routes read the live state from ``commons.state``, so that is where a
        # test has to swap it (see commons.state's module docstring).
        self._previous_store = state.monitor_store
        self._previous_config = (
            state.memories_enabled,
            state.memories_auto_extract,
            state.memories_max_prompt_chars,
            state.memories_source,
        )
        self.store = _SqliteTaskStore(root / "tasks.db")
        state.monitor_store = self.store
        state.memories_enabled = True
        state.memories_auto_extract = True
        state.memories_max_prompt_chars = 4000
        state.memories_source = "default"
        self.client = TestClient(main.app)

    def tearDown(self):
        state.monitor_store = self._previous_store
        (
            state.memories_enabled,
            state.memories_auto_extract,
            state.memories_max_prompt_chars,
            state.memories_source,
        ) = self._previous_config
        self.store.close()
        self._tmp.cleanup()

    def create(self, **overrides):
        payload = {**NOTE, **overrides}
        return self.client.post("/api/memories", json=payload)

    def list_payload(self):
        response = self.client.get("/api/memories")
        self.assertEqual(response.status_code, 200)
        return response.json()

    # -------------------------------------------------------------------- tests

    def test_the_page_starts_empty_and_says_the_library_is_on(self):
        payload = self.list_payload()

        self.assertEqual(payload["memories"], [])
        self.assertEqual(payload["total"], 0)
        self.assertTrue(payload["enabled"])
        self.assertTrue(payload["auto_extract"])

    def test_a_created_memory_is_listed(self):
        response = self.create()

        self.assertEqual(response.status_code, 200)
        record = response.json()
        self.assertEqual(record["name"], "user-prefers-tabs")
        self.assertEqual(record["type"], "user")
        self.assertTrue(record["memory_id"])
        self.assertEqual(self.list_payload()["total"], 1)

    def test_the_name_is_normalized_into_the_key_a_save_replaces(self):
        record = self.create(name="User Prefers Tabs!").json()

        self.assertEqual(record["name"], "user-prefers-tabs")

    def test_saving_an_existing_name_replaces_it(self):
        self.create()
        self.create(body="Use tabs everywhere, including YAML.")

        payload = self.list_payload()

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["memories"][0]["body"], "Use tabs everywhere, including YAML.")

    def test_an_unknown_type_is_rejected(self):
        self.assertEqual(self.create(type="gut-feeling").status_code, 422)

    def test_a_name_without_letters_is_rejected(self):
        self.assertEqual(self.create(name="!!!").status_code, 400)

    def test_a_full_library_refuses_a_new_name(self):
        for index in range(MAX_MEMORIES):
            self.store.upsert_memory(f"note-{index}", "project", f"note {index}", f"body {index}")

        response = self.create()

        self.assertEqual(response.status_code, 409)
        self.assertIn("delete one first", response.json()["detail"])

    def test_an_update_changes_only_the_field_it_was_given(self):
        record = self.create().json()

        response = self.client.put(
            f"/api/memories/{record['memory_id']}", json={"body": "Tabs in YAML too."}
        )

        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["body"], "Tabs in YAML too.")
        self.assertEqual(updated["description"], NOTE["description"])

    def test_renaming_onto_another_note_is_a_conflict(self):
        first = self.create().json()
        self.create(name="other-note", body="a different note")

        response = self.client.put(f"/api/memories/{first['memory_id']}", json={"name": "other-note"})

        self.assertEqual(response.status_code, 409)

    def test_renaming_a_note_moves_it(self):
        record = self.create(name="tabss").json()

        response = self.client.put(f"/api/memories/{record['memory_id']}", json={"name": "tabs"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "tabs")
        self.assertEqual(self.list_payload()["total"], 1)

    def test_updating_an_unknown_id_is_a_404(self):
        response = self.client.put("/api/memories/no-such-id", json={"body": "x"})

        self.assertEqual(response.status_code, 404)

    def test_deleting_a_memory_removes_it(self):
        record = self.create().json()

        self.assertEqual(self.client.delete(f"/api/memories/{record['memory_id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/memories/{record['memory_id']}").status_code, 404)
        self.assertEqual(self.list_payload()["total"], 0)

    def test_the_config_round_trips_and_is_live_for_the_next_run(self):
        response = self.client.put(
            "/api/admin/memory-config",
            json={"enabled": False, "auto_extract": False, "max_prompt_chars": 900},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertEqual(response.json()["source"], "database")
        self.assertFalse(state.memories_enabled)
        self.assertFalse(state.memories_auto_extract)
        self.assertEqual(state.memories_max_prompt_chars, 900)
        self.assertEqual(self.client.get("/api/admin/memory-config").json()["max_prompt_chars"], 900)

    def test_the_prompt_budget_has_a_ceiling(self):
        response = self.client.put(
            "/api/admin/memory-config",
            json={"enabled": True, "auto_extract": True, "max_prompt_chars": 999999},
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
