#!/usr/bin/env python3
"""
Project pre-commit hook:
  - 仅校验暂存文件中的文本文件是否 UTF-8 可解码
  - 检测明显的乱码特征，避免错误编码继续提交
"""

from __future__ import annotations

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
    count = 0
    for token in SUSPECT_TOKENS:
        count += text.count(token)
    return count


def main() -> int:
    bad_files: list[str] = []

    for path in staged_files():
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
            bad_files.append(f"{path}: 含有替代字符（�），疑似乱码或解码失败")
            continue

        if len(text) > 200 and detect_garble(text) >= 6:
            bad_files.append(
                f"{path}: 检测到疑似乱码特征（高频出现异常中文符号），请检查编码是否被错误转换"
            )

    if not bad_files:
        return 0

    print("[pre-commit] 检测到编码问题：")
    for item in bad_files:
        print(f" - {item}")
    print("请修复后再提交（保存为 UTF-8 无 BOM）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
