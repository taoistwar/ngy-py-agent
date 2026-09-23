"""What the model is told about ``write_file``: its description and parameter schema.

Kept apart from the implementation so the tool's contract can be read on its own.
"""

from typing import Any, Dict

WRITE_FILE_DESCRIPTION = (
    "Create a text file or replace its entire content. Paths resolve against the workspace "
    "root and can never escape it; the global allow/deny policy applies on top. The whole "
    "file is written - nothing is appended, and the previous content is gone. Overwriting an "
    "existing file is only allowed after read_file has read that file in full in this task "
    "(line 1, no 'limit') and the file has not changed since; otherwise the call is rejected, "
    "so a file you have never seen can never be destroyed. The parent directory must already "
    "exist. Content is encoded with 'encoding' (required); a byte order mark and the existing "
    "line endings are preserved, and a new file is written with LF line endings and mode 0644. "
    "The write is atomic. To change part of a file use edit_file; to append, anchor edit_file "
    "on the file's last line."
)

WRITE_FILE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to the file, relative to the workspace root.",
        },
        "content": {
            "type": "string",
            "description": (
                "The complete new content of the file. It replaces whatever was there; an "
                "empty string empties the file."
            ),
        },
        "encoding": {
            "type": "string",
            "description": (
                "Text encoding used to encode the content (required). Use UTF-8 unless the "
                "file needs something else. A byte order mark always wins over this value."
            ),
        },
    },
    "required": ["file_path", "content", "encoding"],
}
