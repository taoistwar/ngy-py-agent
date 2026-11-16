"""Project instructions shipped with the workspace: ``AGENTS.md`` (https://agents.md/).

The format is deliberately minimal - plain Markdown, no schema - and its rules are the
whole specification:

- one file at the repository root carries the project-wide rules;
- a monorepo may nest one per package, and **the file closest to the edited path wins**;
- an instruction the user states in the conversation outranks the file.

So this module finds the files under the session's workspace root, and turns them into
one system-prompt block: the root file is inlined (that is the one that applies to every
task), while the nested ones are only *listed*, with a note to read the nearest one
before editing inside that folder. Inlining every nested file would spend the context
budget on packages the task never touches, and the "closest wins" rule means the model
has to be pointed at the right file anyway.

"Workspace" here always means the folder a task has been bound to, never this
application's own source tree: the repository's ``AGENTS.md`` is guidance for the people
editing it, and its rules have nothing to say about the user's project.

Nothing here writes: the workspace is only read, so a task can never edit its own rules
through this path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

AGENTS_FILENAME = "AGENTS.md"
# The pre-standard singular name. The site suggests renaming with a symlink back to the
# old name; reading it directly covers the repositories that never renamed.
LEGACY_FILENAME = "AGENT.md"

ENABLED_ENV = "AGENTS_MD_ENABLED"
MAX_BYTES_ENV = "AGENTS_MD_MAX_BYTES"
# Same ceiling Codex uses for its project document: large enough for real instructions,
# small enough that a runaway file cannot eat the context on its own.
DEFAULT_MAX_BYTES = 32 * 1024
# The range the admin API accepts for the byte cap: below 1 KiB nothing useful fits,
# above 1 MiB the cap is no longer protecting the context.
MIN_MAX_BYTES = 1024
MAX_BYTES_LIMIT = 1024 * 1024

# How deep to look for nested files, and how many of them to name. A monorepo can hold
# dozens (OpenAI's own repository had 88 at one point); the list is an index, not the
# instructions themselves, so a short one stays useful.
SCAN_DEPTH = 3
NESTED_FILE_LIMIT = 20

# Directories that never carry project instructions worth scanning: dependencies and
# build output. Dot-directories are skipped by the same rule that skips these (see
# ``_skipped``).
SKIPPED_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        "dist",
        "build",
        "target",
        "vendor",
    }
)


@dataclass(frozen=True)
class AgentsMdSettings:
    """How much of the workspace's instructions to read.

    The web layer resolves these from env + database and hands the result to the loop;
    passing ``None`` anywhere means "ask the environment" (:func:`settings_from_env`).
    """

    enabled: bool = True
    max_bytes: int = DEFAULT_MAX_BYTES


@dataclass(frozen=True)
class AgentsMdDocument:
    """One instruction file that was read into the prompt."""

    path: Path
    relative_path: str
    content: str
    truncated: bool


@dataclass(frozen=True)
class AgentsMdInstructions:
    """What a workspace's ``AGENTS.md`` files say, ready to be formatted."""

    root: Optional[AgentsMdDocument]
    # Relative paths of the nested files, closest-to-the-root first.
    nested: Tuple[str, ...] = ()
    # Nested files the index had no room for: the model can still find them with glob.
    skipped: int = 0

    def describe(self) -> Dict[str, Any]:
        """Debug-event form: what was loaded, without the instruction text itself."""
        root = self.root
        return {
            "root": root.relative_path if root is not None else "",
            "root_chars": len(root.content) if root is not None else 0,
            "root_truncated": bool(root.truncated) if root is not None else False,
            "nested": list(self.nested),
            "nested_skipped": self.skipped,
        }


