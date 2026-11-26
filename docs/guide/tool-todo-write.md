# 工具：`todo_write`（任务清单）

模型在动手前把计划写成一份有序清单，并在执行过程中更新每一步的状态。它**只改计划**，不执行任何操作：没有文件、没有网络、没有权限闸门（`permission = none`）。`build` 模式（全部工具）可用；`ask` / `plan` 两个模式没有这个工具。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `todos` | array | 完整计划，按顺序。每项含 `content`（非空、一句话）与 `status`（`pending` / `in_progress` / `completed`）。最多 20 项；同时最多一项 `in_progress`。 |

每次调用**替换整份清单**，不是追加：已完成的步骤要保留并标成 `completed`。传空数组 `[]` 就是清空计划。

模型拿到的结果是规范化后的清单：

```text
Todo list (1/3 completed)
[x] 读一遍解析器
[>] 先写会失败的测试
[ ] 修解析器
```

## 清单属于会话，不属于单次任务

- 计划按 **session** 持久化（`session_todos` 表，一行一个会话），同一会话里的后续任务会继续用它；新任务启动时，系统提示里会带上这份计划并要求"接着做，不要重开一份"。
- `GET /api/tasks/{id}` 的 `todos` 字段返回该任务所在会话的计划，因此 Web Admin 的 1 秒任务轮询就是同步机制：任务线程改了状态，面板下一次轮询就更新，不需要额外的推送通道。
- 面板（`web-admin/src/components/TodoPanel.jsx`）固定在任务详情页两个页签**上方**：任务在跑时界面会自动切到日志页签，而计划正是这份日志在执行的东西。

## 提醒（reminder）

连续 **3 个**工具调用轮次没有调用 `todo_write` 时，Harness 会把 `<reminder>Update your todos.</reminder>` 追加到该轮最后一个工具结果里（不是新起一条 user 消息），并在任务日志里记一条 `Todo reminder sent` 的 debug 事件，随后计数清零。没有注册这个工具的模式（`ask` / `plan`）不会收到提醒。

## 相关文件

- 工具包：`agent/tools/todo_write/`（`description.py` 声明、`items.py` 校验与渲染、`tool.py` 调用）
- 会话绑定：`agent/tools/todo_store.py`（`TodoBoard` / `TodoStore`）、`agent/runtime/todos.py`（数据库适配）
- 持久化：`dao/todos.py`
- 循环接入：`agent/agent_loop/todo_context.py`（继承既有计划）、`agent/agent_loop/todo_reminder.py`（提醒计数）
