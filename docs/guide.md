# 用户指南

- 开发者请先阅读 [docs/dev.md](dev.md)。

## 运行方式

### 单次运行

```bash
uv run python main.py
```

默认会执行内置示例问题，并走 ReAct + 工具调用流程。

### 指定问题（单次）

```bash
uv run python main.py "What's the weather in Tokyo?"
```

### 指定 Provider

```bash
uv run python main.py --provider openai-compatible
uv run python main.py --provider openai
uv run python main.py --provider anthropic
uv run python main.py --provider anthropic-compatible
uv run python main.py --provider openai-compatible --steps 4
```

说明：`openai-compatible` 会走 OpenAI 兼容接口。

### 交互模式

```bash
uv run python main.py --interactive
uv run python main.py --interactive --trace
```

### 仅输出最终结果

```bash
uv run python main.py --quiet "What's the weather in Vancouver?"
```

## Web Admin 管理中心

```bash
uv run python main.py --web
```

启动后访问：

```text
http://127.0.0.1:8001
```

### 参数说明（关键）

```text
--web
--host HOST          监听地址（默认 127.0.0.1）
--port PORT          监听端口（默认 8001）
--reload             运行时热重载
```

## API 说明

### 任务管理

- `POST /api/tasks`：创建任务，返回 `task_id`。
- `GET /api/tasks`：查询任务列表。
- `GET /api/tasks/{task_id}`：查询单个任务详情。
- `GET /api/tasks/{task_id}/events`：分页查询任务事件。
  - `offset`：起始偏移（默认 `0`）
  - `limit`：每页数量（1-100，默认 `30`）
- `GET /api/tasks/{task_id}/events/stream`：SSE 事件流。
- `GET /api/tasks/{task_id}/events/ws`：WebSocket 事件流。
  - `since`：按 `event_id` 增量拉取
  - `heartbeat`：心跳间隔（秒）
- `GET /api/healthz`：服务健康检查。

### 备份管理（任务明细保留）

- `GET /api/admin/retention`：读取当前保留配置。
  - 返回字段：
    - `retention_days`：当前保留天数
    - `retention_source`：`env` 或 `database`
    - `removed_tasks`：最近一次清理移除数量（`GET` 返回 0）
- `PUT /api/admin/retention`：设置保留天数。
  - 请求体：`{"retention_days": 30}`
  - `0` 表示关闭清理（保留全部任务明细）

默认 `.env` 也支持：

```
TASK_RETENTION_DAYS=36600
```

## 运行前端（源码开发）

前端源码位于：

- `web-admin/`
- 打包产物路径：`web-admin/dist/`

## 构建与运行前端

```bash
cd web-admin
npm install
npm run build
cd ..
uv run python main.py --web
```

```bash
cd web-admin
npm run dev
```

## 备注

- 任务与事件持久化存储在仓库根目录 `monitor_tasks.db`，服务重启后可继续查询历史。
- WebSocket 重连可带 `since`，避免重复消费事件。
