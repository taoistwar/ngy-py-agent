"""The pure text and byte surgery behind ``edit_file``.

Matching, replacing and splicing are all side-effect free, which is what lets the
confirmation dialog show the very diff the write will produce (ADR 0006 D11). The
splice works at the byte level on purpose: rewriting the whole file through a
decode/encode round trip would alter bytes the edit never touched, on encodings
whose decode/encode pair is not a bijection (ADR 0002).
"""

from __future__ import annotations

from typing import List

from agent.tools.edit_file.errors import EditFileError
from agent.tools.text_encoding import encode_text


def match_spans(text: str, old_string: str, replace_all: bool) -> List[int]:
    """Character offsets of every (non-overlapping) match."""
    spans: List[int] = []
    cursor = text.find(old_string)
    while cursor != -1:
        spans.append(cursor)
        if not replace_all:
            break
        cursor = text.find(old_string, cursor + len(old_string))
    return spans


def replace_spans(text: str, spans: List[int], old_string: str, new_string: str) -> str:
    """Rebuild ``text`` with ``new_string`` at every span."""
    parts: List[str] = []
    cursor = 0
    for start in spans:
        parts.append(text[cursor:start])
        parts.append(new_string)
        cursor = start + len(old_string)
    parts.append(text[cursor:])
    return "".join(parts)


def splice_bytes(
    raw: bytes,
    text: str,
    bom: bytes,
    encoding: str,
    spans: List[int],
    old_string: str,
    inserted: str,
    display: str,
) -> bytes:
    """Replace only the matched byte ranges, copying every other byte verbatim."""
    body = raw[len(bom) :]
    old_bytes = encode_text(old_string, encoding)
    new_bytes = encode_text(inserted, encoding)

    parts: List[bytes] = []
    byte_cursor = 0
    char_cursor = 0
    for start in spans:
        byte_start = byte_cursor + len(encode_text(text[char_cursor:start], encoding))
        byte_end = byte_start + len(old_bytes)
        if body[byte_start:byte_end] != old_bytes:
            raise EditFileError(
                "The bytes behind 'old_string' do not match a canonical "
                f"{encoding} sequence, so this edit cannot be applied byte-for-byte. "
                "Rewrite the file as UTF-8 first.",
                reason="encoding_mismatch",
                file_path=display,
                encoding=encoding,
            )
        parts.append(body[byte_cursor:byte_start])
        parts.append(new_bytes)
        byte_cursor = byte_end
        char_cursor = start + len(old_string)
    parts.append(body[byte_cursor:])
    return bom + b"".join(parts)
