# 用户指南

- 开发者请先阅读 [docs/dev.md](dev.md)。

## 运行方式

只剩两个入口：`--web`（管理界面 + API）和 `--interactive`（命令行多轮对话）。单次运行（`--query`）已移除——一次性任务走 Web Admin 的 `POST /api/tasks` 或在界面里提交。

### 交互模式

```bash
uv run python main.py --interactive
uv run python main.py --interactive --trace
```

### 交互模式指定 Provider 与步数

```bash
uv run python main.py --provider openai-compatible --interactive
uv run python main.py --provider openai --interactive
uv run python main.py --provider anthropic --interactive
uv run python main.py --provider anthropic-compatible --interactive
uv run python main.py --provider openai-compatible --steps 4 --interactive
```

说明：`openai-compatible` 会走 OpenAI 兼容接口；不带 `--provider` 时使用环境变量里的默认值。Web Admin 里的 provider / model 来自数据库，与这几个命令行参数无关。

## 可观测（Tracing）

默认关闭，行为与原来完全一致。需要看一次执行到底走了哪几步时再打开：

```bash
# 临时开一次，输出到控制台
OTEL_TRACING_ENABLED=true OTEL_TRACES_EXPORTER=console uv run python main.py --interactive
```

长期开启就写进 `.env`（字段见 `.env.example`）：

```dotenv
OTEL_TRACING_ENABLED=true
OTEL_TRACES_EXPORTER=jsonl
OTEL_TRACES_JSONL_PATH=data/traces/spans.jsonl
```

`data/traces/` 已在 `.gitignore` 中，属于本机运行时产物。

### 一次任务长什么样

一条 trace 覆盖 `HTTP 请求 → 任务 → 每个 ReAct 步骤 → 模型请求 / 工具调用`：

| span | 何时产生 | 关键属性 |
| --- | --- | --- |
| `POST /api/tasks`（或任意接口） | 每个 HTTP 请求 | `http.method`、`http.route` |
| `task` | 每个任务（CLI 单次运行也有） | `task.id`、`task.mode`、`react.max_steps` |
| `react.step` | 每一轮循环 | `react.step`、`react.max_steps` |
| `chat <模型名>` | 每次模型请求 | `gen_ai.system`、`gen_ai.request.model`、`gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`、`gen_ai.response.finish_reasons` |
| `execute_tool <工具名>` | 每次工具调用 | `gen_ai.tool.name`、`gen_ai.tool.call.arguments`（已脱敏、已截断） |

模型请求失败或工具抛异常时，对应 span 的状态是 `ERROR`，异常摘要写在 `status.description` 里；工具异常仍然照旧回给模型（不会因为埋点改变行为）。

### 从任务到 trace

事件流（Web Admin 的任务详情）没有变化，只是每条事件的 `data` 在 tracing 开启时多了两个键：

- `trace_id`：整条链路的标识；
- `span_id`：这条事件所属 span。

拿任务详情里 `Start task execution` 事件的 `data.trace_id`，就能把同一次执行的全部 span 捞出来：

```bash
# Linux / macOS / Git Bash
grep '"trace_id": "153f3acc75b230d58bff65dc2357d203"' data/traces/spans.jsonl

# PowerShell
Select-String -Path data/traces/spans.jsonl -Pattern '"trace_id": "153f3acc75b230d58bff65dc2357d203"'
```

每一行是一条完整 JSON，字段固定：

```json
{
  "trace_id": "153f3acc...",
  "span_id": "c7202dea...",
  "parent_span_id": "87fa7bc3...",
  "name": "chat qwen3:0.6b",
  "kind": "CLIENT",
  "start_time": 1792726072405,
  "end_time": 1792726086102,
  "start_time_ns": 1792726072405327100,
  "end_time_ns": 1792726086102397800,
  "started_at": "2026-10-23T03:27:52.405327+00:00",
  "duration_ms": 13697.071,
  "status": {"code": "ERROR", "description": "LLMCallError: ..."},
  "attributes": {"gen_ai.system": "openai", "gen_ai.request.model": "qwen3:0.6b"}
}
```

`parent_span_id` 为空的是根 span；按它把行拼起来就是调用树。写入采用批量刷盘，进程正常退出时会把剩余 span 落盘。

## Web Admin 管理中心

```bash
uv run python main.py --web
```

