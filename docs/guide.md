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
