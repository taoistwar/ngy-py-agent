"""Translated display text for the six board tools.

The model always gets the English ``description``/``parameters`` from each tool
package; this is read by the admin tool page only, so ``test/tool_api_test.py`` can
assert that no language falls back to English on a mixed-language screen.

One module for all six because they are one vocabulary: "the task id" means the same
thing in five calls, and six copies of that sentence would drift apart. Each tool
package imports its own bundle, so reading one tool still starts in its package.
"""

from __future__ import annotations

from typing import Any, Dict

from agent.tools.spec import ToolText, localized_texts

# Shared parameter text: the id is always "the one the board listed".
TASK_ID_ZH_CN = "要操作的任务 id，与任务板列出的一致。"
TASK_ID_ZH_TW = "要操作的任務 id，與任務板列出的一致。"
TASK_ID_FR = "L'identifiant de la tâche, tel que le tableau l'affiche."
TASK_ID_DE = "Die Task-ID, so wie das Board sie anzeigt."
TASK_ID_RU = "Идентификатор задачи в том виде, в каком его показывает доска."


CREATE_TEXTS: Dict[str, Any] = localized_texts(
    zh_cn=ToolText(
        description=(
            "在项目任务板上新建一个任务：有 id、负责人和前置依赖。任务板是项目级计划，"
            "不是本次会话的步骤清单（步骤用 todo_write）。先建出全部节点并记下返回的 id，"
            "再用 task_update 连边——同一条回复里拿不到另一个调用刚生成的 id。subject "
            "写一行祈使句，description 写清什么算完成。新任务是 pending 且无主，"
            "用 task_claim 认领。"
        ),
        parameters={
            "subject": "一行祈使句：这个任务交付什么。",
            "description": "什么算完成：验收方式、涉及文件、约束；subject 已说清时可留空。",
        },
    ),
    zh_tw=ToolText(
        description=(
            "在專案任務板上新增一個任務：有 id、負責人與前置相依。任務板是專案級計畫，"
            "不是本次工作階段的步驟清單（步驟請用 todo_write）。先建立全部節點並記下回傳的 id，"
            "再用 task_update 連邊——同一則回覆裡拿不到另一個呼叫剛產生的 id。subject "
            "寫一行祈使句，description 寫清楚什麼算完成。新任務是 pending 且無主，"
            "用 task_claim 認領。"
        ),
        parameters={
            "subject": "一行祈使句：這個任務交付什麼。",
            "description": "什麼算完成：驗收方式、涉及檔案、限制；subject 已說清楚時可留空。",
        },
    ),
    fr=ToolText(
        description=(
            "Crée une tâche sur le tableau du projet : un identifiant, un responsable et "
            "des prérequis. Le tableau est le plan du projet, pas la liste des étapes de "
            "cette conversation (pour cela, todo_write). Crée d'abord tous les nœuds et "
            "relis les identifiants renvoyés, puis ajoute les dépendances avec task_update. "
            "Le sujet tient en une ligne à l'impératif ; la description dit ce que "
            "'terminé' signifie. Une tâche naît 'pending' et sans responsable : "
            "task_claim la démarre."
        ),
        parameters={
            "subject": "Une ligne à l'impératif : ce que la tâche livre.",
            "description": "Ce que 'terminé' veut dire : critères, fichiers, contraintes. Facultatif.",
        },
    ),
    de=ToolText(
        description=(
            "Legt eine Aufgabe auf dem Projektboard an: mit ID, Verantwortlichem und "
            "Voraussetzungen. Das Board ist der Plan des Projekts, nicht die Schritte "
            "dieses Gesprächs (dafür todo_write). Lege zuerst alle Knoten an und lies die "
            "zurückgegebenen IDs, dann verbinde sie mit task_update. Das Subject ist eine "
            "kurze Aufforderung, die Beschreibung sagt, wann die Aufgabe fertig ist. Neue "
            "Aufgaben sind 'pending' und ohne Verantwortlichen; task_claim startet sie."
        ),
        parameters={
            "subject": "Eine kurze Aufforderung: was die Aufgabe liefert.",
            "description": "Was 'fertig' heißt: Kriterien, Dateien, Einschränkungen. Optional.",
        },
    ),
    ru=ToolText(
        description=(
            "Создаёт задачу на доске проекта: с идентификатором, ответственным и "
            "зависимостями. Доска - это план проекта, а не шаги текущего разговора (для них "
            "есть todo_write). Сначала создайте все узлы и запомните выданные "
            "идентификаторы, затем свяжите их через task_update. Subject - одна короткая "
            "строка в повелительном наклонении, description объясняет, что считается "
            "готовым. Новая задача 'pending' и без ответственного; её начинает task_claim."
        ),
        parameters={
            "subject": "Одна короткая строка: что даёт задача.",
            "description": "Что значит 'готово': критерии, файлы, ограничения. Необязательно.",
        },
    ),
)


