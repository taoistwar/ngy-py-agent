# ADR 0030: `vault_http` 工具的设计

- 状态：已接受（Accepted）
- 日期：2026-11-17
- 相关：`agent/tools/vault_http/`、`agent/tools/vault_store.py`、`agent/tools/permissions.py`、`agent/tools/web_urls.py`、`agent/tools/catalog.py`、`web-admin/src/components/admin/toolMeta.js`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0012](0012-tool-result-budget.md)（工具结果预算）、[ADR 0027](0027-web-fetch-tool.md)（`web_fetch`）、[ADR 0029](0029-web-browser-tool.md)（`web_browser`）

## 背景

`web_fetch` 明确不能认证：它拒绝内嵌凭证的 URL，只读公开页面。于是"调一个需要 token 的接口"在工具集里没有形状，模型只能退回：

- `exec_command`：`curl -H "Authorization: Bearer xxx"`；
- `code_interpreter`：`requests.get(url, headers={"Authorization": ...})`。

两条路都把密钥写进**工具调用参数**。参数会进入 `messages`、任务事件、`tool-calls` 明细与工作空间里的会话记录——一次调用泄漏的是长期有效的凭证，而模型此后也能反复引用它。参考实现（Claude Code 的 `VaultHttpFetchTool`）用一句话解决：**只给钥匙的名字，不给密码本体**。本 ADR 记录把它搬进本仓库时的取舍。

## 决策

### D1. 密钥按名字引用，存在本地文件里

- 工具参数是 `vault_auth_key`（1–128 位字母、数字、`.`、`_`、`:`、`-`），不是密钥。
- 保险柜是 `data/vault.json`（`VAULT_SECRETS_PATH` 可改路径），格式 `{"secrets": {"<名字>": "<值>"}}`；裸映射也接受，因为那是人手写的形状。`data/` 已在 `.gitignore` 里，与 `permission_rules.json` 同一处置。
- **每次查询都重读文件**，不缓存：密钥轮换与新增必须下一步就生效，缓存会让"我改了文件却还在用旧值"变成一个无法解释的失败。
- 读取失败分两种，因为修法不同：文件不存在/读不了/JSON 坏 → `vault_unavailable`；文件正常但没有这个键 → `secret_not_found`，错误里列出**存在的键名**（模型本来就在猜名字），绝不列值。

### D2. 权限种类是 `vault`，目标是 `key@host[:port]`

`read` 的目标是文件路径或主机名，两者都不足以表达"这把钥匙能不能发到这个服务"：

- 参数名是 `url`，但真正被批准的是"这把钥匙可以发给这个主机"，所以 `_target` 返回 `gh-token@api.example.com`；
- 端口属于目标：`api.example.com:8443` 与 `api.example.com` 是两个服务，规则不能互相覆盖（`web_urls.FetchUrl.authority` 因此新增）；
- 只有 `https://` 才产生目标：明文调用会被工具直接拒绝，为不可能的调用弹框等于提供一个无法兑现的选项（与 ADR 0006 D9 同一条理由）；
- 规则键含工具名，所以这条例行批准不会外溢到 `web_fetch` / `web_browser`；
- 确认框的文案是 `Send GET to api.example.com with vault key gh-token`，`details` 里有 `url` / `method` / `vault_auth_key` / `auth_scheme` / `auth_header_name` / `purpose`（用户给的 `reason`）/ `body`。`details.reason` 仍是机器码 `network_vault`，与网络读取的 `network_fetch` 保持同一约定。

### D3. `auto_approve` 也要问（`ToolSpec.always_confirm`）

参考实现把这个标记叫 bypass-immune。理由不是洁癖：`auto_approve` 是"这次任务里的确认别烦我"，它不可能是"我已经想过这把钥匙发给这个域名"这个判断。所以：

- `ToolSpec.always_confirm = True` → `ToolRegistry` 传给 `PermissionBroker.check(always_ask=True)` → `AUTO_APPROVE` 分支被跳过；
- `DENY_ALL` 仍然不问直接拒；`always` 规则仍然命中就放行（那是用户针对这个 `key@host` 真的做过的决定）；
- 代价：无人值守 + `auto_approve` 的任务会在 120 秒超时后被拒。这是正确方向——拒绝会说清原因，自动放行不会。

### D4. 只 https，不跟重定向

- 明文 HTTP 在**校验阶段**就拒绝（`https_required`），保险柜还没打开。
- `allow_redirects=False`，30x 原样返回，`redirect_to`（Location，已擦除）+ 正文里一段 `REDIRECT NOT FOLLOWED` 说明。跟过去的后果是把密钥交给一个没批准过的域名；让模型另发一次调用则重新走一遍 `key@host` 确认。
- 同域跳转也不跟：这个工具不是浏览器，一次调用就是一次被批准的请求。

### D5. 擦除是结果的一部分，不是可选项

