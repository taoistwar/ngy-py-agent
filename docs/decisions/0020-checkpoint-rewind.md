# ADR 0020: 任务改动的快照与回退

- 状态：已接受（Accepted）
- 日期：2026-10-28
- 相关：`agent/checkpoints/`、`agent/tools/registry.py`、`agent/agent_loop/runtime.py`、`agent/modes.py`、`test/checkpoints/checkpoint_store_test.py`
- 前置：[ADR 0003](0003-edit-write-and-patch.md)（写与改）、[ADR 0005](0005-exec-tool.md)（shell）、[ADR 0006](0006-tool-permission-confirmation.md)（权限闸门）、[ADR 0019](0019-cancel-interrupts-running-work.md)（取消）

## 背景

需求：任务跑完之后，能不能把这个任务改过的东西退回去。

现状是**没有任何快照机制**：全仓库没有 checkout / stash / backup / snapshot 逻辑，工作空间也不要求是 git 仓库。能改盘的东西分四层，成本和可见性差一个量级：

| 层 | 路径 | 现有记录 |
| --- | --- | --- |
| A | `write_file`、`edit_file` | 事件里已有 `original_file` 全文与 `created` 标记 |
| B | `exec_command`、`write_stdin` | 无。任意 shell：`git` / `mv` / `rm` / 构建产物 |
| C | `code_interpreter` | 无。进程内任意 Python |
| D | `computer_control` | 无。宿主桌面，[ADR 0011](0011-computer-use.md) 明确无回放 |

只做 A 层看起来最省事——事件表里就躺着原文，`created=true` 的回退就是删文件。但它的失败模式很糟：用户点了"回退"、界面显示成功，而模型刚跑的 `npm install`、`git checkout`、`rm` 一个都没撤。**一个有假阳性承诺的撤销，比没有撤销更伤信任。**

A 层方案还有两个隐性代价：`original_file` 是全文塞进 SQLite 的 JSON，大文件会顶爆 `events` 表；`TASK_RETENTION_DAYS` 到期 purge 时，回退能力跟着历史一起消失。

## 决策

### D1. 覆盖 A+B+C 层，用影子 git；D 层明确不做

`exec_command` 和 `code_interpreter` 都可能改任意文件，所以快照必须看全树。既然要看全树，git 就是最便宜的实现：增量存储、二进制、忽略规则、以及"恢复到某个树"这件本来就写对的事。

`computer_control` 操作的是宿主桌面，没有可重放的输入流，**不在覆盖范围**。这一条写在这里，是为了以后不要有人以为"回退"能撤销一次点击。

### D2. 每 workspace 一个 bare 仓库，放在工作空间**外面**

仓库在 `data/checkpoints/<workspace-key>/repo`，每次调用都显式传 `--git-dir` 与 `--work-tree`：

- **不碰用户的 `.git`**：不读它的配置、不动它的 index、不留任何引用。工作空间不是 git 仓库也照样工作。
- **bare + 显式 work-tree**：工作树是调用参数而不是仓库属性，工作空间搬家或换个路径拼写都不用迁移。
- `core.autocrlf=false`：存的是字节。任何换行转换都会让回退去重写任务没碰过的文件。
- workspace key 是路径的 sha1（Windows 下大小写折叠），同一个目录的两种写法必须落到同一个仓库。

### D3. 一任务一分支：归属靠分支，不靠对比工作树

`cp/<task>` 是该任务的历史，`cp/<task>-base` 是它的基线。基线 = **该任务第一次改动前的 `HEAD`**。

用分支而不是"拿当前盘面跟某个全量快照对比"，是因为后者无法区分"这个任务改的"和"隔壁任务改的"。分支让 `git diff base..head` 天然只包含这个任务的提交。

**基线是磁盘现状，不是上一次提交。** 任务第一次改动前，把当时的工作树提交成一个基线提交，`cp/<task>-base` 指向它。

这一条被端到端验证纠正过一次：最初实现记的是当时 `HEAD`，看起来"几乎免费"，但两个任务之间磁盘随时可能领先于 `HEAD`——用户手写的文件、上一个任务回退删掉的文件，都在磁盘上而不在 `HEAD` 里。拿 `HEAD` 当基线，下一个任务对这些文件的改动就会被记成**新建**，回退时直接**删掉用户的文件**。这不是边角情况，是数据丢失。

代价是每个任务一次全树 `add -A`，但只在"磁盘与上次提交确实不同"时发生（先看 `git status --porcelain`），所以两次任务之间没人动过东西时几乎不花时间。

### D4. 快照点在 `execute_tool` 前后各一次

环在 `agent/tools/registry.py` 的 `execute_tool` 里——所有工具调用的唯一咽喉，权限通过之后、执行之前。

- **前**（`begin`）：确保本任务有基线。这是唯一能抓到"改动前"状态的时刻。
- **后**（`end`）：`add` + `commit`，放在 `finally` 里。工具抛异常也改变了磁盘，一样要记。

粒度分两档，这是性能的关键：

- 文件工具只 `add` 那一个 `file_path`（O(1)）。
- `exec_command` / `write_stdin` / `code_interpreter` 才 `add -A`（O(文件数)）——因为它们不告诉任何人自己动了什么。

只读工具不产生快照。

### D5. 回退判据是"内容仍然等于任务留下的样子"

回退前比对当前文件与任务分支上的 blob：

- 相等 → 直接覆盖（或删除，如果基线里没有这个文件）。
- 不等 → 这个文件在任务之后被人改过，**判为冲突、跳过它**，其余文件照常回退，响应里逐文件说明结果。`force=true` 才覆盖。

不做 3-way merge：静默合并会毁掉用户手里的内容，而"部分成功 + 说清楚跳过了什么"是诚实的。

回退是**逐文件**的：一个冲突不能连累其他文件。

### D6. 回退不删历史

已回退的路径记进 `data/checkpoints/<key>/<task>.json`，`changes()` 把它们过滤掉。分支和提交留着：一次回退是发生过的事实，删掉它等于抹掉审计线索。

### D7. 不可用必须可见

git 不在机器上时，store 记下原因（`unavailable_reason`），不抛异常也不阻塞任务。UI 必须据此把回退入口标成不可用——给一个点不动的按钮，比不给更糟。

### D8. 已知限制：并发任务的归属会重叠

多个任务可以同时跑，共享同一个工作树。A 在 B 的基线之后改了文件，这个改动会落进 B 的分支，于是 B 的 `changes()` 会把 A 的改动算进来。真实场景里同一个 workspace 同时跑两个 agent 本身就是在赌，这里不假装能解决它。

**缓解**在 D5：冲突判据比的是"任务留下的内容"，所以任务提交之后再发生的改动仍会被挡下。但这挡不住并发窗口内的重叠。

## 影响

- `ToolRegistry` 多一个可选 `checkpoint_store`；`run_react_loop` 的运行时在 `task_id` 非空时创建它。
- 每次可能改盘的工具调用多两次 git 调用（一次 `rev-parse`，一次 `add`/`commit`）；工作空间第一次改动时多一次全树扫描。
- `data/checkpoints/` 进入 `.gitignore`：它是本程序的运行时状态，不是项目内容。
- 任务被删除时 `CheckpointStore.forget` 清掉它的分支。

## 未覆盖

- `computer_control`（D 层）不可回退。
- 工作空间外部的路径（快照只覆盖 `--work-tree` 之下的东西）。
- 并发任务的归属重叠（见 D8）。
