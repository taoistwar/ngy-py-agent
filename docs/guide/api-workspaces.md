# API：工作空间、会话与 AGENTS.md

## 工作空间与会话

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
- `GET /api/sessions/{session_id}/context`：这个会话已经占用了多少上下文（任务窗口右下角的环形进度，悬停可看百分比与明细）。
  - 可选 `model_id`：任务窗口当前选中的模型，它决定分母（该模型的 `max_input_tokens`）。
  - `used_tokens` 不是估算值，而是会话最近一次模型请求的 `usage`（输入 + 输出 token）；最近一个任务还没拿到回答时，会往回看前几个任务，取最近一次真实读数。
  - 模型没配 `max_input_tokens` 时，分母回退到 ReAct 循环自己的上下文预算（`CONTEXT_CHAR_LIMIT`，默认 200000 字符 ÷ 4 = 50000 token），`limit_source` 会说明是 `model` 还是 `loop`。

取舍与已知限制见 [ADR 0021](../decisions/0021-context-usage-meter.md)。

左侧列表展示顺序为：先列出工作空间（可展开显示其下会话），再列出任务（即没有工作空间的会话）。

## 项目指令：AGENTS.md

工作空间根目录下的 `AGENTS.md`（[agents.md](https://agents.md/) 格式：纯 Markdown、无 schema、无必填字段）会在该工作区的任务里自动进入系统提示词，不用每次在问题里重复交代构建与测试命令：

- 根目录的 `AGENTS.md` **全文注入**，未配置时默认开启、单文件上限 32 KiB；开关与上限在 Web Admin「全局配置 → AGENTS.md 项目指令」里改（范围 1024–1048576 字节，无环境变量），下一次任务生效。超出部分截断，并提示模型用 `read_file` 读原文。
- 子目录里的 `AGENTS.md`（monorepo 每个包一份）只列成**索引**，并说明"改到那个目录前先读它，最近的那份优先"。不在索引里的用 `glob`（`**/AGENTS.md`）找。
- 旧名 `AGENT.md` 仍可读；同一目录同时存在两份时只用 `AGENTS.md`。
- 扫描到第三层为止，跳过 `.git`、`.venv`、`node_modules`、`venv`、`dist`、`build`、`target`、`vendor`、`__pycache__`；索引最多列 20 个。
- 优先级：用户在对话里的要求 > `AGENTS.md` > 智能体/模式的默认提示词。
- 未绑定工作区的会话不读（它没有"项目"）；全局开关关闭时一律不读。
- 每次读到文件，任务日志里会有一条 `Loaded AGENTS.md` 事件：文件名、字符数、是否截断、嵌套索引，不含正文。

配置接口（「全局配置」页用的就是这两个）：

- `GET /api/admin/agents-md`：读取当前配置，返回 `{enabled, max_bytes, source}`，`source` 为 `env` 或 `database`。
- `PUT /api/admin/agents-md`：设置开关与上限，下一次任务生效。
  - 请求体：`{"enabled": true, "max_bytes": 32768}`
  - `max_bytes` 允许 1024–1048576，超界返回 422。

本仓库自己那份 `AGENTS.md` 是写给维护者的开发约定，不会成为运行时规则；只有绑定成工作区的目录才会被读取。取舍与已知限制见 [ADR 0022](../decisions/0022-agents-md.md)。
