"""The ``write_file`` tool: create a file, or replace it entirely.

The tool always writes the **whole** file. It never appends: to append, anchor
``edit_file`` on the file's last line, which keeps the write small, keeps the
concurrency check, and stays idempotent when a call is retried.

Replacing an existing file requires proof that the model has seen its current
content: a full ``read_file`` of that file (from line 1, without ``limit``)
recorded for this run, plus the bytes on disk still being the ones that were read.
A file that was never read can therefore never be destroyed. When the content
being replaced is not known, the call is rejected instead of guessing.

Encoding works like the other two tools: ``encoding`` decides, a byte order mark
outranks it, and existing line endings and the BOM are preserved. Failures are
reported to the model as text so it can correct itself, while the UI receives the
full record through a ``file_write`` event (see
``docs/decisions/0004-file-write-tool.md``).

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation is in :mod:`~agent.tools.write_file.write`; this module
re-exports the public surface.
"""

from agent.tools.write_file.description import WRITE_FILE_DESCRIPTION, WRITE_FILE_PARAMETERS
from agent.tools.write_file.errors import WriteFileError
from agent.tools.write_file.tool import make_write_file_tool

__all__ = [
    "WRITE_FILE_DESCRIPTION",
    "WRITE_FILE_PARAMETERS",
    "WriteFileError",
    "make_write_file_tool",
]
