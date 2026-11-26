"""Translated display text for ``todo_write``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "把当前任务的计划维护成一份有序清单。开始需要多个步骤的工作前先调用它：先把所有步骤"
        "写成 'pending'，然后把正在做的那一步改成 'in_progress'，做完立刻改成 'completed'；"
        "同时最多只有一个进行中，全部完成或还在规划时可以没有。每次调用都会替换整份清单，"
        "所以每次都要发送完整计划，已完成的步骤也要保留并标成 'completed'。清单属于整个会话"
        "而不是这一次调用：同一会话的后续任务会继续使用它，并且会展示给用户，因此每一项都要"
        "简短、具体、使用用户的语言，不要列出不打算执行的步骤。最多 20 项，多数任务 2 到 7 项"
        "即可。返回结果是规范化后的清单，也就是现在这份计划。"
    ),
    parameters={
        "todos": "按顺序排列的完整计划。替换之前的清单；已完成的步骤也要发送并标成 'completed'。",
    },
)

ZH_TW = ToolText(
    description=(
        "把目前任務的計畫維護成一份有序清單。開始需要多個步驟的工作前先呼叫它：先把所有步驟"
        "寫成 'pending'，接著把正在做的那一步改成 'in_progress'，完成後立刻改成 'completed'；"
        "同時最多只有一個進行中，全部完成或還在規劃時可以沒有。每次呼叫都會取代整份清單，"
        "所以每次都要送出完整計畫，已完成的步驟也要保留並標成 'completed'。清單屬於整個工作階段"
        "而不是這一次呼叫：同一工作階段的後續任務會繼續使用它，並且會顯示給使用者，因此每一項都要"
        "簡短、具體、使用使用者的語言，不要列出不打算執行的步驟。最多 20 項，多數任務 2 到 7 項"
        "即可。回傳結果是正規化後的清單，也就是現在這份計畫。"
    ),
    parameters={
        "todos": "依序排列的完整計畫。取代先前的清單；已完成的步驟也要送出並標成 'completed'。",
    },
)

FR = ToolText(
    description=(
        "Tenez le plan de la tâche en cours sous forme de liste ordonnée. Appelez-le avant "
        "un travail qui demande plus de deux ou trois étapes : inscrivez d'abord toutes les "
        "étapes en 'pending', passez celle en cours en 'in_progress', puis en 'completed' "
        "dès qu'elle est finie - une seule étape en cours à la fois, ou aucune quand tout "
        "est terminé ou pendant la planification. Chaque appel remplace toute la liste : "
        "envoyez toujours le plan complet, étapes terminées comprises, marquées "
        "'completed'. La liste appartient à la conversation, pas à cet appel : elle survit "
        "à la tâche suivante de la même conversation et elle est montrée à l'utilisateur ; "
        "gardez donc chaque élément court, concret, dans la langue de l'utilisateur, et "
        "n'inscrivez pas d'étape que vous n'exécuterez pas. 20 éléments au maximum ; deux "
        "à sept suffisent pour la plupart des tâches. Le résultat renvoie la liste "
        "normalisée, qui est désormais « le plan »."
    ),
    parameters={
        "todos": (
            "Le plan complet, dans l'ordre. Remplace la liste précédente ; envoyez aussi "
            "les étapes terminées, marquées 'completed'."
        ),
    },
)

DE = ToolText(
    description=(
        "Führe den Plan der aktuellen Aufgabe als geordnete Checkliste. Rufe das Werkzeug "
        "auf, bevor Arbeit mit mehr als ein paar Schritten beginnt: schreibe zuerst alle "
        "Schritte als 'pending' auf, setze den Schritt, an dem du arbeitest, auf "
        "'in_progress' und wechsle ihn auf 'completed', sobald er fertig ist - höchstens "
        "ein Schritt gleichzeitig in Arbeit, keiner mehr, wenn alles erledigt ist oder du "
        "noch planst. Jeder Aufruf ersetzt die gesamte Liste: sende immer den vollständigen "
        "Plan, auch die erledigten Schritte, markiert als 'completed'. Die Liste gehört zum "
        "Gespräch, nicht zu diesem Aufruf: sie bleibt für die nächste Aufgabe desselben "
        "Gesprächs bestehen und wird dem Nutzer angezeigt. Halte jeden Eintrag kurz, "
        "konkret und in der Sprache des Nutzers, und liste keine Schritte auf, die du nicht "
        "ausführen wirst. Höchstens 20 Einträge; zwei bis sieben reichen für die meisten "
        "Aufgaben. Das Ergebnis gibt die normalisierte Liste zurück - das ist jetzt der Plan."
    ),
    parameters={
        "todos": (
            "Der vollständige Plan in Reihenfolge. Ersetzt die vorherige Liste; sende auch "
            "erledigte Schritte, markiert als 'completed'."
        ),
    },
)

RU = ToolText(
    description=(
        "Ведите план текущей задачи как упорядоченный список. Вызывайте инструмент перед "
        "работой, в которой больше пары шагов: сначала запишите все шаги как 'pending', "
        "затем переведите текущий шаг в 'in_progress' и сразу отметьте его 'completed', "
        "когда он готов, - одновременно в работе не больше одного шага, а когда всё "
        "готово или вы ещё планируете, таких шагов нет. Каждый вызов заменяет весь "
        "список: всегда отправляйте полный план, включая выполненные шаги с отметкой "
        "'completed'. Список принадлежит разговору, а не этому вызову: он сохраняется для "
        "следующей задачи того же разговора и показывается пользователю, поэтому каждый "
        "пункт должен быть коротким, конкретным и на языке пользователя; не вписывайте "
        "шаги, которые не собираетесь выполнять. Не больше 20 пунктов; для большинства "
        "задач достаточно двух-семи. Результат возвращает нормализованный список, который "
        "теперь и есть план."
    ),
    parameters={
        "todos": (
            "Полный план по порядку. Заменяет предыдущий список; отправляйте и выполненные "
            "шаги с отметкой 'completed'."
        ),
    },
)
