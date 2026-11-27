# ADR 0033: 任务板——项目级任务图，带依赖与认领

- 状态：已接受（Accepted）
- 日期：2026-11-27
- 相关：`agent/tools/task_board.py`、`agent/tools/task_store.py`、`dao/board_tasks.py`、`agent/runtime/board.py`、`agent/tools/task_*/`、`routes/task_api.py`、`web-admin/src/components/TaskBoardPanel.jsx`
- 前置：[ADR 0016](0016-micro-compact.md)（工具结果预算与压缩）、[ADR 0019](0019-cancel-interrupts-running-work.md)（取消）

## 背景

`todo_write`（[上一层的会话清单](../guide/tool-todo-write.md)）只解决"这次对话的步骤"：它随会话结束，没有依赖，也不区分谁在做。而一个项目常有"数据库表建好才能写 API，API 定了才能写测试"这种顺序，并且这些工作要跨越多次对话。参考实现（`learn-claude-code/s10_task_system`）用一个任务图解决：每个任务有 id、状态、负责人和前置依赖，Agent 通过工具认领与完成。

本 ADR 记录把它搬进本仓库时的取舍。

## 决策

### D1. 概念叫"任务板上的任务"，不叫"任务"

仓库里 "task" 已经指一次完整的 Agent 运行（`tasks` 表、`task_id`、任务列表）。新的实体在代码与库表里叫 **board task**（`board_tasks`），模型可见的工具名用 `task_` 前缀（`task_create` / `task_update` / `task_list` / `task_get` / `task_claim` / `task_complete`），前端叫「任务板」。命名对照与取舍写在 `docs/guide/tool-task-board.md`。

### D2. 作用域是工作区，不是会话

- 会话绑定了工作区 → `board_id = workspace:<workspace_id>`：该项目的所有会话共享一块板，这是"跨会话"的来源。
- 会话没有工作区 → `board_id = session:<session_id>`：这次对话自己一块板。

`board_id` 带前缀是因为它可能来自两张不同的表，裸 uuid 看不出板属于谁。删除工作区时一并删除它的板（`dao/sessions.py`）。

### D3. 三种状态、两个转移、一条规则

`pending --claim--> in_progress --complete--> completed`，规则只有一条：**任务的所有前置依赖都是 `completed` 才可开始认领**。依赖指向的任务不存在也算阻塞——缺失不等于完成。

拒绝按信息返回（`details.reason`：`not_found` / `conflict` / `blocked` / `owner_mismatch` / `invalid_argument`），不是步骤失败：「你被 X 阻塞」是模型需要的信息，不是错误。只拒绝渲染不出来的输入：空 subject、超长文本、依赖超过 50 条、自依赖、环。

### D4. owner 是会话，由应用层注入

`task_claim` 不接受 `owner` 参数。认领者由 `TaskBoard.owner`（会话 id）决定，由 `agent/runtime/board.py` 在运行时绑入，工具层无法伪造：否则模型可以给自己起个名字去完成别人的任务。`task_complete` 只接受 owner 匹配的 `in_progress` 任务，错误里说明实际 owner。

代价：被放弃的认领没有释放机制，只能由原会话完成。这是有意保留的限制（同参考实现）。

### D5. 规则与存储分离

- 规则（纯函数）：`agent/tools/task_board.py`——就绪判断、依赖合并与环检测、认领/完成的变更集、渲染。
- 存储契约：`agent/tools/task_store.py`（`BoardStore` 协议 + 内存实现 + `TaskBoard` 绑定对象）。
- 数据库：`dao/board_tasks.py`（只有 SQL 与行映射，没有派生状态；"ready" 由规则层算，避免两处对"被阻塞"的定义分叉）。
- 注入点：`agent/runtime/board.py`（`MonitorBoardStore`、`resolve_board_id`、`board_view`）。

`agent.tools` 仍然不 import `commons`/`dao`（[ADR 0019](0019-cancel-interrupts-running-work.md) 的分层），`agent.runtime` 是唯一读活状态的地方。

### D6. 前端复用任务轮询

`GET /api/tasks/{id}` 的响应新增 `board` 字段（工作区维度，`agent.runtime.board.board_view`）：派生状态 + owner 会话名 + 阻塞任务名。前端 `TaskBoardPanel.jsx` 于「任务清单」下方渲染，跟随已有的 1 秒轮询自动同步，不新建通道。

行序按「进行中 → 可开始 → 阻塞 → 已完成」，因为面板回答的是"现在该干什么"。板行按 `rowid` 排序，不用 `created_at`：同一毫秒的两次插入会让顺序在两次轮询之间抖动。

### D7. 工具页归入「任务管理」

`todo_write` 与六个 `task_*` 共七件同属"计划与协作"，`category = task`（`CATEGORY_TASK`），工具页单独成组，不埋进 `other`。

## 后果

- 模型多六个工具（`build` 模式全量；`ask` / `plan` 白名单不含它们）。
- 会话详情响应多一个 `board` 字段；`test/tool_api_test.py` 的六语言契约同样覆盖这七个工具（`agent/tools/task_board_i18n.py`）。
- 子 agent 拿不到这六个工具（`agent/tools/catalog.py::CHILD_EXCLUDED_TOOLS`，理由见 [ADR 0032](0032-subagent-tool.md) D2）：规划由守着计划的那个会话做，被派出去的任务只回一份摘要。
- 已知限制：
  - 没有释放认领、没有删除依赖；依赖图在任务被认领后冻结；
  - 板不与 `todo_write` 同步：清单是即刻步骤，板是项目计划，由模型各自维护；
  - 认领是协作提示而不是锁：另一个会话仍可创建依赖同一任务的新任务，只是不能完成别人认领的那个。
