# ADR 0013: 按 provider 的模型请求限流（RPM）

- 状态：部分被取代（D1 的桶键与 D6 的配置层见 [ADR 0014](0014-provider-model-split.md)；滑动窗口、wire 层钩子、等待上限仍然有效）
- 日期：2026-10-25
- 相关：`agent/rate_limit.py`、`agent/provider.py`、`agent/agent_loop/steps.py`、`admin_api.py`、`task_store.py`、`app_state.py`、`api_schemas.py`、`web-admin/src/components/admin/SettingsPanels.jsx`、`test/rate_limit_test.py`、`test/rpm_config_api_test.py`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（全局配置的读写惯例）

## 背景

模型端点有每分钟请求数（RPM）的配额。本仓库现在没有任何节流：任务循环、任务命名线程都可以在同一秒里打同一个端点，而 provider 一旦返回 429，本仓库**不重试**（`agent/llm_errors.py` 只负责把失败讲清楚），任务直接失败。

四条既成事实决定了方案形状：

1. **provider 实例每个任务重建**（`agent_loop/runtime.py`、`task_runtime.py`），所以计数器不能挂在实例上——那等于每个任务各自拥有完整的一分钟配额。
2. **调用有两条入口**：ReAct 循环（`agent_loop/steps.py`）和任务命名线程（`task_runtime.py`）。只堵住循环，配额仍会被辅助线程吃掉。
3. **请求是同步阻塞的**（openai SDK 同步 client、`requests.post`），没有 asyncio 可用，节流只能是"在发请求前阻塞"。
4. **没有重试**，所以"等待"不会和重试逻辑叠加成双倍请求。

## 决策

### D1. 一个 provider 一个桶，进程级单例

桶的键是**规范化后的 provider 名**（`canonicalize_provider`：`openai`、`anthropic`、`anthropic_compatible`、`gemini`、`bedrock`）。`openai-compatible`、`ollama` 这类拼写落到同一个桶。

限流器是模块级单例（`agent/rate_limit.py` 的 `provider_throttle`），因为它必须活得比任何一次运行都久。管理配置在启动时与每次 PUT 时把它配置一遍。

**已知代价**：同一个 provider 名下挂两个不同 `base_url`（例如本地 12434 与真实 OpenAI 网关）会共用一个额度。选它是为了少一层"地址一改配额就重置"的隐式行为；如果将来真出现多地址并存，再按 `provider + base_url` 拆桶。

> **已被 ADR 0014 取代**：桶键现在是 `provider + base_url`（`bucket_key()`），`rpm_limit` 也从「provider 名的全局表」搬到了 provider 记录上。

### D2. 滑动窗口，不是固定窗口

第 N+1 个请求等待"窗口里最老的那个请求满 60 秒"。固定窗口（`ceil(now/60)` 计数）在边界处允许 2N 个请求挤在两秒里，而这正是最容易触发上游 429 的形状。

### D3. 等待有上限：超时即报错

单次请求最多等 60 秒（`DEFAULT_WAIT_CAP_SECONDS`）。需要的等待超过上限时抛 `RpmLimitError`，由循环转成 `LLMCallError`，文案直接说"调高限制或稍后重试"。

不设上限的反面是"配成 1 RPM 却要跑 8 步"表现为任务假死——比报错难排查得多。报错是**可见的失败**，静止不动的任务不是。

### D4. 钩子装在 wire 层，不装在循环里

四个 `chat_completion` 的第一行都是 `self._throttle()`（`agent/provider.py`）。理由就是背景第 2 条：任何"只在循环里等"的实现都能被任务命名线程绕过，而被绕过的限流不是限流。用户要求"辅助调用一起限流"，这也是唯一能真正做到的位置。

代价：新增 provider 适配器时必须记得加这一行。这是有意的——它出现在每个适配器的同一个位置，漏掉时测试 `test_the_adapter_throttles_first` 会失败（该用例遍历四个适配器）。

### D5. 等待要有信号：`debug` 事件 + span 属性

等待发生在适配器内部，循环读不到墙钟差。因此 `acquire()` 把本次等待秒数记在线程局部变量里，循环用 `take_last_wait()` 取一次（取后清零），然后：

- span 属性 `llm.rpm.wait_ms`（`record_throttle_wait`）；
- 一条 `debug` 事件，含 `provider`、`model`、`rpm_limit`、`waited_ms`。

"模型慢"和"我们在自己的配额里打转"从外部看完全一样，排障时却要分开。**不新增事件类别**：`debug` 已经承载循环的运行细节，新增类别要连带改前端两份 i18n 与样式，收益为零。

### D6. 配置三层，PUT 整表替换

解析顺序：`LLM_RPM` 环境变量（`openai=60,anthropic=20`）→ `settings.llm_rpm_limits`（数据库优先）→ `PUT /api/admin/llm-rpm` 热更新。

- 未列出的 provider **不限速**；显式 `0` 同样表示不限。
- PUT 是**整表替换**：漏掉某个 provider 等于解除它的限制。逐项合并会让"删除一行"没有表达方式。
- 未知 provider 与越界值（`< 0` 或 `> 6000`）一律 **400 拒绝**，不做静默丢弃——管理员刚设的限制被悄悄忽略，是最坏的失败方式。
- 上限 6000 RPM（100 请求/秒）只是防手滑，不代表推荐值。

### D7. 与工具输出预算正交

`token_budget` 管**单条工具输出**，`result_budget` 管**一步的工具结果总量**（ADR 0012），本 ADR 管**发往模型的请求频率**。三者服务的资源不同（上下文 vs 上下文 vs 上游配额），互不替代，也不要合并成一个"预算"概念。

## 后果

- 超限的请求会阻塞任务线程最多 60 秒。任务状态仍是 `RUNNING`：它确实在工作，只是被自己的配额挡住。
- 多进程部署（多个 uvicorn worker）时每个进程各有一份配额，实际 RPM 是 `N × 配置值`。**已知限制**，写在这里而不是假装它是全局的：要真正全局，需要一个进程外的计数器（Redis 之类），超出本仓库现在的形态。
- 限流不改变错误处理：429 仍然不重试。本 ADR 只保证"我们不会主动撞上去"。
- 桶的状态随进程重启清零，符合"分钟"这个时间尺度。

## 备选方案（未采用）

- **令牌桶**：等价能力，但滑动窗口的语义与"任意 60 秒内最多 N 次"完全一致，解释成本更低。
- **在 `steps.py` 里等待**：改动最小，但任务命名线程绕得过去。
- **按模型分桶**：更精细，但配额通常挂在服务商 API key 上，而一个 key 对应一个 provider；按模型分桶会让同一 key 下多个模型各自用满配额，反而更容易 429。
- **被动退避（等 429 再退）**：本仓库没有重试，且被拒的请求已经花掉了时间与配额；主动限流把冲突挡在发请求之前。
- **无限等待**：配错时表现为假死，排障成本远高于一条明确的错误。
- **新增 `rate_limit` 事件类别**：需要前端两份 i18n 与样式，信息量与 `debug` 事件相同。
- **进程外共享计数**（Redis）：本仓库是单进程 CLI/Web 的形态，引入外部依赖换一个"多 worker 也准确"的保证，现在不划算。
