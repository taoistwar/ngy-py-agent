"""Filesystem-backed skill library.

Every skill is a subfolder of a single shared root folder. A skill folder may
contain a ``SKILL.md`` file whose YAML frontmatter provides the display name and
description; otherwise the folder name is used as the display name.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

SKILL_FILE_NAMES = ("SKILL.md", "skill.md", "Skill.md")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter mapping, body) for a ``---`` delimited document."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    meta: dict[str, str] = {}
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return meta, "\n".join(lines[index + 1 :])
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return {}, text


def _first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def read_skill_metadata(skill_dir: Path) -> tuple[str, str]:
    """Return ``(display_name, description)`` for one skill folder."""
    for filename in SKILL_FILE_NAMES:
        skill_file = skill_dir / filename
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = _split_frontmatter(text)
        display_name = meta.get("name") or skill_dir.name
        description = meta.get("description") or _first_body_line(body)
        return display_name, description
    return skill_dir.name, ""


def list_skills(root: str | None) -> list[dict[str, Any]]:
    """List the skill folders directly under ``root``."""
    if not root:
        return []
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        return []

    skills: list[dict[str, Any]] = []
    for child in sorted(root_path.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        display_name, description = read_skill_metadata(child)
        skills.append(
            {
                "name": child.name,
                "display_name": display_name,
                "description": description,
                "path": str(child),
            }
        )
    return skills


def resolve_skill_dir(root: str | None, name: str) -> Path | None:
    """Resolve a skill folder that is a direct child of ``root``."""
    if not root or not name or "/" in name or "\\" in name:
        return None
    root_path = Path(root).expanduser().resolve()
    target = (root_path / name).resolve()
    if target.parent != root_path or not target.is_dir():
        return None
    return target


def import_skill(root: str | None, source: str) -> dict[str, Any]:
    """Copy a local folder into the skills root as a new skill."""
    if not root:
        raise ValueError("skills root is not configured")
    source_path = Path(source).expanduser()
    if not source_path.is_dir():
        raise FileNotFoundError("Source folder not found.")

    root_path = Path(root).expanduser()
    root_path.mkdir(parents=True, exist_ok=True)
    target = root_path / source_path.name
    if target.exists():
        raise FileExistsError(f"Skill '{source_path.name}' already exists.")
    shutil.copytree(source_path, target)
    return {"name": source_path.name, "path": str(target)}


def delete_skill(root: str | None, name: str) -> bool:
    """Delete a skill folder that is a direct child of ``root``."""
    target = resolve_skill_dir(root, name)
    if target is None:
        return False
    shutil.rmtree(target)
    return True
