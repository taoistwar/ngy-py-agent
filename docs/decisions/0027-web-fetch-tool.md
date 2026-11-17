# ADR 0027: `web_fetch` 工具的设计

- 状态：已接受（Accepted）
- 日期：2026-11-17
- 相关：`agent/tools/web_fetch/`、`agent/tools/web_urls.py`、`agent/tools/permissions.py`、`agent/tools/catalog.py`、`agent/modes.py`、`web-admin/src/components/admin/toolMeta.js`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0012](0012-tool-result-budget.md)（工具结果预算）、[ADR 0013](0013-llm-rpm-limit.md)（模型请求频率）、[ADR 0024](0024-tool-denylist.md)（工具黑名单）

## 背景

模型想读一篇网页时，现有工具集只有两条路：`exec_command`（`curl` / `Invoke-WebRequest`）或 `code_interpreter`（`requests`）。两者都能拿到页面，但都不是"读网页"这件事的形状：

- 没有域名层面的确认——确认框问的是"跑这条命令"，看不出"要访问哪个站"；
- 没有大小上限——一个流式接口可以把上下文撑爆；
- 没有把 HTML 变成可读文本的步骤——模型要么自己啃标签，要么多花一步写脚本；
- 结果形态随 shell 方言而变，失败只知道"命令退出了"。

参考实现（Claude Code 的 `WebFetchTool`）的形状是：`url` + `prompt` → 抓取 → HTML 转 Markdown → 小模型按 `prompt` 提炼 → 6 字段回执（`result` / `code` / `codeText` / `bytes` / `durationMs` / `url`）。本 ADR 记录把它搬进本仓库时的取舍：哪些照抄，哪些必须改。

## 决策

### D1. 不提供 `prompt` 参数：工具内部不调用模型

参考实现用一个更小的模型（Haiku）按 `prompt` 提炼答案。本仓库不这么做，理由不是"省掉了就好"，而是分工：

- tool 层拿不到 provider，也不该拿到：本仓库里唯一会额外调模型的是压缩管线的历史摘要步骤（[ADR 0017](0017-compact-history.md)），它在 loop 里，带 span、`llm_request`/`llm_response` 事件与用量记账；
- 工具内部发起的模型调用会绕过速率限制的"每步一次请求"语义（[ADR 0013](0013-llm-rpm-limit.md) 的钩子在 wire 层，计数却按 provider 走），也让上下文占用计量（[ADR 0021](0021-context-usage-meter.md)）对不上账；
- 主模型本来就在 loop 里，下一步就要读这段正文。"答案"没有第二个消费者，提炼只是把同一份内容换个说法。

代价：模型必须自己从正文里得出结论。收益：一次抓取只发生一次请求，结果可复现，成本可预测。

### D2. 权限种类是 `read`，目标是**域名**

参数名是 `url`，而权限门对 `read` 类工具读的是 `file_path` / `path`（`permissions._target`），直接复用会把目标算成 `web_fetch` 这个字符串。因此：

- `permissions.NETWORK_READ_TOOLS = ("web_fetch",)`，`_target` 用 `web_urls.host_of(url)` 返回主机名；
- 这类工具**每次都问**——`_read_needs_confirmation` 的文件系统启发式（敏感文件名、工作空间外）对网络没有意义；
- 规则键是主机名（`example.com`），所以一个任务里第二次抓同一站点不再弹框："允许这个站"是用户能判断的粒度，一页一问会让多页阅读不可用；
- 子域不继承：`evil.example.com` 与 `example.com` 是两条规则；
- URL 本身不合法时 `_target` 返回 `None`，权限门**不问**——工具自己会报错，"不可批准的问题"不该弹框（与 ADR 0006 D9 同一条理由）。

配套改 `_build_request`：`read` 分支的默认文案是 "Read \<路径\>" 且带 `reason=sensitive_path`；网络读取必须是 "Fetch \<主机\>"、`reason=network_fetch`，并把完整 `url` 放进 `details` 供确认框显示。

### D3. 同域重定向跟随，跨域不跟随

用 `allow_redirects=False` 自己走跳转循环，最多 5 跳：

- **同域**（主机名相等；端口与协议可以不同，因此 `http://example.com` → `https://example.com` 能过）继续走；
- **跨域**立刻返回 `redirect_to` + `REDIRECT DETECTED` 文案，让模型另发一次调用。新域名没被批准过，跟过去等于绕过 D2；而"带着新地址再抓一次"正是参考实现的行为；
- 跳数用尽报 `too_many_redirects`，不静默返回中间的 3xx 页面。

