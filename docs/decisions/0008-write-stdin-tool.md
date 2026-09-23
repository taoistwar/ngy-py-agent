# ADR 0008: `write_stdin` 工具与"还活着的会话"

- 状态：已接受（Accepted）
- 日期：2026-09-23
- 相关：`agent/tools/process_store.py`、`agent/tools/write_stdin_tool.py`、`agent/tools/exec_tool.py`、`agent/tools/process_group.py`、`agent/tools/specs.py`
- 前置：[ADR 0005](0005-exec-tool.md)、[ADR 0006](0006-tool-permission-confirmation.md)

## 背景

`exec_command` 的 `run_in_background` 能启动一条命令并立刻返回，但那条命令是**只写不读**的：stdin 接的是 `DEVNULL`，输出只往日志文件里追加。结果是三种常见需求都做不到：

- 交互式程序（REPL、需要回答 y/n 的脚本、`git rebase -i` 这类）；
- 长跑命令的**中间**输出：只能等它结束，或者反复用 `read_file` 去啃日志；
- 把"卡住的提示"当成一个可回答的问题，而不是一次失败。

参考实现（Codex 的 `write_stdin`）给出的最小契约是：`exec_command` 若命令没结束就返回一个 `session_id`；`write_stdin(session_id, chars, yield_time_ms, max_output_tokens)` 找到那台没挂的电话，打字，再听一会儿，并把"还活着（session_id）"与"结束了（exit_code）"区分开。

## 决策

### D1. 后台命令即"会话"，不新造第二种执行方式

`run_in_background` 从"输出进日志文件的孤儿进程"升级为"可交互会话"：

- **stdin 用管道**（原来 `DEVNULL`），`process_group.start_with_log(..., stdin=PIPE)`；
- stdout/stderr **仍然**重定向到日志文件；
- 除了原有的 `pid`、`persistedOutputPath`、`pidFile`，结果里多一个 `session_id`。

保留 pid 与日志路径是刻意的：既有调用方与测试依赖它们，且日志路径仍是"完整输出在哪"的答案。

### D2. `process_store` 是唯一注册表

`session_id → (RunningCommand, log_path, read_offset)` 由 `agent/tools/process_store.py` 统一持有。`exec_command` 写入，`write_stdin` 读取；原先 `exec_tool` 内部的 `_BACKGROUND`（按 pid 存句柄）删除，`list_background()` / `stop_background(pid)` 改成它的薄封装。理由是**一个进程只应有一个权威句柄**：两份注册表迟早会不同步，而不问步的后果是把还活着的进程"忘了"。

命名上有一处需要记住：模型看到的是 `session_id`（对齐 `write_stdin` 契约），内部的键叫 `process_id`，因为 `session_id` 在本仓库已经表示"run/task 的输出目录作用域"。它俩是不同的东西。

### D3. 输出按日志文件增量返回，不加 reader 线程

后台命令的输出已经在日志文件里，`write_stdin` 只需记住"上次读到第几字节"，下次从那里继续读。**不再维护第二份内存缓冲**：那会带来背压、重复缓冲和"日志与缓冲不一致"三类新问题，而日志文件本来就是这一路输出的唯一通道。

### D4. 空 `chars` = 轮询；Ctrl-C 表示中断；其余 = 写 stdin

与参考一致：

| 输入 | 语义 |
| --- | --- |
| `chars = ""`（默认） | 只轮询新输出，不写任何字节 |
| `chars = "\u0003"` | **中断**命令（停止整棵进程树），不走普通写入 |
| 其它 | 写入命令的 stdin（要发整行就自己带 `\n`） |

`yield_time_ms` 按模式收窄：轮询抬到 `5000–300000 ms`，写入最多 `30000 ms`，默认 `250 ms`。轮询更耐心、写入更跟手，是刻意的：轮询是在等程序说话，写入是在等自己的手感。`max_output_tokens` 默认 `10000`，并被本次运行配置的输出预算再压一次。

