# 工具：`vault_http`（带保险柜密钥的 HTTPS 请求）

给模型一个接口地址和**钥匙的名字**，它从本地保险柜取出密钥、挂到请求上、把响应交回来，并保证密钥不会出现在结果里。适合调需要 token / API key / Basic 认证的接口；读公开网页用 [`web_fetch`](tool-web-fetch.md)。

`build` 模式可用；`ask` 模式**没有**它（会带凭证改变远端状态，不是只读工具）；`plan` 模式没有工具。取舍见 [ADR 0030](../decisions/0030-vault-http-tool.md)。

## 先把密钥放进保险柜

保险柜是一个 JSON 文件，默认 `data/vault.json`（`VAULT_SECRETS_PATH` 可改路径）。`data/` 已在 `.gitignore` 里，不会进仓库。

```json
{
  "secrets": {
    "gh-token": "ghp_xxxxxxxxxxxxxxxx",
    "billing-api": "sk_live_xxxxxxxx",
    "legacy-basic": "ada:s3cret"
  }
}
```

- 键名就是模型要引用的 `vault_auth_key`；值是密钥本体。
- 改完即可生效：每次调用都重读文件，不需要重启。
- `basic` 认证要写成 `用户名:密码`，因为线上格式是 `base64(用户名:密码)`。
- 值必须是字符串；空值、对象、数字会被跳过（并在报错里表现为"没有这个键"）。

## 参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `url` | string（必填） | 完整的 `https://` 地址。`http://` 与其他协议直接拒绝；内嵌用户名/密码的地址也拒绝。 |
| `vault_auth_key` | string（必填） | 保险柜里的键名，1–128 位字母、数字、`.`、`_`、`:`、`-`。**不是密钥本体**。 |
| `reason` | string（必填） | 为什么要这次请求，1–500 字符。显示在确认框与审计日志里。 |
| `method` | string（可选） | `GET`（默认）/ `POST` / `PUT` / `PATCH` / `DELETE`。 |
| `auth_scheme` | string（可选） | `bearer`（默认）→ `Authorization: Bearer <密钥>`；`basic` → `Authorization: Basic base64(<密钥>)`；`header_x_api_key` → `X-Api-Key: <密钥>`；`custom` → `auth_header_name` 指定的头。 |
| `auth_header_name` | string（可选） | 仅 `auth_scheme=custom` 时必填，其他取值下会报错。1–64 位字母、数字、`_`、`-`；`host`、`content-length` 这类报文框架头不允许。 |
| `body` | string（可选） | 请求正文，按 UTF-8 发送。可用于 `POST`/`PUT`/`PATCH`/`DELETE`；`GET` 会被拒绝。 |
| `body_content_type` | string（可选） | `body` 的 Content-Type，默认 `application/json`（最长 128 字符）。 |

参数是**封闭集合**：多传或拼错的参数不会被忽略，而是返回 `unknown_argument` 并列出全部合法参数名。

```json
{
  "url": "https://api.example.com/v1/users",
  "vault_auth_key": "gh-token",
  "reason": "拉取用户列表以核对工单",
  "method": "GET"
}
```

## 返回

成功时是一张回执单：

| 字段 | 含义 |
| --- | --- |
| `status` / `status_text` | HTTP 状态码与文字（`200` / `OK`） |
| `response_headers` | 响应头（**已擦除**），条数与单值长度都有上限 |
| `body` | 响应正文（**已擦除**）；超预算时是预览 + 落盘路径 |
| `url` / `method` / `vault_auth_key` / `auth_scheme` | 这次调用实际用的是什么，便于对账 |
| `bytes` / `duration_ms` / `encoding` | 字节数、耗时、解码用的编码 |
| `response_truncated` | 是否在 1 MiB 上限处被截断 |
| `body_truncated` / `persisted_path` / `original_tokens` | 正文是否超预算、全文落在哪个文件 |
| `redirect_to` | 服务器要求重定向时的目标（**未跟随**） |

失败时是 `{"error": "<说明>", "reason": "<原因码>", ...}`，原因码：`invalid_argument` / `unknown_argument` / `missing_argument` / `https_required` / `body_not_allowed` / `invalid_url` / `unsupported_scheme` / `credentials_in_url` / `secret_not_found` / `vault_unavailable` / `timeout` / `tls_error` / `connection_failed` / `request_failed`。

**HTTP 4xx/5xx 不算失败**：401、403、500 的正文通常正是需要的解释，所以照常返回 `status` 与 `body`。只有"没拿到回答"（保险柜、连接、TLS、超时）才是 `error`。

## 规矩

- **只走 HTTPS**：明文目标在校验阶段就拒绝，保险柜还没被打开。
- **不跟重定向**：30x 原样返回，`redirect_to` + 正文里的 `REDIRECT NOT FOLLOWED` 说明。要新地址就另发一次调用，让新主机单独获得授权。
- **密钥只在请求里**：结果正文、响应头、错误文本里的密钥都会被替换成 `[REDACTED]`；原始值、URL 编码、base64、JSON 转义，以及 `user:password` 的两半都算在内。
- **每次都要人点头**：权限种类是 `vault`，确认框显示 `Send GET to api.example.com with vault key gh-token` 与 `purpose`。批准绑定的是"钥匙名 + `host[:port]`"：换个域名、换个端口、换把钥匙都要重新问。
- **自动批准也照问**：即使任务被配置为 `auto_approve`，这个工具仍然弹框（`always_confirm`）。无人值守时会在超时后被拒，并告诉模型不要重试。
- **`deny_all` 仍然直接拒**，不会弹框。

## 排错

- `vault_unavailable`：文件不存在 / 读不了 / JSON 坏了。检查 `data/vault.json`（或 `VAULT_SECRETS_PATH`），报错里带路径。
- `secret_not_found`：键名写错或值为空；报错里列出**存在**的键名。
- `https_required`：把 `http://` 改成 `https://`，或换一个支持 TLS 的地址。
- 需要看完整响应但被落盘：用 `read_file` 读 `persisted_path`，`offset` / `limit` 分段。
