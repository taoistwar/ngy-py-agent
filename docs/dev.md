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
- `REACT_MAX_STEPS=8`（ReAct 全局最大步数的环境变量默认值；Web Admin「全局配置」页可在前端修改并落库到 `settings` 表，`agent_max_steps` 优先于环境变量）
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
- 全局配置（最大步数、任务保留天数）存于 `settings` 表（`agent_max_steps`、`task_retention_days` 两键），可在 Web Admin「全局配置」页修改；DB 值优先于同名环境变量。

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
- `POST /api/tasks/{task_id}/permission/{request_id}`（回答待确认的工具调用）
- `GET /api/healthz`
- `GET /api/admin/retention`
- `PUT /api/admin/retention`
- `GET /api/admin/permission-mode`
- `PUT /api/admin/permission-mode`
- `GET /api/admin/permission-rules`
- `POST /api/admin/permission-rules`
- `DELETE /api/admin/permission-rules?tool=&target=`

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
  - `backend` 测试：逐个执行 `test/**/*_test.py`（`test/` 不是包，所以不用 `unittest discover`；本地等价命令见 `scripts/ci_check.py`）。
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

## 12. 工具设计约束

### read_file 永远带行号

- `read_file` 的返回内容一律带 `N<TAB>` 行号前缀（`agent/tools/file_read_tool.py` 的 `LINE_NUMBER_SEPARATOR` / `_format_lines`），**不提供 `include_line_numbers` 之类的开关**。
- 分隔符用制表符而不是 `| `：同样能对齐，但每行只占 1 个字符，比 `| ` 少一个字符。
- 原因：模型看不到文件的真实行号，也不具备可靠的行号推算能力。返回不带行号的正文，会让后续所有“把第 N 行改掉”“第 N 行有问题”的引用变成猜测，而猜错的行号会直接传导到写操作上。
- 代价：读 2000 行大约多花 4000 个 token。这个开销是明知的，且远小于一次错行号的返工成本。
- 因此：不要为了省 token 给这个行为加开关，也不要让 `_format_lines` 支持“无前缀”模式。
- 相关说明页：`docs/tools/read_file/eli5-line-numbers.html`

### 相对路径的基目录（有工作空间 vs 无工作空间）

- 有工作空间：相对路径以会话绑定的工作空间根为基准，且**不得逃出**该目录。
- 无工作空间（未绑定会话）：相对路径以**会话默认目录** `<程序启动路径>/data/default_workspace` 为基准（`DEFAULT_WORKSPACE_DIR` 可覆盖）。它是**基目录不是边界**——`..` 仍可离开，全局策略照旧生效。
- 解析是三个文件工具**共用**的一条路径（`file_access._resolve_path`），所以三者的相对路径语义**必须一致**。不要只给某一个工具加特例：那会造成"写得进去、读不回来"。
- 写入时按需创建默认目录（`write_file` 新建文件要求父目录存在），**读取不创建**：一次查找不该有副作用。
- 未绑定会话的 system prompt 会明确告知该目录，别把这段文案删掉（只改解析等于修一半）。取舍见 [ADR 0007](decisions/0007-default-workspace.md)。

### read_file 保留原始换行（不要规范化）

- `read_file` **不把行尾统一成 `\n`**：`N<TAB>` 之后的正文原样保留 `\r\n` / `\n` / `\r`（`agent/tools/text_lines.py` 的 `split_line_ending`）。
- 原因：`edit_file` 做**严格字节匹配**，而模型只能用 `read_file` 看到的文本构造 `old_string`；一旦在这里规范化换行，CRLF 文件上的多行编辑必然失配。
- 因此：`read_file` 与 `edit_file` 的换行处理**成对**存在，改一个必须评估另一个。细节见 [ADR 0001](decisions/0001-file-edit-tool.md)。

### 文件编码：不猜、报错、让模型带参数重试

- `read_file` / `edit_file` 都接受可选 `encoding`（默认 UTF-8），**BOM 优先于该参数**。
- 解码失败**不静默回退**：返回 `decode_failed` 与 `suggested_encodings`（BOM → `charset-normalizer` → 候选试探），由模型带上 `encoding` 重试。取舍见 [ADR 0002](decisions/0002-file-encoding.md)。
- 不要拿检测结果自动重读——猜错就是静默读错。
- 不要把 BOM 留在正文里，也不要让它进 `read_file` 的 `content`：读取文本与 `edit_file` 匹配用的文本必须一致。

### edit_file 的补丁是整行的

- `structured_patch` / `gitDiff` 的行是**文件的真实整行**：`-` 是受影响行的完整原文，`+` 是替换后的完整新文；同一行多处匹配合成一个 hunk。
- `gitDiff` 保留 `\r`（否则 CRLF 文件的补丁无法 `git apply`），`structured_patch` 剥掉行尾（只给人看）。**改补丁格式前先跑 `git apply --check` 用例**。
- 写入是**字节级拼接**：只替换匹配到的字节区间，其余字节原样搬运。不要改回"整文件解码再重编码"——`cp932` / `big5` 会因此改写未触碰的字节。理由见 [ADR 0003](decisions/0003-edit-write-and-patch.md)。
- 行只由 `\n` / `\r\n` / `\r` 终止（`text_lines.split_lines`），**不要用 `str.splitlines()`**，它多认 `\x0b`、`\x0c`、`\x1c`-`\x1e`、`\x85`、`\u2028`、`\u2029`，会让补丁行号与读取行号错位。
- 说明页：`docs/tools/edit_file/eli5-whole-line-patch.html`。

### write_file 的读前置（不要拆掉）