### D5. 输出是"带表头的文字"，死活由 session_id / exit_code 判断

模型看到的就是参考里那段：

```
Chunk ID: 3f9a1c
Wall time: 0.2531 seconds
Process running with session ID 7
Original token count: 42
Output:
>>> 1
```

字段含义与参考一致（`chunk_id` 追踪、`wall_time_seconds` 等待时长、`original_token_count` 截断前 token 数、`output` 正文）。**有 `session_id` 就是还活着，有 `exit_code` 就是结束了**；一旦确认退出，会话立刻从 `process_store` 移除并释放句柄与管道——"结束了还能继续打字"是不允许的。

### D6. 权限按会话确认

`write_stdin` 声明 `exec` 种类（往一条活着的命令里灌任意输入，风险等价于直接跑命令）。门禁目标取 `session:{session_id}`，因此**一次批准只覆盖这一台终端，不会顺带放行所有 `write_stdin`**。参考实现这里的 guardian review 与此同向。

### 明确偏离参考：没有 PTY

本仓库的命令跑在普通管道上，没有伪终端。后果必须写明：

- 需要 TTY 的程序（`top`、密码提示、行编辑）**不会**表现得像交互式；
- 参考实现"非 PTY 只允许 Ctrl-C、其余输入一律拒绝"的限制**不采纳**——本仓库只有普通管道，照搬会让 `write_stdin` 除了打断之外毫无用处。这里允许写管道 stdin，并把"需要 TTY 就不行"作为已知限制写明。

## 后果

- 模型可以启动一个 REPL/长跑任务，注入输入、分段取回输出，再决定是继续喂还是打断。
- `session_id` 与 `pid` 现在同时存在，语义不同：pid 用于"这是哪个进程"，session_id 用于"和谁对话"。两者都在结果里给出，避免模型自己换算。
- 会话不再依赖日志文件的"读得到就能改"路径策略：`write_stdin` 读的是注册表里的路径，不是工作空间路径。
- 新增 CLI 之外的工具，`agent/tools/specs.py` 与 `registry.py` 各加一行即可（沿用既有惯例）。
- 未回收的会话：命令结束后由调用方 `retire`；进程在 agent 退出时随 Job/pgid 一起消失（ADR 0005）。

## 备选方案（未采用）

- **给 `exec_command` 加 `yield_time_ms`，做成 Codex 那样的统一 exec**：会改掉现有 `run_in_background` 的返回契约与既有测试，收益只是参数名字更贴近参考；本轮以"新增工具、不动既有行为"为界。
- **开一个 reader 线程把输出收集到内存**：与 D3 重复，且要处理背压与线程退出，收益不明显。
- **引 PTY（Windows 上尤其昂贵）**：能覆盖更多交互程序，但平台差异大、失败模式多；留作后续独立子项目。
- **不设 `max_output_tokens`，直接返回全部新输出**：一条 `yes` 就能撑爆上下文，与 ADR 0005 D4/D8 对输出的克制相矛盾。

## 设计评审修订（2026-09-23）

一轮设计评审确认或改动了以下各点；本文上半部分仍是原始决策，**以本节为准**。标"待定"的部分由下一轮评审补齐。

