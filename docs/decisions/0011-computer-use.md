# ADR 0011: 宿主桌面操作（cua-driver）

- 状态：已接受（Accepted）
- 日期：2026-10-19
- 相关：`agent/tools/computer_driver.py`、`agent/tools/computer_state.py`、`agent/tools/computer_observe/`、`agent/tools/computer_control/`、`agent/tools/permissions.py`、`agent/models.py`、`agent/tools/catalog.py`、`web-admin/src/components/PermissionPrompt.jsx`
- 前置：[ADR 0005](0005-exec-tool.md)、[ADR 0006](0006-tool-permission-confirmation.md)

## 背景

需求是让 agent **直接操作宿主机**（不是容器、不是沙箱）：打开应用、点击、输入，并在界面上完成任务。

`cua-driver` 是这类操作的本机入口：`cua-driver <tool>` 用 JSON over stdin 调用，工具名是 snake_case（`list_apps` / `list_windows` / `get_window_state` / `click` / `type_text` / `launch_app` …），另有 `cua-driver mcp` 的 stdio MCP 端点。它要求运行在**交互式会话（Session 1+）**；Session 0 里 UIA、截图与应用激活全部不可用。

本仓库的既有约束决定了方案形态：

1. 权限门禁按**工具**生效（`ToolSpec.permission`），不是按 action。
2. 工具只能返回文本给模型；`provider.py` 没有 image content，`screenshot` 对模型不可见。
3. Windows 宿主上没有 Lume，也没有可用的本地 gVisor 沙箱，所以 `cua-driver` 是唯一可行路径。
4. 仓库里已有 MCP 集市存储，但没有 MCP 客户端；为了这一步去实现完整协议不划算。

## 决策

### D1. CLI 桥 + 常驻 daemon，先不写 MCP 客户端

工具通过 `subprocess` 调 `cua-driver <tool>`，JSON 从 stdin 进入。理由：

- driver 的 CLI 本身就是给一次性调用设计的，多步流程用同一个 `session` 标签，快照缓存（`element_token`）由 daemon 保持。
- 出问题时可以在终端复现同一条命令，调试成本远低于一条 MCP 会话。
- 协议实现（发现、版本协商、重连、图片 content）在 P1 没有收益。

`session` 取 `task_id`（无任务时用 `ngy-default`），随任务结束丢弃：同一任务内的观察与操作共享快照，不同任务之间不共享。

未来若接 MCP，只替换 `computer_driver.call_tool`，工具面对模型不变。

### D2. 观察与操作拆成两个工具

`computer_observe`（`list_apps` / `list_windows` / `get_window_state` / `get_desktop_state` / `get_browser_state`）声明 `permission=none`；`computer_control` 声明新类型 `computer`。

如果合成一个工具，每次观察都要弹确认框，agent 会被自己的权限门禁卡死。拆分后观察仍然发 `computer` 事件，可审计，但不阻塞。

### D3. 新权限类型，且不提供 `always`

- `PERMISSION_COMPUTER = "computer"`，与 `exec` 分开：对话框需要说清"在哪个窗口上做什么"，UI 也需要区分"点了窗口"和"跑了命令"。
- `computer_control` 的 `scopes=(once, session)`：桌面控制不值得有一条跨任务、跨重启的永久许可。
- 规则目标（`_target`）取 `action + pid + window_id`；`launch_app` 取 app 标识（`aumid` / `path` / `name`）。"允许在这个窗口里点击"是有用的粒度，按像素或按元素记规则则永远不会再次命中。
- 对话框的 `preview` 由 `computer_control/preview.py` 提供，只回显参数，不碰 driver。

### D4. 快照压成文本，超预算落盘；截图按模型能力进入上下文

- `get_window_state` 的 UIA 树按一行一个控件渲染（role / name / token / value / bounds / 状态），节点上限 400，再走 `token_budget`。
- 超出预算或节点被截断时，完整 JSON 与完整文本写入本次运行的 scratch 目录（`output_store`），模型拿到预览 + 路径，和 `exec_command` 的处理一致。
- 截图由 driver 写到 `<output>/computer/*.png`。工具把它放进 `ToolOutcome.images`；是否变成模型输入由 `agent/vision.py` 决定（见 D7），因此同一个工具在纯文本模型和视觉模型上都能工作。

### D5. driver 的错误码转成下一步指令

`background_unavailable` → "只把这一次动作改成 `foreground`"；`stale_element_token` → "重新 `get_window_state`"；`effect=unverifiable` / `route=synthetic_events` → "先重新快照再重试"。这些提示写在 `computer_driver` 与 `computer_control/tool.py` 里，因为它们决定模型下一步怎么做。

同理，三条 driver 不变量写进工具描述而不是靠模型自觉：动作前后快照、优先 `element_token`、默认 `background`。另外明确禁止用 `exec_command`（`Start-Process` / `cmd /c start` / `shell:`）启动或驱动 GUI：那些路径会抢焦点，绕过 background 输入处理。

### D6. 本次不做

- 自动在动作前后抓快照：会让每个动作多一次 driver 往返，且掩盖 `unverifiable`；先由描述约束模型。
- MCP 传输、浏览器专用流程、`invoke_menu` 的强类型参数：先留 `params` 逃生口。

### D7. 截图以“工具结果之后的 user 消息”进入模型上下文

OpenAI 兼容接口的 `tool` 消息只接受字符串，把 `image_url` 塞进 tool content 会被严格实现拒绝。因此 `agent_loop` 在一组工具消息之后追加一条 `user` 消息，内容是 text + `image_url`（base64 data URL），一次附加本步所有截图。

- 触发条件是**两个开关同时成立**：模型配置的 `supports_image_input`（Web Admin → 模型 → 图片输入）和 provider 的 `wire_compatible_with_openai`。前者是运营者对模型的声明，后者是 `agent/vision.py` 自己的协议限制；任一不满足就不发图片消息，工具文本里仍有路径。
- 代价是截图与具体 `tool_call_id` 不是严格绑定，而是在消息文本里带工具名和文件路径做关联；一批工具调用只有一条图片消息。
- 单张超过 `TOOL_IMAGE_MAX_BYTES`（默认 8 MiB）或文件缺失/不可读时跳过该张图，不失败整次请求。
- Anthropic / Gemini 的 wire 转换尚未支持图片；它们会走"只保留路径"的分支，等有需求再补。

## 后果

- 新增 2 个工具、1 个权限类型、1 个事件类别；`catalog_test.py` 的顺序需要同步（已同步）。
- 运行前提变成硬要求：安装 `cua-driver`、在交互式会话中启动、`cua-driver doctor` 显示 `SessionId >= 1`。`CUA_DRIVER_BIN` 可覆盖二进制路径。
- 失败会以 `ToolOutcome(success=False)` 回到模型（不是异常），与 `exec_command` 的 `ExecError` 处理一致，任务不会因为 driver 缺失而崩掉。
- 这是**协作式确认**，不是安全边界：一次放行之后，`computer_control` 能在宿主机做任何事。P1 没有做动作回放/撤销。
- 截图文件不会自动清理，跟随 `output_store` 的 scratch 目录策略。
- 视觉模型每一步可能收到两张截图（动作前后各一张），上下文增长比纯文本任务快；是否只保留最近一张属于后续优化，当前不做隐式裁剪。

## 备选

- **MCP 客户端**：通用性最好，但要先实现协议层；推迟到有第二个 MCP server 需求时。
- **Agent-as-tool**：把整段桌面任务交给子 agent，上下文干净，但过程黑盒、调试困难。
- **cua-sandbox**：隔离性最好，但解决的是"安全执行"，不是"操作宿主机"。
