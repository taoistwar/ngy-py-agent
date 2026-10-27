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

ZH_TW = ToolText(
    description="取得指定時區的目前日期與時間。",
    parameters={
        "timezone": (
            "時區名稱（例如 'America/New_York'、'Europe/London'、'Asia/Tokyo'）。"
            "請使用標準 IANA 時區名稱。"
        ),
    },
)

FR = ToolText(
    description="Renvoie la date et l'heure actuelles dans le fuseau horaire indiqué.",
    parameters={
        "timezone": (
            "Nom du fuseau horaire (par exemple 'America/New_York', 'Europe/London', "
            "'Asia/Tokyo'). Utilisez les noms standard IANA."
        ),
    },
)

DE = ToolText(
    description="Gibt das aktuelle Datum und die aktuelle Uhrzeit in der angegebenen Zeitzone zurück.",
    parameters={
        "timezone": (
            "Name der Zeitzone (z. B. 'America/New_York', 'Europe/London', 'Asia/Tokyo'). "
            "Bitte die standardisierten IANA-Namen verwenden."
        ),
    },
)

RU = ToolText(
    description="Возвращает текущую дату и время в указанном часовом поясе.",
    parameters={
        "timezone": (
            "Название часового пояса (например, 'America/New_York', 'Europe/London', "
            "'Asia/Tokyo'). Используйте стандартные имена IANA."
        ),
    },
)