启动后访问：

```text
http://127.0.0.1:8001
```

界面右上角可切换「浅色 / 深色」皮肤，选择会保存在浏览器本地；首次打开时跟随系统配色。

### 参数说明（关键）

```text
--web
--host HOST          监听地址（默认 127.0.0.1）
--port PORT          监听端口（默认 8001）
--reload             运行时热重载
--interactive        命令行多轮模式
--provider PROVIDER  交互模式使用的 provider
--steps N            交互模式的 ReAct 步数上限
--quiet              交互模式不打印模型回答
--trace              交互模式打印思考与工具调用细节
```

## API 说明

### 任务管理

- `POST /api/tasks`：创建任务，返回 `task_id`。
  - 请求带 `session_id` 时，该会话中**已成功完成**的任务会作为对话上下文注入：每个任务是一轮 `user`（原始 `query`）+ `assistant`（任务结果），新任务接着这些 messages 继续，因此“给它加个测试”这类追问能指向前一个任务做的事。
  - 未完成、失败、已停止的任务不算上下文；上下文有预算（最多 40 条消息、24000 字符，单条消息截断到 8000 字符），超出时整轮丢弃最旧的轮次，保留最近的对话。
- `GET /api/tasks`：查询任务列表。
- `GET /api/tasks/{task_id}`：查询单个任务详情。
- `GET /api/tasks/{task_id}/events`：分页查询任务事件。
  - `offset`：起始偏移（默认 `0`）
  - `limit`：每页数量（1-100，默认 `30`）
- `GET /api/tasks/{task_id}/events/stream`：SSE 事件流。
- `GET /api/tasks/{task_id}/events/ws`：WebSocket 事件流。
  - `since`：按 `event_id` 增量拉取
  - `heartbeat`：心跳间隔（秒）
- `POST /api/tasks/{task_id}/stop`：请求停止（见下面「停止与撤销」）。
- `GET /api/tasks/{task_id}/changes`：这个任务改过哪些文件（`status` + 增删行数 + `conflict`）。`conflict: true` 表示任务之后该文件又被改过，撤销会覆盖别人的改动，因此不可撤销；`available: false` 时 `reason` 说明为什么不能撤销。
- `GET /api/tasks/{task_id}/changes/diff?path=`：单个文件的补丁，按需取。
- `POST /api/tasks/{task_id}/revert`：撤销改动。body 可带 `paths`（省略 = 全部）与 `force`（覆盖任务之后被改过的文件），返回逐文件的 `restored` / `conflicts` / `skipped`。
- `GET /api/healthz`：服务健康检查。

### 停止与撤销

**停止**是协作式中断，生效点在 step 边界、每个工具调用之间，以及阻塞等待内部（0.25 秒轮询一次）。所以正在跑的前台 `exec_command`、`write_stdin` 的等待也会被打断，不需要等命令自己的 `timeout`。[ADR 0019](decisions/0019-cancel-interrupts-running-work.md) 里有完整的边界说明：能打断的是**等待**，不是计算——进程内 `exec()` 的死循环和正在飞的模型请求仍会跑完。

**撤销**把任务改过的文件恢复到它第一次改动之前。范围覆盖文件工具、`exec_command` / `write_stdin` 和 `code_interpreter`；`computer_control` 操作的宿主桌面**不在**范围内。

- 判据是"当前内容仍等于任务留下的内容"。任务之后被人改过的文件会报为 **conflict 并跳过**，其余文件照常回退；确认要覆盖就带 `force`。
- 任务详情的结果区有「查看变更」入口：列出每个文件的增删行数，可展开单个文件的补丁；被之后改动过的文件标为冲突，撤销按钮禁用（服务端的 `conflict` 标记，见上）。
- 逐文件进行，不是全有全无。
- 只有**全部**回退成功时任务才变成 `reverted`，并且不再进入后续会话的对话上下文（它的改动已经不在了）。

### 断点续跑（进程重启后）

任务的执行线程跟着进程一起消失，但数据库里的行还写着 `running`。下次启动 Web 服务（`--web`）时，启动钩子会扫描这类任务并接着跑：

