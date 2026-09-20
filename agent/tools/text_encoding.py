"""Strict text decoding and encoding hints shared by the file tools.

The file tools never guess an encoding silently. When decoding fails they report
the failure to the model together with the candidate encodings that *would*
decode the bytes, and the model retries with an explicit ``encoding`` argument.
Detection therefore exists to produce a hint, not to make the decision: a wrong
automatic guess would be a silently mis-read file, which is exactly what the
tools are built to avoid (see ``docs/decisions/0002-file-encoding.md``).

Detection is layered:

1. **BOM** - definitive. When present it wins over any requested encoding.
2. **charset-normalizer** - ranked candidates for the ambiguous middle ground.
3. **Trial decodes** - the encodings that are known to decode these bytes.

Every layer degrades gracefully: a missing library or a detector error simply
yields a shorter suggestion list (same optional-import style as
``agent/tools/tokenizers.py``).
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_ENCODING = "utf-8"

# Longest BOM first: BOM_UTF32_LE starts with the BOM_UTF16_LE bytes.
_BOMS: Tuple[Tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# Trial decoded only to enrich the hint. ``latin-1`` decodes any byte sequence,
# so it comes last and is reported as carrying no information.
_TRIAL_ENCODINGS: Tuple[str, ...] = (
    "gb18030",
    "big5",
    "shift_jis",
    "euc-kr",
    "cp1252",
    "latin-1",
)

# Bounded so detection stays cheap on large files.
_DETECTION_SAMPLE_BYTES = 64 * 1024

_MAX_SUGGESTIONS = 5

# Bytes inspected when deciding whether a file is binary.
BINARY_SNIFF_BYTES = 8192

REASON_DECODE_FAILED = "decode_failed"
REASON_UNKNOWN_ENCODING = "unknown_encoding"
REASON_UNENCODABLE_TEXT = "unencodable_text"


@dataclass(frozen=True)
class DecodedText:
    """A file decoded to text, with the BOM kept aside for a byte-faithful write."""

    text: str
    encoding: str
    bom: bytes = b""
    requested: Optional[str] = None

    @property
    def has_bom(self) -> bool:
        return bool(self.bom)


class DecodeError(Exception):
    """Raised when bytes cannot be decoded with the requested encoding."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}


class EncodeError(Exception):
    """Raised when text cannot be encoded with the target encoding."""

    def __init__(self, message: str, reason: str = REASON_UNENCODABLE_TEXT, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}


def canonical_encoding(name: str) -> str:
    """Return the canonical codec name, raising ``LookupError`` when unknown."""
    return codecs.lookup((name or "").strip() or DEFAULT_ENCODING).name


def detect_bom(raw: bytes) -> Optional[Tuple[bytes, str]]:
    """Return ``(bom_bytes, encoding)`` when ``raw`` starts with a known BOM."""
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return bom, encoding
    return None


def looks_binary(raw: bytes) -> bool:
    """Heuristic used only when no BOM is present.

    A BOM is definitive evidence of a text encoding, so the caller must check it
    first: UTF-16/UTF-32 text always contains NUL bytes and would otherwise be
    rejected as binary before its encoding is ever considered.
    """
    return b"\x00" in raw[:BINARY_SNIFF_BYTES]


def _charset_normalizer_candidates(raw: bytes) -> List[Tuple[str, Optional[float]]]:
    """Ranked candidates from charset-normalizer, or ``[]`` when unavailable."""
    try:
        from charset_normalizer import from_bytes
    except Exception:
        return []

    try:
        matches = from_bytes(raw[:_DETECTION_SAMPLE_BYTES])
        collected: List[Tuple[str, Optional[float]]] = []
        for match in list(matches)[:3]:
            encoding = getattr(match, "encoding", None)
            if not encoding:
                continue
            chaos = getattr(match, "chaos", None)
            confidence = None if chaos is None else round(max(0.0, 1.0 - float(chaos)), 3)
            collected.append((str(encoding), confidence))
        return collected
    except Exception:
        return []


def suggest_encodings(raw: bytes) -> List[Dict[str, Any]]:
    """Candidate encodings that could decode ``raw``, best first.

    Never applied automatically: the caller only reports them so the model can
    retry with an explicit ``encoding``.
    """
    suggestions: List[Dict[str, Any]] = []
    seen = set()

    def add(name: str, source: str, confidence: Optional[float], note: Optional[str] = None) -> None:
        try:
            canonical = canonical_encoding(name)
        except LookupError:
            return
        if canonical in seen:
            return
        seen.add(canonical)
        entry: Dict[str, Any] = {"encoding": canonical, "source": source, "confidence": confidence}
        if note:
            entry["note"] = note
        suggestions.append(entry)

    bom_hit = detect_bom(raw)
    if bom_hit is not None:
        add(bom_hit[1], "bom", 1.0)

    for name, confidence in _charset_normalizer_candidates(raw):
        add(name, "charset-normalizer", confidence)

    sample = raw[:_DETECTION_SAMPLE_BYTES]
    for name in _TRIAL_ENCODINGS:
        try:
            sample.decode(name)
        except (UnicodeDecodeError, LookupError, TypeError):
            continue
        if name == "latin-1":
            add(name, "trial", 0.0, "decodes any byte sequence, so it proves nothing")
        else:
            add(name, "trial", None)

    return suggestions[:_MAX_SUGGESTIONS]


def decode_file_bytes(raw: bytes, encoding: Optional[str] = None) -> DecodedText:
    """Decode file bytes, keeping any BOM aside for a byte-faithful write.

    A BOM outranks the requested encoding: it is what the file itself declares.
    On failure a :class:`DecodeError` carrying encoding suggestions is raised.
    """
    bom_hit = detect_bom(raw)
    if bom_hit is not None:
        bom_bytes, bom_encoding = bom_hit
        effective = bom_encoding
        body = raw[len(bom_bytes) :]
    else:
        bom_bytes = b""
        try:
            effective = canonical_encoding(encoding or DEFAULT_ENCODING)
        except LookupError:
            raise DecodeError(
                f"Unknown encoding {encoding!r}.",
                reason=REASON_UNKNOWN_ENCODING,
                encoding=encoding,
                suggested_encodings=suggest_encodings(raw),
            ) from None
        body = raw

    try:
        text = body.decode(effective)
    except UnicodeDecodeError as exc:
        raise DecodeError(
            f"Cannot decode the file as {effective}; retry with the correct 'encoding'.",
            reason=REASON_DECODE_FAILED,
            encoding=effective,
            byte_offset=exc.start,
            suggested_encodings=suggest_encodings(raw),
        ) from exc

    return DecodedText(text=text, encoding=effective, bom=bom_bytes, requested=encoding)


def encode_text(text: str, encoding: str) -> bytes:
    """Encode text strictly, raising :class:`EncodeError` on unencodable characters."""
    try:
        return text.encode(encoding)
    except UnicodeEncodeError as exc:
        bad = text[exc.start : exc.end]
        raise EncodeError(
            f"Character {bad!r} (U+{ord(bad[:1]):04X}) cannot be encoded as {encoding}; "
            "rewrite it using characters that encoding supports.",
            encoding=encoding,
            character=bad,
        ) from exc
    except LookupError:
        raise EncodeError(
            f"Unknown encoding {encoding!r}.",
            reason=REASON_UNKNOWN_ENCODING,
            encoding=encoding,
        ) from None
