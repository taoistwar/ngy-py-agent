"""Chinese display text for ``read_file``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "读取文本文件。会话绑定了工作空间时，路径以工作空间根目录为基准解析且不能越出；"
        "全局允许/拒绝策略始终叠加生效。返回请求的行区间，每行前是该行的 1 起始行号和单个"
        "制表符。省略 'limit' 表示从 'offset' 读到文件末尾（文件大于 256KB 时会被拒绝）。"
        "给出 'limit' 则读取指定行数；返回文本超过输出 token 预算时会被拒绝，因此请优先读"
        "小范围，需要时用新的 'offset' 继续。解码使用 'encoding'（默认 UTF-8），文件带字节"
        "序标记时以标记为准；无法解码时会返回列出候选编码的错误，请用正确的 'encoding' 重试。"
        "结果会报告实际生效的 'encoding'，把这个值原样传给 edit_file。原始换行符会被保留，"
        "因此去掉 'N<TAB>' 前缀后的文本可以原样作为 edit_file 的 'old_string'。"
    ),
    parameters={
        "file_path": "文件路径，相对于工作空间根目录（绝对路径只有在仍位于工作空间内时才被接受）。",
        "offset": "起始行号（1 起始）。默认 1；0 视为 1。",
        "limit": "要读取的行数。省略（或传 0）表示从 'offset' 读到文件末尾。",
        "encoding": (
            "解码文件所用的文本编码（必填）。除非有特别理由，否则用 UTF-8。"
            "字节序标记优先于此值。解码失败时错误里会列出候选编码，用合适的那个重试。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "讀取文字檔。工作階段綁定了工作區時，路徑以工作區根目錄為基準解析且不能越出；"
        "全域允許／拒絕策略一律疊加生效。傳回請求的行區間，每行前是該行的 1 起始行號與單一"
        "定位字元。省略 'limit' 表示從 'offset' 讀到檔尾（檔案大於 256KB 時會被拒絕）。"
        "給出 'limit' 則讀取指定行數；傳回文字超過輸出 token 預算時會被拒絕，因此請優先讀"
        "小範圍，需要時用新的 'offset' 繼續。解碼使用 'encoding'（預設 UTF-8），檔案帶位元組"
        "順序標記時以標記為準；無法解碼時會傳回列出候選編碼的錯誤，請用正確的 'encoding' 重試。"
        "結果會回報實際生效的 'encoding'，把這個值原樣傳給 edit_file。原始換行字元會被保留，"
        "因此去掉 'N<TAB>' 前綴後的文字可以原樣作為 edit_file 的 'old_string'。"
    ),
    parameters={
        "file_path": "檔案路徑，相對於工作區根目錄（絕對路徑只有在仍位於工作區內時才被接受）。",
        "offset": "起始行號（1 起始）。預設 1；0 視為 1。",
        "limit": "要讀取的行數。省略（或傳 0）表示從 'offset' 讀到檔尾。",
        "encoding": (
            "解碼檔案所用的文字編碼（必填）。除非有特別理由，否則用 UTF-8。"
            "位元組順序標記優先於此值。解碼失敗時錯誤裡會列出候選編碼，用合適的那個重試。"
        ),
    },
)

FR = ToolText(
    description=(
        "Lit un fichier texte. Les chemins sont résolus par rapport à la racine de l'espace de "
        "travail et ne peuvent pas en sortir quand la session en a une ; la politique globale "
        "d'autorisation et de refus s'applique en plus. Renvoie la plage de lignes demandée, "
        "chaque ligne précédée de son numéro de ligne (à partir de 1) et d'une tabulation. "
        "Omettre 'limit' lit de 'offset' jusqu'à la fin du fichier (refusé si le fichier dépasse "
        "256 Ko) ; 'limit' lit ce nombre de lignes. La lecture est refusée quand le texte renvoyé "
        "dépasserait le budget de tokens de sortie : préférez de petites plages et continuez avec "
        "un nouvel 'offset'. Le décodage utilise 'encoding' (UTF-8 par défaut), une marque d'ordre "
        "des octets l'emporte sur cette valeur, et un fichier indécodable renvoie une erreur "
        "listant des encodages candidats : réessayez avec le bon 'encoding'. Le résultat indique "
        "l'encodage réellement utilisé ; transmettez-le tel quel à edit_file. Les fins de ligne "
        "d'origine sont préservées : le texte sans le préfixe 'N<TAB>' est utilisable tel quel "
        "comme 'old_string' d'edit_file."
    ),
    parameters={
        "file_path": (
            "Chemin du fichier, relatif à la racine de l'espace de travail (un chemin absolu "
            "n'est accepté que s'il reste dans l'espace de travail)."
        ),
        "offset": "Numéro de la première ligne (à partir de 1). 1 par défaut ; 0 est traité comme 1.",
        "limit": (
            "Nombre de lignes à lire. Omettre (ou passer 0) lit de 'offset' jusqu'à la fin du "
            "fichier."
        ),
        "encoding": (
            "Encodage utilisé pour décoder le fichier (obligatoire). Utilisez UTF-8 sauf raison "
            "contraire. Une marque d'ordre des octets l'emporte sur cette valeur. En cas d'échec, "
            "l'erreur liste des encodages candidats ; réessayez avec le bon."
        ),
    },
)

DE = ToolText(
    description=(
        "Liest eine Textdatei. Pfade werden gegen die Wurzel des Arbeitsbereichs aufgelöst und "
        "können sie nicht verlassen, wenn die Sitzung eine hat; die globale Erlauben-/"
        "Ablehnen-Richtlinie gilt zusätzlich. Gibt den angeforderten Zeilenbereich zurück, jede "
        "Zeile mit ihrer 1-basierten Zeilennummer und einem Tabulator davor. Ohne 'limit' wird von "
        "'offset' bis zum Dateiende gelesen (abgelehnt, wenn die Datei größer als 256 KB ist); mit "
        "'limit' werden entsprechend viele Zeilen gelesen. Abgelehnt wird auch, wenn der "
        "zurückgegebene Text das Ausgabe-Token-Budget übersteigt: lieber kleine Bereiche lesen und "
        "mit einem neuen 'offset' fortsetzen. Dekodiert wird mit 'encoding' (standardmäßig UTF-8), "
        "ein Byte Order Mark hat Vorrang davor; eine nicht dekodierbare Datei liefert einen Fehler "
        "mit Kandidaten-Kodierungen — mit dem richtigen 'encoding' erneut versuchen. Das Ergebnis "
        "nennt das tatsächlich verwendete 'encoding'; reiche es unverändert an edit_file weiter. "
        "Ursprüngliche Zeilenenden bleiben erhalten, der Text ohne das Präfix 'N<TAB>' ist also "
        "direkt als 'old_string' für edit_file verwendbar."
    ),
    parameters={
        "file_path": (
            "Dateipfad relativ zur Wurzel des Arbeitsbereichs (absolute Pfade werden nur "
            "akzeptiert, solange sie im Arbeitsbereich liegen)."
        ),
        "offset": "Erste Zeilennummer (1-basiert). Standard 1; 0 wird als 1 behandelt.",
        "limit": "Anzahl der zu lesenden Zeilen. Weglassen (oder 0) liest von 'offset' bis zum Dateiende.",
        "encoding": (
            "Kodierung zum Dekodieren der Datei (erforderlich). UTF-8 verwenden, außer es gibt "
            "einen Grund dagegen. Ein Byte Order Mark hat Vorrang vor diesem Wert. Bei Fehlschlag "
            "nennt der Fehler Kandidaten-Kodierungen; mit der passenden erneut versuchen."
        ),
    },
)

RU = ToolText(
    description=(
        "Читает текстовый файл. Пути разрешаются относительно корня рабочей области и не могут "
        "выйти за его пределы, если рабочая область задана; глобальная политика разрешений и "
        "запретов действует дополнительно. Возвращает запрошенный диапазон строк: перед каждой "
        "строкой её номер (с 1) и один символ табуляции. Если 'limit' не указан, читается от "
        "'offset' до конца файла (для файлов больше 256 КБ запрос отклоняется); с 'limit' "
        "читается указанное число строк. Запрос отклоняется, если возвращаемый текст превышает "
        "бюджет выходных токенов, поэтому читайте небольшими диапазонами и продолжайте с новым "
        "'offset'. Декодирование выполняется через 'encoding' (по умолчанию UTF-8), метка "
        "порядка байтов имеет приоритет; если файл не декодируется, ошибка перечисляет "
        "подходящие кодировки — повторите с правильной 'encoding'. В результате указывается "
        "фактически использованная 'encoding'; передайте её в edit_file без изменений. Исходные "
        "переводы строк сохраняются, поэтому текст без префикса 'N<TAB>' можно передавать в "
        "edit_file как 'old_string'."
    ),
    parameters={
        "file_path": (
            "Путь к файлу относительно корня рабочей области (абсолютный путь принимается, "
            "только если он остаётся внутри рабочей области)."
        ),
        "offset": "Номер первой строки (с 1). По умолчанию 1; 0 трактуется как 1.",
        "limit": (
            "Сколько строк прочитать. Если не указать (или указать 0) — читать от 'offset' до "
            "конца файла."
        ),
        "encoding": (
            "Кодировка для декодирования файла (обязательно). Используйте UTF-8, если нет особой "
            "причины. Метка порядка байтов имеет приоритет над этим значением. При ошибке "
            "декодирования в тексте ошибки перечислены подходящие кодировки — повторите с нужной."
        ),
    },
)