- **D1 保留**："后台即会话"不变，不给 `exec_command` 加 Codex 风格的 `yield_time_ms`；代价是**前台超时命令不可附着**，要靠 `run_in_background` 预判。工具描述需明确写出这一点。
- **D2/D3 保留**：普通管道（无 PTY）、按日志文件增量读输出（不加 reader 线程）。
- **D4 修订**：Ctrl-C 在 POSIX 改为对 pgid 发 **SIGINT**（更接近真实 Ctrl-C）；在 `TERMINATE_GRACE_SECONDS` 内没退出再升级为 SIGKILL。Windows 没有等价物，仍由 Job 终止——平台差异写进工具描述。
- **D6 保留**：权限仍声明 `exec` 种类、目标 `session:{id}`；但需避免"always allow"写出永不命中的持久化规则（处置方式待定）。
- **新增 D7（会话归属与回收，待定）**：`Session.meta` 记录 `task_id`；任务结束时回收本任务活会话；`session_id` 视为 capability，跨任务一律按"未知会话"处理；另有容量上限与 TTL 兜底。**回收钩子的挂载点、回收时是"杀"还是"放生"、跨任务隔离强度、上限/TTL 数值均待定。**
- **新增 D8（超预算输出，待定）**：与 ADR 0005 D4/D8 对齐——超预算的那一段输出落盘到既有输出根并返回路径，模型用 `read_file` 读回，而不是只截断。**落盘目录/命名细节待定。**
- **保留不做**：不做"列出活会话"的发现工具；`ask` 模式不包含 `write_stdin`；不支持 EOF/关闭 stdin。
- **术语**：模型可见的 `session_id`（可交互进程）与 run-scope 的 `session_id`（输出目录作用域）是两个概念，`docs/glossary.md` 已分列说明。

## 定稿（2026-09-23）

上一节标为"待定"的各项在此落定，代码已按此实现：

- **回收钩子**：挂在 `agent/agent_loop.py` 的收尾包装器上（`run_react_loop` 被 `_reaps_task_sessions` 包住），凡是传入 `task_id` 的调用在返回时都会 `stop_task`——API 任务（`main.py:790`）走的就是这条；**不传 `task_id` 的调用**（交互式 CLI 的 REPL、部分库用法）**不属于任何任务**，其会话由容量上限、TTL 与 `atexit` 兜底。给 REPL 补一个 per-query 任务标识是后续可选工作。
- **回收语义**：任务结束**显式停止**本任务会话。不采用"丢句柄"：那在 Windows 上会杀掉整棵树（`KILL_ON_JOB_CLOSE`）、在 POSIX 上却让进程继续活着，同一份代码两种结果。因此不存在"活过任务"的后台命令；需要长跑服务就让用户自己在终端起。
- **隔离**：校验 `task_id + workspace`，不匹配一律按"未知会话"回答，不泄露存在性（`session_id` 当 capability 用）。
- **上限 / TTL**：每任务活会话上限 8，超限**拒绝**新启（先 sweep 掉已退出与超 TTL 的僵尸再计数），而不是杀旧会话——那会毁掉模型正在进行的交互；TTL 30 分钟，与 `MAX_TIMEOUT_MS` 同量级。
- **中断**：`chars` 为 `\u0003` 时 POSIX 对 pgid 发 SIGINT，宽限期内未退出再 SIGKILL；Windows 没有等价信号，仍由 Job 终止。
- **超预算输出**：落盘到既有输出根并返回 `persistedOutputPath`，模型用 `read_file` 读回。
- **权限 scope**：`write_stdin` 只提供 `once`/`session`；对话框按请求携带的 `scopes` 渲染，API 对越界 scope 返回 400（不静默降级），broker 内部对直接调用者仍保守回退为 `once`。
- **事件类别**：复用 `exec`——`write_stdin` 是同一条命令的延续，拆成两类会让"这条命令发生了什么"在时间线上断开。
- **明确不做**：不提供"列出活会话"的工具；不支持 EOF/关闭 stdin；不修"长阻塞工具期间无法响应停止"——`exec_command` 前台最长阻塞 30 分钟且同样不检查停止信号，属既有问题，记为后续子项目。

> **后续结构变更（同日，工具目录重构）**：工具声明已从 `agent/tools/specs.py` 移入**各工具包的 `spec.py`**，由 `agent/tools/catalog.py` 汇总、`agent/tools/bindings.py` 提供运行期绑定，`specs.py` 已删除。本文上方"相关"里的 `agent/tools/specs.py`，以及 D7 提到的 `write_stdin_tool.py` / `exec_tool.py`，请按 `agent/tools/spec.py`、`agent/tools/write_stdin/`、`agent/tools/exec_command/` 理解；决策内容不受影响。
