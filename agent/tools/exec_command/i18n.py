"""Translated display text for ``exec_command``.

Built rather than written out, because the description names the shell this
machine actually has - the same reason ``description.py`` builds the English one.
Each language is a function instead of a module constant so importing this module
does not start shell detection.
"""

from __future__ import annotations

import platform
from typing import Any, Dict, Optional

from agent.tools.shell_platform import FAMILY_CMD, FAMILY_POWERSHELL, detect_shell
from agent.tools.spec import ToolText


def _dialect_hint(shell: Any) -> str:
    if shell.family == FAMILY_POWERSHELL:
        return (
            "命令在 PowerShell 7+ 中运行，请写 PowerShell 语法：环境变量用 '$env:NAME'，"
            "语句用 ';' 连接，仅在 cmd 内建命令前加 'cmd /c'。"
        )
    if shell.family == FAMILY_CMD:
        return (
            "命令在 cmd.exe 中运行，请写 cmd 语法：环境变量用 '%NAME%'，用 '&&' 连接，"
            "避免使用 PowerShell cmdlet。"
        )
    return (
        f"命令在 {shell.display}（POSIX shell）中运行，请写 POSIX 语法：环境变量用 '$NAME'，"
        "用 '&&' 连接，使用 POSIX 工具。"
    )


def _tty_hint(shell: Any) -> str:
    """What a pseudo terminal buys, and what it costs - in Chinese."""
    hint = (
        "'tty' 会把命令接到伪终端而不是普通管道，因此会检查终端的程序（颜色、进度条、提示符）"
        "会像面对真人一样工作。代价是没有独立的 stderr —— 终端会把 stderr 并进 stdout —— "
        "并且每行返回都以回车符结尾。前台运行的 'tty' 命令无法应答，需要回复提示时请配合 "
        "'run_in_background'。"
    )
    if shell.family in (FAMILY_POWERSHELL, FAMILY_CMD):
        hint += (
            "在 Windows 上，终端会在命令自身输出之前打印一小段转义序列握手，"
            "你输入的一个换行会作为 Enter 送达。"
        )
    return hint


