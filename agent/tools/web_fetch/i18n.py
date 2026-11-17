"""Display text for ``web_fetch`` in the admin page's languages.

The model always sees the English description and schema (``description.py``);
these bundles are read by the tool management page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "抓取网页并返回其文本。仅支持 http 与 https，且只能抓无需登录的页面：需要登录的页面会"
        "返回登录页或 HTTP 错误，请如实告知用户，不要重试。HTML 会转换成 Markdown 风格的纯文本"
        "（保留标题、列表、链接、代码块与表格行，丢弃脚本、样式与隐藏元素）。纯文本、JSON 与 XML "
        "原样返回。其他类型（PDF、图片、压缩包）会保存到本次运行的临时目录，并在结果里给出路径。"
        "同域名重定向会自动跟随，最多五次；跨域名重定向不跟随，结果里带 'redirect_to'，请另外"
        "发起一次抓取，让新站点单独获得授权。结果包含 'code' 与 'code_text'（HTTP 状态）、"
        "'bytes'、'duration_ms'、'content_type'、'encoding' 与 'content'。文本超出输出 token "
        "预算时会写入文件，'content' 只给预览与 'persisted_path'，可用 read_file 分段读回。"
        "一个任务里首次访问某个域名会询问用户，同一域名的后续页面不再询问。"
    ),
    parameters={
        "url": (
            "要读取的页面的完整 http:// 或 https:// 地址。内嵌用户名或密码的地址会被拒绝。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "擷取網頁並傳回其文字。僅支援 http 與 https，且只能擷取無需登入的頁面：需要登入的頁面"
        "會傳回登入頁或 HTTP 錯誤，請如實告知使用者，不要重試。HTML 會轉換成 Markdown 風格的"
        "純文字（保留標題、清單、連結、程式碼區塊與表格列，丟棄腳本、樣式與隱藏元素）。純文字、"
        "JSON 與 XML 原樣傳回。其他類型（PDF、圖片、壓縮檔）會存到本次執行的暫存目錄，並在結果裡"
        "給出路徑。同網域重新導向會自動跟隨，最多五次；跨網域重新導向不跟隨，結果裡帶 "
        "'redirect_to'，請另外發起一次擷取，讓新網站單獨取得授權。結果包含 'code' 與 "
        "'code_text'（HTTP 狀態）、'bytes'、'duration_ms'、'content_type'、'encoding' 與 "
        "'content'。文字超出輸出 token 預算時會寫入檔案，'content' 只給預覽與 "
        "'persisted_path'，可用 read_file 分段讀回。一個任務裡首次存取某個網域會詢問使用者，"
        "同一網域的後續頁面不再詢問。"
    ),
    parameters={
        "url": "要讀取的頁面完整 http:// 或 https:// 網址。內嵌使用者名稱或密碼的網址會被拒絕。",
    },
)

FR = ToolText(
    description=(
        "Récupère une page web et renvoie son texte. Seuls http et https sont acceptés, et "
        "seulement pour des pages sans authentification : une page derrière un login renvoie "
        "la page de connexion ou une erreur HTTP, à signaler à l'utilisateur sans réessayer. "
        "Le HTML est converti en texte de style Markdown (titres, listes, liens, blocs de "
        "code et lignes de tableau conservés ; scripts, styles et éléments masqués "
        "supprimés). Le texte brut, JSON et XML reviennent inchangés. Tout autre type (PDF, "
        "image, archive) est enregistré dans le répertoire temporaire de l'exécution et le "
        "résultat indique le chemin. Les redirections vers le même hôte sont suivies, cinq "
        "au maximum ; une redirection vers un autre hôte n'est pas suivie : le résultat "
        "contient 'redirect_to' et il faut récupérer cette URL par un appel séparé, afin que "
        "le nouveau site reçoive sa propre autorisation. Le résultat contient 'code' et "
        "'code_text' (statut HTTP), 'bytes', 'duration_ms', 'content_type', 'encoding' et "
        "'content'. Un texte trop long pour le budget de tokens est écrit dans un fichier ; "
        "'content' ne contient alors qu'un aperçu et 'persisted_path', relisible par "
        "read_file. La première récupération depuis un hôte demande l'autorisation de "
        "l'utilisateur ; les pages suivantes du même hôte ne la redemandent pas."
    ),
    parameters={
        "url": (
            "URL absolue http:// ou https:// de la page à lire. Une URL contenant un nom "
            "d'utilisateur ou un mot de passe est refusée."
        ),
    },
)

DE = ToolText(
    description=(
        "Ruft eine Webseite ab und gibt ihren Text zurück. Nur http und https werden "
        "unterstützt, und nur Seiten ohne Anmeldung: eine Seite hinter einem Login liefert "
        "die Anmeldeseite oder einen HTTP-Fehler - das dem Nutzer melden statt erneut zu "
        "versuchen. HTML wird in Markdown-artigen Text umgewandelt (Überschriften, Listen, "
        "Links, Codeblöcke und Tabellenzeilen bleiben; Skripte, Styles und versteckte "
        "Elemente entfallen). Reiner Text, JSON und XML kommen unverändert zurück. Alle "
        "anderen Typen (PDF, Bild, Archiv) werden im temporären Verzeichnis des Laufs "
        "gespeichert, und das Ergebnis nennt den Pfad. Weiterleitungen zum selben Host "
        "werden verfolgt, höchstens fünfmal; eine Weiterleitung zu einem anderen Host nicht: "
        "das Ergebnis enthält 'redirect_to', und diese URL sollte in einem eigenen Aufruf "
        "abgerufen werden, damit die neue Seite ihre eigene Freigabe bekommt. Das Ergebnis "
        "enthält 'code' und 'code_text' (HTTP-Status), 'bytes', 'duration_ms', "
        "'content_type', 'encoding' und 'content'. Ein Text über dem Ausgabe-Token-Budget "
        "wird in eine Datei geschrieben; 'content' enthält dann eine Vorschau und "
        "'persisted_path', das read_file abschnittsweise liest. Der erste Abruf von einem "
        "Host fragt den Nutzer nach Erlaubnis; weitere Seiten desselben Hosts nicht mehr."
    ),
    parameters={
        "url": (
            "Vollständige http://- oder https://-Adresse der zu lesenden Seite. URLs mit "
            "eingebettetem Benutzernamen oder Passwort werden abgelehnt."
        ),
    },
)

RU = ToolText(
    description=(
        "Загружает веб-страницу и возвращает её текст. Поддерживаются только http и https, "
        "и только страницы без входа: страница за авторизацией вернёт форму входа или "
        "ошибку HTTP - сообщите об этом пользователю, не повторяйте запрос. HTML "
        "преобразуется в текст в стиле Markdown (заголовки, списки, ссылки, блоки кода и "
        "строки таблиц сохраняются; скрипты, стили и скрытые элементы отбрасываются). "
        "Обычный текст, JSON и XML возвращаются без изменений. Всё остальное (PDF, "
        "изображение, архив) сохраняется во временный каталог запуска, а результат "
        "указывает путь. Перенаправления на том же хосте отслеживаются, не более пяти; "
        "перенаправление на другой хост не отслеживается: в результате есть "
        "'redirect_to', и этот адрес нужно загрузить отдельным вызовом, чтобы новый сайт "
        "получил собственное разрешение. Результат содержит 'code' и 'code_text' (статус "
        "HTTP), 'bytes', 'duration_ms', 'content_type', 'encoding' и 'content'. Текст "
        "сверх бюджета выходных токенов записывается в файл; тогда 'content' содержит "
        "предпросмотр и 'persisted_path', который читается через read_file по частям. "
        "Первый запрос к хосту в задаче спрашивает разрешение у пользователя; следующие "
        "страницы того же хоста - уже нет."
    ),
    parameters={
        "url": (
            "Полный адрес http:// или https:// страницы для чтения. Адреса со встроенным "
            "именем пользователя или паролем отклоняются."
        ),
    },
)
