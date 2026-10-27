"""Chinese display text for ``glob``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "按文件名模式查找文件。当你知道文件叫什么、但不知道它在哪个目录时用它；在"
        "read_file 之前用它，胜过猜一个路径。返回匹配的文件路径，最多 100 个：项目源码在前，"
        "已安装依赖与构建产物排在最后，两组内部各自按修改时间从新到旧；'truncated' 为真表示"
        "列表不完整，此时应缩小 'path' 或把 'pattern' "
        "写得更具体，而不是翻页。模式语义与 ripgrep 的 --glob 一致：'*' 只匹配单个路径段内"
        "的字符，'**' 可跨路径段（'a/**/b' 也匹配 'a/b'），'?' 匹配一个字符，'[abc]' 是"
        "字符集，'{a,b}' 是候选列表。不含 '/' 的模式只匹配文件名，因此任意深度都算，所以 "
        "'*.py' 能找出搜索根之下的全部 Python 文件。隐藏文件与被 .gitignore 排除的文件"
        "同样会被列出，只返回普通文件、不返回目录。路径以工作空间根为基准解析且不能越出；"
        "全局允许/拒绝策略依然会隐藏它拦截的内容。返回的路径相对于工作空间根（在工作空间"
        "之外时为绝对路径），可直接原样传给 read_file。绝对路径的 'pattern' 自带搜索根，"
        "会覆盖 'path'。"
    ),
    parameters={
        "pattern": (
            "描述要找的文件名的 glob 模式，例如 '**/*.ts' 或 'src/**/test_*.py'。"
            "支持上文说明的 '**'、'*'、'?'、'[...]' 和 '{a,b}'。"
        ),
        "path": (
            "搜索目录，相对于工作空间根（绝对路径只有在仍位于工作空间内时才被接受）。"
            "省略时使用工作空间根。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "依檔名樣式尋找檔案。當你知道檔案叫什麼、但不知道它在哪個目錄時用它；在 read_file "
        "之前用它，勝過猜一個路徑。傳回相符的檔案路徑，最多 100 個：專案原始碼在前，已安裝"
        "依賴與建置產物排在最後，兩組內部各自依修改時間從新到舊；"
        "'truncated' 為真表示清單不完整，此時應縮小 'path' 或把 'pattern' 寫得更具體，而不是"
        "翻頁。樣式語意與 ripgrep 的 --glob 一致：'*' 只相符單一路徑段內的字元，'**' 可跨路徑"
        "段（'a/**/b' 也相符 'a/b'），'?' 相符一個字元，'[abc]' 是字元集，'{a,b}' 是候選清單。"
        "不含 '/' 的樣式只比對檔名，因此任意深度都算，所以 '*.py' 能找出搜尋根之下的全部 "
        "Python 檔案。隱藏檔案與被 .gitignore 排除的檔案同樣會被列出，只傳回一般檔案、不傳回"
        "目錄。路徑以工作區根為基準解析且不能越出；全域允許／拒絕策略依然會隱藏它攔截的內容。"
        "傳回的路徑相對於工作區根（在工作區之外時為絕對路徑），可直接原樣傳給 read_file。"
        "絕對路徑的 'pattern' 自帶搜尋根，會覆蓋 'path'。"
    ),
    parameters={
        "pattern": (
            "描述要找的檔名的 glob 樣式，例如 '**/*.ts' 或 'src/**/test_*.py'。"
            "支援上文說明的 '**'、'*'、'?'、'[...]' 和 '{a,b}'。"
        ),
        "path": (
            "搜尋目錄，相對於工作區根（絕對路徑只有在仍位於工作區內時才被接受）。"
            "省略時使用工作區根。"
        ),
    },
)

FR = ToolText(
    description=(
        "Trouve des fichiers par motif de nom. À utiliser quand vous connaissez le nom du fichier "
        "mais pas son dossier ; avant read_file, c'est mieux que deviner un chemin. Renvoie les "
        "chemins correspondants, 100 au maximum : le code du projet d'abord, les dépendances "
        "installées et les artefacts de build en dernier, chaque groupe du plus récemment "
        "modifié au plus ancien ; "
        "'truncated' vrai signifie que la liste est incomplète : réduisez alors 'path' ou rendez "
        "'pattern' plus précis plutôt que de paginer. La sémantique des motifs est celle de "
        "--glob de ripgrep : '*' ne correspond qu'à des caractères d'un seul segment de chemin, "
        "'**' peut traverser les segments ('a/**/b' correspond aussi à 'a/b'), '?' correspond à un "
        "caractère, '[abc]' est un ensemble de caractères et '{a,b}' une liste d'alternatives. Un "
        "motif sans '/' ne compare que le nom du fichier, à n'importe quelle profondeur : '*.py' "
        "trouve donc tous les fichiers Python sous la racine de recherche. Les fichiers cachés et "
        "ceux exclus par .gitignore sont listés aussi ; seuls les fichiers ordinaires sont "
        "renvoyés, pas les dossiers. Les chemins sont résolus depuis la racine de l'espace de "
        "travail et ne peuvent pas en sortir ; la politique globale d'autorisation et de refus "
        "continue de masquer ce qu'elle bloque. Les chemins renvoyés sont relatifs à la racine de "
        "l'espace de travail (absolus en dehors) et peuvent être passés tels quels à read_file. Un "
        "'pattern' absolu porte sa propre racine de recherche et l'emporte sur 'path'."
    ),
    parameters={
        "pattern": (
            "Motif glob décrivant les noms de fichiers recherchés, par exemple '**/*.ts' ou "
            "'src/**/test_*.py'. '**', '*', '?', '[...]' et '{a,b}' sont pris en charge comme "
            "décrit plus haut."
        ),
        "path": (
            "Dossier de recherche, relatif à la racine de l'espace de travail (un chemin absolu "
            "n'est accepté que s'il reste dans l'espace de travail). Omis, la racine de l'espace "
            "de travail est utilisée."
        ),
    },
)

DE = ToolText(
    description=(
        "Findet Dateien über ein Namensmuster. Verwenden, wenn der Dateiname bekannt ist, der "
        "Ordner aber nicht; vor read_file ist das besser, als einen Pfad zu raten. Gibt passende "
        "Dateipfade zurück, höchstens 100: Projektquellcode zuerst, installierte Abhängigkeiten "
        "und Build-Artefakte zuletzt, innerhalb jeder Gruppe zuletzt geänderte zuerst; "
        "'truncated' wahr heißt, die "
        "Liste ist unvollständig — dann 'path' verkleinern oder 'pattern' genauer fassen statt zu "
        "blättern. Die Mustersemantik entspricht --glob von ripgrep: '*' trifft nur Zeichen "
        "innerhalb eines Pfadsegments, '**' darf Segmente überschreiten ('a/**/b' trifft auch "
        "'a/b'), '?' trifft ein Zeichen, '[abc]' ist eine Zeichenmenge und '{a,b}' eine "
        "Alternativenliste. Ein Muster ohne '/' vergleicht nur den Dateinamen, also auf jeder "
        "Ebene: '*.py' findet alle Python-Dateien unter der Suchwurzel. Versteckte Dateien und von "
        ".gitignore ausgeschlossene Dateien werden ebenfalls gelistet; zurückgegeben werden nur "
        "reguläre Dateien, keine Ordner. Pfade werden gegen die Wurzel des Arbeitsbereichs "
        "aufgelöst und können sie nicht verlassen; die globale Erlauben-/Ablehnen-Richtlinie "
        "verbirgt weiterhin, was sie blockiert. Die zurückgegebenen Pfade sind relativ zur Wurzel "
        "des Arbeitsbereichs (außerhalb davon absolut) und können unverändert an read_file gehen. "
        "Ein absolutes 'pattern' bringt seine eigene Suchwurzel mit und hat Vorrang vor 'path'."
    ),
    parameters={
        "pattern": (
            "Glob-Muster für die gesuchten Dateinamen, z. B. '**/*.ts' oder 'src/**/test_*.py'. "
            "'**', '*', '?', '[...]' und '{a,b}' werden wie oben beschrieben unterstützt."
        ),
        "path": (
            "Suchordner, relativ zur Wurzel des Arbeitsbereichs (absolute Pfade werden nur "
            "akzeptiert, solange sie im Arbeitsbereich liegen). Ohne Angabe wird die Wurzel des "
            "Arbeitsbereichs verwendet."
        ),
    },
)

RU = ToolText(
    description=(
        "Ищет файлы по шаблону имени. Используйте, когда имя файла известно, а папка — нет; "
        "перед read_file это лучше, чем угадывать путь. Возвращает подходящие пути, не больше "
        "100: сначала исходники проекта, установленные зависимости и артефакты сборки в конце, "
        "внутри каждой группы — более свежие по времени изменения; 'truncated' = true означает, что "
        "список неполный: сузьте 'path' или сделайте 'pattern' конкретнее, а не листайте "
        "дальше. Семантика шаблонов совпадает с --glob в ripgrep: '*' соответствует символам в "
        "пределах одного сегмента пути, '**' может пересекать сегменты ('a/**/b' соответствует "
        "и 'a/b'), '?' — один символ, '[abc]' — набор символов, '{a,b}' — список альтернатив. "
        "Шаблон без '/' сравнивается только с именем файла, то есть на любой глубине: '*.py' "
        "найдёт все файлы Python под корнем поиска. Скрытые файлы и файлы, исключённые через "
        ".gitignore, тоже попадают в список; возвращаются только обычные файлы, без папок. Пути "
        "разрешаются от корня рабочей области и не могут выйти за его пределы; глобальная "
        "политика разрешений и запретов по-прежнему скрывает то, что блокирует. Возвращённые "
        "пути относительны корня рабочей области (вне её — абсолютные) и подходят для read_file "
        "без изменений. Абсолютный 'pattern' несёт собственный корень поиска и перекрывает "
        "'path'."
    ),
    parameters={
        "pattern": (
            "Glob-шаблон имён искомых файлов, например '**/*.ts' или 'src/**/test_*.py'. "
            "Поддерживаются '**', '*', '?', '[...]' и '{a,b}', как описано выше."
        ),
        "path": (
            "Папка поиска относительно корня рабочей области (абсолютный путь принимается, "
            "только если он остаётся внутри рабочей области). Если не указан, берётся корень "
            "рабочей области."
        ),
    },
)
