# Web Admin

Web Admin 负责任务管理、任务详情与任务明细展示。

## 启动

```bash
uv run python main.py --web
```

默认地址：`http://127.0.0.1:8001`

## 开发调试

```bash
cd web-admin
npm install
npm run build
```

或直接开发模式：

```bash
cd web-admin
npm run dev
```

## 目录结构

- `src/`：前端源码
- `dist/`：构建产物

## 后端接口

- `POST /api/tasks`：新增任务
- `GET /api/tasks`：任务列表
- `GET /api/tasks/{task_id}`：任务详情
- `GET /api/tasks/{task_id}/events`：分页任务明细
- `GET /api/tasks/{task_id}/events/stream`：SSE 流
- `GET /api/healthz`：服务健康检查
- `GET /api/admin/retention` / `PUT /api/admin/retention`：备份保留策略

运行参数：

- `WEB_MONITOR_HOST`：监听地址（默认 `127.0.0.1`）
- `WEB_MONITOR_PORT`：监听端口（默认 `8001`）
