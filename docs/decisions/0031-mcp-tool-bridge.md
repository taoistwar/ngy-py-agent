# ADR 0031: MCP 服务端的工具接进任务运行时

- 状态：已接受（Accepted）
- 日期：2026-11-17
- 相关：`agent/mcp/`（`stdio` / `session` / `bridge` / `live` / `names` / `prompt` / `probe`）、`agent/agent_loop/runtime.py`、`agent/agent_loop/loop.py`、`agent/tools/permissions.py`、`agent/tools/registry.py`、`web-admin/src/components/admin/toolMeta.js`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0012](0012-tool-result-budget.md)（结果预算）、[ADR 0024](0024-tool-denylist.md)（deny 名单）、[ADR 0030](0030-vault-http-tool.md)（新增权限种类的先例）

## 背景

MCP 市场存的是预设，智能体勾选后会把它写进自己的快照并随任务记录。但运行时从未读过这份配置：`ToolRegistry` 里只有 `agent/tools/catalog.py` 的 16 个内置工具，于是模型手上确实没有 MCP 工具，问它「你有哪些 MCP」只能回答「没有」——这不是模型不肯说，而是它的世界里真的没有。

集市页的连接测试（ADR 0030 之后新增的 `probe`）解决了「这条预设连得上吗、会提供什么」，但连上之后仍然没有东西去调用。两条路可选：

1. 只把已配置的服务端写进提示词，告诉模型「有这些 MCP，但还调不了」；
2. 把远端工具真正注册进运行时，让模型能调。

选 2。一个只能在提示词里出现的工具，与没有这个工具的区别只是模型说话更好听；而「能连上却调不了」正是最初那次「没有 MCP」的错误答案。

## 决策

### D1. 每个远端工具是一个普通注册工具，名字带服务端

- 名字是 `mcp__<服务端>__<工具名>`：前缀保证永不与内置工具撞名，中间段是权限门要用的身份。
- 两端都是自由文本（市场里的名字、服务端声明的工具名），而函数名受限于 `[A-Za-z0-9_-]+` 且不超过 64 字符：`names.tool_name` 负责清洗、截断（优先截工具名，服务端段保留），撞名加 `_2`，绝不静默覆盖。
- 注册发生在 `registry.get_tool_schemas()` **之前**：schema 在循环开始时就固定下来，晚注册的工具模型永远看不到。
- 描述保留服务端自己的说明，并追加一行 `Provided by MCP server <名字>`，这样「有哪些 MCP」可以从工具列表本身回答。

### D2. 权限种类是 `mcp`，目标是服务端

- `PERMISSION_MCP` 而不是复用 `exec`：这里被批准的不是一条命令行，而是「这个服务端的工具可以在本任务里跑」。确认框摘要形如 `Run echo on MCP server filesystem`，`details` 有 `server` / `tool` / `arguments`（截断）。
- 目标从工具名反解（`names.server_of`），不是从参数里取：参数属于远端工具，放不下我们的元信息，而且改参数也改不了被批准的对象。
- 规则键本来就含工具名，所以「本任务允许」只覆盖这一个远端工具；「一直允许」是「这个工具 + 这个服务端」的组合。批准一次 `echo` 不是对同一台服务器上写文件工具的批准。
- `auto_approve` 照常生效（不设 `always_confirm`）：它表示「这次任务别问我」，而服务端本身已经被智能体配置批准过了。这一点与 ADR 0030 的 `vault` 不同——那里每次都有可能把长期凭证发到一个新主机。

### D3. 生命周期是任务级，关停点与后台进程一致

- `live.start_for_task(task_id, mcp_servers)` 在 `_build_runtime` 里开服务端；`live` 按 task_id 记桥。
- 关停在 `_reaps_task_sessions` 的 `finally` 里调用，与 `process_store.stop_task(task_id)` 同一处、同一理由：循环有多个出口（最终答案、步数上限、停止请求），只有装饰器的 `finally` 能覆盖全部。
- 空 task_id（CLI）也被当成一个键，所以 REPL 不会每轮攒一套服务端进程。
- 不跨任务复用进程：一个任务一次连接，用完即关。复用会把「上一个任务的远端状态」带进下一个任务，收益（省 1–2 秒）不值得。

### D4. 一个服务端起不来不能拖垮任务

