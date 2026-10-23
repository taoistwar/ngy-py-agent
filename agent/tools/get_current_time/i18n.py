"""Chinese display text for ``get_current_time``.

The model always sees the English description and schema (``description.py`` /
``spec.py``); this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description="获取指定时区的当前日期与时间。",
    parameters={
        "timezone": "时区名称（例如 'America/New_York'、'Europe/London'、'Asia/Tokyo'）。"
        "请使用标准 IANA 时区名。",
    },
)
