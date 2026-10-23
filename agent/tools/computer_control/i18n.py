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
