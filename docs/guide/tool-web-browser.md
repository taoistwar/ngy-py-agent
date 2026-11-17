# 工具：`web_browser`（用"文字浏览器"打开网页）

给模型一个网址，它把页面下载下来、去掉标签，交回 **标题 + 最终地址 + 纯文本**——就像一个只有文字的浏览器。它**只读**：不改工作空间里的任何文件。

它不是真的浏览器：**不执行 JavaScript、不能点击/输入/滚动、不能截图**。取舍见 [ADR 0029](../decisions/0029-web-browser-tool.md)。

`build` 与 `ask` 模式可用；`plan` 模式没有工具。

## 参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `url` | string（必填） | 完整的 `http://` 或 `https://` 地址。只接受这两种协议；内嵌用户名或密码（`http://user:pw@host/`）会被拒绝；空格按 `%20` 编码，`#fragment` 被丢弃。 |
| `action` | string（可选） | `navigate`（默认）打开页面并返回正文；`screenshot` 返回**同一份正文**，并在开头加一句说明"没有截取画面"。传入其它值直接报 `invalid_argument`，不猜默认值。 |

## 返回

成功时：

| 字段 | 含义 |
| --- | --- |
| `title` | 页面的 `<title>`；非 HTML 页面为空字符串 |
| `url` | 实际落地的地址（跟随过同域跳转后） |
| `action` | 本次使用的动作 |
| `content` | 正文纯文本；超 5 万字符会被截断；超输出预算时是预览 + 落盘路径 |
| `truncated` | 是否触到 50,000 字符上限（此时 `content` 以 `[truncated]` 结尾） |
| `content_truncated` / `persisted_path` / `original_tokens` | 是否因输出 token 预算落盘、全文落在哪个文件、原文字数对应的 token 估算 |

失败时是 `{"error": "<说明>", "reason": "<原因码>", "title": "<HTTP 404 或 Error>", "url": "..."}`。原因码：`invalid_argument` / `invalid_url` / `unsupported_scheme` / `credentials_in_url` / `timeout` / `connection_failed` / `tls_error` / `request_failed` / `http_error` / `bad_redirect` / `too_many_redirects` / `cross_host_redirect` / `not_text`。

失败也带 `title`，是因为参考实现把失败写成"页面标题"（`HTTP 404`、`Error`），那确实是浏览器标签页上的样子；但只有标题不够，所以 `error` / `reason` 同时存在。

```json
{
  "error": "REDIRECT DETECTED: http://example.com/old answered 302 and points at a different host: https://other.example/new. ...",
  "reason": "cross_host_redirect",
  "title": "Redirected to another host",
  "url": "http://example.com/old",
  "redirect_to": "https://other.example/new",
  "code": 302
}
```

## 与 `web_fetch` 的分工

两个工具都能打开一个网址，区别是"交回来什么"：

| | `web_fetch` | `web_browser` |
| --- | --- | --- |
| 结果形态 | 回执单：状态码、字节数、耗时、类型、编码 + 正文 | 三件事：标题、最终地址、正文 |
| HTML | 转成 Markdown 风格文本（标题/列表/链接/代码块/表格行） | 剥成纯文本（列表保留 `- ` 与缩进，链接地址、代码围栏、表格竖线不保留） |
| 长度上限 | 2 MiB 正文 + 输出 token 预算 | 50,000 字符 + 输出 token 预算 |
| 非文本内容 | 原字节存盘并给路径 | 报 `not_text`（要看字节用 `web_fetch`） |
| 适合 | 需要状态/类型/编码、需要结构、需要下载 | 只想读页面说了什么 |

## 规矩

- **第一次打开某个域名要确认**：权限种类是 `read`，确认框显示 "Browse \<主机\>" 与完整地址；选择"本任务允许"后，同一主机的后续页面不再询问。URL 不合法的调用不会弹框（工具自己报错）。
- **`web_fetch` 与 `web_browser` 各自计权限**：同一任务里先 `web_browser` 后 `web_fetch` 访问同一站点会问两次。这是刻意的保守方向——"允许读这个站"与"允许用另一种方式读这个站"不是同一句话。
- **同域跳转自动跟随**（最多 5 跳，`http`↔`https`、换端口都算同域）；**跨域不跟随**，返回 `cross_host_redirect` + `redirect_to`，由模型另发一次调用，让新站点单独获批。
- **50,000 字符上限**：超出即截断，`truncated` 为真，正文以 `[truncated]` 结尾。**不静默截断**。
- **2 MiB 正文上限**：读的时候边读边截，正文末尾追加一行说明。
- **HTTP ≥ 400 是失败**，不是正文：登录页、403、404 都以 `http_error` 返回。
- **需要登录的页面抓不到**：结果是登录页或一个 HTTP 错误，换认证类工具（MCP）才行。
- **空正文会说清楚**：靠 JavaScript 渲染、或本来就是空页面，返回一段固定文案，不返回空字符串。
- **`screenshot` 不假装**：它返回的是同一份文本快照，开头写明没有画面。真正的截图是 `computer_observe` 的职责（桌面窗口），它也不渲染网页。

## 大页面

正文超出输出 token 预算（`TOOL_OUTPUT_MAX_TOKENS`，默认 25000）时，全文写到本次运行的临时输出目录（`<temp>/ngy-py-agent/output/<workspace>/<scope>/browse-*.txt`），`content` 只留头部预览与提示；用 `read_file` 的 `offset` / `limit` 分段读回。该目录对文件工具**可读不可写**。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_BROWSER_TIMEOUT_SECONDS` | `20` | 单次打开的总超时（含跳转与读正文），上限 120 秒。连接超时固定 10 秒。 |
| `TOOL_OUTPUT_MAX_TOKENS` | `25000` | 所有工具共用的输出预算；决定正文是否落盘。 |

请求头是固定的 `User-Agent`（`ngy-py-agent-web-browser/0.1`）与常见的 `Accept` / `Accept-Language`；**不冒充 Chrome**，也不带 cookie——需要登录的内容本来就抓不到。

## 已知限制

- 不执行 JavaScript：靠前端渲染的页面只会拿到底壳。
- 纯文本会丢信息：链接只剩锚文本，代码块没有围栏，表格靠空格分隔。需要结构就用 `web_fetch`。
- 不解析 PDF、图片等二进制内容，只报 `not_text`。
- 站点框架按 `<nav>` / `<footer>` / `role="navigation|banner|contentinfo"` 丢弃；把正文写进这些标签的站点会丢内容。
- 不做私网地址拦截：`http://127.0.0.1:8001/` 这类地址照常可打开。它不是沙箱（`exec_command` 本来就能访问同样的网络）。