- 连接失败、超时、协议错误都记进 `McpServerStatus`，该服务端的工具缺席，其余服务端与内置工具照常。
- `registry.mcp_status` 进入「Starting ReAct loop」事件，同时由 `prompt.append_server_status` 追加到系统提示词的 `## MCP servers` 一节：连上几个工具、或者为什么没连上。没有这一段，「连不上」和「没配置」在模型看来完全一样，它会给出同一个错误答案。
- `sse` 暂不支持：探测会直说，运行时记为未连接。宁可少一个传输方式，也不要一个「看起来支持」的半实现。

### D5. 远端结果怎么变成模型能读的文本

- `content` 里的 `text` 直通；`resource` 保留 URI（有 `text` 就带上）。
- `image` 块把字节写进临时目录并作为 `ToolImage` 交给 `agent.vision`，与 `computer_observe` 走同一条视觉通道：内容寻址（重复的截图复用同一个文件）、png/jpeg/webp/gif、8 MB 以内、base64 合法才写。文本里同时留一行 `[image image/png]`——看不见图的模型也得知道"有张截图"，而 `supports_image_input` 为假的模型只拿得到这一行。
- `audio` 只留一行标记：这个仓库没有音频输入的通道，造一个没人消费的 attachment 没有意义。
- 写不进文件、base64 坏了、格式不认识、超过上限：都不让这次调用失败，只是没有 attachment。截图丢了一张不值得让模型的真正答案一起丢。
- 没有可用内容时退回 `structuredContent` 的 JSON；两者都没有则明说 `(the MCP tool returned no content)`。
- 服务端回 `isError: true` 抛 `McpToolError`：这是一次失败的调用，那一步应当标记为失败，模型读到「Error: <服务端原话>」而不是把它当成功结果继续推理。传输层失败（进程退出、超时、非 JSON）沿用 `McpSessionError` / `McpProtocolError`。
- 结果原样交给 `apply_result_budget`，与内置工具同一套预算：远端工具没有资格绕过它。

### D6. 客户端仍然手写，不引 SDK

- 与 `computer_driver` 一致：一次对话就是一次子进程调用（JSON-RPC 2.0 行分隔），省一个依赖，也便于自己处理 Windows 的 `.cmd` shim。
- 管道分两种编码解码：stdout 按规范 UTF-8，stderr 用控制台代码页（中文 Windows 是 GBK）。统一 UTF-8 会把「'npx' 不是内部或外部命令」变成乱码——那恰好是最常见的失败。
- `target` 写绝对路径时把它所在目录放到子进程 `PATH` 最前（`_child_env`），因为 `npx.cmd` 会按名字调 `node`。
- 关停走 `taskkill /F /T`（Windows）或 `killpg`（POSIX）：`npx` 后面还有 `node`。

### D7. 明确不做

- 不做工具级白名单：勾选一个服务端就是授权它的全部工具，逐工具勾选会让配置界面爆炸，而权限门已经逐次问过。
- 不把 MCP 工具加进 `agent/tools/catalog.py`，也不进 `/api/tools`：它们是每次任务动态注册的，没有稳定的「工具清单」可言。
- 不做音频输入、不做 `sse`、不做跨任务连接池。

## 后果

- 「你有哪些 MCP」现在有真实答案：`mcp__` 前缀的工具出现在模型可见工具集里，系统提示词里还有一份服务端清单（含未连上的原因）。
- 工具数量可能陡增（`@modelcontextprotocol/server-everything` 一次给出 16 个），schema 与工具列表都会变长；这是勾选该服务端的直接代价，由用户决定。
- 每个任务开始会多出连接时间（本地 `npx` 约 2 秒；冷启动要下载包时更久，上限 60 秒/请求）。连不上不会失败，只是少工具。
- 远端截图能进模型了：`image` 块落进系统临时目录的 `ngy-mcp-images/`，由 `agent.vision` 决定是否随下一条消息发出；没有图片输入的模型仍然只看到 `[image image/png]`，行为与之前一致。
- 权限门新增 `mcp` 种类，但界面不加新标签：确认框显示的是后端给的 `summary` 与 `details`（且刻意不显示 `kind`），而「工具管理」页只列内置工具，所以没有地方需要一个 `mcp` 的中文名。`docs/dev.md`、`docs/guide/api-agents.md`、`docs/guide/api-tools.md` 同步。
- 测试覆盖：`test/agent/mcp/mcp_bridge_test.py`（命名、注册、调用、远端失败、坏预设、撞名、关停、任务级开关）、`test/agent_loop_mcp_test.py`（注册进 registry 与 schema、坏预设不失败、teardown 关停）、`test/tools/permissions_test.py`（目标=服务端、session 粒度、auto_approve、deny_all）、`test/agent/mcp/mcp_prompt_test.py`。