### D4. 上限，以及"不完整必须说明"

- 只接受 `http` / `https`；URL 内嵌用户名或密码直接拒绝（它会被回显进结果与事件日志）；控制字符拒绝；空格按 `%20` 编码。
- 正文最多 2 MiB，边读边截；`response_truncated` 为真时正文末尾追加一行说明。**不静默截断**。
- 单次超时默认 20 秒（`WEB_FETCH_TIMEOUT_SECONDS`，上限 120），连接超时 10 秒。
- HTTP 状态 ≥ 400 报 `http_error` 并带 `code` / `code_text`，不把错误页当正文：错误页对模型只有噪音，且会让它以为页面内容就是 "404 Not Found"。
- 正文为空（JS 渲染、登录页、204）返回一段固定文案，不返回空字符串——空的工具结果只会换来一次重试。

### D5. 文本转换用标准库 `html.parser`，不引依赖

`html_text.py` 把 HTML 变成 Markdown 风格文本：标题、段落、列表（嵌套缩进、有序编号）、链接（相对地址按最终 URL 解析）、图片 alt、行内代码、围栏代码块（保留缩进）、表格行（`| a | b |`）。丢弃：

- `script` / `style` / `noscript` / `template` / `svg` / `iframe` / 表单控件；
- `hidden` 与 `aria-hidden="true"`；
- `nav` / `footer` / `role="navigation" | "banner" | "contentinfo"`。

最后一条是本仓库自己加的：参考实现靠小模型过滤站点框架（D1 把它拿掉了），所以只能在转换阶段丢。实测 Python 文档页因此从"开头 1,000 token 的侧边栏"变成"标题 + 正文"。代价是正文若被放在 `<nav>` 里会丢——可接受，因为这类页面把菜单当正文写时，任何启发式都会误判。

解析器异常时回退到"正则去标签"：抓取已经成功，不该在转换这一步失败。

### D6. 大结果落盘，二进制也落盘

- 文本超出输出 token 预算时写进 `ToolBindings.output_directory`（本次运行的临时树，`read_file` 可读不可写，与 `exec_command` 的大输出同一条契约），结果给 `persisted_path` 与预览；预览字符数是 `min(2000, budget × 3)`，避免"预览本身就超预算"这个自相矛盾的状态。
- 非文本（PDF、图片、压缩包）按**原字节**写盘并给路径，不尝试转文本：把 PDF 当文本返回只会制造一段错误的"正文"。需要 PDF 正文是另一个工具的职责。

### D7. 分类、顺序与模式

- 新分类 `network`（`spec.CATEGORY_NETWORK`，管理页分组"网络访问"），六种语言的标签一起补（`toolMeta.js` + `locales/*.json`）。
- 工具顺序放在 `grep` 与 `read_file` 之间：发现先于读取（文件名 → 代码 → 网页）。
- `ask` 模式（只读）把它加入允许列表：抓网页不改本地状态。`build` 是 `tool_names=None`，自动包含。

## 后果

- 模型看到"回执 + 正文"：`url`、`requested_url`、`code`、`code_text`、`content_type`、`bytes`、`duration_ms`、`redirected`、`response_truncated`、`title`、`media_type`、`encoding`、`content`、`content_truncated`、`persisted_path`、`original_tokens`。失败是 `{"error", "reason", ...}`，原因码：`invalid_argument` / `invalid_url` / `unsupported_scheme` / `credentials_in_url` / `timeout` / `connection_failed` / `tls_error` / `request_failed` / `http_error` / `bad_redirect` / `too_many_redirects`。
- 不解析 PDF；不跟随跨域跳转；没有 `prompt`（D1）。
- **不是安全边界**：不做 DNS 解析，也不拦私网 / 回环地址。`exec_command` 本来就能访问同样的网络，一个假装沙箱的抓取工具只会误导；真要拦在网络层拦，D2 的域名确认是这一层能提供的全部保护。
- 已有数据库里的内置 `ask` 智能体不会自动获得新工具（`_seed_default_agents` 只补空字段，不覆盖已有 `tool_names`），需要在管理页添加；`build` 自动获得。
- 新增共享模块 `agent/tools/web_urls.py`：工具与权限门必须对"这是哪个主机"给出同一个答案，否则要么重复弹框，要么把批准过的站点的规则套到另一个站上；而工具包之间不许互相 import，所以它落在包根。
