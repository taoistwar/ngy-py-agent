"""What the model is told about ``delete_file``: its description and parameter schema.

Kept apart from the implementation so the tool's contract can be read on its own.
"""

from typing import Any, Dict

DELETE_FILE_DESCRIPTION = (
    "Delete one file from the workspace. Paths resolve against the workspace root and "
    "can never escape it; the global allow/deny policy applies on top. Only a single "
    "regular file can be removed - a directory is refused, so use code_interpreter "
    "(for example shutil.rmtree) for a tree, and empty a file with write_file if it "
    "should stay. Deleting a file whose whole content this task has not read is "
    "refused (read it first with read_file, without 'limit'); a file that changed "
    "after it was read is refused as well, so a file you have never seen is not "
    "destroyed by a guess. Files too large to read in full are the one exception: "
    "the call runs and reports 'content_verified: false'. The user confirms every "
    "deletion, and in the app the deleted file shows up in the task's changes and can "
    "be restored from there."
)

DELETE_FILE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to the file to delete, relative to the workspace root.",
        },
    },
    "required": ["file_path"],
}
