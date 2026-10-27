"""The ``type`` filter: a language name mapped to the extensions it owns.

A small hand-written table rather than a ripgrep-compatible type database: the
point is "search the Python files", not to reproduce every file type ripgrep
knows. Extension matching is case insensitive, so ``MAIN.PY`` is a Python file
on Windows.

Names are the canonical ones; ``ALIASES`` covers the spellings models actually
try (``python``, ``javascript``, ``c++``, ``shell``...). An unknown name is an
error listing what is supported, never a silent "no files matched" - a typo that
returns nothing looks exactly like an empty repository.
"""

from typing import Dict, Optional, Tuple

FILE_TYPES: Dict[str, Tuple[str, ...]] = {
    "c": ("c", "h"),
    "cpp": ("cc", "cpp", "cxx", "hpp", "hh", "hxx"),
    "csharp": ("cs",),
    "css": ("css", "scss", "sass", "less"),
    "dart": ("dart",),
    "go": ("go",),
    "html": ("html", "htm"),
    "java": ("java",),
    "js": ("js", "mjs", "cjs", "jsx"),
    "json": ("json", "jsonc"),
    "kotlin": ("kt", "kts"),
    "lua": ("lua",),
    "markdown": ("md", "mdx"),
    "php": ("php",),
    "py": ("py", "pyi"),
    "rb": ("rb",),
    "rust": ("rs",),
    "scala": ("scala",),
    "sh": ("sh", "bash", "zsh", "fish"),
    "sql": ("sql",),
    "swift": ("swift",),
    "toml": ("toml",),
    "ts": ("ts", "tsx", "mts", "cts"),
    "vue": ("vue",),
    "yaml": ("yaml", "yml"),
}

ALIASES: Dict[str, str] = {
    "c#": "csharp",
    "c++": "cpp",
    "golang": "go",
    "javascript": "js",
    "jsx": "js",
    "kt": "kotlin",
    "md": "markdown",
    "php": "php",
    "python": "py",
    "ruby": "rb",
    "rs": "rust",
    "shell": "sh",
    "typescript": "ts",
    "yml": "yaml",
}


def supported_types() -> Tuple[str, ...]:
    """Every name ``type`` accepts, canonical ones only."""
    return tuple(sorted(FILE_TYPES))


def extensions_for(name: str) -> Optional[Tuple[str, ...]]:
    """Extensions owned by ``name``, or ``None`` when it is not a known type."""
    cleaned = (name or "").strip().lower()
    if not cleaned:
        return None
    key = ALIASES.get(cleaned, cleaned)
    return FILE_TYPES.get(key)
