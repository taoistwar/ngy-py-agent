"""Tests for the interactive tool permission gate (ADR 0006).

Run from the repository root::

    uv run python test/tools/permissions_test.py -v

The point of these tests is the behaviour that makes the gate worth having, not
the plumbing: refusals come back as *results* rather than exceptions, nobody
answering means no, a stop beats the timeout, the static policy is never asked
about, and a tool that cannot reach the filesystem never reaches the broker.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import ToolOutcome  # noqa: E402
from agent.tools.file_access import FileAccessConfig  # noqa: E402
from agent.tools.file_edit_tool import EditFileError, make_edit_preview  # noqa: E402
from agent.tools.permission_rules import PermissionRuleStore  # noqa: E402
from agent.tools.permissions import (  # noqa: E402
    PERMISSION_EXEC,
    PERMISSION_NONE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    REASON_AUTO_APPROVED,
    REASON_DENY_ALL,
    REASON_PERSISTENT_RULE,
    REASON_SESSION_RULE,
    REASON_STOPPED,
    REASON_TIMEOUT,
    REASON_USER_ALLOWED,
    REASON_USER_DENIED,
    SCOPE_ALWAYS,
    SCOPE_SESSION,
    PermissionBroker,
    PermissionMode,
    is_sensitive_path,
)
from agent.tools.registry import ToolRegistry  # noqa: E402


class SensitivePathTest(unittest.TestCase):
    """Reads are questioned on the file that is the risk, not on every read."""

    def test_credential_and_key_names_are_sensitive(self):
        for name in (
            ".env",
            ".env.local",
            "id_rsa",
            "id_ed25519.pub",
            "server.pem",
            "private.key",
            "keystore.p12",
            ".git-credentials",
            "secrets.yaml",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_sensitive_path(Path("/w") / name))

    def test_files_inside_credential_directories_are_sensitive(self):
        self.assertTrue(is_sensitive_path(Path("/w/.ssh/config")))
        self.assertTrue(is_sensitive_path(Path("/w/.aws/config")))

    def test_ordinary_project_files_are_not_sensitive(self):
        for name in ("main.py", "env.py", "notes.md", "keyboard.js", "settings.json"):
            with self.subTest(name=name):
                self.assertFalse(is_sensitive_path(Path("/w") / name))


class PermissionBrokerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.events = []

    def tearDown(self):
        self._tmp.cleanup()

    def make_broker(self, **overrides) -> PermissionBroker:
        options = {
            "task_id": "task-1",
            "emit": lambda category, title, data: self.events.append((category, title, data)),
            "base_dir": str(self.root),
            "wait_seconds": 0.3,
        }
        options.update(overrides)
        return PermissionBroker(**options)

    def categories(self):
        return [event[0] for event in self.events]

    def requests(self):
        return [event for event in self.events if event[0] == "permission_request"]

    def decisions(self):
        return [event for event in self.events if event[0] == "permission_decision"]

    # ------------------------------------------------------------ no question

    def test_tools_without_a_kind_never_ask(self):
        broker = self.make_broker()

        self.assertIsNone(broker.check("get_current_time", PERMISSION_NONE, {}))
        self.assertEqual(self.events, [])

    def test_ordinary_read_is_not_worth_interrupting_the_user_for(self):
        broker = self.make_broker()

        decision = broker.check("read_file", PERMISSION_READ, {"file_path": "notes.txt"})

        self.assertIsNone(decision)
        self.assertEqual(self.requests(), [])

    def test_policy_denied_path_is_not_asked_about(self):
        blocked = self.root / "blocked.txt"
        blocked.write_text("x", encoding="utf-8")
        config = FileAccessConfig(deny_files=(blocked.resolve(),))
        broker = self.make_broker(access_config=config)

        decision = broker.check("write_file", PERMISSION_WRITE, {"file_path": "blocked.txt"})

        # ``None`` means "carry on", so the tool raises its own canonical
        # AccessDenied error. Asking first would imply the answer could be yes.
        self.assertIsNone(decision)
        self.assertEqual(self.requests(), [])

    def test_read_outside_the_workspace_is_left_to_the_policy(self):
        outside = self.root.parent / "elsewhere.txt"
        broker = self.make_broker()

        decision = broker.check("read_file", PERMISSION_READ, {"file_path": str(outside)})

        self.assertIsNone(decision)
        self.assertEqual(self.requests(), [])

    def test_scratch_output_root_does_not_count_as_outside_the_workspace(self):
        scratch = self.root.parent / "ngy-scratch"
        broker = self.make_broker(extra_read_roots=(str(scratch),))

        decision = broker.check(
            "read_file", PERMISSION_READ, {"file_path": str(scratch / "output.txt")}
        )

        self.assertIsNone(decision)
        self.assertEqual(self.requests(), [])

    def test_auto_approve_never_asks_but_records_the_decision(self):
        broker = self.make_broker(mode=PermissionMode.AUTO_APPROVE)

        decision = broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        self.assertIsNone(decision)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.decisions()[0][2]["reason"], REASON_AUTO_APPROVED)

    # -------------------------------------------------------------- refusals

    def test_deny_all_refuses_without_asking(self):
        broker = self.make_broker(mode=PermissionMode.DENY_ALL)

        denial = broker.check("exec", PERMISSION_EXEC, {"command": "rm -rf build"})

        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], REASON_DENY_ALL)
        self.assertEqual(denial.details["kind"], PERMISSION_EXEC)
        self.assertEqual(self.requests(), [])

    def test_nobody_answering_means_no(self):
        (self.root / ".env").write_text("SECRET=1", encoding="utf-8")
        broker = self.make_broker()

        denial = broker.check("read_file", PERMISSION_READ, {"file_path": ".env"})

        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], REASON_TIMEOUT)
        self.assertEqual(len(self.requests()), 1)
        self.assertIn(REASON_TIMEOUT, denial.model_text)
        # The model must be told not to hammer the same call.
        self.assertIn("Do not retry", denial.model_text)

    def test_sensitive_read_does_ask(self):
        (self.root / ".env").write_text("SECRET=1", encoding="utf-8")
        broker = self.make_broker()

        broker.check("read_file", PERMISSION_READ, {"file_path": ".env"})

        payload = self.requests()[0][2]
        self.assertEqual(payload["tool"], "read_file")
        self.assertEqual(payload["details"]["reason"], "sensitive_path")
        self.assertTrue(payload["target"].endswith(".env"))

    def test_stop_releases_the_wait_instead_of_hanging_until_timeout(self):
        broker = self.make_broker(wait_seconds=30.0, should_stop=lambda: True)

        started = time.monotonic()
        denial = broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})
        elapsed = time.monotonic() - started

        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], REASON_STOPPED)
        self.assertLess(elapsed, 5.0, "a stop must not wait for the timeout")

    # ------------------------------------------------- answering from another thread

    def answer_next_request(self, broker, allowed=True, scope="once", timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = broker.pending()
            if pending is not None:
                return broker.resolve(pending.request_id, allowed, scope)
            time.sleep(0.01)
        raise AssertionError("the broker never asked")

    def run_in_thread(self, func):
        box = {}

        def runner():
            box["result"] = func()

        thread = threading.Thread(target=runner)
        thread.start()
        return thread, box

    def test_allow_once_runs_the_call(self):
        broker = self.make_broker()
        call = lambda: broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        thread, box = self.run_in_thread(call)
        self.assertTrue(self.answer_next_request(broker, allowed=True))
        thread.join(timeout=5.0)

        self.assertIsNone(box["result"])
        self.assertEqual(self.decisions()[0][2]["reason"], REASON_USER_ALLOWED)
        self.assertIsNone(broker.pending())

    def test_refusal_is_reported_to_the_model_instead_of_raising(self):
        broker = self.make_broker()
        call = lambda: broker.check("exec", PERMISSION_EXEC, {"command": "git push --force"})

        thread, box = self.run_in_thread(call)
        self.answer_next_request(broker, allowed=False)
        thread.join(timeout=5.0)

        denial = box["result"]
        self.assertIsNotNone(denial)
        self.assertEqual(denial.details["reason"], REASON_USER_DENIED)
        self.assertIn(REASON_USER_DENIED, denial.model_text)

    def test_session_scope_answers_the_next_call_without_asking_again(self):
        broker = self.make_broker()
        call = lambda: broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        thread, box = self.run_in_thread(call)
        self.answer_next_request(broker, allowed=True, scope=SCOPE_SESSION)
        thread.join(timeout=5.0)

        second = broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        self.assertIsNone(box["result"])
        self.assertIsNone(second)
        self.assertEqual(len(self.requests()), 1, "the second call must not ask again")
        self.assertEqual(self.decisions()[-1][2]["reason"], REASON_SESSION_RULE)

    def test_session_scope_is_per_target(self):
        broker = self.make_broker()
        call = lambda: broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        thread, box = self.run_in_thread(call)
        self.answer_next_request(broker, allowed=True, scope=SCOPE_SESSION)
        thread.join(timeout=5.0)

        other = lambda: broker.check("edit_file", PERMISSION_WRITE, {"file_path": "other.txt"})
        thread2, box2 = self.run_in_thread(other)
        self.answer_next_request(broker, allowed=False)
        thread2.join(timeout=5.0)

        self.assertEqual(len(self.requests()), 2, "a different file must be asked about")
        self.assertIsNotNone(box2["result"])

    def test_teardown_does_not_overwrite_an_answer_that_already_arrived(self):
        broker = self.make_broker(wait_seconds=30.0)
        call = lambda: broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        thread, box = self.run_in_thread(call)
        self.answer_next_request(broker, allowed=True)
        # Task teardown can land in the same instant as the user's click; an
        # approved call must not be turned into a refusal by it.
        broker.cancel_all(REASON_STOPPED)
        thread.join(timeout=5.0)

        self.assertIsNone(box["result"], "an approved call must still run")
        self.assertEqual(self.decisions()[0][2]["reason"], REASON_USER_ALLOWED)

    def test_cancel_all_releases_a_waiting_call_as_stopped(self):
        broker = self.make_broker(wait_seconds=30.0)
        call = lambda: broker.check("edit_file", PERMISSION_WRITE, {"file_path": "notes.txt"})

        thread, box = self.run_in_thread(call)
        deadline = time.monotonic() + 5.0
        while broker.pending() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        broker.cancel_all(REASON_STOPPED)
        thread.join(timeout=5.0)

        self.assertEqual(box["result"].details["reason"], REASON_STOPPED)

    def test_pending_is_none_when_nothing_is_waiting(self):
        self.assertIsNone(self.make_broker().pending())


class ExplodingBroker:
    """A broker that is broken on purpose."""

    def check(self, *args, **kwargs):
        raise RuntimeError("permission subsystem broke")

    def pending(self):
        return None


class RegistryGateTest(unittest.TestCase):
    """The gate sits on the single dispatch choke point, not inside tools."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.registry = ToolRegistry(base_dir=str(self.root), enabled_tools=[])
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def register_probe(self, name="probe", permission=PERMISSION_WRITE):
        def probe(**kwargs):
            self.calls.append(kwargs)
            return {"ok": True}

        self.registry.register_tool(
            name=name, function=probe, description="", parameters={}, permission=permission
        )

    def test_without_a_broker_nothing_is_gated(self):
        self.register_probe()

        result = self.registry.execute_tool("probe", {"file_path": "notes.txt"})

        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(len(self.calls), 1)

    def test_denied_call_is_not_invoked_and_returns_an_outcome(self):
        self.register_probe()
        self.registry.permission_broker = PermissionBroker(mode=PermissionMode.DENY_ALL)

        result = self.registry.execute_tool("probe", {"file_path": "notes.txt"})

        self.assertIsInstance(result, ToolOutcome)
        self.assertEqual(result.details["reason"], REASON_DENY_ALL)
        self.assertEqual(result.details["allowed"], False)
        self.assertIn("probe", result.model_text)
        self.assertEqual(self.calls, [], "a denied call must never reach the tool")

    def test_ungated_tool_never_reaches_a_broken_broker(self):
        self.register_probe(name="lookup", permission=PERMISSION_NONE)
        self.registry.permission_broker = ExplodingBroker()

        result = self.registry.execute_tool("lookup", {})

        self.assertEqual(result, '{"ok": true}')

    def test_a_broken_broker_denies_rather_than_letting_everything_through(self):
        self.register_probe()
        self.registry.permission_broker = ExplodingBroker()

        result = self.registry.execute_tool("probe", {"file_path": "notes.txt"})

        self.assertIsInstance(result, ToolOutcome)
        self.assertEqual(result.details["reason"], "broker_error")
        self.assertEqual(self.calls, [])

    def test_declared_kinds_cover_every_tool_that_can_touch_the_machine(self):
        full = ToolRegistry(base_dir=str(self.root))

        expected = {
            "read_file": PERMISSION_READ,
            "edit_file": PERMISSION_WRITE,
            "write_file": PERMISSION_WRITE,
            "exec": PERMISSION_EXEC,
            # Without this, code_interpreter is an unrestricted bypass: it can
            # open() and subprocess.run() anything (ADR 0005 D1, ADR 0006 D2).
            "code_interpreter": PERMISSION_EXEC,
            "get_current_time": PERMISSION_NONE,
            "get_current_temperature": PERMISSION_NONE,
            "convert_currency": PERMISSION_NONE,
        }
        for name, kind in expected.items():
            with self.subTest(tool=name):
                self.assertIn(name, full.tools)
                self.assertEqual(full.tools[name]["permission"], kind)