- **恢复对话**：从事件日志重建消息。最后一次 `LLM request` 的 `messages` 就是当时发给模型的完整对话（历史、压缩、截图都已经在里面），其后已记录的模型回答和工具结果按顺序补回。
- **不重复执行**：日志里已有 `tool_result` 的调用直接复用结果，工具**不会再跑一次**；只有调用事件、没有结果事件的调用（进程正好死在工具执行中间）不会被重放，而是变成一条「结果未知，先确认现状再决定是否重做」的 tool 消息交给模型判断。
- **不重复收尾**：日志里已经有最终结论时（`Task finished` / `ReAct finished` / 模型最后一条不带工具调用的回答），只补齐任务状态，不重新调用模型。
- **步数沿用同一个预算**：续跑从停下的那一步继续编号，`max_steps` 不会被重置。
- 每次续跑会写一条 `Task resumed after restart` 事件，记录恢复模式、起始 step、复用了多少条工具结果、有多少次调用结果未知。

无法续跑时任务会被标记为 `failed`，并写入 `Task recovery failed` 事件说明原因（没有可重建的对话、绑定的模型已被删除等）。同一个任务在**没有进展**的情况下反复中断时最多重试 3 次（第 4 次写 `Task recovery gave up`）；只要每次续跑都产生过模型回答或工具结果就重新计数，所以开发期频繁重启不会误伤正常任务。

```bash
# 关闭自动续跑（0 表示不自动恢复，发现残留任务时直接标记失败）
TASK_RESUME_MAX_ATTEMPTS=0 uv run python main.py --web
```
- 撤销依赖本机的 `git`，但仓库在 `data/checkpoints/<workspace-key>/` 下，**不会碰你自己的 `.git`**；工作空间不是 git 仓库也能用。拿不到 git 时接口返回 409 并说明原因，前端把入口标为不可用。

实现与已知限制（并发任务共享工作树时的归属重叠）见 [ADR 0020](decisions/0020-checkpoint-rewind.md)。

### 智能体（Agent）管理

每个智能体包含名称、描述、系统提示词、工具、MCP 与技能配置。内置三个默认智能体：`build`（构建）、`ask`（问答）、`plan`（规划），对应原有的任务模式。

- `GET /api/agents`：查询智能体列表。
- `GET /api/agents/meta`：返回可选工具、内置技能（`skills`）、技能库技能（`library_skills`）与 MCP 传输类型。
- `POST /api/agents`：创建智能体。
  - 请求体：`{"name": "...", "description": "", "system_prompt": "...", "tool_names": null, "skill_names": [], "mcp_servers": [{"name": "fs", "transport": "stdio", "target": "npx ..."}]}`
  - `tool_names` 为 `null` 表示使用全部已注册工具；为空数组表示不使用任何工具。
- `PUT /api/agents/{agent_id}`：更新智能体（部分字段）。
- `DELETE /api/agents/{agent_id}`：删除智能体；内置智能体不可删除（返回 400）。
- 创建任务时通过 `POST /api/tasks` 的 `agent_id` 指定智能体；未提供时回退到 `mode` 或默认智能体。

说明：MCP 目前仅作为每个智能体的配置保存并随任务记录（暂无 MCP 客户端执行）。工具与内置技能（`agent/modes.py` 中的 `SKILLS`）会实际影响任务的提示词与可用工具集；技能库技能（技能根目录下的子文件夹）目前只在智能体编辑中列出并标注来源，尚未注入提示词。同名时以内置技能为准。

### 工具管理

「工具管理」页面把 `agent/tools/catalog.py` 注册的工具按分类分组，一类一张表（文件读写 / 命令与进程 / 桌面操作 / 计算与代码 / 信息查询 / 用户交互），可搜索工具名、描述或智能体；点「详情」查看权限门禁、确认框可提供的答复、实现文件与参数结构（参数渲染与智能体编辑里的工具详情一致）。

- `GET /api/tools`：返回 `{tools}`，每个工具包含：
  - `name` / `description` / `parameters`：与模型看到的工具声明一致；
  - `category`：列表分组，取值见 `agent/tools/spec.py` 的 `CATEGORY_KINDS`；页面认识的分类用本地化名称，不认识的直接显示原值；
  - `description_i18n`：`{语言: {description, parameters}}`，只用于页面展示，不会进入模型看到的 schema；
  - `permission`：权限门禁种类 `none` / `read` / `write` / `exec` / `computer`（见 `agent/tools/permissions.py`），`none` 表示永不询问；
  - `scopes`：确认框可以给出的答复（`once` / `session` / `always`），只包含该工具实际接受的范围；
  - `has_preview`：是否提供确认前的无副作用预演；
  - `source`：实现文件，相对仓库根目录；
  - `agent_ids`：允许调用该工具的智能体 id；智能体的 `tool_names` 为 `null` 表示"全部工具"，此时它会出现在每个工具的列表里。

