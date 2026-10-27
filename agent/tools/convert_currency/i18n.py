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

ZH_TW = ToolText(
    description="把金額從一種貨幣換算成另一種。需要貨幣換算或取得最新匯率時，"
    "必須使用這個工具。",
    parameters={
        "amount": "要換算的金額。",
        "from_currency": "來源貨幣代碼（例如 'USD'、'EUR'）。",
        "to_currency": "目標貨幣代碼（例如 'USD'、'EUR'）。",
    },
)

FR = ToolText(
    description="Convertit un montant d'une devise vers une autre. Cet outil est "
    "obligatoire pour les conversions de devises et les taux de change à jour.",
    parameters={
        "amount": "Montant à convertir.",
        "from_currency": "Code de la devise source (par exemple 'USD', 'EUR').",
        "to_currency": "Code de la devise cible (par exemple 'USD', 'EUR').",
    },
)

DE = ToolText(
    description="Rechnet einen Betrag von einer Währung in eine andere um. Für "
    "Währungsumrechnungen und aktuelle Wechselkurse muss dieses Werkzeug verwendet werden.",
    parameters={
        "amount": "Der umzurechnende Betrag.",
        "from_currency": "Code der Ausgangswährung (z. B. 'USD', 'EUR').",
        "to_currency": "Code der Zielwährung (z. B. 'USD', 'EUR').",
    },
)

RU = ToolText(
    description="Переводит сумму из одной валюты в другую. Для конвертации валют и "
    "актуальных курсов нужно использовать именно этот инструмент.",
    parameters={
        "amount": "Сумма для перевода.",
        "from_currency": "Код исходной валюты (например, 'USD', 'EUR').",
        "to_currency": "Код целевой валюты (например, 'USD', 'EUR').",
    },
)
