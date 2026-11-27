# ADR 0032: `subagent` 工具——把一段子任务放进独立上下文

- 状态：已接受（Accepted）
- 日期：2026-11-27
- 相关：`agent/tools/subagent/`、`agent/agent_loop/subagent.py`、`agent/tools/bindings.py`、`agent/tools/registry.py`、`agent/agent_loop/loop.py`、`agent/models.py`、`web-admin/src/events/friendlyEvent.js`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0010](0010-ask-user-question.md)（通道以绑定注入）、[ADR 0019](0019-cancel-interrupts-running-work.md)（取消）、[ADR 0020](0020-checkpoint-rewind.md)（快照与回退）

## 背景

父 ReAct 循环的 `messages[]` 会记住每一次工具调用与结果。追踪一条调用链常常要读十几个文件，等结论出来时，中间细节已经占满上下文——而且不再被需要。参考实现（`learn-claude-code/s06_subagent`）用一个 `task` 工具解决：开一份全新的 `messages[]` 跑嵌套循环，只把最终文本交回父循环。

本 ADR 记录把它搬进本仓库时的取舍。核心问题不是"能不能跑一个嵌套循环"，而是"哪些东西共享、哪些隔离"，以及"前端怎么看见它"。

## 决策

### D1. 隔离的是消息，不是进程或工作空间

- 子 agent 有独立的 `messages`（system + 一段 brief），父对话**不复制**给它。
- 同一进程、同一 `base_dir`、同一份文件系统。子 agent 的写入与命令和父 agent 一样留在工作空间里。
- 只把**最终文本**交回父对话；子 agent 的工具调用与结果不进入父 `messages`。

### D2. 子 agent 的工具 = 父的工具 − `subagent` − 任务板

- 从父 registry 的工具名列表里排除 `subagent`，其余全部给子 registry（包括 MCP 动态注册的工具：`ToolRegistry` 只构建内置工具，所以 `_adopt_dynamic_tools` 把父用的动态工具复制过去）。
- 因此**只有一层委派**：子 agent 看不到 `subagent`，调用它会得到 `Tool 'subagent' not found`。
- 任务板六个工具（`task_*`）也排除（`agent/tools/catalog.py::CHILD_EXCLUDED_TOOLS`）：派出去的是「做完一件事、回一份摘要」，子上下文返回即弃；建任务、连依赖、认领都是**父会话**的规划职责，给子 agent 只会越权（它看不到父会话正在推进哪一步）又多花 token。
- 子 agent 的 `todo_write` 用**独立的内存计划板**：共享父会话的 board 会让一次委派覆盖父对话正在推进的计划。

### D3. 门禁、黑名单、检查点、提问通道共享

子 registry 与父 registry 共用同一批对象：

| 能力 | 为什么必须共享 |
| --- | --- |
| `permission_broker` | 子 agent 的 `exec_command` 必须问同一个用户；"委派"本身不是一次被批准的动作，确认要落在真正执行的命令上 |
| `denylist` | 硬拒绝是策略，不能因为换了执行上下文就失效 |
| `checkpoint_store` + 父 `task_id` | 子 agent 的文件改动属于**父任务**的撤销记录，回退一次要能一起收回 |
| `user_question_broker` | 有客户端时子 agent 也能提问；系统提示要求它优先自行假设而不是打断用户 |
| `should_stop` | 父任务停止时，子循环在下一次模型调用或下一次工具调用前退出 |

`subagent` 工具自身的 `permission` 是 `none`：它不是特权动作，门禁由子 agent 的每个工具各自过。

### D4. 子循环不经过 `run_react_loop`

直接复用 `run_react_loop` 有两个硬冲突：

- 它带 `_reaps_task_sessions`，返回时按 `task_id` 停 MCP 会话与后台进程。子循环沿用父 `task_id` 会**杀掉父任务的会话**；用新 id 又会让检查点脱离父任务的撤销记录。
- 它会重新走 `_build_runtime`（重新解析 provider、重建 MCP 桥），而子循环要的恰恰是"父的 provider + 父的工具集"。

