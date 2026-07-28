# NGY Agent

基于 ReAct 的 CLI Agent 示例，支持命令行执行和 Web Admin 管理中心。

## 快速启动

```bash
uv run python main.py
```

## 启动 Web Admin

```bash
uv run python main.py --web
```

默认地址：`http://127.0.0.1:8001`

自定义监听地址示例：

```bash
uv run python main.py --web --host 0.0.0.0 --port 8080 --reload
```

## 文档

- 用户文档：[docs/guide.md](docs/guide.md)
- 开发者文档：[docs/dev.md](docs/dev.md)

## 前端资源

管理前端位于 `web-admin/`，启动前请先执行 `npm run build` 生成 `web-admin/dist/`。
