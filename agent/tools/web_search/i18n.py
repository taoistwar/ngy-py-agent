"""Display text for ``web_search`` in the admin page's languages.

The model always sees the English description and schema (``description.py``);
these bundles are read by the tool management page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "在互联网上搜索并返回排序后的结果：每条包含标题、网址与摘要。它只搜索、不打开页面——"
        "要读某一页请用 web_fetch。搜索后端由部署配置决定（默认后端无需密钥，也可配置 "
        "DeepSeek Search、Tavily、Serper 或 Bing 这类 API 后端），不是工具参数。'allowed_domains' 只保留这些"
        "站点，'blocked_domains' 排除这些站点；两者不能同时给，同时给会报错。域名包含其子域，"
        "所以 'example.com' 也允许 'docs.example.com'。'num_results' 默认 8，最多 20（超过按 "
        "20 处理）。'search_type' 取 'auto'（默认）、'fast' 或 'deep'；只有部分后端支持深度"
        "设置，结果里的 'search_type_applied' 会说明是否生效。'context_max_characters'（默认 "
        "10000）限制返回列表的字符数，超出的部分会被丢弃，'context_truncated' 给出丢弃的条数。"
        "结果包含 'query'、'provider'、'result_count'、'results'（每项含 'title'、'url'、"
        "'snippet'）、'duration_ms' 与 'content'（同一份列表的 Markdown 版本，带链接）。搜不到"
        "时 'result_count' 为 0 并附一句说明——这是答案而不是错误，重复同样的搜索没有意义。"
        "凡是用到这些结果，都要用 Markdown 链接标出来源。一个任务里第一次搜索会询问用户，"
        "同一任务的后续搜索不再询问。搜索是只读的，可以并行发起。"
    ),
    parameters={
        "query": "要搜什么。至少 2 个字符；像在搜索框里那样写下问题。",
        "allowed_domains": (
            "只返回这些站点的结果，用裸域名如 'example.com'（子域也包含）。不能与 "
            "'blocked_domains' 同时使用。"
        ),
        "blocked_domains": (
            "不返回这些站点的结果，用裸域名。不能与 'allowed_domains' 同时使用。"
        ),
        "num_results": "返回多少条结果。默认 8；超过 20 按 20 处理。",
        "search_type": (
            "'auto'（默认）兼顾速度与覆盖，'fast' 更快、结果更少，'deep' 更彻底。只有支持"
            "深度设置的后端才生效。"
        ),
        "context_max_characters": (
            "返回给你的结果列表的字符上限。默认 10000；超出的结果会被丢弃并说明。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "在網際網路上搜尋並傳回排序後的結果：每條包含標題、網址與摘要。它只搜尋、不開啟頁面——"
        "要讀某一頁請用 web_fetch。搜尋後端由部署設定決定（預設後端無需金鑰，也可設定 "
        "DeepSeek Search、Tavily、Serper 或 Bing 這類 API 後端），不是工具參數。'allowed_domains' 只保留這些"
        "站點，'blocked_domains' 排除這些站點；兩者不能同時給，同時給會報錯。網域包含其子網域，"
        "所以 'example.com' 也允許 'docs.example.com'。'num_results' 預設 8，最多 20（超過以 "
        "20 處理）。'search_type' 取 'auto'（預設）、'fast' 或 'deep'；只有部分後端支援深度"
        "設定，結果裡的 'search_type_applied' 會說明是否生效。'context_max_characters'（預設 "
        "10000）限制傳回清單的字元數，超出的部分會被丟棄，'context_truncated' 給出丟棄的條數。"
        "結果包含 'query'、'provider'、'result_count'、'results'（每項含 'title'、'url'、"
        "'snippet'）、'duration_ms' 與 'content'（同一份清單的 Markdown 版本，帶連結）。搜不到"
        "時 'result_count' 為 0 並附一句說明——這是答案而不是錯誤，重複同樣的搜尋沒有意義。"
        "凡是用到這些結果，都要用 Markdown 連結標出來源。一個任務裡第一次搜尋會詢問使用者，"
        "同一任務的後續搜尋不再詢問。搜尋是唯讀的，可以平行發起。"
    ),
    parameters={
        "query": "要搜尋什麼。至少 2 個字元；像在搜尋框裡那樣寫下問題。",
        "allowed_domains": (
            "只傳回這些站點的結果，用裸網域如 'example.com'（子網域也包含）。不能與 "
            "'blocked_domains' 同時使用。"
        ),
        "blocked_domains": (
            "不傳回這些站點的結果，用裸網域。不能與 'allowed_domains' 同時使用。"
        ),
        "num_results": "傳回多少條結果。預設 8；超過 20 以 20 處理。",
        "search_type": (
            "'auto'（預設）兼顧速度與覆蓋，'fast' 更快、結果更少，'deep' 更徹底。只有支援"
            "深度設定的後端才生效。"
        ),
        "context_max_characters": (
            "傳回給你的結果清單的字元上限。預設 10000；超出的結果會被丟棄並說明。"
        ),
    },
)

FR = ToolText(
    description=(
        "Cherche sur le Web et renvoie des résultats classés : un titre, une URL et un "
        "extrait pour chacun. L'outil ne lit pas les pages qu'il trouve : utilisez "
        "web_fetch pour en ouvrir une. Le moteur est défini par la configuration du "
        "déploiement (un moteur par défaut sans clé, ou une API comme DeepSeek Search, "
        "Tavily, Serper ou Bing) et n'est pas un paramètre de l'outil. 'allowed_domains' ne garde que ces "
        "sites et 'blocked_domains' les exclut ; les deux ne peuvent pas être combinés, "
        "et les fournir ensemble est une erreur. Un domaine couvre ses sous-domaines : "
        "'example.com' autorise donc 'docs.example.com'. 'num_results' vaut 8 par défaut "
        "et est plafonné à 20. 'search_type' vaut 'auto' (par défaut), 'fast' ou 'deep' ; "
        "seuls certains moteurs honorent la profondeur, et 'search_type_applied' indique "
        "si c'était le cas. 'context_max_characters' (10000 par défaut) borne le nombre "
        "de caractères renvoyés ; au-delà, des résultats sont écartés et "
        "'context_truncated' précise combien. Le résultat contient 'query', 'provider', "
        "'result_count', 'results' (avec 'title', 'url', 'snippet'), 'duration_ms' et "
        "'content' - la même liste en Markdown avec des liens. Une recherche sans "
        "résultat renvoie 'result_count': 0 et une phrase l'expliquant : c'est une "
        "réponse, pas une erreur, et répéter la même requête n'aidera pas. Lorsque vous "
        "utilisez ces résultats, citez chaque affirmation avec un lien Markdown vers sa "
        "source. La première recherche d'une tâche demande l'autorisation de "
        "l'utilisateur ; les suivantes ne la redemandent pas. La recherche est en "
        "lecture seule et peut être lancée en parallèle."
    ),
    parameters={
        "query": (
            "Ce qu'il faut chercher. Au moins 2 caractères ; écrivez-le comme dans un "
            "champ de recherche."
        ),
        "allowed_domains": (
            "Ne renvoyer que les résultats de ces sites, sous forme de domaines nus comme "
            "'example.com' (sous-domaines inclus). Incompatible avec 'blocked_domains'."
        ),
        "blocked_domains": (
            "Ne jamais renvoyer les résultats de ces sites, sous forme de domaines nus. "
            "Incompatible avec 'allowed_domains'."
        ),
        "num_results": (
            "Nombre de résultats à renvoyer. 8 par défaut ; au-delà de 20, la valeur est "
            "ramenée à 20."
        ),
        "search_type": (
            "'auto' (par défaut) équilibre vitesse et couverture, 'fast' répond plus vite "
            "avec moins de résultats, 'deep' cherche plus largement. Seuls les moteurs "
            "qui gèrent une profondeur en tiennent compte."
        ),
        "context_max_characters": (
            "Borne, en caractères, de la liste de résultats renvoyée. 10000 par défaut ; "
            "les résultats au-delà sont écartés et signalés."
        ),
    },
)

DE = ToolText(
    description=(
        "Durchsucht das Web und liefert sortierte Treffer: je Titel, URL und Auszug. "
        "Gefundene Seiten werden nicht geöffnet - dafür ist web_fetch zuständig. Das "
        "Backend ist Teil der Deployment-Konfiguration (Standard ohne Schlüssel, oder "
        "eine API wie DeepSeek Search, Tavily, Serper oder Bing) und kein Werkzeugparameter. "
        "'allowed_domains' behält nur diese Seiten, 'blocked_domains' schließt sie aus; "
        "beides zusammen ist ein Fehler. Eine Domain umfasst ihre Subdomains, "
        "'example.com' erlaubt also auch 'docs.example.com'. 'num_results' ist "
        "standardmäßig 8 und wird bei 20 gekappt. 'search_type' ist 'auto' (Standard), "
        "'fast' oder 'deep'; nur manche Backends kennen eine Tiefe, und "
        "'search_type_applied' sagt, ob sie wirksam war. 'context_max_characters' "
        "(Standard 10000) begrenzt die zurückgegebene Liste; darüber hinausgehende "
        "Treffer entfallen, und 'context_truncated' nennt die Anzahl. Das Ergebnis "
        "enthält 'query', 'provider', 'result_count', 'results' (mit 'title', 'url', "
        "'snippet'), 'duration_ms' und 'content' - dieselbe Liste als Markdown mit "
        "Links. Findet die Suche nichts, ist 'result_count': 0 und ein Satz erklärt es: "
        "das ist eine Antwort, kein Fehler, und dieselbe Suche zu wiederholen hilft "
        "nicht. Wer Ergebnisse verwendet, belegt jede Aussage mit einem Markdown-Link "
        "auf die Quelle. Die erste Suche einer Aufgabe fragt den Nutzer um Erlaubnis; "
        "weitere Suchen derselben Aufgabe nicht mehr. Suchen ist lesend und darf "
        "parallel laufen."
    ),
    parameters={
        "query": (
            "Was gesucht werden soll. Mindestens 2 Zeichen; formuliert wie in einem "
            "Suchfeld."
        ),
        "allowed_domains": (
            "Nur Treffer dieser Seiten zurückgeben, als reine Domains wie 'example.com' "
            "(Subdomains inklusive). Nicht mit 'blocked_domains' kombinierbar."
        ),
        "blocked_domains": (
            "Nie Treffer dieser Seiten zurückgeben, als reine Domains. Nicht mit "
            "'allowed_domains' kombinierbar."
        ),
        "num_results": (
            "Anzahl der Treffer. Standard 8; Werte über 20 werden auf 20 gekappt."
        ),
        "search_type": (
            "'auto' (Standard) gleicht Tempo und Abdeckung aus, 'fast' antwortet schneller "
            "mit weniger Treffern, 'deep' sucht gründlicher. Nur Backends mit "
            "Tiefenoption beachten es."
        ),
        "context_max_characters": (
            "Obergrenze in Zeichen für die zurückgegebene Trefferliste. Standard 10000; "
            "weitere Treffer entfallen und werden gemeldet."
        ),
    },
)

RU = ToolText(
    description=(
        "Ищет в интернете и возвращает упорядоченные результаты: заголовок, URL и "
        "фрагмент для каждого. Страницы не открываются - для чтения страницы есть "
        "web_fetch. Поисковый сервис задаётся конфигурацией развёртывания (по умолчанию "
        "без ключа, либо API вроде DeepSeek Search, Tavily, Serper или Bing) и не является параметром "
        "инструмента. 'allowed_domains' оставляет только эти сайты, 'blocked_domains' "
        "их исключает; вместе их передавать нельзя - это ошибка. Домен включает "
        "поддомены, поэтому 'example.com' разрешает и 'docs.example.com'. "
        "'num_results' по умолчанию 8 и ограничен 20. 'search_type' - 'auto' (по "
        "умолчанию), 'fast' или 'deep'; глубину понимают не все сервисы, и "
        "'search_type_applied' сообщает, применилась ли она. 'context_max_characters' "
        "(по умолчанию 10000) ограничивает длину возвращаемого списка; лишние "
        "результаты отбрасываются, а 'context_truncated' указывает сколько. Результат "
        "содержит 'query', 'provider', 'result_count', 'results' (с 'title', 'url', "
        "'snippet'), 'duration_ms' и 'content' - тот же список в Markdown со ссылками. "
        "Если ничего не найдено, 'result_count': 0 и поясняющая фраза: это ответ, а не "
        "ошибка, и повторять тот же запрос бесполезно. Используя результаты, "
        "подкрепляйте каждое утверждение ссылкой Markdown на источник. Первый поиск в "
        "задаче запрашивает разрешение у пользователя; последующие - уже нет. Поиск "
        "только читает и может выполняться параллельно."
    ),
    parameters={
        "query": (
            "Что искать. Не менее 2 символов; формулируйте так, как ввели бы в строку "
            "поиска."
        ),
        "allowed_domains": (
            "Возвращать результаты только с этих сайтов, в виде доменов без схемы, "
            "например 'example.com' (поддомены включены). Несовместимо с "
            "'blocked_domains'."
        ),
        "blocked_domains": (
            "Никогда не возвращать результаты с этих сайтов, в виде доменов без схемы. "
            "Несовместимо с 'allowed_domains'."
        ),
        "num_results": (
            "Сколько результатов вернуть. По умолчанию 8; значения выше 20 "
            "ограничиваются 20."
        ),
        "search_type": (
            "'auto' (по умолчанию) уравновешивает скорость и охват, 'fast' отвечает "
            "быстрее и меньшим числом результатов, 'deep' ищет тщательнее. Учитывается "
            "только сервисами с настройкой глубины."
        ),
        "context_max_characters": (
            "Предел длины возвращаемого списка в символах. По умолчанию 10000; "
            "остальные результаты отбрасываются и это указывается."
        ),
    },
)
