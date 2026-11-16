"""Archive a conversation to disk, so a compaction can always be undone.

Two steps remove messages from the live conversation: :mod:`agent.agent_loop.snip_compact`
drops a range of them, :mod:`agent.agent_loop.compact_history` replaces the old history
with a summary. Both owe the model the same promise - the full history is on disk, one
JSON object per line, at an absolute path ``read_file`` can open.

That promise lives here rather than in either step: two writers of the same file shape
would eventually disagree about the line format or the directory, and the model would
have to learn two read-back stories for one archive.

JSONL, not one big JSON array: ``read_file`` slices by line, so a payload that answers
"the whole history" but arrives as a single line cannot be read back in parts.

Images are replaced before writing (``redact_image_payload``): a transcript is for the
text that was dropped, and one inline screenshot is a few megabytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tools.output_store import (
    ensure_result_directory,
    new_stem,
    persist_text,
    workspace_transcript_directory,
)
from agent.vision import redact_image_payload

TRANSCRIPT_PREFIX = "transcript-"
TRANSCRIPT_EXTENSION = ".jsonl"


def write_transcript(
    messages: List[Dict[str, Any]],
    base_dir: Optional[str] = None,
) -> Path:
    """Write ``messages`` to a new ``.ngy-agent/.transcripts/transcript-<stamp>-<hex>.jsonl``.

    A new file per call, never an overwrite: the previous marker in the conversation
    still points at the previous file, and replacing it would delete the evidence that
    marker promises.
    """
    directory = workspace_transcript_directory(base_dir)
    ensure_result_directory(directory)
    lines = [
        json.dumps(redact_image_payload(message), ensure_ascii=False) for message in messages
    ]
    return persist_text(
        directory,
        new_stem(TRANSCRIPT_PREFIX) + TRANSCRIPT_EXTENSION,
        "\n".join(lines) + "\n",
    )
