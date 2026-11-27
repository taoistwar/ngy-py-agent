"""Chinese display text for ``glob``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "按文件名模式递归查找文件。一次调用就会遍历 'path' 之下的整棵目录树：单独的 '*' 已经"
        "返回任意深度的全部文件，'**/*' 与它等价，所以一次调用只问一个问题——不要同时发出 "
        "'*' 和 '**/*'，也不要用同一模式的变体重复调用。'path' 是起点而不是深度限制；只有写了"
        "层级的模式（例如 'src/*'）才会只查那一层。它的用途是回答目录里有哪些文件、在只知道"
        "文件名不知道所在目录时定位文件，以及在 read_file 之前用它，胜过猜一个路径。只返回普通"
        "文件、不返回目录，因此 'filenames' 为空表示没有匹配的文件，而不是目录不存在。最多返回 "
        "100 个路径：项目源码在前，已安装依赖与构建产物排在最后，两组内部各自按修改时间从新到"
        "旧；'truncated' 为真表示列表不完整，此时应缩小 'path' 或把 'pattern' 写得更具体，而"
        "不是翻页。模式语义与 ripgrep 的 --glob 一致：'*' 只匹配单个路径段内的字符，'**' 可跨"
        "路径段（'a/**/b' 也匹配 'a/b'），'?' 匹配一个字符，'[abc]' 是字符集，'{a,b}' 是候选"
        "列表；不含 '/' 的模式只比对文件名，任意深度都算。隐藏文件与被 .gitignore 排除的文件"
        "同样会被列出。路径以工作空间根为基准解析且不能越出；全局允许/拒绝策略依然会隐藏它拦截"
        "的内容。返回的路径相对于工作空间根（在工作空间之外时为绝对路径），可直接原样传给 "
        "read_file。绝对路径的 'pattern' 自带搜索根，会覆盖 'path'。"
    ),
    parameters={
        "pattern": (
            "要找的文件名的 glob 模式：'*' 表示任意深度的全部文件，'*.py' 表示全部 Python "
            "文件，'src/*.py' 表示只查 'src/' 下面一层。'**'、'*'、'?'、'[...]' 和 '{a,b}' "
            "按上文说明生效；不含 '/' 的模式只比对文件名，任意深度都算。"
        ),
        "path": (
            "搜索起点目录，相对于工作空间根（绝对路径只有在仍位于工作空间内时才被接受）。"
            "省略时使用工作空间根。它之下的搜索是递归的，要只查一层就把模式写成 'src/*' 这样。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "依檔名樣式遞迴尋找檔案。一次呼叫就會走訪 'path' 之下的整棵目錄樹：單獨的 '*' 已經"
        "傳回任意深度的全部檔案，'**/*' 與它等價，所以一次呼叫只問一個問題——不要同時送出 "
        "'*' 和 '**/*'，也不要用同一樣式的變體重複呼叫。'path' 是起點而不是深度限制；只有寫了"
        "層級的樣式（例如 'src/*'）才會只查那一層。它的用途是回答目錄裡有哪些檔案、在只知道"
        "檔名不知道所在目錄時定位檔案，以及在 read_file 之前用它，勝過猜一個路徑。只傳回一般"
        "檔案、不傳回目錄，因此 'filenames' 為空表示沒有相符的檔案，而不是目錄不存在。最多傳回 "
        "100 個路徑：專案原始碼在前，已安裝依賴與建置產物排在最後，兩組內部各自依修改時間從新"
        "到舊；'truncated' 為真表示清單不完整，此時應縮小 'path' 或把 'pattern' 寫得更具體，"
        "而不是翻頁。樣式語意與 ripgrep 的 --glob 一致：'*' 只相符單一路徑段內的字元，'**' 可"
        "跨路徑段（'a/**/b' 也相符 'a/b'），'?' 相符一個字元，'[abc]' 是字元集，'{a,b}' 是"
        "候選清單；不含 '/' 的樣式只比對檔名，任意深度都算。隱藏檔案與被 .gitignore 排除的檔案"
        "同樣會被列出。路徑以工作區根為基準解析且不能越出；全域允許／拒絕策略依然會隱藏它攔截"
        "的內容。傳回的路徑相對於工作區根（在工作區之外時為絕對路徑），可直接原樣傳給 "
        "read_file。絕對路徑的 'pattern' 自帶搜尋根，會覆蓋 'path'。"
    ),
    parameters={
        "pattern": (
            "要找的檔名的 glob 樣式：'*' 表示任意深度的全部檔案，'*.py' 表示全部 Python "
            "檔案，'src/*.py' 表示只查 'src/' 下面一層。'**'、'*'、'?'、'[...]' 和 '{a,b}' "
            "依上文說明生效；不含 '/' 的樣式只比對檔名，任意深度都算。"
        ),
        "path": (
            "搜尋起點目錄，相對於工作區根（絕對路徑只有在仍位於工作區內時才被接受）。"
            "省略時使用工作區根。它之下的搜尋是遞迴的，要只查一層就把樣式寫成 'src/*' 這樣。"
        ),
    },
)

FR = ToolText(
    description=(
        "Liste des fichiers par motif de nom, récursivement. Un appel parcourt tout le "
        "sous-arbre sous 'path' : un simple '*' renvoie déjà tous les fichiers à n'importe "
        "quelle profondeur et '**/*' est la même requête ; posez donc une seule question par "
        "appel, n'envoyez jamais '*' et '**/*' ensemble et ne répétez pas un appel avec une "
        "variante du même motif. 'path' est un point de départ, pas une limite de profondeur ; "
        "seul un motif qui nomme un niveau ('src/*') s'arrête à ce niveau. À utiliser pour "
        "répondre à la question des fichiers présents, pour retrouver un fichier dont vous "
        "connaissez le nom mais pas le dossier, et avant read_file plutôt que de deviner un "
        "chemin. Seuls des fichiers ordinaires sont renvoyés, jamais des dossiers : un "
        "'filenames' vide signifie donc qu'aucun fichier ne correspond, pas que le dossier "
        "manque. 100 chemins au maximum : le code du projet d'abord, les dépendances installées "
        "et les artefacts de build en dernier, chaque groupe du plus récemment modifié au plus "
        "ancien ; 'truncated' vrai signifie que la liste est incomplète : réduisez alors 'path' "
        "ou rendez 'pattern' plus précis plutôt que de paginer. La sémantique des motifs est "
        "celle de --glob de ripgrep : '*' ne correspond qu'à des caractères d'un seul segment "
        "de chemin, '**' peut traverser les segments ('a/**/b' correspond aussi à 'a/b'), '?' "
        "correspond à un caractère, '[abc]' est un ensemble de caractères et '{a,b}' une liste "
        "d'alternatives ; un motif sans '/' compare le nom du fichier à n'importe quelle "
        "profondeur. Les fichiers cachés et ceux exclus par .gitignore sont listés à dessein. "
        "Les chemins sont résolus depuis la racine de l'espace de travail et ne peuvent pas en "
        "sortir ; la politique globale d'autorisation et de refus continue de masquer ce "
        "qu'elle bloque. Les chemins renvoyés sont relatifs à la racine de l'espace de travail "
        "(absolus en dehors) et peuvent être passés tels quels à read_file. Un 'pattern' "
        "absolu porte sa propre racine de recherche et l'emporte sur 'path'."
    ),
    parameters={
        "pattern": (
            "Motif glob des noms de fichiers recherchés : '*' pour tous les fichiers à toute "
            "profondeur, '*.py' pour tous les fichiers Python, 'src/*.py' pour rester un niveau "
            "sous 'src/'. '**', '*', '?', '[...]' et '{a,b}' fonctionnent comme décrit plus "
            "haut, et un motif sans '/' est comparé au nom du fichier à n'importe quelle "
            "profondeur."
        ),
        "path": (
            "Dossier de départ, relatif à la racine de l'espace de travail (un chemin absolu "
            "n'est accepté que s'il reste dans l'espace de travail). Omis, la racine de "
            "l'espace de travail est utilisée. La recherche en dessous est récursive : un "
            "motif comme 'src/*' est la façon de la limiter à un niveau."
        ),
    },
)

DE = ToolText(
    description=(
        "Dateien rekursiv über ein Namensmuster auflisten. Ein Aufruf durchsucht den gesamten "
        "Teilbaum unter 'path': Ein einfaches '*' liefert bereits jede Datei auf jeder Ebene, "
        "und '**/*' ist dieselbe Abfrage — stellen Sie also eine Frage pro Aufruf, senden Sie "
        "niemals '*' und '**/*' zusammen und wiederholen Sie einen Aufruf nicht mit einer "
        "Variante desselben Musters. 'path' ist ein Ausgangspunkt, keine Tiefenbegrenzung; nur "
        "ein Muster, das eine Ebene nennt ('src/*'), endet auf dieser Ebene. Verwenden, um die "
        "Frage nach den vorhandenen Dateien zu beantworten, um eine Datei zu finden, deren Name "
        "bekannt ist, deren Ordner aber nicht, und vor read_file, statt einen Pfad zu raten. "
        "Zurückgegeben werden nur reguläre Dateien, keine Ordner; ein leeres 'filenames' heißt "
        "also, dass keine Datei passt, nicht dass der Ordner fehlt. Höchstens 100 Pfade: "
        "Projektquellcode zuerst, installierte Abhängigkeiten und Build-Artefakte zuletzt, "
        "innerhalb jeder Gruppe zuletzt geänderte zuerst; 'truncated' wahr heißt, die Liste ist "
        "unvollständig — dann 'path' verkleinern oder 'pattern' genauer fassen statt zu "
        "blättern. Die Mustersemantik entspricht --glob von ripgrep: '*' trifft nur Zeichen "
        "innerhalb eines Pfadsegments, '**' darf Segmente überschreiten ('a/**/b' trifft auch "
        "'a/b'), '?' trifft ein Zeichen, '[abc]' ist eine Zeichenmenge und '{a,b}' eine "
        "Alternativenliste; ein Muster ohne '/' vergleicht den Dateinamen auf jeder Ebene. "
        "Versteckte Dateien und von .gitignore ausgeschlossene Dateien werden bewusst gelistet. "
        "Pfade werden gegen die Wurzel des Arbeitsbereichs aufgelöst und können sie nicht "
        "verlassen; die globale Erlauben-/Ablehnen-Richtlinie verbirgt weiterhin, was sie "
        "blockiert. Die zurückgegebenen Pfade sind relativ zur Wurzel des Arbeitsbereichs "
        "(außerhalb davon absolut) und können unverändert an read_file gehen. Ein absolutes "
        "'pattern' bringt seine eigene Suchwurzel mit und hat Vorrang vor 'path'."
    ),
    parameters={
        "pattern": (
            "Glob-Muster für die gesuchten Dateinamen: '*' für jede Datei auf jeder Ebene, "
            "'*.py' für jede Python-Datei, 'src/*.py' um eine Ebene unter 'src/' zu bleiben. "
            "'**', '*', '?', '[...]' und '{a,b}' wirken wie oben beschrieben, und ein Muster "
            "ohne '/' wird auf jeder Ebene mit dem Dateinamen verglichen."
        ),
        "path": (
            "Startordner, relativ zur Wurzel des Arbeitsbereichs (absolute Pfade werden nur "
            "akzeptiert, solange sie im Arbeitsbereich liegen). Ohne Angabe wird die Wurzel "
            "des Arbeitsbereichs verwendet. Die Suche darunter ist rekursiv; ein Muster wie "
            "'src/*' begrenzt sie auf eine Ebene."
        ),
    },
)

RU = ToolText(
    description=(
        "Рекурсивный поиск файлов по шаблону имени. Один вызов обходит всё поддерево под "
        "'path': простой '*' уже возвращает все файлы на любой глубине, а '**/*' — тот же "
        "самый запрос, поэтому задавайте один вопрос на вызов: никогда не отправляйте '*' и "
        "'**/*' вместе и не повторяйте вызов с вариацией того же шаблона. 'path' — это точка "
        "старта, а не ограничение глубины; на одном уровне останавливается только шаблон, "
        "называющий уровень ('src/*'). Используйте, чтобы ответить, какие файлы здесь есть, "
        "найти файл, чьё имя известно, а папка — нет, и перед read_file вместо угадывания "
        "пути. Возвращаются только обычные файлы, без папок, поэтому пустой 'filenames' "
        "означает, что подходящих файлов нет, а не что папки не существует. Не больше 100 "
        "путей: сначала исходники проекта, установленные зависимости и артефакты сборки в "
        "конце, внутри каждой группы — более свежие по времени изменения; 'truncated' = true "
        "означает, что список неполный: сузьте 'path' или сделайте 'pattern' конкретнее, а не "
        "листайте дальше. Семантика шаблонов совпадает с --glob в ripgrep: '*' соответствует "
        "символам в пределах одного сегмента пути, '**' может пересекать сегменты ('a/**/b' "
        "соответствует и 'a/b'), '?' — один символ, '[abc]' — набор символов, '{a,b}' — "
        "список альтернатив; шаблон без '/' сравнивается только с именем файла на любой "
        "глубине. Скрытые файлы и файлы, исключённые через .gitignore, попадают в список "
        "намеренно. Пути разрешаются от корня рабочей области и не могут выйти за его "
        "пределы; глобальная политика разрешений и запретов по-прежнему скрывает то, что "
        "блокирует. Возвращённые пути относительны корня рабочей области (вне её — "
        "абсолютные) и подходят для read_file без изменений. Абсолютный 'pattern' несёт "
        "собственный корень поиска и перекрывает 'path'."
    ),
    parameters={
        "pattern": (
            "Glob-шаблон имён искомых файлов: '*' для всех файлов на любой глубине, '*.py' "
            "для всех файлов Python, 'src/*.py' чтобы остаться на один уровень ниже 'src/'. "
            "'**', '*', '?', '[...]' и '{a,b}' работают как описано выше, а шаблон без '/' "
            "сравнивается с именем файла на любой глубине."
        ),
        "path": (
            "Начальная папка поиска относительно корня рабочей области (абсолютный путь "
            "принимается, только если он остаётся внутри рабочей области). Если не указан, "
            "берётся корень рабочей области. Поиск ниже неё рекурсивный; шаблон вида "
            "'src/*' ограничивает его одним уровнем."
        ),
    },
)
