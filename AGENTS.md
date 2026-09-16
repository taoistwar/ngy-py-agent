# AGENTS.md

## 范围

本仓库是一个基于 ReAct 的 CLI Agent 示例，入口在 `main.py`，`agent/` 目录包含 provider 与工具的适配逻辑。

## 规则

- 本仓库文档使用中文。
- 代码及代码注释使用英文，尽量避免中文注释进入源码。
- `README.md` 仅保留精简入口信息（项目简介、快速开始、文档入口）。
- 详细使用文档（参数、示例、运行方式）统一放到 `docs/guide.md`。
- 开发者细节文档放到 `docs/dev.md`。
- 单个源码文件应优先拆分为多个源码文件；单个方法应优先拆分为多个更小方法，不应等到“文件太大/方法太长”才改。
  - 建议门槛（用于执行）：一个文件出现明显多个职责（输入/计算/输出、网络/持久化/业务）时立即拆分；一个方法包含两个以上职责阶段（如验证-组装-调用、查询-处理-输出）时优先拆成子方法。 
- 如无明确要求，优先保持现有行为不变，最小化改动范围。
- 涉及运行时行为调整时，优先只修改 `main.py` 与 `agent/agent_loop.py`，避免无关文件扩散。

## AI 辅助修改建议的快速校验

- 语法检查：
  - `python -m compileall -q main.py agent/agent_loop.py`
- 冒烟验证：
  - `uv run python main.py --help`
  - `uv run python main.py --steps 2 --quiet`
  - `uv run python main.py --interactive --quiet`（如当前环境可交互）

## 环境说明

- 启动时会自动读取仓库根目录 `.env`。
- 支持的 provider 标识包括：`openai-compatible`、`openai`、`anthropic`、`anthropic-compatible`。
