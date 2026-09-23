# AGENTS.md

## 范围

本仓库是一个基于 ReAct 的 CLI Agent 示例，入口在 `main.py`，`agent/` 目录包含 provider 与工具的适配逻辑。

## 规则

- 本仓库文档使用中文。
- 源码文件不能过大:
  - 大文件既难阅读也难修改，工具读一次就吃掉上下文。
  - **单个源码文件不得超过约 700 行。
    - **超过就按职责拆成子模块，不要继续往上堆：新增代码时如果目标文件已经接近这个上限，先拆再改。拆完后，记得要git commit。
  - 拆分沿用现有惯例：
    - `foo.py` 改成 `foo/__init__.py` 加若干 `foo/*.py`（测试同理，`test/tools/foo_test.py` 改成 `test/tools/foo/foo_test.py`）。
    - `__init__.py` 只放文档、导入和对外面（`from ...tool import ...` 这类重新导出），共享类型要单独出来；
    - 实现按主题分文件：`description.py`（描述与参数 schema）、按职责命名的主题模块、`tool.py`（工厂/入口），同一类型的实现可以分散在多个文件里。
    - **一个工具一个包，包名 = 模型可见工具名**（`exec_command/`、`write_stdin/`、`read_file/`…），实现细节不跨包暴露；工具包只依赖共享基础设施，不反向 import 声明层。
    - 测试同样拆分，并镜像源码布局：`test/tools/<tool>/<tool>_test.py`；跨工具的集成测试留在 `test/tools/`。
    - 测试文件名要添加 `_test`，例如 `foo.py` 的测试叫 `foo_test.py`。
- 业务开发时
  - 遵循模块化和单一职责原则，保持代码清晰和可维护性。
  - 先开发UI，后开发后端。
  - 无论UI和后端，都使用TDD。
  - 具体业务，要在每一步中，添加调试工信息（debug）。
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
- Node 用的fnm管理，使用命令 `fnm use v26.8.1` 启动node。