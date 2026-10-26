# ADR 0015: snip_compact —— 归档旧消息，把对话窗口收在 50 条

- 状态：已接受（Accepted）
- 日期：2026-10-26
- 相关：`agent/agent_loop/snip_compact.py`、`agent/agent_loop/loop.py`、`agent/tools/output_store.py`、`agent/tools/registry.py`、`test/snip_compact_test.py`
- 前置：[ADR 0012](0012-tool-result-budget.md)（工具结果预算：管单条体积）、[ADR 0007](0007-default-workspace.md)（未绑定会话的基目录）

## 背景

上下文膨胀有两个维度，ADR 0012 只解决了其中一个：

| 维度 | 现有手段 | 现状 |
| --- | --- | --- |
| 单条结果太大 | `result_budget`（每步、按字节） | 已解决 |
| **消息条数太多** | 无 | 本 ADR |

条数增长是稳定的：每步至少追加 `assistant` + N 条 `tool`，截图还会再加一条 `user`。带上会话历史时起点更高——`MAX_HISTORY_MESSAGES = 40` 意味着第一次请求前就可能已有 42 条。

参考实现给的方案：超过 50 条就把完整历史写进 `.transcripts/`，保留前 3 条 + 最近 46 条 + 1 条归档标记；切点要保住 `assistant(tool_use)` 与 `user(tool_result)` 的配对。

那一版伪代码落到本仓库要改两处，都因为**一次回复可能产生 N 条 tool 消息**（并行工具调用，`loop.py` 里逐条 append）：

- tail 侧只回退一步：`tail_start` 落在第 2 条 tool 上时，回退一步仍是 tool，切片以孤儿 `tool_result` 开头；
- head 侧只前进一次同理不成立，一组工具结果可能有多条。

Anthropic 适配器会把每条 `tool` 转成一条 `user(tool_result)`（`provider.py:379-394`），孤儿 `tool_use` / `tool_result` 都是确定的 400。

## 决策

### D1. 原地替换，不返回新列表

`messages[:] = [...]`。`loop.py` 里 `messages = initial_messages` 是**别名**，交互式 REPL 跨轮持有同一个列表（`main.py`）；返回新列表会让 REPL 那一份停在压缩前，之后的消息全丢。原地替换同时让 `run_model_turn` 的 append 与 `batch_start` 下标语义保持不变。

### D2. 切点绝不落在一次工具调用内部

- **head 侧**：若第 3 条是 `assistant(tool_calls)`，把它后面的 tool 结果**全部**并入 head。
- **tail 侧**：若 `tail_start` 落在 `tool` 上，**循环**回退到发起调用的 assistant。

两处都必须是循环而不是"动一步"。`test_the_tail_never_starts_with_an_orphan_tool_result` 用一组 3 个并行调用来钉住这条。

### D3. 窗口是上限，不是等号

两条规则会改变最终条数，且方向相反：

- head 扩展**从尾部扣**（先算 head_end，再用它反推 `tail_start`），所以"助手调了 3 个工具"不会让窗口变成 53；
- tail 回退**只能加**（一组工具调用不能切一半），所以窗口可能超出上限，最多超出一组工具调用的条数。

参考实现的"恰好 50"在只有一个 head 例外时不成立；这里承认它，条件写在 `test_the_tail_never_starts_with_an_orphan_tool_result`（60 → 53）。

### D4. 阈值：常量 50 + 环境变量

`TRANSCRIPT_MAX_MESSAGES`，`<= 0` 关闭。不进管理页：它是压缩链路的形状参数，不是运维每天要调的旋钮；`result_budget` 的两个阈值同理。

### D5. transcript 落在 `<workspace>/.transcripts/`，一次压缩一个快照

