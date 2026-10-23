"""Chinese display text for ``edit_file``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "在文本文件里替换一段完全匹配的字符串。路径以工作空间根目录为基准解析且不能越出；"
        "全局允许/拒绝策略叠加生效。'old_string' 按字节完全匹配，必须与文件中的内容一模一样"
        "（包括换行符）：把 read_file 输出中的 'N<TAB>' 前缀去掉后原样使用。匹配必须唯一 —— "
        "'old_string' 出现多次时调用会被拒绝，需要补充上下文，或传 replace_all=true 替换所有"
        "出现。解码使用 'encoding'（默认 UTF-8），文件带字节序标记时以标记为准；无法解码时会"
        "返回列出候选编码的错误，请用正确的 'encoding' 重试。插入的文本会被改写成文件现有的"
        "换行符，字节序标记会保留；只重写匹配到的范围，其余字节不会被改动。写入是原子的，"
        "文件权限会保留。"
    ),
    parameters={
        "file_path": "文件路径，相对于工作空间根目录。",
        "old_string": "要被替换的原文。除非 'replace_all' 为 true，否则必须唯一。",
        "new_string": "替换后的文本。空字符串表示删除匹配到的内容。",
        "replace_all": "替换所有出现，而不是要求唯一匹配。默认 false。",
        "encoding": (
            "解码并重新编码文件所用的文本编码。默认 UTF-8。使用 read_file 报告过的 "
            "'encoding'。字节序标记优先于此值。"
        ),
    },
)
