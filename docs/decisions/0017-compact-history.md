# ADR 0017: compact_history —— 用一次模型调用换掉旧历史

- 状态：已接受（Accepted）
- 日期：2026-10-27
- 相关：`agent/agent_loop/compact_history.py`、`agent/agent_loop/transcript.py`、`agent/agent_loop/snip_compact.py`、`agent/agent_loop/loop.py`、`agent/telemetry/spans.py`、`test/compact_history_test.py`
- 前置：[ADR 0012](0012-tool-result-budget.md)（工具结果预算）、[ADR 0015](0015-snip-compact.md)（对话窗口裁剪）、[ADR 0016](0016-micro-compact.md)（上下文微型压缩）
- 取代：[ADR 0016](0016-micro-compact.md) D1 的最后一句（"仍超限只记账、不进入需要额外模型调用的第四步"）

## 背景

ADR 0016 的第三步解决的是"工具结果占位太多"：把模型已读过的旧结果换成路径。但它只能动 `role="tool"` 的消息，所以有一类超限它**结构上无能为力**：

- 一长串 assistant 回复与用户消息（每轮几 KB，累积几十万字符）；
- 一轮里反复对话，工具结果并不多；
- 会话历史注入（`history_messages`）本身就很长。

这些内容既不落盘、也没有"已读/未读"可区分，文本手术没有可裁剪的边界。ADR 0016 当时的结论是"只记 `still_over`，交给运维调阈值"；本 ADR 承认那不是终局：上下文满了还是得腾地方，代价只能是**一次模型调用**。

## 决策

### D1. 最后一步，也是唯一会调用模型的一步

```
tool_result_budget（步末）→ snip_compact（步首）→ 超限？micro_compact → 仍超限？fit_tool_results → 仍超限？compact_history
```

进入条件只有一个：`prepare_context(...)["still_over"]` 为真。`CONTEXT_SUMMARY_ENABLED=0` 可整体关闭；`CONTEXT_CHAR_LIMIT <= 0` 时自然不会触发。

管线到此结束：摘要之后再超限只记事件，不再有第五步。摘要本已是有损的二次创作，再叠一层只会更难核对。

### D2. 只摘要"将被删掉的那段"，尾部不重复送

尾部要原样留在对话里。把它也送进摘要，等于让模型看两份同样的内容，还多花一份输入预算。所以送给模型的是 `old`（`_split` 的中间段），tail 与 system 都不送。

### D3. 摘要请求有自己的输入预算

被删的旧历史可能几十万字符，"摘要请求"本身会先撞上下文墙。三层上限：

1. **单条消息** `SUMMARY_MESSAGE_CHAR_LIMIT = 4,000`：否则一条 200k 的工具结果会吃光整个输入预算，摘要只描述了一个观测；
2. **总量** `min(60,000, context_limit × 0.5)`：跟着模型窗口走，而不是写死；
3. **头 1/4 + 尾 3/4**，中间用 `...[middle omitted; full transcript on disk]...` 代替，只在消息边界切。

图片一律换成 `[image]`：摘要要的是事实，不是 base64。

### D4. 替换形状：`system` + 一条标记 + 最近 5 条

`messages[:] = [*system 消息, {"role": "user", "content": marker}, *tail]`，`KEEP_RECENT_MESSAGES = 5`，列表对象不变（`main.py` REPL 跨轮持有它，ADR 0015 D1）。

- **头部只留 system**，不像 `snip_compact` 那样保留前 3 条：目标与当前请求已经在摘要和标记里，再留一条旧 user 只会制造两份"当前请求"。
- **尾部是正在进行的活儿**，所以整条保留。切点落在 `role="tool"` 上时**循环**回退到发起该批调用的 `assistant(tool_calls)`：孤儿结果必然被 provider 拒绝（ADR 0015 D2）。
- 并行工具多时尾部会超过 5 条。与 ADR 0015 D3 同一个取舍：**上限不是等号**，正确性优先于条数。

### D5. 标记自足，摘要只作参考

```
[Compacted: {N} earlier messages summarized; full transcript at {绝对路径}]

Current user request:
{user_query}

Conversation summary (reference only; the transcript is authoritative):
{summary}

Read the transcript with read_file (offset/limit): it is line-numbered and capped by the output token budget.
```

三处判断：

- **总是复制当前请求**。参考实现是因为工具结果也用 `role=user` 才不得不单独传 `active_request`；本仓库的工具结果是 `role=tool`，理论上请求就在消息里——但长工具循环里它可能远在被删区间，从 `messages` 反查不如直接用 `run_react_loop(user_query=...)`。尾部恰好含它时重复一次，可接受。
- **摘要标 reference-only，transcript 才是权威**。摘要是有损派生，把它当记录会在细节上骗人。
- **`role="user"`**：与 `snip_compact` 的标记一致，避免 Anthropic 侧的连续 assistant 问题。
- 回读提示不是装饰（ADR 0012「回读契约」）：只给路径，模型的第一次读取就是一次确定的报错。