class PermissionRuleTest(unittest.TestCase):
    """Persisted allow rules, which are narrow by construction."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rules = PermissionRuleStore(self.root / "rules.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_means_no_rules(self):
        self.assertEqual(self.rules.list(), [])
        self.assertFalse(self.rules.match("exec", "ls"))

    def test_add_then_match(self):
        self.assertTrue(self.rules.add("exec", "git status", "exec"))
        self.assertTrue(self.rules.match("exec", "git status"))

    def test_a_rule_does_not_cover_a_different_target_or_tool(self):
        self.rules.add("exec", "git status")

        self.assertFalse(self.rules.match("exec", "git status --short"))
        self.assertFalse(self.rules.match("exec", "git push --force"))
        self.assertFalse(self.rules.match("read_file", "git status"))

    def test_adding_a_duplicate_is_idempotent(self):
        self.rules.add("exec", "ls")
        self.assertTrue(self.rules.add("exec", "ls"))

        self.assertEqual(len(self.rules.list()), 1)

    def test_remove_forgets_the_rule(self):
        self.rules.add("exec", "ls")

        self.assertTrue(self.rules.remove("exec", "ls"))
        self.assertFalse(self.rules.remove("exec", "ls"))
        self.assertFalse(self.rules.match("exec", "ls"))

    def test_a_corrupt_file_degrades_to_asking_not_to_allowing(self):
        (self.root / "rules.json").write_text("{ not json", encoding="utf-8")

        self.assertEqual(self.rules.list(), [])
        self.assertFalse(self.rules.match("exec", "ls"))
        # ...and it recovers on the next add instead of staying broken.
        self.assertTrue(self.rules.add("exec", "ls"))
        self.assertTrue(self.rules.match("exec", "ls"))

    def test_a_rule_survives_a_new_store_instance(self):
        self.rules.add("exec", "ls")

        reopened = PermissionRuleStore(self.root / "rules.json")

        self.assertTrue(reopened.match("exec", "ls"))


class NoWriteRules:
    """A rule store that can never persist anything."""

    def match(self, tool, target):
        return False

    def add(self, tool, target, kind=""):
        return False


class PersistentRuleBrokerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.events = []
        self.rules = PermissionRuleStore(self.root / "rules.json")

    def tearDown(self):
        self._tmp.cleanup()

    def make_broker(self, **overrides):
        options = {
            "base_dir": str(self.root),
            "rules": self.rules,
            "emit": lambda category, title, data: self.events.append((category, title, data)),
            "wait_seconds": 0.3,
        }
        options.update(overrides)
        return PermissionBroker(**options)

    def decisions(self):
        return [event for event in self.events if event[0] == "permission_decision"]

    def answer_next_request(self, broker, allowed=True, scope="once", timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = broker.pending()
            if pending is not None:
                return broker.resolve(pending.request_id, allowed, scope)
            time.sleep(0.01)
        raise AssertionError("the broker never asked")

    def run_in_thread(self, func):
        box = {}

        def runner():
            box["result"] = func()

        thread = threading.Thread(target=runner)
        thread.start()
        return thread, box

    def test_always_scope_persists_and_a_new_task_honours_it(self):
        broker = self.make_broker(wait_seconds=30.0)
        call = lambda: broker.check("exec", PERMISSION_EXEC, {"command": "git status"})

        thread, box = self.run_in_thread(call)
        self.answer_next_request(broker, allowed=True, scope=SCOPE_ALWAYS)
        thread.join(timeout=5.0)

        self.assertIsNone(box["result"])
        self.assertTrue(self.rules.match("exec", "git status"))

        # A fresh broker stands in for a later task: it must not ask again.
        later = self.make_broker()
        self.assertIsNone(later.check("exec", PERMISSION_EXEC, {"command": "git status"}))
        self.assertEqual(self.decisions()[-1][2]["reason"], REASON_PERSISTENT_RULE)

    def test_a_persisted_rule_does_not_leak_to_another_command(self):
        self.rules.add("exec", "git status", PERMISSION_EXEC)
        broker = self.make_broker()

        denial = broker.check("exec", PERMISSION_EXEC, {"command": "git push --force"})

        self.assertIsNotNone(denial, "a different command must still be asked about")
        self.assertEqual(denial.details["reason"], REASON_TIMEOUT)

    def test_a_rule_that_cannot_be_written_is_not_reported_as_persistent(self):
        broker = self.make_broker(wait_seconds=30.0, rules=NoWriteRules())
        call = lambda: broker.check("exec", PERMISSION_EXEC, {"command": "git status"})

        thread, box = self.run_in_thread(call)
        self.answer_next_request(broker, allowed=True, scope=SCOPE_ALWAYS)
        thread.join(timeout=5.0)

        self.assertIsNone(box["result"], "the call itself still runs")
        self.assertEqual(
            self.decisions()[-1][2]["scope"],
            "once",
            "a rule that was not written must not be reported as standing",
        )


class EditPreviewTest(unittest.TestCase):
    """The dialog shows the change before the user decides (ADR 0006 D11)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "notes.txt"
        self.path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_preview_returns_a_diff_without_writing(self):
        before = self.path.read_bytes()

        result = make_edit_preview(str(self.root))(
            {"file_path": "notes.txt", "old_string": "beta", "new_string": "BETA"}
        )

        self.assertIn("-beta", result["gitDiff"])
        self.assertIn("+BETA", result["gitDiff"])
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(self.path.read_bytes(), before, "a preview must not write")

    def test_preview_reports_failures_instead_of_swallowing_them(self):
        preview = make_edit_preview(str(self.root))

        with self.assertRaises(EditFileError):
            preview({"file_path": "notes.txt", "old_string": "absent", "new_string": "x"})

    def test_the_dialog_receives_the_diff_through_the_registry(self):
        events = []
        registry = ToolRegistry(base_dir=str(self.root))
        registry.permission_broker = PermissionBroker(
            base_dir=str(self.root),
            rules=NoWriteRules(),
            wait_seconds=0.3,
            emit=lambda category, title, data: events.append((category, title, data)),
        )

        outcome = registry.execute_tool(
            "edit_file",
            {
                "file_path": "notes.txt",
                "old_string": "beta",
                "new_string": "BETA",
                "encoding": "utf-8",
            },
        )

        # Nobody answered, so the call was refused and the file is untouched...
        self.assertIsInstance(outcome, ToolOutcome)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "alpha\nbeta\ngamma\n")
        # ...but the request that went to the dialog carried the diff.
        request = [event for event in events if event[0] == "permission_request"][0]
        self.assertIn("+BETA", request[2]["details"]["gitDiff"])

    def test_a_broken_preview_does_not_break_the_request(self):
        events = []
        registry = ToolRegistry(base_dir=str(self.root))
        registry.permission_broker = PermissionBroker(
            base_dir=str(self.root),
            rules=NoWriteRules(),
            wait_seconds=0.3,
            emit=lambda category, title, data: events.append((category, title, data)),
        )

        registry.execute_tool(
            "edit_file",
            {"file_path": "notes.txt", "old_string": "absent", "new_string": "x"},
        )

        request = [event for event in events if event[0] == "permission_request"][0]
        self.assertEqual(request[2]["tool"], "edit_file")
        self.assertNotIn("gitDiff", request[2]["details"])


if __name__ == "__main__":
    unittest.main()
