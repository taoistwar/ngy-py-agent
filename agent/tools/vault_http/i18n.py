"""Display text for ``vault_http`` in the admin page's languages.

The model always sees the English description and schema (``description.py``);
these bundles are read by the tool management page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "用本地保险柜（vault）里的密钥发起一次 HTTPS 请求。密钥只按名称引用"
        "（vault_auth_key），不会作为参数传入：保险柜保存密钥本体，工具把它挂到请求上，再把"
        "回信里密钥的各种变形全部擦掉，所以模型与记录都看不到它。需要 token、API key 或 basic "
        "认证的接口用这个方法；公开网页请用 web_fetch。规则：只接受 https:// 地址，明文 http "
        "直接拒绝；不跟随重定向——30x 会带 redirect_to 返回，请另发一次调用，让新域名单独获得"
        "授权；body 可配 POST/PUT/PATCH/DELETE，GET 不能带 body。auth_scheme 决定密钥挂在哪里："
        "默认 bearer → 'Authorization: Bearer <密钥>'；basic → 'Authorization: Basic "
        "base64(<密钥>)'，保险柜里存的是 'user:password'；header_x_api_key → 'X-Api-Key: "
        "<密钥>'；custom → 挂到 auth_header_name 指定的请求头。参数严格匹配：多传或拼错的参数"
        "会被拒绝，不会被忽略。结果包含 status 与 status_text（HTTP 状态）、response_headers"
        "（已擦除）、body（已擦除，JSON 与文本原样）、bytes、duration_ms、encoding，被重定向时"
        "还有 redirect_to。正文超出输出 token 预算时会写入文件，body 只给预览与 persisted_path，"
        "可用 read_file 分段读回。每次调用都会先询问用户（按“钥匙名 + 域名”授权），该批准只覆盖"
        "这一个组合；即使确认被设为自动批准，这个询问也照样会出现。失败是 "
        "'{\"error\", \"reason\", ...}'，不带 status 与 body。"
    ),
    parameters={
        "url": "接口的完整 https:// 地址。http:// 与其他协议会被拒绝；内嵌用户名或密码的地址也会被拒绝。",
        "vault_auth_key": (
            "保险柜里存放密钥的条目名称（1–128 位字母、数字、'.'、'_'、':' 或 '-'），例如 "
            "'gh-token'。密钥本体永远不作为参数传入。"
        ),
        "reason": "为什么需要这次请求（1–500 字符）。会显示在许可弹窗与审计日志里，请写给批准人看。",
        "method": "HTTP 方法，默认 GET。",
        "auth_scheme": (
            "密钥的挂载方式：bearer（默认）→ Authorization: Bearer；basic → Authorization: "
            "Basic base64(密钥)，密钥按 'user:password' 存；header_x_api_key → X-Api-Key；"
            "custom → auth_header_name 指定的请求头。"
        ),
        "auth_header_name": (
            "承载密钥的请求头。auth_scheme=custom 时必填，其他取值下会被拒绝。1–64 位字母、数字、"
            "'_' 或 '-'；host、content-length 这类报文框架头不允许。"
        ),
        "body": "请求正文，按 UTF-8 发送。可用于 POST、PUT、PATCH、DELETE；GET 会被拒绝。",
        "body_content_type": "body 的 Content-Type，默认 application/json（最长 128 字符）。",
    },
)

ZH_TW = ToolText(
    description=(
        "用本機保險箱（vault）裡的密鑰發起一次 HTTPS 請求。密鑰只按名稱引用"
        "（vault_auth_key），不會當作參數傳入：保險箱保存密鑰本體，工具把它掛到請求上，再把"
        "回信裡密鑰的各種變形全部擦掉，所以模型與紀錄都看不到它。需要 token、API key 或 basic "
        "認證的介面用這個方法；公開網頁請用 web_fetch。規則：只接受 https:// 網址，明文 http "
        "直接拒絕；不跟隨重新導向——30x 會帶 redirect_to 傳回，請另發一次呼叫，讓新網域單獨取得"
        "授權；body 可配 POST/PUT/PATCH/DELETE，GET 不能帶 body。auth_scheme 決定密鑰掛在哪裡："
        "預設 bearer → 'Authorization: Bearer <密鑰>'；basic → 'Authorization: Basic "
        "base64(<密鑰>)'，保險箱裡存的是 'user:password'；header_x_api_key → 'X-Api-Key: "
        "<密鑰>'；custom → 掛到 auth_header_name 指定的請求標頭。參數嚴格比對：多傳或拼錯的參數"
        "會被拒絕，不會被忽略。結果包含 status 與 status_text（HTTP 狀態）、response_headers"
        "（已擦除）、body（已擦除，JSON 與文字原樣）、bytes、duration_ms、encoding，被重新導向時"
        "還有 redirect_to。正文超出輸出 token 預算時會寫入檔案，body 只給預覽與 persisted_path，"
        "可用 read_file 分段讀回。每次呼叫都會先詢問使用者（按「密鑰名 + 網域」授權），該批准只"
        "覆蓋這一個組合；即使確認被設為自動批准，這個詢問也照樣會出現。失敗是 "
        "'{\"error\", \"reason\", ...}'，不帶 status 與 body。"
    ),
    parameters={
        "url": "介面的完整 https:// 網址。http:// 與其他協定會被拒絕；內嵌使用者名稱或密碼的網址也會被拒絕。",
        "vault_auth_key": (
            "保險箱裡存放密鑰的項目名稱（1–128 位字母、數字、'.'、'_'、':' 或 '-'），例如 "
            "'gh-token'。密鑰本體永遠不作為參數傳入。"
        ),
        "reason": "為什麼需要這次請求（1–500 字元）。會顯示在許可彈窗與稽核日誌裡，請寫給批准人看。",
        "method": "HTTP 方法，預設 GET。",
        "auth_scheme": (
            "密鑰的掛載方式：bearer（預設）→ Authorization: Bearer；basic → Authorization: "
            "Basic base64(密鑰)，密鑰按 'user:password' 存；header_x_api_key → X-Api-Key；"
            "custom → auth_header_name 指定的請求標頭。"
        ),
        "auth_header_name": (
            "承載密鑰的請求標頭。auth_scheme=custom 時必填，其他取值下會被拒絕。1–64 位字母、數字、"
            "'_' 或 '-'；host、content-length 這類訊息框架標頭不允許。"
        ),
        "body": "請求正文，按 UTF-8 送出。可用於 POST、PUT、PATCH、DELETE；GET 會被拒絕。",
        "body_content_type": "body 的 Content-Type，預設 application/json（最長 128 字元）。",
    },
)

FR = ToolText(
    description=(
        "Envoie une requête HTTPS en utilisant un secret pris dans le coffre local (vault). "
        "Le secret est référencé par son NOM (vault_auth_key), jamais passé en argument : le "
        "coffre détient la valeur, l'outil l'attache à la requête puis efface toutes ses "
        "formes de la réponse, donc ni le modèle ni la trace ne la voient. À utiliser pour "
        "les points d'accès qui demandent un token, une clé d'API ou une authentification "
        "basic ; une page publique se lit avec web_fetch. Règles : seules les URL https:// "
        "sont acceptées (http en clair est refusé) ; les redirections ne sont PAS suivies - "
        "un 30x revient avec 'redirect_to' et doit être demandé par un appel séparé, afin "
        "que le nouvel hôte reçoive sa propre autorisation ; un corps peut accompagner POST, "
        "PUT, PATCH ou DELETE, jamais GET. auth_scheme décide où va le secret : 'bearer' "
        "(par défaut) envoie 'Authorization: Bearer <secret>', 'basic' envoie "
        "'Authorization: Basic base64(<secret>)' où le secret stocké s'écrit "
        "'utilisateur:mot de passe', 'header_x_api_key' envoie 'X-Api-Key: <secret>' et "
        "'custom' l'envoie dans l'en-tête nommé par 'auth_header_name'. Les arguments sont "
        "comparés exactement : un argument inconnu ou mal orthographié est refusé, pas "
        "ignoré. Le résultat contient 'status' et 'status_text', 'response_headers' "
        "(effacés), 'body' (effacé, JSON et texte tels quels), 'bytes', 'duration_ms', "
        "'encoding', et 'redirect_to' si le serveur a redirigé. Un corps dépassant le "
        "budget de tokens est écrit dans un fichier ; 'body' ne contient alors qu'un aperçu "
        "et 'persisted_path', relisible par read_file. Chaque appel demande d'abord "
        "l'autorisation de l'utilisateur, liée au nom de clé et à l'hôte ; une autorisation "
        "permanente ne couvre que ce couple, et cette question est posée même lorsque les "
        "confirmations sont par ailleurs automatiques. Un échec est "
        "'{\"error\", \"reason\", ...}' sans status ni body."
    ),
    parameters={
        "url": (
            "URL https:// absolue du point d'accès. http:// et les autres schémas sont "
            "refusés, tout comme une URL contenant un nom d'utilisateur ou un mot de passe."
        ),
        "vault_auth_key": (
            "Nom de l'entrée du coffre qui contient le secret (1 à 128 lettres, chiffres, "
            "'.', '_', ':' ou '-'), par exemple 'gh-token'. Le secret lui-même n'est jamais "
            "un argument."
        ),
        "reason": (
            "Pourquoi cette requête est nécessaire (1 à 500 caractères). Affiché dans la "
            "boîte d'autorisation et le journal d'audit : écrivez-le pour la personne qui "
            "approuve."
        ),
        "method": "Méthode HTTP. Par défaut GET.",
        "auth_scheme": (
            "Comment le secret est attaché : 'bearer' (par défaut) -> Authorization: Bearer ; "
            "'basic' -> Authorization: Basic base64(secret), le secret stocké étant "
            "'utilisateur:mot de passe' ; 'header_x_api_key' -> X-Api-Key ; 'custom' -> "
            "l'en-tête indiqué par auth_header_name."
        ),
        "auth_header_name": (
            "En-tête qui porte le secret. Obligatoire avec auth_scheme=custom, refusé "
            "autrement. 1 à 64 lettres, chiffres, '_' ou '-' ; les en-têtes de structure "
            "comme host ou content-length sont interdits."
        ),
        "body": (
            "Corps de la requête, envoyé en UTF-8. Autorisé avec POST, PUT, PATCH et "
            "DELETE ; refusé avec GET."
        ),
        "body_content_type": (
            "Content-Type du corps. Par défaut 'application/json' (128 caractères maximum)."
        ),
    },
)

DE = ToolText(
    description=(
        "Sendet eine HTTPS-Anfrage mit einem Geheimnis aus dem lokalen Tresor (Vault). Das "
        "Geheimnis wird über seinen NAMEN (vault_auth_key) referenziert, nie als Argument "
        "übergeben: der Tresor hält den Wert, das Werkzeug hängt ihn an die Anfrage und "
        "entfernt anschließend jede Form davon aus der Antwort - weder Modell noch "
        "Protokoll sehen ihn. Für Endpunkte mit Token, API-Schlüssel oder Basic-Auth "
        "gedacht; eine öffentliche Seite liest web_fetch. Regeln: nur https:// wird "
        "akzeptiert (reines http wird abgelehnt); Weiterleitungen werden NICHT verfolgt - "
        "ein 30x kommt mit 'redirect_to' zurück und muss als eigener Aufruf erfolgen, damit "
        "der neue Host seine eigene Freigabe bekommt; ein Body ist mit POST, PUT, PATCH und "
        "DELETE erlaubt, mit GET nicht. auth_scheme entscheidet, wohin das Geheimnis geht: "
        "'bearer' (Standard) sendet 'Authorization: Bearer <Geheimnis>', 'basic' sendet "
        "'Authorization: Basic base64(<Geheimnis>)' mit gespeichertem 'Benutzer:Passwort', "
        "'header_x_api_key' sendet 'X-Api-Key: <Geheimnis>' und 'custom' sendet es in dem "
        "Header, den 'auth_header_name' nennt. Argumente werden exakt geprüft: ein "
        "unbekanntes oder falsch geschriebenes Argument wird abgelehnt, nicht ignoriert. "
        "Das Ergebnis enthält 'status' und 'status_text', 'response_headers' (bereinigt), "
        "'body' (bereinigt, JSON und Text unverändert), 'bytes', 'duration_ms', 'encoding' "
        "und bei Weiterleitung 'redirect_to'. Ein Body über dem Ausgabe-Token-Budget wird "
        "in eine Datei geschrieben; 'body' enthält dann eine Vorschau und "
        "'persisted_path', das read_file abschnittsweise liest. Jeder Aufruf fragt zuerst "
        "den Nutzer, gebunden an Schlüsselname und Host; eine dauerhafte Freigabe gilt nur "
        "für dieses Paar, und diese Frage kommt auch dann, wenn Bestätigungen sonst "
        "automatisch erteilt werden. Ein Fehler ist '{\"error\", \"reason\", ...}' ohne "
        "Status und Body."
    ),
    parameters={
        "url": (
            "Vollständige https://-Adresse des Endpunkts. http:// und andere Schemata "
            "werden abgelehnt, ebenso URLs mit eingebettetem Benutzernamen oder Passwort."
        ),
        "vault_auth_key": (
            "Name des Tresoreintrags mit dem Geheimnis (1-128 Buchstaben, Ziffern, '.', "
            "'_', ':' oder '-'), zum Beispiel 'gh-token'. Das Geheimnis selbst ist nie ein "
            "Argument."
        ),
        "reason": (
            "Warum diese Anfrage nötig ist (1-500 Zeichen). Erscheint im "
            "Bestätigungsdialog und im Audit-Log - für die Person geschrieben, die zustimmt."
        ),
        "method": "HTTP-Methode. Standard: GET.",
        "auth_scheme": (
            "Wie das Geheimnis angehängt wird: 'bearer' (Standard) -> Authorization: Bearer; "
            "'basic' -> Authorization: Basic base64(Geheimnis) mit 'Benutzer:Passwort'; "
            "'header_x_api_key' -> X-Api-Key; 'custom' -> der in auth_header_name genannte "
            "Header."
        ),
        "auth_header_name": (
            "Header, der das Geheimnis trägt. Pflicht bei auth_scheme=custom, sonst "
            "abgelehnt. 1-64 Buchstaben, Ziffern, '_' oder '-'; Rahmen-Header wie host oder "
            "content-length sind nicht erlaubt."
        ),
        "body": (
            "Anfrage-Body, als UTF-8 gesendet. Erlaubt mit POST, PUT, PATCH und DELETE; mit "
            "GET abgelehnt."
        ),
        "body_content_type": (
            "Content-Type des Bodys. Standard 'application/json' (höchstens 128 Zeichen)."
        ),
    },
)

RU = ToolText(
    description=(
        "Отправляет один HTTPS-запрос с секретом из локального хранилища (vault). Секрет "
        "указывается ИМЕНЕМ (vault_auth_key) и никогда не передаётся аргументом: хранилище "
        "держит значение, инструмент подставляет его в запрос, а затем вычищает все его "
        "формы из ответа - ни модель, ни журнал его не видят. Нужен для эндпоинтов с "
        "токеном, ключом API или basic-аутентификацией; публичную страницу читает "
        "web_fetch. Правила: принимаются только адреса https:// (обычный http "
        "отклоняется); перенаправления НЕ отслеживаются - ответ 30x возвращается с "
        "'redirect_to' и требует отдельного вызова, чтобы новый хост получил собственное "
        "разрешение; тело допустимо с POST, PUT, PATCH и DELETE, но не с GET. auth_scheme "
        "решает, куда попадёт секрет: 'bearer' (по умолчанию) отправляет 'Authorization: "
        "Bearer <секрет>', 'basic' отправляет 'Authorization: Basic base64(<секрет>)', где "
        "секрет хранится как 'пользователь:пароль', 'header_x_api_key' отправляет "
        "'X-Api-Key: <секрет>', а 'custom' - в заголовке, указанном в "
        "'auth_header_name'. Аргументы сверяются точно: неизвестный или с опечаткой "
        "аргумент отклоняется, а не игнорируется. Результат содержит 'status' и "
        "'status_text', 'response_headers' (вычищены), 'body' (вычищено, JSON и текст "
        "как есть), 'bytes', 'duration_ms', 'encoding' и 'redirect_to' при "
        "перенаправлении. Тело сверх бюджета выходных токенов записывается в файл, тогда "
        "'body' содержит предпросмотр и 'persisted_path', который читается через "
        "read_file по частям. Каждый вызов сначала спрашивает пользователя, привязывая "
        "разрешение к имени ключа и хосту; постоянное разрешение покрывает только эту "
        "пару, и вопрос задаётся даже когда подтверждения в остальном автоматические. "
        "Ошибка - это '{\"error\", \"reason\", ...}' без status и body."
    ),
    parameters={
        "url": (
            "Полный адрес эндпоинта https://. http:// и другие схемы отклоняются, как и "
            "адреса со встроенным именем пользователя или паролем."
        ),
        "vault_auth_key": (
            "Имя записи в хранилище с секретом (1-128 букв, цифр, '.', '_', ':' или '-'), "
            "например 'gh-token'. Сам секрет никогда не является аргументом."
        ),
        "reason": (
            "Зачем нужен этот запрос (1-500 символов). Показывается в окне разрешения и в "
            "журнале аудита - пишите для того, кто утверждает."
        ),
        "method": "Метод HTTP. По умолчанию GET.",
        "auth_scheme": (
            "Как подставляется секрет: 'bearer' (по умолчанию) -> Authorization: Bearer; "
            "'basic' -> Authorization: Basic base64(секрет) с секретом "
            "'пользователь:пароль'; 'header_x_api_key' -> X-Api-Key; 'custom' -> заголовок "
            "из auth_header_name."
        ),
        "auth_header_name": (
            "Заголовок, несущий секрет. Обязателен при auth_scheme=custom, иначе "
            "отклоняется. 1-64 буквы, цифры, '_' или '-'; служебные заголовки вроде host "
            "или content-length запрещены."
        ),
        "body": (
            "Тело запроса, отправляется в UTF-8. Допустимо с POST, PUT, PATCH и DELETE; с "
            "GET отклоняется."
        ),
        "body_content_type": (
            "Content-Type тела. По умолчанию 'application/json' (не более 128 символов)."
        ),
    },
)
