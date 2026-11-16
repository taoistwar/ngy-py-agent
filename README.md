# NGY Agent

基于 ReAct 的 CLI Agent 示例，支持命令行执行和 Web Admin 管理中心。

## 快速开始

生产启动与开发启动（依赖安装、前端构建、启动命令、监听参数）统一见 [docs/quickstart.md](docs/quickstart.md)。

最短路径：

```bash
uv sync
cd web-admin
npm install
npm run build
cd ..
uv run python main.py --web
```

默认地址：`http://127.0.0.1:8001`。

## 文档

- 快速开始（生产 / 开发启动）：[docs/quickstart.md](docs/quickstart.md)
- 用户文档：[docs/guide/README.md](docs/guide/README.md)
- 开发者文档：[docs/dev.md](docs/dev.md)
