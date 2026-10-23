"""Chinese display text for ``convert_currency``.

The model always sees the English description and schema (``spec.py``); this is
read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description="把金额从一种货币换算成另一种。要做货币换算、拿到最新汇率，"
    "必须使用这个工具。",
    parameters={
        "amount": "要换算的金额。",
        "from_currency": "源货币代码（例如 'USD'、'EUR'）。",
        "to_currency": "目标货币代码（例如 'USD'、'EUR'）。",
    },
)
