# 用户指南

- 开发者请先阅读 [docs/dev.md](dev.md)。

## 运行方式

### 单次运行

```bash
uv run python main.py
```

默认会执行内置示例问题，并走 ReAct + 工具调用流程。

### 指定问题（单次）

```bash
uv run python main.py "What's the weather in Tokyo?"
```

### 指定 Provider

```bash
uv run python main.py --provider openai-compatible
uv run python main.py --provider openai
uv run python main.py --provider anthropic
uv run python main.py --provider anthropic-compatible
uv run python main.py --provider openai-compatible --steps 4
```

说明：`openai-compatible` 会走 OpenAI 兼容接口。

### 交互模式

```bash
uv run python main.py --interactive
uv run python main.py --interactive --trace
```

### 仅输出最终结果

```bash
uv run python main.py --quiet "What's the weather in Vancouver?"
```

## Web Admin 管理中心

```bash
uv run python main.py --web
```

启动后访问：

```text
http://127.0.0.1:8001
```

### 参数说明（关键）

```text
--web
--host HOST          监听地址（默认 127.0.0.1）
--port PORT          监听端口（默认 8001）
--reload             运行时热重载
```

## API 说明

### 任务管理

- `POST /api/tasks`：创建任务，返回 `task_id`。
- `GET /api/tasks`：查询任务列表。
- `GET /api/tasks/{task_id}`：查询单个任务详情。
- `GET /api/tasks/{task_id}/events`：分页查询任务事件。
  - `offset`：起始偏移（默认 `0`）
  - `limit`：每页数量（1-100，默认 `30`）
- `GET /api/tasks/{task_id}/events/stream`：SSE 事件流。
- `GET /api/tasks/{task_id}/events/ws`：WebSocket 事件流。
  - `since`：按 `event_id` 增量拉取
  - `heartbeat`：心跳间隔（秒）
- `GET /api/healthz`：服务健康检查。

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

- 任务与事件持久化存储在仓库根目录 `monitor_tasks.db`，服务重启后可继续查询历史。
- WebSocket 重连可带 `since`，避免重复消费事件。
