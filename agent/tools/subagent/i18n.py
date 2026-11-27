"""Translated display text for ``subagent`` (admin tool page only).

The model always sees the English ``description``/``parameters``; this module holds
the five translated locales the page offers. Every parameter needs text in every
locale, otherwise the admin page falls back to English for that row
(``test/tool_api_test.py`` asserts it).
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "把一个独立的子任务委派给子代理：子代理从全新对话开始，只能看到你给的 'prompt'，"
        "看不到当前对话。适用于会往上下文里塞满中间细节的工作——跨很多文件追踪调用链、通读"
        "一个目录、或在隔离环境里构建并验证一小块内容。子代理拥有相同的工具（本工具除外）、"
        "同一个工作空间和同样的权限检查，但它的工具调用与结果不会进入当前对话，你只会收到它"
        "的最终报告。请把 'prompt' 写成完整简报：目标、它需要的路径或事实、要回报什么、以及"
        "约束，并要求它以简短报告结束。子代理不能再委派，不要让它再去开子代理。如果报告显示"
        "任务没做完，修正简报后再次委派，而不是在这里把每一步重做一遍。"
    ),
    parameters={
        "prompt": (
            "给子代理的完整指令。它对当前对话一无所知，因此请写清目标、所需背景，"
            "以及要回报的确切结果。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "把一個獨立的子任務委派給子代理：子代理從全新對話開始，只能看到你給的 'prompt'，"
        "看不到目前對話。適用於會往上下文塞滿中間細節的工作——跨許多檔案追蹤呼叫鏈、通讀"
        "一個目錄、或在隔離環境裡建置並驗證一小塊內容。子代理擁有相同的工具（本工具除外）、"
        "同一個工作區和同樣的權限檢查，但它的工具呼叫與結果不會進入目前對話，你只會收到它"
        "的最終報告。請把 'prompt' 寫成完整簡報：目標、它需要的路徑或事實、要回報什麼、以及"
        "限制，並要求它以簡短報告結束。子代理不能再委派，不要讓它再去開子代理。如果報告顯示"
        "任務沒做完，修正簡報後再次委派，而不是在這裡把每一步重做一遍。"
    ),
    parameters={
        "prompt": (
            "給子代理的完整指令。它對目前對話一無所知，因此請寫清目標、所需背景，"
            "以及要回報的確切結果。"
        ),
    },
)

FR = ToolText(
    description=(
        "Délègue une sous-tâche autonome à un sous-agent qui repart d'une conversation "
        "vierge : il ne voit que le 'prompt' que vous lui donnez, jamais cette conversation. "
        "À utiliser quand le travail noierait ce contexte sous les détails intermédiaires — "
        "suivre une chaîne d'appels dans de nombreux fichiers, parcourir un répertoire, ou "
        "construire et vérifier un petit morceau isolément. Le sous-agent dispose des mêmes "
        "outils (sauf celui-ci), du même espace de travail et des mêmes contrôles de "
        "permission, mais ses appels d'outils et leurs résultats n'entrent jamais dans cette "
        "conversation : vous ne recevez que son rapport final. Rédigez 'prompt' comme un "
        "briefing complet — l'objectif, les chemins ou faits nécessaires, ce qu'il doit "
        "rapporter et les contraintes — et demandez-lui de terminer par un rapport court. Le "
        "sous-agent ne peut pas déléguer à son tour : ne lui demandez pas de créer un autre "
        "agent. Si le rapport montre que la tâche n'est pas faite, corrigez le briefing et "
        "déléguez à nouveau plutôt que de refaire chaque étape ici."
    ),
    parameters={
        "prompt": (
            "Instructions complètes pour le sous-agent. Il ne sait rien de cette "
            "conversation : indiquez l'objectif, le contexte nécessaire et le résultat "
            "exact à rapporter."
        ),
    },
)

DE = ToolText(
    description=(
        "Delegiert eine abgeschlossene Teilaufgabe an einen Subagenten, der mit einer "
        "frischen Unterhaltung beginnt: er sieht nur den übergebenen 'prompt', nie diese "
        "Unterhaltung. Sinnvoll, wenn die Arbeit diesen Kontext sonst mit Zwischendetails "
        "fluten würde — eine Aufrufkette über viele Dateien verfolgen, ein Verzeichnis "
        "durchsehen oder ein kleines Stück isoliert bauen und prüfen. Der Subagent hat "
        "dieselben Werkzeuge (außer diesem), denselben Arbeitsbereich und dieselben "
        "Berechtigungsprüfungen, aber seine Werkzeugaufrufe und Ergebnisse gelangen nie in "
        "diese Unterhaltung: Sie erhalten nur seinen Abschlussbericht. Formulieren Sie "
        "'prompt' als vollständiges Briefing — Ziel, benötigte Pfade oder Fakten, was "
        "zurückgemeldet werden soll und Einschränkungen — und lassen Sie es mit einem "
        "kurzen Bericht enden. Der Subagent kann nicht weiter delegieren; fordern Sie ihn "
        "nicht auf, einen weiteren Agenten zu starten. Zeigt der Bericht, dass die Aufgabe "
        "nicht erledigt ist, korrigieren Sie das Briefing und delegieren erneut, statt hier "
        "jeden Schritt zu wiederholen."
    ),
    parameters={
        "prompt": (
            "Vollständige Anweisungen für den Subagenten. Er weiß nichts über diese "
            "Unterhaltung: nennen Sie Ziel, nötigen Kontext und das exakt zu berichtende "
            "Ergebnis."
        ),
    },
)

RU = ToolText(
    description=(
        "Поручает одну самостоятельную подзадачу субагенту, который начинает с чистого "
        "разговора: он видит только переданный 'prompt' и никогда — этот разговор. "
        "Используйте, когда работа иначе завалит контекст промежуточными деталями: "
        "проследить цепочку вызовов по множеству файлов, просмотреть каталог или собрать и "
        "проверить небольшой фрагмент изолированно. У субагента те же инструменты (кроме "
        "этого), тот же рабочий каталог и те же проверки разрешений, но его вызовы "
        "инструментов и результаты никогда не попадают в этот разговор: вы получаете "
        "только его итоговый отчёт. Составьте 'prompt' как полное задание — цель, нужные "
        "пути или факты, что именно сообщить и ограничения — и попросите закончить коротким "
        "отчётом. Субагент не может делегировать дальше: не просите его запускать ещё "
        "одного агента. Если отчёт показывает, что задача не выполнена, исправьте задание "
        "и поручите снова, а не повторяйте каждый шаг здесь."
    ),
    parameters={
        "prompt": (
            "Полные инструкции для субагента. Он ничего не знает об этом разговоре, "
            "поэтому укажите цель, необходимый контекст и точный результат, который "
            "нужно вернуть."
        ),
    },
)
