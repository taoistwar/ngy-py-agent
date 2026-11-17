"""Which transport a preset asks for, and how to open it.

A preset stores a transport name and a target: a command line for ``stdio``, a URL for
``sse`` and ``http``. This module is the only place that maps the two onto a session, so
the probe and the bridge cannot disagree about what a preset means.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from agent.mcp.http_transport import SseSession, StreamableHttpSession
from agent.mcp.protocol import McpSession
from agent.mcp.stdio import McpSessionError, StdioSession
from agent.tools.vault_store import VaultStore, VaultStoreError

SUPPORTED_TRANSPORTS = ("stdio", "sse", "http")
DEFAULT_TRANSPORT = "stdio"
# A header value that starts with this names a vault key instead of holding a secret:
# a token typed into a preset would end up in the database, in every agent snapshot and
# in the task record (ADR 0030).
VAULT_REFERENCE_PREFIX = "vault:"
_HEADER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def normalize_transport(value: Any) -> str:
    """The stored transport name, with the spellings people use for Streamable HTTP."""
    transport = str(value or DEFAULT_TRANSPORT).strip().lower()
    return {
        "streamable": "http",
        "streamable-http": "http",
        "streamable_http": "http",
    }.get(transport, transport)


def open_session(preset: Mapping[str, Any]) -> McpSession:
    """The session a preset describes.

    Raises ``McpSessionError`` when the preset cannot be turned into one at all (empty
    target, unknown transport, unusable headers): every caller - probe and bridge - turns
    that into a status line rather than a crash, because it is a configuration mistake.
    """
    transport = normalize_transport(preset.get("transport"))
    target = str(preset.get("target") or "").strip()
    if transport not in SUPPORTED_TRANSPORTS:
        raise McpSessionError(
            f"The '{transport}' transport is not supported; use stdio, sse or http."
        )
    if not target:
        raise McpSessionError("The MCP target is empty, so there is nothing to connect to.")
    headers = resolve_headers(preset.get("headers"))
    if transport == "stdio":
        if headers:
            raise McpSessionError(
                "Headers only apply to the sse and http transports, not to a stdio command."
            )
        return StdioSession(target)
    if transport == "sse":
        return SseSession(target, headers)
    return StreamableHttpSession(target, headers)


def resolve_headers(raw: Any) -> Dict[str, str]:
    """Header pairs for a preset, with ``vault:<name>`` values read from the vault."""
    return {name: _resolve_value(name, value) for name, value in _header_pairs(raw)}


def _header_pairs(raw: Any) -> List[Tuple[str, str]]:
    """The preset's headers, in whichever shape they were stored."""
    if not raw:
        return []
    entries: Sequence[Any] = list(raw.items()) if isinstance(raw, Mapping) else raw
    if isinstance(entries, (str, bytes)) or not isinstance(entries, (list, tuple)):
        raise McpSessionError("MCP headers must be a list of name/value pairs.")
    pairs: List[Tuple[str, str]] = []
    for entry in entries:
        name, value = _entry_of(entry)
        if not name:
            continue
        if not _HEADER_NAME.match(name):
            raise McpSessionError(f"{name!r} is not a usable HTTP header name.")
        if not value:
            continue
        pairs.append((name, value))
    return pairs


def _entry_of(entry: Any) -> Tuple[str, str]:
    if isinstance(entry, Mapping):
        return (
            str(entry.get("name") or "").strip(),
            str(entry.get("value") or "").strip(),
        )
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return str(entry[0] or "").strip(), str(entry[1] or "").strip()
    raise McpSessionError("Each MCP header needs a name and a value.")


def _resolve_value(name: str, value: str) -> str:
    if not value.startswith(VAULT_REFERENCE_PREFIX):
        return value
    key = value[len(VAULT_REFERENCE_PREFIX) :].strip()
    try:
        return VaultStore().get(key)
    except VaultStoreError as exc:
        raise McpSessionError(
            f"Header {name!r} could not be filled from the vault: {exc.message}"
        ) from exc
