"""Chinese display text for ``code_interpreter``.

The model always sees the English description and schema (``spec.py``); this is
read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description="执行 Python 代码以完成计算与数据处理。任何复杂计算或数据处理都必须使用"
    "这个工具。",
    parameters={
        "code": "要执行的 Python 代码。使用 Python 运算符：乘方用 **（2 ** 10），不要用 ^；"
        "Python 里 ^ 是按位异或。",
    },
)
