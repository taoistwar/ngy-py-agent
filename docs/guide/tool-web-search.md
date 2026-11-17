# 工具：`web_search`（联网搜索）

给模型一个关键词，它把排序后的结果带回来：每条是**标题 + 网址 + 摘要**。它**只搜不读**——要把某一页读下来是 [`web_fetch`](tool-web-fetch.md) 的事。

`build` 与 `ask` 模式可用（`ask` 是只读模式）；`plan` 模式没有工具。取舍见 [ADR 0028](../decisions/0028-web-search-tool.md)。

## 参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string（必填） | 搜什么。至少 2 个字符；连续空白会被压成一个空格。 |
| `allowed_domains` | string[]（可选） | 白名单：只返回这些站点的结果。写裸域名（`example.com`），也接受 `https://example.com/docs` 这种写法——会被归一化成域名。**包含子域**：`example.com` 也允许 `docs.example.com`。 |
| `blocked_domains` | string[]（可选） | 黑名单：不返回这些站点的结果。语义同上。**不能与 `allowed_domains` 同时给**，同时给直接报错（`conflicting_domain_filters`）。 |
| `num_results` | integer（可选） | 要几条结果。默认 8，上限 20（超过按 20 处理，不报错）。 |
| `search_type` | string（可选） | `auto`（默认）/ `fast` / `deep`。只有支持深度的后端（Tavily）会真正改变行为，结果里 `search_type_applied` 说明是否生效。 |
| `context_max_characters` | integer（可选） | 返回列表的字符上限，默认 10000（下限 500、上限 50000）。超出部分按整条丢弃，`context_truncated` / `dropped_results` 说明丢了多少条。 |

没有 `livecrawl` 之类的“顺手抓正文”参数：抓取与正文提取是 `web_fetch` 的职责，复制一份只会让两套规则（大小上限、HTML 转换、跳转规则）各自漂移。

## 返回

成功时是一张"结果单"：

| 字段 | 含义 |
| --- | --- |
| `query` | 这次搜索的问题（归一化后） |
| `provider` | 实际使用的后端（`duckduckgo` / `tavily` / `serper` / `bing`） |
| `search_type` / `search_type_applied` | 请求的力度，以及后端是否真的支持它 |
| `result_count` | 返回条数 |
| `results` | `{"title", "url", "snippet"}` 数组 |
| `filtered_out` | 被域名过滤（或重复 URL）去掉的条数 |
| `context_truncated` / `dropped_results` | 是否因 `context_max_characters` 丢了尾部结果、丢了几条 |
| `content` | 同一份列表的 Markdown 版本（带链接），供模型直接引用 |
| `content_truncated` / `persisted_path` | 列表超出输出 token 预算时落盘的位置 |
| `duration_ms` | 一次搜索的耗时（含读响应） |

一条都没搜到时 `result_count` 为 `0`，`content` 是一句"没有结果，换个说法，不要重复同样的搜索"——**这不是错误**。若结果全被域名过滤吃掉，`content` 会换成另一句提示（放宽白名单 / 去掉黑名单），并带 `filtered_out`。

失败时是 `{"error": "<说明>", "reason": "<原因码>", ...}`，原因码：`invalid_argument` / `invalid_query` / `invalid_domain` / `conflicting_domain_filters` / `unsupported_provider` / `missing_api_key` / `timeout` / `connection_failed` / `tls_error` / `invalid_endpoint` / `request_failed` / `http_error` / `response_too_large` / `bad_response` / `provider_blocked`。`http_error` 额外带 `code` / `code_text` / `body`（响应正文的前 400 字符）。

## 后端与配置

后端是**部署配置**，不是工具参数：模型没有“换一个引擎重试”的能力，给它这个参数只会浪费一步。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_SEARCH_PROVIDER` | `duckduckgo` | 后端标识：`duckduckgo` / `tavily` / `serper` / `bing`。 |
| `WEB_SEARCH_API_KEY` | 空 | API 后端的密钥。`tavily` 放在请求体、`serper` 走 `X-API-KEY` 头、`bing` 走 `Ocp-Apim-Subscription-Key` 头。 |
| `WEB_SEARCH_BASE_URL` | 空 | 覆盖后端端点（公司网关、镜像或测试用）。整段替换，不是拼接前缀。 |
| `WEB_SEARCH_TIMEOUT_SECONDS` | `15` | 单次搜索总超时，上限 60 秒；连接超时固定 8 秒。 |
| `WEB_SEARCH_DEFAULT_NUM_RESULTS` | `8` | 模型没给 `num_results` 时的条数，上限 20。 |
| `TOOL_OUTPUT_MAX_TOKENS` | `25000` | 所有工具共用的输出预算；决定结果列表是否落盘。 |

默认后端是**无需密钥**的 DuckDuckGo HTML 端点，所以拿到仓库就能用。它有两个已知代价：解析的是页面结构（改版会失效），以及可能被机器人校验拦截——这两种情况都会以 `provider_blocked` / 空结果明确报回来，而不是假装"没有相关内容"。配置任意一个 API 后端可以获得稳定的结果质量。

请求头是一个固定的 `User-Agent`（`ngy-py-agent-web-search/0.1`）与常见的 `Accept` / `Accept-Language`。

## 规矩

- **一个任务问一次**：权限种类是 `read`，但目标不是文件路径，而是**这个工具本身**（`permissions.SEARCH_PERMISSION_TARGET`）。确认框显示 "Search the web: \<query\>"；选择"本任务允许"后，同一任务里的后续搜索不再询问。按 query 建规则会让用户为每个新问题重新点一次，那不是有用的粒度。
- **只读、可并行**：不改本地任何东西，多个搜索可以同时跑。
- **必须标来源**：结果里的 `content` 末尾有一句提醒，要求把用到的信息以 Markdown 链接标出来源。
- **域名过滤在本地再做一遍**：Tavily 支持原生域名过滤，其它后端不支持；两套行为不能不一样，所以过滤统一在 `providers.run` 里完成。
- **限制都如实上报**：`filtered_out`、`context_truncated`、`content_truncated` 分别对应“被过滤”“超字符上限”“超 token 预算”。不要把部分结果伪装成完整结果。

## 已知限制

- 不读页面正文：拿到的永远只有标题/网址/摘要，需要正文请 `web_fetch`。
- 不做 JavaScript 渲染、不翻页：一次调用只取后端给的第一页（`num_results` 条）。
- 不是安全边界：不发请求也做不到 DNS 层面的拦截；`exec_command` 本来就能访问同样的网络。
- 搜索质量取决于所选后端；`fast` / `deep` 只在 Tavily 上有效果。
