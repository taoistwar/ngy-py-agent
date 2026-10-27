"""Chinese display text for ``computer_observe``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "通过本机 cua-driver 观察宿主桌面。读取的是 agent 运行的真实机器，不是沙箱。动作："
        "'list_apps'（运行中的应用及 pid）、'list_windows'（某个 pid 的窗口，需要 pid）、"
        "'get_window_state'（一个窗口的无障碍树与截图，需要 pid 和 window_id）、"
        "'get_desktop_state'（整个桌面）、'get_browser_state'（浏览器窗口的页面级状态）。"
        "每次 computer_control 动作前后都要调用 'get_window_state'：元素 token 只对产生它的"
        "快照有效，而且动作可能在界面没变的情况下报告成功。窗口用 pid + window_id 定位，"
        "绝不要用标题。文本结果是按每行一个控件渲染的无障碍树；截图会写入 PNG 文件并在结果里"
        "报告路径，配置的模型接受图片输入时也会附到下一轮。"
    ),
    parameters={
        "action": "要执行哪种观察。",
        "pid": "目标应用的进程 id（来自 list_apps 或 launch_app）。",
        "window_id": (
            "来自 list_windows 的窗口句柄，不是窗口标题。十进制或 0x 前缀的十六进制都接受。"
        ),
        "screenshot": (
            "在本次运行的临时输出目录旁写一张 PNG 截图并报告路径。默认 true；"
            "无论是否截图都会返回无障碍树。"
        ),
    },
)

ZH_TW = ToolText(
    description=(
        "透過本機 cua-driver 觀察宿主桌面。讀取的是 agent 執行的真實機器，不是沙箱。動作："
        "'list_apps'（執行中的應用程式及 pid）、'list_windows'（某個 pid 的視窗，需要 pid）、"
        "'get_window_state'（一個視窗的無障礙樹與截圖，需要 pid 和 window_id）、"
        "'get_desktop_state'（整個桌面）、'get_browser_state'（瀏覽器視窗的頁面層級狀態）。"
        "每次 computer_control 動作前後都要呼叫 'get_window_state'：元素 token 只對產生它的"
        "快照有效，而且動作可能在介面沒變的情況下回報成功。視窗用 pid + window_id 定位，"
        "絕不要用標題。文字結果是依每行一個控制項描繪的無障礙樹；截圖會寫入 PNG 檔案並在結果裡"
        "回報路徑，設定的模型接受圖片輸入時也會附到下一輪。"
    ),
    parameters={
        "action": "要執行哪種觀察。",
        "pid": "目標應用程式的行程 id（來自 list_apps 或 launch_app）。",
        "window_id": (
            "來自 list_windows 的視窗控制代碼，不是視窗標題。十進位或 0x 前綴的十六進位都接受。"
        ),
        "screenshot": (
            "在本次執行的暫存輸出目錄旁寫一張 PNG 截圖並回報路徑。預設 true；"
            "無論是否截圖都會傳回無障礙樹。"
        ),
    },
)

FR = ToolText(
    description=(
        "Observe le bureau hôte via le cua-driver local. Il lit la vraie machine sur laquelle "
        "tourne l'agent, pas une sandbox. Actions : 'list_apps' (applications en cours et leur "
        "pid), 'list_windows' (fenêtres d'un pid, le pid est requis), 'get_window_state' (arbre "
        "d'accessibilité et capture d'une fenêtre, pid et window_id requis), 'get_desktop_state' "
        "(tout le bureau), 'get_browser_state' (état au niveau de la page pour une fenêtre de "
        "navigateur). Appelez 'get_window_state' avant et après chaque action computer_control : "
        "un token d'élément n'est valable que pour l'instantané qui l'a produit, et une action "
        "peut signaler un succès sans que l'interface ait changé. Une fenêtre se désigne par pid "
        "+ window_id, jamais par son titre. Le résultat texte est l'arbre d'accessibilité rendu à "
        "raison d'un contrôle par ligne ; la capture est écrite dans un fichier PNG dont le "
        "chemin est renvoyé, et elle est jointe au tour suivant quand le modèle configuré accepte "
        "les images."
    ),
    parameters={
        "action": "Quelle observation effectuer.",
        "pid": "Identifiant de processus de l'application cible (issu de list_apps ou launch_app).",
        "window_id": (
            "Handle de fenêtre issu de list_windows, pas le titre de la fenêtre. Décimal ou "
            "hexadécimal préfixé par 0x."
        ),
        "screenshot": (
            "Écrire une capture PNG à côté du dossier de sortie temporaire de cette exécution et "
            "en renvoyer le chemin. true par défaut ; l'arbre d'accessibilité est renvoyé dans "
            "tous les cas."
        ),
    },
)

DE = ToolText(
    description=(
        "Beobachtet den Host-Desktop über den lokalen cua-driver. Gelesen wird die echte Maschine, "
        "auf der der Agent läuft, keine Sandbox. Aktionen: 'list_apps' (laufende Anwendungen mit "
        "pid), 'list_windows' (Fenster einer pid, pid erforderlich), 'get_window_state' "
        "(Accessibility-Baum und Screenshot eines Fensters, pid und window_id erforderlich), "
        "'get_desktop_state' (gesamter Desktop), 'get_browser_state' (seitenbezogener Zustand "
        "eines Browserfensters). Vor und nach jeder computer_control-Aktion 'get_window_state' "
        "aufrufen: ein Element-Token gilt nur für den Schnappschuss, der es erzeugt hat, und eine "
        "Aktion kann Erfolg melden, ohne die Oberfläche zu ändern. Fenster werden über pid + "
        "window_id adressiert, nie über den Titel. Das Textergebnis ist der Accessibility-Baum mit "
        "einem Steuerelement pro Zeile; der Screenshot wird als PNG-Datei geschrieben, ihr Pfad "
        "wird zurückgegeben, und er wird der nächsten Runde beigelegt, wenn das konfigurierte "
        "Modell Bildeingaben akzeptiert."
    ),
    parameters={
        "action": "Welche Beobachtung ausgeführt wird.",
        "pid": "Prozess-ID der Zielanwendung (aus list_apps oder launch_app).",
        "window_id": (
            "Fenster-Handle aus list_windows, nicht der Fenstertitel. Dezimal oder hexadezimal mit "
            "0x-Präfix."
        ),
        "screenshot": (
            "Eine PNG-Aufnahme neben dem temporären Ausgabeordner dieses Laufs schreiben und den "
            "Pfad melden. Standard true; der Accessibility-Baum kommt unabhängig davon zurück."
        ),
    },
)

RU = ToolText(
    description=(
        "Наблюдает за рабочим столом хоста через локальный cua-driver. Читается реальная "
        "машина, на которой работает агент, а не песочница. Действия: 'list_apps' (запущенные "
        "приложения и их pid), 'list_windows' (окна процесса pid, нужен pid), "
        "'get_window_state' (дерево доступности и снимок окна, нужны pid и window_id), "
        "'get_desktop_state' (весь рабочий стол), 'get_browser_state' (состояние на уровне "
        "страницы для окна браузера). Перед каждым действием computer_control и после него "
        "вызывайте 'get_window_state': токен элемента действителен только для снимка, который "
        "его создал, а действие может сообщить об успехе, не изменив интерфейс. Окно задаётся "
        "парой pid + window_id, никогда по заголовку. Текстовый результат — дерево доступности, "
        "по одному элементу на строку; снимок записывается в PNG-файл, его путь возвращается, а "
        "при следующем раунде файл прикладывается, если настроенная модель принимает "
        "изображения."
    ),
    parameters={
        "action": "Какое наблюдение выполнить.",
        "pid": "Идентификатор процесса целевого приложения (из list_apps или launch_app).",
        "window_id": (
            "Дескриптор окна из list_windows, а не заголовок окна. Принимается десятичный или "
            "шестнадцатеричный с префиксом 0x."
        ),
        "screenshot": (
            "Записать PNG-снимок рядом с временной папкой вывода этого запуска и вернуть путь. "
            "По умолчанию true; дерево доступности возвращается в любом случае."
        ),
    },
)