UPDATE_TEXTS: Dict[str, Any] = localized_texts(
    zh_cn=ToolText(
        description=(
            "给任务板上的任务追加前置依赖，这就是任务板的排序方式：先建全部任务，再用 "
            "task_create 返回的 id 逐条连边。只有前置全部 completed 任务才能被认领，"
            "所以一条边等于『不早于那个任务』。只能修改 pending 且无人认领的任务；"
            "自依赖、环、未知 id 会被拒绝，已存在的边重复添加是空操作。"
        ),
        parameters={
            "task_id": TASK_ID_ZH_CN,
            "add_blocked_by": "必须先完成的任务 id，追加到现有依赖之后，不会替换。",
        },
    ),
    zh_tw=ToolText(
        description=(
            "為任務板上的任務追加前置相依，這就是任務板的排序方式：先建立全部任務，再用 "
            "task_create 回傳的 id 逐條連邊。只有前置全部 completed 的任務才能被認領，"
            "所以一條邊等於『不早於那個任務』。只能修改 pending 且無人認領的任務；"
            "自相依、環、未知 id 會被拒絕，已存在的邊重複加入是空操作。"
        ),
        parameters={
            "task_id": TASK_ID_ZH_TW,
            "add_blocked_by": "必須先完成的任務 id，追加到現有相依之後，不會取代。",
        },
    ),
    fr=ToolText(
        description=(
            "Ajoute des prérequis à une tâche du tableau : c'est ainsi que le projet est "
            "séquencé. Crée d'abord toutes les tâches, puis ajoute une arête par appel avec "
            "les identifiants renvoyés par task_create. Une tâche ne peut être prise que "
            "lorsque tous ses prérequis sont terminés. Seule une tâche 'pending' et sans "
            "responsable peut être modifiée ; les cycles, les auto-dépendances et les "
            "identifiants inconnus sont refusés, une arête déjà présente est ignorée."
        ),
        parameters={
            "task_id": TASK_ID_FR,
            "add_blocked_by": "Identifiants des tâches à terminer avant celle-ci (ajout, pas remplacement).",
        },
    ),
    de=ToolText(
        description=(
            "Ergänzt Voraussetzungen einer Aufgabe auf dem Board - so wird das Projekt "
            "geordnet. Lege zuerst alle Aufgaben an und füge dann pro Aufruf eine Kante mit "
            "den IDs aus task_create hinzu. Eine Aufgabe lässt sich erst übernehmen, wenn "
            "alle Voraussetzungen erledigt sind. Änderbar ist nur eine 'pending' Aufgabe "
            "ohne Verantwortlichen; Zyklen, Selbstbezüge und unbekannte IDs werden "
            "abgelehnt, eine bereits vorhandene Kante ist wirkungslos."
        ),
        parameters={
            "task_id": TASK_ID_DE,
            "add_blocked_by": "IDs der Aufgaben, die vorher fertig sein müssen (wird ergänzt, nicht ersetzt).",
        },
    ),
    ru=ToolText(
        description=(
            "Добавляет задаче на доске зависимости - так проект и упорядочивается. Сначала "
            "создайте все задачи, затем добавляйте по одной связи за вызов, используя "
            "идентификаторы из task_create. Взять задачу можно только когда все её "
            "зависимости завершены. Менять можно лишь задачу в состоянии 'pending' без "
            "ответственного; циклы, самозависимости и неизвестные идентификаторы "
            "отклоняются, уже существующая связь ничего не меняет."
        ),
        parameters={
            "task_id": TASK_ID_RU,
            "add_blocked_by": "Идентификаторы задач, которые должны быть завершены раньше (добавляются, не заменяют).",
        },
    ),
)


