"""Tests for the ``vault`` permission kind (ADR 0030).

Run from the repository root::

    uv run python test/tools/vault_permission_test.py -v

Three properties make this kind different from every other one, and each fails
silently if it regresses:

* the rule key is ``key@host`` (port included), so approving one credential for one
  service cannot approve it anywhere else;
* ``auto_approve`` does **not** skip the question - a standing "yes to everything"
  was not a decision about sending a credential;
* a non-HTTPS target is never asked about, because the tool refuses it outright.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import ToolOutcome  # noqa: E402
from agent.tools.permission_rules import PermissionRuleStore  # noqa: E402
from agent.tools.permissions import (  # noqa: E402
    PERMISSION_VAULT,
    REASON_TIMEOUT,
    SCOPE_SESSION,
    PermissionBroker,
    PermissionMode,
    is_sensitive_path,
)
from agent.tools.registry import ToolRegistry  # noqa: E402

_CALL = {
    "url": "https://api.example.com/v1/users",
    "vault_auth_key": "gh-token",
    "reason": "list users for the ticket",
}


class VaultPermissionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.events = []
        self.broker = PermissionBroker(
            task_id="task-1",
            emit=lambda category, title, data: self.events.append((category, title, data)),
            base_dir=str(self.root),
            wait_seconds=0.3,
            rules=PermissionRuleStore(path=self.root / "rules.json"),
            mode=PermissionMode.ASK,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def requests(self):
        return [event for event in self.events if event[0] == "permission_request"]

    def decisions(self):
        return [event for event in self.events if event[0] == "permission_decision"]

    def call_in_thread(self, arguments, broker=None):
        box = {}
        target_broker = broker or self.broker

        def runner():
            box["result"] = target_broker.check(
                "vault_http", PERMISSION_VAULT, dict(arguments), always_ask=True
            )

        thread = threading.Thread(target=runner)
        thread.start()
        return thread, box

    def answer(self, allowed=True, scope="once", timeout=5.0, broker=None):
        target_broker = broker or self.broker
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = target_broker.pending()
            if pending is not None:
                return target_broker.resolve(pending.request_id, allowed, scope)
            time.sleep(0.01)
        raise AssertionError("the broker never asked")

    def test_the_target_is_the_key_and_the_host(self):
        thread, _box = self.call_in_thread(_CALL)
        self.answer(allowed=False)
        thread.join(timeout=5.0)

        payload = self.requests()[0][2]
        self.assertEqual(payload["target"], "gh-token@api.example.com")
        self.assertEqual(payload["details"]["url"], _CALL["url"])
        self.assertEqual(payload["details"]["method"], "GET")
        self.assertEqual(payload["details"]["purpose"], _CALL["reason"])
        self.assertEqual(payload["details"]["reason"], "network_vault")
        self.assertIn("gh-token", payload["summary"])

    def test_the_port_is_part_of_the_target(self):
        thread, _box = self.call_in_thread(
            {**_CALL, "url": "https://api.example.com:8443/v1/users"}
        )
        self.answer(allowed=False)
        thread.join(timeout=5.0)

        self.assertEqual(self.requests()[0][2]["target"], "gh-token@api.example.com:8443")

    def test_the_default_port_is_not(self):
        thread, _box = self.call_in_thread({**_CALL, "url": "https://api.example.com:443/x"})
        self.answer(allowed=False)
        thread.join(timeout=5.0)

        self.assertEqual(self.requests()[0][2]["target"], "gh-token@api.example.com")

    def test_a_session_approval_covers_that_key_on_that_host_only(self):
        thread, _box = self.call_in_thread(_CALL)
        self.answer(allowed=True, scope=SCOPE_SESSION)
        thread.join(timeout=5.0)

        same = self.broker.check(
            "vault_http", PERMISSION_VAULT, {**_CALL, "reason": "another endpoint"}, always_ask=True
        )
        self.assertIsNone(same)
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(self.decisions()[-1][2]["reason"], "session_rule")

        # A different host needs its own approval: the key must not travel there.
        other_host = self.call_in_thread({**_CALL, "url": "https://other.example.com/v1"})
        self.answer(allowed=False)
        other_host[0].join(timeout=5.0)

        # So does a different key on the approved host.
        other_key = self.call_in_thread({**_CALL, "vault_auth_key": "billing-api"})
        self.answer(allowed=False)
        other_key[0].join(timeout=5.0)

        self.assertEqual(len(self.requests()), 3)

    def test_auto_approve_does_not_answer_this_question(self):
        broker = PermissionBroker(
            task_id="task-1",
            emit=lambda category, title, data: self.events.append((category, title, data)),
            base_dir=str(self.root),
            wait_seconds=0.3,
            rules=PermissionRuleStore(path=self.root / "rules.json"),
            mode=PermissionMode.AUTO_APPROVE,
        )

        thread, box = self.call_in_thread(_CALL, broker=broker)
        self.answer(allowed=True, broker=broker)
        thread.join(timeout=5.0)

        self.assertEqual(len(self.requests()), 1, "auto_approve must still ask")
        self.assertIsNone(box["result"])

    def test_auto_approve_still_covers_the_ordinary_tools(self):
        broker = PermissionBroker(
            mode=PermissionMode.AUTO_APPROVE,
            rules=PermissionRuleStore(path=self.root / "rules.json"),
        )

        self.assertIsNone(
            broker.check("exec_command", "exec", {"command": "ls"}, always_ask=False)
        )
        self.assertEqual(self.requests(), [])

    def test_nobody_answering_means_no(self):
        denial = self.broker.check("vault_http", PERMISSION_VAULT, dict(_CALL), always_ask=True)

        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], REASON_TIMEOUT)
        self.assertEqual(denial.details["kind"], PERMISSION_VAULT)
        self.assertIn("Do not retry", denial.model_text)

    def test_a_plain_http_url_is_not_asked_about(self):
        denial = self.broker.check(
            "vault_http",
            PERMISSION_VAULT,
            {**_CALL, "url": "http://api.example.com/v1"},
            always_ask=True,
        )

        self.assertIsNone(denial, "the tool refuses it; no dialog for an impossible call")
        self.assertEqual(self.requests(), [])

    def test_the_vault_file_is_a_sensitive_read(self):
        self.assertTrue(is_sensitive_path(self.root / "data" / "vault.json"))


class VaultRegistryTest(unittest.TestCase):
    def test_the_catalog_declares_the_vault_gate_and_the_approval_is_bypass_immune(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = ToolRegistry(base_dir=str(root), enabled_tools=["vault_http"])

            self.assertEqual(registry.tools["vault_http"]["permission"], PERMISSION_VAULT)
            self.assertTrue(registry.tools["vault_http"]["always_confirm"])

            # Auto-approve plus a short wait: the call must still ask, time out, and
            # come back as a refusal the model can read - not run silently.
            registry.permission_broker = PermissionBroker(
                mode=PermissionMode.AUTO_APPROVE,
                wait_seconds=0.05,
                rules=PermissionRuleStore(path=root / "rules.json"),
            )
            result = registry.execute_tool(
                "vault_http",
                {"url": _CALL["url"], "vault_auth_key": "gh-token", "reason": "x"},
            )

        self.assertIsInstance(result, ToolOutcome)
        self.assertEqual(result.details["reason"], REASON_TIMEOUT)
        self.assertIn("vault_http", result.model_text)


if __name__ == "__main__":
    unittest.main()
