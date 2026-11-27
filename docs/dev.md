# 开发者文档

## 1. 环境依赖

- Python 3.12+
- uv
- Node.js 18+
- npm 或 bun（二选一）

## 2. 项目安装

依赖版本、`uv sync` / `npm install`、前端构建与两种启动方式统一见 [快速开始](quickstart.md)。

## 3. 环境变量

常用配置：

- `NGY_PY_AGENT_MODE=dev`
- `WEB_MONITOR_HOST=127.0.0.1`
- `WEB_MONITOR_PORT=8001`
- `TASK_RETENTION_DAYS=36600`（默认 36600 天，约 100 年）
- `TRANSCRIPT_MAX_MESSAGES=50`（对话窗口条数上限，超出后旧消息归档到 `<workspace>/.ngy-agent/.transcripts/`，`<= 0` 关闭，见 [ADR 0015](decisions/0015-snip-compact.md)）
- `CONTEXT_CHAR_LIMIT`（整段上下文的字符上限，超出后缩短模型已读过的旧工具结果；未配置时取模型 `max_input_tokens × 4`，再退回 200,000，`<= 0` 关闭，见 [ADR 0016](decisions/0016-micro-compact.md)）
- `CONTEXT_SUMMARY_ENABLED=0`（关闭压缩管线的第四步——历史摘要。该步是唯一会额外发起模型调用的压缩步骤，见 [ADR 0017](decisions/0017-compact-history.md)）
- 供应商相关：
  - `TOOL_SCHEMA_PROVIDER=openai`
  - `OLLAMA_BASE_URL`
  - `OLLAMA_MODEL`
  - `OLLAMA_API_KEY`
  - `ANTHROPIC_MODEL`
  - `ANTHROPIC_API_KEY`
  - `GEMINI_MODEL`
  - `GEMINI_API_KEY`
- 工具黑名单：`TOOL_DENYLIST_CONFIG`（规则文件路径，默认 `data/tool_denylist.json`，见 [ADR 0024](decisions/0024-tool-denylist.md)）
- 桌面操作：
  - `CUA_DRIVER_BIN`（`cua-driver` 可执行文件路径；默认从 PATH 或 Windows 安装目录查找）
  - `TOOL_IMAGE_MAX_BYTES`（工具截图附加到模型上下文的大小上限，默认 `8388608`，即 8 MiB）
- 可观测（默认关闭，见第 15 节）：`OTEL_TRACING_ENABLED`、`OTEL_TRACES_EXPORTER`、`OTEL_TRACES_JSONL_PATH`、`OTEL_TRACES_SAMPLER_ARG`、`OTEL_SERVICE_NAME`

## 4. 启动方式

生产启动与开发启动（`--reload` + Vite dev server）见 [快速开始](quickstart.md)。

单次运行（`--query`）与交互式 CLI（`--interactive`）都已移除：一次性问题就是 Web Admin 的 `POST /api/tasks`，多轮对话就是 Web Admin 的会话；模型与 provider 在数据库里配置，不再依赖 `.env`。

## 5. Web Admin 前端目录与构建

- 前端约定目录：`web-admin/`
- 后端优先读取：
  - `web-admin/dist/index.html`
  - 如果 `dist` 不存在则读取 `web-admin/index.html`
- 全局配置（最大步数、工具确认模式、AGENTS.md 项目指令、任务保留天数）存于 `settings` 表（`agent_max_steps`、`permission_mode`、`agents_md_config`、`task_retention_days` 四键），可在 Web Admin「全局配置」页修改。确认模式与保留天数有同名环境变量作默认值且库值优先；**最大步数与 AGENTS.md 没有环境变量**，库值缺失时取代码默认（`DEFAULT_MAX_STEPS = 9`，见 `agent/agent_loop/config.py`；AGENTS.md 为开启、单文件 32768 字节，见 `agent/agents_md.py`），因此 `.env` 里再写 `REACT_MAX_STEPS`、`AGENTS_MD_ENABLED`、`AGENTS_MD_MAX_BYTES` 都不会生效。`agents_md_config` 是一行 JSON（`{"enabled": ..., "max_bytes": ...}`），两个字段共享一个来源标签。
- 任务详情的结果区：`src/components/TaskResultPanel.jsx` 负责「渲染 / 源码」切换与全屏阅读（portal 覆盖层，Esc 关闭）；Markdown 由 `src/components/MarkdownView.jsx` 渲染，解析在 `src/utils/markdown.js`（块级）与 `src/utils/markdownInline.js`（行内），排版样式在 `src/styles/markdown.css`。渲染产出 React 元素而非 HTML 字符串，模型输出里的标签只会显示成文本。
- 任务窗口的上下文占用：`src/components/ContextMeter.jsx` 渲染一个 18px 的环形进度（SVG `stroke-dasharray`，-90° 起点、圆头端点），悬停/聚焦时向上弹出面板给出百分比、`已用 / 上限`、输入输出明细与上限来源。数字格式化在 `src/utils/contextUsage.js`（1024 进制、一位小数，≥80% 变黄、≥95% 变红）。它随发送按钮一起右对齐，跟随会话与所选模型，每 5 秒读一次 `GET /api/sessions/{id}/context`，任务开始/结束时立即再读一次。

### 构建前端

