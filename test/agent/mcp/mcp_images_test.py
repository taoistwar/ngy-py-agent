"""Tests for turning remote image blocks into attachments the vision layer can send.

Run from the repository root::

    uv run python test/agent/mcp/mcp_images_test.py -v
"""

import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# ``test/`` is intentionally not a package, so the repository root is added to the
# import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.mcp.images import tool_image_from_block  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\nfake body"


def _png_block(data: bytes = _PNG, **overrides) -> dict:
    block = {
        "type": "image",
        "mimeType": "image/png",
        "data": base64.b64encode(data).decode("ascii"),
    }
    block.update(overrides)
    return block


class ToolImageFromBlockTest(unittest.TestCase):
    def test_a_png_block_becomes_a_file_with_the_right_mime_type(self):
        image = tool_image_from_block(_png_block())

        self.assertIsNotNone(image)
        self.assertEqual(image.mime_type, "image/png")
        path = Path(image.path)
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), _PNG)
        self.assertEqual(path.suffix, ".png")

    def test_the_same_bytes_reuse_one_file(self):
        first = tool_image_from_block(_png_block())
        second = tool_image_from_block(_png_block())

        self.assertEqual(first.path, second.path)

    def test_a_jpeg_block_gets_a_jpg_extension(self):
        image = tool_image_from_block(_png_block(mimeType="image/JPEG"))

        self.assertIsNotNone(image)
        self.assertEqual(image.mime_type, "image/jpeg")
        self.assertTrue(image.path.endswith(".jpg"))

    def test_a_format_the_vision_layer_cannot_send_is_skipped(self):
        self.assertIsNone(tool_image_from_block(_png_block(mimeType="image/svg+xml")))

    def test_broken_base64_is_skipped(self):
        block = {"type": "image", "mimeType": "image/png", "data": "!!!!"}

        self.assertIsNone(tool_image_from_block(block))

    def test_an_empty_payload_is_skipped(self):
        block = {"type": "image", "mimeType": "image/png", "data": "   "}

        self.assertIsNone(tool_image_from_block(block))

    def test_a_missing_payload_is_skipped(self):
        self.assertIsNone(tool_image_from_block({"type": "image", "mimeType": "image/png"}))

    def test_an_oversized_payload_is_skipped(self):
        with patch("agent.mcp.images.MAX_IMAGE_BYTES", 4):
            self.assertIsNone(tool_image_from_block(_png_block()))

    def test_a_base64_value_that_is_not_a_string_is_skipped(self):
        self.assertIsNone(tool_image_from_block({"type": "image", "data": 12}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
