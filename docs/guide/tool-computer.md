# 工具：`computer_observe` / `computer_control`（宿主桌面操作）

这两个工具通过本机的 [cua-driver](https://cua.ai/docs/cua-driver) 操作**宿主机**的桌面应用，不是沙箱。

前提：

- 安装 driver（Windows：`irm https://cua.ai/driver/install.ps1 | iex`，首次运行可能被 SmartScreen 拦一次）；
- 必须在**交互式会话**（Session 1+）中运行，SSH / Session 0 里 UIA 与截图不可用；
- `cua-driver doctor` 显示 `SessionId >= 1`，`cua-driver autostart status` 为 `registered (running)`；
- 二进制不在 PATH 时，用 `CUA_DRIVER_BIN` 指定绝对路径。

```powershell
cua-driver doctor                       # 版本、SessionId、UIA/AppX 可达性
cua-driver autostart enable             # 注册交互式登录时启动的守护进程
cua-driver list-tools                   # 当前版本实际暴露的工具
cua-driver describe get_window_state    # 核对参数名（尤其 screenshot_out_file）
'{"pid":6004}' | cua-driver list_windows
```

| 工具 | 动作 | 权限 |
| --- | --- | --- |
| `computer_observe` | `list_apps`、`list_windows`（需 `pid`）、`get_window_state`（需 `pid` + `window_id`）、`get_desktop_state`、`get_browser_state` | 不询问，但每次调用发 `computer` 事件 |
| `computer_control` | `launch_app`、`click` / `double_click` / `right_click`、`drag`、`scroll`、`press_key`、`hotkey`、`type_text`、`set_window_frame`、`invoke_menu`、`bring_to_front` | `computer` 类型，可选"允许一次 / 本任务内允许"，**没有"始终允许"** |

使用约定（也写进了工具描述）：

1. 动作前后都要 `get_window_state`；`element_token` 只对产生它的快照有效。
2. 点击优先用 `element_token`，其次才是 `x` / `y`。
3. `delivery_mode` 默认 `background`（不抢前台）；只有收到 `background_unavailable` 时，才对**该次动作**改用 `foreground`。
4. `effect=unverifiable` 时要先重新快照再重试，否则可能重复输入。
5. 不要用 `exec_command` 的 `Start-Process` / `cmd /c start` / `shell:` 启动或驱动 GUI。

结果：

- 文本结果是 UIA 树的逐控件渲染（role / name / token / value / bounds），超出预算时只给预览 + 落盘路径；
- 截图写到 `<临时目录>/ngy-py-agent/output/<工作区>/<会话>/computer/*.png`，路径在结果里；
- 模型配置里勾选 **图片输入（Image input）** 后，截图会作为下一条 `user` 消息的 `image_url`（base64 data URL）附加到下一轮请求，模型可以真正看到窗口；未勾选或 provider 不是 OpenAI 兼容 wire format 时只保留路径；
- 单张图片超过 `TOOL_IMAGE_MAX_BYTES`（默认 8 MiB）会被跳过，不影响本次任务；
- 细节与取舍见 [ADR 0011](../decisions/0011-computer-use.md)。
