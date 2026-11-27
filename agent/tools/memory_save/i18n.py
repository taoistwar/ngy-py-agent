"""Translated display text for ``memory_save``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "保存一条长期有效的笔记，让后续会话不必再被交代一遍。以下情况调用它：用户说出长期"
        "偏好或对做事方式的固定要求；你了解到稳定的项目事实（某个决定及其原因、某个约束、"
        "某样东西在哪里）；或者用户要求你记住某事。\n\n"
        "只对本次任务有意义的内容不要保存：只用过一次的命令、临时路径、中间发现。把 scope "
        "写成 'current_task'，这条笔记会被有意拒绝——你在本次任务里继续遵守它即可，不要把它"
        "变成长期规则。\n\n"
        "一条记忆只讲一件事：简短的名字、一行索引、几段足以让后续会话在没有这段对话的情况下"
        "照着做的正文。整份记忆库已经按名字和描述列在你的系统提示词里，正文只能用 "
        "memory_search 读取——所以描述要说清这条笔记讲什么，细节放进正文。用同名再保存一次会"
        "替换原记录，这就是修正记忆的方式。返回结果会说明这条笔记是已保存、已替换还是被拒绝"
        "以及原因。"
    ),
    parameters={
        "name": (
            "用作键的短标识，例如 'user-prefers-tabs' 或 "
            "'auth-rewrite-driven-by-compliance'。用同名再保存一次会替换原内容。"
        ),
        "type": (
            "user = 用户的长期偏好；feedback = 以后仍适用的工作方式反馈；"
            "project = 稳定的项目事实；reference = 外部资料所在位置。"
        ),
        "description": (
            "记忆索引里显示的一行：这条笔记讲什么，而不是整段正文的摘要。最多 200 个字符。"
        ),
        "body": (
            "笔记正文，使用用户的语言：学到了什么，以及后续会话要照着做还需要哪些信息。"
            "最多 4000 个字符。"
        ),
        "scope": (
            "'persistent' 表示跨会话仍然成立（只有这个值会被保存）；"
            "'current_task' 表示只约束当前这次工作。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "儲存一則長期有效的筆記，讓後續工作階段不必再被交代一次。以下情況呼叫它：使用者說出"
        "長期偏好或對做事方式的固定要求；你了解到穩定的專案事實（某個決定及其原因、某個限制、"
        "某樣東西在哪裡）；或者使用者要求你記住某事。\n\n"
        "只對本次任務有意義的內容不要儲存：只用過一次的命令、臨時路徑、中間發現。把 scope "
        "寫成 'current_task'，這則筆記會被刻意拒絕——你在本次任務裡繼續遵守它即可，不要把它"
        "變成長期規則。\n\n"
        "一則記憶只講一件事：簡短的名稱、一行索引、幾段足以讓後續工作階段在沒有這段對話的"
        "情況下照著做的正文。整份記憶庫已經按名稱和描述列在你的系統提示詞裡，正文只能用 "
        "memory_search 讀取——所以描述要說清這則筆記講什麼，細節放進正文。用同名再儲存一次會"
        "取代原記錄，這就是修正記憶的方式。回傳結果會說明這則筆記是已儲存、已取代還是被拒絕"
        "以及原因。"
    ),
    parameters={
        "name": (
            "用作鍵的短識別碼，例如 'user-prefers-tabs' 或 "
            "'auth-rewrite-driven-by-compliance'。用同名再儲存一次會取代原內容。"
        ),
        "type": (
            "user = 使用者的長期偏好；feedback = 之後仍適用的工作方式回饋；"
            "project = 穩定的專案事實；reference = 外部資料所在位置。"
        ),
        "description": (
            "記憶索引裡顯示的一行：這則筆記講什麼，而不是整段正文的摘要。最多 200 個字元。"
        ),
        "body": (
            "筆記正文，使用使用者的語言：學到了什麼，以及後續工作階段要照著做還需要哪些資訊。"
            "最多 4000 個字元。"
        ),
        "scope": (
            "'persistent' 表示跨工作階段仍然成立（只有這個值會被儲存）；"
            "'current_task' 表示只限制目前這次工作。"
        ),
    },
)

FR = ToolText(
    description=(
        "Enregistrez une note durable pour qu'une conversation ultérieure n'ait pas à être "
        "remise au courant. Appelez-le quand l'utilisateur énonce une préférence durable ou une "
        "règle permanente sur la façon de travailler, quand vous apprenez un fait stable sur le "
        "projet (une décision et sa raison, une contrainte, où se trouve quelque chose), ou "
        "quand l'utilisateur vous demande de retenir quelque chose.\n\n"
        "N'enregistrez pas ce qui ne vaut que pour cette tâche : la commande qui a marché une "
        "fois, un chemin temporaire, un constat intermédiaire. Indiquez-le avec scope "
        "'current_task' et la note sera refusée volontairement - continuez à le respecter "
        "vous-même, mais n'en faites pas une règle permanente.\n\n"
        "Une mémoire, c'est une idée : un nom court, une ligne d'index, et un corps de quelques "
        "phrases qu'une session ultérieure peut appliquer sans relire cette conversation. Toute "
        "la bibliothèque est déjà listée dans votre prompt système par nom et description, et "
        "seuls les corps se lisent avec memory_search - la description dit donc de quoi parle la "
        "note, et les détails vont dans le corps. Enregistrer à nouveau le même nom remplace la "
        "note précédente : c'est ainsi qu'une mémoire se corrige. Le résultat indique si la note "
        "a été enregistrée, remplacée ou refusée, et pourquoi."
    ),
    parameters={
        "name": (
            "Identifiant court servant de clé, par exemple 'user-prefers-tabs' ou "
            "'auth-rewrite-driven-by-compliance'. Enregistrer le même nom remplace son contenu."
        ),
        "type": (
            "user = préférence durable de l'utilisateur ; feedback = retour sur la façon de "
            "travailler qui vaut encore ensuite ; project = fait stable sur le projet ; "
            "reference = où trouver une ressource externe."
        ),
        "description": (
            "Une ligne pour l'index : de quoi parle la note, et non un résumé de tout le corps. "
            "200 caractères au maximum."
        ),
        "body": (
            "Le corps de la note, dans la langue de l'utilisateur : ce qui a été appris et ce "
            "qu'il faut pour agir dessus plus tard. 4000 caractères au maximum."
        ),
        "scope": (
            "'persistent' quand le fait vaut encore dans une session ultérieure (seule valeur "
            "enregistrée) ; 'current_task' quand il ne contraint que le travail en cours."
        ),
    },
)

DE = ToolText(
    description=(
        "Speichere eine dauerhafte Notiz, damit ein späteres Gespräch nicht erneut informiert "
        "werden muss. Rufe das Werkzeug auf, wenn der Nutzer eine bleibende Vorliebe oder eine "
        "feste Regel für die Arbeitsweise nennt, wenn du einen stabilen Projektfakt lernst (eine "
        "Entscheidung und ihr Grund, eine Einschränkung, wo etwas liegt) oder wenn der Nutzer "
        "dich bittet, sich etwas zu merken.\n\n"
        "Speichere nichts, was nur für diese Aufgabe gilt: den Befehl, der einmal funktioniert "
        "hat, einen temporären Pfad, einen Zwischenbefund. Schreibe dafür scope 'current_task', "
        "dann wird die Notiz bewusst abgelehnt - halte dich selbst weiter daran, aber mache "
        "daraus keine dauerhafte Regel.\n\n"
        "Eine Erinnerung ist ein Gedanke: ein kurzer Name, eine Indexzeile und ein Text aus "
        "wenigen Sätzen, mit dem eine spätere Sitzung ohne dieses Gespräch arbeiten kann. Die "
        "ganze Bibliothek steht bereits mit Name und Beschreibung im System-Prompt, und nur die "
        "Texte werden mit memory_search gelesen - die Beschreibung sagt also, worum es geht, und "
        "die Einzelheiten gehören in den Text. Derselbe Name ersetzt beim erneuten Speichern den "
        "alten Eintrag; so wird eine Erinnerung korrigiert. Das Ergebnis sagt, ob die Notiz "
        "gespeichert, ersetzt oder abgelehnt wurde, und warum."
    ),
    parameters={
        "name": (
            "Kurze Kennung als Schlüssel, etwa 'user-prefers-tabs' oder "
            "'auth-rewrite-driven-by-compliance'. Erneutes Speichern unter demselben Namen "
            "ersetzt den Inhalt."
        ),
        "type": (
            "user = bleibende Vorliebe des Nutzers; feedback = Rückmeldung zur Arbeitsweise, die "
            "weiterhin gilt; project = stabiler Projektfakt; reference = wo eine externe Quelle "
            "zu finden ist."
        ),
        "description": (
            "Eine Zeile für den Index: worum es in der Notiz geht, nicht eine Zusammenfassung "
            "des ganzen Textes. Höchstens 200 Zeichen."
        ),
        "body": (
            "Der Text der Notiz in der Sprache des Nutzers: was gelernt wurde und was später "
            "zum Handeln nötig ist. Höchstens 4000 Zeichen."
        ),
        "scope": (
            "'persistent', wenn der Fakt in einer späteren Sitzung noch gilt (nur dieser Wert "
            "wird gespeichert); 'current_task', wenn er nur die aktuelle Arbeit einschränkt."
        ),
    },
)

RU = ToolText(
    description=(
        "Сохраните долговечную заметку, чтобы следующему разговору не приходилось объяснять "
        "всё заново. Вызывайте инструмент, когда пользователь называет устойчивое предпочтение "
        "или постоянное правило работы, когда вы узнаёте стабильный факт о проекте (решение и "
        "его причина, ограничение, где что находится) или когда пользователь просит запомнить.\n\n"
        "Не сохраняйте то, что важно только для текущей задачи: команду, сработавшую один раз, "
        "временный путь, промежуточную находку. Укажите scope 'current_task', и заметка будет "
        "намеренно отклонена - продолжайте соблюдать это сами, но не делайте постоянным "
        "правилом.\n\n"
        "Одна память - одна мысль: короткое имя, одна строка индекса и текст из нескольких "
        "предложений, по которому следующая сессия сможет действовать без этого разговора. Вся "
        "библиотека уже перечислена в системном запросе по имени и описанию, а тексты читаются "
        "только через memory_search - поэтому описание говорит, о чём заметка, а подробности "
        "идут в текст. Повторное сохранение под тем же именем заменяет запись: так память "
        "исправляется. Результат сообщает, сохранена заметка, заменена или отклонена, и почему."
    ),
    parameters={
        "name": (
            "Короткий идентификатор-ключ, например 'user-prefers-tabs' или "
            "'auth-rewrite-driven-by-compliance'. Повторное сохранение под тем же именем "
            "заменяет содержимое."
        ),
        "type": (
            "user = устойчивое предпочтение пользователя; feedback = отзыв о способе работы, "
            "который ещё пригодится; project = стабильный факт о проекте; reference = где "
            "находится внешний источник."
        ),
        "description": (
            "Одна строка для индекса: о чём заметка, а не пересказ всего текста. Не более 200 "
            "символов."
        ),
        "body": (
            "Текст заметки на языке пользователя: что узнали и что понадобится позже, чтобы "
            "этим воспользоваться. Не более 4000 символов."
        ),
        "scope": (
            "'persistent', если факт важен и в следующей сессии (только это значение "
            "сохраняется); 'current_task', если он ограничивает только текущую работу."
        ),
    },
)
