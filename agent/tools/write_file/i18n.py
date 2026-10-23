"""Chinese display text for ``write_file``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "创建文本文件，或替换它的全部内容。路径以工作空间根目录为基准解析且不能越出；"
        "全局允许/拒绝策略叠加生效。写入的是整个文件 —— 不做追加，原内容会消失。覆盖已有文件"
        "的前提是本次任务里 read_file 已完整读过该文件（第 1 行、不带 'limit'）且文件之后没有"
        "变化，否则调用会被拒绝，因此没见过的文件永远不会被毁掉。父目录必须已存在。内容按 "
        "'encoding'（必填）编码；字节序标记与现有换行符会保留，新文件使用 LF 换行和 0644 "
        "权限。写入是原子的。要改文件的一部分请用 edit_file；要追加，把 edit_file 的锚点放在"
        "文件最后一行。"
    ),
    parameters={
        "file_path": "文件路径，相对于工作空间根目录。",
        "content": "文件的新完整内容，会替换原有内容；空字符串表示清空文件。",
        "encoding": (
            "编码内容所用的文本编码（必填）。除非文件需要其它编码，否则用 UTF-8。"
            "字节序标记优先于此值。"
        ),
    },
)
