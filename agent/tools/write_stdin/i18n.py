"""Chinese display text for ``write_stdin``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "向 exec_command 留下的运行中命令输入内容，并读回它打印的输出。传入 exec_command "
        "为仍在运行的命令返回的 'session_id'。把 'chars' 设为要写入命令 stdin 的文本"
        "（含 '\\n' 才会发送一行）；'chars' 留空则只轮询新输出。'chars' 等于 Ctrl-C"
        "（'\\u0003'）时会中断命令而不是写入。'yield_time_ms' 限制等待输出的时长，"
        "'max_output_tokens' 限制返回多少内容。结果会说明命令仍在运行（给出 session_id）"
        "还是已结束（给出 exit_code）；已结束的会话不能复用。"
    ),
    parameters={
        "session_id": "exec_command 为仍在运行的命令返回的会话 id。已结束的会话会被拒绝。",
        "chars": (
            "写入命令 stdin 的文本。为空（默认）时只轮询新输出。"
            "单个 Ctrl-C 字符（'\\u0003'）会中断命令。"
        ),
        "yield_time_ms": (
            "等待输出的时长，单位毫秒。轮询（'chars' 为空）至少提升到 5000、上限 300000；"
            "写入最多等待 30000。默认 250。"
        ),
        "max_output_tokens": (
            "返回输出的 token 预算。默认 10000；更大的请求可能被策略压低。"
            "超出预算的输出会被持久化并返回其路径。"
        ),
    },
)
