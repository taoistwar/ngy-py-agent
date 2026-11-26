# 快速开始

本文只讲怎么把服务跑起来，分「生产启动」与「开发启动」两种方式。参数、接口与内部设计的细节见 [开发者文档](dev.md) 与 [用户指南](guide/README.md)。

## 1. 环境依赖

| 依赖 | 版本 |
| --- | --- |
| Python | 3.12+ |
| uv | 任意近期版本 |
| Node.js | 18+ |
| npm 或 bun | 二选一（下文以 npm 为例） |

## 2. 安装依赖

后端与前端各装一次：

```bash
uv sync
cd web-admin
npm install
cd ..
```

## 3. 生产启动

生产启动只有一个进程：后端读取前端构建产物 `web-admin/dist/` 并一起对外提供页面与 API。

### 3.1 构建前端

```bash
cd web-admin
npm run build
cd ..
```

产物落在 `web-admin/dist/`。后端优先读 `web-admin/dist/index.html`；`dist` 不存在时回退到 `web-admin/index.html`（会缺构建资源，仅供本地应急）。

### 3.2 启动服务

```bash
uv run python main.py
```

默认地址：`http://127.0.0.1:8001`。

需要换个监听地址或端口时：

```bash
uv run python main.py --host 0.0.0.0 --port 8080
```

启动参数：

```text
--host HOST          监听地址（默认 127.0.0.1）
--port PORT          监听端口（默认 8001）
--reload             运行时热重载（生产环境不要开）
```

### 3.3 验证

```bash
curl http://127.0.0.1:8001/api/healthz
```

浏览器打开上面的地址即可进入 Web Admin。

### 3.4 运行期数据

- 模型端点、API Key、模型与全局配置都存在数据库里（`monitor_tasks.db`，仓库根目录），**不在** `.env` 里配。
- 进程启动时会自动加载仓库根目录的 `.env`；需要预置的只有「读数据库之前就要生效」的开关。可从 `.env.example` 复制一份：

```bash
cp .env.example .env
```

- `.env` 已被 git 忽略，不要提交，也不要写入真实密钥。
- 任务与对话持久化在 `monitor_tasks.db`，服务重启后历史仍在；被重启打断的任务会在启动时自动续跑（见 [断点续跑](guide/api-tasks.md)）。

## 4. 开发启动

开发时后端开热重载、前端跑 Vite dev server，页面改动无需重新构建。

### 4.1 启动后端

```bash
uv run python main.py --reload
```

默认监听 `http://127.0.0.1:8001`。建议同时设置：

```bash
NGY_PY_AGENT_MODE=dev
```

### 4.2 启动前端（另开一个终端）

```bash
cd web-admin
npm run dev
```

- 前端调试地址：`http://127.0.0.1:3000`
- Vite 已把 `/api` 代理到 `http://127.0.0.1:8001`，浏览器只访问 3000 端口即可。

### 4.3 改前端后要验证生产形态时

改完前端、想确认「构建产物 + 后端直出」这条路径没问题，回到生产启动的第 3 步重新 `npm run build` 再访问 8001。

## 5. 环境变量

常用项（完整清单与说明见 [开发者文档 · 环境变量](dev.md#3-环境变量)）：

- `NGY_PY_AGENT_MODE=dev`：开发模式标记。
- `WEB_MONITOR_HOST` / `WEB_MONITOR_PORT`：监听地址与端口的默认值（命令行参数优先）。
- `TASK_RETENTION_DAYS`：任务保留天数。
- `TRANSCRIPT_MAX_MESSAGES`、`CONTEXT_CHAR_LIMIT`、`CONTEXT_SUMMARY_ENABLED`：上下文与压缩相关。
- `TOOL_DENYLIST_CONFIG`：工具黑名单规则文件路径。
- `OTEL_*`：可观测开关，默认关闭。

## 6. 常见问题

- **页面 404 或样式全丢**：没有构建前端，执行 `cd web-admin && npm run build`。
- **端口被占用**：`--port` 换一个，或用 `WEB_MONITOR_PORT` 改默认值。
- **模型配置改错导致任务失败**：模型与 provider 在 Web Admin「全局配置」里改，不由 `.env` 提供，改完不需要重启。
- **本地 CI 在 `npm ci` 报 `EPERM`**：先关掉占用 `esbuild.exe` 的 Vite dev server，再执行 `python scripts/ci_check.py`（脚本会回退到 `npm install`）；细节见 [开发者文档 · Local CI](dev.md#11-local-ci-one-shot)。