- 覆盖**已存在**文件前，必须同时满足：本 run 内对该文件有过一次**完整读取**（第 1 行、不带 `limit`），且 `st_mtime_ns` + `st_size` 与那次读取一致。不满足分别报 `read_required` 与 `file_changed`。
- `limit` 或 `offset > 1` 的读取**不解锁**覆盖：模型没看到的内容不许被覆盖。
- 账本（`ReadLedger`）由 `ToolRegistry` 持有，一个 run 一份；写入成功后会随文件更新，所以连续写入、以及"读 → 编辑 → 覆盖"都无需再读。
- 这是该工具唯一能强制的保护。`write_file` 的失败模式是无界的（整文件被毁），不要为了"顺手"去掉它。
- 相关取舍见 [ADR 0004](decisions/0004-file-write-tool.md)；说明页：`docs/tools/file_write/eli5-read-before-write.html`。
- 追加**不用新工具**：把 `edit_file` 的锚点放在最后一行即可（幂等，大文件同样可行）。

### exec：命令执行，以及它的 containment 到底管什么

- `exec` 只约束**资源与进程生命周期**：Windows 用 Job Object（进程数上限 + job 内存上限 + 整树终止），POSIX 用新会话 + `killpg`。POSIX **没有**内存上限（`preexec_fn` 在线程模型里不安全），文档里不要写成有。
- 这**不是安全边界**：命令能读写进程用户碰得到的任何路径，工作空间约束对它无效。`containment.note` 就是为此存在的，不要删。
- 低完整性（L2）**未启用**：机制已验证可用（令牌降到 Low、写入被拒），但单独开启会让普通命令连临时目录都写不了；启用前需要给工作空间加 ACL 授权与撤销路径。见 [ADR 0005](decisions/0005-exec-tool.md)。
- Windows 上**不要**把 `bash` 加进候选：本机 `bash.exe` 是 WSL 启动器，命令会跑在另一个文件系统里。
- 工具描述按平台生成，结果里必须报告**实际 shell 与版本**——模型要知道自己在写哪种方言（`$env:FOO` 还是 `$FOO`）。
- 凭据类环境变量默认不下发（纵深防御，不是边界）；`EXEC_PASS_SECRET_ENV=1` 可关闭。
- `interrupted` **只表示超时**。`stop` 是协作式的，杀不掉正在执行的命令，所以它不代表"用户停止"。
- 说明页：`docs/tools/exec/eli5-not-a-sandbox.html`。

### 大输出与只读附加根

- 命令输出超过 token 预算就落盘到系统临时目录，模型拿到预览 + 路径，用 `read_file` 分段读回。
- 该目录通过 `extra_read_roots` **可读不可写**（写报 `read_only_root`）。这是 [ADR 0001](decisions/0001-file-edit-tool.md) D3 的显式例外，不要把它当成漏洞"修掉"。
- 全局策略依然作用于它：`allow_dirs` 非空时输出目录会不可达，这是有意的。
- 进入事件 `details` 的 stdout/stderr 截到 64 KiB（命令输出无上限），完整文本只在磁盘上。

### 工具结果分流（模型 vs UI）

- 工具若需要把结构化记录交给 UI/外部消费者，**不要**把它塞进返回给模型的字符串：返回 `ToolOutcome`（`model_text` + 事件类别/标题 + `details`），由 `agent_loop` 拆分。
- 首个用例是 `edit_file`：模型只收到一行成功摘要，`original_file` / `structured_patch` / `gitDiff` 走独立的 `file_edit` 事件。
- `write_file` 同理，走**独立**的 `file_write` 事件（不复用 `file_edit`：整体替换与局部替换对 UI 是两件事）。新增事件类别时别忘了前端 i18n 与 `.tag.<category>` 样式。

### 权限确认（P1）

详见 [ADR 0006](decisions/0006-tool-permission-confirmation.md)。改动这条链路时最容易踩的三个点：

- **门禁写在 `ToolRegistry.execute_tool` 这个唯一收口上**，不要写进各个工具内部（工具拿不到 `EventSink`，而且按工具加门禁的默认结局是漏掉某个工具）。新增工具时必须在 `ToolSpec.permission` 里声明种类，默认 `none`＝永不询问。
- **`TaskStatus.WAITING` 仍属"进行中"**：`/events/stream`、WebSocket 循环与前端 `isTaskRunningStatus` 都必须把它当作在飞行中。否则事件流会在用户最需要看到确认请求的那一刻断掉（这个坑已踩过一次）。
- **scope 不做降级**：未知取值返回 400。把 `always` 静默降级成 `once` 会让用户以为已经长期允许了。

## 13. 决策记录与术语

- 设计决策（ADR）：`docs/decisions/`，命名 `NNNN-<topic>.md`。新增需要"解释为什么"的取舍时，先写 ADR 再改代码。
- 术语表：`docs/glossary.md`。新增领域名词（工具、事件、策略、patch 结构等）时同步补条目。
- 当前已有：
  - [ADR 0001 `edit_file` 工具的设计](decisions/0001-file-edit-tool.md)
  - [ADR 0002 文件工具的编码策略](decisions/0002-file-encoding.md)
  - [ADR 0003 `edit_file` 的写入与补丁语义](decisions/0003-edit-write-and-patch.md)
  - [ADR 0004 `write_file` 工具的设计](decisions/0004-file-write-tool.md)
  - [ADR 0005 `exec` 工具与沙箱分层](decisions/0005-exec-tool.md)
  - [ADR 0006 工具权限确认（P1 交互式确认）](decisions/0006-tool-permission-confirmation.md)
  - [ADR 0007 未绑定会话的相对路径基目录](decisions/0007-default-workspace.md)
