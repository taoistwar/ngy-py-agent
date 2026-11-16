"""What a workspace's ``AGENTS.md`` contributes to the system prompt.

https://agents.md/ defines the behaviour with three rules: one file at the repository
root, one per package in a monorepo, and the closest file wins. That is why the root file
is inlined while the nested ones are only indexed - one test per rule keeps the split
honest.

Run from the repository root::

    uv run python test/agents_md_test.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import agents_md  # noqa: E402


class _Workspace:
    """A throwaway workspace; ``write`` takes a POSIX-style relative path."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def write(self, relative: str, text: str = "- rule\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cleanup(self):
        self._tmp.cleanup()


class AgentsMdTest(unittest.TestCase):
    def setUp(self):
        self.workspace = _Workspace()
        self.addCleanup(self.workspace.cleanup)

    def load(self, settings=None):
        return agents_md.load_instructions(str(self.workspace.root), settings)

    def prompt(self, base: str = "base prompt", settings=None) -> str:
        return agents_md.with_agents_md(base, str(self.workspace.root), settings)

    def test_the_root_file_is_inlined_into_the_system_prompt(self):
        self.workspace.write("AGENTS.md", "Run `uv run pytest` before committing.\n")

        prompt = self.prompt()

        self.assertTrue(prompt.startswith("base prompt"))
        self.assertIn("## Project instructions (AGENTS.md)", prompt)
        self.assertIn("Run `uv run pytest` before committing.", prompt)

    def test_the_user_outranks_the_file(self):
        self.workspace.write("AGENTS.md", "Use tabs.\n")

        # The file is guidance, not a cage: the prompt has to say who wins a conflict.
        self.assertIn("outranks", self.prompt())

    def test_a_workspace_without_the_file_leaves_the_prompt_alone(self):
        self.assertEqual("base prompt", self.prompt())

    def test_an_unbound_session_has_no_project_instructions(self):
        self.assertEqual("base prompt", agents_md.with_agents_md("base prompt", None))
        self.assertIsNone(agents_md.load_instructions(""))
        self.assertIsNone(agents_md.load_instructions(str(self.workspace.root / "missing")))

    def test_the_singular_legacy_name_still_loads(self):
        self.workspace.write("AGENT.md", "Legacy rule.")

        self.assertIn("Legacy rule.", self.prompt())

    def test_the_standard_name_wins_over_the_legacy_one(self):
        self.workspace.write("AGENTS.md", "Standard rule.")
        self.workspace.write("AGENT.md", "Legacy rule.")

        prompt = self.prompt()

        self.assertIn("Standard rule.", prompt)
        self.assertNotIn("Legacy rule.", prompt)

    def test_nested_files_are_indexed_but_not_inlined(self):
        self.workspace.write("AGENTS.md", "Root rule.")
        self.workspace.write("packages/foo/AGENTS.md", "Package-only rule.")

        prompt = self.prompt()

        self.assertIn("`packages/foo/AGENTS.md`", prompt)
        self.assertNotIn("Package-only rule.", prompt)
        self.assertIn("closest file takes precedence", prompt)

    def test_the_root_file_is_not_listed_as_nested(self):
        self.workspace.write("AGENTS.md", "Root rule.")

        self.assertEqual((), self.load().nested)

    def test_nested_files_work_without_a_root_file(self):
        self.workspace.write("packages/foo/AGENTS.md", "Package rule.")

        prompt = self.prompt()

        self.assertIn("no root `AGENTS.md`", prompt)
        self.assertIn("`packages/foo/AGENTS.md`", prompt)
        # Nothing was inlined, so there is no "instructions above" to outrank.
        self.assertNotIn("precedence over the instructions above", prompt)

    def test_nested_files_are_listed_root_first(self):
        self.workspace.write("packages/foo/AGENTS.md")
        self.workspace.write("packages/foo/deep/AGENTS.md")

        self.assertEqual(
            ("packages/foo/AGENTS.md", "packages/foo/deep/AGENTS.md"),
            self.load().nested,
        )

    def test_dependencies_and_hidden_directories_are_not_scanned(self):
        self.workspace.write("AGENTS.md", "Root rule.")
        self.workspace.write("node_modules/pkg/AGENTS.md")
        self.workspace.write(".git/AGENTS.md")
        self.workspace.write(".venv/lib/AGENTS.md")

        self.assertEqual((), self.load().nested)

    def test_files_below_the_scan_depth_are_not_indexed(self):
        self.workspace.write("a/b/c/d/AGENTS.md")

        # Deeper than ``SCAN_DEPTH``: a monorepo's node_modules-sized tree is not walked.
        self.assertIsNone(self.load())

    def test_the_index_is_capped_and_says_how_many_were_left_out(self):
        for index in range(agents_md.NESTED_FILE_LIMIT + 3):
            self.workspace.write(f"pkg{index:02d}/AGENTS.md")

        instructions = self.load()

        self.assertEqual(agents_md.NESTED_FILE_LIMIT, len(instructions.nested))
        self.assertEqual(3, instructions.skipped)
        self.assertIn("3 more not listed", self.prompt())

    def test_the_setting_can_switch_the_read_off(self):
        self.workspace.write("AGENTS.md", "Root rule.")
        disabled = agents_md.AgentsMdSettings(enabled=False)

        self.assertIsNone(self.load(disabled))
        self.assertEqual("base prompt", self.prompt(settings=disabled))

    def test_the_defaults_are_on_and_32_kib(self):
        settings = agents_md.AgentsMdSettings()

        self.assertTrue(settings.enabled)
        self.assertEqual(agents_md.DEFAULT_MAX_BYTES, settings.max_bytes)

    def test_leftover_environment_variables_are_ignored(self):
        # The setting lives in the database (ADR 0022 D9); an old .env entry must not
        # quietly turn the read off or shrink the cap.
        self.workspace.write("AGENTS.md", "Root rule.")

        with patch.dict(
            os.environ,
            {"AGENTS_MD_ENABLED": "0", "AGENTS_MD_MAX_BYTES": "100"},
        ):
            instructions = self.load()

        self.assertIsNotNone(instructions)
        self.assertFalse(instructions.root.truncated)

    def test_a_large_file_is_truncated_without_splitting_a_character(self):
        self.workspace.write("AGENTS.md", "字" * 200)

        document = self.load(agents_md.AgentsMdSettings(max_bytes=100)).root

        self.assertTrue(document.truncated)
        self.assertIn("Truncated at 100 bytes", document.content)
        kept = document.content.split("\n\n[Truncated")[0]
        self.assertLessEqual(len(kept.encode("utf-8")), 100)
        self.assertEqual("字" * 33, kept)

    def test_empty_files_do_not_produce_an_empty_section(self):
        self.workspace.write("AGENTS.md", "  \n\n")

        self.assertIsNone(self.load())

    def test_the_debug_summary_names_files_without_their_text(self):
        self.workspace.write("AGENTS.md", "Root rule.")
        self.workspace.write("packages/foo/AGENTS.md")

        data = self.load().describe()

        self.assertEqual("AGENTS.md", data["root"])
        self.assertEqual(["packages/foo/AGENTS.md"], data["nested"])
        self.assertEqual(0, data["nested_skipped"])
        self.assertFalse(data["root_truncated"])
        self.assertNotIn("Root rule.", str(data))


if __name__ == "__main__":
    unittest.main()
