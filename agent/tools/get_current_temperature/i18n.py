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

ZH_TW = ToolText(
    description="取得指定地點目前的氣溫。",
    parameters={
        "location": "城市與國家，例如 'Paris, France'。",
        "unit": "溫度單位（預設為攝氏）。",
    },
)

FR = ToolText(
    description="Renvoie la température actuelle à un endroit donné.",
    parameters={
        "location": "Ville et pays, par exemple 'Paris, France'.",
        "unit": "Unité de température (Celsius par défaut).",
    },
)

DE = ToolText(
    description="Gibt die aktuelle Temperatur an einem angegebenen Ort zurück.",
    parameters={
        "location": "Stadt und Land, z. B. 'Paris, France'.",
        "unit": "Temperatureinheit (Standard: Celsius).",
    },
)

RU = ToolText(
    description="Возвращает текущую температуру в указанном месте.",
    parameters={
        "location": "Город и страна, например 'Paris, France'.",
        "unit": "Единица температуры (по умолчанию — Цельсий).",
    },
)
