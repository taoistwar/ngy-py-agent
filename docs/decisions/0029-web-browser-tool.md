# ADR 0029: `web_browser` 工具的设计

- 状态：已接受（Accepted）
- 日期：2026-11-17
- 相关：`agent/tools/web_browser/`、`agent/tools/permissions.py`、`agent/tools/catalog.py`、`agent/modes.py`、`docs/guide/tool-web-browser.md`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0012](0012-tool-result-budget.md)（工具结果预算）、[ADR 0027](0027-web-fetch-tool.md)（`web_fetch`）

## 背景

参考实现是 Claude Code 的 `WebBrowserTool`（模型看到的名字是 `Browser`）：`url` + `action`（`navigate` / `screenshot`）→ 下载页面 → 剥掉标签 → 回 `title` / `url` / `content`，正文超 5 万字符截断。它是一个"假浏览器"：没有渲染引擎，也不跑 JavaScript。

本仓库已有 `web_fetch`（[ADR 0027](0027-web-fetch-tool.md)），能力是它的超集：Markdown 风格转换、HTTP 回执、二进制落盘、编码探测。但 `web_fetch` 的**结果形状**是为诊断设计的：模型只想读一段正文时，要先越过 6 个回执字段，并且在"这是页面说的"与"这是抓取的状态"之间自己对照。

所以要回答的问题不是"能不能抓"，而是"要不要第二种结果形状"。

## 决策

### D1. 与 `web_fetch` 并存，各自说清分工

两个工具都保留。分工写进各自的 `description`：`web_browser` 只说"标题 + 最终地址 + 纯文本"，并在描述里点名"要结构 / 状态 / 编码 / 下载请用 `web_fetch`"。

代价是模型在工具列表里看到两个相似的读取工具。收益是选择依据来自描述，而不是一次试错；要求合并的直觉被明确否决——合并意味着两边的取舍都要重新谈一遍（结构 vs 简单、回执 vs 简洁）。

### D2. 权限沿用 `read` + 主机名，但**按键分开**

`permissions.NETWORK_READ_TOOLS` 加入 `web_browser`，目标仍是 `web_urls.host_of(url)` 返回的主机名；确认框文案是 "Browse \<主机\>"（`reason=network_browse`），与 `web_fetch` 的 "Fetch \<主机\>"（`reason=network_fetch`）区分。

规则键是 `(工具名, 主机名)`，**不合并**两个工具的批准：

- 合并会让"允许读 example.com"隐式放大成"允许两种读取路径都跑"；用户点的是哪个按钮，规则就该记住哪件事；
- 合并还要迁移已经存下的规则键，收益不足。

代价：同一任务里先用 `web_browser` 再用 `web_fetch` 访问同一站点会问两次。`session` / `always` 两种范围都能缓解；这是一个明确选择过的摩擦，不是遗漏。

### D3. 重定向只跟随同域，不照抄参考实现

参考实现的 `redirect: follow` 会跟到任何站点。这里不跟：

- 跨域是另一个权限目标，跟过去等于绕过 D2；
- "把新地址交还给模型，让它另发一次调用"正是参考实现之后的动作，模型不需要猜。

规则与 `web_fetch` 完全一致：同域（主机名相等，协议与端口可不同）最多 5 跳，跨域回 `cross_host_redirect` + `redirect_to`，跳数用尽报 `too_many_redirects`。

### D4. 输出是纯文本，不是第二份 Markdown

`snapshot.py` 把 HTML 变成纯文本：块级元素之间空一行，列表项 `- ` + 两级缩进，`<pre>` 保留缩进，其它空白折叠。

不重复 `web_fetch` 的 Markdown 转换，理由不是省代码，而是**两个都输出 Markdown 的转换器就是同一个转换器起了两个名字**：模型无法据此选择，维护者要同时改两处。丢掉的东西（链接地址、代码围栏、表格竖线）正是 `web_fetch` 存在的理由。

丢弃集合与 `web_fetch` 同源：`script` / `style` / `noscript` / `template` / `svg` / 表单控件 / `hidden` / `aria-hidden="true"` / `nav` / `footer` / `role="navigation|banner|contentinfo"`。参考实现靠"浏览器只显示可见文本"天然做到这件事，这里没有渲染引擎，只能在解析层丢。

### D5. 两层上限，都不静默

- **50,000 字符**：参考实现的上限，超出即截断，`truncated` 为真，正文以 `[truncated]` 结尾；
- **输出 token 预算**：本项目的统一契约，超出就把全文写到本次运行的临时目录（`browse-*.txt`），结果是预览 + `persisted_path`。

两层都保留，是因为它们防的是不同的东西：字符上限防止一次调用吃掉过多上下文，token 预算保证结果永远不会比 loop 允许的更大（小预算的 run 可能在 5 万字符以内就落盘）。

### D6. `action=screenshot` 保留，但不假装

参考实现里这个动作只是把同一份正文再回一遍，前面加一句"visual screenshots require Chrome browser tools"，字段 `screenshot` 从未赋值。

这里保留参数（它是参考契约的一部分，模型会按名字调用），但把承诺写清楚：返回同一份文本快照 + 一句"没有截取画面"。**不**伪造一张图，也**不**把它接到 `computer_observe`：截图工具拍的是桌面窗口，不是网页渲染结果，接上去只会制造"我截了图"的错误印象。

### D7. 失败也带 `title`，同时保留 `error` / `reason`

参考实现把失败写成页面标题（`HTTP 404`、`Error`），`content` 里放错因。这里两者都要：

- `error` / `reason` 与文件工具、`web_fetch` 同形，loop 与 UI 才能按同一个约定处理失败；
- `title` 让"这次导航落在哪"这个浏览器语义保持完整。

### D8. 不冒充 Chrome

参考实现用 Chrome 的 User-Agent。这里沿用 [ADR 0027](0027-web-fetch-tool.md) 的判断：请求头写 `ngy-py-agent-web-browser/0.1`。站点运营者在日志里看到谁来了，比多骗过一个 UA 检查更有价值；需要绕过反爬的抓取本来就不是这个工具的职责。

### D9. 分类、顺序与模式

- 分类沿用 `network`（`spec.CATEGORY_NETWORK`），前端无需改动；
- 顺序排在 `web_fetch` 之后：同一个"打开网页"家族里，契约更完整的一个先出现；
- `ask` 模式（只读）加入允许列表；`build` 是 `tool_names=None`，自动包含；`plan` 仍然没有工具。

## 后果

- 模型拿到两套网页读取工具，靠描述里的分工选择：`web_browser` 简单视图，`web_fetch` 诊断视图。
- 权限规则按工具分开：同一站点换工具会再问一次（D2）。这是刻意的方向，不要为了少点一次框去合并规则键。
- 工具包之间不许互相 import（`agent/tools/__init__.py`），所以 `web_browser` 自带一份 HTTP 管道（`fetch.py`）与纯文本转换（`snapshot.py`）。这与 `web_search/http.py` 是同一先例：约 150 行传输层代码重复，换掉它需要把 `web_fetch` 的抓取层提到包根并迁移既有测试，本次不做。
- 不执行 JavaScript；不解析 PDF；不做私网地址拦截（与 `web_fetch` 相同，它不是安全边界）。
- 已有数据库里的内置 `ask` 智能体不会自动获得新工具（`_seed_default_agents` 只补空字段），需要在管理页添加；`build` 自动获得。
