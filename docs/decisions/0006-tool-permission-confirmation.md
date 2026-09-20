# ADR 0006: 工具权限确认（P1 交互式确认）

- 状态：已接受（Accepted）
- 日期：2026-09-20
- 相关：`agent/tools/permissions.py`、`agent/tools/registry.py`、`agent/tools/specs.py`、`agent/agent_loop.py`、`main.py`、`task_store.py`、`web-admin/src/components/PermissionPrompt.jsx`
- 前置：[ADR 0001](0001-file-edit-tool.md)、[ADR 0002](0002-file-encoding.md)、[ADR 0004](0004-file-write-tool.md)、[ADR 0005](0005-exec-tool.md)

## 背景

需求：工具读取、写入/修改文件时，需要用户确认是否执行。

按惯例先核查本仓库的前提，四条结论直接决定了实现形态：

| 核查项 | 结果 |
| --- | --- |
| 是否存在唯一的工具调用收口 | **存在**：`ToolRegistry.execute_tool`（`registry.py:222`）。`agent/tool_registry.py` 只是转发壳，`agent_loop.py:443` 的 `_execute_tool` 是唯一调用点 |
| 是否有可以问用户的通道 | **有**：SSE `GET /api/tasks/{id}/events/stream`（`main.py:1047`）与 WebSocket `main.py:1059`。ADR 0005 D1 的判断"任务跑在守护线程里，没有人可以问"**在通道层面不成立**：同步阻塞的线程 + 下行事件流 + 一个决策端点，就足以问人 |
| 工具能否自己发事件 | **不能**。术语表已定死：`EventSink` 是 `(task_id, TaskEvent) -> None`，"工具本身拿不到它"。因此**门禁不能写在工具内部**，只能写在工具之外、又持有 sink 的那一层 |
| 状态能否表达"等待中" | **不能**：`TaskStatus` 只有 RUNNING/SUCCESS/FAILED/STOPPED，且 `_iter_task_events:1007` 与 WS `:1090` 都是 `status != RUNNING` 即**终止推流**。直接置新状态会让事件流在用户最需要看到确认请求时断掉 |

另有一处**必须同步修掉的既有文本**：ADR 0005 D5 记录了 `description` 是预留字段，工具描述里写的是"记录到审计轨迹，**不会暂停执行**"（`exec_tool.py:131` 与 `:156-159`，原文 "it does not pause execution" / "Does not pause execution."）。D5 当时的前提是"没有权限系统、没有消费者"，而本 ADR 正好把 D5 预言的第 1 个消费者（权限对话框展示 `description`）变成现实——**门禁上线的那一刻，这两句话就成了假话**。D5 自己警告过"任何'会有人审批'的暗示都会误导模型"，反向同理，所以这两处文案在本 ADR 内一并修正。

## 决策

### D1. 门禁做在 `ToolRegistry.execute_tool`，一处收口

`execute_tool` 是每次工具调用的必经之路，因此门禁写在这里可以**自动覆盖全部工具**，包括将来新增的工具。反过来，如果按工具逐个加门禁，遗漏是默认结局，而遗漏意味着"界面上显示已保护、实际没保护"——比不做更危险。

`agent/tools/registry.py` 与 `agent/agent_loop.py` 的分工：

- `ToolRegistry` 拿到一个可选的 `permission_broker`。**为 `None` 时行为与今天完全一致（全部放行）**，这样测试、库调用与其它 `execute_tool` 调用方不受影响。
- `run_react_loop` 在该函数内部构建 registry（`agent_loop.py:247`），而它同时持有 `task_id` 与 `event_sink`，因此在构建完 registry 后注入 broker 即可。

这与术语表"工具本身拿不到 `EventSink`"的约定不冲突：broker 不是工具，它是 registry 的协作对象，由 `agent_loop` 装配。

### D2. 覆盖面：凡是能碰文件系统或执行代码的工具都门禁

被门禁的工具与种类：

| 工具 | 种类 | 说明 |
| --- | --- | --- |
| `read_file` | `read` | 见 D3：只在敏感路径上问 |
| `edit_file` | `write` | 每次问 |
| `write_file` | `write` | 每次问 |
| `exec` | `exec` | 每次问 |
| `code_interpreter` | `exec` | 每次问 |
| 天气/时间/汇率 | `none` | 不问 |

