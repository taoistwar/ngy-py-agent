"""Token usage is read from whatever shape the provider returned.

Run from the repository root::

    uv run python test/telemetry/usage_test.py -v
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.telemetry.usage import extract_token_usage  # noqa: E402


class ExtractTokenUsageTest(unittest.TestCase):
    def test_openai_style_keys_are_mapped(self):
        payload = {"usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}}

        self.assertEqual(
            extract_token_usage(payload), {"input_tokens": 12, "output_tokens": 34}
        )

    def test_anthropic_style_keys_are_mapped(self):
        payload = {"usage": {"input_tokens": 7, "output_tokens": 9}}

        self.assertEqual(
            extract_token_usage(payload), {"input_tokens": 7, "output_tokens": 9}
        )

    def test_objects_with_attributes_work_too(self):
        payload = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2))

        self.assertEqual(
            extract_token_usage(payload), {"input_tokens": 1, "output_tokens": 2}
        )

    def test_missing_usage_yields_an_empty_mapping(self):
        self.assertEqual(extract_token_usage({"id": "chatcmpl-1"}), {})
        self.assertEqual(extract_token_usage(None), {})
        self.assertEqual(extract_token_usage({"usage": None}), {})

    def test_non_numeric_counts_are_ignored(self):
        self.assertEqual(extract_token_usage({"usage": {"prompt_tokens": "many"}}), {})


if __name__ == "__main__":
    unittest.main()
