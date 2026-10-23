"""Chinese display text for ``exec_command``.

Built rather than written out, because the description names the shell this
machine actually has - the same reason ``description.py`` builds the English one.
It is a function instead of a module constant so importing this module does not
start shell detection.
"""

from __future__ import annotations

import platform
from typing import Any, Dict, Optional

from agent.tools.shell_platform import FAMILY_CMD, FAMILY_POWERSHELL, detect_shell
from agent.tools.spec import ToolText


def _dialect_hint(shell: Any) -> str:
    if shell.family == FAMILY_POWERSHELL:
        return (
            "命令在 PowerShell 7+ 中运行，请写 PowerShell 语法：环境变量用 '$env:NAME'，"
            "语句用 ';' 连接，仅在 cmd 内建命令前加 'cmd /c'。"
        )
    if shell.family == FAMILY_CMD:
        return (
            "命令在 cmd.exe 中运行，请写 cmd 语法：环境变量用 '%NAME%'，用 '&&' 连接，"
            "避免使用 PowerShell cmdlet。"
        )
    return (
        f"命令在 {shell.display}（POSIX shell）中运行，请写 POSIX 语法：环境变量用 '$NAME'，"
        "用 '&&' 连接，使用 POSIX 工具。"
    )


def _tty_hint(shell: Any) -> str:
    """What a pseudo terminal buys, and what it costs - in Chinese."""
    hint = (
        "'tty' 会把命令接到伪终端而不是普通管道，因此会检查终端的程序（颜色、进度条、提示符）"
        "会像面对真人一样工作。代价是没有独立的 stderr —— 终端会把 stderr 并进 stdout —— "
        "并且每行返回都以回车符结尾。前台运行的 'tty' 命令无法应答，需要回复提示时请配合 "
        "'run_in_background'。"
    )
    if shell.family in (FAMILY_POWERSHELL, FAMILY_CMD):
        hint += (
            "在 Windows 上，终端会在命令自身输出之前打印一小段转义序列握手，"
            "你输入的一个换行会作为 Enter 送达。"
        )
    return hint


def build_description(shell: Optional[Any] = None) -> str:
    """The Chinese description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "运行 shell 命令。本机没有找到受支持的 shell"
            f"（{platform.system()}），任何调用都会失败。"
        )
    return (
        f"运行 shell 命令并返回输出。{_dialect_hint(shell)} "
        "命令从工作空间根目录开始执行。本工具不限制路径：命令能读写进程用户可访问的任何位置，"
        "因此请把路径限制在工作空间内，项目文件使用 read_file/edit_file/write_file 处理。"
        "'timeout' 单位是毫秒（默认 120000，最大 1800000）；超时后整个进程树会被停止，"
        "'interrupted' 为 true。超出响应预算的输出会写入文件，结果里给出简短预览和该文件路径，"
        "可以用 read_file 读回。'run_in_background' 不等待命令结束就返回，给出 pid、session_id "
        "和日志路径；把这个 session_id 交给 write_stdin 就能向它输入并读取输出。命令会一直运行"
        "到退出或任务结束，任务结束时会被停止。给 'description' 写一句简短说明，讲清命令在做"
        "什么：确认命令时会给用户看，也会记入审计。"
        f"{_tty_hint(shell)}"
        "'dangerouslyDisableSandbox' 只跳过额外的隔离层（完整性级别）；资源限制与进程树终止"
        "始终生效。"
    )


ZH_CN_PARAMETERS: Dict[str, str] = {
    "command": "在该平台 shell 中执行的命令行。",
    "timeout": (
        "超时时间，单位毫秒。默认 120000（2 分钟），最大 1800000（30 分钟）。"
        "超时后进程树会被停止，'interrupted' 为 true。"
    ),
    "description": (
        "用平实语言简短说明这条命令做什么，写给要决定是否允许它的人看"
        "（例如 '安装 lodash 工具库'）。执行前会显示在确认框里，并记入审计。"
    ),
    "run_in_background": (
        "启动命令后立即返回，不等待结果。结果里带 pid、session_id（交给 write_stdin 交互）"
        "和日志路径。任务结束时命令会被停止。默认 false。"
    ),
    "tty": "true 为命令分配 PTY；false 或省略则使用普通管道。",
    "dangerouslyDisableSandbox": (
        "跳过这条命令的额外隔离层（完整性级别）。资源限制与进程树终止不能关闭。默认 false。"
    ),
}


def zh_cn(shell: Optional[Any] = None) -> ToolText:
    """The ``zh-CN`` text; called while the spec is built, not on import."""
    return ToolText(description=build_description(shell), parameters=ZH_CN_PARAMETERS)