def build_description(shell: Optional[Any] = None) -> str:
    """The Chinese description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "运行 shell 命令。本机没有找到受支持的 shell"
            f"（{platform.system()}），任何调用都会失败。"
        )
    return (
        f"运行 shell 命令并返回输出。{_dialect_hint(shell)} "
        "命令从工作空间根目录开始执行。本工具不限制路径：命令能读写进程用户可访问的任何位置，"
        "因此请把路径限制在工作空间内，项目文件使用 read_file/edit_file/write_file 处理。"
        "'timeout' 单位是毫秒（默认 120000，最大 1800000）；超时后整个进程树会被停止，"
        "'interrupted' 为 true。超出响应预算的输出会写入文件，结果里给出简短预览和该文件路径，"
        "可以用 read_file 读回。'run_in_background' 不等待命令结束就返回，给出 pid、session_id "
        "和日志路径。命令结束时，后续轮次会收到一条 <task_notification>（退出码与输出末尾），"
        "不必轮询；只有它仍在运行时才用 write_stdin 向它输入。命令会一直运行到退出或任务结束，"
        "任务结束时会被停止。给 'description' 写一句简短说明，讲清命令在做"
        "什么：确认命令时会给用户看，也会记入审计。"
        f"{_tty_hint(shell)}"
        "'dangerouslyDisableSandbox' 只跳过额外的隔离层（完整性级别）；资源限制与进程树终止"
        "始终生效。"
    )


ZH_CN_PARAMETERS: Dict[str, str] = {
    "command": "在该平台 shell 中执行的命令行。",
    "timeout": (
        "超时时间，单位毫秒。默认 120000（2 分钟），最大 1800000（30 分钟）。"
        "超时后进程树会被停止，'interrupted' 为 true。"
    ),
    "description": (
        "用平实语言简短说明这条命令做什么，写给要决定是否允许它的人看"
        "（例如 '安装 lodash 工具库'）。执行前会显示在确认框里，并记入审计。"
    ),
    "run_in_background": (
        "启动命令后立即返回，不等待结果。结果里带 pid、session_id（运行期间交给 write_stdin 交互）"
        "和日志路径。结束时后续轮次会收到一条 <task_notification>（退出码与输出末尾）。"
        "任务结束时命令会被停止。默认 false。"
    ),
    "tty": "true 为命令分配 PTY；false 或省略则使用普通管道。",
    "dangerouslyDisableSandbox": (
        "跳过这条命令的额外隔离层（完整性级别）。资源限制与进程树终止不能关闭。默认 false。"
    ),
}


def zh_cn(shell: Optional[Any] = None) -> ToolText:
    """The ``zh-CN`` text; called while the spec is built, not on import."""
    return ToolText(description=build_description(shell), parameters=ZH_CN_PARAMETERS)


def _dialect_hint_zh_tw(shell: Any) -> str:
    if shell.family == FAMILY_POWERSHELL:
        return (
            "命令在 PowerShell 7+ 中執行，請寫 PowerShell 語法：環境變數用 '$env:NAME'，"
            "陳述式用 ';' 連接，僅在 cmd 內建命令前加 'cmd /c'。"
        )
    if shell.family == FAMILY_CMD:
        return (
            "命令在 cmd.exe 中執行，請寫 cmd 語法：環境變數用 '%NAME%'，用 '&&' 連接，"
            "避免使用 PowerShell cmdlet。"
        )
    return (
        f"命令在 {shell.display}（POSIX shell）中執行，請寫 POSIX 語法：環境變數用 '$NAME'，"
        "用 '&&' 連接，使用 POSIX 工具。"
    )


def _tty_hint_zh_tw(shell: Any) -> str:
    hint = (
        "'tty' 會把命令接到偽終端而不是普通管線，因此會檢查終端的程式（顏色、進度列、提示符）"
        "會像面對真人一樣運作。代價是沒有獨立的 stderr —— 終端會把 stderr 併進 stdout —— "
        "並且每行傳回都以回車字元結尾。前景執行的 'tty' 命令無法應答，需要回覆提示時請配合 "
        "'run_in_background'。"
    )
    if shell.family in (FAMILY_POWERSHELL, FAMILY_CMD):
        hint += (
            "在 Windows 上，終端會在命令自身輸出之前印出一小段轉義序列握手，"
            "你輸入的一個換行會作為 Enter 送達。"
        )
    return hint


def build_description_zh_tw(shell: Optional[Any] = None) -> str:
    """The ``zh-TW`` description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "執行 shell 命令。本機沒有找到受支援的 shell"
            f"（{platform.system()}），任何呼叫都會失敗。"
        )
    return (
        f"執行 shell 命令並傳回輸出。{_dialect_hint_zh_tw(shell)} "
        "命令從工作區根目錄開始執行。本工具不限制路徑：命令能讀寫行程使用者可存取的任何位置，"
        "因此請把路徑限制在工作區內，專案檔案使用 read_file/edit_file/write_file 處理。"
        "'timeout' 單位是毫秒（預設 120000，最大 1800000）；逾時後整個行程樹會被停止，"
        "'interrupted' 為 true。超出回應預算的輸出會寫入檔案，結果裡給出簡短預覽和該檔案路徑，"
        "可以用 read_file 讀回。'run_in_background' 不等待命令結束就傳回，給出 pid、session_id "
        "和日誌路徑。命令結束時，後續輪次會收到一條 <task_notification>（退出碼與輸出末尾），"
        "不必輪詢；只有它仍在執行時才用 write_stdin 向它輸入。命令會一直執行到結束或任務結束，"
        "任務結束時會被停止。給 'description' 寫一句簡短說明，講清命令在做"
        "什麼：確認命令時會給使用者看，也會記入稽核。"
        f"{_tty_hint_zh_tw(shell)}"
        "'dangerouslyDisableSandbox' 只跳過額外的隔離層（完整性等級）；資源限制與行程樹終止"
        "始終生效。"
    )


