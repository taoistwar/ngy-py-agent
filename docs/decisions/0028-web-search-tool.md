# ADR 0028: `web_search` 工具的设计

- 状态：已接受（Accepted）
- 日期：2026-11-17
- 相关：`agent/tools/web_search/`、`agent/tools/permissions.py`、`agent/tools/catalog.py`、`agent/modes.py`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0012](0012-tool-result-budget.md)（工具结果预算）、[ADR 0024](0024-tool-denylist.md)（工具黑名单）、[ADR 0027](0027-web-fetch-tool.md)（`web_fetch`）

## 背景

模型需要联网找资料时，现有工具集里只有两条路：

- `web_fetch` 能读，但**必须先知道 URL**。没有搜索，模型只能凭记忆猜一个网址，猜错就是一次 404 或一条编造的引用；
- `exec_command`（`curl` + 手工解析）或 `code_interpreter`（`requests`）能凑出搜索请求，但没有统一的返回形状、没有域名过滤、失败形态随方言漂移，而且确认框问的是"跑这条命令"，看不出"要访问哪个搜索服务"。

参考实现（Claude Code 的 `WebSearchTool`）的形状是：`query` + 若干筛选参数 → 服务端/兜底搜索 → 一张结果单（`query` / `results` / `durationSeconds`），其中 `results` 是"标题 + 网址 + 摘要"。本 ADR 记录把它搬进本仓库时的取舍。

## 决策

### D1. 后端由配置决定，不是工具参数

`WEB_SEARCH_PROVIDER` 选后端（`duckduckgo` / `tavily` / `serper` / `bing`），`WEB_SEARCH_API_KEY` 给密钥，`WEB_SEARCH_BASE_URL` 可整体覆盖端点。

模型不选后端：它不知道这次部署配了哪个 key，"换一个引擎重试"也不是它能做的有效动作，多一个它填不对的参数只是多一次浪费。

默认后端是**无需密钥**的 DuckDuckGo HTML 端点，理由是可获得性：工具在拿到仓库、没有任何配置时就应该能用。代价是它抓的是页面结构、可能被机器人校验拦住；两种情况都返回明确原因（`provider_blocked`），不伪装成"没有结果"。

**更新（2026-11-24）**：管理员可以在 Web Admin 的“系统 → 联网搜索”页面配置后端、密钥和端点覆盖，值存入 `settings` 表并推入运行中的工具，下一次搜索立即生效。数据库中的一行优先于 `WEB_SEARCH_*` 环境变量；环境变量只在该页面从未保存过时作为回落。超时与默认条数仍由环境变量控制，不在页面里。

### D2. 只返回链接与摘要，不抓正文

参考实现有 `livecrawl` / 正文抓取选项。这里不提供：

- 抓正文需要 `web_fetch` 已有的全部规则（2 MiB 上限、HTML→文本、跨域跳转不跟随、二进制落盘）；
- 在第二个工具里复制一份，等于让两条链路各自演化——用户批准过的是 `web_fetch` 的域名，而搜索工具抓正文会绕过那次确认；
- 模型拿到链接后下一步就是 `web_fetch`，那一步本来就要走。

因此工具里没有 `livecrawl`、没有 `include_raw_content`，描述里直说"它不开页面"。

### D3. 权限种类 `read`，目标是工具自身

搜索没有 `url` 可作规则键（`permissions._target` 对 `NETWORK_READ_TOOLS` 取 `host_of(url)`），而按 `query` 建规则会让用户为每个新问题重新点一次：

- `NETWORK_READ_TOOLS` 加入 `web_search`，因此跳过"文件读取通常不用问"的启发式，**每次都问**；
- `_target` 在没有 URL 时返回 `SEARCH_PERMISSION_TARGET`（`"web_search"`），规则键是工具本身——一次授权覆盖本任务里的所有搜索；
- query 为空则返回 `None` 不弹框：工具自己会报 `invalid_query`，不为不可批准的问题打扰用户；
- `_build_request` 增加 `network_search` 分支：文案 "Search the web: \<query\>"，`details.query` 供确认框显示。

### D4. 参数：有效的筛选，而不是参数镜像

保留 `query`（≥2 字符）、`allowed_domains` / `blocked_domains`（互斥，子域包含）、`num_results`（默认 8，上限 20）、`search_type`（`auto`/`fast`/`deep`）、`context_max_characters`（默认 10000）。

- 数值**钳制**而不是报错：要 100 条是能服务的请求，按 20 返回并在回执里说明；把一组数字当错误只会让模型改写参数重试。
- `search_type` 非法值**报错**：枚举值不是"稍微偏一点"的东西，静默当成 `auto` 会让模型以为深搜生效了。只有 Tavily 支持深度，回执里 `search_type_applied` 说明是否生效。
- 域名接受 `https://example.com/docs`、`*.example.com` 这类写法并归一化成裸域名：模型把域名写成 URL 很常见，为此失败一次没有收益。

### D5. 失败是结果，不完整也要说明

- 失败统一 `{"error", "reason", ...}`，原因码区分可行动的情况：`missing_api_key`（该配 `WEB_SEARCH_API_KEY`）/ `unsupported_provider` / `invalid_query` / `conflicting_domain_filters` / `timeout` / `http_error`（带 `code`）/ `bad_response` / `provider_blocked`。
- 三重"不完整"分开报：`filtered_out`（域名过滤）、`context_truncated` + `dropped_results`（超 `context_max_characters`，按整条丢）、`content_truncated` + `persisted_path`（超输出 token 预算，落盘给预览）。
- 空结果是**答案**：`result_count: 0` 加一句"换个说法，不要重复同样的搜索"；被过滤吃空时换成另一句提示。这两种情况必须不同，否则模型会去改查询，而问题出在过滤器上。

### D6. 分类、顺序与模式

- 分类沿用 `network`（`spec.CATEGORY_NETWORK`），管理页与六份 `locales/*.json` **无需改动**。
- 顺序放在 `grep` 与 `web_fetch` 之间：先找到页面，再读页面。
- `ask` 模式（只读）加入允许列表：搜索不改本地状态。`build` 是 `tool_names=None`，自动包含。`plan` 仍然没有工具。

## 后果

- 模型看到：`query`、`provider`、`search_type` / `search_type_applied`、`result_count`、`results`（`title`/`url`/`snippet`）、`filtered_out`、`context_truncated` / `dropped_results`、`content`（Markdown 链接列表）、`content_truncated` / `persisted_path`、`duration_ms`。
- 不读正文、不翻页、不做 JS 渲染；`fast` / `deep` 只在 Tavily 上生效。
- 默认后端依赖一个**页面结构**：DDG 改版会让它返回 `provider_blocked` 或空结果，此时应配置 API 后端，而不是调整解析器去追新标记。
- 不是安全边界：不拦私网、不做 DNS 过滤；`exec_command` 本来就能访问同样的网络。
- 新增设置项（`WEB_SEARCH_*`）写进 `.env.example`，与 `WEB_FETCH_TIMEOUT_SECONDS` 同样按调用时读取，非法值回落默认。
