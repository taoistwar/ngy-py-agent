"""The ``delete_file`` tool: remove one file from the workspace.

Deletion is the most destructive thing the file tools can do, so the same two facts
``write_file`` insists on are required here: this run must have seen the whole
content of the file, and the bytes on disk must still be the ones that were seen. A
file the model never read is therefore not deleted by a guess, and a file that
changed after it was read is refused rather than removed.

One honest exception: a file larger than the reader's ceiling
(``agent/tools/file_limits.py``) cannot be read in full, so "have you seen it" has no
answer. Refusing those would leave only ``exec_command`` / ``code_interpreter`` as a
way to delete them, and both escape the file policy entirely; instead the call runs,
is confirmed by the user, and reports ``content_verified: false``
(see ``docs/decisions/0026-delete-file-tool.md``).

Only regular files can be removed. Directories are refused with a hint that names the
tool which can remove a tree, and the permission gate is declared as a **write** so
the model can never delete something the user was not asked about.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``). The
implementation is in :mod:`~agent.tools.delete_file.delete`; this module re-exports
the public surface.
"""

from agent.tools.delete_file.delete import delete_file_impl
from agent.tools.delete_file.description import DELETE_FILE_DESCRIPTION, DELETE_FILE_PARAMETERS
from agent.tools.delete_file.errors import DeleteFileError
from agent.tools.delete_file.tool import make_delete_file_tool

__all__ = [
    "DELETE_FILE_DESCRIPTION",
    "DELETE_FILE_PARAMETERS",
    "DeleteFileError",
    "delete_file_impl",
    "make_delete_file_tool",
]
