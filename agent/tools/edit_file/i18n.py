"""Chinese display text for ``edit_file``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "在文本文件里替换一段完全匹配的字符串。路径以工作空间根目录为基准解析且不能越出；"
        "全局允许/拒绝策略叠加生效。'old_string' 按字节完全匹配，必须与文件中的内容一模一样"
        "（包括换行符）：把 read_file 输出中的 'N<TAB>' 前缀去掉后原样使用。匹配必须唯一 —— "
        "'old_string' 出现多次时调用会被拒绝，需要补充上下文，或传 replace_all=true 替换所有"
        "出现。解码使用 'encoding'（默认 UTF-8），文件带字节序标记时以标记为准；无法解码时会"
        "返回列出候选编码的错误，请用正确的 'encoding' 重试。插入的文本会被改写成文件现有的"
        "换行符，字节序标记会保留；只重写匹配到的范围，其余字节不会被改动。写入是原子的，"
        "文件权限会保留。"
    ),
    parameters={
        "file_path": "文件路径，相对于工作空间根目录。",
        "old_string": "要被替换的原文。除非 'replace_all' 为 true，否则必须唯一。",
        "new_string": "替换后的文本。空字符串表示删除匹配到的内容。",
        "replace_all": "替换所有出现，而不是要求唯一匹配。默认 false。",
        "encoding": (
            "解码并重新编码文件所用的文本编码。默认 UTF-8。使用 read_file 报告过的 "
            "'encoding'。字节序标记优先于此值。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "在文字檔裡替換一段完全相符的字串。路徑以工作區根目錄為基準解析且不能越出；"
        "全域允許／拒絕策略疊加生效。'old_string' 按位元組完全相符，必須與檔案中的內容一模"
        "一樣（包括換行字元）：把 read_file 輸出中的 'N<TAB>' 前綴去掉後原樣使用。相符必須"
        "唯一 —— 'old_string' 出現多次時呼叫會被拒絕，需要補充上下文，或傳 replace_all=true "
        "替換所有出現。解碼使用 'encoding'（預設 UTF-8），檔案帶位元組順序標記時以標記為準；"
        "無法解碼時會傳回列出候選編碼的錯誤，請用正確的 'encoding' 重試。插入的文字會被改寫成"
        "檔案現有的換行字元，位元組順序標記會保留；只重寫相符到的範圍，其餘位元組不會被改動。"
        "寫入是原子的，檔案權限會保留。"
    ),
    parameters={
        "file_path": "檔案路徑，相對於工作區根目錄。",
        "old_string": "要被替換的原文。除非 'replace_all' 為 true，否則必須唯一。",
        "new_string": "替換後的文字。空字串表示刪除相符到的內容。",
        "replace_all": "替換所有出現，而不是要求唯一相符。預設 false。",
        "encoding": (
            "解碼並重新編碼檔案所用的文字編碼。預設 UTF-8。使用 read_file 回報過的 "
            "'encoding'。位元組順序標記優先於此值。"
        ),
    },
)

FR = ToolText(
    description=(
        "Remplace une chaîne exactement identique dans un fichier texte. Les chemins sont "
        "résolus par rapport à la racine de l'espace de travail et ne peuvent pas en sortir ; la "
        "politique globale d'autorisation et de refus s'applique en plus. 'old_string' est "
        "comparé octet par octet et doit correspondre exactement au contenu du fichier (fins de "
        "ligne comprises) : reprenez tel quel le texte de read_file après avoir retiré le préfixe "
        "'N<TAB>'. La correspondance doit être unique — si 'old_string' apparaît plusieurs fois, "
        "l'appel est refusé : ajoutez du contexte ou passez replace_all=true pour remplacer "
        "toutes les occurrences. Le décodage utilise 'encoding' (UTF-8 par défaut), une marque "
        "d'ordre des octets l'emporte ; un fichier indécodable renvoie une erreur listant des "
        "encodages candidats : réessayez avec le bon 'encoding'. Le texte inséré est réécrit avec "
        "les fins de ligne du fichier, la marque d'ordre des octets est conservée ; seule la plage "
        "correspondante est réécrite, les autres octets restent intacts. L'écriture est atomique "
        "et les droits du fichier sont conservés."
    ),
    parameters={
        "file_path": "Chemin du fichier, relatif à la racine de l'espace de travail.",
        "old_string": "Texte à remplacer. Doit être unique, sauf si 'replace_all' vaut true.",
        "new_string": "Texte de remplacement. Une chaîne vide supprime la correspondance.",
        "replace_all": (
            "Remplacer toutes les occurrences au lieu d'exiger une correspondance unique. false "
            "par défaut."
        ),
        "encoding": (
            "Encodage utilisé pour décoder puis réencoder le fichier. UTF-8 par défaut. Utilisez "
            "l'encodage rapporté par read_file. Une marque d'ordre des octets l'emporte sur cette "
            "valeur."
        ),
    },
)

DE = ToolText(
    description=(
        "Ersetzt eine exakt passende Zeichenkette in einer Textdatei. Pfade werden gegen die "
        "Wurzel des Arbeitsbereichs aufgelöst und können sie nicht verlassen; die globale "
        "Erlauben-/Ablehnen-Richtlinie gilt zusätzlich. 'old_string' wird byteweise verglichen und "
        "muss exakt dem Dateiinhalt entsprechen (inklusive Zeilenenden): den Text aus read_file "
        "ohne das Präfix 'N<TAB>' unverändert übernehmen. Die Fundstelle muss eindeutig sein — "
        "kommt 'old_string' mehrfach vor, wird der Aufruf abgelehnt: mehr Kontext mitgeben oder "
        "replace_all=true übergeben, um alle Vorkommen zu ersetzen. Dekodiert wird mit 'encoding' "
        "(standardmäßig UTF-8), ein Byte Order Mark hat Vorrang; eine nicht dekodierbare Datei "
        "liefert einen Fehler mit Kandidaten-Kodierungen — mit dem richtigen 'encoding' erneut "
        "versuchen. Eingefügter Text wird auf die vorhandenen Zeilenenden umgeschrieben, ein Byte "
        "Order Mark bleibt erhalten; nur der Fundbereich wird neu geschrieben, alle anderen Bytes "
        "bleiben unangetastet. Das Schreiben ist atomar, die Dateirechte bleiben erhalten."
    ),
    parameters={
        "file_path": "Dateipfad relativ zur Wurzel des Arbeitsbereichs.",
        "old_string": "Der zu ersetzende Originaltext. Muss eindeutig sein, außer 'replace_all' ist true.",
        "new_string": "Der Ersatztext. Eine leere Zeichenkette löscht die Fundstelle.",
        "replace_all": (
            "Alle Vorkommen ersetzen statt einer eindeutigen Fundstelle zu verlangen. Standard false."
        ),
        "encoding": (
            "Kodierung zum Dekodieren und erneuten Kodieren der Datei. Standard UTF-8. Die von "
            "read_file gemeldete 'encoding' verwenden. Ein Byte Order Mark hat Vorrang vor diesem "
            "Wert."
        ),
    },
)

RU = ToolText(
    description=(
        "Заменяет в текстовом файле фрагмент, совпадающий байт в байт. Пути разрешаются "
        "относительно корня рабочей области и не могут выйти за его пределы; глобальная "
        "политика разрешений и запретов действует дополнительно. 'old_string' сравнивается "
        "побайтово и должен точно совпадать с содержимым файла (включая переводы строк): "
        "возьмите текст из read_file, убрав префикс 'N<TAB>', и передайте как есть. Совпадение "
        "должно быть единственным — если 'old_string' встречается несколько раз, вызов "
        "отклоняется: добавьте контекста или передайте replace_all=true, чтобы заменить все "
        "вхождения. Декодирование выполняется через 'encoding' (по умолчанию UTF-8), метка "
        "порядка байтов имеет приоритет; если файл не декодируется, ошибка перечисляет "
        "подходящие кодировки — повторите с правильной 'encoding'. Вставляемый текст приводится "
        "к существующим в файле переводам строк, метка порядка байтов сохраняется; "
        "перезаписывается только найденный диапазон, остальные байты не меняются. Запись "
        "атомарна, права файла сохраняются."
    ),
    parameters={
        "file_path": "Путь к файлу относительно корня рабочей области.",
        "old_string": "Исходный текст для замены. Должен быть единственным, если 'replace_all' не true.",
        "new_string": "Текст замены. Пустая строка удаляет найденный фрагмент.",
        "replace_all": (
            "Заменить все вхождения вместо требования единственного совпадения. По умолчанию false."
        ),
        "encoding": (
            "Кодировка для декодирования и повторного кодирования файла. По умолчанию UTF-8. "
            "Используйте 'encoding', которую сообщил read_file. Метка порядка байтов имеет "
            "приоритет над этим значением."
        ),
    },
)