ZH_TW_PARAMETERS: Dict[str, str] = {
    "command": "在該平台 shell 中執行的命令列。",
    "timeout": (
        "逾時時間，單位毫秒。預設 120000（2 分鐘），最大 1800000（30 分鐘）。"
        "逾時後行程樹會被停止，'interrupted' 為 true。"
    ),
    "description": (
        "用平實語言簡短說明這條命令做什麼，寫給要決定是否允許它的人看"
        "（例如 '安裝 lodash 工具庫'）。執行前會顯示在確認框裡，並記入稽核。"
    ),
    "run_in_background": (
        "啟動命令後立即傳回，不等待結果。結果裡帶 pid、session_id（執行期間交給 write_stdin 互動）"
        "和日誌路徑。結束時後續輪次會收到一條 <task_notification>（退出碼與輸出末尾）。"
        "任務結束時命令會被停止。預設 false。"
    ),
    "tty": "true 為命令分配 PTY；false 或省略則使用普通管線。",
    "dangerouslyDisableSandbox": (
        "跳過這條命令的額外隔離層（完整性等級）。資源限制與行程樹終止不能關閉。預設 false。"
    ),
}


def zh_tw(shell: Optional[Any] = None) -> ToolText:
    """The ``zh-TW`` text; called while the spec is built, not on import."""
    return ToolText(description=build_description_zh_tw(shell), parameters=ZH_TW_PARAMETERS)


def _dialect_hint_fr(shell: Any) -> str:
    if shell.family == FAMILY_POWERSHELL:
        return (
            "La commande s'exécute dans PowerShell 7+ : écrivez en syntaxe PowerShell, variables "
            "d'environnement via '$env:NAME', instructions chaînées par ';', et préfixez "
            "'cmd /c' uniquement devant les commandes internes de cmd."
        )
    if shell.family == FAMILY_CMD:
        return (
            "La commande s'exécute dans cmd.exe : écrivez en syntaxe cmd, variables "
            "d'environnement via '%NAME%', chaînez avec '&&', et évitez les cmdlets PowerShell."
        )
    return (
        f"La commande s'exécute dans {shell.display} (shell POSIX) : écrivez en syntaxe POSIX, "
        "variables d'environnement via '$NAME', chaînez avec '&&', et utilisez les outils POSIX."
    )


def _tty_hint_fr(shell: Any) -> str:
    hint = (
        "'tty' branche la commande sur un pseudo-terminal au lieu d'un simple tube : les "
        "programmes qui interrogent le terminal (couleurs, barres de progression, invites) se "
        "comportent comme face à une personne. Le prix à payer : pas de stderr séparé — le "
        "terminal fusionne stderr dans stdout — et chaque ligne renvoyée se termine par un retour "
        "chariot. Une commande 'tty' lancée au premier plan ne peut pas répondre ; pour répondre à "
        "une invite, combinez avec 'run_in_background'."
    )
    if shell.family in (FAMILY_POWERSHELL, FAMILY_CMD):
        hint += (
            " Sous Windows, le terminal imprime une courte poignée de main en séquences "
            "d'échappement avant la sortie de la commande, et le saut de ligne que vous saisissez "
            "est envoyé comme Entrée."
        )
    return hint


