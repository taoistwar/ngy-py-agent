"""Chinese display text for ``grep``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "用正则表达式搜索文件内容（Python 're' 语法，默认逐行匹配）。返回形状由 "
        "'output_mode' 决定：'files_with_matches'（默认）列出含匹配的文件，按修改时间从新"
        "到旧；'content' 返回命中行，形如 'path:line:text'，上下文行为 'path-line-text'，"
        "不相邻的组之间用 '--' 分隔；'count' 返回每个文件的命中行数与总数。默认逐行匹配，"
        "设置 'multiline' 后模式可以跨行。隐藏文件同样会被搜索，但版本库元数据（.git 等）、"
        "已安装依赖与构建产物（node_modules、.venv、dist、build、target…）、二进制文件、"
        "超过 8MB 的文件，以及看起来像凭证的文件会被跳过——最后一类会列在 "
        "'skipped_sensitive' 里，因为它们仍可用 read_file 读取；把 'path' 显式指向被跳过的"
        "目录则会照常搜索它。工具的忽略规则不读 .gitignore，因此被它忽略的文件仍会参与搜索。"
        "'glob' 与 'type' 用于缩小搜索的文件范围。单次最多返回 250 条输出行/路径，用 "
        "'offset'/'head_limit' 翻页（'head_limit' 为 0 表示不限），不要靠放宽模式硬凑；"
        "超长行会在 500 字符处截断。返回的路径相对于工作空间根，可直接传给 read_file。"
        "想按文件名找文件用 glob，想找某段代码写在哪里用 grep。"
    ),
    parameters={
        "pattern": (
            "要搜索的正则表达式（Python 're' 语法）。特殊字符必须转义，"
            "例如找 'interface{}' 要写成 'interface\\{\\}'。"
        ),
        "path": (
            "要搜索的文件或目录，相对于工作空间根（绝对路径只有在仍位于工作空间内时才被"
            "接受）。省略时使用工作空间根。"
        ),
        "glob": "只搜索文件名匹配该模式的文件，例如 '*.py' 或 '*.{ts,tsx}'。多个模式可用逗号或空格分隔。",
        "type": (
            "只搜索某种语言的文件，例如 'py'、'js'、'ts'、'rust'、'go'、'java'、'json'、"
            "'yaml'、'markdown'、'sh'。未知名称会被拒绝并给出支持列表。"
        ),
        "output_mode": (
            "'files_with_matches'（默认）只看路径，'content' 看命中行，'count' 数每个文件"
            "命中多少行。"
        ),
        "case_insensitive": "匹配时忽略大小写。默认 false。",
        "multiline": (
            "允许模式跨行（'.' 也能匹配换行，便于搜 'struct \\{[\\s\\S]*?field' 这类结构）。"
            "默认 false。"
        ),
        "line_numbers": (
            "在 'content' 模式下给每行加上 1 起始行号。默认 true；其它模式始终按文件汇报结果。"
        ),
        "context": "在 'content' 模式下每条命中前后各显示几行。优先于 'before_context'/'after_context'。",
        "before_context": "在 'content' 模式下每条命中前显示几行。",
        "after_context": "在 'content' 模式下每条命中后显示几行。",
        "head_limit": (
            "最多返回多少条输出行（content）、路径（files_with_matches）或计数（count）。"
            "默认 250；填 0 表示不限。"
        ),
        "offset": "先跳过多少条结果，用于翻到下一页。",
    },
)