工具说明与参数说明是双语的：英文是源文本，页面上始终显示；当前语言不是英文时，会在英文下方再显示该语言的翻译。英文界面只显示英文。每个工具都自带 `zh-CN` / `zh-TW` / `fr` / `de` / `ru` 五套文案，与界面可选语言一致。

翻译放在每个工具包自己的 `i18n.py` 里（`ToolText`，由 `spec.py` 通过 `localized_texts(...)` 装配成 `description_i18n`），与 `description.py` 分开，因为模型永远只看英文。新增或修改工具参数时要同步补这五套翻译：`test/tool_api_test.py` 会校验每个工具的每个语种都覆盖了全部参数。

详情弹窗里每个参数都有一个输入框（按参数类型给文本框 / 下拉 / JSON 文本），点右上角「测试」会在后台真实执行一次该工具，并显示模型会收到的结果；`ToolOutcome` 的 `details` 另列为 JSON。

- `POST /api/tools/{tool_name}/test`：请求体 `{"arguments": {...}}`，返回 `{tool, ok, result, details, error, truncated, duration_ms}`。
  - `ok=false` 表示工具抛出了异常（参数不对就是这种），不是 HTTP 错误；工具自己返回的错误仍是 `ok=true`，错误文本在 `result` 里。
  - **不经过权限确认**：它不属于任何任务，没有 broker 可以询问。页面在测试需要确认的工具（`permission != none`）前会先弹一次浏览器确认；不要把它当作通用执行接口。
  - `result` / `details` 超过 2 万字符会截断，`truncated=true`。

### MCP 市场

MCP 市场维护可复用的 MCP 服务预设（传输方式 + 命令/URL），智能体在创建或编辑时从市场中勾选，不再手写传输方式与目标。

- `GET /api/mcp-servers`：返回 `{servers}`。
- `POST /api/mcp-servers`：新增。
  - 请求体：`{"name": "filesystem", "description": "", "transport": "stdio", "target": "npx -y @modelcontextprotocol/server-filesystem"}`
  - `transport` 仅支持 `stdio` / `sse`，其它取值返回 400。
- `PUT /api/mcp-servers/{mcp_id}`：部分更新。
- `DELETE /api/mcp-servers/{mcp_id}`：删除。

删除市场条目不会影响已引用它的智能体：智能体保存的是选中条目的一份快照（含 `mcp_id`），因此编辑智能体时即使市场条目已被删除或改名，原配置仍会以“不在市场中”的标记保留。

### 技能（Skills）库

所有技能共用一个根文件夹，每个技能是根文件夹下的一个子文件夹。技能的名称与描述优先读取子文件夹内 `SKILL.md` 的 YAML frontmatter（`name` / `description`），否则使用子文件夹名，描述可回退为正文首行。

- `GET /api/skills`：返回 `{skills_root, skills}`，`skills` 为根文件夹下的技能列表。
- `GET /api/admin/skills-root`：读取当前技能根文件夹与来源（`database` / `env`）。
- `PUT /api/admin/skills-root`：设置技能根文件夹。
  - 请求体：`{"skills_root": "E:/skills"}`
- `POST /api/skills/import`：把本地文件夹复制为技能。
  - 请求体：`{"source_path": "E:/downloads/my-skill"}`
- `DELETE /api/skills/{name}`：删除根文件夹下的技能子文件夹。

环境变量也支持：`SKILLS_ROOT`。默认根文件夹为仓库根目录下的 `skills/`。

### 工作空间与会话

工作空间指向一个本地文件夹，任务运行时的相对文件路径以该文件夹为基准（该路径会注入到系统提示词）。

- `GET /api/workspaces`：查询工作空间列表。
- `POST /api/workspaces`：创建工作空间。
  - 请求体：`{"name": "my-project", "root_path": "E:/projects/my-project"}`
