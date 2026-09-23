"""The ``read_file`` tool: workspace scoped text reading, one window at a time.

Reading is bounded on four axes so a single call can never blow up the model
context:

- the path must resolve inside the workspace root (``base_dir``),
- only text files are readable (a BOM is recognised as text; otherwise NUL bytes
  in the head mean binary),
- the raw bytes are capped (``MAX_FULL_READ_BYTES`` when reading to the end of
  file, ``min(MAX_FULL_READ_BYTES, budget * 4)`` when a line range is requested),
- the returned text must pass the three step token budget check.

The encoding is **never guessed silently**: decoding uses ``encoding`` (default
UTF-8) or the byte order mark when the file has one, and a failure is reported
with the candidate encodings that would decode the bytes so the model can retry
(see ``docs/decisions/0002-file-encoding.md``).

Line endings are deliberately **preserved** (``\\r\\n`` / ``\\n`` / ``\\r``) instead
of being normalized to ``\\n``: stripping the ``N<TAB>`` prefixes from the output
must reproduce the file bytes exactly, otherwise ``edit_file``'s strict byte
matching could never succeed on CRLF files (see
``docs/decisions/0001-file-edit-tool.md``).

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation is in :mod:`~agent.tools.read_file.tool`, the line handling in
:mod:`~agent.tools.read_file.lines`; this module re-exports the public surface.
"""

from agent.tools.read_file.description import (
    MAX_FULL_READ_BYTES,
    READ_FILE_DESCRIPTION,
    READ_FILE_PARAMETERS,
)
from agent.tools.read_file.errors import ReadFileError
from agent.tools.read_file.tool import make_read_file_tool

__all__ = [
    "MAX_FULL_READ_BYTES",
    "READ_FILE_DESCRIPTION",
    "READ_FILE_PARAMETERS",
    "ReadFileError",
    "make_read_file_tool",
]