def build_description_fr(shell: Optional[Any] = None) -> str:
    """The ``fr`` description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "Exécute des commandes shell. Aucun shell pris en charge n'a été trouvé sur cette "
            f"machine ({platform.system()}) : tout appel échouera."
        )
    return (
        f"Exécute une commande shell et renvoie sa sortie. {_dialect_hint_fr(shell)} "
        "La commande démarre à la racine de l'espace de travail. Cet outil ne restreint pas les "
        "chemins : la commande peut lire et écrire partout où l'utilisateur du processus en a le "
        "droit ; gardez donc les chemins dans l'espace de travail et traitez les fichiers du "
        "projet avec read_file/edit_file/write_file. 'timeout' est en millisecondes (120000 par "
        "défaut, 1800000 au maximum) ; à l'expiration, l'arbre de processus entier est arrêté et "
        "'interrupted' passe à true. La sortie qui dépasse le budget de réponse est écrite dans "
        "un fichier, dont le résultat donne un aperçu court et le chemin, relisible avec "
        "read_file. 'run_in_background' rend la main sans attendre la fin et fournit pid, "
        "session_id et chemin du journal. À la fin de la commande, une <task_notification> avec le "
        "code de sortie et la fin de la sortie arrive au début d'un tour ultérieur : inutile "
        "d'interroger ; write_stdin ne sert que pendant l'exécution, pour y écrire. La commande "
        "tourne jusqu'à sa fin ou jusqu'à la fin de la tâche, qui l'arrête. "
        "Renseignez 'description' avec une phrase simple expliquant ce que fait la commande : "
        "elle est montrée à l'utilisateur lors de la confirmation et enregistrée pour l'audit. "
        f"{_tty_hint_fr(shell)}"
        "'dangerouslyDisableSandbox' ne saute que la couche d'isolation supplémentaire (niveau "
        "d'intégrité) ; les limites de ressources et la fin de l'arbre de processus restent "
        "actives."
    )


FR_PARAMETERS: Dict[str, str] = {
    "command": "Ligne de commande exécutée dans le shell de cette plateforme.",
    "timeout": (
        "Délai en millisecondes. 120000 (2 minutes) par défaut, 1800000 (30 minutes) au "
        "maximum. À l'expiration, l'arbre de processus est arrêté et 'interrupted' passe à true."
    ),
    "description": (
        "Décrivez en langage clair ce que fait la commande, pour la personne qui doit décider de "
        "l'autoriser (par exemple 'installer la bibliothèque lodash'). Affiché dans la fenêtre de "
        "confirmation avant l'exécution et enregistré pour l'audit."
    ),
    "run_in_background": (
        "Rend la main dès le lancement sans attendre le résultat. Le résultat contient pid, "
        "session_id (à passer à write_stdin pendant l'exécution) et le chemin du journal. À la fin, "
        "une <task_notification> avec le code de sortie arrive à un tour ultérieur. La commande est "
        "arrêtée à la fin de la tâche. false par défaut."
    ),
    "tty": "true alloue un PTY à la commande ; false ou absent utilise un tube normal.",
    "dangerouslyDisableSandbox": (
        "Saute la couche d'isolation supplémentaire (niveau d'intégrité) de cette commande. Les "
        "limites de ressources et la fin de l'arbre de processus ne peuvent pas être désactivées. "
        "false par défaut."
    ),
}


def fr(shell: Optional[Any] = None) -> ToolText:
    """The ``fr`` text; called while the spec is built, not on import."""
    return ToolText(description=build_description_fr(shell), parameters=FR_PARAMETERS)


def _dialect_hint_de(shell: Any) -> str:
    if shell.family == FAMILY_POWERSHELL:
        return (
            "Der Befehl läuft in PowerShell 7+: in PowerShell-Syntax schreiben, "
            "Umgebungsvariablen mit '$env:NAME', Anweisungen mit ';' verketten, und 'cmd /c' nur "
            "vor cmd-eigene Befehle setzen."
        )
    if shell.family == FAMILY_CMD:
        return (
            "Der Befehl läuft in cmd.exe: in cmd-Syntax schreiben, Umgebungsvariablen mit "
            "'%NAME%', mit '&&' verketten und PowerShell-Cmdlets vermeiden."
        )
    return (
        f"Der Befehl läuft in {shell.display} (POSIX-Shell): in POSIX-Syntax schreiben, "
        "Umgebungsvariablen mit '$NAME', mit '&&' verketten und POSIX-Werkzeuge verwenden."
    )


def _tty_hint_de(shell: Any) -> str:
    hint = (
        "'tty' hängt den Befehl an ein Pseudo-Terminal statt an eine normale Pipe: Programme, "
        "die das Terminal abfragen (Farben, Fortschrittsbalken, Eingabeaufforderungen), verhalten "
        "sich wie gegenüber einer Person. Der Preis: kein separates stderr — das Terminal mischt "
        "stderr in stdout — und jede zurückgegebene Zeile endet mit einem Wagenrücklauf. Ein im "
        "Vordergrund laufender 'tty'-Befehl kann nicht antworten; für Antworten auf eine "
        "Eingabeaufforderung 'run_in_background' mitverwenden."
    )
    if shell.family in (FAMILY_POWERSHELL, FAMILY_CMD):
        hint += (
            " Unter Windows gibt das Terminal vor der eigenen Ausgabe des Befehls einen kurzen "
            "Escape-Sequenz-Handshake aus, und der eingegebene Zeilenumbruch wird als Enter "
            "zugestellt."
        )
    return hint


def build_description_de(shell: Optional[Any] = None) -> str:
    """The ``de`` description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "Führt Shell-Befehle aus. Auf dieser Maschine wurde keine unterstützte Shell "
            f"gefunden ({platform.system()}): jeder Aufruf schlägt fehl."
        )
    return (
        f"Führt einen Shell-Befehl aus und gibt dessen Ausgabe zurück. {_dialect_hint_de(shell)} "
        "Der Befehl startet im Wurzelverzeichnis des Arbeitsbereichs. Dieses Werkzeug beschränkt "
        "keine Pfade: der Befehl kann überall lesen und schreiben, wo der Prozessbenutzer darf — "
        "halte Pfade deshalb im Arbeitsbereich und behandle Projektdateien mit "
        "read_file/edit_file/write_file. 'timeout' ist in Millisekunden (Standard 120000, maximal "
        "1800000); nach Ablauf wird der gesamte Prozessbaum gestoppt und 'interrupted' ist true. "
        "Ausgabe über dem Antwortbudget wird in eine Datei geschrieben, das Ergebnis nennt eine "
        "kurze Vorschau und den Pfad, der mit read_file zurückgelesen werden kann. "
        "'run_in_background' kehrt sofort zurück und liefert pid, session_id und Logpfad. Endet "
        "der Befehl, kommt zu Beginn eines späteren Zugs eine <task_notification> mit Exit-Code "
        "und dem Ende der Ausgabe - also nicht pollen; write_stdin dient nur dem Eingeben, solange "
        "er läuft. Der Befehl läuft bis zu seinem Ende oder bis zum Aufgabenende, das ihn stoppt. "
        "In 'description' "
        "einen kurzen Satz schreiben, was der Befehl tut: er wird dem Benutzer bei der Bestätigung "
        "gezeigt und für die Prüfung protokolliert. "
        f"{_tty_hint_de(shell)}"
        "'dangerouslyDisableSandbox' überspringt nur die zusätzliche Isolationsschicht "
        "(Integritätsstufe); Ressourcenlimits und das Beenden des Prozessbaums gelten weiterhin."
    )


