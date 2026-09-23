"""Tests for the token counter backends and their degradation rules.

What is under test here is the counter's *contract*, not transformers: both real
backends are optional dependencies that need files on disk, so they are stubbed. The
rule being pinned is that a broken tokenizer costs accuracy and never a failed turn —
a budget check that raises is worse than a budget check that over-estimates.

Run from the repository root::

    uv run python test/tools/tokenizers_test.py -v
"""

import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools import tokenizers  # noqa: E402
from agent.tools.tokenizers import (  # noqa: E402
    FOREIGN_MODEL_PENALTY,
    TokenCounter,
    estimate_tokens,
)


class _HealthyTokenizer:
    """Answers the same count for every input, so a fallback cannot mask itself."""

    def encode(self, text: str, **kwargs: Any) -> list[int]:
        return [1, 2, 3]


class _FailsOnRealTextTokenizer:
    """Passes the loader's self-test, then fails on the text being counted."""

    def encode(self, text: str, **kwargs: Any) -> list[int]:
        if text == "self-test":
            return [1]
        raise RuntimeError("tokenizer backend exploded")


class _BrokenTokenizer:
    """Half-downloaded cache: construction succeeds, encoding never does."""

    def encode(self, text: str, **kwargs: Any) -> list[int]:
        raise RuntimeError("cache is half-downloaded")


class _FakeEncoding:
    """A tiktoken encoding: one token per word, or failure when asked."""

    def __init__(self, fail: bool = False):
        self._fail = fail

    def encode(self, text: str, **kwargs: Any) -> list[int]:
        if self._fail:
            raise RuntimeError("tiktoken exploded")
        return [0] * len(text.split())


class TokenCounterTest(unittest.TestCase):
    def setUp(self):
        self._tokenizer_dir = tempfile.TemporaryDirectory()
        self._env = {
            name: os.environ.get(name)
            for name in (tokenizers.DEEPSEEK_TOKENIZER_ENV, tokenizers.DEEPSEEK_OFFLINE_ENV)
        }
        # Point the DeepSeek loader at an empty temp directory, so a test can never
        # read or create the real one.
        os.environ[tokenizers.DEEPSEEK_TOKENIZER_ENV] = self._tokenizer_dir.name
        # An offline flag inherited from the developer's shell would make every loader
        # bail out early, and the assertions would pass for the wrong reason.
        os.environ.pop(tokenizers.DEEPSEEK_OFFLINE_ENV, None)
        self._modules: dict[str, Any] = {}

    def tearDown(self):
        for name, module in self._modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name, value in self._env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._tokenizer_dir.cleanup()

    def stub(self, name: str, **attributes: Any) -> None:
        """Install a fake optional dependency, remembering what it replaced."""
        self._modules.setdefault(name, sys.modules.get(name))
        module = types.ModuleType(name)
        for attribute, value in attributes.items():
            setattr(module, attribute, value)
        sys.modules[name] = module

    def hide(self, name: str) -> None:
        """Make ``import name`` fail the way a missing dependency does."""
        self._modules.setdefault(name, sys.modules.get(name))
        sys.modules[name] = None

    def stub_transformers(self, tokenizer: Any) -> None:
        self.stub(
            "transformers",
            AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda *a, **k: tokenizer),
        )

    def deepseek_counter(self) -> TokenCounter:
        return TokenCounter(provider="deepseek", model="deepseek-chat")

    def test_healthy_tokenizer_counts(self):
        self.stub_transformers(_HealthyTokenizer())

        counter = self.deepseek_counter()

        self.assertEqual(counter.backend, "transformers")
        self.assertEqual(counter.count("hello world"), 3)

    def test_empty_text_never_reaches_the_tokenizer(self):
        self.stub_transformers(_HealthyTokenizer())

        # The stub answers 3 for every input, so 0 here proves the short circuit.
        self.assertEqual(self.deepseek_counter().count(""), 0)

    def test_tokenizer_that_cannot_count_is_rejected_at_load(self):
        self.stub_transformers(_BrokenTokenizer())

        self.assertIsNone(tokenizers._load_local_tokenizer_counter())
        # The caller must not be told it is on the exact backend either.
        self.assertEqual(self.deepseek_counter().backend, "heuristic")

    def test_failed_count_degrades_instead_of_raising(self):
        self.stub_transformers(_FailsOnRealTextTokenizer())

        counter = self.deepseek_counter()

        self.assertEqual(counter.backend, "transformers")
        self.assertEqual(counter.count("hello world"), estimate_tokens("hello world"))

    def test_deepseek_without_transformers_uses_the_estimate(self):
        self.hide("transformers")

        counter = self.deepseek_counter()

        self.assertEqual(counter.backend, "heuristic")
        self.assertEqual(counter.count("hello world"), estimate_tokens("hello world"))

    def test_tiktoken_counts_and_applies_the_foreign_model_penalty(self):
        self.stub("tiktoken", encoding_for_model=lambda model: _FakeEncoding())

        counter = TokenCounter(provider="anthropic", model="claude-3-5-sonnet")

        self.assertEqual(counter.backend, "tiktoken")
        self.assertTrue(counter.applies_penalty)
        # The stub yields one token per word, then the margin is applied on top.
        self.assertEqual(counter.count("hello world"), math.ceil(2 * FOREIGN_MODEL_PENALTY))

    def test_failed_tiktoken_count_degrades_instead_of_raising(self):
        self.stub("tiktoken", encoding_for_model=lambda model: _FakeEncoding(fail=True))

        counter = TokenCounter(provider="anthropic", model="claude-3-5-sonnet")

        # The estimate goes through the margin as well: falling back is a way to avoid
        # failing the turn, not a way to escape the safety margin.
        expected = math.ceil(estimate_tokens("hello world") * FOREIGN_MODEL_PENALTY)
        self.assertEqual(counter.count("hello world"), expected)


if __name__ == "__main__":
    unittest.main()
