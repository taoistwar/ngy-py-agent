# ADR 0019: 取消要能打断正在跑的命令

- 状态：已接受（Accepted）
- 日期：2026-10-28
- 相关：`agent/tools/bindings.py`、`agent/tools/registry.py`、`agent/tools/exec_command/`、`agent/tools/write_stdin/`、`agent/agent_loop/loop.py`、`agent/agent_loop/runtime.py`、`test/tools/exec_command/exec_command_test.py`、`test/tools/exec_command/tty_test.py`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（工具权限确认）、[ADR 0008](0008-write-stdin-tool.md)（后台会话）、[ADR 0009](0009-exec-tty.md)（终端传输）

## 背景

取消这件事**本来就有**，而且是完整的：

| 环节 | 位置 |
| --- | --- |
| HTTP 入口 | `POST /api/tasks/{task_id}/stop`，`task_api.py:153` |
| 信号 | 每任务一个 `threading.Event`，`app_state.signal_task_stop` |
| 工具层 | 权限与提问 broker 每 0.25 秒轮询一次 `should_stop` |
| 循环层 | step 边界检查一次，每个 tool call 之间再检查一次 |
| 收尾 | 循环退出时 `process_store.stop_task` 杀掉该任务的后台会话 |
| UI | 任务行按钮 → `stopTask` |

问题出在**检查点只有那两个**：一个正在执行的工具调用是打不断的。于是：

- `exec_command` 前台阻塞在 `communicate(timeout)` 上，`timeout` 上限是 **30 分钟**（`MAX_TIMEOUT_MS`）。用户点了停止，屏幕上可以继续刷 30 分钟的 build 日志。
- `write_stdin` 的一次 poll 最长等 **300 秒**（`POLL_MAX_YIELD_MS`），同样不读停止标志。

这不是"取消没实现"，而是"取消的承诺和它的延迟对不上"：按钮说停，界面却像没反应。这个差距在用户那里是**功能坏了**，不是"稍后生效"。

## 决策

### D1. 停止信号以回调下传，工具层不认识应用状态

`ToolBindings` 新增 `should_stop: Optional[Callable[[], bool]]`，由 `run_react_loop` → `_build_runtime` → `ToolRegistry` → 各工具包一路传下去。

用回调而不是事件对象，有两个理由：

1. 工具层不该 import `app_state`——那是应用层，`agent/` 要能脱离服务端单独跑；
2. CLI 没有取消通道，传 `None` 就是"永不停止"，不需要为一个不存在的场景造一个空事件。

### D2. 阻塞等待改为分片轮询

前台命令的等待从"一次长等待"改成"每 0.25 秒一片"，每片之前先看停止标志。

两条关键约束：

- **管道必须走 `communicate`，不能走 `process.wait()`。** 只等进程而不读管道，子进程写满缓冲区就会卡死——这正是 `communicate` 存在的原因。`communicate` 在 `TimeoutExpired` 之后可以重试且不丢输出，所以切片是安全的。
- **终端路径本来就在轮询**（终端没有管道可读），所以切片对它零成本。

### D3. 中断原因必须分类

同样是 `interrupted=true`，用户停止和命令超时是两件事，模型看到的文案必须不同：

- 超时：`The command was stopped after N ms and its process tree was terminated.`
- 停止：`The command was interrupted because the task was stopped...`（不提时长——提了就是把原因错误地归给时钟）

结果里记 `interrupted_by: "task_stop" | "timeout" | null`，让 UI 和排查能区分。

### D4. `write_stdin` 的轮询也读停止标志

一次 poll 最长 300 秒，比大多数超时都长。等待是为了"给命令时间打印"，不是为了"盖过用户的取消"，所以循环里一并检查。

### D5. 后台会话的清理留在既有边界

后台命令是模型在对话的会话，不是被打断的等待：循环退出时 `process_store.stop_task` 已经在收。本次不改这条路径，避免出现"停止时杀一半、退出时再杀一半"的两套逻辑。

### D6. 不做线程强杀，并明确写下这条缺口

Python 没有安全的线程中断手段。本次能打断的是**等待**，不能打断**计算**：

- `code_interpreter` 是进程内 `exec()`，一个死循环仍然会把任务线程占住；
- 正在进行的模型 HTTP 请求是单次阻塞调用，只能等它返回或超时。

把这条写进 ADR 而不是留给读者猜，是因为"取消"这个词容易被理解成"立刻断电"。它现在的含义是：**在一个等待点上，最迟 0.25 秒后生效**。

## 影响

- 停止的感知延迟从"命令自己的 timeout（最长 30 分钟）"降到 0.25 秒。
- `exec_command` 的 `details` 多一个 `interrupted_by` 字段；既有 `interrupted` 语义不变，读旧字段的消费者不受影响。
- `ToolBindings`/`ToolRegistry`/两个注册表工厂各多一个可选参数，默认 `None`，既有调用点无需改动。

## 未覆盖

- 模型请求本身不可中断（见 D6）。
- `code_interpreter` 的 `exec()` 不可中断（见 D6）。
- 停止后不会自动回退磁盘改动，那是 [ADR 0020](0020-checkpoint-rewind.md)。