### D6. 投影守卫，而不是时间窗

调用模型前先算：

```
projected = estimate(messages) - estimate(old) + len(active_request) + SUMMARY_CHAR_ESTIMATE + MARKER_OVERHEAD
```

若 `projected > int(context_limit × TARGET_RATIO)`，说明摘要也救不回来（问题在 system 提示或尾部），**跳过并记 debug**，从不调用模型。

- 不需要"每 K 步一次"的状态：状态会随重启、跨轮、并发失效，而投影是每步都能重算的事实。
- 代价是最坏情况"一次都不摘要"。这正是想要的：不能让一个救不回来的场景变成每步一次模型调用。
- `SUMMARY_CHAR_ESTIMATE = 2,000` 是投影用的摘要长度上界，与截断上限同一个数。

### D7. 输出上限按 wire 格式选 kwarg

OpenAI 与 Anthropic（含 `anthropic_compatible`）认 `max_tokens`；**Gemini 只认 `max_output_tokens`，并把未知 kwarg 直接 `request_payload.update(kwargs)`**——传错名字在 Gemini 侧是 400，不是默认值。`_token_cap(provider)` 按 `provider.provider_name == "gemini"` 分流，`SUMMARY_MAX_TOKENS = 1,500`。

### D8. 失败即不压缩：归档先行

顺序固定为**写 transcript → 请求摘要 → 替换消息**：

- transcript 写不出（`OSError`）→ 不调用模型、不替换；
- 模型异常或**摘要为空** → 不替换，历史原样保留，发 `error`（`action: "kept the full history"`）。

空摘要按失败处理：一条空壳 `[Compacted]` 既删了历史又没给回任何东西。归档先行还有一层收益——即使摘要失败，证据也已经落盘。

### D9. 可观测：这是一次真实的模型请求

- trace：独立 span `compact.summary`（`llm_span` 增加可选 `name`，默认仍是 `chat <model>`）。
- 事件流：一对 `llm_request` / `llm_response`，`data.purpose = "compaction_summary"`，带 `input_chars` / `output_chars` / 消息数，**不带原始 payload**（那等于把整段旧历史再存一份进事件库）。
- 成功一条 `debug`（前后字符、删了多少条、保留多少条、摘要字符、transcript 路径、模型）；跳过一条 `debug` 带 `reason`；失败一条 `error`。

### D10. transcript 写入器共享

`snip_compact` 与 `compact_history` 都承诺"全量历史在这个路径、JSONL、可 `read_file` 读回"。两套实现迟早会在行格式或目录上分叉，所以抽到 `agent/agent_loop/transcript.py`：`write_transcript(messages, base_dir)`，JSONL 一行一条、图片 redact、`transcript-<stamp>-<hex>.jsonl` 每次一个新文件（不覆盖：旧标记还指着旧文件）。

不放 `output_store`：那里是纯存储层（路径与写字节），"把消息列表变成可回读的 JSONL"是 agent_loop 的语义。

## 后果

- 上下文终于有了**有损但可控**的兜底：前三步修不了的内容（长对话文本）由摘要接管。
- 每次压缩多一次模型调用，占用 provider 的 RPM 与 token 预算。投影守卫把调用限制在"确实能救回来"的场景。
- 摘要是有损的：细节只能从 transcript 读回。与前三步不同，这一步**不能**只靠路径还原"模型当时看到的东西"。
- 字符估算对中文偏保守（阈值 = token × 4）。窗口接近上限时，摘要可能比预期更早触发；调 `CONTEXT_CHAR_LIMIT` 是唯一的旋钮。
- 长单轮工具循环仍可能停在"超限"状态：尾部自己就超过目标线时 D6 会跳过。这是有意的——那种场景需要的是更小的工具结果，而不是更狠的历史压缩。
- 未做、留给后续 ADR：`reactive_compact`（provider 明确返回 `prompt_too_long` 后补救一次；`agent/llm_errors.py` 目前没有这类错误分类）与模型主动调用的 `compact` 工具（要动工具面、权限与前端）。

## 备选方案（未采用）

- **摘要整段对话（含尾部）**：重复内容 + 双份预算，且摘要里出现的"最新结果"可能与尾部原文矛盾（D2）。
- **不写 transcript 直接摘要**：省一次 IO，代价是删掉的内容再也找不回（D8）。
- **一条标记都不留（只留摘要）**：模型不知道有更细的记录可查（D5）。
- **每 K 步才允许压缩一次**：需要跨步/跨轮状态，重启即失忆；投影判断每步都能重算（D6）。
- **摘要用第二个模型/provider**：多一套配置与失败面，收益是质量——先证明这一步值得存在。
- **把摘要塞进 `prepare_context`**：会让"纯文本、零网络"的第三步依赖网络，测试也必须造假 provider（ADR 0016 D1）。
- **保留前 3 条消息（照抄 `snip_compact`）**：与摘要/标记里的目标重复（D4）。