def enabled() -> bool:
    """Whether ``AGENTS.md`` is read at all; ``AGENTS_MD_ENABLED=0`` turns it off."""
    raw = (os.getenv(ENABLED_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def max_bytes() -> int:
    """Byte ceiling for one instruction file, overridable per deployment."""
    raw = (os.getenv(MAX_BYTES_ENV) or "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_BYTES
    return value if value > 0 else DEFAULT_MAX_BYTES


def settings_from_env() -> AgentsMdSettings:
    """The environment's defaults; the admin API layers database values on top."""
    return AgentsMdSettings(enabled=enabled(), max_bytes=max_bytes())


def load_instructions(
    base_dir: Optional[str],
    settings: Optional[AgentsMdSettings] = None,
) -> Optional[AgentsMdInstructions]:
    """Read the workspace's instruction files, or ``None`` when there are none.

    Only a bound workspace is read: an unbound session has no project to speak for, and
    its scratch directory is not one. A file that cannot be read, or is empty, is
    treated as absent rather than as an error - a broken ``AGENTS.md`` must not stop a
    task from running.
    """
    settings = settings or settings_from_env()
    if not settings.enabled:
        return None
    text = (base_dir or "").strip()
    if not text:
        return None
    root = Path(text).expanduser()
    try:
        if not root.is_dir():
            return None
        root = root.resolve()
    except OSError:
        return None

    limit = settings.max_bytes
    document = _load_root(root, limit)
    nested, skipped = _nested_paths(root)
    if document is None and not nested:
        return None
    return AgentsMdInstructions(root=document, nested=nested, skipped=skipped)


def append_project_instructions(prompt: str, instructions: AgentsMdInstructions) -> str:
    """Put the instruction block after ``prompt``, keeping the caller's text intact."""
    return f"{prompt}\n\n{format_instructions(instructions)}"


def with_agents_md(
    prompt: str,
    base_dir: Optional[str],
    settings: Optional[AgentsMdSettings] = None,
) -> str:
    """``prompt`` plus this workspace's instruction block, when it has one.

    The one-call form, for a caller that owns its prompt. The loop composes the two
    steps itself because it also logs which files were loaded.
    """
    instructions = load_instructions(base_dir, settings)
    if instructions is None:
        return prompt
    return append_project_instructions(prompt, instructions)


def format_instructions(instructions: AgentsMdInstructions) -> str:
    """The Markdown block as the model sees it: root text inlined, nested ones indexed."""
    blocks = []
    if instructions.root is not None:
        blocks.append(_root_block(instructions.root))
    if instructions.nested:
        blocks.append(
            _nested_block(
                instructions.nested,
                instructions.skipped,
                has_root=instructions.root is not None,
            )
        )
    return "\n\n".join(blocks)


def _root_block(document: AgentsMdDocument) -> str:
    return (
        "## Project instructions (AGENTS.md)\n"
        "\n"
        "This workspace carries agent instructions in `AGENTS.md` (https://agents.md/): "
        "project rules that apply to every task here. Follow them. A requirement stated "
        "by the user in the conversation outranks them.\n"
        "\n"
        f"Instructions from `{document.relative_path}`:\n"
        "\n"
        f"{document.content}"
    )


def _nested_block(nested: Tuple[str, ...], skipped: int, has_root: bool) -> str:
    if has_root:
        intro = (
            "### Nested AGENTS.md files\n"
            "\n"
            "More specific instructions live closer to the code. Before editing files "
            "below one of these folders, read its `AGENTS.md` with read_file: the closest "
            "file takes precedence over the instructions above.\n"
        )
    else:
        intro = (
            "## Project instructions (AGENTS.md)\n"
            "\n"
            "This workspace has no root `AGENTS.md`, but these folders carry their own "
            "instructions (https://agents.md/). Read the one closest to the files you "
            "touch before editing:\n"
        )
    lines = [intro]
    lines.extend(f"- `{path}`" for path in nested)
    if skipped > 0:
        lines.append(
            f"- ({skipped} more not listed; find them with the glob tool, pattern "
            f'`**/{AGENTS_FILENAME}`)'
        )
    return "\n".join(lines)


def _load_root(root: Path, limit: int) -> Optional[AgentsMdDocument]:
    for name in (AGENTS_FILENAME, LEGACY_FILENAME):
        candidate = root / name
        if not candidate.is_file():
            continue
        document = _read_document(candidate, root, limit)
        if document is not None:
            return document
    return None


def _read_document(path: Path, root: Path, limit: int) -> Optional[AgentsMdDocument]:
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    body = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        return None
    content, truncated = _truncate(body, limit)
    if truncated:
        content += (
            f"\n\n[Truncated at {limit} bytes ({MAX_BYTES_ENV}={limit}). Ask the user, or "
            "read the rest with read_file.]"
        )
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - the file was just found under root
        relative = path.as_posix()
    return AgentsMdDocument(
        path=path, relative_path=relative, content=content, truncated=truncated
    )


def _truncate(text: str, limit: int) -> Tuple[str, bool]:
    """Cut ``text`` on a byte boundary, never in the middle of a character."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    return data[:limit].decode("utf-8", "ignore"), True


def _nested_paths(root: Path) -> Tuple[Tuple[str, ...], int]:
    """Find nested instruction files, skipping what the index never needs."""
    found = []
    for current, dirnames, filenames in os.walk(root):
        try:
            depth = len(Path(current).relative_to(root).parts)
        except ValueError:  # pragma: no cover - os.walk only yields children of root
            continue
        if depth >= SCAN_DEPTH:
            # Deep enough: still read this folder's own files, but stop descending.
            dirnames[:] = []
        else:
            dirnames[:] = sorted(name for name in dirnames if not _skipped(name))
        name = _instruction_name(filenames)
        if name is None:
            continue
        if depth == 0:
            # The root file is inlined above (under either name); listing it again as
            # "nested" would tell the model to read what it has already been given.
            continue
        found.append((depth, (Path(current).relative_to(root) / name).as_posix()))

    found.sort(key=lambda item: (item[0], item[1]))
    paths = tuple(path for _, path in found[:NESTED_FILE_LIMIT])
    return paths, max(0, len(found) - NESTED_FILE_LIMIT)


def _skipped(dirname: str) -> bool:
    """Dependencies, build output and every dot-directory (``.git``, ``.venv``...)."""
    return dirname.startswith(".") or dirname in SKIPPED_DIRS


def _instruction_name(filenames: Sequence[str]) -> Optional[str]:
    """Which instruction file a folder carries, preferring the standard name."""
    for name in (AGENTS_FILENAME, LEGACY_FILENAME):
        if name in filenames:
            return name
    return None