LIST_TEXTS: Dict[str, Any] = localized_texts(
    zh_cn=ToolText(
        description=(
            "列出项目任务板：每个任务一行，含 id、subject、状态、负责人以及现在能否认领。"
            "开始一个可能已有计划的项目前先读它——别的会话可能已经建好任务并完成了其中一些；"
            "完成一个任务后再读一次，看解锁了什么。"
        )
    ),
    zh_tw=ToolText(
        description=(
            "列出專案任務板：每個任務一行，含 id、subject、狀態、負責人以及現在能否認領。"
            "開始一個可能已有計畫的專案前先讀它——其他工作階段可能已經建好任務並完成了其中一些；"
            "完成一個任務後再讀一次，看解鎖了什麼。"
        )
    ),
    fr=ToolText(
        description=(
            "Liste le tableau du projet : une ligne par tâche avec son identifiant, son "
            "sujet, son statut, son responsable et si elle peut être prise maintenant. À "
            "lire avant de commencer sur un projet qui a peut-être déjà un plan, et de "
            "nouveau après avoir terminé une tâche, pour voir ce qu'elle a débloqué."
        )
    ),
    de=ToolText(
        description=(
            "Listet das Projektboard auf: eine Zeile pro Aufgabe mit ID, Subject, Status, "
            "Verantwortlichem und ob sie jetzt übernommen werden kann. Vor der Arbeit an "
            "einem Projekt lesen, das schon einen Plan haben kann, und erneut nach dem "
            "Abschluss einer Aufgabe, um zu sehen, was sie freigegeben hat."
        )
    ),
    ru=ToolText(
        description=(
            "Показывает доску проекта: по строке на задачу с идентификатором, subject, "
            "статусом, ответственным и тем, можно ли её взять сейчас. Читайте перед "
            "началом работы над проектом, у которого уже может быть план, и снова после "
            "завершения задачи, чтобы увидеть, что она разблокировала."
        )
    ),
)


GET_TEXTS: Dict[str, Any] = localized_texts(
    zh_cn=ToolText(
        description=(
            "读取任务板上一个任务的全文：description、前置依赖和负责人。task_list 是一行概览，"
            "这个才是续做别人任务前要读的——验收标准和涉及的文件都在 description 里。"
        ),
        parameters={"task_id": TASK_ID_ZH_CN},
    ),
    zh_tw=ToolText(
        description=(
            "讀取任務板上一個任務的全文：description、前置相依與負責人。task_list 是一行概覽，"
            "這個才是續做別人任務前要讀的——驗收標準與涉及的檔案都在 description 裡。"
        ),
        parameters={"task_id": TASK_ID_ZH_TW},
    ),
    fr=ToolText(
        description=(
            "Lit une tâche du tableau en entier : description, prérequis et responsable. "
            "task_list n'en donne qu'une ligne ; c'est ici que se trouvent les critères "
            "d'acceptation et les fichiers, quand on reprend le travail d'une autre "
            "conversation."
        ),
        parameters={"task_id": TASK_ID_FR},
    ),
    de=ToolText(
        description=(
            "Liest eine Aufgabe des Boards vollständig: Beschreibung, Voraussetzungen und "
            "Verantwortlicher. task_list zeigt nur eine Zeile; die Abnahmekriterien und "
            "Dateien stehen hier - nötig, wenn eine andere Konversation die Arbeit begonnen hat."
        ),
        parameters={"task_id": TASK_ID_DE},
    ),
    ru=ToolText(
        description=(
            "Читает задачу с доски целиком: описание, зависимости и ответственного. "
            "task_list даёт только строку; критерии приёмки и файлы находятся здесь - это "
            "нужно, когда работу начал другой разговор."
        ),
        parameters={"task_id": TASK_ID_RU},
    ),
)


