"""Chinese display text for ``computer_control``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "通过本机 cua-driver 操作宿主桌面。作用于 agent 运行的真实机器，不是沙箱。动作："
        "'launch_app'（按路径/名称启动 Win32 应用、按 aumid 启动打包应用，或用 urls 打开网址）、"
        "'click'/'double_click'/'right_click'（pid、window_id，再加 element_token 或 x/y）、"
        "'drag'、'scroll'、'press_key'、'hotkey'、'type_text'、'set_window_frame'、"
        "'invoke_menu'、'bring_to_front'。规则：(1) 动作前后都要调用 computer_observe "
        "get_window_state；元素 token 只对产生它的快照有效。(2) 优先用 element_token 而不是 "
        "x/y：它走无障碍调用路径，不移动光标、不改变焦点。(3) delivery_mode 默认 "
        "'background'，绝不抢占前台窗口；某次调用返回 background_unavailable 时，只把那一单个"
        "动作用 delivery_mode='foreground' 重试。(4) 动作可能在没有改变界面时报告成功"
        "（UWP 应用会静默忽略合成事件，effect='unverifiable'）：重试前先重新快照，否则可能"
        "输入或点击两次。(5) 调用返回 stale_element_token 时，重新快照。部分动作可以通过 "
        "'params' 传入这里没列出的 driver 原生字段。不要用 exec_command（Start-Process、"
        "cmd /c start、explorer.exe shell:...）启动或操作 GUI 应用 —— 那些方式会抢焦点并绕过 "
        "driver 的后台输入处理；请改用本工具。"
    ),
    parameters={
        "action": "要执行的桌面动作。",
        "pid": "目标进程 id（来自 list_apps 或 launch_app）。",
        "window_id": "来自 list_windows 的目标窗口句柄（十进制或 0x 前缀十六进制）。",
        "element_token": (
            "上一次 get_window_state 快照中某个控件的 token。优先于坐标；"
            "新的快照或界面变化后它会失效。"
        ),
        "x": "客户区 x 坐标（像素路径）。",
        "y": "客户区 y 坐标（像素路径）。",
        "from_x": "拖动起点 x。",
        "from_y": "拖动起点 y。",
        "to_x": "拖动终点 x。",
        "to_y": "拖动终点 y。",
        "delta_x": "水平滚动增量。",
        "delta_y": "垂直滚动增量。",
        "direction": "driver 期望方向而不是增量时的滚动方向。",
        "amount": "滚动量。",
        "text": "要输入的文本（type_text）。",
        "key": "要按下的单个按键（press_key）。",
        "keys": "热键组合，例如 ['alt', 'f4']。",
        "path": "可执行文件路径（launch_app）。",
        "name": "应用名称（launch_app）。",
        "aumid": "打包 Windows 应用的 application user model id（launch_app）。",
        "urls": "要打开的网址，每个一个窗口（launch_app）。",
        "width": "窗口宽度（set_window_frame）。",
        "height": "窗口高度（set_window_frame）。",
        "delivery_mode": (
            "输入投递方式。保持 'background'（绝不抢焦点）；只有返回 background_unavailable "
            "的单个动作才用 'foreground'。"
        ),
        "params": "命名参数未覆盖的动作所用的 driver 原生字段。",
    },
)

ZH_TW = ToolText(
    description=(
        "透過本機 cua-driver 操作宿主桌面。作用於 agent 執行的真實機器，不是沙箱。動作："
        "'launch_app'（依路徑／名稱啟動 Win32 應用程式、依 aumid 啟動封裝應用程式，或用 urls "
        "開啟網址）、'click'/'double_click'/'right_click'（pid、window_id，再加 element_token "
        "或 x/y）、'drag'、'scroll'、'press_key'、'hotkey'、'type_text'、'set_window_frame'、"
        "'invoke_menu'、'bring_to_front'。規則：(1) 動作前後都要呼叫 computer_observe "
        "get_window_state；元素 token 只對產生它的快照有效。(2) 優先使用 element_token 而不是 "
        "x/y：它走無障礙呼叫路徑，不移動游標、不改變焦點。(3) delivery_mode 預設 'background'，"
        "絕不搶占前景視窗；某次呼叫傳回 background_unavailable 時，只把那個單一動作用 "
        "delivery_mode='foreground' 重試。(4) 動作可能在沒有改變介面時回報成功（UWP 應用程式"
        "會靜默忽略合成事件，effect='unverifiable'）：重試前先重新快照，否則可能輸入或點擊兩次。"
        "(5) 呼叫傳回 stale_element_token 時，重新快照。部分動作可以透過 'params' 傳入這裡沒"
        "列出的 driver 原生欄位。不要用 exec_command（Start-Process、cmd /c start、"
        "explorer.exe shell:...）啟動或操作 GUI 應用程式 —— 那些方式會搶焦點並繞過 driver 的"
        "背景輸入處理；請改用本工具。"
    ),
    parameters={
        "action": "要執行的桌面動作。",
        "pid": "目標行程 id（來自 list_apps 或 launch_app）。",
        "window_id": "來自 list_windows 的目標視窗控制代碼（十進位或 0x 前綴十六進位）。",
        "element_token": (
            "上一次 get_window_state 快照中某個控制項的 token。優先於座標；"
            "新的快照或介面變化後它會失效。"
        ),
        "x": "客戶區 x 座標（像素路徑）。",
        "y": "客戶區 y 座標（像素路徑）。",
        "from_x": "拖曳起點 x。",
        "from_y": "拖曳起點 y。",
        "to_x": "拖曳終點 x。",
        "to_y": "拖曳終點 y。",
        "delta_x": "水平捲動增量。",
        "delta_y": "垂直捲動增量。",
        "direction": "driver 期望方向而不是增量時的捲動方向。",
        "amount": "捲動量。",
        "text": "要輸入的文字（type_text）。",
        "key": "要按下的單一按鍵（press_key）。",
        "keys": "熱鍵組合，例如 ['alt', 'f4']。",
        "path": "執行檔路徑（launch_app）。",
        "name": "應用程式名稱（launch_app）。",
        "aumid": "封裝 Windows 應用程式的 application user model id（launch_app）。",
        "urls": "要開啟的網址，每個一個視窗（launch_app）。",
        "width": "視窗寬度（set_window_frame）。",
        "height": "視窗高度（set_window_frame）。",
        "delivery_mode": (
            "輸入投遞方式。保持 'background'（絕不搶焦點）；只有傳回 background_unavailable "
            "的單一動作才用 'foreground'。"
        ),
        "params": "具名參數未涵蓋的動作所用的 driver 原生欄位。",
    },
)

FR = ToolText(
    description=(
        "Agit sur le bureau hôte via le cua-driver local. Il agit sur la vraie machine où tourne "
        "l'agent, pas dans une sandbox. Actions : 'launch_app' (lancer une application Win32 par "
        "chemin/nom, une application empaquetée par aumid, ou des URL via urls), "
        "'click'/'double_click'/'right_click' (pid, window_id, puis element_token ou x/y), "
        "'drag', 'scroll', 'press_key', 'hotkey', 'type_text', 'set_window_frame', "
        "'invoke_menu', 'bring_to_front'. Règles : (1) appelez computer_observe "
        "get_window_state avant et après chaque action ; un token d'élément n'est valable que "
        "pour l'instantané qui l'a produit. (2) Préférez element_token à x/y : il passe par "
        "l'invocation d'accessibilité, sans déplacer le curseur ni changer le focus. (3) "
        "delivery_mode vaut 'background' par défaut et ne prend jamais la fenêtre d'avant-plan ; "
        "si un appel renvoie background_unavailable, réessayez uniquement cette action avec "
        "delivery_mode='foreground'. (4) Une action peut signaler un succès sans que l'interface "
        "ait changé (les applications UWP ignorent silencieusement les événements synthétiques, "
        "effect='unverifiable') : prenez un nouvel instantané avant de réessayer, sinon vous "
        "risquez de saisir ou cliquer deux fois. (5) Si l'appel renvoie stale_element_token, "
        "reprenez un instantané. Certaines actions acceptent via 'params' des champs natifs du "
        "driver qui ne sont pas listés ici. N'utilisez pas exec_command (Start-Process, "
        "cmd /c start, explorer.exe shell:...) pour lancer ou piloter une application graphique — "
        "ces méthodes volent le focus et contournent la gestion de l'entrée en arrière-plan du "
        "driver ; utilisez cet outil."
    ),
    parameters={
        "action": "L'action de bureau à exécuter.",
        "pid": "Identifiant de processus cible (issu de list_apps ou launch_app).",
        "window_id": "Handle de la fenêtre cible issu de list_windows (décimal ou hexadécimal préfixé par 0x).",
        "element_token": (
            "Token d'un contrôle du dernier instantané de get_window_state. Prioritaire sur les "
            "coordonnées ; il devient invalide après un nouvel instantané ou un changement "
            "d'interface."
        ),
        "x": "Coordonnée x dans la zone cliente (chemin par pixels).",
        "y": "Coordonnée y dans la zone cliente (chemin par pixels).",
        "from_x": "x du point de départ du glisser.",
        "from_y": "y du point de départ du glisser.",
        "to_x": "x du point d'arrivée du glisser.",
        "to_y": "y du point d'arrivée du glisser.",
        "delta_x": "Delta de défilement horizontal.",
        "delta_y": "Delta de défilement vertical.",
        "direction": "Direction de défilement quand le driver attend une direction et non un delta.",
        "amount": "Quantité de défilement.",
        "text": "Texte à saisir (type_text).",
        "key": "Touche unique à presser (press_key).",
        "keys": "Combinaison de touches, par exemple ['alt', 'f4'].",
        "path": "Chemin de l'exécutable (launch_app).",
        "name": "Nom de l'application (launch_app).",
        "aumid": "application user model id d'une application Windows empaquetée (launch_app).",
        "urls": "URL à ouvrir, une fenêtre par URL (launch_app).",
        "width": "Largeur de la fenêtre (set_window_frame).",
        "height": "Hauteur de la fenêtre (set_window_frame).",
        "delivery_mode": (
            "Mode de distribution de l'entrée. Gardez 'background' (ne prend jamais le focus) ; "
            "n'utilisez 'foreground' que pour l'action unique qui a renvoyé background_unavailable."
        ),
        "params": "Champs natifs du driver pour les actions non couvertes par les paramètres nommés.",
    },
)

DE = ToolText(
    description=(
        "Steuert den Host-Desktop über den lokalen cua-driver. Gewirkt wird auf der echten "
        "Maschine, auf der der Agent läuft, nicht in einer Sandbox. Aktionen: 'launch_app' "
        "(Win32-Anwendung über Pfad/Name starten, gepackte Anwendung über aumid, oder URLs über "
        "urls öffnen), 'click'/'double_click'/'right_click' (pid, window_id, dann element_token "
        "oder x/y), 'drag', 'scroll', 'press_key', 'hotkey', 'type_text', 'set_window_frame', "
        "'invoke_menu', 'bring_to_front'. Regeln: (1) vor und nach jeder Aktion computer_observe "
        "get_window_state aufrufen; ein Element-Token gilt nur für den Schnappschuss, der es "
        "erzeugt hat. (2) element_token statt x/y bevorzugen: es läuft über den "
        "Accessibility-Aufruf, verschiebt den Cursor nicht und ändert den Fokus nicht. (3) "
        "delivery_mode ist standardmäßig 'background' und stiehlt nie das Vordergrundfenster; "
        "meldet ein Aufruf background_unavailable, nur diese eine Aktion mit "
        "delivery_mode='foreground' wiederholen. (4) Eine Aktion kann Erfolg melden, ohne die "
        "Oberfläche zu ändern (UWP-Anwendungen ignorieren synthetische Ereignisse "
        "stillschweigend, effect='unverifiable'): vor dem Wiederholen einen neuen Schnappschuss "
        "machen, sonst wird doppelt getippt oder geklickt. (5) Meldet der Aufruf "
        "stale_element_token, einen neuen Schnappschuss machen. Manche Aktionen nehmen über "
        "'params' native Driver-Felder an, die hier nicht aufgeführt sind. GUI-Anwendungen nicht "
        "mit exec_command (Start-Process, cmd /c start, explorer.exe shell:...) starten oder "
        "bedienen — diese Wege stehlen den Fokus und umgehen die Hintergrundeingabe des Drivers; "
        "stattdessen dieses Werkzeug verwenden."
    ),
    parameters={
        "action": "Die auszuführende Desktop-Aktion.",
        "pid": "Prozess-ID des Ziels (aus list_apps oder launch_app).",
        "window_id": "Ziel-Fenster-Handle aus list_windows (dezimal oder hexadezimal mit 0x-Präfix).",
        "element_token": (
            "Token eines Steuerelements aus dem letzten get_window_state-Schnappschuss. Hat "
            "Vorrang vor Koordinaten; nach einem neuen Schnappschuss oder einer "
            "Oberflächenänderung wird es ungültig."
        ),
        "x": "x-Koordinate im Clientbereich (Pixel-Pfad).",
        "y": "y-Koordinate im Clientbereich (Pixel-Pfad).",
        "from_x": "Startpunkt x des Ziehens.",
        "from_y": "Startpunkt y des Ziehens.",
        "to_x": "Endpunkt x des Ziehens.",
        "to_y": "Endpunkt y des Ziehens.",
        "delta_x": "Horizontaler Scroll-Delta.",
        "delta_y": "Vertikaler Scroll-Delta.",
        "direction": "Scroll-Richtung, wenn der Driver eine Richtung statt eines Deltas erwartet.",
        "amount": "Scroll-Menge.",
        "text": "Der zu tippende Text (type_text).",
        "key": "Die einzelne Taste (press_key).",
        "keys": "Tastenkombination, z. B. ['alt', 'f4'].",
        "path": "Pfad der ausführbaren Datei (launch_app).",
        "name": "Anwendungsname (launch_app).",
        "aumid": "application user model id einer gepackten Windows-Anwendung (launch_app).",
        "urls": "Zu öffnende URLs, je eine pro Fenster (launch_app).",
        "width": "Fensterbreite (set_window_frame).",
        "height": "Fensterhöhe (set_window_frame).",
        "delivery_mode": (
            "Zustellart der Eingabe. Bei 'background' bleiben (stiehlt nie den Fokus); nur die "
            "eine Aktion mit background_unavailable mit 'foreground' wiederholen."
        ),
        "params": (
            "Native Driver-Felder für Aktionen, die von den benannten Parametern nicht abgedeckt "
            "werden."
        ),
    },
)

RU = ToolText(
    description=(
        "Управляет рабочим столом хоста через локальный cua-driver. Действует на реальной "
        "машине, где работает агент, а не в песочнице. Действия: 'launch_app' (запуск "
        "приложения Win32 по пути/имени, упакованного приложения по aumid или открытие URL через "
        "urls), 'click'/'double_click'/'right_click' (pid, window_id, затем element_token или "
        "x/y), 'drag', 'scroll', 'press_key', 'hotkey', 'type_text', 'set_window_frame', "
        "'invoke_menu', 'bring_to_front'. Правила: (1) перед каждым действием и после него "
        "вызывайте computer_observe get_window_state; токен элемента действителен только для "
        "снимка, который его создал. (2) Предпочитайте element_token вместо x/y: он идёт через "
        "вызов доступности, не двигая курсор и не меняя фокус. (3) delivery_mode по умолчанию "
        "'background' и никогда не захватывает активное окно; если вызов вернул "
        "background_unavailable, повторите только это действие с delivery_mode='foreground'. "
        "(4) Действие может сообщить об успехе, не изменив интерфейс (приложения UWP молча "
        "игнорируют синтетические события, effect='unverifiable'): перед повтором сделайте "
        "новый снимок, иначе ввод или клик задвоится. (5) Если вызов вернул stale_element_token, "
        "сделайте новый снимок. Некоторые действия принимают через 'params' нативные поля "
        "драйвера, не перечисленные здесь. Не используйте exec_command (Start-Process, "
        "cmd /c start, explorer.exe shell:...) для запуска или управления GUI-приложениями — "
        "такие способы забирают фокус и обходят фоновую обработку ввода драйвера; используйте "
        "этот инструмент."
    ),
    parameters={
        "action": "Какое действие на рабочем столе выполнить.",
        "pid": "Идентификатор целевого процесса (из list_apps или launch_app).",
        "window_id": (
            "Дескриптор целевого окна из list_windows (десятичный или шестнадцатеричный с "
            "префиксом 0x)."
        ),
        "element_token": (
            "Токен элемента управления из последнего снимка get_window_state. Приоритетнее "
            "координат; после нового снимка или изменения интерфейса он перестаёт действовать."
        ),
        "x": "Координата x в клиентской области (путь по пикселям).",
        "y": "Координата y в клиентской области (путь по пикселям).",
        "from_x": "x начала перетаскивания.",
        "from_y": "y начала перетаскивания.",
        "to_x": "x конца перетаскивания.",
        "to_y": "y конца перетаскивания.",
        "delta_x": "Приращение горизонтальной прокрутки.",
        "delta_y": "Приращение вертикальной прокрутки.",
        "direction": "Направление прокрутки, когда драйвер ждёт направление, а не приращение.",
        "amount": "Величина прокрутки.",
        "text": "Текст для ввода (type_text).",
        "key": "Одна клавиша для нажатия (press_key).",
        "keys": "Сочетание клавиш, например ['alt', 'f4'].",
        "path": "Путь к исполняемому файлу (launch_app).",
        "name": "Имя приложения (launch_app).",
        "aumid": "application user model id упакованного приложения Windows (launch_app).",
        "urls": "URL для открытия, каждое в своём окне (launch_app).",
        "width": "Ширина окна (set_window_frame).",
        "height": "Высота окна (set_window_frame).",
        "delivery_mode": (
            "Способ доставки ввода. Оставляйте 'background' (никогда не забирает фокус); "
            "'foreground' используйте только для того единственного действия, которое вернуло "
            "background_unavailable."
        ),
        "params": "Нативные поля драйвера для действий, не покрытых именованными параметрами.",
    },
)
