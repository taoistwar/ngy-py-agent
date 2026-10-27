"""Chinese display text for ``write_file``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "创建文本文件，或替换它的全部内容。路径以工作空间根目录为基准解析且不能越出；"
        "全局允许/拒绝策略叠加生效。写入的是整个文件 —— 不做追加，原内容会消失。覆盖已有文件"
        "的前提是本次任务里 read_file 已完整读过该文件（第 1 行、不带 'limit'）且文件之后没有"
        "变化，否则调用会被拒绝，因此没见过的文件永远不会被毁掉。父目录必须已存在。内容按 "
        "'encoding'（必填）编码；字节序标记与现有换行符会保留，新文件使用 LF 换行和 0644 "
        "权限。写入是原子的。要改文件的一部分请用 edit_file；要追加，把 edit_file 的锚点放在"
        "文件最后一行。"
    ),
    parameters={
        "file_path": "文件路径，相对于工作空间根目录。",
        "content": "文件的新完整内容，会替换原有内容；空字符串表示清空文件。",
        "encoding": (
            "编码内容所用的文本编码（必填）。除非文件需要其它编码，否则用 UTF-8。"
            "字节序标记优先于此值。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "建立文字檔，或取代它的全部內容。路徑以工作區根目錄為基準解析且不能越出；"
        "全域允許／拒絕策略疊加生效。寫入的是整個檔案 —— 不做附加，原內容會消失。覆寫既有檔案"
        "的前提是本次任務裡 read_file 已完整讀過該檔案（第 1 行、不帶 'limit'）且檔案之後沒有"
        "變化，否則呼叫會被拒絕，因此沒見過的檔案永遠不會被毀掉。父目錄必須已存在。內容依 "
        "'encoding'（必填）編碼；位元組順序標記與既有換行字元會保留，新檔案使用 LF 換行與 0644 "
        "權限。寫入是原子的。要改檔案的一部分請用 edit_file；要附加內容，把 edit_file 的錨點"
        "放在檔案最後一行。"
    ),
    parameters={
        "file_path": "檔案路徑，相對於工作區根目錄。",
        "content": "檔案的新完整內容，會取代原有內容；空字串表示清空檔案。",
        "encoding": (
            "編碼內容所用的文字編碼（必填）。除非檔案需要其它編碼，否則用 UTF-8。"
            "位元組順序標記優先於此值。"
        ),
    },
)

FR = ToolText(
    description=(
        "Crée un fichier texte ou remplace tout son contenu. Les chemins sont résolus par "
        "rapport à la racine de l'espace de travail et ne peuvent pas en sortir ; la politique "
        "globale d'autorisation et de refus s'applique en plus. C'est le fichier entier qui est "
        "écrit — aucun ajout, le contenu d'origine disparaît. Remplacer un fichier existant "
        "suppose que read_file l'a lu en entier pendant cette tâche (depuis la ligne 1, sans "
        "'limit') et qu'il n'a pas changé depuis ; sinon l'appel est refusé, donc un fichier "
        "jamais vu ne peut pas être détruit. Le dossier parent doit déjà exister. Le contenu est "
        "encodé selon 'encoding' (obligatoire) ; une marque d'ordre des octets et les fins de "
        "ligne existantes sont préservées, un nouveau fichier utilise des fins de ligne LF et les "
        "droits 0644. L'écriture est atomique. Pour modifier une partie d'un fichier, utilisez "
        "edit_file ; pour ajouter, placez l'ancre d'edit_file sur la dernière ligne du fichier."
    ),
    parameters={
        "file_path": "Chemin du fichier, relatif à la racine de l'espace de travail.",
        "content": (
            "Nouveau contenu complet du fichier, qui remplace l'ancien ; une chaîne vide vide le "
            "fichier."
        ),
        "encoding": (
            "Encodage utilisé pour écrire le contenu (obligatoire). Utilisez UTF-8 sauf si le "
            "fichier exige un autre encodage. Une marque d'ordre des octets l'emporte sur cette "
            "valeur."
        ),
    },
)

DE = ToolText(
    description=(
        "Erstellt eine Textdatei oder ersetzt ihren gesamten Inhalt. Pfade werden gegen die "
        "Wurzel des Arbeitsbereichs aufgelöst und können sie nicht verlassen; die globale "
        "Erlauben-/Ablehnen-Richtlinie gilt zusätzlich. Geschrieben wird die ganze Datei — kein "
        "Anhängen, der alte Inhalt verschwindet. Eine vorhandene Datei zu überschreiben setzt "
        "voraus, dass read_file sie in dieser Aufgabe vollständig gelesen hat (ab Zeile 1, ohne "
        "'limit') und sie sich seither nicht geändert hat; sonst wird der Aufruf abgelehnt, eine "
        "nie gesehene Datei kann also nicht zerstört werden. Das Elternverzeichnis muss bereits "
        "existieren. Der Inhalt wird nach 'encoding' (erforderlich) kodiert; ein Byte Order Mark "
        "und vorhandene Zeilenenden bleiben erhalten, eine neue Datei bekommt LF-Zeilenenden und "
        "Rechte 0644. Das Schreiben ist atomar. Um einen Teil einer Datei zu ändern, edit_file "
        "verwenden; zum Anhängen den Anker von edit_file auf die letzte Zeile setzen."
    ),
    parameters={
        "file_path": "Dateipfad relativ zur Wurzel des Arbeitsbereichs.",
        "content": (
            "Der neue vollständige Inhalt der Datei, der den alten ersetzt; eine leere "
            "Zeichenkette leert die Datei."
        ),
        "encoding": (
            "Kodierung, in der der Inhalt geschrieben wird (erforderlich). UTF-8 verwenden, außer "
            "die Datei verlangt eine andere Kodierung. Ein Byte Order Mark hat Vorrang vor diesem "
            "Wert."
        ),
    },
)

RU = ToolText(
    description=(
        "Создаёт текстовый файл или заменяет всё его содержимое. Пути разрешаются "
        "относительно корня рабочей области и не могут выйти за его пределы; глобальная "
        "политика разрешений и запретов действует дополнительно. Записывается файл целиком — "
        "без дописывания, прежнее содержимое исчезает. Перезапись существующего файла возможна, "
        "только если read_file прочитал его в этой задаче полностью (с первой строки, без "
        "'limit') и файл с тех пор не изменился; иначе вызов отклоняется, поэтому файл, который "
        "вы не видели, нельзя уничтожить. Родительская папка должна уже существовать. "
        "Содержимое кодируется согласно 'encoding' (обязательно); метка порядка байтов и "
        "существующие переводы строк сохраняются, новый файл получает переводы строк LF и права "
        "0644. Запись атомарна. Чтобы изменить часть файла, используйте edit_file; чтобы "
        "дописать, поставьте якорь edit_file на последнюю строку файла."
    ),
    parameters={
        "file_path": "Путь к файлу относительно корня рабочей области.",
        "content": (
            "Новое полное содержимое файла, заменяющее прежнее; пустая строка очищает файл."
        ),
        "encoding": (
            "Кодировка для записи содержимого (обязательно). Используйте UTF-8, если файл не "
            "требует другой кодировки. Метка порядка байтов имеет приоритет над этим значением."
        ),
    },
)
