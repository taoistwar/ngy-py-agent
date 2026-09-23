"""What the model is told about ``read_file``: its description and parameter schema.

Kept apart from the implementation so the tool's contract can be read on its own.
"""

from typing import Any, Dict

# Hard ceiling for the "read to the end of file" path.
MAX_FULL_READ_BYTES = 256 * 1024

# Line numbers are always emitted and deliberately have no opt-out switch: the
# model cannot see the real line numbers, so a numberless read turns every later
# "change line N" reference into guesswork. Saving tokens is not worth that.
LINE_NUMBER_SEPARATOR = "\t"

READ_FILE_DESCRIPTION = (
    "Read a text file. Paths are resolved against the workspace root when the session "
    "has one and can never escape it; a global allow/deny policy always applies on top. "
    "Returns the requested line range, each line prefixed with its 1-based line number "
    "followed by a single tab. Omit 'limit' to "
    "read from 'offset' to the end of the file (rejected when the file is larger than "
    "256KB). Provide 'limit' to read a specific number of lines; the returned text is "
    "rejected when it exceeds the output token budget, so prefer small ranges and "
    "continue with a new 'offset' when needed. Decoding uses 'encoding' (default UTF-8) "
    "or the file's byte order mark when it has one; when the bytes cannot be decoded you "
    "get an error listing candidate encodings, so retry with the right 'encoding'. The "
    "result reports the 'encoding' that worked - pass the same value to edit_file. "
    "Original line endings are preserved, so "
    "the text with the 'N<TAB>' prefixes stripped can be passed verbatim to edit_file "
    "as 'old_string'."
)

READ_FILE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": (
                "Path to the file, relative to the workspace root (absolute paths are "
                "accepted only when they stay inside the workspace)."
            ),
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": ("1-based line number to start from. Defaults to 1; 0 is treated as 1."),
        },
        "limit": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Number of lines to read. Omit it (or pass 0) to read from 'offset' to the end of the file."
            ),
        },
        "encoding": {
            "type": "string",
            "description": (
                "Text encoding used to decode the file (required). Use UTF-8 unless you have "
                "a reason not to. A byte order mark always wins over this value. When "
                "decoding fails the error lists candidate encodings; retry with the one "
                "that fits."
            ),
        },
    },
    "required": ["file_path", "encoding"],
}
