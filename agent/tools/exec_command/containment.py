"""What actually constrains a command, and what only looks like it does.

Containment is layered and the layers are *not* equivalent (see
``docs/decisions/0005-exec-tool.md``): the process tree and resource caps are always
on, the integrity-level drop is not enabled yet. Nothing here is a security
boundary, so the report says so in as many words.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Tuple

from agent.tools import process_group
from agent.tools.text_encoding import DecodeError, decode_file_bytes, suggest_encodings

INTEGRITY_UNCHANGED = "unchanged"

# Credential-looking environment variables are withheld from commands: defense in
# depth against a build script printing its environment, not a boundary
# (``code_interpreter`` can still read them).
SECRET_ENV_PATTERN = re.compile(r"(API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSWD)", re.IGNORECASE)
PASS_SECRET_ENV_FLAG = "EXEC_PASS_SECRET_ENV"


def child_env() -> Tuple[Dict[str, str], int]:
    """The environment for the command, with credential-looking names withheld."""
    env = dict(os.environ)
    if (os.getenv(PASS_SECRET_ENV_FLAG) or "").strip() == "1":
        return env, 0
    withheld = 0
    for name in list(env):
        if SECRET_ENV_PATTERN.search(name):
            env.pop(name, None)
            withheld += 1
    return env, withheld


def decode_capture(raw: bytes) -> Tuple[str, str, bool]:
    """Decode command output, reporting the encoding and whether bytes were lost."""
    if not raw:
        return "", "utf-8", False
    try:
        decoded = decode_file_bytes(raw, "utf-8")
        return decoded.text, decoded.encoding, False
    except DecodeError:
        pass
    for candidate in suggest_encodings(raw):
        name = str(candidate.get("encoding") or "")
        # latin-1 decodes anything, so it would hide a mis-decode behind a
        # plausible looking string. Prefer an explicit replacement marker.
        if not name or name == "latin-1":
            continue
        try:
            return raw.decode(name), name, False
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8", True


def looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:8192]


def containment_report(
    command: process_group.RunningCommand, disable_sandbox: bool
) -> Dict[str, Any]:
    """Report what is actually enforcing something, and what is not."""
    return {
        "process_tree": (
            "job-object" if command.kind == process_group.KIND_WINDOWS_JOB else "process-group"
        ),
        "resource_limits": dict(command.limits) or None,
        "integrity_level": INTEGRITY_UNCHANGED,
        "disabled_by_caller": bool(disable_sandbox),
        "note": (
            "Resource limits and process-tree termination only; commands are not confined to the "
            "workspace and this is not a security boundary."
        ),
    }
