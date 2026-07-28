# 开发者文档

## 1. 环境依赖

- Python 3.12+
- uv
- Node.js 18+
- npm 或 bun（二选一）

## 2. 项目安装

```bash
uv sync
cd web-admin
npm install
cd ..
```

## 3. 环境变量

常用配置：

- `NGY_PY_AGENT_MODE=dev`
- `NGY_PY_AGNET_QUERY=...`
- `REACT_MAX_STEPS=8`
- `WEB_MONITOR_HOST=127.0.0.1`
- `WEB_MONITOR_PORT=8001`
- `TASK_RETENTION_DAYS=36600`（默认 36600 天，约 100 年）
- 供应商相关：
  - `TOOL_SCHEMA_PROVIDER=openai`
  - `OLLAMA_BASE_URL`
  - `OLLAMA_MODEL`
  - `OLLAMA_API_KEY`
  - `ANTHROPIC_MODEL`
  - `ANTHROPIC_API_KEY`
  - `GEMINI_MODEL`
  - `GEMINI_API_KEY`

## 4. 启动方式

```bash
uv run python main.py
uv run python main.py --interactive
uv run python main.py --web --reload
```

## 5. Web Admin 前端目录与构建

- 前端约定目录：`web-admin/`
- 后端优先读取：
  - `web-admin/dist/index.html`
  - 如果 `dist` 不存在则读取 `web-admin/index.html`

### 构建前端

```bash
cd web-admin
npm run build
cd ..
uv run python main.py --web --reload
```

### 本地开发（Vite）

```bash
cd web-admin
npm run dev
```

### 访问地址

- 后端服务地址：`http://127.0.0.1:8001`
- 本地 Vite 调试地址：`http://127.0.0.1:3000`

## 6. API 联调

- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/events`
- `GET /api/tasks/{task_id}/events/stream`
- `GET /api/tasks/{task_id}/events/ws`
- `GET /api/healthz`
- `GET /api/admin/retention`
- `PUT /api/admin/retention`

WebSocket 示例：

```js
const ws = new WebSocket("ws://127.0.0.1:8001/api/tasks/task-001/events/ws?since=<eventId>&heartbeat=10")
ws.onmessage = (event) => {
  const payload = JSON.parse(event.data)
  console.log(payload)
}
```

## 7. 持久化与备份管理

- 任务与明细落库文件：`monitor_tasks.db`（SQLite）
- 重启服务后历史仍保留（取决于 `TASK_RETENTION_DAYS` / 管理中心配置）
- 可通过后端 API 实时调整保留天数：`PUT /api/admin/retention`

## 8. 前端国际化（i18n）文案维护

- 目前支持语言：
  - `en`
  - `zh-CN`
- 规范：所有界面文案通过 `web-admin/src/i18n.js` 的 `t(locale, key)` 获取，不允许在 `web-admin/src/*.jsx/.js` 中写入直接中文文本。
- 文案文件位置：
  - `web-admin/src/locales/en.json`
  - `web-admin/src/locales/zh-CN.json`
- 新增或修改文案时的检查清单：
  - 先在 `en.json` 新增/更新 key-value。
  - 再在 `zh-CN.json` 增加同名 key（缺失会回退显示 `key` 本身）。
  - 保持两份文件的 key 集合一致。
  - 前端页面调用时统一使用 `translate("...")` 或对应 helper（如 `getTaskStatusText`）。
- 快速校验：
```bash
cd web-admin
npm run i18n:check
```

## 9. CI 检查

- 仓库默认包含 `.github/workflows/ci.yml`，包含两条线：
  - `web-admin`：安装前端依赖并执行 `npm run build`（内含 i18n 键一致性检查）。
  - `backend`：安装 `uv` 后执行 `uv sync`，再执行 `uv run python -m compileall -q main.py agent/agent_loop.py` 做语法检查，并执行 `uv run python main.py --help` 做入口参数可用性检查。
- 如果后端 CLI 检查失败，优先排查：
  - 是否已执行 `uv sync`。
  - 是否新添了 CLI 参数但未在解析逻辑中添加默认值。
  - 是否有语法错误或环境依赖导入在 `main.py` 启动时触发。

## 10. CI 失败排查（后端）

- 后端 CI 的 `Check backend CLI entry` 失败时会输出统一的建议：
  - 先执行 `uv sync`。
  - 检查 `main.py` 启动阶段是否有导入错误。
  - 检查新增的 CLI 参数是否已设置默认值并正确注册。## 11. Local CI one-shot

- Run full local check in one command from repo root:
  - `python scripts/ci_check.py`
- Run the same check from web-admin directory:
  - `cd web-admin`
  - `npm run ci-check`

### Windows note

- If local check fails at `npm ci` with `EPERM` unlink errors:
  - close Vite/dev servers or editors that may hold `esbuild.exe`
  - rerun `python scripts/ci_check.py`
  - if still failing, this script now falls back to `npm install --no-audit --no-fund` for local use.
