#!/usr/bin/env python3
"""Run local checks used by CI for backend and web-admin."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parent.parent
WEB_ADMIN = ROOT / "web-admin"


def resolve_executable(name: str) -> str:
    if shutil.which(name):
        return name
    if os.name == "nt":
        for suffix in (".cmd", ".bat", ".exe"):
            candidate = f"{name}{suffix}"
            if shutil.which(candidate):
                return candidate
    raise FileNotFoundError(f"Executable not found: {name}")


def run(cmd, cwd: Path | None = None, check: bool = True) -> int:
    if not cmd:
        return 0
    command = [str(part) for part in cmd]
    command[0] = resolve_executable(command[0])
    label = " ".join(command)
    print(f"\n==> {label}")
    if os.name == "nt":
        command_line = " ".join(command)
        result = subprocess.run(command_line, cwd=str(cwd) if cwd else None, shell=True)
    else:
        result = subprocess.run(command, cwd=str(cwd) if cwd else None)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def require(cmd: str) -> None:
    try:
        resolve_executable(cmd)
    except FileNotFoundError:
        print(f"Missing required executable: {cmd}")
        raise SystemExit(1)


def main() -> None:
    require("uv")
    require("npm")

    run(["uv", "sync"], cwd=ROOT)
    run(
        ["uv", "run", "python", "-m", "compileall", "-q", "main.py", "agent/agent_loop.py"],
        cwd=ROOT,
    )
    run(["uv", "run", "python", "main.py", "--help"], cwd=ROOT)

    # ``test/`` is intentionally not a package, so the files are run one by one
    # instead of using ``unittest discover``.
    for test_file in sorted((ROOT / "test").rglob("*_test.py")):
        run(["uv", "run", "python", str(test_file.relative_to(ROOT))], cwd=ROOT)

    npm_status = run(["npm", "ci"], cwd=WEB_ADMIN, check=False)
    if npm_status != 0:
        print("npm ci failed, fallback to npm install for local environment.")
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=WEB_ADMIN)
    run(["npm", "run", "i18n:check"], cwd=WEB_ADMIN)
    run(["npm", "run", "build"], cwd=WEB_ADMIN)

    print("\nLocal CI checks passed.")


if __name__ == "__main__":
    main()
