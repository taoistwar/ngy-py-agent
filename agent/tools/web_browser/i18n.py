"""Display text for ``web_browser`` in the admin page's languages.

The model always sees the English description and schema (``description.py``);
these bundles are read by the tool management page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "打开一个网页，返回它的标题、最终地址与正文，就像一个只有文字的浏览器。仅支持 http 与 https，"
        "且只能打开无需登录的页面：需要登录的页面会返回登录页或 HTTP 错误，请如实告知用户，不要重试。"
        "它不是真的浏览器：只下载 HTML 再去掉标签，不执行 JavaScript（靠脚本渲染的页面只能拿到空壳或"
        "残缺内容），也不能点击、输入、滚动，无法截图。'action' 取 'navigate'（默认）读取页面，取 "
        "'screenshot' 则返回同一份正文并在开头说明没有截取画面。脚本、样式、隐藏元素与站点框架"
        "（nav/footer）会被丢弃；结果是纯文本而不是 Markdown：列表项保留 '- ' 前缀，链接地址与代码围栏"
        "不保留。需要结构、HTTP 状态、内容类型、编码，或要把非文本内容存盘时，请改用 web_fetch。"
        "同域名重定向会自动跟随，最多五次；跨域名重定向不跟随，结果里带 'redirect_to'，请另外发起一次"
        "调用，让新站点单独获得授权。正文超过 50,000 个字符会截断，并以 '[truncated]' 结尾；若仍超出"
        "输出 token 预算，全文写入文件，'content' 只给预览与 'persisted_path'，可用 read_file 分段读回。"
        "结果包含 'title'、'url'（最终地址）、'action'、'content' 与 'truncated'；失败时是 'error' 与 "
        "'reason'，'title' 为 'HTTP 404' 或 'Error'。一个任务里首次打开某个域名会询问用户，同一域名的"
        "后续页面不再询问。"
    ),
    parameters={
        "url": "要打开的页面的完整 http:// 或 https:// 地址。内嵌用户名或密码的地址会被拒绝。",
        "action": (
            "'navigate'（默认）打开页面并返回正文；'screenshot' 返回同一份正文，并在开头说明本工具"
            "无法截取画面。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "開啟一個網頁，傳回它的標題、最終位址與正文，就像一個只有文字的瀏覽器。僅支援 http 與 https，"
        "且只能開啟無需登入的頁面：需要登入的頁面會傳回登入頁或 HTTP 錯誤，請如實告知使用者，不要重試。"
        "它不是真的瀏覽器：只下載 HTML 再去掉標籤，不執行 JavaScript（靠腳本渲染的頁面只能拿到空殼或"
        "殘缺內容），也不能點擊、輸入、捲動，無法截圖。'action' 取 'navigate'（預設）讀取頁面，取 "
        "'screenshot' 則傳回同一份正文並在開頭說明沒有截取畫面。腳本、樣式、隱藏元素與站台框架"
        "（nav/footer）會被丟棄；結果是純文字而不是 Markdown：清單項目保留 '- ' 前綴，連結位址與程式碼"
        "圍籬不保留。需要結構、HTTP 狀態、內容類型、編碼，或要把非文字內容存檔時，請改用 web_fetch。"
        "同網域重新導向會自動跟隨，最多五次；跨網域重新導向不跟隨，結果裡帶 'redirect_to'，請另外發起"
        "一次呼叫，讓新網站單獨取得授權。正文超過 50,000 個字元會截斷，並以 '[truncated]' 結尾；若仍"
        "超出輸出 token 預算，全文寫入檔案，'content' 只給預覽與 'persisted_path'，可用 read_file 分段"
        "讀回。結果包含 'title'、'url'（最終位址）、'action'、'content' 與 'truncated'；失敗時是 "
        "'error' 與 'reason'，'title' 為 'HTTP 404' 或 'Error'。一個任務裡首次開啟某個網域會詢問"
        "使用者，同一網域的後續頁面不再詢問。"
    ),
    parameters={
        "url": "要開啟的頁面完整 http:// 或 https:// 網址。內嵌使用者名稱或密碼的網址會被拒絕。",
        "action": (
            "'navigate'（預設）開啟頁面並傳回正文；'screenshot' 傳回同一份正文，並在開頭說明本工具"
            "無法截取畫面。"
        ),
    },
)

FR = ToolText(
    description=(
        "Ouvre une page web et renvoie son titre, son URL finale et son texte, comme le ferait "
        "un navigateur en mode texte. Seuls http et https sont acceptés, et seulement pour des "
        "pages sans authentification : une page derrière un login renvoie la page de connexion "
        "ou une erreur HTTP, à signaler à l'utilisateur sans réessayer. Ce n'est pas un vrai "
        "navigateur : le HTML est téléchargé puis le balisage retiré, donc le JavaScript n'est "
        "pas exécuté (une page construite dans le navigateur revient vide ou partielle) et il "
        "est impossible de cliquer, saisir, faire défiler ou capturer une image. 'action' vaut "
        "'navigate' (par défaut) pour lire la page, ou 'screenshot' pour le même texte précédé "
        "d'une note indiquant qu'aucune image n'a été capturée. Scripts, styles, éléments "
        "masqués et habillage du site (nav/footer) sont supprimés, et le résultat est du texte "
        "brut et non du Markdown : les listes gardent un tiret '- ', les cibles de liens et les "
        "blocs de code ne survivent pas. Utiliser web_fetch lorsque la structure compte, que le "
        "statut HTTP, le type de contenu ou l'encodage sont nécessaires, ou qu'un corps non "
        "textuel doit être enregistré. Les redirections vers le même hôte sont suivies, cinq au "
        "maximum ; une redirection vers un autre hôte ne l'est pas : le résultat contient "
        "'redirect_to' et il faut ouvrir cette URL par un appel séparé. Un texte de plus de "
        "50 000 caractères est coupé et se termine par '[truncated]'. S'il dépasse encore le "
        "budget de tokens, il est écrit dans un fichier et 'content' ne contient qu'un aperçu "
        "et 'persisted_path', relisible par read_file. Le résultat contient 'title', 'url' "
        "(URL finale), 'action', 'content' et 'truncated'. Un échec donne 'error' et 'reason', "
        "avec 'title' à 'HTTP 404' ou 'Error'. La première page d'un hôte dans une tâche "
        "demande l'autorisation de l'utilisateur ; les pages suivantes du même hôte non."
    ),
    parameters={
        "url": (
            "URL absolue http:// ou https:// de la page à ouvrir. Une URL contenant un nom "
            "d'utilisateur ou un mot de passe est refusée."
        ),
        "action": (
            "'navigate' (par défaut) ouvre la page et renvoie son texte ; 'screenshot' renvoie "
            "le même texte précédé d'une note indiquant qu'aucune capture n'est possible."
        ),
    },
)

DE = ToolText(
    description=(
        "Öffnet eine Webseite und gibt ihren Titel, ihre endgültige URL und ihren Text zurück, "
        "wie es ein Textbrowser täte. Nur http und https werden unterstützt, und nur Seiten "
        "ohne Anmeldung: eine Seite hinter einem Login liefert die Anmeldeseite oder einen "
        "HTTP-Fehler - das dem Nutzer melden statt erneut zu versuchen. Es ist kein echter "
        "Browser: das HTML wird geladen und das Markup entfernt, daher läuft kein JavaScript "
        "(eine im Browser zusammengebaute Seite kommt leer oder unvollständig zurück), und "
        "Klicken, Tippen, Scrollen oder ein Screenshot sind nicht möglich. 'action' ist "
        "'navigate' (Standard) zum Lesen der Seite oder 'screenshot' für denselben Text mit "
        "einem Hinweis, dass kein Bild aufgenommen wurde. Skripte, Styles, versteckte Elemente "
        "und Seitengerüst (nav/footer) entfallen, und das Ergebnis ist reiner Text statt "
        "Markdown: Listeneinträge behalten '- ', Linkziele und Codeblöcke überleben nicht. "
        "web_fetch ist die richtige Wahl, wenn Struktur zählt, HTTP-Status, Inhaltstyp oder "
        "Kodierung gebraucht werden, oder ein nicht-textueller Body gespeichert werden soll. "
        "Weiterleitungen zum selben Host werden verfolgt, höchstens fünfmal; eine Weiterleitung "
        "zu einem anderen Host nicht: das Ergebnis enthält 'redirect_to', und diese URL sollte "
        "in einem eigenen Aufruf geöffnet werden. Text über 50.000 Zeichen wird abgeschnitten "
        "und endet mit '[truncated]'. Passt er trotzdem nicht ins Ausgabe-Token-Budget, wird er "
        "in eine Datei geschrieben; 'content' enthält dann eine Vorschau und 'persisted_path', "
        "das read_file abschnittsweise liest. Das Ergebnis enthält 'title', 'url' "
        "(endgültige URL), 'action', 'content' und 'truncated'. Ein Fehler liefert 'error' und "
        "'reason', wobei 'title' 'HTTP 404' oder 'Error' ist. Die erste Seite eines Hosts in "
        "einer Aufgabe fragt den Nutzer nach Erlaubnis; weitere Seiten desselben Hosts nicht."
    ),
    parameters={
        "url": (
            "Vollständige http://- oder https://-Adresse der zu öffnenden Seite. URLs mit "
            "eingebettetem Benutzernamen oder Passwort werden abgelehnt."
        ),
        "action": (
            "'navigate' (Standard) öffnet die Seite und gibt ihren Text zurück; 'screenshot' "
            "gibt denselben Text mit einem Hinweis zurück, dass keine Aufnahme möglich ist."
        ),
    },
)

RU = ToolText(
    description=(
        "Открывает веб-страницу и возвращает её заголовок, итоговый адрес и текст - так, как "
        "это сделал бы текстовый браузер. Поддерживаются только http и https, и только "
        "страницы без входа: страница за авторизацией вернёт форму входа или ошибку HTTP - "
        "сообщите об этом пользователю, не повторяйте запрос. Это не настоящий браузер: HTML "
        "загружается, разметка снимается, поэтому JavaScript не выполняется (страница, "
        "собранная в браузере, вернётся пустой или неполной), а клики, ввод, прокрутка и "
        "снимок экрана невозможны. 'action' - 'navigate' (по умолчанию) для чтения страницы "
        "или 'screenshot' для того же текста с пометкой, что изображение не снято. Скрипты, "
        "стили, скрытые элементы и оформление сайта (nav/footer) отбрасываются, а результат - "
        "простой текст, не Markdown: пункты списков сохраняют '- ', адреса ссылок и блоки кода "
        "не сохраняются. Используйте web_fetch, когда важна структура, нужны статус HTTP, тип "
        "содержимого или кодировка, либо нетекстовое тело нужно сохранить на диск. "
        "Перенаправления на том же хосте отслеживаются, не более пяти; перенаправление на "
        "другой хост нет: в результате есть 'redirect_to', и этот адрес нужно открыть "
        "отдельным вызовом. Текст длиннее 50 000 символов обрезается и заканчивается "
        "'[truncated]'. Если он всё равно не влезает в бюджет выходных токенов, он "
        "записывается в файл, а 'content' содержит предпросмотр и 'persisted_path', который "
        "читается через read_file по частям. Результат содержит 'title', 'url' (итоговый "
        "адрес), 'action', 'content' и 'truncated'. При ошибке возвращаются 'error' и "
        "'reason', а 'title' равен 'HTTP 404' или 'Error'. Первая страница с хоста в задаче "
        "спрашивает разрешение у пользователя; следующие страницы того же хоста - уже нет."
    ),
    parameters={
        "url": (
            "Полный адрес http:// или https:// страницы для открытия. Адреса со встроенным "
            "именем пользователя или паролем отклоняются."
        ),
        "action": (
            "'navigate' (по умолчанию) открывает страницу и возвращает её текст; 'screenshot' "
            "возвращает тот же текст с пометкой, что снимок экрана невозможен."
        ),
    },
)
