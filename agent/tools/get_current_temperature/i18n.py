"""Chinese display text for ``get_current_temperature``.

The model always sees the English description and schema (``spec.py``); this is
read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description="获取指定地点的当前气温。",
    parameters={
        "location": "城市与国家，例如 'Paris, France'。",
        "unit": "温度单位（默认摄氏）。",
    },
)
