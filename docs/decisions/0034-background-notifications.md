# ADR 0034: 后台命令的完成通知——占位结果之后，消息从哪里来

- 状态：已接受（Accepted）
- 日期：2026-11-27
- 相关：`agent/tools/background.py`、`agent/agent_loop/background_context.py`、`agent/agent_loop/loop.py`、`agent/tools/exec_command/tool.py`、`agent/tools/bindings.py`、`agent/tools/registry.py`
- 前置：[ADR 0008](0008-write-stdin-tool.md)（后台命令即会话）、[ADR 0019](0019-cancel-interrupts-running-work.md)（取消）、[ADR 0016](0016-micro-compact.md)（工具结果预算）

## 背景

`exec_command(run_in_background=True)` 从 ADR 0008 起就有：立刻返回 `pid`/`session_id`/日志路径，命令作为会话继续跑，模型可以用 `write_stdin` 打字、用 `read_file` 读日志。

问题是**没有人告诉模型它结束了**。一次工具调用只有一个结果，占位结果已经用掉了；模型只能主动轮询（`write_stdin` 或反复 `read_file`），而那正是参考实现（`learn-claude-code/s11_background_tasks`）用 `<task_notification>` 去掉的动作。

## 决策

### D1. 每次运行一份台账，不用线程等待

`BackgroundTasks`（`agent/tools/background.py`）只做两件事：`track()` 记下刚启动的后台会话，`collect()` 报告"已经结束、还没报告过"的那些。

没有 waiter 线程：一个命令一个线程要和 `process_store` 的所有权与清理规则重复一遍（会话可能被 `write_stdin` 提前 retire、被下一次注册的 `sweep()` 清掉），而循环本来就要再跑一轮——"下一轮之前告诉你"就是通知的承诺。代价：循环不再继续时不会再有通知（参考实现同样如此）；此时命令也会在任务边界被统一停掉。

### D2. 通知是一条独立的 `user` 消息

```
<task_notification>
Background command finished: Install dependencies (exit code 0)
session 4a9c1e02 (pid 18344); output: .../20261127-101500-812233.log

Last output:
added 212 packages in 8s
</task_notification>
```

- 不复用原来的 `tool_call_id`：那次调用已经有结果了，重复 id 会让 transcript 非法。`task_recovery` 按 `tool_call_id` 重建对话，也不受影响。
- 用 `user` 而不是 `tool`：这段文本不属于任何调用，模型读它的方式就是"harness 告诉你，你起的东西完了"。循环里追加图片消息已经是同一个形状（`agent/vision`）。
- 同一轮的多个完成合并成一条消息，避免一次多出一条。

### D3. 收集点在每轮模型调用之前

`run_react_loop` 在步首（`apply_snip_compact` 之后、`prepare_context` 之前）调用 `inject_background_results()`：报告进入的正是模型接下来要读的上下文，也参与上下文预算估算。

顺序是刻意的：先压缩再注入，通知就不会被当作"可挪走的旧工具结果"处理。工具结果预算只处理本轮 `batch_start` 之后的 `tool` 消息，与 `user` 通知无关。

### D4. 报告即收尾

`collect()` 发现进程已结束（或会话已被别人 retire）时：取 `exit_code`、读日志末尾 600 字符、**retire 会话**、从台账删除。这与 `write_stdin` 看到进程结束时的做法一致，句柄不会因为"已经通知过"而多留一份。退出码取不到（会话已被 `write_stdin` 收走）时明确写 `exit code unknown`，不猜。

通知带日志末尾而不是只给路径：`exit code 1` 加上最后一行通常就是答案，让模型再花一轮 `read_file` 才能知道发生了什么，等于把省下的轮次又还回去。

### D5. 绑定与可见性

- 台账由循环创建（`run_react_loop` 的 `background` 参数，`None` 时自建一份），经 `_build_runtime` → `ToolRegistry` → `ToolBindings.background` 传到 `exec_command`；工具层其余部分不感知它。
- 子 agent 的 registry 是新建的（父工具集减去 `subagent` 自身，ADR 0032），所以台账要**显式传过去**（`_build_child_registry` 里 `background=getattr(parent, "background", None)`）：子 agent 启动的后台命令记在父台账里，由父循环通知，父循环也是唯一会来收的地方——不会丢，也不会重复。`todo_board` 相反，故意不共享（子 agent 的计划是它自己的）。
- 前端不加新通道：通知本身是一条 `debug` 事件（`Background command finished`，含 session、pid、退出码、日志路径），在任务日志里可见；状态变化仍由已有的 1 秒轮询呈现。日志视图给它一条专门的记录（`web-admin/src/events/friendlyEvent.js::buildBackground`，一条命令一个分块，退出码读不到时标 `unknown` 而不是算成功），而不是按通用 debug 记录渲染——那样读者看到的是 `count`/`commands` 这类原始键名。

## 后果

- 模型侧：`exec_command` 描述与 `run_in_background` 参数说明改为"结束时会在后续轮次收到 `<task_notification>`，不要轮询"，六种语言的展示文案同步更新。
- 已知限制：
  - 通知依赖循环继续；模型在启动后台命令后直接结束任务，就收不到结果（命令也会被停掉）；
  - 一次运行最多 8 个并发会话（`process_store.MAX_LIVE_SESSIONS_PER_TASK`，未改）；
  - 日志末尾固定 600 字符，不按 token 预算裁剪；
  - 台账只在内存里，进程重启后已启动的命令与其通知一起丢失（会话由 `process_store` 的 TTL 与 `atexit` 兜底）。
