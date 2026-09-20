"""Line-oriented text helpers shared by the file tools.

Both ``read_file`` and ``edit_file`` must agree on two things, because
``edit_file`` does strict byte matching on the text ``read_file`` handed to the
model (see ``docs/decisions/0001-file-edit-tool.md``):

- line endings are **never** normalized (``\\r\\n`` / ``\\n`` / ``\\r`` are kept
  exactly as they appear), and
- a **line** ends only at one of those three terminators.

The second point is why ``str.splitlines`` is not used: it also breaks on
``\\v``, ``\\f``, ``\\x1c``-``\\x1e``, ``\\x85``, ``\\u2028`` and ``\\u2029``.
``read_file`` streams the file with ``newline=""``, which breaks on the three
terminators only, so using ``splitlines`` here made the line numbers reported by
the patch disagree with the line numbers the model was shown.
"""

import re
from bisect import bisect_right
from typing import List, Tuple

LINE_ENDINGS = ("\r\n", "\n", "\r")

# Every terminator style, used to re-emit one consistent style in inserted text.
_LINE_ENDING_PATTERN = re.compile(r"\r\n|\r|\n")


def split_line_ending(raw: str) -> Tuple[str, str]:
    """Split a raw line into ``(content, line_ending)`` without normalizing."""
    for ending in LINE_ENDINGS:
        if raw.endswith(ending):
            return raw[: -len(ending)], ending
    return raw, ""


def strip_line_ending(raw: str) -> str:
    """Return the line content without its terminator."""
    return split_line_ending(raw)[0]


def split_lines(text: str) -> List[str]:
    """Split ``text`` on ``\\r\\n`` / ``\\n`` / ``\\r``, keeping the terminators.

    Mirrors what a file opened with ``newline=""`` yields, so line numbers stay
    consistent between reading and patching.
    """
    if not text:
        return []

    lines: List[str] = []
    start = 0
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char == "\n":
            index += 1
            lines.append(text[start:index])
            start = index
            continue
        if char == "\r":
            index += 1
            if index < length and text[index] == "\n":
                index += 1
            lines.append(text[start:index])
            start = index
            continue
        index += 1

    if start < length:
        lines.append(text[start:])
    return lines


def offsets_from_lines(lines: List[str]) -> List[int]:
    """Character offset of the start of every line already split by :func:`split_lines`."""
    offsets: List[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    return offsets


def line_offsets(text: str) -> List[int]:
    """Character offset of the start of every line in ``text``."""
    return offsets_from_lines(split_lines(text))


def line_index(offsets: List[int], position: int) -> int:
    """Index of the line containing character ``position`` (0-based)."""
    if not offsets:
        return 0
    index = bisect_right(offsets, max(position, 0)) - 1
    return max(index, 0)


def dominant_line_ending(text: str) -> str:
    """The terminator ``text`` uses most; ``\\n`` when it uses none."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    best = max(crlf, lf, cr)
    if best == 0:
        return "\n"
    if crlf == best:
        return "\r\n"
    if lf == best:
        return "\n"
    return "\r"


def apply_line_ending(text: str, ending: str) -> str:
    """Rewrite every terminator in ``text`` to ``ending``.

    Without this, inserting LF text into a CRLF file leaves the file with mixed
    endings, so "line endings are preserved" would only hold for the parts the
    write did not touch.
    """
    if not text:
        return text
    return _LINE_ENDING_PATTERN.sub(lambda _match: ending, text)