一次调用的密钥出现在四处：请求头、响应正文、响应头、报错文本。统一用 `scrub.variants_of(secret)` 生成的变体清单做替换（`[REDACTED]`）：

- 原值、URL 编码（两种 safe 集合）、base64（含去 padding）、base64 的 URL 编码、JSON 转义；
- `user:password` 形式的密钥额外擦除两半（basic 认证失败时服务端常引述其中一个）；
- 变体按长度倒序替换，避免 base64 形式被原值的前缀切碎；
- 请求失败时，异常消息与 `details` 里的字符串同样过一遍（`requests` 的报错可能引述它正在构造的请求）。

擦除**不是安全边界**：模型仍然可以 `exec_command curl`。它保证的是这个工具的输出、以及由此进入上下文与事件流的文本不含密钥。

### D6. 参数是封闭集合，校验在发请求之前

接受且只接受八个参数（`url`、`vault_auth_key`、`reason`、`method`、`auth_scheme`、`auth_header_name`、`body`、`body_content_type`）。多传或拼错的参数返回 `unknown_argument` 并列全部合法参数名——静默忽略一个拼错的 `auth_header` 会让密钥以错误的头发出去，表现为一个莫名其妙的 401。

- `method` 白名单 `GET/POST/PUT/PATCH/DELETE`，默认 `GET`；
- `auth_scheme` 白名单 `bearer`（默认）/`basic`/`header_x_api_key`/`custom`；`custom` 必填 `auth_header_name`，其他取值下给了它会报错；头名限 `[A-Za-z0-9_-]{1,64}`，且不允许 `host`、`content-length`、`transfer-encoding`、`connection` 这类报文框架头；
- `basic` 发送 `Authorization: Basic base64(<密钥>)`，因此保险柜里存的是 `user:password`；
- `body` 允许 POST/PUT/PATCH/DELETE，GET 拒绝（服务端要么忽略要么报错，两种都是"数据没送到"）；
- `reason` 1–500 字符，进确认框与审计日志。

### D7. 上限、预算与错误语义

- 正文 1 MiB，边读边截，`response_truncated` 为真时正文追加一行说明（不静默截断）；
- 超时默认 20 秒（`VAULT_HTTP_TIMEOUT_SECONDS`，上限 120），连接超时 10 秒；
- 正文超出输出 token 预算时落盘（`vault-*.txt`）并给 `persisted_path`，与 `exec_command` / `web_fetch` 同一契约；
- **HTTP ≥ 400 不是工具失败**：401/403/500 的正文通常正是模型需要的解释，所以照常返回 `status` / `body`；只有"没拿到回答"（保险柜、连接、TLS、超时）才是 `{"error", "reason"}`；
- 失败是返回值而不是异常，否则 loop 会把这一步标成失败，模型会当成工具坏了去重试。

### D8. 分类、顺序与模式

- 分类 `network`（管理页"网络访问"）。
- 顺序在 `web_browser` 之后、`read_file` 之前：同一"访问 URL"家族里，能登录的那个紧跟公开读取器。
- **不加入 `ask` 模式**：它会带凭证改变远端状态，不是只读工具。`build` 通过 `tool_names=None` 自动获得。
- 管理页只多一个确认种类标签（`toolPermissionVault`，六种语言）。**没有密钥管理界面**：保险柜是运维手里的文件，给它做增删改查会引入"谁能看值"的问题，而那正是这个工具想避开的。

## 后果

- 模型看到：`status` / `status_text` / `response_headers`（已擦除）/ `body`（已擦除）/ `bytes` / `duration_ms` / `encoding` / `response_truncated` / `redirect_to` / `body_truncated` / `persisted_path` / `original_tokens`，以及 `url` / `method` / `vault_auth_key` / `auth_scheme` 便于对账。
- 原因码：`invalid_argument` / `unknown_argument` / `missing_argument` / `https_required` / `body_not_allowed` / `invalid_url` / `unsupported_scheme` / `credentials_in_url` / `secret_not_found` / `vault_unavailable` / `timeout` / `tls_error` / `connection_failed` / `request_failed`。
- 新增共享模块 `agent/tools/vault_store.py`（工具包之间不许互相 import，而权限门与未来的运维接口都可能要列出键名）与 `web_urls.https_authority_of`（工具与权限门必须对"这是哪个 `host[:port]`"给同一个答案）。
- `data/vault.json` 被加进 `permissions._SENSITIVE_NAMES`：`read_file` 读它要先问用户——否则手工读一次，工具辛苦擦掉的东西就又进了上下文。
- **不是安全边界**：不拦私网、不做 DNS 解析、不阻止 `exec_command`。真正的隔离在网络层，这一层能提供的全部保护是"密钥不在上下文里"与"发到哪个主机要人点头"。
- 已有数据库里的内置 `ask` 智能体不会自动获得新工具（`_seed_default_agents` 只补空字段），需要在管理页添加；`build` 自动获得。
