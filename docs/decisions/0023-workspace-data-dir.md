# ADR 0023: 工作空间里只留一个 `.ngy-agent/`，运行期目录都放它下面

- 状态：已接受（Accepted）
- 日期：2026-11-16
- 相关：`agent/tools/output_store.py`、`agent/tools/registry.py`、`test/agent_loop_result_budget_test.py`、`test/snip_compact_test.py`、`test/compact_history_test.py`
- 修订：[ADR 0012](0012-tool-result-budget.md) D4（工具结果落盘位置）、[ADR 0015](0015-snip-compact.md) D5（transcript 位置）

## 背景

ADR 0012 与 ADR 0015 各给工作空间加了一个目录，都直接放在根下：

| 目录 | 内容 | 来源 |
| --- | --- | --- |
| `.task_outputs/tool-results/` | 移出上下文的工具结果 | ADR 0012 |
| `.transcripts/` | 归档的对话快照 | ADR 0015 |

两处的位置理由相同（历史里写的是绝对路径，文件必须跨运行存在），实现也共享 `output_store._workspace_directory()`。但它们让**用户的项目根多了两个条目**，而且每加一个功能就多一个：这类目录不是项目内容，是应用自己的状态，散在根上既难解释"这是什么"，也难清理——用户想回收空间，得先知道有哪几个名字。

## 决策

### D1. 一个工作空间一个 `.ngy-agent/`，运行期目录都挂在它下面

```
<workspace>/.ngy-agent/
├── .task_outputs/tool-results/<tool_call_id>.txt
└── .transcripts/transcript-<时间戳>-<随机>.jsonl
```

常量 `WORKSPACE_DATA_DIRNAME = ".ngy-agent"` 由 `output_store` 提供，两个目录函数都经 `_workspace_directory(base_dir, WORKSPACE_DATA_DIRNAME, ...)` 组装，位置知识仍只有一处。

"应用状态"因此在工作空间里只有一个入口：看一眼 `.ngy-agent/` 就知道应用写了什么，清理也只需删一个目录。

### D2. 仍然在**工作空间内部**，没有搬到系统 AppData

ADR 0012 D4 的理由不变：会话历史里存的是绝对路径，下一轮追问要按它读回来。放到临时树或系统目录只是把"路径会不会失效"换了个地方回答，还得额外解释为什么路径里有工作空间的哈希。放在工作空间里，模型看到的路径与它操作的项目在同一个树里，`read_file` 的可见范围与相对路径语义也一致。

### D3. 叶子目录各带自己的 `.gitignore`

`ensure_result_directory` 的行为不变：谁被创建，谁就在里面写一个只含 `*` 的 `.gitignore`。父目录 `.ngy-agent/` 不需要额外规则——它的可见内容只有这些被忽略的子树。仍然不碰用户仓库根的那份 `.gitignore`。

### D4. 旧的根目录不迁移

已经存在的 `<workspace>/.task_outputs/` 与 `<workspace>/.transcripts/` 留在原地：旧会话标记里写的是旧绝对路径，删掉它们等于让历史里的路径失效（ADR 0012 D4 / ADR 0015 D5 都拒绝这个形状）。新压缩、新落盘写进 `.ngy-agent/`；旧目录由用户决定何时清理。

## 后果

- 工作空间根只多一个条目（ADR 0012 的"后果"里"多了 `.task_outputs/`"这一条由本 ADR 改写）。
- 三个只读根的实际前缀统一为 `<workspace>/.ngy-agent/`；`ToolRegistry` 的构造代码不变，因为它只接收两个目录函数的结果。
- 归档标记、占位文本里的路径变长了一段（`.ngy-agent/`）。占位文本仍以绝对路径给出，长度差异可以忽略。
- 已存在的旧目录不会被自动发现或清理；同一个工作空间可能同时有新旧两套目录。这是 D4 的直接代价，也是唯一不破坏历史路径的选项。
- 未绑定会话（ADR 0007）同样落在 `<default_workspace>/.ngy-agent/`，`data/default_workspace/` 本来就整体被根 `.gitignore` 忽略。

## 备选方案（未采用）

- **保持两个根目录各放一处**：每加一个运行期目录就多一个根条目，且"应用状态"没有统一入口。功能上无差别，可读性上会一直退。
- **放到 `<workspace>/data/`**：`data/` 是用户（和本仓库）常用的项目目录名，撞名后无法区分谁写的。
- **放到系统 AppData（按工作空间哈希分桶）**：路径仍然绝对、仍然跨运行，但"在项目里、可读回、只读根"这三个性质都要重新解释，且模型看到的路径与它正在操作的项目完全脱节。
- **迁移旧目录并改写历史里的路径**：历史是只追加的记录，改写它等于伪造"模型当时看到的东西"。
