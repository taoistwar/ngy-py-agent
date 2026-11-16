"""Ceilings the file tools share.

They live at the root rather than inside one tool package because two packages need
the same number and a tool package must not import another tool package
(``agent/tools/__init__.py``).

``read_file`` refuses to hand over a file larger than this in one call, so no tool
can honestly claim it has seen the whole content of such a file. ``delete_file``
reads the same number for exactly that reason: it decides whether "this run has seen
the content" is a question the model could have answered at all
(see ``docs/decisions/0026-delete-file-tool.md``).
"""

# Hard ceiling for the "read to the end of file" path.
MAX_FULL_READ_BYTES = 256 * 1024