**只门禁文件三件套等于没门禁**：`exec` 能 `cat`/`rm` 任意路径，`code_interpreter` 能 `open()` 任意文件，两者都会绕过文件工具。这与 ADR 0005 D1 记的是同一个洞。

本 ADR **部分修补** D1，但不关闭它，理由明写：

- 门禁点被覆盖后，`code_interpreter` 不再是无条件绕过——它需要用户点一次"允许"。
- 但那一次允许给出的就是**不受约束的任意执行**。用户批准一次 `code_interpreter`，等价于批准任意文件写入与联网。
- 因此分层仍在：P1（本 ADR）只管"有没有问过"，L1/L2/L3（ADR 0005）管"能做到什么"。P1 不是 L3 的替代品。

### D3. 读取的门禁按**敏感路径**判定，不是每次读

一次正常任务会读 10~30 个文件。逐次弹窗会把用户训练成无脑点允许，反而降低真实安全性。因此 `read_file` 只在两种情况下需要确认：

1. **路径在工作空间之外**——但这类路径通常已被 `file_access` 直接拒绝（见 D9），所以实际很少触发；
2. **文件名命中敏感模式**：`.env` / `.env.*` / `*.pem` / `*.key` / `*.pfx` / `*.p12` / `id_rsa*` / `id_ed25519*` / `.git-credentials` / `.npmrc` / `.pypirc` / `secrets.*` / `credentials*`。

风险不在"读普通源码"，而在"读走密钥"。这是第 2 条存在的理由。

### D4. 拒绝是**结果**，不是异常

`execute_tool` 刻意让异常向上抛（`registry.py:230-233`），因为调用方用异常把步骤标记为失败。**用户拒绝不是失败**，把它表达成异常会让 UI 与审计都记错。因此门禁返回 `ToolOutcome`：

- `model_text`：给模型的结构化说明，包含工具名、`reason`、以及"不要重复同样的调用，先问用户"的指引；
- `event_category` / `details`：给 UI 的决策记录。

模型据此能自己换方案或停下来问人，而不是对着一个 `Error: ...` 反复重试。

### D5. 无应答 = 拒绝（fail closed），默认 120 秒

等待确认有时间上限，超时按**拒绝**处理，`reason: "timeout"`。模型收到的是与"用户拒绝"同构的结果，只是原因不同。

反向（超时按允许处理）会让"用户不在电脑前"变成"默认放行一切"，与这个功能的目的直接相反。

### D6. 停止优先于超时

等待期间若收到任务停止请求（`should_stop()`，即 `main.py` 的 `_task_stop_events`），**立即中止等待**，不等超时。等待循环以短间隔轮询 `should_stop`。否则用户点了停止却要再等两分钟。

### D7. 模式：`ask` / `auto_approve` / `deny_all`

- 全局配置，默认 `ask`，可被任务创建请求覆盖（与既有 `max_steps`、`retention` 的配置形态一致）。
- `auto_approve`：从不询问，全部放行。**这是 headless（只通过 API 使用，没有界面）场景的唯一可用模式**——没有它，每个被门禁的调用都会阻塞到超时然后失败，这个功能会直接把 headless 用法打死。
- `deny_all`：全部拒绝。

### D8. 粒度：`once` / `session` / `always`

用户在对话框上可以选择：

- **允许一次（`once`）**：只放行本次调用；
- **本任务内允许（`session`）**：该任务内**同一工具 + 同一目标**后续调用自动放行，作用域仅限该任务的内存；
- **始终允许（`always`）**：写入 `data/permission_rules.json`，跨任务、跨重启生效；"配置"页可以查看与移除。

规则**刻意做窄**：一条规则只记「一个工具 + 一个精确目标」，不接受 `Bash(git push:*)` 这类模式。模式是目标设计，但在用户看不全的范围上自动放行，等于把"我确实看过的那一次"悄悄放大；精确目标不会。实现见 `agent/tools/permission_rules.py`，管理入口 `/api/admin/permission-rules`。作用域默认值一律是 `once`，未知的 scope 一律**报 400 而不是降级**——把 `always` 静默降级成 `once` 会让用户以为已经长期允许了（这个 bug 在集成测试里被真实捕获过）。

规则写盘失败时**不谎报**：调用照常放行，但决策事件与返回值里的 `scope` 退回 `once`，而不是声称有一个并不存在的长期许可。

