# 用户指南

- 开发者请先阅读 [开发者文档](../dev.md)。

## 内容索引

- [Web Admin 管理中心](web-admin.md)：任务台用法与启动参数。
- [可观测（Tracing）](tracing.md)：开启方式、span 结构、从任务找 trace。
- [API：任务与撤销](api-tasks.md)：任务/事件接口、停止、撤销改动、断点续跑、明细保留。
- [API：智能体、MCP 与技能](api-agents.md)
- [API：工作空间、会话与 AGENTS.md](api-workspaces.md)
- [API：Provider 与模型](api-models.md)
- [API：工具管理](api-tools.md)
- [工具：`exec_command`](tool-exec-command.md)
- [工具：`web_search`](tool-web-search.md)
- [工具：`web_fetch`](tool-web-fetch.md)
- [工具：`web_browser`](tool-web-browser.md)
- [工具：`ask_user_question`](tool-ask-user-question.md)
- [工具：`computer_observe` / `computer_control`](tool-computer.md)
- [工具黑名单（denylist）](tool-denylist.md)

## 运行方式

依赖安装、生产启动、开发启动（含前端构建与 Vite 调试）统一见 [快速开始](../quickstart.md)。

要点：唯一入口是 `--web`（管理界面 + API）。单次运行（`--query`）与交互式 CLI（`--interactive`）都已移除：一次性任务走 Web Admin 的 `POST /api/tasks` 或在界面里提交，多轮对话就是 Web Admin 里的会话。provider、模型与步数都在数据库与「全局配置」里，不再有对应的命令行参数。

## 备注

- 任务与事件持久化存储在仓库根目录 `monitor_tasks.db`，服务重启后可继续查询历史；被重启打断的任务会在启动时自动续跑（见 [断点续跑](api-tasks.md)）。
- WebSocket 重连可带 `since`，避免重复消费事件。