DE_PARAMETERS: Dict[str, str] = {
    "command": "Die in der Shell dieser Plattform auszuführende Befehlszeile.",
    "timeout": (
        "Zeitlimit in Millisekunden. Standard 120000 (2 Minuten), maximal 1800000 (30 Minuten). "
        "Nach Ablauf wird der Prozessbaum gestoppt und 'interrupted' ist true."
    ),
    "description": (
        "In einfacher Sprache kurz beschreiben, was der Befehl tut — für die Person, die über die "
        "Erlaubnis entscheidet (z. B. 'lodash-Bibliothek installieren'). Wird vor der Ausführung "
        "im Bestätigungsdialog gezeigt und für die Prüfung protokolliert."
    ),
    "run_in_background": (
        "Kehrt direkt nach dem Start zurück, ohne auf das Ergebnis zu warten. Das Ergebnis enthält "
        "pid, session_id (an write_stdin geben, solange er läuft) und den Logpfad. Am Ende kommt "
        "eine <task_notification> mit dem Exit-Code in einem späteren Zug. Beim Aufgabenende wird "
        "der Befehl gestoppt. Standard false."
    ),
    "tty": "true weist dem Befehl ein PTY zu; false oder weggelassen nutzt eine normale Pipe.",
    "dangerouslyDisableSandbox": (
        "Überspringt die zusätzliche Isolationsschicht (Integritätsstufe) für diesen Befehl. "
        "Ressourcenlimits und das Beenden des Prozessbaums lassen sich nicht abschalten. Standard "
        "false."
    ),
}


def de(shell: Optional[Any] = None) -> ToolText:
    """The ``de`` text; called while the spec is built, not on import."""
    return ToolText(description=build_description_de(shell), parameters=DE_PARAMETERS)


def _dialect_hint_ru(shell: Any) -> str:
    if shell.family == FAMILY_POWERSHELL:
        return (
            "Команда выполняется в PowerShell 7+: пишите в синтаксисе PowerShell, переменные "
            "окружения через '$env:NAME', операторы через ';', а 'cmd /c' добавляйте только "
            "перед встроенными командами cmd."
        )
    if shell.family == FAMILY_CMD:
        return (
            "Команда выполняется в cmd.exe: пишите в синтаксисе cmd, переменные окружения через "
            "'%NAME%', соединяйте через '&&', избегайте командлетов PowerShell."
        )
    return (
        f"Команда выполняется в {shell.display} (POSIX shell): пишите в синтаксисе POSIX, "
        "переменные окружения через '$NAME', соединяйте через '&&', используйте инструменты "
        "POSIX."
    )


