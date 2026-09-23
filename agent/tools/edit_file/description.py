"""What the model is told about ``edit_file``: its description and parameter schema.

Kept apart from the implementation so the tool's contract can be read on its own.
"""

from typing import Any, Dict

EDIT_FILE_DESCRIPTION = (
    "Replace an exact string inside a text file. Paths resolve against the workspace root "
    "and can never escape it; the global allow/deny policy applies on top. "
    "'old_string' is matched BYTE FOR BYTE, so it must appear exactly as in the file, "
    "line endings included: strip the 'N<TAB>' prefix from read_file output and reuse the "
    "text verbatim. The match must be unique - when 'old_string' occurs more than once the "
    "call is rejected and you must add surrounding context, or pass replace_all=true to "
    "replace every occurrence. Decoding uses 'encoding' (default UTF-8) or the file's byte "
    "order mark when it has one; when the bytes cannot be decoded you get an error listing "
    "candidate encodings, so retry with the right 'encoding'. Inserted text is rewritten to "
    "the line ending the file already uses, and the byte order mark is preserved; only the "
    "matched range is rewritten, so untouched bytes are never touched. Edits are written "
    "atomically, and the file's permissions are carried over."
)

EDIT_FILE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to the file, relative to the workspace root.",
        },
        "old_string": {
            "type": "string",
            "description": (
                "Exact text to replace. Must be unique unless 'replace_all' is true."
            ),
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text. An empty string deletes the matched text.",
        },
        "replace_all": {
            "type": "boolean",
            "description": (
                "Replace every occurrence instead of requiring a unique match. Defaults to false."
            ),
        },
        "encoding": {
            "type": "string",
            "description": (
                "Text encoding used to decode and re-encode the file. Defaults to UTF-8. "
                "Use the 'encoding' value reported by read_file. A byte order mark always "
                "wins over this value."
            ),
        },
    },
    "required": ["file_path", "old_string", "new_string", "encoding"],
}