- 位置与 `.task_outputs` 一致（ADR 0012 D4）：标记里写绝对路径，被删掉的消息只能靠它找回，所以要跨运行存在。
- 文件名 `transcript-<时间戳>-<随机>.jsonl`，**不覆盖**：第二次压缩写第二个文件。覆盖会让第一次的证据消失，而"上一条标记指向的文件"还在对话里。
- 内容：**JSONL，一行一条消息**。不是一个大 JSON——`read_file` 按行切片，单行 JSON 读不回来（ADR 0012 的"回读契约"）。
- 图片：写入前用 `redact_image_payload` 换成占位。transcript 是为了找回**文本**；一张截图几 MB，原样写会把一次压缩变成几十 MB。
- 目录注册为**只读根**（第三个），工具可读不可改；目录内嵌 `*` 的 `.gitignore`。

### D6. 写盘失败就不压缩

`OSError` 时消息原样保留，发 `error` 事件说明"一条都没归档"。唯一不能接受的降级是"删了消息但档案没写出来"：任务会继续跑，却再也没有办法知道它忘了什么。

### D7. 标记是一条 `user` 消息，两行

```
[{N} messages archived to {绝对路径}]
Read it with read_file (offset/limit): it is line-numbered and capped by the output token budget.
```

第二行是 ADR 0012 那节课的直接复用：只给路径，模型的第一次读取就是一次确定的报错（行号前缀、单次 token 上限、整读 256KB）。

用 `user` 而不是 `assistant`：`assistant` 位可能与 `tool_calls` 相邻并让适配器误判；`user` 在 OpenAI / Gemini 明确合法，Anthropic 侧见"后果"。

### D8. 与 `result_budget` 的分工和顺序

`result_budget` 在**步末**（工具执行完，动的是最新一批的字节），`snip_compact` 在**步首**（上一个工具组已完整，动的是条数）。压缩后的历史结果不再重新扫描——那正是 ADR 0012 否决过的"每步全量扫描"。

## 后果

- 会话前 3 条可能是**历史消息**而不是本任务的开头（`session_history` 注入在 system 之后）。这是有意的：保留"这个会话在聊什么"比保留"本任务第一句话"更有用；但如果哪天要改，改动点是 `HEAD_MESSAGES` 与注入顺序，不是压缩算法。
- 窗口可能略超上限（D3）。上限用于防止无界增长，不用于精确计费。
- 磁盘占用随压缩次数呈 O(n²)（每次全量快照）。一次 run 通常只压缩几次；文件不自动清理，理由同 ADR 0012 D4。
- **Anthropic 未实测**：标记紧邻另一条 user 消息时会形成连续同角色。OpenAI / Gemini 明确允许；Anthropic 按公开的"合并连续同角色"行为应允许，但本仓库没有可用的 Anthropic key，只能在本地测"配对完整"（`test_anthropic_gets_no_orphan_tool_use_or_result`），测不了这一点。若将来在 Anthropic 上复现 400，改法是 D7 的标记并入相邻 user 文本，而不是回退整个 ADR。
- 归档之后模型看不到中段对话；需要时按标记里的路径用 `read_file` 读回（受 ADR 0012 的回读契约约束）。

## 备选方案（未采用）

- **LLM 摘要压缩**：质量更高，但每次压缩要一次模型调用、要处理"摘要失败"、且摘要本身就是不可核对的二次创作。先做可验证的裁剪。
- **丢弃中段但不写盘**：省一次 IO，代价是模型永远找不回被删的内容——这正是 D6 拒绝的形状。
- **固定保留最近 N 条、不做 head**：任务开场（系统提示与本轮问题之外的编排信息）会丢失，长任务更容易跑偏。
- **返回新列表**：破坏 `main.py` 的 REPL 引用语义（D1）。
- **每任务一个 transcript 文件、内容覆盖**：第二次压缩会毁掉第一次的证据（D5）。
- **单个 JSON 文件**：`read_file` 无法分段读（D5）。
- **阈值进管理页**：多一套 API + 前端表单 + 迁移，换一个几乎不变的数。
