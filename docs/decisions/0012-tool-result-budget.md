# ADR 0012: 工具结果预算（tool result budget）

- 状态：已接受（Accepted）
- 日期：2026-10-24
- 相关：`agent/agent_loop/result_budget.py`、`agent/agent_loop/loop.py`、`agent/tools/output_store.py`、`agent/tools/registry.py`、`test/agent_loop_result_budget_test.py`
- 前置：[ADR 0005](0005-exec-tool.md)（exec 输出的落盘与只读附加根）、[ADR 0007](0007-default-workspace.md)（未绑定会话的基目录）

## 背景

一次模型回复可能同时调用多个工具。它们的结果一起写进消息列表，所以**单条**结果有预算并不等于**一批**结果有预算：

- `exec_command` 有 per-result 预算（`agent/tools/token_budget.py`，默认 25k tokens），超了落盘到 temp 输出树；
- 但"一次读 30 个文件"、"一次看几张长截图"里没有任何一条超限，合起来却能把上下文撑爆。

参考实现在 `tool_result` **block** 层做这件事：一批超过 200,000 字符就按大小降序处理，超过 30,000 字符的单条整份写进 `.task_outputs/tool-results/<tool_use_id>.txt`，上下文里只留路径 + 2,000 字符预览。

那条路径在本仓库不能直接照搬，原因有两条，都是既成事实：

1. **`tool_result` 不是本仓库的内层形状**。循环里是 `{"role": "tool", "tool_call_id": ..., "content": ...}`（`agent/agent_loop/loop.py`），`tool_result` / `tool_use_id` 只出现在 Anthropic 适配器的线格式转换里（`agent/provider.py`）。在 block 层做，等于只给 Anthropic 修；在消息层做，四个适配器一起受益。
2. **`.task_outputs` 与 ADR 0005 的"输出树在 workspace 之外"相反**。ADR 0005 把 exec 输出放 temp，理由是"不污染项目、不进 git"，代价是跨运行不保证存在。工具结果要付出的代价不一样：会话历史里存的是**绝对路径**，后续轮次（同一会话的下一次追问）要能按那个路径读回来。

## 决策

### D1. 在消息层做，不在 block 层

预算步骤读的是 `role == "tool"` 的消息，与 provider 无关。文件名用 `tool_call_id`：它在各 provider 适配器里都存在且唯一，而 `tool_use_id` 只是它在 Anthropic 线格式里的名字。

### D2. 只处理最新一批

`loop.py` 在工具循环开始前记下 `batch_start`，预算只看这之后追加的消息。

理由是这段代码在压缩链路里是**第一步**：已经换成路径的历史结果不会自己长回去，反复重扫旧消息只会打乱 prompt 前缀、破坏缓存。多步累积留给后续步骤（摘要 / 裁剪）处理，不在这里做第二份职责。

### D3. 两遍扫描，第二遍不设下限

1. 第一遍：只动 `> 30,000` 字符的单条（`TOOL_RESULT_LARGE_CHAR_LIMIT`）。
2. 第二遍：如果总量**仍**超过 200,000 字符，按大小继续落盘，不再设下限。

没有第二遍，`30 × 20,000 = 600,000` 的场景一条都不会被处理，预算形同虚设。第二遍只在严重超预算时触发，不会平白把正常结果换成占位。

两遍都要求**占位文本比原文短**才替换：否则 2,100 字符左右的结果会被"落盘"成一个更长的路径，既不省 token 又丢内容。每个下标只访问一次——被第二遍再次处理的占位文本会把真正的全文覆盖成它自己。

### D4. 落盘在 `<workspace>/.task_outputs/tool-results/`，这是对 ADR 0005 的显式例外

- 位置：`<base_dir>/.task_outputs/tool-results/<tool_call_id>.txt`；未绑定会话时是 `<default_workspace>/.task_outputs/tool-results/`（ADR 0007），`data/default_workspace/` 已在根 `.gitignore` 里。
- 为什么破例：会话历史保留这些绝对路径，下一轮追问仍要读得到；temp 树被清理后，历史里的路径就变成死链。
- 不进 git 由工具自己保证：落盘目录里放一个只含 `*` 的 `.gitignore`，不改用户仓库根的那份文件。
- **不自动清理**：删掉它们等于让历史里的路径失效。清理是用户的决定，不是读一次文件的副作用。

### D5. 落盘目录是只读根

`ToolRegistry` 在构造期把 `workspace_result_directory(base_dir)` 并入 `read_only_roots`（与 exec 的 temp 树并列），因此 `read_file` 读得到、`write_file` / `edit_file` 报 `read_only_root`。

理由：这些文件是"模型当时看到的证据"。允许改写，模型就能改完再回读，然后把改写版当成原文——之后所有推理都建立在假数据上。

### D6. 字符计量，不接 tokenizer

参考实现用的就是字符（200,000 / 30,000 / 2,000），照抄它能省掉一次 tokenizer 依赖与一整类"数出来不一样"的争议。它与 `token_budget.py` 分工不同：

| | `token_budget` | `result_budget` |
| --- | --- | --- |
| 管什么 | **单条**工具输出 | **一步**的全部工具结果 |
| 单位 | token | 字符 |
| 超限动作 | 报错或落盘（工具自己决定） | 落盘并换成占位文本 |
| 位置 | 工具内部 | 循环里，工具全部返回之后 |

两者不互相替代，也不合并：一个是工具对自己输出的承诺，一个是循环对整轮上下文的护栏。

### D7. 落盘失败保留原文

磁盘满、权限异常时**不截断**：消息保留完整内容，超预算照旧，同时发一条 `error` 事件。静默丢掉内容比超预算危险得多——超预算会在下一次调用里表现为臃肿，而丢内容只会表现为模型给出一个自信的错误结论。

### D8. 两个事件，不动既有 `tool_result`

- 成功：一条 `debug` 事件，含 `step`、`max_chars`、`before_chars` / `after_chars`、`persisted[]`（`tool_call_id` / `name` / `chars` / `path`）。
- 失败：一条 `error` 事件，说明"已保留全文"。
- 既有 `tool_result` 事件**不裁剪**：UI 仍然要看到完整结果，预算省的是模型上下文，不是审计记录。

## 后果

- 一步的工具结果总量有了可预测的上限（默认 200,000 字符，`TOOL_RESULT_BUDGET_CHARS` 可覆盖，`<= 0` 关闭）。
- 模型看到大结果时要多一次 `read_file` 才能读全文。这是有意的：先看预览、需要时再读，比把 20 万字符塞进每一次请求便宜。
- 工作空间里多了 `.task_outputs/`，且不会被自动回收。已知限制，写在 D4。
- 现在有两套落盘树（temp 的 exec 输出、workspace 的工具结果），都以只读根的形式交给 `read_file`。它们形状相同、生命周期不同，术语表把两者分开命名。

## 备选方案（未采用）

- **照抄 block 层实现**：只对 Anthropic 生效，其余 provider 静默不受保护。
- **落盘到 temp 输出树**（沿用 ADR 0005）：路径跨运行不保证存在，会话历史里的绝对路径会变成死链。
- **用 token 计量**：需要 tokenizer、与"0 次 API 调用"的定位冲突，且参考实现的阈值就是字符，换算反而引入新的不一致。
- **超预算就截断**：内容不可恢复，模型没有任何回到全文的路径。
- **每步扫描全部历史 `tool` 消息**：破坏 prompt 缓存，且已完成压缩的历史结果不会重新变大，没有收益。
- **任务结束时删除 `.task_outputs`**：后续追问读不回上一轮的结果，等于让历史里的路径指着空气。
