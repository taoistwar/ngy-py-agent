# ADR 0021: 任务窗口的上下文占用读数

- 状态：已接受（Accepted）
- 日期：2026-11-14
- 相关：`context_usage.py`、`workspace_api.py`、`api_schemas.py`、`task_store.py`（`recent_events_of_category`）、`web-admin/src/components/ContextMeter.jsx`、`web-admin/src/utils/contextUsage.js`、`test/context_usage_api_test.py`
- 前置：[ADR 0015](0015-snip-compact.md)（对话窗口裁剪）、[ADR 0016](0016-micro-compact.md)（上下文微型压缩）、[ADR 0017](0017-compact-history.md)（历史摘要）

## 背景

上下文会满，而用户在看到"上下文已用满"之前没有任何征兆：任务窗口（composer）只显示输入框、智能体与模型，跑长会话时用户不知道距离窗口上限还有多少。CodeBuddy 在输入框右下角给出 `0.0% · 0 / 256.0K 上下文已使用`，本仓库照这个形态补上。

难点不是画一个数字，而是**这个数字从哪来**：

- 会话的历史（`session_history`）按字符预算裁剪（40 条 / 24000 字符），与模型窗口不是同一把尺子；
- 循环自己的压缩阈值是**字符**（`CONTEXT_CHAR_LIMIT`，默认 200000，`CHARS_PER_TOKEN = 4`），而模型窗口是 **token**；
- 只有 provider 回包里的 `usage` 是真实计数，且它已经落在事件流的 `llm_response` 里。

## 决策

### D1. 读数取 provider 自己数出的 token，不估算文本

`used_tokens = 最近一次模型请求的输入 token + 输出 token`。理由：

- 真实计数已经在事件里（`raw_response.usage`，OpenAI 的 `prompt_tokens` / Anthropic 的 `input_tokens`，由 `agent/telemetry/usage.py` 统一读出），复用它不需要引入分词器；
- 字符估算对中文偏差可达数成（`CHARS_PER_TOKEN = 4` 对中文偏保守），而仪表盘是要被信任的数字；
- 下一次请求的输入 ≈ 上一次的输入 + 输出 + 新工具结果，所以"输入 + 输出"是下一次成本的合理上界估计。

没有任务、或从未发生过模型请求时显示 `0`：**不猜**。

### D2. 读最近一次，而不是当前选中任务的那一次

仪表盘回答的是"这个会话还剩多少空间"，不是"这个任务花了多少"。因此：

- 从**会话最新的任务**往回找，最多 5 个任务（`MAX_SCANNED_TASKS`）；新任务已经开始但模型还没回包时，上一个任务的读数仍然是最新的真值，不会把仪表盘清成 0；
- 每个任务里只看最近 5 条 `llm_response`（`RECENT_RESPONSES`），跳过没有 `usage` 的那些——压缩摘要本身也是一次 `llm_response`，但按 [ADR 0017](0017-compact-history.md) D9 它不带 payload，若只看"最后一条"就会读不到数。

### D3. 分母是"下一次请求会撞上的那个上限"

- 模型配了 `max_input_tokens` → 用它，`limit_source = "model"`；
- 没配 → 用循环自己的预算 `resolve_context_limit(None, 0)`（`CONTEXT_CHAR_LIMIT`，缺省 200000 字符）÷ 4，`limit_source = "loop"`。

两处判断：

- **不把"没有上限"显示成 0 分母**：循环确实会在那个字符预算处开始压缩，那个数就是真正的天花板；
- **不假装它是模型窗口**：`limit_source` 让前端在 tooltip 里说明这是 Agent 的预算，而不是模型的输入窗口。一个显示成"模型的 50K"的数字会让人以为模型只有 50K。

`model_id` 由前端传（任务窗口选中的那个模型）：分母属于**下一次请求将要发往的模型**，而不是上一次碰巧用过的模型。

### D4. 读数只读事件，不重新加载整份日志

新增 `task_store.recent_events_of_category(task_id, category, limit)`：按 `id DESC` 取一小段。用 `get_events` 能算对，但每个轮询周期（5 秒）都会把该任务所有工具结果 JSON 反序列化一遍——为了最后一个数字。

### D5. 前端：与发送按钮同组，跟随会话与模型

- 位置：`composer-toolbar` 右侧、发送/停止按钮左边（`.composer-actions`），因为它描述的是这个按钮即将发出的请求；
- 刷新：随 `sessionId` / 选中模型变化立即读一次，之后每 5 秒一次，任务开始与结束时（`composerRunning` 翻转）再立即读一次——一次任务的 token 数只在一轮结束时变化，更密的轮询没有信息增量；
- 读失败**不弹全局错误**：读数只是提示，后端重启期间它不该盖住真正的错误；
- 阈值着色：≥80% 黄、≥95% 红，先于 provider 报错让人看见。

## 后果

- 用户能在发起任务前看到还剩多少窗口，而不是等模型返回 `prompt_too_long`。
- 数字与循环的压缩阈值可能不一致（模型窗口 vs 字符预算 ÷ 4），这是有意的：一个是"provider 会拒绝"，一个是"我们会主动压缩"，`limit_source` 区分两者。
- 首次请求前仪表盘是 `0`，即使输入框里已经有一大段提示词：那是**没发生过请求**的诚实读法，而不是"这段文字会花多少"。想做"输入即估算"需要分词器，本 ADR 不做。
- 每个任务窗口每 5 秒多一个轻量查询（两次 `LIMIT` 查询，不扫事件表）。

## 备选方案（未采用）

- **按字符估算整个 transcript**：无请求也能算，但中文误差大，且与 `used_tokens` 的真实口径混在一起后没人分得清哪个可信。
- **在 `llm_response` 事件里再存一份 `usage_tokens`**：多一个需要保持同步的字段，现有 `raw_response.usage` 已经够读。
- **把读数放进 `GET /api/tasks` 列表**：每次列表刷新都要为每个任务找 usage，代价跟着任务数走；仪表盘只关心当前会话。
- **前端自己累加 token**：需要把事件流整段读进浏览器，且与后端的口径会出现两份实现。
