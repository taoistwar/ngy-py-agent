# ADR 0025: 根目录只留 `main.py`——应用层拆进 `commons` / `dao` / `agent.runtime`

- 状态：已接受（Accepted）
- 日期：2026-11-16
- 相关：`main.py`、`commons/`、`dao/`、`agent/runtime/`、`agent/history.py`、`agent/usage.py`、`test/`、`docs/dev.md`
- 修订：[ADR 0019](0019-cancel-interrupts-running-work.md) D1 的分层约束（把"工具层不碰应用层"收窄成一条可执行的规则）

## 背景

`main.py` 早在第一次拆分里就被拆掉了1700 行（`docs/dev.md` 第 13 节），但拆出来的东西全留在根目录，于是"根目录"变成了"应用层"：`api_schemas.py`、`app_state.py`、`context_usage.py`、`llm_store.py`、`mcp_store.py`、`session_history.py`、`task_runtime.py`、`task_usage.py` 与入口平级。三个具体后果：

1. **看不出分层。** `agent/` 是引擎、`routes/` 是 HTTP、`dao` 那一层却散在根目录；新表该往哪写、新状态该往哪放，只能靠读 import 猜。
2. **两个文件顶到行数红线。** `api_schemas.py` 693 行（`AGENTS.md` 的 ~700 上限），`task_runtime.py` 595 行且同时管解析、命名、清理、执行四件事。
3. **依赖方向被目录抹平。** `dao/store.py` 反向 import 根目录的 `llm_store`；`session_history` / `context_usage` 直接抓 `app_state`，与 `routes/` 平级，看不出谁在上层。

## 决策

### D1. 根目录只允许 `main.py` 一个源码模块

目录不算：`agent/`、`routes/`、`commons/`、`dao/`、`task_recovery/`、`test/`、`docs/`、`scripts/`、`web-admin/`、`data/` 照旧。新增的应用层代码只能进已有包，不再往根目录加 `.py`。

### D2. 三个桶

| 桶 | 放什么 | 判据 |
| --- | --- | --- |
| `commons/` | `state.py`（进程活状态）+ `schemas/`（全部请求/响应模型） | 被路由和任务运行**共同**依赖、且不碰数据库的东西 |
| `dao/` | 全部 SQLite 读写（任务、会话、事件、设置、provider、model、MCP） | 只要碰表，就进这里 |
| `agent/` | 引擎（`agent_loop`、`provider`、`tools`、`telemetry`、`checkpoints`）+ 任务生命周期（`runtime/`、`history.py`、`usage.py`） | 与"跑一个 agent 任务"直接相关 |

### D3. `commons/__init__.py` 不 re-export

`from commons import state` 才会建存储；如果 `commons/__init__` 里 re-export 了 `state`，任何只想拿 schema 的进程（比如一个纯数据校验脚本）都会连带建库、起单例。所以这个文件只有文档。

### D4. `dao/` = 原 `task_store/` 改名 + 收编三块存储

- 内部分法不变：`base` / `schema` / `sessions` / `forks` / `agents` / `settings` / `tasks` / `store`（组合类）。
- 新增 `dao/llm.py`（providers + models，共用 `dao.store` 的连接与锁）与 `dao/mcp.py`（自管连接，同一个库文件）。反向依赖 `dao/store.py → dao/llm.py` 变成包内 import。
- 类名与单例名**不改**（`_SqliteTaskStore`、`monitor_store`、`llm_store`、`mcp_store`）：这次只改路径，语义改名留给真正需要它的改动。

### D5. `agent/runtime/` 按职责拆包，`agent/__init__.py` 不 re-export

`task_runtime.py` → `events`（事件构造与结果提取）、`config`（provider / 工作目录 / 步数 / 确认模式 / AGENTS.md 解析）、`naming`（会话标题与任务名）、`purge`（保留期清理）、`runner`（`run_task` + `_execute_task`）。`__init__.py` 只做 re-export，调用方仍写 `from agent.runtime import run_task`。

`agent/__init__.py` 是**新建**的（此前是隐式命名空间包），并且**只放文档**：一旦它 re-export 任何子模块，`commons.state → agent.agent_loop` 就会顺手把 `agent.runtime → commons.state` 拉起来，产生真正的循环导入。

