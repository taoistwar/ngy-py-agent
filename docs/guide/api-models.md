# API：Provider 与模型

Web Admin 把过去的「模型连接」拆成两层：**Provider** 是请求的去处（协议 + 地址 + Key + RPM），**模型** 只有一个模型名和能力开关，挂到某个 Provider 下。地址、Key 与 **每分钟请求数（RPM）** 都记在 Provider 上，因此同一 Provider 下的所有模型共享一份配额；同一个协议配两个地址则是两个端点、两份配额。

- `GET /api/providers`：返回 `{providers}`，每项含 `provider_id` / `name` / `protocol` / `base_url` / `api_key` / `rpm_limit` / `model_count`。
- `POST /api/providers`：创建端点。
  - 请求体：`{"name": "本地 Ollama", "protocol": "openai-compatible", "base_url": "http://127.0.0.1:11434/v1", "api_key": "", "rpm_limit": 60}`
  - `protocol` 会规范化为 `openai` / `anthropic` / `anthropic_compatible` / `gemini`；未知协议 400。
  - `rpm_limit` 为 0 表示不限，上限 6000；超限的请求会等到有配额（单次最多 60 秒，超过报错）。
  - `anthropic-compatible` 必须给 `base_url`；同一（协议, 地址）重复创建会 400（一个端点只有一份配额）。
- `PUT /api/providers/{provider_id}`：部分更新；改地址等于把配额搬到新端点，下一次请求生效。
- `DELETE /api/providers/{provider_id}`：删除端点；其下还有模型时返回 409，先删除或迁走模型。
- `GET /api/models`：返回 `{models}`，每项含 `model_id` / `name` / `provider_id`，并附带解析出的 `provider_name` / `protocol` / `base_url`。
- `POST /api/models`：创建模型。
  - 请求体：`{"name": "qwen3:0.6b", "provider_id": "<provider_id>", "supports_tool_calls": true, "supports_image_input": false, "thinking_mode": false, "max_input_tokens": 32768, "max_output_tokens": 8192}`
  - `provider_id` 不存在时 400（模型必须能解析到端点）。
- `PUT /api/models/{model_id}`：部分更新，含换 Provider。
- `DELETE /api/models/{model_id}`：删除模型，不影响 Provider。

任务仍用 `model_id` 指定模型（`POST /api/tasks`），运行时会连同它的 Provider 一起解析成实际请求的地址与 Key。
