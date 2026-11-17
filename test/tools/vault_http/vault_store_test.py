"""Tests for the local secret store behind ``vault_http``.

Run from the repository root::

    uv run python test/tools/vault_http/vault_store_test.py -v

The store is a plain JSON file, so the tests are about the two contracts that
matter: which shapes are accepted, and what a failure looks like. A failure must
name the file and the key names and must never contain a value.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.vault_store import (  # noqa: E402
    REASON_SECRET_NOT_FOUND,
    REASON_VAULT_UNAVAILABLE,
    VAULT_FILE_ENV,
    VaultStore,
    VaultStoreError,
    default_vault_path,
)


class VaultStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "vault.json"
        self.store = VaultStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_the_wrapped_shape(self):
        self.write({"secrets": {"gh-token": "abc123"}})

        self.assertEqual(self.store.get("gh-token"), "abc123")

    def test_reads_a_bare_mapping_because_that_is_what_a_user_types(self):
        self.write({"gh-token": "abc123"})

        self.assertEqual(self.store.get("gh-token"), "abc123")

    def test_lists_names_sorted_and_never_values(self):
        self.write({"secrets": {"zeta": "v1", "alpha": "v2"}})

        self.assertEqual(self.store.names(), ["alpha", "zeta"])
        self.assertNotIn("v1", json.dumps(self.store.names()))

    def test_a_rotated_value_is_read_fresh(self):
        # Re-read per lookup: the API can write the file while a task is running.
        self.write({"secrets": {"gh-token": "old"}})
        self.assertEqual(self.store.get("gh-token"), "old")

        self.write({"secrets": {"gh-token": "new"}})
        self.assertEqual(self.store.get("gh-token"), "new")

    def test_an_unknown_key_is_reported_with_the_names_that_exist(self):
        self.write({"secrets": {"gh-token": "abc123", "billing": "def456"}})

        with self.assertRaises(VaultStoreError) as caught:
            self.store.get("typo")

        error = caught.exception
        self.assertEqual(error.reason, REASON_SECRET_NOT_FOUND)
        self.assertIn("gh-token", error.message)
        self.assertNotIn("abc123", error.message)
        self.assertNotIn("def456", json.dumps(error.to_dict()))

    def test_a_missing_file_explains_how_to_create_it(self):
        with self.assertRaises(VaultStoreError) as caught:
            self.store.get("gh-token")

        error = caught.exception
        self.assertEqual(error.reason, REASON_VAULT_UNAVAILABLE)
        self.assertIn(VAULT_FILE_ENV, error.message)
        self.assertIn("vault.json", error.message)

    def test_invalid_json_is_an_error_not_an_empty_vault(self):
        self.path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(VaultStoreError) as caught:
            self.store.get("gh-token")

        self.assertEqual(caught.exception.reason, REASON_VAULT_UNAVAILABLE)

    def test_non_string_values_are_skipped_instead_of_served(self):
        # A number or an object is a configuration mistake; sending it would put
        # something unintended on the wire.
        self.write({"secrets": {"gh-token": 1234, "other": {"value": "x"}, "ok": "abc"}})

        self.assertEqual(self.store.names(), ["ok"])
        with self.assertRaises(VaultStoreError):
            self.store.get("gh-token")

    def test_an_empty_vault_says_it_is_empty(self):
        self.write({"secrets": {}})

        with self.assertRaises(VaultStoreError) as caught:
            self.store.get("gh-token")

        self.assertIn("empty", caught.exception.message)

    def test_the_path_env_override_wins(self):
        os.environ[VAULT_FILE_ENV] = str(self.root / "elsewhere.json")
        self.addCleanup(os.environ.pop, VAULT_FILE_ENV, None)

        self.assertEqual(default_vault_path(), self.root / "elsewhere.json")


if __name__ == "__main__":
    unittest.main()