def _tty_hint_ru(shell: Any) -> str:
    hint = (
        "'tty' подключает команду к псевдотерминалу вместо обычного канала: программы, "
        "проверяющие терминал (цвета, индикаторы прогресса, приглашения), ведут себя как с "
        "человеком. Цена — нет отдельного stderr (терминал сливает stderr в stdout) и каждая "
        "возвращённая строка заканчивается символом возврата каретки. Команда 'tty', "
        "запущенная на переднем плане, не может ответить; чтобы отвечать на приглашения, "
        "используйте вместе с 'run_in_background'."
    )
    if shell.family in (FAMILY_POWERSHELL, FAMILY_CMD):
        hint += (
            " В Windows терминал перед собственным выводом команды печатает короткое рукопожатие "
            "escape-последовательностями, а введённый перевод строки доставляется как Enter."
        )
    return hint


def build_description_ru(shell: Optional[Any] = None) -> str:
    """The ``ru`` description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "Выполняет команды shell. На этой машине не найдено поддерживаемой оболочки "
            f"({platform.system()}): любой вызов завершится ошибкой."
        )
    return (
        f"Выполняет команду shell и возвращает вывод. {_dialect_hint_ru(shell)} "
        "Команда запускается из корня рабочей области. Инструмент не ограничивает пути: "
        "команда может читать и писать везде, где разрешено пользователю процесса, поэтому "
        "держите пути внутри рабочей области, а файлы проекта обрабатывайте через "
        "read_file/edit_file/write_file. 'timeout' задаётся в миллисекундах (по умолчанию "
        "120000, максимум 1800000); по истечении всё дерево процессов останавливается, а "
        "'interrupted' становится true. Вывод сверх бюджета ответа записывается в файл, в "
        "результате даётся короткий предпросмотр и путь к этому файлу, который можно прочитать "
        "через read_file. 'run_in_background' возвращает управление сразу и даёт pid, "
        "session_id и путь к журналу. Когда команда завершится, в начале одного из следующих "
        "шагов придёт <task_notification> с кодом возврата и концом вывода - опрашивать не "
        "нужно; write_stdin нужен только для ввода, пока она работает. Команда работает до "
        "своего завершения или до конца задачи, который её останавливает. В 'description' "
        "напишите короткое пояснение, что делает "
        "команда: оно показывается пользователю при подтверждении и попадает в аудит. "
        f"{_tty_hint_ru(shell)}"
        "'dangerouslyDisableSandbox' пропускает только дополнительный слой изоляции (уровень "
        "целостности); ограничения ресурсов и остановка дерева процессов действуют всегда."
    )


RU_PARAMETERS: Dict[str, str] = {
    "command": "Командная строка для выполнения в shell этой платформы.",
    "timeout": (
        "Таймаут в миллисекундах. По умолчанию 120000 (2 минуты), максимум 1800000 (30 минут). "
        "По истечении дерево процессов останавливается, 'interrupted' становится true."
    ),
    "description": (
        "Коротко и простыми словами опишите, что делает команда, — для человека, который "
        "решает, разрешать ли её (например, 'установить библиотеку lodash'). Показывается в "
        "окне подтверждения перед выполнением и записывается в аудит."
    ),
    "run_in_background": (
        "Возвращает управление сразу после запуска, не дожидаясь результата. В результате есть "
        "pid, session_id (передавать в write_stdin, пока команда работает) и путь к журналу. "
        "По завершении придёт <task_notification> с кодом возврата в одном из следующих шагов. "
        "По завершении задачи команда останавливается. По умолчанию false."
    ),
    "tty": "true выделяет команде PTY; false или отсутствие значения — обычный канал.",
    "dangerouslyDisableSandbox": (
        "Пропускает дополнительный слой изоляции (уровень целостности) для этой команды. "
        "Ограничения ресурсов и остановку дерева процессов отключить нельзя. По умолчанию "
        "false."
    ),
}


def ru(shell: Optional[Any] = None) -> ToolText:
    """The ``ru`` text; called while the spec is built, not on import."""
    return ToolText(description=build_description_ru(shell), parameters=RU_PARAMETERS)