因此子循环只复用两半：`run_model_turn`（模型请求与解析）与子 registry 的 `execute_tool`（工具分发，含门禁与黑名单）。压缩管线不进入子循环：子上下文是一次性的，通常远小于上限，做压缩只会引入另一份需要维护的阈值。

### D5. 子循环不发自己的 `llm_*` 事件

父对话永远读不到子 agent 的模型往返，把它们写进同一份任务日志只会让日志翻倍且被误读。时间线只收 `subagent` 类别：

- `phase=started`：brief、步数上限；
- `phase=tool`：子 agent 的每一次工具调用（名称、参数、结果、是否失败、子步骤号）；
- `phase=done` / `phase=failed`：最终报告、已用步数、工具调用数、耗时、失败原因（`stopped` / `model_error` / `step_limit`）。

不复用 `tool_call` / `tool_result`：那两类记录的含义是"**这次对话**调用了工具"，而子 agent 的调用不属于父对话。合并会让任务恢复重建的 transcript 声称父对话执行过它从没执行过的步骤。

事件里的长文本（brief、参数、结果）按 4,000 字符截断：事件随任务持久化，一份被转述的文件不需要第二份全文。

### D6. 工具名是 `subagent`，不是 `task`

仓库里"task"已经指一次完整的运行（`task_id`、任务列表、事件流）。模型可见工具名再叫 `task` 会让"任务是子任务"这个歧义进入所有文档与日志。参考实现用 `task` 是因为那边没有第二个 task 概念。

### D7. 步数上限 12，取消在调用边界生效

- `DEFAULT_SUBAGENT_MAX_STEPS = 12`：子任务有自己的轮次预算，不沿用父循环的步数计数器。
- 停止检查发生在每次模型调用**之前**与每次工具调用**之前**；已经发出的请求不会被强行中断（与父循环同一规则，见 ADR 0019）。
- 到上限、模型报错、父任务停止，都会返回一段**可读文本**给父模型（`Subagent stopped after N turns ...` / `Error: ...`），而不是抛异常：父模型据此决定修正 brief 再委派，还是自己接着做。

### D8. 前端：一个类别、三个阶段、六种语言

- `EventCategory.SUBAGENT = "subagent"`；过滤器的顺序放在 `tool_result` 之后。
- 友好视图 `buildSubagent`（`web-admin/src/events/friendlyEvent.js`）：brief 与报告是文本块，参数摊平为字段/块；headline 按阶段取模板。
- 六个语言包（`src/locales/*.json`）加 `category_subagent`，六个事件字典（`src/events/dictionary/*.js`）加 `phase` / `steps_used` / `tool_calls` 字段、`phase` 取值与 7 条文案；`.tag.subagent` 复用工具类颜色。
- 管理页：分类用 `other`（不给"委派"单开一类），六个语种的工具说明按工具包 `i18n.py` 的约定补齐。

## 后果

- 父模型的工具列表多一个 `subagent`（`build` 自动获得；`ask` / `plan` 的白名单没有它——委派会执行副作用，不属于只读模式）。
- 任务日志多一条 `subagent` 事件流；`task_recovery` 只按 `tool_call` / `tool_result` 重建 transcript，因此恢复后看到的是"父调用了 `subagent` 并拿到一份报告"，与真实上下文一致。
- 已知限制：
  - 子 agent 的完整对话不入库，排障只能看到每次工具调用的摘要；
  - 子 agent 的输出不参与父循环的结果预算与压缩，超大报告仍可能占满父上下文（brief 里应要求"简短报告"）；
  - 委派是同步的：父任务在子 agent 运行期间被它阻塞，不能并行跑多个子任务；
  - 子 agent 与父共享工作空间，两者对同一文件的写入按调用顺序串行发生，没有额外隔离。
