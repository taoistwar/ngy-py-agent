"""Turning tool screenshots into model-visible image content.

A tool only knows that it produced a screenshot; it does not know which provider
is running or whether the configured model accepts images. Both facts live here,
so ``computer_observe`` can return a :class:`~agent.models.ToolImage` without
branching on the provider.

Two constraints decide the shape of the message:

* The OpenAI chat API only accepts text in a ``tool`` message, so the image
  cannot be attached to the tool result itself. It travels as a follow-up
  ``user`` message with ``image_url`` parts, which is what OpenAI-compatible
  endpoints (including the configured DeepSeek model) accept.
* A provider that is not wire-compatible with OpenAI (Anthropic, Gemini) gets no
  image message from this module yet. The tool result still carries the file
  path, so nothing is silently lost; it is simply not shown to the model.

The image is embedded as a base64 data URL: the file lives on this machine, and
some OpenAI-compatible servers cannot reach a local path. ``TOOL_IMAGE_MAX_BYTES``
(default 8 MiB) keeps one oversized screenshot from failing the whole request.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.models import ToolImage

IMAGE_MAX_BYTES_ENV = "TOOL_IMAGE_MAX_BYTES"
DEFAULT_IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_MESSAGE_TEXT = "Screenshots captured by the tool calls above."


def max_image_bytes() -> int:
    """The per-image size ceiling, overridable for tests and constrained hosts."""
    raw = (os.getenv(IMAGE_MAX_BYTES_ENV) or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_IMAGE_MAX_BYTES
    return value if value > 0 else DEFAULT_IMAGE_MAX_BYTES


def image_data_url(image: ToolImage) -> Optional[str]:
    """Read ``image`` as a data URL, or ``None`` when it cannot be attached.

    A missing file, an unreadable one, or one over the size ceiling all mean
    "leave it out": the tool text already names the path, and failing the model
    call because a screenshot is large would be worse than a text-only step.
    """
    path = Path(image.path)
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > max_image_bytes():
            return None
        payload = path.read_bytes()
    except OSError:
        return None

    mime_type = image.mime_type or mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def supports_images(provider: Any) -> bool:
    """Whether this provider can carry image parts for the configured model.

    ``supports_image_input`` is the operator's statement about the model (Web
    Admin -> Models -> Image input); the wire check is this module's own limit.
    Both have to be true, otherwise the image never reaches the model and the
    extra message would only cost tokens.
    """
    config = getattr(provider, "config", None)
    if not bool(getattr(config, "supports_image_input", False)):
        return False
    return bool(getattr(provider, "wire_compatible_with_openai", False))


def redact_image_payload(value: Any) -> Any:
    """Copy ``value`` with inline image data replaced by a placeholder.

    The debugging event stores the raw request; a screenshot is a base64 string
    of a few megabytes, so keeping it there would bloat the task database and the
    UI. The conversation itself is untouched - this only builds the copy that is
    safe to persist.
    """
    if isinstance(value, dict):
        if value.get("type") == "image_url":
            image_url = value.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "")
                if url.startswith("data:"):
                    header = url.split(",", 1)[0]
                    return {
                        **value,
                        "image_url": {**image_url, "url": f"{header},<image data omitted>"},
                    }
        return {key: redact_image_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_image_payload(item) for item in value]
    return value


def build_image_message(
    images: Sequence[Tuple[str, ToolImage]],
    provider: Any,
) -> Optional[Dict[str, Any]]:
    """A follow-up user message carrying ``images``, or ``None`` when unusable.

    ``images`` pairs a label (the tool name) with the attachment, so the model
    can tell which observation each screenshot belongs to when a step ran
    several tools.
    """
    if not images or not supports_images(provider):
        return None

    parts: List[Dict[str, Any]] = [{"type": "text", "text": IMAGE_MESSAGE_TEXT}]
    attached = 0
    for label, image in images:
        data_url = image_data_url(image)
        if data_url is None:
            parts.append(
                {
                    "type": "text",
                    "text": f"{label}: screenshot at {image.path} could not be attached.",
                }
            )
            continue

        parts.append({"type": "text", "text": f"{label}: {image.path}"})
        image_url: Dict[str, Any] = {"url": data_url}
        if image.detail:
            image_url["detail"] = image.detail
        parts.append({"type": "image_url", "image_url": image_url})
        attached += 1

    if not attached:
        return None
    return {"role": "user", "content": parts}
