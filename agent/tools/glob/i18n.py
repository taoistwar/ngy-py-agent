"""Chinese display text for ``glob``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "按文件名模式查找文件。当你知道文件叫什么、但不知道它在哪个目录时用它；在"
        "read_file 之前用它，胜过猜一个路径。返回匹配的文件路径，按修改时间从新到旧，"
        "最多 100 个；'truncated' 为真表示列表不完整，此时应缩小 'path' 或把 'pattern' "
        "写得更具体，而不是翻页。模式语义与 ripgrep 的 --glob 一致：'*' 只匹配单个路径段内"
        "的字符，'**' 可跨路径段（'a/**/b' 也匹配 'a/b'），'?' 匹配一个字符，'[abc]' 是"
        "字符集，'{a,b}' 是候选列表。不含 '/' 的模式只匹配文件名，因此任意深度都算，所以 "
        "'*.py' 能找出搜索根之下的全部 Python 文件。隐藏文件与被 .gitignore 排除的文件"
        "同样会被列出，只返回普通文件、不返回目录。路径以工作空间根为基准解析且不能越出；"
        "全局允许/拒绝策略依然会隐藏它拦截的内容。返回的路径相对于工作空间根（在工作空间"
        "之外时为绝对路径），可直接原样传给 read_file。绝对路径的 'pattern' 自带搜索根，"
        "会覆盖 'path'。"
    ),
    parameters={
        "pattern": (
            "描述要找的文件名的 glob 模式，例如 '**/*.ts' 或 'src/**/test_*.py'。"
            "支持上文说明的 '**'、'*'、'?'、'[...]' 和 '{a,b}'。"
        ),
        "path": (
            "搜索目录，相对于工作空间根（绝对路径只有在仍位于工作空间内时才被接受）。"
            "省略时使用工作空间根。"
        ),
    },
)
