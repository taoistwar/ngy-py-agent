"""The ``edit_file`` tool: exact-string replacement at the byte level.

The match is **strict byte-for-byte at the text level**: ``old_string`` must
appear in the file exactly as provided, with no newline or whitespace
normalization. That contract is only usable because ``read_file`` preserves the
original line endings, so the text the model reconstructs from a read is
byte-identical to the file (see ``docs/decisions/0001-file-edit-tool.md``).

The **write** is done at the byte level: only the matched byte range is replaced,
everything else is copied verbatim. Decoding the whole file, replacing and
re-encoding it would rewrite bytes the edit never touched on encodings whose
decode/encode pair is not a bijection (``cp932`` has hundreds of such byte pairs,
verified by ``test/tools/edit_file/edit_file_test.py``), so the splice keeps
untouched bytes pristine on every encoding (see
``docs/decisions/0002-file-encoding.md``).

A single call produces two outputs:

- the **model** only sees a one line success summary (or a readable error), and
- the **UI / external consumers** receive ``original_file``, ``structured_patch``
  and ``gitDiff`` through a dedicated ``file_edit`` event, never through the
  model's context.

The tool cannot create files: ``old_string`` must already exist.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The pipeline is in :mod:`~agent.tools.edit_file.edit`, the byte surgery in
:mod:`~agent.tools.edit_file.replace`, the patches in
:mod:`~agent.tools.edit_file.diff`; this module re-exports the public surface.
"""

from agent.tools.edit_file.description import EDIT_FILE_DESCRIPTION, EDIT_FILE_PARAMETERS
from agent.tools.edit_file.edit import make_edit_preview
from agent.tools.edit_file.errors import EditFileError
from agent.tools.edit_file.tool import make_edit_file_tool

__all__ = [
    "EDIT_FILE_DESCRIPTION",
    "EDIT_FILE_PARAMETERS",
    "EditFileError",
    "make_edit_file_tool",
    "make_edit_preview",
]
