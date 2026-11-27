"""Chinese display text for ``write_stdin``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "向 exec_command 留下的运行中命令输入内容，并读回它打印的输出。传入 exec_command "
        "为仍在运行的命令返回的 'session_id'。把 'chars' 设为要写入命令 stdin 的文本"
        "（含 '\\n' 才会发送一行）；'chars' 留空只用于读取仍在运行的命令的新输出"
        "（命令结束会由后续轮次的 <task_notification> 告知，不必轮询确认）。'chars' 等于 Ctrl-C"
        "（'\\u0003'）时会中断命令而不是写入。'yield_time_ms' 限制等待输出的时长，"
        "'max_output_tokens' 限制返回多少内容。结果会说明命令仍在运行（给出 session_id）"
        "还是已结束（给出 exit_code）；已结束的会话不能复用。"
    ),
    parameters={
        "session_id": "exec_command 为仍在运行的命令返回的会话 id。已结束的会话会被拒绝。",
        "chars": (
            "写入命令 stdin 的文本。为空（默认）时只轮询新输出。"
            "单个 Ctrl-C 字符（'\\u0003'）会中断命令。"
        ),
        "yield_time_ms": (
            "等待输出的时长，单位毫秒。轮询（'chars' 为空）至少提升到 5000、上限 300000；"
            "写入最多等待 30000。默认 250。"
        ),
        "max_output_tokens": (
            "返回输出的 token 预算。默认 10000；更大的请求可能被策略压低。"
            "超出预算的输出会被持久化并返回其路径。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "向 exec_command 留下的執行中命令輸入內容，並讀回它列印的輸出。傳入 exec_command "
        "為仍在執行的命令傳回的 'session_id'。把 'chars' 設為要寫入命令 stdin 的文字"
        "（含 '\\n' 才會送出一個換行）；'chars' 留空只用於讀取仍在執行的命令的新輸出"
        "（命令結束會由後續輪次的 <task_notification> 告知，不必輪詢確認）。'chars' 等於 Ctrl-C"
        "（'\\u0003'）時會中斷命令而不是寫入。'yield_time_ms' 限制等待輸出的時長，"
        "'max_output_tokens' 限制傳回多少內容。結果會說明命令仍在執行（給出 session_id）"
        "還是已結束（給出 exit_code）；已結束的工作階段不能重複使用。"
    ),
    parameters={
        "session_id": "exec_command 為仍在執行的命令傳回的工作階段 id。已結束的工作階段會被拒絕。",
        "chars": (
            "寫入命令 stdin 的文字。為空（預設）時只輪詢新輸出。"
            "單一 Ctrl-C 字元（'\\u0003'）會中斷命令。"
        ),
        "yield_time_ms": (
            "等待輸出的時長，單位毫秒。輪詢（'chars' 為空）至少提升到 5000、上限 300000；"
            "寫入最多等待 30000。預設 250。"
        ),
        "max_output_tokens": (
            "傳回輸出的 token 預算。預設 10000；更大的請求可能被策略壓低。"
            "超出預算的輸出會被持久化並傳回路徑。"
        ),
    },
)

FR = ToolText(
    description=(
        "Écrit dans l'entrée standard d'une commande laissée en cours par exec_command et relit "
        "ce qu'elle affiche. Passez le 'session_id' renvoyé par exec_command pour une commande "
        "encore en cours. Mettez dans 'chars' le texte à écrire sur l'entrée standard (un '\\n' "
        "est nécessaire pour envoyer une ligne) ; laissez 'chars' vide pour lire les nouvelles "
        "sorties d'une commande dont vous savez déjà qu'elle tourne (la fin d'une commande en "
        "arrière-plan arrive dans une <task_notification>, inutile de la guetter). Un 'chars' égal "
        "à Ctrl-C ('\\u0003') interrompt la commande au "
        "lieu d'écrire. 'yield_time_ms' borne l'attente de sortie, 'max_output_tokens' borne la "
        "quantité renvoyée. Le résultat indique si la commande tourne encore (avec le session_id) "
        "ou est terminée (avec l'exit_code) ; une session terminée n'est pas réutilisable."
    ),
    parameters={
        "session_id": (
            "Identifiant de session renvoyé par exec_command pour une commande encore en cours. "
            "Une session terminée est refusée."
        ),
        "chars": (
            "Texte à écrire sur l'entrée standard de la commande. Vide (par défaut), seule la "
            "nouvelle sortie est interrogée. Un seul caractère Ctrl-C ('\\u0003') interrompt la "
            "commande."
        ),
        "yield_time_ms": (
            "Durée d'attente de la sortie, en millisecondes. Une interrogation ('chars' vide) est "
            "relevée à 5000 au minimum, plafond 300000 ; une écriture attend au plus 30000. 250 "
            "par défaut."
        ),
        "max_output_tokens": (
            "Budget de tokens de la sortie renvoyée. 10000 par défaut ; une demande plus grande "
            "peut être réduite par la politique. La sortie au-delà du budget est persistée et son "
            "chemin renvoyé."
        ),
    },
)

DE = ToolText(
    description=(
        "Schreibt in die Standardeingabe eines von exec_command laufengelassenen Befehls und "
        "liest dessen Ausgabe zurück. Übergib die 'session_id', die exec_command für einen noch "
        "laufenden Befehl zurückgibt. 'chars' ist der Text für die Standardeingabe (ein '\\n' ist "
        "nötig, um eine Zeile zu senden); bleibt 'chars' leer, wird nur neue Ausgabe eines bereits "
        "laufenden Befehls gelesen - das Ende kommt als <task_notification>, danach muss man nicht "
        "pollen. "
        "'chars' gleich Ctrl-C ('\\u0003') bricht den Befehl ab, statt zu schreiben. "
        "'yield_time_ms' begrenzt das Warten auf Ausgabe, 'max_output_tokens' die zurückgegebene "
        "Menge. Das Ergebnis sagt, ob der Befehl noch läuft (mit session_id) oder beendet ist "
        "(mit exit_code); eine beendete Sitzung ist nicht wiederverwendbar."
    ),
    parameters={
        "session_id": (
            "Sitzungs-ID, die exec_command für einen noch laufenden Befehl zurückgibt. Eine "
            "beendete Sitzung wird abgelehnt."
        ),
        "chars": (
            "Text für die Standardeingabe des Befehls. Leer (Standard) fragt nur neue Ausgabe ab. "
            "Ein einzelnes Ctrl-C-Zeichen ('\\u0003') bricht den Befehl ab."
        ),
        "yield_time_ms": (
            "Wartezeit auf Ausgabe in Millisekunden. Eine Abfrage ('chars' leer) wird auf "
            "mindestens 5000 angehoben, Obergrenze 300000; ein Schreiben wartet höchstens 30000. "
            "Standard 250."
        ),
        "max_output_tokens": (
            "Token-Budget der zurückgegebenen Ausgabe. Standard 10000; größere Anfragen können "
            "durch die Richtlinie gekürzt werden. Ausgabe über dem Budget wird persistiert und ihr "
            "Pfad zurückgegeben."
        ),
    },
)

RU = ToolText(
    description=(
        "Пишет в стандартный ввод команды, оставленной работающей exec_command, и читает её "
        "вывод. Передайте 'session_id', который exec_command вернул для ещё работающей команды. "
        "В 'chars' — текст для stdin команды (нужен '\\n', чтобы отправить строку); если "
        "'chars' пуст, читается только новый вывод уже работающей команды (о завершении "
        "сообщит <task_notification>, опрашивать не нужно). 'chars', равный Ctrl-C "
        "('\\u0003'), прерывает команду вместо записи. 'yield_time_ms' ограничивает ожидание "
        "вывода, 'max_output_tokens' — объём возвращаемых данных. В результате сказано, "
        "работает ли команда ещё (с session_id) или завершилась (с exit_code); завершённый "
        "сеанс нельзя использовать повторно."
    ),
    parameters={
        "session_id": (
            "Идентификатор сеанса, который exec_command вернул для ещё работающей команды. "
            "Завершённый сеанс отклоняется."
        ),
        "chars": (
            "Текст для записи в stdin команды. Пустое значение (по умолчанию) — только опрос "
            "нового вывода. Один символ Ctrl-C ('\\u0003') прерывает команду."
        ),
        "yield_time_ms": (
            "Сколько ждать вывода, в миллисекундах. Опрос ('chars' пуст) поднимается минимум до "
            "5000, предел 300000; запись ждёт не дольше 30000. По умолчанию 250."
        ),
        "max_output_tokens": (
            "Бюджет токенов для возвращаемого вывода. По умолчанию 10000; большие значения "
            "могут быть уменьшены политикой. Вывод сверх бюджета сохраняется, а путь "
            "возвращается."
        ),
    },
)