- `PUT /api/workspaces/{workspace_id}`：更新工作空间（`name` / `root_path` 均可选）。
- `DELETE /api/workspaces/{workspace_id}`：删除工作空间。其下会话会变为“无工作空间”，不会被删除。
- `POST /api/sessions`：创建会话。
  - `name` 可选，缺省时按当前时间自动生成。
  - `workspace_id` 可选，缺省或为空表示该会话不属于任何工作空间。
- `GET /api/sessions`：返回的会话项包含 `workspace_id`（可能为 `null`）。

左侧列表展示顺序为：先列出工作空间（可展开显示其下会话），再列出任务（即没有工作空间的会话）。

### Provider 与模型

Web Admin 把过去的「模型连接」拆成两层：**Provider** 是请求的去处（协议 + 地址 + Key + RPM），**模型** 只有一个模型名和能力开关，挂到某个 Provider 下。地址、Key 与 **每分钟请求数（RPM）** 都记在 Provider 上，因此同一 Provider 下的所有模型共享一份配额；同一个协议配两个地址则是两个端点、两份配额。

- `GET /api/providers`：返回 `{providers}`，每项含 `provider_id` / `name` / `protocol` / `base_url` / `api_key` / `rpm_limit` / `model_count`。
- `POST /api/providers`：创建端点。
  - 请求体：`{"name": "本地 Ollama", "protocol": "openai-compatible", "base_url": "http://127.0.0.1:11434/v1", "api_key": "", "rpm_limit": 60}`
  - `protocol` 会规范化为 `openai` / `anthropic` / `anthropic_compatible` / `gemini`；未知协议 400。
  - `rpm_limit` 为 0 表示不限，上限 6000；超限的请求会等到有配额（单次最多 60 秒，超过报错）。
  - `anthropic-compatible` 必须给 `base_url`；同一（协议, 地址）重复创建会 400（一个端点只有一份配额）。
- `PUT /api/providers/{provider_id}`：部分更新；改地址等于把配额搬到新端点，下一次请求生效。
- `DELETE /api/providers/{provider_id}`：删除端点；其下还有模型时返回 409，先删除或迁走模型。
- `GET /api/models`：返回 `{models}`，每项含 `model_id` / `name` / `provider_id`，并附带解析出的 `provider_name` / `protocol` / `base_url`。
- `POST /api/models`：创建模型。
  - 请求体：`{"name": "qwen3:0.6b", "provider_id": "<provider_id>", "supports_tool_calls": true, "supports_image_input": false, "thinking_mode": false, "max_input_tokens": 32768, "max_output_tokens": 8192}`
  - `provider_id` 不存在时 400（模型必须能解析到端点）。
- `PUT /api/models/{model_id}`：部分更新，含换 Provider。
- `DELETE /api/models/{model_id}`：删除模型，不影响 Provider。

任务仍用 `model_id` 指定模型（`POST /api/tasks`），运行时会连同它的 Provider 一起解析成实际请求的地址与 Key。

### 备份管理（任务明细保留）

- `GET /api/admin/retention`：读取当前保留配置。
  - 返回字段：
    - `retention_days`：当前保留天数
    - `retention_source`：`env` 或 `database`
    - `removed_tasks`：最近一次清理移除数量（`GET` 返回 0）
- `PUT /api/admin/retention`：设置保留天数。
  - 请求体：`{"retention_days": 30}`
  - `0` 表示关闭清理（保留全部任务明细）

默认 `.env` 也支持：

```
TASK_RETENTION_DAYS=36600
```

## 工具：`exec_command`（命令执行）

模型执行外部命令用 `exec_command`。命令**不经过** `file_access` 的路径策略——它就是个 shell，能读写进程用户碰得到的任何路径（见 [ADR 0005](decisions/0005-exec-tool.md)）。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `command` | string | 必填 | 交给当前平台 shell 执行的命令行。 |
| `timeout` | integer（**毫秒**） | `120000` | 上限 `1800000`（30 分钟）。超时会终止整棵进程树，结果里 `interrupted: true`。 |
| `description` | string | — | 一句话说明这条命令做什么，用于权限确认弹窗与审计记录。 |
| `run_in_background` | boolean | `false` | 立即返回 `pid` / `session_id` / 日志路径；之后用 `write_stdin` 打字并取新输出。 |
| `tty` | boolean | `false` | `true` 时把命令挂到**伪终端**而不是普通管道。 |
| `dangerouslyDisableSandbox` | boolean | `false` | 跳过额外的约束层；资源上限与整树终止不可关闭。 |

