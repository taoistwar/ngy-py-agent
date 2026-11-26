# API：任务与撤销

## 任务管理

- `POST /api/tasks`：创建任务，返回 `task_id`。
  - 请求带 `session_id` 时，该会话中**已成功完成**的任务会作为对话上下文注入：每个任务是一轮 `user`（原始 `query`）+ `assistant`（任务结果），新任务接着这些 messages 继续，因此“给它加个测试”这类追问能指向前一个任务做的事。
  - 未完成、失败、已停止的任务不算上下文；上下文有预算（最多 40 条消息、24000 字符，单条消息截断到 8000 字符），超出时整轮丢弃最旧的轮次，保留最近的对话。
- `GET /api/tasks`：查询任务列表。
- `GET /api/tasks/{task_id}`：查询单个任务详情。
  - 额外返回本次运行的 `input_tokens` / `output_tokens` / `total_tokens`（对所有 `llm_response` 事件的 `usage` 求和，压缩摘要这类没有 `usage` 的事件不计）与 `duration_ms`（从任务创建到最后一次更新，即墙钟耗时）。结果区标题栏用它们显示「总 tokens」与「耗时」，点击总 tokens 可看输入/输出明细。
- `GET /api/tasks/{task_id}/events`：分页查询任务事件。
  - `offset`：起始偏移（默认 `0`）
  - `limit`：每页数量（1-100，默认 `30`）
- `GET /api/tasks/{task_id}/events/stream`：SSE 事件流。
- `GET /api/tasks/{task_id}/events/ws`：WebSocket 事件流。
  - `since`：按 `event_id` 增量拉取
  - `heartbeat`：心跳间隔（秒）
- `POST /api/tasks/{task_id}/stop`：请求停止（见下面「停止与撤销」）。
- `POST /api/tasks/{task_id}/fork`：以此任务为分叉点创建新会话（见下面「Fork」）。返回新会话 `session`、分支任务 `task_id`（副本，不是原任务）、来源 `source_session_id` / `source_task_id`，以及 `copied_task_count` / `event_count`。
- `GET /api/tasks/{task_id}/changes`：这个任务改过哪些文件（`status` + 增删行数 + `conflict`）。`conflict: true` 表示任务之后该文件又被改过，撤销会覆盖别人的改动，因此不可撤销；`available: false` 时 `reason` 说明为什么不能撤销。
- `GET /api/tasks/{task_id}/changes/diff?path=`：单个文件的补丁，按需取。
- `POST /api/tasks/{task_id}/revert`：撤销改动。body 可带 `paths`（省略 = 全部）与 `force`（覆盖任务之后被改过的文件），返回逐文件的 `restored` / `conflicts` / `skipped`。
- `GET /api/healthz`：服务健康检查。

## 停止与撤销

**停止**是协作式中断，生效点在 step 边界、每个工具调用之间，以及阻塞等待内部（0.25 秒轮询一次）。所以正在跑的前台 `exec_command`、`write_stdin` 的等待也会被打断，不需要等命令自己的 `timeout`。[ADR 0019](../decisions/0019-cancel-interrupts-running-work.md) 里有完整的边界说明：能打断的是**等待**，不是计算——进程内 `exec()` 的死循环和正在飞的模型请求仍会跑完。

**撤销**把任务改过的文件恢复到它第一次改动之前。范围覆盖文件工具、`exec_command` / `write_stdin` 和 `code_interpreter`；`computer_control` 操作的宿主桌面**不在**范围内。

- 判据是"当前内容仍等于任务留下的内容"。任务之后被人改过的文件会报为 **conflict 并跳过**，其余文件照常回退；确认要覆盖就带 `force`。
- 任务详情的结果区有「查看变更」入口：列出每个文件的增删行数，可展开单个文件的补丁；被之后改动过的文件标为冲突，撤销按钮禁用（服务端的 `conflict` 标记，见上）。
- 逐文件进行，不是全有全无。
- 只有**全部**回退成功时任务才变成 `reverted`，并且不再进入后续会话的对话上下文（它的改动已经不在了）。
- 撤销依赖本机的 `git`，但仓库在 `data/checkpoints/<workspace-key>/` 下，**不会碰你自己的 `.git`**；工作空间不是 git 仓库也能用。拿不到 git 时接口返回 409 并说明原因，前端把入口标为不可用。

实现与已知限制（并发任务共享工作树时的归属重叠）见 [ADR 0020](../decisions/0020-checkpoint-rewind.md)。

## Fork（分支会话）

`POST /api/tasks/{task_id}/fork` 把**该任务及其之前的所有任务**复制到一个新会话，原会话完全不动，两条对话从此各自继续：

- 任务按创建顺序复制，保留原来的 `created_at`、任务名、模型与结果，事件日志一并复制（事件 id 重新分配）。所以新会话的对话历史与分叉点一致，后续任务能接着它往下走。
- 新会话名取自分叉任务：优先任务名 `name`，没有则用 `query` 折叠后截断到 120 字符。
- 任务状态原样复制，但 `running` / `waiting` 会被记成 `stopped`：副本是历史快照，不能让启动恢复扫描把它当成未完成任务再跑一遍。
- 目标任务仍在运行（`running` / `waiting`）时返回 `409`：它的日志还在写，复制出来只是半轮。
- 新会话沿用原会话的 workspace，后续任务从同一个目录开始。

## 断点续跑（进程重启后）

任务的执行线程跟着进程一起消失，但数据库里的行还写着 `running`。下次启动 Web 服务时，启动钩子会扫描这类任务并接着跑：

- **恢复对话**：从事件日志重建消息。最后一次 `LLM request` 的 `messages` 就是当时发给模型的完整对话（历史、压缩、截图都已经在里面），其后已记录的模型回答和工具结果按顺序补回。
- **不重复执行**：日志里已有 `tool_result` 的调用直接复用结果，工具**不会再跑一次**；只有调用事件、没有结果事件的调用（进程正好死在工具执行中间）不会被重放，而是变成一条「结果未知，先确认现状再决定是否重做」的 tool 消息交给模型判断。
- **不重复收尾**：日志里已经有最终结论时（`Task finished` / `ReAct finished` / 模型最后一条不带工具调用的回答），只补齐任务状态，不重新调用模型。
- **步数沿用同一个预算**：续跑从停下的那一步继续编号，`max_steps` 不会被重置。
- 每次续跑会写一条 `Task resumed after restart` 事件，记录恢复模式、起始 step、复用了多少条工具结果、有多少次调用结果未知。

无法续跑时任务会被标记为 `failed`，并写入 `Task recovery failed` 事件说明原因（没有可重建的对话、绑定的模型已被删除等）。同一个任务在**没有进展**的情况下反复中断时最多重试 3 次（第 4 次写 `Task recovery gave up`）；只要每次续跑都产生过模型回答或工具结果就重新计数，所以开发期频繁重启不会误伤正常任务。

```bash
# 关闭自动续跑（0 表示不自动恢复，发现残留任务时直接标记失败）
TASK_RESUME_MAX_ATTEMPTS=0 uv run python main.py
```

## 备份管理（任务明细保留）

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
