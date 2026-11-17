"""Remote image blocks, turned into files the vision layer can attach.

An MCP tool may answer with base64 image content. The model side of the app already
knows how to attach a local screenshot to the next message (``agent.vision``), so the
bytes are written to a file and travel as a ``ToolImage`` instead of being pasted into
the text the model reads.

Files are content addressed under the system temp directory: a polling tool that returns
the same screenshot every few seconds overwrites one file instead of filling the disk
with copies, and the name says nothing about the server (a file name is not a place to
smuggle user data into a path).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

from agent.models import ToolImage

# Anything larger is left as a text marker: the vision layer has its own ceiling
# (``TOOL_IMAGE_MAX_BYTES``) and reading 40 MB of base64 to throw it away helps nobody.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Only formats the vision layer knows how to send. Anything else (svg, bmp) keeps the
# text marker rather than becoming a file nothing can attach.
_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

__all__ = ["MAX_IMAGE_BYTES", "tool_image_from_block"]


def tool_image_from_block(block: Mapping[str, Any]) -> Optional[ToolImage]:
    """A ``ToolImage`` for one ``image`` content block, or ``None`` when unusable."""
    data = block.get("data")
    if not isinstance(data, str) or not data.strip():
        return None
    mime_type = str(block.get("mimeType") or "image/png").strip().lower()
    extension = _EXTENSIONS.get(mime_type)
    if extension is None:
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    return ToolImage(path=_write(raw, extension), mime_type=mime_type)


def _write(raw: bytes, extension: str) -> str:
    """Store ``raw`` under a content-addressed name and return its path."""
    directory = Path(tempfile.gettempdir()) / "ngy-mcp-images"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{hashlib.sha1(raw).hexdigest()[:16]}{extension}"
    if not path.is_file() or path.stat().st_size != len(raw):
        # Written through a temporary name so a reader never sees half a file: the same
        # path is shared by every task on this machine.
        staging = path.with_name(f"{path.name}.{hashlib.sha1(raw).hexdigest()[:6]}.part")
        staging.write_bytes(raw)
        staging.replace(path)
    return str(path)