### `tty`：什么时候要，代价是什么

要终端的场合：程序**先问自己有没有终端**再决定行为时——`git` 的颜色与分页、`npm`/`gh` 的确认提示、`top` 这类全屏程序，以及"没有终端就拒绝运行"的 CLI（`sys.stdout.isatty()` 为 `True`）。

代价（工具描述里也写了，避免模型被吓一跳）：

- **stderr 并入 stdout**：终端只有一条流，结果里 `stderr` 恒为空串，`tty: true` 标记这次输出来自终端；
- 每行以 `\r\n` 结尾：模型看到的是 `\n` 版本，**落盘的完整文件保留原始字节**；
- 前台的 `tty` 命令**没法被回答**（前台在等它结束，提示无人可答）：要交互就配 `run_in_background`，再用 `write_stdin` 打字——Windows 上输入的 `\n` 会被转成回车，因为 ConPTY 只认 `\r`；
- Windows 的终端会在命令自己的输出前先吐一小段握手转义序列（ConPTY 初始化），它不是命令的输出；
- 终端尺寸固定 24×80，没有缩放开关。

平台与依赖：

- Windows 用 `pywinpty`（ConPTY），已在 `pyproject.toml` 以 `sys_platform == "win32"` 标记声明；
- macOS/Linux 用标准库 `pty`：子进程拿到自己的会话但**没有控制终端**，因此 Ctrl-C 由本工具带外投递（`killpg`）；
- 这个平台拿不到终端时报错 `tty_unavailable`（**不会**静默退回管道），也没有关掉它的配置开关。

`tty` 会话同样受进程树约束（Windows Job Object / POSIX 进程组）、同样有每任务 8 个会话上限与 30 分钟 TTL；原理与实测记录见 [ADR 0009](decisions/0009-exec-tty.md)。

## 工具：`ask_user_question`（向用户提问）

模型遇到**本该由用户决定**的事（选哪个方案、改哪个环境、要不要覆盖）时，用这个工具把问题交回来，而不是猜一个再返工。它只读、只阻塞，不能允许或禁止任何操作；`build` 与 `ask` 两个模式可用，`plan` 模式没有工具。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `questions` | array（1–3 项为佳） | 每项含 `id`（snake_case，答复以它为键）、`header`（≤12 字符的短标签）、`question`（一句话）、`options`（2–3 个互斥选项，推荐项放第一并在标签末尾加 `(Recommended)`）。每题至少一个选项；`id` 不能重复。**不要**自己加 "Other" 选项，客户端会加一行自由输入。 |

模型拿到的结果是 JSON：`{"answers": {"<id>": {"answers": ["选项标签", "用户补充的原话"]}}}`——选项一个元素、自由文本另一个元素；用户跳过的题为空数组。

通道的语义（细节见 [ADR 0010](decisions/0010-ask-user-question.md)）：

- **等待期间任务状态是 `waiting`**，事件推流与前端轮询继续，Web Admin 弹出问题表单（每题单选 + 自由输入 + 提交/跳过）。"跳过"等于立刻告诉模型"别等我"。
- **没人回答不等于拒绝**：超时（`ASK_USER_TIMEOUT_SECONDS`，默认 120 秒）、任务被停止、没有客户端，都返回空答案集，并附一句让模型自行决定、说明假设的说明。
- 在 CLI 或库调用里没有客户端可问，工具会返回 `no_client`（不阻塞、不报错）；目前不提供"在终端里直接提问"。

## 工具：`computer_observe` / `computer_control`（宿主桌面操作）

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
- 细节与取舍见 [ADR 0011](decisions/0011-computer-use.md)。

## 运行前端（源码开发）

前端源码位于：

- `web-admin/`
- 打包产物路径：`web-admin/dist/`

## 构建与运行前端

```bash
cd web-admin
npm install
npm run build
cd ..
uv run python main.py --web
```

```bash
cd web-admin
npm run dev
```

## 备注

- 任务与事件持久化存储在仓库根目录 `monitor_tasks.db`，服务重启后可继续查询历史；被重启打断的任务会在启动时自动续跑（见「断点续跑」）。
- WebSocket 重连可带 `since`，避免重复消费事件。
