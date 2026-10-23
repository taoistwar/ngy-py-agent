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
