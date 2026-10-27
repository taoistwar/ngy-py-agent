"""Chinese display text for ``grep``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "用正则表达式搜索文件内容（Python 're' 语法，默认逐行匹配）。返回形状由 "
        "'output_mode' 决定：'files_with_matches'（默认）列出含匹配的文件，按修改时间从新"
        "到旧；'content' 返回命中行，形如 'path:line:text'，上下文行为 'path-line-text'，"
        "不相邻的组之间用 '--' 分隔；'count' 返回每个文件的命中行数与总数。默认逐行匹配，"
        "设置 'multiline' 后模式可以跨行（此时 'context'/'line_numbers' 不再起作用）。"
        "搜索范围就是仓库自己认定的源码：隐藏文件同样会搜，但 .gitignore 排除的文件（逐目录"
        "读取，从搜索根往下）、版本库元数据（.git 等）、已安装依赖与构建产物（node_modules、"
        ".venv、dist、build、target…）、二进制文件、超过 8MB 的文件，以及看起来像凭证的文件"
        "会被跳过——最后一类会列在 'skipped_sensitive' 里，因为它们仍可用 read_file 读取。"
        "没有开关能放开被忽略的文件，需要时把 'path' 指向那个目录即可。"
        "'glob' 与 'type' 用于缩小搜索的文件范围。单次最多返回 250 条输出行/路径，用 "
        "'offset'/'head_limit' 翻页（'head_limit' 为 0 表示不限），不要靠放宽模式硬凑；"
        "超长行会在 500 字符处截断。返回的路径相对于工作空间根，可直接传给 read_file。"
        "想按文件名找文件用 glob，想找某段代码写在哪里用 grep。"
    ),
    parameters={
        "pattern": (
            "要搜索的正则表达式（Python 're' 语法）。特殊字符必须转义，"
            "例如找 'interface{}' 要写成 'interface\\{\\}'。"
        ),
        "path": (
            "要搜索的文件或目录，相对于工作空间根（绝对路径只有在仍位于工作空间内时才被"
            "接受）。省略时使用工作空间根。"
        ),
        "glob": "只搜索文件名匹配该模式的文件，例如 '*.py' 或 '*.{ts,tsx}'。多个模式可用逗号或空格分隔。",
        "type": (
            "只搜索某种语言的文件，例如 'py'、'js'、'ts'、'rust'、'go'、'java'、'json'、"
            "'yaml'、'markdown'、'sh'。未知名称会被拒绝并给出支持列表。"
        ),
        "output_mode": (
            "'files_with_matches'（默认）只看路径，'content' 看命中行，'count' 数每个文件"
            "命中多少行。"
        ),
        "case_insensitive": "匹配时忽略大小写。默认 false。",
        "multiline": (
            "允许模式跨行（'.' 也能匹配换行，便于搜 'struct \\{[\\s\\S]*?field' 这类结构）。"
            "默认 false。"
        ),
        "line_numbers": (
            "在 'content' 模式下给每行加上 1 起始行号。默认 true；其它模式始终按文件汇报结果。"
        ),
        "context": (
            "在 'content' 模式下每条命中前后各显示几行。优先于 'before_context'/'after_context'；"
            "设置 'multiline' 时无效。"
        ),
        "before_context": "在 'content' 模式下每条命中前显示几行。",
        "after_context": "在 'content' 模式下每条命中后显示几行。",
        "head_limit": (
            "最多返回多少条输出行（content）、路径（files_with_matches）或计数（count）。"
            "默认 250；填 0 表示不限。"
        ),
        "offset": "先跳过多少条结果，用于翻到下一页。",
    },
)

ZH_TW = ToolText(
    description=(
        "用正規表達式搜尋檔案內容（Python 're' 語法，預設逐行比對）。傳回形狀由 "
        "'output_mode' 決定：'files_with_matches'（預設）列出含相符的檔案，依修改時間從新到舊；"
        "'content' 傳回命中行，形如 'path:line:text'，上下文行為 'path-line-text'，不相鄰的組"
        "之間用 '--' 分隔；'count' 傳回每個檔案的命中行數與總數。預設逐行比對，設定 "
        "'multiline' 後樣式可以跨行。隱藏檔案同樣會被搜尋，但版本庫中繼資料（.git 等）、"
        "已安裝依賴與建置產物（node_modules、.venv、dist、build、target…）、二進位檔、超過 "
        "8MB 的檔案，以及看起來像憑證的檔案會被略過 —— 最後一類會列在 'skipped_sensitive' 裡，"
        "因為它們仍可用 read_file 讀取；把 'path' 明確指向被略過的目錄則會照常搜尋它。工具的"
        "忽略規則不讀 .gitignore，因此被它忽略的檔案仍會參與搜尋。'glob' 與 'type' 用於縮小"
        "搜尋的檔案範圍。單次最多傳回 250 條輸出行／路徑，用 'offset'/'head_limit' 翻頁"
        "（'head_limit' 為 0 表示不限），不要靠放寬樣式硬湊；超長行會在 500 字元處截斷。"
        "傳回的路徑相對於工作區根，可直接傳給 read_file。想按檔名找檔案用 glob，想找某段"
        "程式碼寫在哪裡用 grep。"
    ),
    parameters={
        "pattern": (
            "要搜尋的正規表達式（Python 're' 語法）。特殊字元必須轉義，"
            "例如找 'interface{}' 要寫成 'interface\\{\\}'。"
        ),
        "path": (
            "要搜尋的檔案或目錄，相對於工作區根（絕對路徑只有在仍位於工作區內時才被接受）。"
            "省略時使用工作區根。"
        ),
        "glob": "只搜尋檔名符合該樣式的檔案，例如 '*.py' 或 '*.{ts,tsx}'。多個樣式可用逗號或空格分隔。",
        "type": (
            "只搜尋某種語言的檔案，例如 'py'、'js'、'ts'、'rust'、'go'、'java'、'json'、"
            "'yaml'、'markdown'、'sh'。未知名稱會被拒絕並給出支援清單。"
        ),
        "output_mode": (
            "'files_with_matches'（預設）只看路徑，'content' 看命中行，'count' 數每個檔案"
            "命中多少行。"
        ),
        "case_insensitive": "比對時忽略大小寫。預設 false。",
        "multiline": (
            "允許樣式跨行（'.' 也能相符換行，便於搜 'struct \\{[\\s\\S]*?field' 這類結構）。"
            "預設 false。"
        ),
        "line_numbers": (
            "在 'content' 模式下給每行加上 1 起始行號。預設 true；其它模式始終按檔案回報結果。"
        ),
        "context": "在 'content' 模式下每條命中前後各顯示幾行。優先於 'before_context'/'after_context'。",
        "before_context": "在 'content' 模式下每條命中前顯示幾行。",
        "after_context": "在 'content' 模式下每條命中後顯示幾行。",
        "head_limit": (
            "最多傳回多少條輸出行（content）、路徑（files_with_matches）或計數（count）。"
            "預設 250；填 0 表示不限。"
        ),
        "offset": "先略過多少條結果，用於翻到下一頁。",
    },
)

FR = ToolText(
    description=(
        "Cherche dans le contenu des fichiers avec une expression régulière (syntaxe 're' de "
        "Python, ligne par ligne par défaut). La forme du résultat dépend de 'output_mode' : "
        "'files_with_matches' (par défaut) liste les fichiers qui correspondent, du plus "
        "récemment modifié au plus ancien ; 'content' renvoie les lignes trouvées sous la forme "
        "'path:line:text', les lignes de contexte sous la forme 'path-line-text', les groupes non "
        "adjacents séparés par '--' ; 'count' renvoie le nombre de lignes trouvées par fichier et "
        "le total. La correspondance est ligne par ligne par défaut ; avec 'multiline', le motif "
        "peut traverser les lignes. Les fichiers cachés sont aussi cherchés, mais les métadonnées "
        "de gestion de version (.git, etc.), les dépendances installées et les artefacts de build "
        "(node_modules, .venv, dist, build, target…), les fichiers binaires, ceux de plus de 8 Mo "
        "et ceux qui ressemblent à des identifiants sont ignorés — ces derniers sont listés dans "
        "'skipped_sensitive', car read_file peut encore les lire ; pointer 'path' explicitement "
        "sur un dossier ignoré le fait chercher normalement. Les règles d'exclusion de l'outil ne "
        "lisent pas .gitignore : un fichier ignoré par Git participe donc à la recherche. 'glob' "
        "et 'type' restreignent les fichiers cherchés. Un appel renvoie au plus 250 lignes de "
        "sortie ou chemins ; paginez avec 'offset'/'head_limit' ('head_limit' à 0 signifie sans "
        "limite) au lieu d'élargir le motif au hasard ; les lignes trop longues sont tronquées à "
        "500 caractères. Les chemins renvoyés sont relatifs à la racine de l'espace de travail et "
        "peuvent être passés à read_file. Pour trouver un fichier par son nom, utilisez glob ; "
        "pour savoir où se trouve un bout de code, grep."
    ),
    parameters={
        "pattern": (
            "Expression régulière à chercher (syntaxe 're' de Python). Les caractères spéciaux "
            "doivent être échappés : pour chercher 'interface{}', écrivez 'interface\\{\\}'."
        ),
        "path": (
            "Fichier ou dossier à chercher, relatif à la racine de l'espace de travail (un chemin "
            "absolu n'est accepté que s'il reste dans l'espace de travail). Omis, la racine de "
            "l'espace de travail est utilisée."
        ),
        "glob": (
            "Ne chercher que dans les fichiers dont le nom correspond à ce motif, par exemple "
            "'*.py' ou '*.{ts,tsx}'. Plusieurs motifs peuvent être séparés par des virgules ou "
            "des espaces."
        ),
        "type": (
            "Ne chercher que les fichiers d'un langage, par exemple 'py', 'js', 'ts', 'rust', "
            "'go', 'java', 'json', 'yaml', 'markdown', 'sh'. Un nom inconnu est refusé avec la "
            "liste des valeurs acceptées."
        ),
        "output_mode": (
            "'files_with_matches' (par défaut) ne renvoie que les chemins, 'content' les lignes "
            "trouvées, 'count' le nombre de lignes trouvées par fichier."
        ),
        "case_insensitive": "Ignorer la casse. false par défaut.",
        "multiline": (
            "Autoriser un motif sur plusieurs lignes ('.' correspond aussi à un saut de ligne, "
            "pratique pour des structures comme 'struct \\{[\\s\\S]*?field'). false par défaut."
        ),
        "line_numbers": (
            "En mode 'content', préfixer chaque ligne par son numéro (à partir de 1). true par "
            "défaut ; les autres modes rapportent toujours par fichier."
        ),
        "context": (
            "En mode 'content', nombre de lignes affichées avant et après chaque correspondance. "
            "Prioritaire sur 'before_context'/'after_context'."
        ),
        "before_context": "En mode 'content', nombre de lignes affichées avant chaque correspondance.",
        "after_context": "En mode 'content', nombre de lignes affichées après chaque correspondance.",
        "head_limit": (
            "Nombre maximal de lignes de sortie (content), de chemins (files_with_matches) ou de "
            "compteurs (count). 250 par défaut ; 0 signifie sans limite."
        ),
        "offset": "Nombre de résultats à sauter, pour passer à la page suivante.",
    },
)

DE = ToolText(
    description=(
        "Sucht im Dateiinhalt mit einem regulären Ausdruck (Python-Syntax 're', standardmäßig "
        "Zeile für Zeile). Die Form des Ergebnisses hängt von 'output_mode' ab: "
        "'files_with_matches' (Standard) listet passende Dateien, zuletzt geänderte zuerst; "
        "'content' liefert Trefferzeilen als 'path:line:text', Kontextzeilen als "
        "'path-line-text', nicht benachbarte Gruppen durch '--' getrennt; 'count' liefert "
        "Trefferzeilen je Datei plus Gesamtzahl. Standardmäßig wird Zeile für Zeile verglichen; "
        "mit 'multiline' darf das Muster über Zeilen laufen. Versteckte Dateien werden ebenfalls "
        "durchsucht, aber Metadaten der Versionsverwaltung (.git usw.), installierte "
        "Abhängigkeiten und Build-Artefakte (node_modules, .venv, dist, build, target…), "
        "Binärdateien, Dateien über 8 MB und Dateien, die wie Zugangsdaten aussehen, werden "
        "übersprungen — letztere erscheinen in 'skipped_sensitive', weil read_file sie weiterhin "
        "lesen kann; zeigt 'path' ausdrücklich auf einen übersprungenen Ordner, wird er normal "
        "durchsucht. Die Ignore-Regeln des Werkzeugs lesen kein .gitignore, von Git ignorierte "
        "Dateien werden also mit durchsucht. 'glob' und 'type' schränken die durchsuchten Dateien "
        "ein. Ein Aufruf liefert höchstens 250 Ausgabezeilen bzw. Pfade; blättere mit "
        "'offset'/'head_limit' ('head_limit' 0 bedeutet unbegrenzt), statt das Muster zu "
        "verwässern; überlange Zeilen werden bei 500 Zeichen abgeschnitten. Die zurückgegebenen "
        "Pfade sind relativ zur Wurzel des Arbeitsbereichs und können an read_file gehen. Um eine "
        "Datei über ihren Namen zu finden, glob verwenden; um eine Codestelle zu finden, grep."
    ),
    parameters={
        "pattern": (
            "Der reguläre Ausdruck (Python-Syntax 're'). Sonderzeichen müssen maskiert werden, "
            "z. B. 'interface\\{\\}' für 'interface{}'."
        ),
        "path": (
            "Zu durchsuchende Datei oder Ordner, relativ zur Wurzel des Arbeitsbereichs (absolute "
            "Pfade werden nur akzeptiert, solange sie im Arbeitsbereich liegen). Ohne Angabe die "
            "Wurzel des Arbeitsbereichs."
        ),
        "glob": (
            "Nur Dateien durchsuchen, deren Name auf dieses Muster passt, z. B. '*.py' oder "
            "'*.{ts,tsx}'. Mehrere Muster durch Komma oder Leerzeichen trennen."
        ),
        "type": (
            "Nur Dateien einer Sprache durchsuchen, z. B. 'py', 'js', 'ts', 'rust', 'go', 'java', "
            "'json', 'yaml', 'markdown', 'sh'. Ein unbekannter Name wird mit der Liste der "
            "unterstützten Werte abgelehnt."
        ),
        "output_mode": (
            "'files_with_matches' (Standard) zeigt nur Pfade, 'content' die Trefferzeilen, "
            "'count' die Anzahl Trefferzeilen je Datei."
        ),
        "case_insensitive": "Beim Vergleichen Groß-/Kleinschreibung ignorieren. Standard false.",
        "multiline": (
            "Muster über Zeilen erlauben ('.' trifft dann auch Zeilenumbrüche, praktisch für "
            "Strukturen wie 'struct \\{[\\s\\S]*?field'). Standard false."
        ),
        "line_numbers": (
            "Im Modus 'content' jede Zeile mit ihrer 1-basierten Zeilennummer versehen. Standard "
            "true; andere Modi melden immer je Datei."
        ),
        "context": (
            "Im Modus 'content' Zeilen vor und nach jedem Treffer. Hat Vorrang vor "
            "'before_context'/'after_context'."
        ),
        "before_context": "Im Modus 'content' Zeilen vor jedem Treffer.",
        "after_context": "Im Modus 'content' Zeilen nach jedem Treffer.",
        "head_limit": (
            "Höchstzahl der Ausgabezeilen (content), Pfade (files_with_matches) oder Zähler "
            "(count). Standard 250; 0 bedeutet unbegrenzt."
        ),
        "offset": "So viele Ergebnisse überspringen, um auf die nächste Seite zu blättern.",
    },
)

RU = ToolText(
    description=(
        "Ищет в содержимом файлов по регулярному выражению (синтаксис 're' Python, по умолчанию "
        "построчно). Форма результата зависит от 'output_mode': 'files_with_matches' (по "
        "умолчанию) перечисляет подходящие файлы, сначала более свежие; 'content' возвращает "
        "найденные строки как 'path:line:text', строки контекста как 'path-line-text', несмежные "
        "группы разделяются '--'; 'count' возвращает число найденных строк по каждому файлу и "
        "общее. По умолчанию сравнение построчное; с 'multiline' шаблон может пересекать "
        "строки. Скрытые файлы тоже ищутся, но метаданные системы контроля версий (.git и т. п.), "
        "установленные зависимости и артефакты сборки (node_modules, .venv, dist, build, "
        "target…), двоичные файлы, файлы больше 8 МБ и файлы, похожие на учётные данные, "
        "пропускаются — последние перечисляются в 'skipped_sensitive', так как read_file всё ещё "
        "может их прочитать; если указать 'path' прямо на пропущенную папку, она будет "
        "просканирована обычным образом. Правила исключения инструмента не читают .gitignore, "
        "поэтому игнорируемые Git файлы тоже участвуют в поиске. 'glob' и 'type' сужают набор "
        "файлов. За один вызов возвращается не больше 250 строк вывода или путей; для листания "
        "используйте 'offset'/'head_limit' ('head_limit' = 0 — без ограничения), а не расширяйте "
        "шаблон наугад; слишком длинные строки обрезаются на 500 символах. Возвращённые пути "
        "относительны корня рабочей области и подходят для read_file. Чтобы найти файл по имени, "
        "используйте glob; чтобы найти место в коде — grep."
    ),
    parameters={
        "pattern": (
            "Регулярное выражение (синтаксис 're' Python). Спецсимволы нужно экранировать, "
            "например для 'interface{}' пишите 'interface\\{\\}'."
        ),
        "path": (
            "Файл или папка для поиска относительно корня рабочей области (абсолютный путь "
            "принимается, только если он остаётся внутри рабочей области). Если не указан, "
            "берётся корень рабочей области."
        ),
        "glob": (
            "Искать только в файлах, имя которых подходит под шаблон, например '*.py' или "
            "'*.{ts,tsx}'. Несколько шаблонов разделяйте запятыми или пробелами."
        ),
        "type": (
            "Искать только файлы определённого языка, например 'py', 'js', 'ts', 'rust', 'go', "
            "'java', 'json', 'yaml', 'markdown', 'sh'. Неизвестное имя отклоняется со списком "
            "поддерживаемых."
        ),
        "output_mode": (
            "'files_with_matches' (по умолчанию) — только пути, 'content' — найденные строки, "
            "'count' — число найденных строк по каждому файлу."
        ),
        "case_insensitive": "Игнорировать регистр при сравнении. По умолчанию false.",
        "multiline": (
            "Разрешить многострочный шаблон ('.' совпадает и с переводом строки; удобно для "
            "конструкций вида 'struct \\{[\\s\\S]*?field'). По умолчанию false."
        ),
        "line_numbers": (
            "В режиме 'content' добавлять к каждой строке её номер (с 1). По умолчанию true; "
            "остальные режимы всегда отчитываются по файлам."
        ),
        "context": (
            "В режиме 'content' сколько строк показывать до и после каждого совпадения. "
            "Приоритетнее 'before_context'/'after_context'."
        ),
        "before_context": "В режиме 'content' сколько строк показывать до совпадения.",
        "after_context": "В режиме 'content' сколько строк показывать после совпадения.",
        "head_limit": (
            "Сколько строк вывода (content), путей (files_with_matches) или счётчиков (count) "
            "вернуть максимум. По умолчанию 250; 0 — без ограничения."
        ),
        "offset": "Сколько результатов пропустить, чтобы перейти к следующей странице.",
    },
)
