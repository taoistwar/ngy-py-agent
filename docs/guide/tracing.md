# 可观测（Tracing）

默认关闭，行为与原来完全一致。需要看一次执行到底走了哪几步时再打开：

```bash
# 临时开一次，输出到控制台
OTEL_TRACING_ENABLED=true OTEL_TRACES_EXPORTER=console uv run python main.py --web
```

长期开启就写进 `.env`（字段见 `.env.example`）：

```dotenv
OTEL_TRACING_ENABLED=true
OTEL_TRACES_EXPORTER=jsonl
OTEL_TRACES_JSONL_PATH=data/traces/spans.jsonl
```

`data/traces/` 已在 `.gitignore` 中，属于本机运行时产物。

## 一次任务长什么样

一条 trace 覆盖 `HTTP 请求 → 任务 → 每个 ReAct 步骤 → 模型请求 / 工具调用`：

| span | 何时产生 | 关键属性 |
| --- | --- | --- |
| `POST /api/tasks`（或任意接口） | 每个 HTTP 请求 | `http.method`、`http.route` |
| `task` | 每个任务（CLI 单次运行也有） | `task.id`、`task.mode`、`react.max_steps` |
| `react.step` | 每一轮循环 | `react.step`、`react.max_steps` |
| `chat <模型名>` | 每次模型请求 | `gen_ai.system`、`gen_ai.request.model`、`gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`、`gen_ai.response.finish_reasons` |
| `execute_tool <工具名>` | 每次工具调用 | `gen_ai.tool.name`、`gen_ai.tool.call.arguments`（已脱敏、已截断） |

模型请求失败或工具抛异常时，对应 span 的状态是 `ERROR`，异常摘要写在 `status.description` 里；工具异常仍然照旧回给模型（不会因为埋点改变行为）。

## 从任务到 trace

事件流（Web Admin 的任务详情）没有变化，只是每条事件的 `data` 在 tracing 开启时多了两个键：

- `trace_id`：整条链路的标识；
- `span_id`：这条事件所属 span。

拿任务详情里 `Start task execution` 事件的 `data.trace_id`，就能把同一次执行的全部 span 捞出来：

```bash
# Linux / macOS / Git Bash
grep '"trace_id": "153f3acc75b230d58bff65dc2357d203"' data/traces/spans.jsonl

# PowerShell
Select-String -Path data/traces/spans.jsonl -Pattern '"trace_id": "153f3acc75b230d58bff65dc2357d203"'
```

每一行是一条完整 JSON，字段固定：

```json
{
  "trace_id": "153f3acc...",
  "span_id": "c7202dea...",
  "parent_span_id": "87fa7bc3...",
  "name": "chat qwen3:0.6b",
  "kind": "CLIENT",
  "start_time": 1792726072405,
  "end_time": 1792726086102,
  "start_time_ns": 1792726072405327100,
  "end_time_ns": 1792726086102397800,
  "started_at": "2026-10-23T03:27:52.405327+00:00",
  "duration_ms": 13697.071,
  "status": {"code": "ERROR", "description": "LLMCallError: ..."},
  "attributes": {"gen_ai.system": "openai", "gen_ai.request.model": "qwen3:0.6b"}
}
```

`parent_span_id` 为空的是根 span；按它把行拼起来就是调用树。写入采用批量刷盘，进程正常退出时会把剩余 span 落盘。
