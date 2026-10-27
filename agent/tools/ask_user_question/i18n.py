"""Chinese display text for ``ask_user_question``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "向用户提出一到三个简短问题并等待回答。当决定确实该由用户来做（两种设计选哪个、"
        "以哪个环境为目标、要不要替换某个东西），而且答案会改变你接下来的做法时使用。"
        "不要用它申请许可：工具调用由客户端确认，不由你确认。一次调用里把需要问的问题都问完"
        "（最多三个），每个问题只用一句话，给出两到三个互斥选项，把推荐项放在第一个并在标签"
        "末尾加 '(Recommended)'。不要添加 'Other' 选项：客户端会给每个问题自动加一个自由填写"
        "的选项。结果是以每个问题 id 为键的 JSON（'{\"answers\": {\"<id>\": {\"answers\": "
        "[...]}}}'）；用户选中的选项以标签形式出现，用户输入的内容作为另一项出现，被跳过的"
        "问题得到空数组。没人回答时 —— 没有客户端连接，或等待超时 —— 答案集为空且结果会说明"
        "原因：用你已有的信息自行决定，说明所做的假设，不要再问一次。"
    ),
    parameters={
        "questions": "要展示给用户的问题。优先 1 个，不要超过 3 个。",
    },
)

ZH_TW = ToolText(
    description=(
        "向使用者提出一到三個簡短問題並等待回答。當決定確實該由使用者來做（兩種設計選哪個、"
        "以哪個環境為目標、要不要替換某個東西），而且答案會改變你接下來的做法時使用。"
        "不要用它申請許可：工具呼叫由用戶端確認，不由你確認。一次呼叫裡把需要問的問題都問完"
        "（最多三個），每個問題只用一句話，給出兩到三個互斥選項，把推薦項放在第一個並在標籤"
        "末尾加上 '(Recommended)'。不要自行加入 'Other' 選項：用戶端會為每個問題自動加一個"
        "自由填寫的選項。結果是以每個問題 id 為鍵的 JSON（'{\"answers\": {\"<id>\": {\"answers\": "
        "[...]}}}'）；使用者選中的選項以標籤形式出現，使用者輸入的內容作為另一項出現，被略過的"
        "問題得到空陣列。沒人回答時 —— 沒有用戶端連線，或等待逾時 —— 答案集為空且結果會說明"
        "原因：用你既有的資訊自行決定，說明所做的假設，不要再問一次。"
    ),
    parameters={
        "questions": "要展示給使用者的問題。優先 1 個，不要超過 3 個。",
    },
)

FR = ToolText(
    description=(
        "Pose à l'utilisateur une à trois questions courtes et attend les réponses. À utiliser "
        "quand la décision revient vraiment à l'utilisateur (quelle option de conception retenir, "
        "quel environnement viser, faut-il remplacer quelque chose) et que la réponse change la "
        "suite. Ne pas s'en servir pour demander une autorisation : les appels d'outils sont "
        "confirmés par le client, pas par vous. Posez toutes les questions nécessaires en un seul "
        "appel (trois au maximum), une phrase par question, avec deux ou trois options mutuellement "
        "exclusives, l'option recommandée en premier et le suffixe '(Recommended)' à la fin de son "
        "libellé. N'ajoutez pas d'option 'Other' : le client ajoute automatiquement un champ libre "
        "à chaque question. Le résultat est un JSON dont les clés sont les id des questions "
        "('{\"answers\": {\"<id>\": {\"answers\": [...]}}}') ; les options choisies apparaissent "
        "sous forme de libellés, le texte saisi par l'utilisateur apparaît comme une entrée "
        "supplémentaire, et une question ignorée reçoit un tableau vide. Si personne ne répond — "
        "aucun client connecté, ou délai dépassé — l'ensemble des réponses est vide et le résultat "
        "en donne la raison : décidez avec ce que vous avez, expliquez l'hypothèse retenue et ne "
        "reposez pas la question."
    ),
    parameters={
        "questions": "Questions à présenter à l'utilisateur. Une seule de préférence, trois au maximum.",
    },
)

DE = ToolText(
    description=(
        "Stellt dem Benutzer ein bis drei kurze Fragen und wartet auf die Antworten. Verwenden, "
        "wenn die Entscheidung wirklich beim Benutzer liegt (welche von zwei Designvarianten, "
        "welche Umgebung, soll etwas ersetzt werden) und die Antwort das weitere Vorgehen ändert. "
        "Nicht für Berechtigungen verwenden: Werkzeugaufrufe bestätigt der Client, nicht du. "
        "Stelle alle nötigen Fragen in einem Aufruf (höchstens drei), eine Frage pro Satz, mit "
        "zwei bis drei sich ausschließenden Optionen, die empfohlene Option zuerst und mit dem "
        "Zusatz '(Recommended)' am Ende der Beschriftung. Füge keine Option 'Other' hinzu: der "
        "Client ergänzt zu jeder Frage automatisch ein Freitextfeld. Das Ergebnis ist JSON mit der "
        "id jeder Frage als Schlüssel ('{\"answers\": {\"<id>\": {\"answers\": [...]}}}'); gewählte "
        "Optionen erscheinen als Beschriftung, selbst eingegebener Text als weiterer Eintrag, "
        "übersprungene Fragen erhalten ein leeres Array. Antwortet niemand — kein Client verbunden "
        "oder Zeitüberschreitung —, ist die Antwortmenge leer und das Ergebnis nennt den Grund: "
        "entscheide mit den vorhandenen Informationen, nenne die getroffene Annahme und frage "
        "nicht erneut."
    ),
    parameters={
        "questions": "Die dem Benutzer zu zeigenden Fragen. Bevorzugt eine, höchstens drei.",
    },
)

RU = ToolText(
    description=(
        "Задаёт пользователю от одного до трёх коротких вопросов и ждёт ответа. Используйте, "
        "когда решение действительно за пользователем (какой из двух вариантов дизайна, какое "
        "окружение взять, нужно ли что-то заменить) и ответ меняет ваши дальнейшие действия. "
        "Не используйте инструмент для запроса разрешений: вызовы инструментов подтверждает "
        "клиент, а не вы. Задайте все нужные вопросы за один вызов (не больше трёх), по одному "
        "предложению на вопрос, с двумя-тремя взаимоисключающими вариантами; рекомендуемый "
        "вариант ставьте первым и добавляйте в конец его подписи '(Recommended)'. Не добавляйте "
        "вариант 'Other': клиент сам добавляет к каждому вопросу поле свободного ввода. "
        "Результат — JSON с id каждого вопроса в качестве ключа "
        "('{\"answers\": {\"<id>\": {\"answers\": [...]}}}'); выбранные варианты приходят как "
        "подписи, введённый пользователем текст — как отдельный элемент, пропущенный вопрос "
        "получает пустой массив. Если никто не ответил — нет подключённого клиента или истекло "
        "время ожидания — набор ответов пуст, а результат объясняет причину: решайте сами на "
        "основе имеющегося, укажите сделанное допущение и не спрашивайте снова."
    ),
    parameters={
        "questions": "Вопросы для показа пользователю. Лучше один, не больше трёх.",
    },
)
