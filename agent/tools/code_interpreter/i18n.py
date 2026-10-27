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

ZH_TW = ToolText(
    description="執行 Python 程式碼以完成計算與資料處理。任何複雜計算或資料處理都"
    "必須使用這個工具。",
    parameters={
        "code": "要執行的 Python 程式碼。使用 Python 運算子：乘方用 **（2 ** 10），"
        "不要用 ^；在 Python 裡 ^ 是按位元互斥或（XOR）。",
    },
)

FR = ToolText(
    description="Exécute du code Python pour effectuer des calculs et traiter des données. "
    "Cet outil est obligatoire pour tout calcul complexe ou tout traitement de données.",
    parameters={
        "code": "Le code Python à exécuter. Utilisez les opérateurs Python : ** pour la "
        "puissance (2 ** 10) et non ^, qui est un OU exclusif bit à bit en Python.",
    },
)

DE = ToolText(
    description="Führt Python-Code aus, um Berechnungen und Datenverarbeitung durchzuführen. "
    "Für jede komplexe Berechnung oder Datenverarbeitung muss dieses Werkzeug verwendet werden.",
    parameters={
        "code": "Der auszuführende Python-Code. Python-Operatoren verwenden: ** für Potenzen "
        "(2 ** 10), nicht ^ — ^ ist in Python ein bitweises XOR.",
    },
)

RU = ToolText(
    description="Выполняет код Python для вычислений и обработки данных. Для любых сложных "
    "вычислений и обработки данных нужно использовать именно этот инструмент.",
    parameters={
        "code": "Код Python для выполнения. Используйте операторы Python: ** для возведения "
        "в степень (2 ** 10), а не ^ — в Python ^ это побитовое исключающее ИЛИ.",
    },
)
