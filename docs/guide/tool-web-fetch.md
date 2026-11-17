# 工具：`web_fetch`（读取网页）

给模型一个网址，它把页面抓回来、转成可读文本。HTML 变成 Markdown 风格文本，纯文本/JSON/XML 原样返回，其它类型（PDF、图片、压缩包）存盘后给出路径。它**只读**：不改工作空间里的任何文件。

`build` 与 `ask` 模式可用（`ask` 是只读模式）；`plan` 模式没有工具。取舍见 [ADR 0027](../decisions/0027-web-fetch-tool.md)。

## 参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `url` | string（必填） | 完整的 `http://` 或 `https://` 地址。只接受这两种协议；内嵌用户名或密码（`http://user:pw@host/`）会被拒绝；空格按 `%20` 编码，`#fragment` 被丢弃。 |

没有 `prompt` 参数——参考实现用第二个模型按 `prompt` 提炼答案，本仓库不在工具里调模型，原因见 ADR 0027 D1。需要结论时，模型自己从正文里得出。

## 返回

成功时是一张"回执单"：

| 字段 | 含义 |
| --- | --- |
| `content` | 正文（HTML 已转成 Markdown 风格文本）。超预算时是预览 + 落盘路径。 |
| `url` | 实际抓取的地址（跟随过同域跳转后） |
| `requested_url` | 调用时给的地址 |
| `code` / `code_text` | HTTP 状态码与文字（`200` / `OK`） |
| `content_type` / `media_type` / `encoding` | 响应头里的类型、归一化后的类型、实际解码用的编码 |
| `bytes` | 抓回的字节数 |
| `duration_ms` | 含跳转与读正文的耗时（毫秒） |
| `redirected` | 是否发生过同域跳转 |
| `response_truncated` | 是否在 2 MiB 上限处被截断 |
| `content_truncated` / `persisted_path` / `original_tokens` | 正文是否超预算、全文落在哪个文件、原文字数对应的 token 估算 |
| `title` | 页面的 `<title>`（HTML 才有） |

跨域跳转时没有正文，改为 `redirect_to`：

```json
{
  "url": "http://example.com/old",
  "code": 302,
  "redirected": true,
  "redirect_to": "https://other.example/new",
  "content": "REDIRECT DETECTED: ..."
}
```

失败时是 `{"error": "<说明>", "reason": "<原因码>", ...}`，原因码：`invalid_argument` / `invalid_url` / `unsupported_scheme` / `credentials_in_url` / `timeout` / `connection_failed` / `tls_error` / `request_failed` / `http_error` / `bad_redirect` / `too_many_redirects`。`http_error` 额外带 `code` 与 `code_text`。

## 规矩

- **第一次访问某个域名要确认**：权限种类是 `read`，确认框显示 "Fetch \<主机\>" 与完整地址；选择"本任务允许"后，同一主机的后续页面不再询问。子域是另一个目标（`evil.example.com` 与 `example.com` 各自确认），URL 不合法的调用不会弹框（工具自己会报错）。
- **同域跳转自动跟随**（最多 5 跳，`http`↔`https`、换端口都算同域）；**跨域不跟随**，而是把新地址交还给模型另发一次调用——新站点需要单独批准。
- **2 MiB 正文上限**：超出即截断，`response_truncated` 会说明。
- **HTTP ≥ 400 是失败**，不是正文：登录页、403、404 都会以 `http_error` 返回，模型应当把状态告诉用户而不是反复重试。
- **需要登录的页面抓不到**：结果是登录页或一个 HTTP 错误，换认证类工具（MCP）才行。
- **正文为空会说清楚**：靠 JavaScript 渲染、或本来就是空页面，返回一段固定文案，不返回空字符串。

## 大页面与二进制

- 正文超出输出 token 预算（`TOOL_OUTPUT_MAX_TOKENS`，默认 25000）时，全文写到本次运行的临时输出目录（`<temp>/ngy-py-agent/output/<workspace>/<scope>/fetch-*.md`），`content` 只留头部预览与提示；用 `read_file` 的 `offset` / `limit` 分段读回，`read_file` 会加行号前缀。该目录对文件工具**可读不可写**。
- PDF、图片、压缩包等写到同一目录（原字节不变，`fetch-*.pdf` 之类），结果给 `persisted_path`。工具不解析 PDF——需要正文时用 `code_interpreter` 处理该文件，或换带 PDF 能力的工具。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_FETCH_TIMEOUT_SECONDS` | `20` | 单次抓取的总超时（含跳转与读正文），上限 120 秒。连接超时固定 10 秒。 |
| `TOOL_OUTPUT_MAX_TOKENS` | `25000` | 所有工具共用的输出预算；决定正文是否落盘。 |

请求头是一个固定的 `User-Agent`（`ngy-py-agent-web-fetch/0.1`）与常见的 `Accept` / `Accept-Language`；不做伪造，也不带 cookie——需要登录的内容本来就抓不到。

## 已知限制

- 不执行 JavaScript：靠前端渲染的页面只会拿到底壳。
- 不解析 PDF、docx 等二进制格式，只落盘。
- 站点框架按 `<nav>` / `<footer>` / `role="navigation|banner|contentinfo"` 丢弃；把正文写进这些标签的站点会丢内容。
- 不做私网地址拦截：`http://127.0.0.1:8001/` 这类地址照常可抓。它不是沙箱（`exec_command` 本来就能访问同样的网络）。
