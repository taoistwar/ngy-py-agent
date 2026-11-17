# API：智能体、MCP 与技能

## 智能体（Agent）管理

每个智能体包含名称、描述、系统提示词、工具、MCP 与技能配置。内置三个默认智能体：`build`（构建）、`ask`（问答）、`plan`（规划），对应原有的任务模式。

- `GET /api/agents`：查询智能体列表。
- `GET /api/agents/meta`：返回可选工具、内置技能（`skills`）、技能库技能（`library_skills`）与 MCP 传输类型。
- `POST /api/agents`：创建智能体。
  - 请求体：`{"name": "...", "description": "", "system_prompt": "...", "tool_names": null, "skill_names": [], "mcp_servers": [{"name": "fs", "transport": "stdio", "target": "npx ..."}]}`
  - `tool_names` 为 `null` 表示使用全部已注册工具；为空数组表示不使用任何工具。
- `PUT /api/agents/{agent_id}`：更新智能体（部分字段）。
- `DELETE /api/agents/{agent_id}`：删除智能体；内置智能体不可删除（返回 400）。
- 创建任务时通过 `POST /api/tasks` 的 `agent_id` 指定智能体；未提供时回退到 `mode` 或默认智能体。

说明：智能体勾选的 MCP 服务端，其工具会进入当前任务（见下面的「MCP 工具如何进入一次任务」）。工具与内置技能（`agent/modes.py` 中的 `SKILLS`）会实际影响任务的提示词与可用工具集；技能库技能（技能根目录下的子文件夹）目前只在智能体编辑中列出并标注来源，尚未注入提示词。同名时以内置技能为准。

## MCP 市场

MCP 市场维护可复用的 MCP 服务预设（传输方式 + 命令/URL），智能体在创建或编辑时从市场中勾选，不再手写传输方式与目标。

- `GET /api/mcp-servers`：返回 `{servers}`。
- `POST /api/mcp-servers`：新增。
  - 请求体：`{"name": "filesystem", "description": "", "transport": "stdio", "target": "npx -y @modelcontextprotocol/server-filesystem"}`
  - `transport` 仅支持 `stdio` / `sse`，其它取值返回 400。
- `PUT /api/mcp-servers/{mcp_id}`：部分更新。
- `DELETE /api/mcp-servers/{mcp_id}`：删除。
- `POST /api/mcp-servers/{mcp_id}/probe`：连接测试。按预设启动服务端、握手并拉取工具清单，返回 `{ok, transport, server_name, server_version, protocol_version, tools, error, duration_ms}`；`tools` 每项为 `{name, description, input_schema}`。
  - 连得上但服务端没有工具时 `ok` 为 `true`、`tools` 为空；连不上是 `200` + `ok: false` + `error`（含服务端 stderr 的尾部），只有预设不存在才返回 404。
  - 目前只有 `stdio` 能测；`sse` 预设返回 `ok: false` 并说明尚未支持。
  - 单次请求超时 60 秒（冷启动 `npx` 要下载包），命令在独立子进程里跑，超时或测试结束会连同子进程一起结束。
  - `target` 用绝对路径时，其所在目录会被放到子进程 `PATH` 最前；写成 `npx ...` 则要求运行后端的进程本身能在 `PATH` 里找到 `npx`（fnm 管理的 Node 需要先激活）。

删除市场条目不会影响已引用它的智能体：智能体保存的是选中条目的一份快照（含 `mcp_id`），因此编辑智能体时即使市场条目已被删除或改名，原配置仍会以“不在市场中”的标记保留。

### MCP 工具如何进入一次任务

任务开始时（`agent/agent_loop/runtime.py` 的 `_build_runtime`）按智能体勾选的服务端逐个连接、取工具清单，并把每个远端工具注册成 `mcp__<服务端>__<工具名>`：

- 这些工具和内置工具走同一条执行路径：同样受 `deny` 名单约束，同样在 `permission_request` 里询问，同样受结果预算与事件流处理。权限种类是 `mcp`，确认框的目标是**服务端**，摘要形如 `Run echo on MCP server filesystem`。
- 「本任务允许」只覆盖这一个远端工具；「一直允许」写进规则时同样是「这个工具 + 这个服务端」的组合。
- 某个服务端连不上不会让任务失败：它的工具直接缺席，`mcp_status` 记录原因（任务详情的「Starting ReAct loop」事件里有 `mcp_status`，系统提示词的 `## MCP servers` 一节也会写明哪些连上、哪些没连上）。
- 服务端只在这一次任务里存活，任务结束（或停止）时连同子进程一起关闭。任务跑完不会留下后台进程。
- 目前只有 `stdio` 会真正加载工具；`sse` 会被记为未连接。远端工具返回的 `image` 块会写成截图，随下一条消息交给支持图片输入的模型（不支持的模型只看到 `[image image/png]` 这一行）；`audio` 只留标记。

## 技能（Skills）库

所有技能共用一个根文件夹，每个技能是根文件夹下的一个子文件夹。技能的名称与描述优先读取子文件夹内 `SKILL.md` 的 YAML frontmatter（`name` / `description`），否则使用子文件夹名，描述可回退为正文首行。

- `GET /api/skills`：返回 `{skills_root, skills}`，`skills` 为根文件夹下的技能列表。
- `GET /api/admin/skills-root`：读取当前技能根文件夹与来源（`database` / `env`）。
- `PUT /api/admin/skills-root`：设置技能根文件夹。
  - 请求体：`{"skills_root": "E:/skills"}`
- `POST /api/skills/import`：把本地文件夹复制为技能。
  - 请求体：`{"source_path": "E:/downloads/my-skill"}`
- `DELETE /api/skills/{name}`：删除根文件夹下的技能子文件夹。

环境变量也支持：`SKILLS_ROOT`。默认根文件夹为仓库根目录下的 `skills/`。