### D6. 分层规则（对 ADR 0019 D1 的收窄）

ADR 0019 说"工具层不该 import `app_state`"，那句话说对了一半：它真正保护的是**工具实现能脱离服务端单独测**。放宽到整个 `agent/` 就会误伤任务生命周期——`run_task` 本来就要读活状态。精确规则：

1. `agent/tools/**` 与 `agent/agent_loop/**` **不得** import `commons/**`、`dao/**`（ADR 0019 原文的约束对象）。
2. `agent/runtime/**`、`agent/history.py`、`agent/usage.py` **可以** import `commons.state`——它们执行任务或统计任务。
3. `commons/**` 可以 import `agent/**` 与 `dao/**`；`dao/**` 只能 import `agent` 的下层（今天只有 `agent.models` 与 `agent.provider`），不得 import `commons` 与 `routes`。
4. `routes/**` 不得 import `main`；`main` 单向 import 全部。

由此 `agent` 与 `commons` 在包级是**双向**的：`commons.state` 要 import `agent.agent_loop` / `agent.tools`，`agent.runtime` 要 import `commons.state`。这在模块级不会成环，因为两个包的 `__init__.py` 都是空的（D3、D5），Python 只会执行被点名的子模块。这条约束靠 code review 守，没有静态检查。

### D7. 迁移期间必须同步改的四处

1. `commons/state.py` 的 `ROOT_DIR`：原 `app_state.py` 用 `Path(__file__).parent`（即"自己在根目录"），移动后改 `parents[1]`。
2. `main.py` 的 `uvicorn_run("main:app", app_dir=ROOT_DIR)`：`main.py` 不能动位置，否则 reload 子进程找不到 app。
3. 测试镜像：`test/session_history_test.py` → `test/agent/history_test.py`、`test/task_usage_test.py` → `test/agent/usage_test.py`、`test/task_store_test.py` → `test/dao/store_test.py`，`parents[N]` 同步 +1；其余测试只改 import 行。
4. `compileall` 的目标从 `main.py agent/agent_loop` 扩到 `main.py agent commons dao routes`（`scripts/ci_check.py` 与 `.github/workflows/ci.yml` 两处），否则新包里的语法错在 CI 里是静默的。

### D8. 不留兼容 shim

不做 `app_state.py` 转发到 `commons.state` 之类。理由：shim 本身就是根目录 `.py` 文件，与 D1 直接冲突；而且它会让"旧路径还能用"变成事实标准。调用方一次改完（本次约 60 处 import）。

## 后果

**正面**

- 根目录一眼可读：入口只有一个，其余按"状态与契约 / 持久化 / 引擎"分桶。
- `api_schemas` 693 行拆成 8 个资源模块，`task_runtime` 595 行拆成 5 个职责模块，都在 `AGENTS.md` 红线以下。
- 新增一张表 → `dao/`；新增一个请求模型 → `commons/schemas/<资源>.py`；新增一步任务逻辑 → `agent/runtime/`。落点不再需要讨论。

**负面**

- `agent` 与 `commons` 包级互相依赖（D6），读代码时要记得"哪个子包允许越界"。这条规则写在两个包的 `__init__.py` 文档里，但它不是自动检查。
- 测试的 `parents[N]` 有三档（`[1]`/`[2]`/`[3]`），移动任何模块都得跟着数一次。
- 老 ADR 里"相关文件"的路径（`llm_store.py`、`task_runtime.py` …）已失效。按本仓库惯例，历史 ADR 不改写，以本文与 `docs/dev.md` 为准。

## 备选（未采纳）

| 方案 | 为什么不选 |
| --- | --- |
| 单一 `server/` 应用包（`server/state.py`、`server/schemas/`…） | 分层最干净（`commons`/`agent` 不会互相依赖），但把"任务编排"和"引擎"割在两个顶级包里，与"agent 相关的放 agent 下"的直觉相反 |
| 每个模块升级成同名包（`app_state/`、`api_schemas/`…） | import 字面不变、改动最小，但根目录从 8 个文件变成 8 个目录，70 行的模块成包纯属噪音 |
| 语义分组多目录（`state/`、`schemas/`、`runtime/`、`usage/`） | 每个目录往往只有一个真文件，碎片化 |
| 保留旧模块名的转发 shim | 见 D8 |
