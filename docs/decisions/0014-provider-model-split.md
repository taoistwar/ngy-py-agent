# ADR 0014: Provider 与模型分离，RPM 按 provider + base_url 计

- 状态：已接受（Accepted）
- 日期：2026-10-26
- 相关：`llm_store.py`、`llm_api.py`、`agent/rate_limit.py`、`agent/provider.py`、`task_runtime.py`、`task_api.py`、`web-admin/src/components/admin/ProviderManager.jsx`、`web-admin/src/components/admin/ModelManager.jsx`、`test/rate_limit_test.py`、`test/provider_api_test.py`、`test/model_api_test.py`
- 取代：[ADR 0013](0013-llm-rpm-limit.md) 的 D1（限流键）与 D6（配置层）

## 背景

1. 旧模型记录把连接信息（`provider` / `base_url` / `api_key`）挂在**每个模型**上：同一台 Ollama 上挂三个模型，就要填三遍地址和 Key，改一次地址要改三行。
2. 限流桶按 provider 名，等于假设"一个 provider 名 = 一个端点"。真实情况是同一个 `openai` 协议会指向多个地址（本地网关、真实 API），它们各有各的配额。
3. 需求：模型管理拆成 **Provider 管理** 与 **模型管理**，RPM 按 `provider + base_url` 限流，而不是按模型。

## 决策

### D1. 两个概念，两张表

**provider** = 请求的去处：协议、`base_url`、`api_key`、RPM。
**model** = 一个模型名（发给 provider 的 `model` 字段）加它的能力开关（工具调用 / 图片输入 / 思考 / token 上限）。

模型只存 `provider_id`。表结构归 `llm_store.py`，它复用 `task_store` 的连接与锁：同一个 SQLite 文件，任务查询仍要 join `models` 取名。

### D2. RPM 属于 provider 记录

`rpm_limit` 是 provider 的字段，界面上也在 provider 表单里，不再是「全局配置」里的一张表。理由：配额是 API key 与端点给的，不是模型给的；"同一端点下的模型共享一份配额"正是要建模的东西。

### D3. 桶键 = 协议 + 规范化后的 base_url

`bucket_key()` = `canonicalize_provider(protocol) + "|" + normalize_base_url(protocol, base_url)`。

适配器会改写地址（OpenAI 兼容补 `/v1`，anthropic-compatible 同样），所以两端都走 `agent.provider.normalize_base_url`：管理员填 `http://host:11434` 与适配器实际请求的 `http://host:11434/v1` 落到同一个桶。固定端点的协议（anthropic / gemini）地址为空，即"每个协议一个桶"。

### D4. 一个端点只能有一条 provider 记录

创建/更新时拒绝重复的（协议, 规范化地址）。否则两条记录抢同一个桶，后写的覆盖先写的，界面上看不出哪条在生效。反过来，同一个协议名配两个地址是允许的：那是两个端点、两份配额。

### D5. 删除 provider 需要先清空它的模型

409，不级联。级联会让模型指向不存在的端点，任务在选择它的那一刻才失败。

### D6. 配置只剩数据库一层

`LLM_RPM` 环境变量与 `settings.llm_rpm_limits` 一并移除：

- 环境变量的键只有 provider 名，无法表达 `base_url`；
- provider 记录本身就是数据库里的配置，再加一层覆盖只会让"界面显示的值"与"生效的值"分叉。

启动时（`admin_api.load_startup_config`）与每次 provider 写入后调用 `llm_api.sync_provider_throttle()` 重建限流表，热更新语义与 ADR 0013 的 PUT 一致：下一次请求就按新配额走。

### D7. 迁移旧库

旧 `models` 表按（`provider`, `base_url`, `api_key`）三元组分组成 provider 记录，模型改挂 `provider_id`，限额初始为 0（不限）。同一端点下的多行模型因此重新共享一个桶——与"按端点限流"一致。旧列随表重建消失。

## 后果

- 旧库首次启动打印迁移行数（`[Provider migration] ...`）。
- 未配置 provider 时，CLI 仍按环境变量走默认端点，此时没有 provider 记录，也就没有 RPM 限制（"未配置 = 不限"不变）。
- 多进程部署仍是每进程一份配额（ADR 0013 的已知限制不变）。
- 任务启动事件与限流等待事件都带 `base_url`，"哪个端点在等"不必再猜。

## 备选方案（未采用）

- **provider 只做枚举，另设 endpoint 表**：多一层概念，而 provider 记录本身就已经是端点。
- **保留 `LLM_RPM` 兜底**：键无法表达地址，且会让生效值与界面显示不一致。
- **允许同一端点两条记录**：两个桶同名，后写覆盖，属于静默的配置错误。
- **删除 provider 时级联删模型**：静默丢掉用户配置。
