# 任务板（`task_create` / `task_update` / `task_list` / `task_get` / `task_claim` / `task_complete`）

任务板是**项目级**的工作图：每个任务有 id、状态、负责人（owner）和前置依赖（`blocked_by`）。它解决的是 `todo_write` 解决不了的问题——依赖和分工：数据库表建好之后才能写 API，API 定了才能写测试；同一个工作区的另一次会话可以接着做。

| | `todo_write` | 任务板（`task_*`） |
| --- | --- | --- |
| 定位 | 当前会话正在做的步骤 | 项目还没做完的工作 |
| 存储 | 会话（`session_todos`） | 工作区（`board_tasks`） |
| 依赖 | 无 | `blocked_by` 依赖图 |
| 生命周期 | 跟随会话 | 跨会话保留 |
| 分工 | 不认领 | `owner` + `task_claim` |
| 更新方式 | 整表替换 | 单条 CRUD |

## 工具

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `task_create` | `subject`（必填）、`description` | 新建 pending、无主的任务，返回 `task_xxxxxxxx` 形式的 id |
| `task_update` | `task_id`、`add_blocked_by`（非空数组） | 追加前置依赖；只能改 pending 且无人认领的任务 |
| `task_list` | — | 每个任务一行：状态、owner、是否可开始、被谁阻塞 |
| `task_get` | `task_id` | 单个任务全文（含 description，续做别人的任务时用） |
| `task_claim` | `task_id` | pending → in_progress，记下 owner（本会话） |
| `task_complete` | `task_id` | in_progress → completed，并报告这次完成解锁了哪些任务 |

两阶段建图：先 `task_create` 拿到所有 id，再用 `task_update` 连边。同一条回复里的多个工具调用在结果产生前就已确定，所以一次调用拿不到另一次调用刚生成的 id。

## 规则

- **可开始** = `pending` 且没有 owner 且 `blocked_by` 全部 `completed`。前置任务文件/记录不存在也算阻塞（缺失不等于完成）。
- **状态机**：`pending --claim--> in_progress --complete--> completed`，没有反向或跳步。
- **owner 是会话**，由应用层注入，不是工具参数：模型不能给自己起名去认领或完成别人的任务。别人的任务只能由那个会话完成，错误会说明 owner。
- **拒绝按信息返回**，不是失败：被阻塞的认领返回「blocked by task_xxx」，认领别人的任务返回「owner_mismatch」，未知 id 返回「not_found」。工具结果的 `details.reason` 带同样的枚举。
- 只拒绝渲染不出来的输入：空 subject、超长 subject（200）或 description（4000）、依赖超过 50 条、自依赖、环、未知 id。

## 工具页分组

`todo_write` 与六个 `task_*` 工具在「工具管理」页统一归到 **任务管理**（`category = task`）这一组：同一个会话的清单和项目级的任务板是同一件事的两个层级，放在一起才好比较。分组常量见 `agent/tools/spec.py` 的 `CATEGORY_TASK`，前端的顺序与文案见 `web-admin/src/components/admin/toolMeta.js`。

## 任务板属于谁

`board_id` 有两段式取值：

- 会话绑定了工作区 → `workspace:<workspace_id>`：该工作区所有会话共享同一块板；
- 会话没有工作区 → `session:<session_id>`：这次会话自己一块板。

删除工作区时，它的板一并删除（`dao/sessions.py`）。

## 前端

任务详情页在「任务清单」下面显示「任务板」面板，数据来自 `GET /api/tasks/{id}` 的 `board` 字段——复用前端已有的 1 秒轮询，任务线程改了状态，面板下一次轮询就更新。每行按「进行中 → 可开始 → 阻塞 → 已完成」排序，显示状态标签、阻塞它的任务名和 owner 的会话名。

## 已知限制

- 没有「释放认领」：被放弃的 in_progress 任务只能由原会话完成。需要时删掉工作区或直接改库。
- 只支持 `add_blocked_by`，不能删依赖；依赖图在任务被认领后冻结。
- 任务板不与 `todo_write` 同步：清单是即刻步骤，板是项目计划，两者都由模型各自维护。

## 相关文件

- 工具包：`agent/tools/task_create/`、`task_update/`、`task_list/`、`task_get/`、`task_claim/`、`task_complete/`
- 规则：`agent/tools/task_board.py`；存储契约与绑定：`agent/tools/task_store.py`
- 数据库：`dao/board_tasks.py`；应用层绑定：`agent/runtime/board.py`
- 前端：`web-admin/src/components/TaskBoardPanel.jsx`