CLAIM_TEXTS: Dict[str, Any] = localized_texts(
    zh_cn=ToolText(
        description=(
            "认领任务板上的任务：状态变为 in_progress，负责人记为本次会话。只有前置全部"
            "完成的任务才能认领；被阻塞时会返回它在等什么，那就是先去做那个任务。动手前先"
            "认领，别让另一个会话重复开始同一件事；做完用 task_complete 结束，等它的任务"
            "才能开始。"
        ),
        parameters={"task_id": TASK_ID_ZH_CN},
    ),
    zh_tw=ToolText(
        description=(
            "認領任務板上的任務：狀態變成 in_progress，負責人記為本次工作階段。只有前置全部"
            "完成的任務才能認領；被阻塞時會回傳它在等什麼，那就是先去做那個任務。動手前先"
            "認領，別讓另一個工作階段重複開始同一件事；做完用 task_complete 結束，等它的任務"
            "才能開始。"
        ),
        parameters={"task_id": TASK_ID_ZH_TW},
    ),
    fr=ToolText(
        description=(
            "Prend une tâche du tableau : elle passe 'in_progress' et la conversation "
            "devient responsable. Seule une tâche dont tous les prérequis sont terminés "
            "peut être prise ; une tâche bloquée répond ce qu'elle attend. Prends la tâche "
            "avant de commencer pour éviter le doublon, et termine-la avec task_complete."
        ),
        parameters={"task_id": TASK_ID_FR},
    ),
    de=ToolText(
        description=(
            "Übernimmt eine Aufgabe vom Board: Status 'in_progress', das Gespräch wird als "
            "Verantwortlicher eingetragen. Übernehmbar ist nur eine Aufgabe, deren "
            "Voraussetzungen alle erledigt sind; eine blockierte Aufgabe antwortet, worauf "
            "sie wartet. Vor der Arbeit übernehmen, damit keine doppelte Arbeit entsteht."
        ),
        parameters={"task_id": TASK_ID_DE},
    ),
    ru=ToolText(
        description=(
            "Берёт задачу с доски: статус становится 'in_progress', ответственным "
            "записывается этот разговор. Взять можно только задачу, все зависимости которой "
            "завершены; заблокированная ответит, чего она ждёт. Берите задачу до начала "
            "работы, чтобы не было дублей, и завершайте через task_complete."
        ),
        parameters={"task_id": TASK_ID_RU},
    ),
)


COMPLETE_TEXTS: Dict[str, Any] = localized_texts(
    zh_cn=ToolText(
        description=(
            "把本次会话认领的任务标记为完成，并报告这次完成解锁了哪些任务。只有本会话认领的 "
            "in_progress 任务能完成，别的会话认领的任务要在那边结束（错误里会说明是谁）。"
            "验证通过就立刻完成，不要拖到会话结束：图里下一个任务在等它。"
        ),
        parameters={"task_id": TASK_ID_ZH_CN},
    ),
    zh_tw=ToolText(
        description=(
            "把本次工作階段認領的任務標記為完成，並回報這次完成解鎖了哪些任務。只有本工作階段"
            "認領的 in_progress 任務能完成，其他工作階段認領的任務要在那邊結束（錯誤會說明是誰）。"
            "驗證通過就立刻完成，不要拖到工作階段結束：圖裡下一個任務在等它。"
        ),
        parameters={"task_id": TASK_ID_ZH_TW},
    ),
    fr=ToolText(
        description=(
            "Marque comme terminée la tâche que cette conversation a prise, et indique ce "
            "qu'elle débloque. Seule une tâche 'in_progress' dont cette conversation est "
            "responsable peut être terminée : une tâche prise ailleurs se termine là-bas. "
            "Termine dès que le travail est vérifié, pas en fin de session."
        ),
        parameters={"task_id": TASK_ID_FR},
    ),
    de=ToolText(
        description=(
            "Schließt die von diesem Gespräch übernommene Aufgabe ab und meldet, was sie "
            "freigibt. Abschließbar ist nur eine 'in_progress' Aufgabe dieses Gesprächs; "
            "eine anderswo übernommene Aufgabe wird dort beendet. Sofort abschließen, wenn "
            "die Arbeit geprüft ist - die nächste Aufgabe wartet darauf."
        ),
        parameters={"task_id": TASK_ID_DE},
    ),
    ru=ToolText(
        description=(
            "Завершает задачу, взятую этим разговором, и сообщает, что она разблокировала. "
            "Завершить можно только задачу 'in_progress', взя́тую этим разговором; чужую "
            "закрывают там, где её взяли. Завершайте сразу после проверки работы - "
            "следующая задача ждёт именно этого."
        ),
        parameters={"task_id": TASK_ID_RU},
    ),
)
