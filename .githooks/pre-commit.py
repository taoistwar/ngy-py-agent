#!/usr/bin/env python3
"""
Project pre-commit hook:
  - 仅校验暂存文件中的文本文件是否 UTF-8 可解码
  - 检测明显的乱码特征，避免错误编码继续提交
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

CHECK_EXTS = {
    ".md",
    ".py",
    ".toml",
    ".json",
    ".yml",
    ".yaml",
    ".sh",
    ".ps1",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".css",
    ".html",
    ".txt",
    ".ini",
    ".cfg",
    ".env",
}

CHECK_NAMES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "ruff.toml",
    "uv.lock",
}

SUSPECT_TOKENS = (
    "锛",
    "鏈",
    "涓",
    "銆",
    "椤",
    "鎴",
    "浜",
    "瀹",
    "濡",
    "瑕",
    "璀",
    "鎵",
    "绂",
)


def staged_files() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    )
    files: list[Path] = []
    for line in result.stdout.splitlines():
        p = Path(line.strip())
        if p.exists():
            files.append(p)
    return files


def should_check(path: Path) -> bool:
    if path.suffix.lower() in CHECK_EXTS:
        return True
    return path.name in CHECK_NAMES


def detect_garble(text: str) -> int:
    """Count suspicious characters that sit next to another suspicious one.

    Mojibake arrives in runs (``锛堝锛夛紝``), so adjacency is the signal. Counting
    lone hits instead made this file report itself: ``SUSPECT_TOKENS`` above spells
    every one of them out, and a dictionary is not a symptom.
    """
    suspects = set(SUSPECT_TOKENS)
    return sum(
        1 for left, right in zip(text, text[1:]) if left in suspects and right in suspects
    )


def lint_python_files(paths: list[Path]) -> int:
    """Run ruff over the staged Python files; non-zero means "do not commit".

    The rule set lives in ``ruff.toml``, the same one CI and ``scripts/ci_check.py``
    use. A missing ``uv`` is a hint rather than a failure: this hook exists to catch
    mistakes, not to block a commit in a checkout that has not been set up yet.
    """
    targets = [p.as_posix() for p in paths if p.suffix.lower() == ".py"]
    if not targets:
        return 0
    if shutil.which("uv") is None:
        print("[pre-commit] 未找到 uv，跳过 ruff 检查（安装 uv 后自动启用）")
        return 0

    result = subprocess.run(
        ["uv", "run", "ruff", "check", "--force-exclude", *targets],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return 0

    print(result.stdout.rstrip())
    print(result.stderr.rstrip())
    print("[pre-commit] ruff 检查未通过，请修复后再提交（规则见 ruff.toml）。")
    return 1


def main() -> int:
    # Windows consoles are often cp936, and a check that finds unencodable text must
    # not itself die printing about it: fall back to "?" instead.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    files = staged_files()
    bad_files: list[str] = []

    for path in files:
        if not should_check(path):
            continue

        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            bad_files.append(f"{path}: 非 UTF-8 编码，位置 {exc.start} 附近无法解码")
            continue

        if text.startswith("\ufeff"):
            bad_files.append(f"{path}: 文件以 UTF-8 BOM 开头，建议移除")

        if "\ufffd" in text:
            # Spelled out rather than embedded: a message about a broken character
            # must not carry one, or printing it dies on a cp936 console.
            bad_files.append(f"{path}: 含有替代字符 U+FFFD，疑似乱码或解码失败")
            continue

        if len(text) > 200 and detect_garble(text) >= 6:
            bad_files.append(
                f"{path}: 检测到疑似乱码特征（高频出现异常中文符号），请检查编码是否被错误转换"
            )

    if bad_files:
        print("[pre-commit] 检测到编码问题：")
        for item in bad_files:
            print(f" - {item}")
        print("请修复后再提交（保存为 UTF-8 无 BOM）。")

    lint_status = lint_python_files(files)
    return 1 if bad_files or lint_status else 0


if __name__ == "__main__":
    sys.exit(main())