### D9. 静态策略优先：已被 `file_access` 拒绝的不弹窗

`file_access` 的 `deny_dirs` / `deny_files` / `allow_dirs` / 工作空间约束是**硬拒绝**。这类路径直接拒绝，**不询问**。

弹窗意味着"可能允许"，与硬拒绝的语义冲突；而且用户点"允许"也无法让它通过（策略在工具内部仍会拒绝），会得到一个"我明明允许了却还是失败"的迷惑结果。

判定顺序因此固定为：**静态策略（硬拒绝，不问） → 权限模式 → 会话规则 → 询问**。

### D10. 事件与状态

- 新增事件类别 `permission_request`（待确认）与 `permission_decision`（决策结果，含 `allowed` / `reason` / `scope` / 决策人）。
- 新增 `TaskStatus.WAITING`。**同时必须修掉两条推流循环**：`_iter_task_events`（`main.py:1007`）与 WebSocket 循环（`:1090`）要把 `WAITING` 视为"仍在进行"，否则状态一置为等待，事件流立刻终止，用户永远收不到那条请求。
- 因此 `task_store` 需要一个中途改状态的入口（今天只有 `finish_task`，没有别的）。

### D11. 对话框给用户看什么

工具名 + **人话摘要** + 目标 + 参数摘录：

- `exec`：命令原文 + `description`（D5 预留的字段，这里的第 1 个真实消费者）；
- `edit_file`：文件路径 + `old_string` / `new_string` 摘录（截断到 8 KiB）**+ 写入前的 diff**；
- `write_file`：文件路径 + 内容摘录与字节数（截断到 8 KiB）；
- `read_file`：路径与命中敏感模式的原因。

**改动预览（diff）**通过 `ToolSpec.preview` 实现：`edit_file` 的 `make_edit_preview` 复用 `_prepare_edit`——读取、匹配、字节拼接**全部没有副作用**，所以"写入前给出 `gitDiff`"不需要第二条实现路径，只需要把写入那几步摘出去（ADR 0003 的 `gitDiff` 语义完全不变）。预览是**便利而非门禁**：它出错不影响是否询问，工具真正执行时会报出准确错误。

### D12. 这是**协作式确认**，不是安全边界

用户能看到并控制 Agent 的**意图**，但一旦放行，被放行的动作本身不受任何新增限制。`exec` 被批准一次就等于批准任意文件写入。因此：

- 用户可见文案不得宣称"已沙箱化"或"已阻止恶意操作"；
- 本 ADR 与 ADR 0005 的 L1/L2/L3 是**两条正交的轴**：P 轴管"问不问"，L 轴管"能做到什么"。

## 后果

- 权限判定与工具实现解耦：工具不需要知道自己会被询问，也不需要在 `file_access` 之外新增判断。
- `auto_approve` 模式下行为与今天完全一致，因此既有行为是这套机制的一个特例，而不是被替换掉的东西。
- `code_interpreter` 从"无条件绕过"变为"需要一次显式放行"，ADR 0005 D1 的风险面收窄，但**未关闭**。
- 工具描述里的"Does not pause execution"必须删改，否则模型会基于假信息决定是否调用（尤其 `exec` 的 `description` 参数——它现在真的会被展示）。
- 等待状态对 API 消费者可见（任务详情带 `pendingPermission`），headless 客户端可以据此实现自己的审批流，而不只是被动超时。

## 备选方案（未采用）

- **门禁写在各个工具内部**：工具拿不到 `EventSink`（术语表已定），且每加一个工具就多一个可能漏掉的门禁点。
- **只门禁文件三件套**：`exec` 与 `code_interpreter` 一步绕过，且界面会给人"已保护"的错觉。
- **读取也逐次确认**：一次任务几十次弹窗，会把用户训练成无脑允许。
- **超时按允许处理**：用户不在时等于全放行，与本功能目的相反。
- **把拒绝实现成抛异常**：调用方会把步骤标记为失败，UI 与审计记错，且模型会把"用户拒绝"理解成"工具坏了"而重试。
- **在等待期不做 `should_stop` 轮询**：用户点停止后仍需等满超时。
- **规则用模式而不是精确目标**（如 `Bash(git push:*)`）：覆盖面更省事，但用户无法完全看清一条模式会匹配到什么，而这正是"自动放行"最不该有的性质。等有了可靠的匹配预览再说。
