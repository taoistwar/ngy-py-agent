"""Tests for provider-name normalisation.

A provider name is user configuration, and the same value is read by three callers
(``build_provider``, ``agent_loop`` and the registry's schema selection). These tests
pin the one table they all go through, so a new spelling is added in one place
instead of three.

Run from the repository root::

    uv run python test/provider_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.provider import canonicalize_provider, normalize_provider_name  # noqa: E402
from agent.tools.registry import ToolRegistry  # noqa: E402

# Spellings a user might write -> the normalised form. Punctuation variants are not
# listed separately: unifying them is the point of normalisation.
SPELLINGS = {
    "openai": "openai",
    "OpenAI": "openai",
    "  openai  ": "openai",
    "openai_compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "OpenAI Compatible": "openai_compatible",
    "openai.compatible": "openai_compatible",
    "anthropic_compatible": "anthropic_compatible",
    "anthropic-compatible": "anthropic_compatible",
    "Claude": "claude",
    "google_generative_ai": "google_generative_ai",
}

UNUSABLE = ("", "   ", None, 123, ["openai"])


class NormalizeProviderNameTest(unittest.TestCase):
    def test_spellings_become_lower_snake_case(self):
        for raw, expected in SPELLINGS.items():
            with self.subTest(provider=raw):
                self.assertEqual(normalize_provider_name(raw), expected)

    def test_unusable_input_is_blank_rather_than_an_exception(self):
        # A wrong type in a config file must not raise ``AttributeError`` out of a
        # caller that only expects the documented failure mode.
        for raw in UNUSABLE:
            with self.subTest(provider=raw):
                self.assertEqual(normalize_provider_name(raw), "")


class CanonicalizeProviderTest(unittest.TestCase):
    def test_aliases_resolve_to_the_provider_we_build(self):
        cases = {
            "claude": "anthropic",
            "aws": "bedrock",
            "google": "gemini",
            "openai-compatible": "openai",
            "OpenAI Compatible": "openai",
        }
        for raw, expected in cases.items():
            with self.subTest(provider=raw):
                self.assertEqual(canonicalize_provider(raw), expected)

    def test_anthropic_compatible_stays_distinct(self):
        # ``build_provider`` builds a different client for it, so canonicalisation
        # must not collapse it into ``anthropic``.
        self.assertEqual(
            canonicalize_provider("anthropic-compatible"), "anthropic_compatible"
        )

    def test_not_configured_falls_back_to_openai(self):
        for raw in UNUSABLE:
            with self.subTest(provider=raw):
                self.assertEqual(canonicalize_provider(raw), "openai")

    def test_unknown_name_is_returned_normalised(self):
        # Guessing would hide a typo; the caller's error names it instead.
        self.assertEqual(canonicalize_provider("azure"), "azure")


class SchemaAdapterTest(unittest.TestCase):
    """The registry picks a tool-schema shape from the same canonical names."""

    def setUp(self):
        self.registry = ToolRegistry(enabled_tools=[])

    def test_spellings_reach_the_right_adapter(self):
        cases = {
            "openai": "openai",
            "openai-compatible": "openai",
            "openai.compatible": "openai",
            "anthropic": "anthropic",
            "anthropic-compatible": "anthropic",
            "claude": "anthropic",
            "google": "gemini",
            "aws": "bedrock",
            "mcp": "mcp",
        }
        for raw, expected in cases.items():
            with self.subTest(provider=raw):
                self.assertEqual(ToolRegistry.normalize_provider(raw), expected)

    def test_blank_input_keeps_the_openai_default(self):
        # Used to raise ``ValueError: Unsupported provider: `` with an empty name.
        self.assertEqual(ToolRegistry.normalize_provider("   "), "openai")
        self.assertEqual(self.registry.get_tool_schemas("   "), [])

    def test_unknown_adapter_still_fails_loudly(self):
        with self.assertRaises(ValueError):
            self.registry.get_tool_schemas("azure")


if __name__ == "__main__":
    unittest.main()
