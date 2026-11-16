"""Display text for ``delete_file``, for the admin tool page.

The model always sees the English description and schema (``description.py``); this is
read by the admin page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "从工作空间里删除一个文件。路径以工作空间根目录为基准解析且不能越出；全局允许/拒绝"
        "策略叠加生效。只删单个普通文件 —— 目录会被拒绝，删整棵树请用 code_interpreter"
        "（例如 shutil.rmtree）；若文件应当保留只是清空，请用 write_file。删除本次任务没有"
        "完整读过的文件会被拒绝（先用 read_file 读，不带 'limit'）；读完之后又变过的文件同样"
        "会被拒绝，因此没见过的文件不会被误删。体积大到无法整读的文件是唯一例外：调用会执行，"
        "并在结果里标 'content_verified: false'。每次删除都由用户确认，在应用里该文件会出现在"
        "任务的改动列表中，可从那里恢复。"
    ),
    parameters={
        "file_path": "要删除的文件路径，相对于工作空间根目录。",
    },
)

ZH_TW = ToolText(
    description=(
        "從工作區刪除一個檔案。路徑以工作區根目錄為基準解析且不能越出；全域允許／拒絕策略"
        "疊加生效。只刪單一一般檔案 —— 目錄會被拒絕，刪整棵樹請用 code_interpreter"
        "（例如 shutil.rmtree）；若檔案該保留、只是要清空，請用 write_file。刪除本次任務沒有"
        "完整讀過的檔案會被拒絕（先用 read_file 讀，不帶 'limit'）；讀完之後又變過的檔案同樣"
        "會被拒絕，因此沒見過的檔案不會被誤刪。體積大到無法整讀的檔案是唯一例外：呼叫會執行，"
        "並在結果裡標 'content_verified: false'。每次刪除都由使用者確認，在應用裡該檔案會出現在"
        "任務的變更清單中，可從那裡還原。"
    ),
    parameters={
        "file_path": "要刪除的檔案路徑，相對於工作區根目錄。",
    },
)

FR = ToolText(
    description=(
        "Supprime un fichier de l'espace de travail. Les chemins sont résolus par rapport "
        "à la racine de l'espace de travail et ne peuvent pas en sortir ; la politique "
        "globale d'autorisation et de refus s'applique en plus. Seul un fichier ordinaire "
        "peut être supprimé : un dossier est refusé, utilisez code_interpreter (par "
        "exemple shutil.rmtree) pour une arborescence, et write_file si le fichier doit "
        "rester mais être vidé. Supprimer un fichier dont cette tâche n'a pas lu tout le "
        "contenu est refusé (lisez-le d'abord avec read_file, sans 'limit') ; un fichier "
        "modifié depuis sa lecture l'est aussi, donc un fichier jamais vu n'est pas "
        "détruit au hasard. Les fichiers trop volumineux pour être lus en entier sont la "
        "seule exception : l'appel s'exécute et renvoie 'content_verified: false'. Chaque "
        "suppression est confirmée par l'utilisateur, et dans l'application le fichier "
        "apparaît dans les modifications de la tâche, d'où il peut être restauré."
    ),
    parameters={
        "file_path": "Chemin du fichier à supprimer, relatif à la racine de l'espace de travail.",
    },
)

DE = ToolText(
    description=(
        "Löscht eine Datei aus dem Arbeitsbereich. Pfade werden gegen die Wurzel des "
        "Arbeitsbereichs aufgelöst und können sie nicht verlassen; die globale "
        "Erlauben-/Ablehnen-Richtlinie gilt zusätzlich. Nur eine einzelne reguläre Datei "
        "kann entfernt werden - ein Verzeichnis wird abgelehnt, für einen ganzen Baum "
        "code_interpreter verwenden (etwa shutil.rmtree); soll die Datei bleiben und nur "
        "geleert werden, write_file verwenden. Eine Datei zu löschen, deren gesamten Inhalt "
        "diese Aufgabe nicht gelesen hat, wird abgelehnt (zuerst mit read_file ohne 'limit' "
        "lesen); ebenso eine Datei, die sich seither geändert hat, sodass eine nie gesehene "
        "Datei nicht auf Verdacht zerstört wird. Dateien, die zu groß zum vollständigen "
        "Lesen sind, bilden die einzige Ausnahme: der Aufruf läuft und meldet "
        "'content_verified: false'. Jedes Löschen wird vom Benutzer bestätigt, und in der "
        "Anwendung erscheint die Datei in den Änderungen der Aufgabe und kann von dort "
        "wiederhergestellt werden."
    ),
    parameters={
        "file_path": "Pfad der zu löschenden Datei, relativ zur Wurzel des Arbeitsbereichs.",
    },
)

RU = ToolText(
    description=(
        "Удаляет файл из рабочей области. Пути разрешаются относительно корня рабочей "
        "области и не могут выйти за его пределы; глобальная политика разрешений и "
        "запретов действует дополнительно. Удалить можно только отдельный обычный файл: "
        "каталог отклоняется, для дерева используйте code_interpreter (например "
        "shutil.rmtree), а если файл должен остаться и лишь очиститься - write_file. "
        "Удаление файла, содержимое которого эта задача не прочитала целиком, "
        "отклоняется (сначала прочитайте его через read_file, без 'limit'); файл, "
        "изменившийся после чтения, тоже отклоняется, поэтому никогда не виденный файл "
        "не будет уничтожен наугад. Файлы, слишком большие для полного чтения, - "
        "единственное исключение: вызов выполняется и сообщает 'content_verified: false'. "
        "Каждое удаление подтверждает пользователь, и в приложении файл появляется в "
        "списке изменений задачи, откуда его можно восстановить."
    ),
    parameters={
        "file_path": "Путь к удаляемому файлу относительно корня рабочей области.",
    },
)
