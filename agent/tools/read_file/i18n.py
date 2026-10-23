"""Chinese display text for ``read_file``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "读取文本文件。会话绑定了工作空间时，路径以工作空间根目录为基准解析且不能越出；"
        "全局允许/拒绝策略始终叠加生效。返回请求的行区间，每行前是该行的 1 起始行号和单个"
        "制表符。省略 'limit' 表示从 'offset' 读到文件末尾（文件大于 256KB 时会被拒绝）。"
        "给出 'limit' 则读取指定行数；返回文本超过输出 token 预算时会被拒绝，因此请优先读"
        "小范围，需要时用新的 'offset' 继续。解码使用 'encoding'（默认 UTF-8），文件带字节"
        "序标记时以标记为准；无法解码时会返回列出候选编码的错误，请用正确的 'encoding' 重试。"
        "结果会报告实际生效的 'encoding'，把这个值原样传给 edit_file。原始换行符会被保留，"
        "因此去掉 'N<TAB>' 前缀后的文本可以原样作为 edit_file 的 'old_string'。"
    ),
    parameters={
        "file_path": "文件路径，相对于工作空间根目录（绝对路径只有在仍位于工作空间内时才被接受）。",
        "offset": "起始行号（1 起始）。默认 1；0 视为 1。",
        "limit": "要读取的行数。省略（或传 0）表示从 'offset' 读到文件末尾。",
        "encoding": (
            "解码文件所用的文本编码（必填）。除非有特别理由，否则用 UTF-8。"
            "字节序标记优先于此值。解码失败时错误里会列出候选编码，用合适的那个重试。"
        ),
    },
)