构建命令与「构建后由后端直出」的验证方式见 [快速开始 · 生产启动](quickstart.md#3-生产启动)。

### 本地开发（Vite）

前端 dev server 与后端并跑的步骤见 [快速开始 · 开发启动](quickstart.md#4-开发启动)。访问地址：后端 `http://127.0.0.1:8001`，Vite `http://127.0.0.1:3000`（`/api` 已代理到后端）。

## 6. API 联调

- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/events`
- `GET /api/tasks/{task_id}/events/stream`
- `GET /api/tasks/{task_id}/events/ws`
- `POST /api/tasks/{task_id}/permission/{request_id}`（回答待确认的工具调用）
- `GET /api/sessions/{session_id}/context?model_id=`（任务窗口的上下文占用）
- `GET /api/healthz`
- `GET /api/admin/retention`
- `PUT /api/admin/retention`
- `GET /api/admin/permission-mode`
- `PUT /api/admin/permission-mode`
- `GET /api/admin/permission-rules`
- `POST /api/admin/permission-rules`
- `DELETE /api/admin/permission-rules?tool=&target=`
- `GET /api/admin/denylist`
- `POST /api/admin/denylist`
- `DELETE /api/admin/denylist?id=`

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

- 目前支持语言（`web-admin/src/i18n.js` 的 `LOCALES`）：
  - `en`（英文，源文本）
  - `zh-CN`（简体中文）
  - `zh-TW`（繁体中文）
  - `fr`（法语）
  - `de`（德语）
  - `ru`（俄语）
- 规范：所有界面文案通过 `web-admin/src/i18n.js` 的 `t(locale, key)` 获取，不允许在 `web-admin/src/*.jsx/.js` 中写入直接中文文本。
- 文案文件位置（`web-admin/src/locales/`）：`en.json`、`zh-CN.json`、`zh-TW.json`、`fr.json`、`de.json`、`ru.json`。
- 默认语言：先看 `localStorage`（`web-admin.locale`），再按 `navigator.language` 推断（`src/i18n.js` 的 `resolveLocale`）：
  - `zh-Hant` / `zh-TW` / `zh-HK` / `zh-MO` → `zh-TW`，其余 `zh-*` → `zh-CN`；
  - `fr-*` / `de-*` / `ru-*` 按主语言匹配；
  - 其余回退 `en`。
- 新增或修改文案时的检查清单：
  - 先在 `en.json` 新增/更新 key-value。
  - 再在其他每份语言包里增加同名 key（缺失会回退英文，`languageName` 缺失会显示 key 本身）。
  - 保持所有文件的 key 集合一致，新增语言时同时改 `LOCALES`、`MESSAGES` 与 `web-admin/scripts/check-i18n.mjs` 的 `LOCALE_FILES`。
  - 前端页面调用时统一使用 `translate("...")` 或对应 helper（如 `getTaskStatusText`）。
- 任务日志「易读」视图有一套独立的词表（字段名、枚举值、句式模板），放在 `web-admin/src/events/dictionary/<locale>.js`，一个语言一个文件，`en.js` 是源文本。新增语言时要一并补这个目录下的文件，键与 `en.js` 完全一致。
- 快速校验：
```bash
cd web-admin
npm run i18n:check
```
`npm run i18n:check` 会同时比对界面文案（`src/locales/*.json`）与事件词表（`src/events/dictionary/*.js`）的键集合。

## 9. CI 检查

- 仓库默认包含 `.github/workflows/ci.yml`，包含两条线：
  - `web-admin`：安装前端依赖并执行 `npm run build`（内含 i18n 键一致性检查）。
  - `backend`：安装 `uv` 后执行 `uv sync`，再执行 `uv run python -m compileall -q main.py agent commons dao routes` 做语法检查，并执行 `uv run python main.py --help` 做入口参数可用性检查。
  - `backend` 测试：逐个执行 `test/**/*_test.py`（`test/` 不是包，所以不用 `unittest discover`；本地等价命令见 `scripts/ci_check.py`）。
  - `backend` 静态检查：`uv run ruff check .`，规则集在根目录 `ruff.toml`（`E4/E7/E9/F/I/BLE/RUF012`）。**同一份规则也被 `scripts/ci_check.py` 与 `.githooks/pre-commit.py` 执行**，所以编辑器里的提示是会拦提交的：`F` 拦未定义名字与未用导入（曾扫出一段调用即 `NameError` 的残留死代码），`BLE` 要求每个宽捕获在代码里写明理由，`I` 让导入顺序不再成为讨论话题。
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
- 启用提交前钩子（编码检查 + 对暂存 Python 文件跑 ruff）：
  - `git config core.hooksPath .githooks`（只影响本仓库的这份克隆）

### Windows note

- If local check fails at `npm ci` with `EPERM` unlink errors:
  - close Vite/dev servers or editors that may hold `esbuild.exe`
  - rerun `python scripts/ci_check.py`
  - if still failing, this script now falls back to `npm install --no-audit --no-fund` for local use.

## 12. 工具设计约束

### glob：找文件是发现，不是导出

- `glob`（`agent/tools/glob/`）负责“知道文件名、不知道目录”这一步，返回的路径与 `read_file` 的解析基准相同（工作空间根），因此可以**原样**交给 `read_file`；不要把结果改成相对搜索根，否则模型还要自己拼前缀。
- **不隐式过滤**：没有 `.gitignore` 处理、不跳过隐藏文件、不剪掉 VCS 目录。模型无法猜出工具替它藏了哪些名字，藏就是错。理由是 `glob` 服务于“这个文件在哪”——目标可能是 `node_modules` 里的某份依赖实现，藏掉就搜不到。
- **排序：源码优先，然后才是最新**。截断决定留谁，所以顺序是设计的一部分：`node_modules`、`dist`、`.git` 这些**内容搜索根本不会打开的目录**排在最后（`is_generated_path`，见 `agent/tools/file_walk.py`），两组内部再按修改时间从新到旧。这是**排序不是隐藏**——每个命中仍在列表里，只是不占头部。证据：修之前 `**/*.js` 的 100 条里有 82 条是 `node_modules/.vite` 与 `dist` 的产物，修之后是 0 条。
- 三个上限都是有意的：`MAX_RESULTS = 100`（结果条数）、`MAX_SCANNED_ENTRIES = 50000`（遍历条目数）、以及单次调用不排序全库。遍历被提前终止时必须报 `scan_truncated`，不能假装结果完整。
- 模式语义照 ripgrep 的 `--glob`（`agent/tools/glob_pattern.py`）：`*` 不跨 `/`，`**` 跨段，`**/` 还能匹配零层目录，无 `/` 的模式只匹配文件名。**不要换成 `fnmatch` 或 `Path.glob`**：前者让 `*` 跨 `/`，后者没有 `{a,b}`、也没法按文件系统决定大小写。
- 目录遍历只走 `os.scandir`（`agent/tools/file_walk.py`）且**不跟随软链接目录**（防循环、防越界），软链接文件照常列出。
- 全局 `file_access` 策略在遍历时**剪枝**：被拒绝的目录不进入、被拒绝的文件不返回——“读不到的名字不应出现在列表里”。
- 权限种类声明为 `read`。`glob` 的参数是 `path` 而不是 `file_path`，所以权限门（`permissions.py` 的 `_target`）对 `read` 类工具读 `path`、缺省视为工作空间根；否则一次列目录会绕过 `deny_all`。

### grep：搜内容，边界比 glob 更紧

- `grep`（`agent/tools/grep/`）回答“这段代码写在哪里”。它和 `glob` 共用两处基础设施：模式匹配（`agent/tools/glob_pattern.py`，用于 `glob` 参数）与目录遍历（`agent/tools/file_walk.py`）。**两者必须共用**：一个能列出来、另一个却读不到的目录，就是一条没人会发现的缝。
- **没有 ripgrep 依赖**：用 Python `re` 逐行匹配，并在描述里明说语法是 `re` 而不是 Rust regex。`multiline` 打开 `DOTALL`；`^`/`$` 在任何模式下都是**行锚**（整文件扫描时额外加 `MULTILINE`），否则打开 multiline 后 `^def` 只会命中文件第一行。
- **三种输出形状**（`output_mode`）：`files_with_matches`（默认，最新优先）、`content`（`path:line:text`，上下文行用 `-` 分隔符，组间 `--`）、`count`（`path:count` + 总数，按次数降序）。`content` 的渲染与分页**同时进行**：`offset`/`head_limit` 数的是输出行，够数就停，不留一份十万行再截断。
- **与 `glob` 相反的过滤取舍**：内容搜索跳过 `.git` 等版本库目录、`.gitignore` 命中的文件、已安装依赖与构建产物（`node_modules`、`.venv`、`dist`、`build`、`target`…）、二进制文件、超过 8MB 的文件。理由是可测的：在本仓库根目录直接扫，不跳过依赖时 20 秒预算会先耗尽，跳过之后 200 毫秒返回。**显式把 `path` 指向被跳过的目录仍会搜**——显式请求优先。
- **`glob` 与 `grep` 的可见范围不同，是有意的**：一个问“文件在哪”（必须能定位任何文件，含依赖），一个问“这段代码在哪”（只该看仓库自己的源码）。所以别为了“一致性”给 `glob` 加跳过，也别为了“一致性”让 `grep` 去读 `node_modules`。
- **凭证类文件必须跳过，并把名字报出来**（`skipped_sensitive`）。`grep` 返回的是**内容**，如果它顺手把 `.env` 的行打出来，`read_file` 对这些文件的确认形同虚设。判据直接复用 `permissions.is_sensitive_path`，不另立一套。
- 四个上限：`DEFAULT_HEAD_LIMIT = 250`（输出条数，0 才不限）、`MAX_COLUMNS = 500`（单行截断，防压缩产物刷屏）、`MAX_SCANNED_ENTRIES = 20000`、`MAX_FILE_BYTES = 8MB`；再加上 `MAX_DURATION_SECONDS = 20` 的墙钟预算。任何一种被触发都要在结果里如实标记（`truncated` / `scan_truncated` / `timed_out`），**不要**把部分结果伪装成完整结果。
- 计时预算**同时覆盖遍历与读取**（一个 deadline 传下去）：否则慢目录会把读取的时间吃光，症状看起来像"正则太慢"。
- **`.gitignore` 逐目录解析**（`agent/tools/grep/ignore.py`）：进入某目录时读它的 `.gitignore`，规则随继承链拼成“祖先在前”的元组，**最后一条匹配生效**（`!` 因此能撤销父目录的排除）。支持 `#` 注释、空行、`!`、`dir/`、`/anchored`、`*`/`**`/`?`/`[...]`/`{a,b}`；语义能这样省，是因为 `GlobPattern` 的“无 `/` 即匹配任意深度的文件名”正是 git 的规则，`anchored=` 参数专门用来表达 `/pattern`。
- **忽略规则只从搜索根往下读，不读祖先**。搜索根就是模型的全世界，指哪搜哪：`path="node_modules/react"` 因此仍然能搜（否则唯一的逃生口会被工作空间根的那条 `node_modules/` 关死）。同理，被忽略的目录不会被下降，所以同目录里的 `!` 想重新包含它下面的文件也无效——与 git 一致。
- **没有开关**。不给 `include_ignored` 之类的参数：`.gitignore` 是仓库自己对“什么算源码”的声明，模型想越过它就显式指 `path`。省一个开关，也省掉“两套行为都要测”。
- **性能约束**：忽略层是每个条目都要过的热路径。`Rule.name_only` 让绝大多数规则只比文件名、需要相对路径的按 base 缓存一次——在本仓库 900 个文件上，不做这一步是 1.2 秒，做了是 0.13 秒。新增规则语法时先看这条。

### web_fetch：读网页，而不是让模型跑 curl

- 有它之前，"读这个网址"只能靠 `exec_command`（`curl`）或 `code_interpreter`（`requests`）：没有域名确认、没有大小上限、没有 HTML→文本这一步，失败形态还随 shell 方言漂移。取舍见 [ADR 0027](decisions/0027-web-fetch-tool.md)。
- **工具内部不调模型**：参考实现有 `prompt` 参数并用小模型提炼答案，本仓库没有——tool 层拿不到 provider，硬接会绕开速率限制与用量记账，而主模型本来就在 loop 里、下一步就要读这段正文。所以参数只有 `url`，别为了"对齐参考实现"把 `prompt` 加回来。
- **权限目标是主机名（`permissions.NETWORK_READ_TOOLS`）**：`read` 类工具的默认目标是 `file_path` / `path`，网络读取没有这个字段；`_target` 走 `web_urls.host_of(url)`，因此规则键是 `example.com`，同域名第二个页面不再弹框，子域各自弹框。URL 不合法返回 `None` 不弹框（工具自己报错）。改这段时同时看 `_build_request` 的 `network_fetch` 分支，确认框的文案与 `details.url` 在那里。
- **重定向自己走**（`allow_redirects=False`）：同域（主机名相等，端口/协议可不同）最多 5 跳；跨域不跟随，返回 `redirect_to` 让模型另抓一次——新站点没被批准过，跳过去等于绕过域名确认。
- **后端可配置**（`WEB_FETCH_PROVIDER`）：`builtin` 是原来的本地抓取；`deepseek` 走 DeepSeek 的 Fetch API（`deepseek.py` + `providers.py`），由对方服务器抓取并返回 Markdown。服务端后端看不到跨域跳转，也拿不到 PDF/图片的原始字节——不要试图在适配器里补回 D3/D6，指南里已把这条差异写明。
- **URL 规则只有一份**（`agent/tools/web_urls.py`）：工具拒绝什么、权限门问什么必须同一个答案，否则要么重复弹框，要么把 A 站的批准套到 B 站。工具包之间不许互相 import，所以它落在包根。
- **不完整要说明**：2 MiB 正文上限（`response_truncated`）、超预算落盘（`content_truncated` + `persisted_path`）、空正文给固定文案、HTTP ≥ 400 报 `http_error` 而不是把错误页当正文。任何一项都不要改成静默截断。
- **HTML 转换只用标准库**（`web_fetch/html_text.py`）：标题/列表/链接/代码块/表格行保留，`script`/`style`/`hidden`/表单控件丢弃，`nav`/`footer`/`role=navigation` 这类站点框架也丢——参考实现靠小模型过滤这部分噪音，这里没有那一步。解析异常回退到"正则去标签"，抓取已经成功就不该在转换上失败。
- 新增分类 `network`：`spec.CATEGORY_NETWORK`、`toolMeta.js` 的 `CATEGORY_ORDER` / 标签键、六份 `locales/*.json` 要一起改（`test/tool_api_test.py` 会校验分类在 `CATEGORY_KINDS` 里）。

### web_browser：同一件事，简单视图

- `web_browser`（`agent/tools/web_browser/`）不是 `web_fetch` 的替代品，是**另一种结果形状**：`title` + 最终 `url` + 纯文本 `content`，没有回执字段。分工写进两份 `description`。取舍见 [ADR 0029](decisions/0029-web-browser-tool.md)。
- **权限键按工具分开**：`permissions.NETWORK_READ_TOOLS` 里有它，目标同样是主机名，但规则键是 `(web_browser, example.com)`，不会继承 `web_fetch` 的批准（反之亦然）。确认框文案 "Browse \<主机\>" 在 `_build_request` 的 `network_browse` 分支。**不要**为了少点一次框合并两边的规则键。
- **纯文本不是第二份 Markdown**（`web_browser/snapshot.py`）：块间空行、列表 `- ` + 缩进、`<pre>` 保留缩进；链接地址、代码围栏、表格竖线都丢——那是 `web_fetch` 的职责。丢掉的噪声集合（`script`/`style`/`hidden`/`nav`/`footer`/`role=navigation`）与 `web_fetch` 同源，别再分叉一套。
- **两层上限**：50,000 字符截断并标 `[truncated]`（参考实现的上限），再叠输出 token 预算落盘（`browse-*.txt`）。任何一层都不要改成静默截断。
- **`action=screenshot` 不假装**：它返回同一份文本快照 + 一句"没有截取画面"。不要把它接到 `computer_observe`——那是桌面截图，不是网页渲染。
- **失败也带 `title`**（`HTTP 404` / `Error`），同时保留 `error` / `reason`：前者是浏览器语义，后者是 loop 与 UI 的约定。
- 传输层（`web_browser/fetch.py`）与 `web_fetch/fetch.py` 是同域跳转规则的两次实现：工具包之间不许互相 import，先例是 `web_search/http.py`。改重定向规则时**两处都要改**。

### vault_http：密钥只按名字引用

- `web_fetch` 明确不能认证，"调一个需要 token 的接口"就只能靠 `exec_command`（`curl -H`）或 `code_interpreter`——密钥因此进入工具参数、`messages`、任务事件与会话记录。`vault_http`（`agent/tools/vault_http/`）把这条路改成"只给钥匙名"。取舍见 [ADR 0030](decisions/0030-vault-http-tool.md)。
- **保险柜是文件**（`agent/tools/vault_store.py`，`data/vault.json` / `VAULT_SECRETS_PATH`）：每次查询重读、不缓存（轮换与新增下一步生效）；报错只列键名，绝不列值。工具包之间不许互相 import，所以它落在包根。
- **权限种类 `vault`，目标是 `key@host[:port]`**（`permissions.vault_target` + `web_urls.https_authority_of`）。两处必须给同一个答案，否则弹框问的和规则记的对不上。明文 `http` 不产生目标 → 不弹框，让工具自己报 `https_required`。
- **`always_confirm` 是 `auto_approve` 的例外**：`ToolSpec.always_confirm` → `ToolRegistry` 的 `always_ask` → `PermissionBroker.check`。`deny_all` 仍直接拒，`always` 规则仍命中即放行。**不要**为了"少弹一次"把它去掉：那是这个工具唯一阻止密钥随便外发的地方。
- **擦除在先、报错在后**：`scrub.variants_of(secret)`（原值 / URL 编码 / base64（含去 padding）/ JSON 转义 / `user:password` 两半）用于正文、响应头与异常文本。新增任何输出字段前先想一遍它会不会带上密钥，然后跑 `vault_http_test.py` 的 `test_the_secret_never_comes_back_in_the_result`。
- **不跟随重定向**（`allow_redirects=False`）是 D4 的全部实现，别为了"顺手"打开。传输层可注入（`transport=`），测试因此不需要网络与 TLS。
- `data/vault.json` 在 `permissions._SENSITIVE_NAMES` 里：`read_file` 读它要先问用户，否则擦除会被"手工读一遍"绕过。

### web_search：先找页面，再去读

- `web_search`（`agent/tools/web_search/`）回答"哪些页面在讲这件事"。`web_fetch` 只能读**已知 URL**，`exec_command`/`code_interpreter` 能搜但结果形态随方言漂移、失败只知道"命令退出了"。取舍见 [ADR 0028](decisions/0028-web-search-tool.md)。
- **后端是配置，不是参数**（`WEB_SEARCH_PROVIDER`）：模型没有"换一个引擎重试"的能力，给它这个参数只会浪费一步。默认后端无需密钥（DuckDuckGo HTML 端点，`duckduckgo.py`），所以拿到仓库就能用；DeepSeek / Tavily / Serper / Bing 在 `search_apis.py`，共享一个 `SearchHit` 形状（`hits.py`）。
- **只给标题/网址/摘要，不抓正文**：参考实现有 `livecrawl`，这里没有。抓正文要重做整条 `web_fetch` 链路（2 MiB 上限、HTML→文本、跨域跳转规则），两份规则一定会漂移。需要正文就 `web_fetch`。
- **权限目标是工具自身**（`permissions.SEARCH_PERMISSION_TARGET = "web_search"`）：搜索没有 `url` 可用，而按 query 建规则会让用户为每个新问题再点一次。`_target` 的 `NETWORK_READ_TOOLS` 分支先取 `host_of(url)`（`web_fetch` 走这条），没有 URL 时再落到工具名；不能解析出目标就不问，让工具自己报 `invalid_query`。确认框文案与 `details.query` 在 `_build_request` 的 `network_search` 分支。
- **默认后端是抓页面，必须把"坏了"说清楚**：DDG 改版或被机器人校验时解析不出结果，`provider_blocked` 会带一句"配置 API 后端"的提示；**不要**把它退化成"没有结果"，那会让模型以为话题不存在而反复改词重试。
- **域名过滤统一在 `providers.run`**：只有 Tavily 支持原生域名过滤，其余后端不支持，行为不能取决于后端。子域匹配（`docs.example.com` 命中 `example.com`）、去重、`num_results` 截断都在这一处；**被 `num_results` 截掉的条数不算 `filtered_out`**——那是上限不是过滤，混在一起会让"你的过滤器吃掉了结果"这条提示骗人。
- **三重不完整都要报**：`filtered_out`（域名过滤）、`context_truncated` / `dropped_results`（超 `context_max_characters`，按整条丢）、`content_truncated` + `persisted_path`（超输出 token 预算，落盘到本次运行的临时目录）。`search_type_applied` 说明后端是否真的支持 `fast`/`deep`。
- 分类沿用 `network`（`spec.CATEGORY_NETWORK`），**前端无需改动**；顺序放在 `grep` 与 `web_fetch` 之间（找到页面 → 再读页面）；`ask` 模式加入允许列表，`plan` 仍然没有工具。

### read_file 永远带行号

- `read_file` 的返回内容一律带 `N<TAB>` 行号前缀（`agent/tools/read_file/lines.py` 的 `LINE_NUMBER_SEPARATOR` / `_format_lines`），**不提供 `include_line_numbers` 之类的开关**。
- 分隔符用制表符而不是 `| `：同样能对齐，但每行只占 1 个字符，比 `| ` 少一个字符。
- 原因：模型看不到文件的真实行号，也不具备可靠的行号推算能力。返回不带行号的正文，会让后续所有“把第 N 行改掉”“第 N 行有问题”的引用变成猜测，而猜错的行号会直接传导到写操作上。
- 代价：读 2000 行大约多花 4000 个 token。这个开销是明知的，且远小于一次错行号的返工成本。
- 因此：不要为了省 token 给这个行为加开关，也不要让 `_format_lines` 支持“无前缀”模式。
- 相关说明页：`docs/tools/read_file/eli5-line-numbers.html`

### 相对路径的基目录（有工作空间 vs 无工作空间）

- 有工作空间：相对路径以会话绑定的工作空间根为基准，且**不得逃出**该目录。
- 无工作空间（未绑定会话）：相对路径以**会话默认目录** `<程序启动路径>/data/default_workspace` 为基准（`DEFAULT_WORKSPACE_DIR` 可覆盖）。它是**基目录不是边界**——`..` 仍可离开，全局策略照旧生效。
- 解析是四个文件工具（`read_file` / `edit_file` / `write_file` / `delete_file`）**共用**的一条路径（`file_access._resolve_path`），所以四者的相对路径语义**必须一致**。不要只给某一个工具加特例：那会造成"写得进去、读不回来"。
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

### delete_file 的删除前置（与写入同源，有一处例外）

- 删除**复用 `write_file` 的读前置**：本 run 内完整读过（第 1 行、不带 `limit`）且指纹未变，否则报 `read_required` / `file_changed`。"没见过的文件不会被摧毁"对删除同样成立，工具集里最不可逆的操作不该是唯一没有保护的那个。
- **例外**：超过 `MAX_FULL_READ_BYTES` 的文件根本不掉，因为 `read_file` 读不全。硬拒会把模型推回 `exec_command` / `code_interpreter`（两者绕过工作空间天花板、全局策略、只读根与权限目标），所以这类文件照删，结果里标 `content_verified: false`。空文件同理不需要读。
- 删除后**必须 `ledger.forget(path)`**：指纹描述的文件已经不存在，留着会让同一路径上新建的文件无需读取即可被删。
- 路径解析用 `resolve_write_path`（删除是修改），`create_default` 不传；只删常规文件，目录报 `not_a_file` 并指向 `code_interpreter`。
- 进入改动快照：`CheckpointStore.FILE_TOOLS` 里有 `delete_file → file_path`，`git add -A -- <path>` 会把删除也暂存，撤销时恢复该文件。别把它挪进 `TREE_TOOLS`（那样每次删除都整树扫描）。
- 权限种类是 `write`（参数名必须是 `file_path`，否则确认框拿不到目标），但 **scope 只有 `once` / `session`**：一条持久化的 always 规则会活过它当初批准的那个文件，将来同路径的新文件会被静默删除。
- 相关取舍见 [ADR 0026](decisions/0026-delete-file-tool.md)。

### exec_command：命令执行，以及它的 containment 到底管什么

- `exec_command` 只约束**资源与进程生命周期**：Windows 用 Job Object（进程数上限 + job 内存上限 + 整树终止），POSIX 用新会话 + `killpg`。POSIX **没有**内存上限（`preexec_fn` 在线程模型里不安全），文档里不要写成有。
- 这**不是安全边界**：命令能读写进程用户碰得到的任何路径，工作空间约束对它无效。`containment.note` 就是为此存在的，不要删。
- 低完整性（L2）**未启用**：机制已验证可用（令牌降到 Low、写入被拒），但单独开启会让普通命令连临时目录都写不了；启用前需要给工作空间加 ACL 授权与撤销路径。见 [ADR 0005](decisions/0005-exec-tool.md)。
- Windows 上**不要**把 `bash` 加进候选：本机 `bash.exe` 是 WSL 启动器，命令会跑在另一个文件系统里。
- 工具描述按平台生成，结果里必须报告**实际 shell 与版本**——模型要知道自己在写哪种方言（`$env:FOO` 还是 `$FOO`）。
- 凭据类环境变量默认不下发（纵深防御，不是边界）；`EXEC_PASS_SECRET_ENV=1` 可关闭。
- `interrupted` **只表示超时**。`stop` 是协作式的，杀不掉正在执行的命令，所以它不代表"用户停止"。
- 说明页：`docs/tools/exec/eli5-not-a-sandbox.html`。

### exec_command 的 tty（伪终端）

- `tty=true` 把命令挂到伪终端：Windows 走 `pywinpty`（ConPTY），POSIX 走标准库 `pty`（`agent/tools/pty_session.py`）。**不要**静默退回管道：拿不到终端就报 `tty_unavailable`，否则模型会一直以为程序看到了 TTY。
- POSIX **不设控制终端**：唯一入口是 `preexec_fn`，而本项目拒绝在线程模型里用它（见上文）。副作用是 Ctrl-C 的投递方式：`\u0003` 一律走带外 `killpg`，**不要**照抄参考实现"tty 就原样写 `\u0003`"——没有控制终端时它在 POSIX 上不产生 SIGINT。
- **读必须在线程里**：终端的 `read` 两个平台都没有超时，而且子进程退出后**不会**结束（除非对端被关闭）。`PtyReader` 负责读，`RunningCommand.release()` 的顺序固定为 `settle()`（排干尾巴）→ `terminal.close()`（这才是结束阻塞读的手段）→ `join()`。少任何一步就是丢日志尾部或泄漏线程。
- 管道命令仍然没有 reader 线程，只有 tty 会话有泵线程（对 [ADR 0008](decisions/0008-write-stdin-tool.md) D3 的定向修订）。
- 输入收口在 `RunningCommand.has_stdin()` / `write_input()`：tty 命令没有 `process.stdin`，`write_stdin` 不要直接摸流。
- Windows 的输入归一化（`pty_session.normalize_windows_input`）：`\n` 转 `\r`。实测 `\n` 在 ConPTY 下不是回车，程序收不到那一行。
- 模型看到的文本把 `\r\n` 归一成 `\n`；**落盘的文件保留原始字节**（`exec_command/runtime._render_foreground_text`）——文件声称是命令的输出，就该是命令的字节。
- L1 不变：tty 命令照样按 pid 挂 Job Object（拿不到 job 就退化成 `KIND_PLAIN`，与管道路径一致），`containment` 报告一字未改。
- 已知限制：不剥离 ANSI（ConPTY 起步的握手转义与 pwsh 的标题序列会出现在输出里）、尺寸固定 24×80、无 resize、Windows 上终端输出由 `pywinpty` 按 UTF-8 解码（不过本仓库的编码探测）。取舍与实测记录见 [ADR 0009](decisions/0009-exec-tty.md)。

### write_stdin：把还活着的命令当成一台没挂的电话

- `exec_command` 的 `run_in_background` 现在返回 `session_id`，且 stdin 是**管道**（不再是 `DEVNULL`）；输出仍然写日志文件。`tty=true` 的会话是**伪终端**：输入走终端、输出由泵线程写进同一个日志文件（见上一节）。
- `write_stdin` 只做三件事：按 `session_id` 找进程 → 可选写入 `chars` → 等 `yield_time_ms` 收新输出。空 `chars` 是轮询，`chars` 为 `\u0003` 是打断。
- 输出按**日志文件增量**返回（`process_store` 记已读偏移），不要另建内存缓冲：日志就是这一路输出的唯一通道。
- 命令退出即 `retire` 会话并释放句柄与管道；"已结束还能继续打字"不要放行。
- `yield_time_ms`：轮询 5000–300000，写入 ≤30000，默认 250；`max_output_tokens` 默认 10000，还会被本次运行的输出预算再压一次。
- 门禁目标是 `session:{session_id}`，且**不提供 always**（目标是随机会话 id，持久化规则永远匹配不上）：`ToolSpec.scopes` 收窄可选答案，前端只渲染可用按钮，API 收到越界 scope 返回 400。见 [ADR 0008](decisions/0008-write-stdin-tool.md)。
- **归属是能力校验**：`Session` 记 `task_id + workspace`，`write_stdin` 只认本任务本工作区的会话，其余一律按未知会话回答。
- **会话是任务级的**：`run_react_loop` 的收尾包装器在任务结束时 `stop_task`，另有 `atexit` 硬停兜底；每任务上限 8（先 sweep 僵尸再计数，超限**拒绝**新启而不是杀旧会话），TTL 30 分钟。
- `chars` 为 `\u0003`（Ctrl-C）时走 `process_group.interrupt`：POSIX 发 SIGINT，3 秒没退再 SIGKILL；Windows 由 Job 终止。
- 输出超预算**落盘并返回 `persistedOutputPath`**，而不是只截断，与 ADR 0005 D4/D8 一致。
- 已知限制：**管道会话**里需要终端的程序不会真的交互（`top`、密码提示、行编辑）；要终端就显式用 `tty=true`，不要把管道行为说成 TTY。原理与取舍见 [ADR 0008](decisions/0008-write-stdin-tool.md) 与 [ADR 0009](decisions/0009-exec-tty.md)。

### 大输出与只读附加根

- 命令输出超过 token 预算就落盘到系统临时目录，模型拿到预览 + 路径，用 `read_file` 分段读回。
- 该目录通过 `extra_read_roots` **可读不可写**（写报 `read_only_root`）。这是 [ADR 0001](decisions/0001-file-edit-tool.md) D3 的显式例外，不要把它当成漏洞"修掉"。
- 全局策略依然作用于它：`allow_dirs` 非空时输出目录会不可达，这是有意的。
- 进入事件 `details` 的 stdout/stderr 截到 64 KiB（命令输出无上限），完整文本只在磁盘上。

### Provider 与模型（两张表，一个端点一份配额）

- **provider** 存协议、`base_url`、`api_key` 与 `rpm_limit`；**model** 只存模型名与能力开关，加一个 `provider_id`（[ADR 0014](decisions/0014-provider-model-split.md)）。表结构在 `dao/llm.py`，它复用 `dao.store` 的连接与锁。
- 一个（协议, 规范化地址）只能有一条 provider 记录：桶键由这两项组成，两条记录会互相覆盖，看不出哪条生效。同一个协议配两个地址是合法的——那是两个端点、两份配额。
- 删 provider 前必须先删/迁走它的模型（409，不级联）。
- `PUT /api/models/{id}` 只改模型自己；换 provider 就是换端点，等价于换配额。

### 本地 Ollama 的上下文长度（模型记录里的 token 上限只是"声明"）

- Ollama 默认 `n_ctx = 4096`，超出即回 400 `exceed_context_size_error`（`request (N tokens) exceeds the available context size (4096 tokens)`）。模型记录里的 `max_input_tokens` 只决定 agent 侧的压缩阈值（`max_input_tokens × 4` 字符），**不会**改变服务端窗口；两者不一致时第 1 步就可能撞上 400——系统提示 + 工具 schema 本身已有数千 token，压缩无从下手。
- OpenAI 兼容接口（`/v1/chat/completions`）**没有**设置上下文长度的字段（官方文档明确说明 `num_ctx` 不是请求参数），只能改服务端默认值或把参数烘进模型：
  - Windows：把用户环境变量 `OLLAMA_CONTEXT_LENGTH` 设为"输入上限 + 输出上限"（本项目模型记录是 32768 + 8192 = `40960`），然后**重启 Ollama 应用**。只写注册表不够：已经在跑的进程继承的是旧环境，托盘退出再打开（或在新 shell 里 `$env:OLLAMA_CONTEXT_LENGTH='40960'` 后启动 `ollama app.exe`）才生效。
  - 按模型单独设置：Modelfile 写 `FROM granite4.2:3b` + `PARAMETER num_ctx 40960`，`ollama create granite4.2:3b-40k`，模型记录改用新名字。
- 窗口调大会按并行数放大 KV cache 内存（`OLLAMA_NUM_PARALLEL × 上下文长度`），给大模型开窗口时要一起算。

### 模型请求频率（RPM）

- 桶按 **provider + base_url** 分（`agent/rate_limit.py` 的 `bucket_key()`），进程级单例：provider 实例每个任务重建，挂在实例上的计数器等于每任务清零（[ADR 0013](decisions/0013-llm-rpm-limit.md)、[ADR 0014](decisions/0014-provider-model-split.md)）。
- 键要经 `agent.provider.normalize_base_url()` 规范化：适配器会给 OpenAI 兼容地址补 `/v1`，两端不一致的话限流会静默失效（`test/rate_limit_test.py` 有对应用例）。
- 滑动窗口而不是固定窗口：第 N+1 个请求等"最老的那个请求满 60 秒"，因此任意 60 秒跨度内都不超限，也没有窗口边界突刺。
- **钩子在 wire 层**（每个适配器的 `chat_completion` 与 `stream_chat_completion` 第一行 `self._throttle()`），不在循环里：任务命名线程也打同一个端点，能绕过的限流不是限流。新增 provider 适配器时必须记得加这一行。
- 等待有上限（60 秒），超过就抛 `RpmLimitError`。循环会把它转成 `LLMCallError` 并给出"调高限制或稍后重试"的文案；**不要**改成无限等待，那会让"配错成 1 RPM"表现为任务假死。
- 等待时长经 `provider_throttle.take_last_wait()` 回读（线程局部，取一次即清零），落成 `debug` 事件（含 `base_url`）+ span 属性 `llm.rpm.wait_ms`：模型慢和自己在配额里打转是两件事，排障时要分得开。
- 配置只有数据库一层：`rpm_limit` 是 provider 字段，启动时与每次 provider 写入后由 `llm_api.sync_provider_throttle()` 重建限流表。**没有** `LLM_RPM` 环境变量，也没有 `settings.llm_rpm_limits`（0013 的旧方案，见 0014 D6）。

### 工具结果预算（一步的结果太多）

- 触发点在循环里：一步的工具全部返回之后，只处理本步新追加的 `role="tool"` 消息（`loop.py` 的 `batch_start`）。工具内部的 per-result 预算管不到"一次读 30 个文件"，这一层管。见 [ADR 0012](decisions/0012-tool-result-budget.md)。
- 两遍扫描：先动 `> 30,000` 字符的单条；若总量仍超 `200,000`，再按大小兜底，不设下限。少了第二遍，`30 × 20k` 的批次会一条都不处理。
- 落盘在**工作空间内** `<workspace>/.ngy-agent/.task_outputs/tool-results/`，是 temp 输出树的显式例外（历史里的绝对路径要一直有效）；它同时是只读根，模型能读回、不能改写。
- 落盘失败**保留原文**并报 `error` 事件：静默丢内容比超预算危险，超预算看得见，丢内容看不见。
- 占位文本必须**比原文短**才替换，且每个下标只访问一次——否则 2,000 字符左右的小结果会被"落盘"成更长的路径，第二遍还会把全文覆盖成占位文本。
- 占位文本不是装饰：它要给**路径、行数、`offset/limit` 提示**。`read_file` 整读上限 256 KB，单次又受 token 预算约束，只给路径等于让模型先撞一次错；`read_file` 还永远加 `N<TAB>` 行号，不说清就会被当成文件内容（见 ADR 0012「回读契约」）。
- 含 NUL 的结果在落盘前把 `\x00` 换成 `\ufffd`：`read_file` 见 NUL 判二进制拒绝，留着 NUL 就是留一个打不开的路径。

### 对话窗口裁剪（snip_compact）

- 触发点在**每步循环顶部**、`batch_start` 之前（`loop.py`）：上一个工具组已完整，下标语义不会被压缩打乱。放在工具循环之后会和 `result_budget` 的"只处理最新一批"打架。
- 原地 `messages[:] = [...]`，不返回新列表：`loop.py` 里 `messages = initial_messages` 是别名，REPL 跨轮持有同一个列表，rebind 会让它停在压缩前。
- 切点**绝不落在一次工具调用内部**，两侧都是 `while` 而不是"动一步"——一次回复可能带 N 条 tool 消息。head 扩展从尾部扣，tail 回退会让窗口略微超限（上限不是等号，见 ADR 0015 D3）。
- transcript 是 JSONL 而不是一个大 JSON：`read_file` 按行切片，单行 JSON 读不回来。截图写入前 redact，对话本身不动。
- 写盘失败**不压缩**：删了消息却写不出档案，是这一步唯一不能接受的降级。
- 归档不足 `MIN_ARCHIVED_MESSAGES = 5` 条就等下一步（小窗口下阈值退化为 `min(5, limit // 10)`）：一份全量快照换 2 条消息不划算，窗口允许在 50→55 之间徘徊。
- 压缩后跑一次 O(n) 配对自检（`_find_orphans`），发现孤儿只发 `error` 事件、不阻断——否则症状会漂到**下一次请求的 400** 上，而那和压缩看不出关系。
- 不移除任何 provider 适配：这一层在消息层，不碰 Anthropic 的 `tool_result` block。

### 上下文微型压缩（micro_compact）

- 前三步是固定管线，性质不同：`result_budget`（步末、字节）与 `snip_compact`（步首、条数）**每步必跑且无损**；`micro_compact`（步首、总量）**只在估算超限时**跑。顺序不能换：`snip_compact` 先重排列表，`seen` 才按 id 而不是下标判定（见 [ADR 0016](decisions/0016-micro-compact.md)）。
- 估算一次结构化遍历（`estimate_chars`），不要退回 `len(json.dumps(messages))`：那会把截图按 base64 实长计入，带图的会话因此永久超限，任何压缩都修不好。图片按 `IMAGE_CHAR_COST = 1,600` 名义计价，替换时用运行总量增减，不做全表重算。
- 阈值解析顺序：显式参数 → `CONTEXT_CHAR_LIMIT` → `max_input_tokens × 4` → `200,000`。模型窗口是模型属性，不该让用户在模型记录和压缩配置里各写一遍。目标线是阈值的 80%，压到线上等于下一步再压一次。
- 能缩短的只有**已读**结果，且保留最近 `KEEP_RECENT_RESULTS = 3` 条：当前的活儿建立在这几条上，换成路径等于让模型为自己正看着的内容再付一次工具调用。`seen` 是 `run_react_loop` 内的局部集合，`mark_seen` 在**请求发出前**记录——所以刚返回的结果在下一步仍算未读。
- 占位分两种形状：已读结果用单行 `[Earlier tool result saved at <路径>]`（模型知道它是什么，只需知道去哪儿找）；未读结果用 `<persisted-output>` + 1,000 字符预览（模型没读过，只给路径等于让它盲读）。措辞都来自 `output_store.persisted_note`，与第一步同一套。
- 文件名由 `tool_call_id` 决定（ADR 0012），所以"是否已落盘"只需按 id 算路径 + `exists()`：第一步落过的结果直接复用，不产生第二份副本，模型也不必在两个路径里挑。
- 单条写盘失败：保留原文、记入 `failed`、继续下一条，最后发一条 `error`。宁可超限（看得见），不可丢内容（看不见）。
- 两步之后仍超限（`still_over`）**只记事件**，不进入需要模型调用的摘要压缩：那会是另一步的设计，不是这一步的隐藏分支。

### 历史摘要压缩（compact_history）

- 前三步都是确定性文本手术；这一步是**唯一会调用模型**的压缩步骤，所以放在最后，进入条件只有一个：`prepare_context` 返回 `still_over`（见 [ADR 0017](decisions/0017-compact-history.md)）。
- 它处理的是前三步结构上碰不到的东西：一长串 assistant/用户消息、注入的历史、没有工具结果的对话。这些内容没有"已读/未读"可区分，也没有可裁剪的边界。
- 顺序固定为 **写 transcript → 请求摘要 → 替换消息**。写不出就不调模型；模型异常或**摘要为空**就不替换，历史原样保留并发 `error`（`action: "kept the full history"`）。归档先行意味着失败时证据也已落盘。
- 摘要输入有独立预算：单条 4,000 字符、总量 `min(60,000, 阈值/2)`、头 1/4 尾 3/4，中间省略。**只送将被删掉的那段**，尾部不送：它要原样留在对话里，送进去等于两份内容 + 双份预算。
- 替换形状是 `system + 一条 [Compacted]（role=user）+ 最近 5 条`；切点落在 `tool` 上要**循环**回退到 `assistant(tool_calls)`，孤儿工具结果会被 provider 拒绝。并行工具多时尾部会超过 5 条——上限不是等号。
- 标记里**总是**写 `Current user request`（来自 `run_react_loop(user_query=...)`）：长工具循环里那条 user 消息可能已经落在被删区间。摘要标 `reference only`，transcript 才是权威；末尾给 `read_file (offset/limit)` 的回读提示。
- **投影守卫**：调用前先算"删掉旧历史 + 摘要 + 标记"之后的大小，若仍高于阈值 80% 就直接跳过并记 `debug`。没有这道判断，一个尾部自己就超限的会话会每步花一次模型调用。不做"每 K 步一次"的时间窗——那需要跨步状态，重启即失效。
- 输出上限按 wire 格式选 kwarg：OpenAI/Anthropic 用 `max_tokens`，**Gemini 用 `max_output_tokens`**（它会把未知 kwarg 直接塞进 payload，传错就是 400）。
- 可观测：span `compact.summary`（`llm_span(name=...)`）+ 一对 `llm_request`/`llm_response` 事件（`purpose: "compaction_summary"`，只带字符数，不带原始 payload）+ 一条 `debug` 汇总。
- transcript 写入器与 `snip_compact` 共用 `agent/agent_loop/transcript.py`（JSONL、图片 redact、每次一个新文件）——两套实现迟早会在行格式或目录上分叉。

### 工具结果分流（模型 vs UI）

- 工具若需要把结构化记录交给 UI/外部消费者，**不要**把它塞进返回给模型的字符串：返回 `ToolOutcome`（`model_text` + 事件类别/标题 + `details`），由 `agent_loop` 拆分。
- 首个用例是 `edit_file`：模型只收到一行成功摘要，`original_file` / `structured_patch` / `gitDiff` 走独立的 `file_edit` 事件。
- `write_file` 同理，走**独立**的 `file_write` 事件（不复用 `file_edit`：整体替换与局部替换对 UI 是两件事）。新增事件类别时别忘了前端 i18n 与 `.tag.<category>` 样式。

### 权限确认（P1）

详见 [ADR 0006](decisions/0006-tool-permission-confirmation.md)。改动这条链路时最容易踩的三个点：

- **门禁写在 `ToolRegistry.execute_tool` 这个唯一收口上**，不要写进各个工具内部（工具拿不到 `EventSink`，而且按工具加门禁的默认结局是漏掉某个工具）。新增工具时必须在**该工具包内 `spec.py`** 的 `ToolSpec.permission` 里声明种类，默认 `none`＝永不询问；工具清单与顺序由 `agent/tools/catalog.py` 统一决定。
- **分类与翻译也写在工具包里**：`ToolSpec.category` 决定管理页的分组，`description_i18n` 只给管理页展示。文案放本包 `i18n.py`，五套语言常量（`ZH_CN` / `ZH_TW` / `FR` / `DE` / `RU`）由 `agent/tools/spec.py` 的 `localized_texts(...)` 装配；它要求五个都传，漏一个在 import 期就报错，不会等到法文页面上才发现某工具回退成英文。它们**不能**写进 `parameters`/`description`：那两处会原样发给 provider，每次请求都付费。`test/tool_api_test.py` 会校验每个工具的每个语种都覆盖全部参数，所以改 schema 时要同步改 `i18n.py`。
- **新增界面语言是两处一起改**：`web-admin/src/i18n.js` 的 `LOCALES` 与 `agent/tools/spec.py` 的 `LOCALES`（后者决定工具的 `description_i18n` 键），另外要给 12 个工具包各补一套 `ToolText`，两处清单不一致时工具页会静默回退英文。
- **`TaskStatus.WAITING` 仍属"进行中"**：`/events/stream`、WebSocket 循环与前端 `isTaskRunningStatus` 都必须把它当作在飞行中。否则事件流会在用户最需要看到确认请求的那一刻断掉（这个坑已踩过一次）。
- **scope 不做降级**：未知取值返回 400。把 `always` 静默降级成 `once` 会让用户以为已经长期允许了。

### 工具黑名单（denylist）

详见 [ADR 0024](decisions/0024-tool-denylist.md)。改动这条链路时最容易踩的几个点：

- **位置在权限门之前**：`ToolRegistry.execute_tool` 先问 `self.denylist`，命中就返回 `ToolOutcome`（`permission_decision` 事件，`details.reason = "denylist"`），工具函数不执行，确认框也不弹。理由与 `file_access` 硬拒绝一致：答案已经是"不"，问一次只会让模型以为再试试有用。
- **规则 = 工具匹配 + 0..N 个参数匹配，全部命中才拒绝**。工具名与参数都支持 `fixed`（整值相等）与 `regex`（`re.search`）。非字符串参数按其 JSON 形态匹配（`json.dumps(..., sort_keys=True)`），所以 `{"timeout": 30}`、`{"urls": ["a"]}` 都按调用里的样子比较；dict 值必须写成 `{"match": "fixed", "value": {...}}`，因为对象位置留给匹配器。
- 规则文件默认 `data/tool_denylist.json`（`TOOL_DENYLIST_CONFIG` 改路径）。`args` 缺省表示整个工具禁用；参数名可写 `a.b` 取嵌套字段，`a.0` 取列表元素。
- **读盘走 stat 缓存**：改完文件下一次调用即生效，不必重启。文件缺失或不可解析 = 没有规则（只会"不拦截"，不会放宽任何访问）。
- **写错的规则整条丢弃**，原因记在 `ToolDenyList.problems`：半解析的规则会匹配到写规则的人没看到的调用，所以绝不保留，也就绝不部分生效。
- **求值异常一律拒绝**（fail closed），和权限门同一原则；`details.reason = "denylist_error"` 与配置写错（`problems`）是两回事。
- 新增事件字段时别忘了前端：拒绝复用 `permission_decision` 类别，因此 `details` 里的 `rule` / `matched_fields` 会直接显示在事件详情里。
- **页面写同一份文件**：`GET/POST/DELETE /api/admin/denylist` 由 `commons.state.denylist_store` 落到 `ToolDenyList.add/remove`（整文件原子重写、按 `id` 替换）。POST 的扁平请求先组装成文件里的 JSON 形状，再交给**同一个 `parse_rules`** 校验，坏正则直接 400——页面因此写不进一条会被任务静默丢掉的规则。GET 同时返回 `path` 与 `problems`，前端把两者都显示出来。

### ask_user_question：把决策交回用户（它不是权限）

- 与权限确认**正交**（P 轴问"能不能做"，Q 轴问"该做什么"）：独立 broker（`agent/tools/user_question.py`）、独立事件类别（`user_question` / `user_answer`）。**不要**把它塞进 `PermissionBroker`：那条通路只能回传布尔，而提问的答案是数据。
- **工具拿不到 broker**（本仓库的不变量）：通道以 `ToolBindings.ask_user` 注入，`ToolRegistry.ask_user` 在**每次调用**时读本任务的 broker —— 与 `permission_broker` 的晚绑定同一个手法（registry 建得比任务身份早）。
- **一直等到有人回答，没有超时**：定时器会在用户还在思考时替他回答"随便"，所以等待只由两件事结束——答复到达，或任务被停止（0.25 秒轮询 `should_stop`）。没有客户端时根本进不到等待：registry 直接返回 `no_client`，不阻塞。
- **空答案不等于拒绝**：任务被停止、没有客户端，两者都返回空答案 + "自行决定并说明假设"。权限那边 fail closed 是对的（沉默不能当允许），这边正好相反（沉默不能当禁止）。
- **数字是描述、结构才强制**（`agent/tools/ask_user_question/questions.py`）：1–3 题 / 2–3 选项 / `header` ≤ 12 字符只写在工具描述与 schema 描述里（**不要**加 `maxItems`/`maxLength`）；机器只拒绝"渲染不出来"的输入——空问题数组、缺 `id` 或 `question`、**重复 `id`**（答复是以 id 为键的字典，重复会静默错位）、没有选项、选项没有 `label`。前端按原样渲染并滚动：只截断**展示**，不截断数据。
- 答案契约 `{"answers": {"<id>": {"answers": [...]}}}`：**不加** `user_note:` 前缀（参考实现的客户端私有编码混进模型可见契约，用户真选了同名选项就会读错）；自由文本是数组里的独立元素，`details` 另给结构化副本。
- 前端对话框是纯表单（`web-admin/src/components/QuestionPrompt.jsx`）：每题单选 + 一个自由输入行；"其他"行由**客户端**加（模型被要求不要自己加）；**跳过 = 空答案集**，且对话框不可静默关闭（静默关闭会让任务永远停在等待里）。
- 新增事件类别照例要补前端各语言的 i18n（`src/locales/*.json` 与 `src/events/dictionary/*.js`）与 `.tag.<category>` 样式（`npm run build` 里的 i18n 校验会拦），以及 `test/tools/catalog_test.py` 的 `EXPECTED_ORDER`。
- 已知限制：CLI 与库调用只能拿到 `no_client`（在 REPL 里真去问用户是后续子项目）；单选，不支持一题多选。取舍与实测见 [ADR 0010](decisions/0010-ask-user-question.md)。

### subagent：委派一段独立上下文

- 工具包 `agent/tools/subagent/` 只管契约（brief → 最终报告）；**嵌套循环在 `agent/agent_loop/subagent.py`**，因为它需要 provider 与 event sink，而工具两者都拿不到（与 `ask_user` 同一条理由）。runner 以 `ToolBindings.run_subagent` 注入，`run_react_loop` 在 registry 建好后按需装入（`registry.subagent_runner`），晚绑定手法与 broker 一致。
- **隔离的只有消息**：同一进程、`base_dir`、权限门、黑名单、检查点（父 `task_id`）、`should_stop`。子工具的改动属于父任务的撤销记录，子 agent 的 `exec_command` 会问同一个用户。
- **子工具集 = 父工具集 − `subagent`**（`_build_child_registry`），所以只有一层委派；MCP 动态工具由 `_adopt_dynamic_tools` 复制过去。子 agent 的 `todo_write` 用独立内存计划板，**不要**传父会话的 board。
- **不要改用 `run_react_loop` 跑子循环**：它的 `_reaps_task_sessions` 会用 `task_id` 停父任务的 MCP 与后台进程，重建 registry 也会绕开"父的 provider + 父的工具集"。子循环只复用 `run_model_turn` 与子 registry 的 `execute_tool`，压缩管线不进入子循环。
- 事件只发 `subagent`（`started` / `tool` / `done` / `failed`），子循环自己的 `llm_*` 不发；长文本 4,000 字符截断。前端需要 `category_subagent`、六份字典里的 `phase` 文案、`buildSubagent` 与 `.tag.subagent`，以及 `eventFilter.js` 的顺序项。
- 取舍与已知限制（子对话不入库、同步阻塞、报告不进父循环的结果预算）见 [ADR 0032](decisions/0032-subagent-tool.md)。

### 桌面操作：CLI 桥，不是 MCP 客户端

- `computer_observe` / `computer_control` 通过 `subprocess` 调 `cua-driver <tool>`（JSON 从 stdin 进入），**没有**复用 MCP 客户端；将来换 MCP 只替换 `agent/tools/computer_driver.py` 的 `call_tool`，工具面对模型不变。
- **会话标签必须等于 `task_id`**（`make_observe_tool` / `make_control_tool` 的绑定）：driver 用它键控快照缓存，`element_token` 才能跨调用复用；如果每次调用换标签，所有 token 都会 stale。
- **观察与操作拆成两个包**，因为门禁按工具：观察 `permission=none`，操作 `PERMISSION_COMPUTER` 且只给 `once` / `session`。不要为了少一个工具把两者合并。
- **driver 的契约写在描述里，不要靠模型试错**：动作前后快照、优先 `element_token`、默认 `background`、`unverifiable` 先重新快照。错误码到指令的映射在 `computer_driver._HINTS` 与 `computer_control/tool.py::_render_result`。
- **截图是否可见由模型配置决定**：`agent/tools/computer_state.py` 负责把 UIA 树压成文本并走 `token_budget`，超预算时把完整 JSON/文本写进 `output_store`。截图通过 `ToolOutcome.images` 交给 `agent/vision.py`：只有模型配置 `supports_image_input` 且 provider 是 OpenAI 兼容 wire format 时，才在工具消息之后追加一条带 `image_url`（base64 data URL）的 user 消息；其他 provider 只保留路径。别在工具描述里承诺模型一定看得到。
- **运行前提**：`cua-driver` 必须在交互式会话（Session 1+）里；Session 0 下 UIA、截图、UWP 激活全部静默失败。错误处理用 `ToolOutcome(success=False)` 回给模型，不抛异常，任务不会因为没装 driver 而崩。
- 取舍见 [ADR 0011](decisions/0011-computer-use.md)。

### MCP：连接测试 + 任务级工具桥

- `agent/mcp/` 有三条用途，共用同一套协议代码：集市页的「测试连接」（`probe_server`，`POST /api/mcp-servers/{id}/probe`）、集市页点开某个工具的「单独调用」（`call_server_tool`，`POST /api/mcp-servers/{id}/tools/{tool}/test`）和任务运行时（`bridge` + `live`）。见 ADR 0031。
- 连接测试弹窗里的工具清单可点：点一行（或「测试」按钮）切到该工具的参数表单，参数由 `input_schema` 生成，提交后后端走 `tool_call.call_server_tool`（独立连接，不参与任务、不走确认门禁），结果按文本展示并截断到 20000 字符。工具自己报 `isError` 是 `ok: false` + 服务端原文，不是接口错误。
- 任务开始时 `_build_runtime` 调 `live.start_for_task(task_id, agent_config["mcp_servers"])`：逐个服务端起进程、`initialize`、`tools/list`，把每个远端工具注册成 `mcp__<服务端>__<工具名>`（`names.py` 负责清洗、截断到 64 字符、撞名加 `_2`）。注册发生在 `get_tool_schemas` **之前**，否则模型看不到就不会调用。
- 这些工具就是普通的 `ToolRegistry` 条目：同样的 deny 名单、同样的 `permission_request`、同样的结果预算与事件。权限种类是 `mcp`，目标从工具名里解析出服务端（`server_of`），摘要形如 `Run echo on MCP server filesystem`。没有第二条分发路径。
- 一个服务端起不来不算任务失败：`bridge.statuses` 记下原因，工具缺席，`registry.mcp_status` 带进「Starting ReAct loop」事件和系统提示词的 `## MCP servers` 一节（`prompt.py`）——否则"连不上"和"没配置"在模型看来是一样的，它会直接回答"没有 MCP"。
- 生命周期是任务级：`live` 按 task_id 记桥，`_reaps_task_sessions` 在循环的任何出口都调 `stop_task`，与 `process_store.stop_task` 同一个位置、同一个理由。空 task_id（CLI）也是一个键，所以 REPL 不会每轮攒一套进程。
- 协议是手写的 JSON-RPC 2.0 行分隔实现（`jsonrpc.py` + `stdio.py`），不引 SDK：与 `computer_driver` 一样按子进程说话，省一个依赖，也便于自己处理 Windows 的 `.cmd` shim。
- 三根管道用**两种编码**解码（`stdio.py::_wrap_pipes`）：stdout 是协议消息，按规范 UTF-8；stderr 是 `cmd.exe` / npm 的诊断，Windows 上是控制台代码页（中文系统 GBK）。统一按 UTF-8 解会把最常见的「'npx' 不是内部或外部命令」变成乱码。
- `target` 写成绝对路径时，其所在目录会被放到子进程 `PATH` 最前（`_child_env`）：`npx.cmd` 这类 shim 会按名字调 `node`，不这么做就会"包装好了也起不来"。写成裸 `npx` 则要求后端进程自己能在 `PATH` 里找到它（fnm 管理的 Node 要先激活）。
- 探测失败一律是 `200 + ok: false + error`：连不上、超时、服务端报错、非 JSON 输出都算"这次没连上"，不是接口错误；只有预设不存在才 404。错误信息里带 stderr 尾部，因为 npm 的 404 / 缺 `node` 只会说在 stderr 上。
- 远端工具报错（`isError`）抛 `McpToolError`，于是那一步是失败而不是成功。`image` 块由 `agent/mcp/images.py` 写成 `ToolImage`（内容寻址、png/jpeg/webp/gif、8 MB 上限），与 `computer_observe` 同一条视觉通道，文本里另留一行 `[image image/png]` 给看不见图的模型；`audio` 只留标记。
- 三种传输方式由 `agent/mcp/transport.py` 的 `open_session` 统一映射：`stdio` 起子进程，`sse` 连两段式事件流，`http` 是 Streamable HTTP（单 URL，POST + 可选 SSE 流）。`normalize_transport` 把 `streamable` / `streamable-http` / `streamable_http` 归一化成 `http`；探测与运行时共用这一个入口，不会给出不同答案。
- 关停走 `taskkill /F /T`（Windows）或 `killpg`（POSIX）：`npx` 后面还有 `node` 子进程，只杀 `Popen` 返回的那个会留下孤儿（仅 `stdio` 有子进程）。

## 13. 后端模块划分（`main.py` 拆分后）

`main.py` 曾经承担全部后端职责，涨到 1700+ 行、超过 `AGENTS.md` 的 ~700 行上限。现在按职责拆开，URL 路由模块统一放在 `routes/` 包里（一个模块一组路由）：

| 文件 | 放什么 | 不放什么 |
| --- | --- | --- |
| `main.py` | FastAPI app 装配、CORS、静态前端与兜底路由、健康检查、服务入口（`--host` / `--port` / `--reload`） | 业务路由、运行期状态 |
| `commons/schemas/` | 所有请求/响应 pydantic 模型，按资源一个模块（`tasks` / `config` / `llm` / `permissions` / `sessions` / `workspace` / `agents` / `tools`）；`__init__.py` 全量 re-export，调用方只认一个导入路径 | 任何行为 |
| `commons/state.py` | 进程内的**活状态**：`monitor_store`、`permission_rule_store`、四项全局配置（保留天数 / 步数上限 / AGENTS.md 指令 / 确认模式）及其 `source`、三类任务注册表（停止事件、权限 broker、提问 broker）、`status_for_event`、`ROOT_DIR` | 任何判断逻辑 |
| `agent/history.py` | 会话上下文：把同一会话中**已完成**任务的 `query` / `result` 重建成 `user` / `assistant` messages，并按消息数 / 字符预算裁剪（只留最近的轮次） | 不注入、不运行任务 |
| `agent/usage.py` | 两处读数：任务的 token 总和与墙钟耗时；会话的上下文占用（最近一次模型请求的 `usage`，回溯最多 5 个任务 / 5 条响应，分母取模型 `max_input_tokens`，缺失时回退到循环自己的字符预算 ÷ 4） | 不估算文本、不改上下文 |
| `agent/runtime/` | "一个任务是什么"：`config`（provider / 工作目录 / 步数 / 确认模式的解析）、`naming`（会话标题与任务名）、`purge`（保留期清理）、`events`（事件构造）、`runner`（`run_task`：跑 ReAct 循环并把两个 broker 注册进 `commons.state`） | HTTP 细节 |
| `agent/mcp/` | MCP 客户端与工具桥：`jsonrpc`（行分隔消息编解码）、`stdio`（起进程、读写管道、关停进程树）、`session`（握手 / 工具清单 / 工具调用）、`probe`（集市的一次性连接测试）、`tool_call`（集市的一次性工具调用）、`bridge`（把远端工具注册成 `mcp__<server>__<tool>`）、`live`（任务级开关与关停）、`names`（命名与反解）、`prompt`（提示词里的服务端列表）、`models`（结果类型） | 不读 `commons` / `dao`，不碰路由 |
| `routes/task_api.py` | 任务与事件路由：创建、列表、详情、停止、删除、SSE 与 WebSocket 推流、两个答复端点（permission / question） | 状态定义 |
| `dao/` | 任务 / 会话 / 工作空间 / 事件 / 全局设置的 SQLite 读写，持有连接与锁；按职责拆成 `base`（常量与行工具）/ `schema`（建表与迁移）/ `sessions`（会话、工作空间）/ `forks`（Fork 复制）/ `agents` / `settings` / `tasks`（任务与事件）/ `store`（组合类） | provider、模型与 MCP（各自独立模块） |
| `dao/llm.py` | provider 端点与模型两张表的 SQL、旧 `models` 表的一次性迁移；共用 `dao.store` 的连接与锁 | 限流策略 |
| `dao/mcp.py` | MCP 集市表的 SQL（自管连接，同一个库文件） | |
| `routes/workspace_api.py` | 会话、工作空间路由 | 模型 / provider 配置 |
| `routes/llm_api.py` | provider 与模型路由、写入时把 RPM 推给 `provider_throttle`（`sync_provider_throttle`） | 限流的窗口算法 |
| `routes/agent_api.py` | 模式、智能体、技能库路由 | |
| `routes/admin_api.py` | 管理配置路由（保留期 / 步数 / 确认模式 / 权限规则）、启动时把 env + 数据库读进 `commons.state` 的 loader、`.env` 加载 | 业务路由 |
| `routes/mcp_api.py` | MCP 集市路由（`/api/mcp-servers`，含连接测试 `POST /{mcp_id}/probe` 与单工具调用 `POST /{mcp_id}/tools/{tool_name}/test`） | 存储实现（在 `dao/mcp.py`）与协议细节（在 `agent/mcp/`） |

两条必须守住的规则：

1. **状态只有一份，在 `commons/state.py`。** 路由与任务运行都读 `commons.state.monitor_store`，而不是 `from dao import monitor_store` 那种"把名字绑走"的写法：绑名字会让"测试换了存储、路由还在用旧的"变成一次静默失效（`test/permission_api_test.py` 与 `test/question_api_test.py` 因此在 `commons.state` 上替换存储）。
2. **路由模块不得 import `main`。** 需要状态就 `from commons import state`，需要任务逻辑就 `from agent import runtime`；`main` 只单向 import 它们。这条是拆分成立的前提，否则就是循环依赖。
3. **`agent` 的下层不 import 上层。** `agent/tools/**` 与 `agent/agent_loop/**` 不许 import `commons` 或 `dao`（工具要能脱离服务端单独测，ADR 0019）；`agent/runtime`、`agent/history`、`agent/usage` 是例外——它们执行和统计任务，必须读活状态（ADR 0025）。

拆分本身是**纯搬运**：路由路径、字段、状态码、事件顺序都没动；验证方式是"全量测试 + 与拆分前的 OpenAPI 路径清单逐一比对"（29 条对 29 条）。

`task_store.py` 后来同样超过行数上限，按职责拆成了包；ADR 0025 又把它改名为 `dao/` 并收编了 provider / model / MCP 三块存储：`__init__.py` 只做导出并创建单例，对外仍是 `from dao import _SqliteTaskStore, monitor_store, TASK_DB_PATH`；各部分共用 `store.py` 里的连接与锁。新增存储逻辑写进对应职责的模块，不要再往 `store.py` 堆。

### provider 包与流式请求

`agent/provider.py` 涨过行数上限后按职责拆成包：`naming.py`（名称与地址规范化）、`config.py`（`ProviderConfig`）、`wire.py`（OpenAI 形状的消息 / 响应 / `StreamDelta`，以及 usage 归一）、`base.py`（`BaseProvider` 与非流式回落）、每个 wire 格式一个模块、`factory.py`（`build_provider`）。对外仍是 `from agent.provider import ...`，不要越过包去 import 内部模块。

模型请求默认走流式（`RunTaskRequest.stream` 默认 `true`）：

- 适配器实现 `stream_chat_completion()` 并置 `supports_streaming = True`；没有流模式的适配器继承 `BaseProvider` 的回落，把一次性响应包装成单个 `StreamDelta`，循环只认一种形状。
- `agent/streaming.py` 负责把分片折回一条完整消息：content、reasoning、分片的 `tool_calls`（按 `index` 拼，`id` 变了视为新调用）、usage、首 token 与总耗时。
- 思考内容以 `reasoning_content` 挂在 assistant 消息上，**只用于展示**：写回 `messages` 前必须剥掉（网关会拒绝或按它计费）。事件里另有顶层 `reasoning` 字段，连同 `stream` / `first_token_ms` / `duration_ms` / `chunk_count` 一起记录，Web Admin 的「深度思考」区块读的就是它。
- `agent/agent_loop/model_turn.py` 是模型半步（请求 + 解析 + 事件），`steps.py` 只剩工具半步；`_report_throttle_wait` 也随之搬走。

## 14. 决策记录与术语

- 设计决策（ADR）：`docs/decisions/`，命名 `NNNN-<topic>.md`。新增需要"解释为什么"的取舍时，先写 ADR 再改代码。
- 术语表：`docs/glossary.md`。新增领域名词（工具、事件、策略、patch 结构等）时同步补条目。
- 当前已有：
  - [ADR 0001 `edit_file` 工具的设计](decisions/0001-file-edit-tool.md)
  - [ADR 0002 文件工具的编码策略](decisions/0002-file-encoding.md)
  - [ADR 0003 `edit_file` 的写入与补丁语义](decisions/0003-edit-write-and-patch.md)
  - [ADR 0004 `write_file` 工具的设计](decisions/0004-file-write-tool.md)
  - [ADR 0005 `exec_command` 工具与沙箱分层](decisions/0005-exec-tool.md)
  - [ADR 0006 工具权限确认（P1 交互式确认）](decisions/0006-tool-permission-confirmation.md)
  - [ADR 0007 未绑定会话的相对路径基目录](decisions/0007-default-workspace.md)
  - [ADR 0008 `write_stdin` 工具与"还活着的会话"](decisions/0008-write-stdin-tool.md)
  - [ADR 0009 `exec_command` 的 `tty`（伪终端）](decisions/0009-exec-tty.md)
  - [ADR 0010 `ask_user_question` 工具与"提问通道"](decisions/0010-ask-user-question.md)
  - [ADR 0011 桌面操作（`computer_observe` / `computer_control`）](decisions/0011-computer-use.md)
  - [ADR 0012 工具结果预算（tool result budget）](decisions/0012-tool-result-budget.md)
  - [ADR 0013 按 provider 的模型请求限流（RPM）](decisions/0013-llm-rpm-limit.md)
  - [ADR 0014 Provider 与模型分离，RPM 按 provider + base_url 计](decisions/0014-provider-model-split.md)
  - [ADR 0015 snip_compact（对话窗口裁剪）](decisions/0015-snip-compact.md)
  - [ADR 0016 micro_compact（只缩短模型已读过的结果）](decisions/0016-micro-compact.md)
  - [ADR 0017 compact_history（用一次模型调用换掉旧历史）](decisions/0017-compact-history.md)
  - [ADR 0018 搜索的可见范围（glob 排序、grep 忽略规则）](decisions/0018-search-visibility.md)
  - [ADR 0019 取消要能打断正在跑的命令](decisions/0019-cancel-interrupts-running-work.md)
  - [ADR 0020 任务改动的快照与回退](decisions/0020-checkpoint-rewind.md)
  - [ADR 0021 任务窗口的上下文占用读数](decisions/0021-context-usage-meter.md)
  - [ADR 0022 AGENTS.md 进入系统提示词](decisions/0022-agents-md.md)
  - [ADR 0023 工作空间里只留一个 `.ngy-agent/`](decisions/0023-workspace-data-dir.md)
  - [ADR 0024 工具黑名单：命中即拒绝](decisions/0024-tool-denylist.md)
  - [ADR 0025 根目录只留 `main.py`，应用层拆进 `commons` / `dao` / `agent.runtime`](decisions/0025-root-only-main-py.md)
  - [ADR 0026 `delete_file` 工具的设计](decisions/0026-delete-file-tool.md)
  - [ADR 0027 `web_fetch` 工具的设计](decisions/0027-web-fetch-tool.md)
  - [ADR 0028 `web_search` 工具的设计](decisions/0028-web-search-tool.md)
  - [ADR 0029 `web_browser` 工具的设计](decisions/0029-web-browser-tool.md)
  - [ADR 0030 `vault_http` 工具的设计](decisions/0030-vault-http-tool.md)
  - [ADR 0031 MCP 服务端的工具接进任务运行时](decisions/0031-mcp-tool-bridge.md)
  - [ADR 0032 `subagent` 工具：把一段子任务放进独立上下文](decisions/0032-subagent-tool.md)

## 15. 可观测（OpenTelemetry Tracing）

目标不是替代事件流，而是补上"一次执行到底调了什么"的调用树：`TaskEvent` 仍然是 Web Admin 的唯一数据源，trace 默认只写本机文件（或控制台），不依赖任何外部后端。

### 代码位置

| 位置 | 职责 |
| --- | --- |
| `agent/telemetry/config.py` | 读 `OTEL_*` 环境变量；非法值回落默认并打印一行提示 |
| `agent/telemetry/setup.py` | 幂等装配 `TracerProvider` + `Resource` + `ParentBased(TraceIdRatioBased)` 采样 + `BatchSpanProcessor`；`shutdown_telemetry()` 负责刷盘；关闭时不占用"已初始化"状态，允许 `.env` 晚加载后再开 |
| `agent/telemetry/exporters.py` | `JsonlSpanExporter`：每行一个 span；写不进去返回 `FAILURE` 而不是抛异常 |
| `agent/telemetry/attributes.py` | 属性截断（512 字符）与敏感键脱敏（按 key 分段匹配，`gen_ai.usage.input_tokens` 不会被误判成凭证） |
| `agent/telemetry/usage.py` | 兼容 OpenAI 的 `prompt_tokens`/`completion_tokens` 与 Anthropic 的 `input_tokens`/`output_tokens` |
| `agent/telemetry/spans.py` | `task_span` / `react_step_span` / `llm_span` / `tool_span`，以及跨线程的 `TaskSpanHandle` |

埋点调用点只有四处：`agent/agent_loop/runtime.py` 的 `_traced_run`（任务根）、`agent/agent_loop/loop.py`（步骤）、`agent/agent_loop/model_turn.py` 与 `agent/agent_loop/steps.py`（模型请求与工具调用）、`task_api.create_task` + `agent/runtime/runner.py` 的 `run_task`（任务生命周期）。

### 三条必须守住的约定

1. **埋点不改变控制流。** span 内部一律 `try/except` 吞掉自己的错误；LLM 失败仍然 `raise failure from exc`，工具异常仍然变成 `Error: ...` 结果回给模型。`with` 块里的异常照常向外抛，由 SDK 记到 span 上。
2. **关闭时零成本。** 没有 provider 时 `active_tracer()` 返回 `None`，四个上下文管理器直接 `yield None`，事件 `data` 里也不会出现 `trace_id`。
3. **跨线程靠显式传递。** 任务跑在 `threading.Thread` 上，`contextvars` 不会跟着走，所以 `create_task` 在请求线程 `start_task_span()`，把 `TaskSpanHandle` 当普通参数交给 `run_task`；后者 `attach`/`detach`，并在 `finally` 里结束 span（失败任务也要结束，否则 span 永远不落盘）。

### 被排除的路径

`main.OTEL_EXCLUDED_URLS` 排除了 `/api/tasks/{id}/events/stream`、`/api/tasks/{id}/events/ws` 与前端静态资源：前两个是长连接，instrument 之后 span 会一直挂到任务结束，是真实的内存风险；静态资源没有调试价值。

### 测试

`test/telemetry/` 按模块镜像：

- `config_test.py` / `exporters_test.py` / `attributes_test.py` / `usage_test.py`：纯单元；
- `spans_test.py`：嵌套、复用外层 span、禁用时零 span、异常状态；
- `agent_loop_tracing_test.py`：假 provider 跑完整循环，断言 span 层级与事件里的 `trace_id`；
- `task_tracing_test.py`：跨线程句柄的 attach/结束，失败任务也要关 span；
- `http_tracing_test.py`：`TestClient` 打一次 `/api/healthz`，确认 HTTP span 与被排除路径。

## 16. 任务断点续跑（`task_recovery/`）

任务的线程不跨进程，行会留在 `running`；唯一的终态写手是线程本身，所以崩溃后没人再改它。`task_recovery` 在服务启动（`main._lifespan`）时补上这一环：认出这种行，从事件日志重建对话，然后**接着跑**。

### 代码位置

| 位置 | 职责 |
| --- | --- |
| `task_recovery/transcript.py` | 纯函数：`build_resume_plan(events, query, ...)` → `ResumePlan`。不碰数据库、不起线程 |
| `task_recovery/launch.py` | 认领任务、查模型、起线程；放弃/收尾时写事件 |
| `dao.list_unfinished_tasks()` | `running` / `waiting` 的行（`waiting` 也是"在飞"，ADR 0006 D10） |
| `dao.increase_resume_count()` / `reset_resume_count()` | 无进展重试预算 |
| `agent/agent_loop/loop.py` | `first_step`（续跑接着编号）、`append_user_query`（重建的对话已含 query）、`Starting ReAct loop` 事件里的 `initial_messages` |
| `agent/runtime/runner.py` 的 `_execute_task()` | `resume_messages` / `resume_step` 透传；续跑时跳过会话命名 |

### 三条必须守住的约定

1. **已记录的结果绝不重算。** 恢复时 `tool_result` 里的 `result` 直接拼回 `messages`，工具不执行；没有结果事件的调用也**不重放**，而是合成一条 `INTERRUPTED_TOOL_NOTE` 的 tool 消息，让模型自己确认现状。这条是"不重复执行"的全部依据——工具的副作用在日志之外，猜不得。
2. **用过期的 row 不如不续跑。** 没有可用基线（请求形态被改写的 provider 且没有 `initial_messages`）、绑定的模型已删除、对话无法重建时，一律 `failed` + 一条说明事件，而不是拿错误的上下文继续跑。
3. **重试预算只惩罚"卡住"。** `resume_count` 在每次认领时 +1，但上一次续跑若产生过 `llm_response` / `tool_result`（从日志判断，跨进程有效）就清零。所以"每次都往前挪一步、但服务总被重启"的任务不会被放弃，只有"一续跑就死"的任务会在第 4 次被 `Task recovery gave up` 结束。

### 为什么基线取最后一个 `LLM request`

`raw_request.messages` 是那一轮真正发给模型的列表，压缩（ADR 0015–0017）、会话历史、截图消息都已经在里面，重放窗口只有"这一步之后"那么短。`anthropic*` / `gemini` 会把 messages 改写成自己的 wire 格式，所以这两类 provider 走 `Starting ReAct loop` 事件里的 `initial_messages`（loop 在组好消息后记一份脱敏副本），代价是从第 1 步重放，正确性一致。

### 事件与状态

- 续跑起点：`debug` / `Task resumed after restart`（含 `mode` / `next_step` / `reused_tool_results` / `unresolved_tool_calls`）；
- 线程启动：`debug` / `Resume task execution`（`resumed: true`，`first_step` 为续跑起始 step）；
- 放弃：`error` / `Task recovery failed` 或 `Task recovery gave up`，任务置 `failed`；
- 已收尾的残留行：只补 `finish_task`，不重跑。

### 测试

`test/task_recovery/` 镜像源码：

- `transcript_test.py`：纯决策——复用结果、未知调用、最后一条回答直接收尾、步数耗尽、provider 改写回退、缺基线返回 `None`；
- `launch_test.py`：认领只一次、进程内在跑的任务不动、模型消失/无基线转 `failed`、有进展不计入预算；
- `startup_test.py`：真的走 `TestClient(main.app)` 的 lifespan，确认钩子接上且两次启动只起一个线程。
