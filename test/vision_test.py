"""Tests for turning tool screenshots into model-visible image content.

Run from the repository root::

    uv run python test/vision_test.py -v

What matters: the image is only attached when both the model configuration and
the wire format allow it, a missing or oversized file never breaks the request,
and the message shape is the one OpenAI-compatible endpoints accept.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.models import ToolImage  # noqa: E402
from agent.vision import (  # noqa: E402
    build_image_message,
    image_data_url,
    redact_image_payload,
    supports_images,
)


def _provider(*, supports_image_input=True, wire_compatible=True):
    return SimpleNamespace(
        config=SimpleNamespace(supports_image_input=supports_image_input),
        wire_compatible_with_openai=wire_compatible,
    )


class VisionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.png = self.root / "shot.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_data_url_is_built_from_the_file(self):
        url = image_data_url(ToolImage(path=str(self.png)))

        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_the_message_is_a_user_message_with_text_and_image_parts(self):
        message = build_image_message(
            [("computer_observe", ToolImage(path=str(self.png)))], _provider()
        )

        self.assertEqual(message["role"], "user")
        kinds = [part["type"] for part in message["content"]]
        self.assertIn("text", kinds)
        self.assertIn("image_url", kinds)
        image_part = next(part for part in message["content"] if part["type"] == "image_url")
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(image_part["image_url"]["detail"], "auto")

    def test_a_model_without_the_flag_gets_no_image_message(self):
        message = build_image_message(
            [("computer_observe", ToolImage(path=str(self.png)))],
            _provider(supports_image_input=False),
        )

        self.assertIsNone(message)

    def test_a_non_openai_wire_format_gets_no_image_message(self):
        message = build_image_message(
            [("computer_observe", ToolImage(path=str(self.png)))],
            _provider(wire_compatible=False),
        )

        self.assertIsNone(message)

    def test_a_missing_file_does_not_produce_an_empty_message(self):
        missing = ToolImage(path=str(self.root / "gone.png"))

        self.assertIsNone(build_image_message([("computer_observe", missing)], _provider()))

    def test_an_oversized_file_is_left_out(self):
        with patch.dict(os.environ, {"TOOL_IMAGE_MAX_BYTES": "1"}):
            self.assertIsNone(image_data_url(ToolImage(path=str(self.png))))

    def test_other_attachments_survive_one_missing_file(self):
        missing = ToolImage(path=str(self.root / "gone.png"))

        message = build_image_message(
            [("computer_observe", missing), ("computer_observe", ToolImage(path=str(self.png)))],
            _provider(),
        )

        kinds = [part["type"] for part in message["content"]]
        self.assertEqual(kinds.count("image_url"), 1)
        self.assertTrue(
            any("could not be attached" in part.get("text", "") for part in message["content"])
        )

    def test_the_debug_payload_hides_the_base64_copy(self):
        message = build_image_message(
            [("computer_observe", ToolImage(path=str(self.png)))], _provider()
        )
        redacted = redact_image_payload({"messages": [message]})

        redacted_url = redacted["messages"][0]["content"][-1]["image_url"]["url"]
        original_url = message["content"][-1]["image_url"]["url"]
        self.assertIn("<image data omitted>", redacted_url)
        self.assertIn("base64,iVBOR", original_url)
        self.assertNotIn("base64,iVBOR", str(redacted))

    def test_supports_images_needs_both_the_flag_and_the_wire_format(self):
        self.assertTrue(supports_images(_provider()))
        self.assertFalse(supports_images(_provider(supports_image_input=False)))
        self.assertFalse(supports_images(_provider(wire_compatible=False)))
        self.assertFalse(supports_images(SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()
