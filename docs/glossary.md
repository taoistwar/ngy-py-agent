# 术语表（Glossary）

本仓库共用的领域术语。按主题分组；每条给出定义与定义位置，避免同一概念在不同文件里叫不同名字。

## Agent 运行时

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **ReAct 循环** | Agent 的主循环：请求模型 → 解析工具调用 → 执行工具 → 把结果回填到消息列表 → 继续，直到模型不再调用工具或达到步数上限。 | `agent/agent_loop/` |
| **`base_dir` / 工作空间根** | 当前会话绑定的本地根目录。相对路径以它为基准解析，且不得逃出该目录。为空表示**未绑定会话（unbound session）**。 | `agent/tools/file_access.py` |
| **未绑定会话** | 没有 `base_dir` 的会话。此时只剩下全局 `file_access` 策略生效，文件工具默认可以访问工作空间之外；**相对路径以"会话默认目录"为起点**。 | `agent/tools/file_access.py` |
| **会话默认目录（`default_workspace`）** | 未绑定会话里相对路径的起点：`<程序启动路径>/data/default_workspace`（`DEFAULT_WORKSPACE_DIR` 可覆盖）。**是基目录不是边界**——`..` 仍可离开，全局策略照旧生效。写入按需创建它，读取不创建。 | [ADR 0007](decisions/0007-default-workspace.md) |
| **`AGENTS.md`** | 工作区自带的项目规则文件（[agents.md](https://agents.md/) 格式：纯 Markdown、无 schema）。根目录那份全文进入系统提示词，子目录的只列成索引（最近者优先）；仅已绑定工作区读取。 | `agent/agents_md.py`、[ADR 0022](decisions/0022-agents-md.md) |
| **token 预算** | 单次工具输出允许占用的 token 上限，超限即报错而非截断。`read_file` 依赖它防止撑爆上下文。 | `agent/tools/token_budget.py` |
| **行号前缀** | `read_file` 输出中每行开头的 `N<分隔符>`，分隔符是**制表符**。模型看不到真实行号，因此永远带前缀、不提供关闭开关。 | `agent/tools/read_file/lines.py` |
| **provider** | 一个请求去处：协议（openai / anthropic / anthropic_compatible / gemini）+ `base_url` + `api_key` + `rpm_limit`。Web Admin「Provider 管理」页维护，`/api/providers` 读写。删除前必须先清空它下面的模型。 | [ADR 0014](decisions/0014-provider-model-split.md) |
| **model** | 一个模型名（发给 provider 的 `model` 字段）加能力开关（工具调用 / 图片输入 / 思考 / token 上限），只通过 `provider_id` 关联到端点。地址、Key 与 RPM 不在这里。 | [ADR 0014](decisions/0014-provider-model-split.md) |
| **RPM 限流（`ProviderThrottle`）** | 按 **provider + base_url**（`bucket_key()`，地址经 `normalize_base_url` 规范化）分桶的每分钟请求上限，进程级单例、滑动窗口。超限的请求阻塞到有配额为止；等待超过 60 秒即抛 `RpmLimitError`（可见的失败，不是假死）。钩子在每个适配器的 `chat_completion` / `stream_chat_completion` 的 `_throttle()` 上，因此任务命名等旁路调用一并受限。配置只有数据库一层：provider 记录的 `rpm_limit`，启动时与每次 provider 写入后推给限流器。 | [ADR 0013](decisions/0013-llm-rpm-limit.md)、[ADR 0014](decisions/0014-provider-model-split.md) |
| **`llm.rpm.wait_ms`** | span 属性（同时有一条 `debug` 事件），记录这次请求为配额等待了多久。把"模型慢"与"自己被限流"分开，排障时才不会查错方向。 | [ADR 0013](decisions/0013-llm-rpm-limit.md) |

## 工具与结果

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **ToolSpec** | 工具的声明式定义：模型可见的 `name`、`description`、JSON Schema `parameters`、绑定的 `handler`，以及**权限种类** `permission`。 | `agent/tools/spec.py` |
| **工具包（tool package）** | 一个模型可见工具 = 一个包，**包名 = 工具名**（`exec_command/`、`write_stdin/`、`read_file/`…）。`__init__.py` 只做对外面（名称常量、`*_DESCRIPTION`、`*_PARAMETERS`、工厂），实现按职责分文件（`description.py`、`errors.py`、主题模块、`tool.py`）。共享基础设施（`permissions`、`file_access`、`process_store`…）留在 `agent/tools/` 根。 | `agent/tools/__init__.py` |
| **ToolRegistry** | 工具注册表：注册工具、把 schema 适配成各 provider 格式、按名分发调用。 | `agent/tools/registry.py` |
| **ToolBindings（工具绑定）** | 一次运行绑给工具的东西：`base_dir`、`session_id`（输出目录作用域）、`task_id`、`max_tokens`、`provider`/`model`、`output_directory`、`ledger`、`extra_read_roots`。每个工具包的 `build_spec(bindings)` 自取所需，所以新增工具不必给 registry 加参数。 | `agent/tools/bindings.py` |
| **工具目录（catalog）** | 内置工具的**唯一清单**，决定模型看到哪些工具、顺序如何：`build_all_specs(bindings)` 遍历各工具包的 `spec.py`。新增工具 = 新增一个包 + 在 `_BUILDERS` 加一行。 | `agent/tools/catalog.py` |
| **ToolOutcome** | **工具结果分流契约**。工具回调可返回它，携带 `model_text`（给模型）与可选事件类别/标题 + `details`（给 UI/外部消费者）。`execute_tool` 对其原样透传，由 `agent_loop` 拆分。 | `agent/models.py` |
| **双通道（dual channel）** | 一次工具调用产生两份输出：给**模型**的精简文本、给 **UI/外部消费者**的结构化记录。二者不再共用同一条消息。见 [ADR 0001](decisions/0001-file-edit-tool.md)。 | `agent/agent_loop/` |
| **`model_text`** | `ToolOutcome` 中回填进 `messages`（`role="tool"`）的文本，是模型实际"看到"的内容。 | `agent/models.py` |
| **`details`** | `ToolOutcome` 中随事件发送的结构化负载，模型看不到。 | `agent/models.py` |
| **tool_result 预算（tool result budget）** | **一步**的全部工具结果允许占用的字符上限，默认 200,000（`TOOL_RESULT_BUDGET_CHARS` 覆盖，`<= 0` 关闭）。超出时按大小降序把结果移出上下文，只留路径 + 2,000 字符预览。只处理**最新一批**（本步追加的消息）。与 **token 预算**分工不同：后者管单条工具输出，前者管整轮批量。 | [ADR 0012](decisions/0012-tool-result-budget.md) |
| **大结果落盘 / 占位文本（`<persisted-output>`）** | 超过 `TOOL_RESULT_LARGE_CHAR_LIMIT`（默认 30,000 字符）的结果整份写进 `<workspace>/.ngy-agent/.task_outputs/tool-results/<tool_call_id>.txt`，消息里换成 `<persisted-output>` 路径 + 预览。目录是**只读根**（`read_file` 读得到，`write_file`/`edit_file` 报 `read_only_root`），自带 `*` 的 `.gitignore`，**不自动清理**。与 `persistedOutputPath`（`exec_command` 落在 temp 的那棵树）是两处不同的树。 | [ADR 0012](decisions/0012-tool-result-budget.md) |
| **snip_compact（对话窗口裁剪）** | 每步开始时若消息数超过 `TRANSCRIPT_MAX_MESSAGES`（默认 50），把**完整历史**写进 `.ngy-agent/.transcripts/`，然后原地替换为「前 3 条 + 归档标记 + 最近若干条」。切点绝不落在一次工具调用内部（head 扩展会从尾部扣，tail 回退会让窗口略微超限）。写盘失败则不压缩；归档不足 `MIN_ARCHIVED_MESSAGES = 5` 条时等下一步（窗口可在 50→55 徘徊）。压缩后自检配对，发现孤儿只报 `error` 不阻断。与 **tool_result 预算**正交：它管条数，后者管字节。 | [ADR 0015](decisions/0015-snip-compact.md) |
| **归档标记 / transcript** | 替换掉被删区间的那条 `user` 消息（两行：条数 + `.ngy-agent/.transcripts/transcript-<时间戳>-<随机>.jsonl` 绝对路径 + 回读提示）。transcript 是 **JSONL**（一行一条消息），内联截图被换成占位，目录是只读根、不自动清理；每次压缩写一个新快照，不覆盖上一个。 | [ADR 0015](decisions/0015-snip-compact.md) |
| **micro_compact（上下文微型压缩）** | 压缩管线第三步，也是**第一步有条件的步骤**（但**不调用模型**）：`step` 开头估算整段上下文的字符量，超阈值（默认 200,000，可由 `CONTEXT_CHAR_LIMIT` / 模型 `max_input_tokens` 决定）才把**模型已读过**的旧工具结果换成单行路径，压缩到阈值的 80% 为止。保留最近 3 条已读结果；不够 120 字符或已是 `<persisted-output>` 的跳过。原地改写 `messages`，每轮一条 `debug` 事件。 | [ADR 0016](decisions/0016-micro-compact.md) |
| **fit_tool_results（未读结果适配）** | `micro_compact` 之后仍超限时的补刀：只处理**未读**结果（`seen` 集合里没有），按大小降序把最大的落盘，留 `<persisted-output>` + 1,000 字符预览 + 路径。与 **micro_compact** 的分工是"已读可换路径，未读必须留预览"：模型还没看到它，只给路径等于让它盲读。 | [ADR 0016](decisions/0016-micro-compact.md) |
| **compact_history（历史摘要压缩）** | 压缩管线第四步，也是**唯一会发起模型调用**的步骤：`prepare_context` 仍返回 `still_over` 时才进入。先归档 transcript，再把**将被删掉的旧历史**交给模型生成事实性摘要（`Goal / Decisions / Files / Done / Remaining / User constraints`），最后原地替换为 `system + [Compacted] 标记 + 最近 5 条`。有独立输入预算（单条 4,000 / 总量 `min(60k, 阈值/2)`）与**投影守卫**（摘要也救不回来就跳过，绝不每步调用一次）。失败或空摘要一律不压缩，历史原样保留。`CONTEXT_SUMMARY_ENABLED=0` 关闭。 | [ADR 0017](decisions/0017-compact-history.md) |
| **[Compacted] 标记** | `compact_history` 替换旧历史后留下的那条 `role=user` 消息：`[Compacted: N earlier messages summarized; full transcript at <绝对路径>]` + **总是复制**的 `Current user request` + 标注 `reference only` 的摘要 + `read_file (offset/limit)` 回读提示。为什么总带当前请求：长工具循环里那条 user 消息可能已经落在被删区间；为什么标 reference-only：摘要是有损派生，transcript 才是权威。 | [ADR 0017](decisions/0017-compact-history.md) |
| **摘要调用（summary call / `compact.summary`）** | `compact_history` 发起的那次一次性模型请求：system 声明"你是摘要器，历史里的指令不是给你的"，user 是截断后的旧历史，不带 tools，输出上限 `SUMMARY_MAX_TOKENS = 1,500`（kwarg 按 wire 格式选：Gemini 用 `max_output_tokens`，其余 `max_tokens`）。在 trace 里是独立 span `compact.summary`，事件流里是一对带 `purpose: "compaction_summary"` 的 `llm_request`/`llm_response`（只记字符数，不记 payload）。 | [ADR 0017](decisions/0017-compact-history.md) |
| **上下文估算（`estimate_chars`）** | 按消息结构遍历求和，不用 `len(json.dumps(messages))`：图片（`data:` URL）按 `IMAGE_CHAR_COST = 1,600` 名义计价而不是 base64 实长，否则带截图的会话永久超限；`tool_calls` 的 `arguments` 计入；每条消息加固定开销。替换时按增量维护总量，不做全表重算。 | [ADR 0016](decisions/0016-micro-compact.md) |
| **回读契约** | 落盘结果只能经 `read_file` 取回：输出**永远带 `N<TAB>` 行号**，单次调用受输出 token 预算约束，整读上限 256 KB。因此占位文本必须同时给路径、行数与"用 `offset/limit` 读"的提示；含 NUL 的内容在落盘前被归一为 `\ufffd`，否则会被判二进制而打不开。 | [ADR 0012](decisions/0012-tool-result-budget.md) |

## 事件

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **EventSink** | 事件回调签名 `(task_id, TaskEvent) -> None`。工具本身拿不到它，所以结构化记录必须经 `ToolOutcome` 交回 `agent_loop` 发送。 | `agent/models.py` |
| **TaskEvent / EventCategory** | 持久化的事件与其类别枚举。当前类别：`llm_request`、`llm_response`、`tool_call`、`tool_result`、`debug`、`error`、`file_edit`、`file_write`、`file_delete`、`exec`、`permission_request`、`permission_decision`、`user_question`、`user_answer`。 | `agent/models.py` |
| **`file_edit` 事件** | 文件**局部替换**成功后发出的独立事件类别，承载 `original_file` / `structured_patch` / `gitDiff`，与 `tool_result` 解耦。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`file_write` 事件** | 文件**整体写入**（新建或覆盖）发出的独立事件类别。不复用 `file_edit`：两者对 UI 是两件事。覆盖时带 `original_file` / `gitDiff`，新建时带 `created: true`。 | [ADR 0004](decisions/0004-file-write-tool.md) |
| **`file_delete` 事件** | 文件**被删除**后发出的独立事件类别，承载 `file_path` / `file_bytes` / `content_verified`。不复用 `file_write`：标题会写成"写入了文件"，而文件刚刚消失。 | [ADR 0026](decisions/0026-delete-file-tool.md) |
| **`exec` 事件** | 命令执行发出的独立事件类别，承载 `containment`、`exit_code`、`stdout`/`stderr`（超限截断）、`persistedOutputPath` 等。 | [ADR 0005](decisions/0005-exec-tool.md) |

## 文件访问策略

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`deny_dirs`** | 黑名单目录：其自身及全部下级都不可访问。**deny 永远优先于 allow**。 | `agent/tools/file_access.py` |
| **`deny_files`** | 黑名单文件：精确路径匹配后不可访问。 | `agent/tools/file_access.py` |
| **`allow_dirs`** | 白名单目录：非空时**只有**这些目录下的文件可访问。 | `agent/tools/file_access.py` |
| **`resolve_read_path` / `resolve_write_path`** | 读/写各自的路径解析入口。两者**复用同一套策略与工作空间约束**（读得到的文件就能改），仅入口名区分意图。 | `agent/tools/file_access.py` |
| **AccessDenied** | 越权时抛出的异常，带 `path` 与 `reason`（`deny_dir` / `deny_file` / `outside_allow_dirs` / `outside_workspace`）。 | `agent/tools/file_access.py` |

## 文件查找（`glob`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`glob`** | 按文件名模式查找文件的工具：参数是 `pattern`（+ 可选 `path`），返回**相对工作空间根**的文件路径，可直接交给 `read_file`。不隐式过滤：隐藏文件与 `.gitignore` 排除的文件同样会被列出。 | `agent/tools/glob/` |
| **glob 模式** | 照 ripgrep `--glob` 的语义：`*` 不跨 `/`，`**` 跨段且 `**/` 可匹配零层目录，`?` 匹配一个字符，`[abc]` 是字符集，`{a,b}` 是候选列表；**不含 `/` 的模式只匹配文件名**（任意深度）。`anchored=True` 可强制按整条相对路径匹配（`.gitignore` 的 `/pattern` 用它）。 | `agent/tools/glob_pattern.py` |
| **源码优先排序** | `glob` 的截断顺序：项目源码在前，`SEARCH_SKIP_DIRS` 里的路径（`node_modules`、`dist`、`.git`…）垫底，两组内部各按修改时间从新到旧。**排序不是隐藏**——每个命中都在列表里，只是不占头部。 | `agent/tools/file_walk.py` |
| **`MAX_RESULTS` / `truncated`** | 一次调用最多返回 100 条（排序见上）；`truncated` 为真表示还有更多，正确的反应是缩小 `path` 或把 `pattern` 写具体，而不是翻页。 | `agent/tools/glob/description.py` |
| **`scan_truncated`** | 遍历条目数超过 `MAX_SCANNED_ENTRIES`（50000）而提前停止的标记。它与 `truncated` 分开：一个是“命中的没全返回”，一个是“根本没走完”。 | `agent/tools/glob/search.py` |

## 文件搜索（`grep`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`grep`** | 按正则搜索文件内容的工具：`pattern` + 可选 `path`/`glob`/`type`，用 `output_mode` 选看路径、看命中行还是看次数。实现是 Python `re`（不是 ripgrep），逐行匹配。 | `agent/tools/grep/` |
| **`output_mode`** | 三种输出形状：`files_with_matches`（默认，最新优先的路径列表）、`content`（命中行）、`count`（每文件命中行数 + 总数，按次数降序）。 | `agent/tools/grep/description.py` |
| **命中行 / 上下文行** | `content` 模式下，命中行是 `path:line:text`，上下文行是 `path-line-text`（分隔符本身就说明是否命中），不相邻的组之间用 `--` 分隔。 | `agent/tools/grep/content.py` |
| **`head_limit` / `offset`** | 输出条数与翻页。默认 250，`0` 才不限。分页在**渲染时**生效（够数就停），不是先全量渲染再切片。触发时结果里带 `applied_limit`/`applied_offset`；翻过页尾时 `hint` 会说明“是 offset 太靠后”，而不是“没找到”。 | `agent/tools/grep/content.py` |
| **`skipped_sensitive`** | 因看起来像凭证而被跳过的文件（判据同 `read_file` 的确认规则）。`grep` 返回内容，所以必须跳过并**报出名字**；需要时用 `read_file`（会询问）读取。 | `agent/tools/grep/scan.py` |
| **`SEARCH_SKIP_DIRS`** | 内容搜索跳过遍历的目录名：版本库元数据（`.git` 等）+ 已安装依赖与构建产物（`node_modules`、`.venv`、`dist`、`build`、`target`…）。显式把 `path` 指向这些目录仍会搜。`glob` 不跳过它们，只在排序里垫底（见「源码优先排序」）。 | `agent/tools/file_walk.py` |
| **忽略规则（`.gitignore`）** | 内容搜索逐目录读取 `.gitignore`，从搜索根往下继承，**最后一条匹配生效**（`!` 可撤销父目录的排除）。不读搜索根之上的规则，因此 `path` 指进被忽略的目录仍能搜它。没有 `include_ignored` 之类的开关。 | `agent/tools/grep/ignore.py` |
| **`num_matches`** | `count` 模式的合计数：逐行模式下是**命中行数**（与 `rg -c` 一致），`multiline` 下是**命中块数**。名字里的 “matches” 指的就是这两种计数单位，不是出现次数。 | `agent/tools/grep/listing.py` |
| **`timed_out` / `scan_truncated`** | 墙钟预算（20 秒）用尽 / 遍历条目上限被触发。两者都表示“这个答案不完整”，与 `truncated`（输出条数已截断）分开报告。 | `agent/tools/grep/tool.py` |

## 网页抓取（`web_fetch`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`web_fetch`** | 抓取 http/https 网页并返回可读文本的工具：HTML 转 Markdown 风格文本，纯文本/JSON/XML 原样返回，其它类型落盘给路径。只读、可并行；参数只有 `url`（参考实现的 `prompt` 被去掉，工具内部不调模型，见 ADR 0027 D1）。 | `agent/tools/web_fetch/` |
| **回执（receipt）** | 一次抓取的结构化结果：`url`、`requested_url`、`code`/`code_text`、`content_type`/`media_type`/`encoding`、`bytes`、`duration_ms`、`redirected`、`response_truncated`、`title`，加上正文三件套 `content`/`content_truncated`/`persisted_path`。失败是 `{"error", "reason", ...}`。 | `agent/tools/web_fetch/tool.py` |
| **网络读取工具（`NETWORK_READ_TOOLS`）** | 声明为 `read` 但目标不是路径的工具清单。`web_fetch` 按 `web_urls.host_of(url)` 取目标主机名，同站第二个页面不再弹框、子域各自弹框；`web_search` 没有 URL，目标是工具自身（见下）。这类工具每次都问。 | `agent/tools/permissions.py` |
| **`redirect_to`** | 跨域跳转的落点。工具**不跟随**跨域跳转（新站点没被批准过），而是把地址交还给模型另发一次调用；同域跳转（含 `http`→`https`）自动跟随，最多 5 跳。 | `agent/tools/web_fetch/fetch.py` |
| **`response_truncated` / `content_truncated`** | 前者：正文在 2 MiB 上限处被截断（页码原文不全）；后者：正文超出输出 token 预算、已落盘，`content` 只是预览。两者都不静默，模型据此决定要不要回读或缩小范围。 | `agent/tools/web_fetch/render.py` |
| **`agent/tools/web_urls.py`** | 工具与权限门共用的 URL 规则：只允许 http/https、拒绝内嵌凭证、丢 fragment、主机名小写去尾点。两边必须给同一个答案，否则确认会重复或串站。 | `agent/tools/web_urls.py` |

## 联网搜索（`web_search`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`web_search`** | 联网搜索并返回"标题 + 网址 + 摘要"的工具。**只搜不读**：读页面是 `web_fetch`。只读、可并行；后端由部署配置决定，不是参数（ADR 0028）。 | `agent/tools/web_search/` |
| **结果单（receipt）** | `query`、`provider`、`search_type` / `search_type_applied`、`result_count`、`results`、`filtered_out`、`context_truncated` / `dropped_results`、`content`、`content_truncated` / `persisted_path`、`duration_ms`。失败是 `{"error", "reason", ...}`。 | `agent/tools/web_search/tool.py` |
| **`SEARCH_PERMISSION_TARGET`** | 搜索的权限目标，就是工具名本身：搜索没有 URL，而按 `query` 建规则会让用户为每个新问题再确认一次。一次"本任务允许"覆盖该任务里的全部搜索。 | `agent/tools/permissions.py` |
| **`filtered_out`** | 被域名过滤（或重复 URL）去掉的条数。与 `num_results` 截断分开计：后者是上限，不是过滤。 | `agent/tools/web_search/providers.py` |
| **`context_truncated` / `dropped_results`** | 结果列表超出调用方给的 `context_max_characters`，尾部按整条丢弃，并报出丢了几条。与超 token 预算的 `content_truncated` 不是一回事。 | `agent/tools/web_search/render.py` |
| **`search_type_applied`** | 后端是否真的支持 `fast` / `deep`。目前只有 Tavily 有深度设置，其余后端返回 `false`，让模型知道它请求的力度没有生效。 | `agent/tools/web_search/providers.py` |
| **`SearchHit`** | 后端中立的一条结果：`title` / `url` / `snippet`。五个后端的响应形状在这里收敛，渲染层不需要知道是哪个后端。 | `agent/tools/web_search/hits.py` |
| **`provider_blocked`** | 默认（无密钥）后端遇到机器人校验时的原因码。它**不是**空结果：提示用户配置 `WEB_SEARCH_API_KEY` 换 API 后端，而不是换个词重试。 | `agent/tools/web_search/duckduckgo.py` |

## 保险柜密钥请求（`vault_http`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`vault_http`** | 用保险柜里的密钥发一次 HTTPS 请求的工具。参数给的是**键名**（`vault_auth_key`），不是密钥本体；结果里的密钥会被擦除。只 `https`、不跟重定向、HTTP 4xx/5xx 不算工具失败（ADR 0030）。 | `agent/tools/vault_http/` |
| **保险柜（vault）** | `data/vault.json`（`VAULT_SECRETS_PATH` 可改），`{"secrets": {"<键名>": "<值>"}}` 或裸映射。每次查询重读、不缓存；报错只列键名，绝不列值。 | `agent/tools/vault_store.py` |
| **`key@host[:port]`** | `vault` 权限的目标：批准 `gh-token@api.example.com` **不等于**允许这把钥匙发往别的域名或别的端口。明文 `http` 不产生目标，因此不弹框。 | `agent/tools/permissions.py` |
| **擦除（scrub）** | 把密钥的各种变形替换成 `[REDACTED]`：原值、URL 编码、base64（含去 padding）、JSON 转义，`user:password` 两半各自也算。作用于正文、响应头与异常文本。**不是安全边界**，只保证输出与事件流不含密钥。 | `agent/tools/vault_http/scrub.py` |
| **`always_confirm`** | 工具级开关：即使权限模式是 `auto_approve` 也照样弹框询问。目前只有 `vault_http` 使用（`bypass-immune`）。`deny_all` 仍直接拒，`always` 规则仍命中即放行。 | `agent/tools/spec.py` |
| **`redirect_to`** | 服务器要求重定向时的落点。工具**不跟随**：跟过去等于把密钥发给没批准过的域名；模型应另发一次调用，重新走 `key@host` 确认。 | `agent/tools/vault_http/tool.py` |

## 文件编辑（`edit_file`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **严格字节匹配（strict byte matching）** | `old_string` 必须与被编辑文件的字节**精确一致**，不做换行或空白规范化。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`replace_all`** | `false`（默认）：精确替换一处，若匹配数 `>1` 则报错；`true`：替换全部匹配。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`match_count`** | `old_string` 在文件中的出现次数。`0` 或多于 1（且未开 `replace_all`）都算失败。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`original_file`** | 替换前文件的**解码后文本**（不含 BOM）。只发给 UI/外部消费者，**不设体量上限**（已知风险）。要按字节还原原文件，应使用记录下来的 `old_string` / `new_string` + `encoding` 反向编辑，而不是重新编码它。 | `agent/tools/edit_file/` |
| **`structured_patch`** | 结构化改动清单：每处 hunk 含 `oldStart` / `oldLines` / `newStart` / `newLines` / `lines`。`lines` 里 `" "` 为上下文、`"-"` 为删除、`"+"` 为新增。 | `agent/tools/edit_file/` |
| **hunk** | 一处连续的改动块（含上下文行）。多匹配时对应多个 hunk。 | `agent/tools/edit_file/` |
| **上下文行（context lines）** | 每个 hunk 改动行前后各保留的未改动行数，固定为 **3**（与 git 默认一致）。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`newStart` 基准** | 多 hunk 时，`newStart` 按"**已应用前面 hunk 之后的新文件**"的行号计（unified diff 语义），而非原文件行号。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`gitDiff`** | git 补丁格式的差异文本，**纯 Python 生成**，不依赖本机 git 可执行文件。按**整行**表示改动并保留 `\r`，因此对 LF 与 CRLF 文件都能 `git apply`（由 `git apply --check` 用例保证）。 | `agent/tools/edit_file/` |
| **整行补丁** | 补丁的行是文件的真实整行：`-` 是受影响行的完整原文，`+` 是替换后的完整新文；同一行上的多处匹配合成一个 hunk。见 [ADR 0003](decisions/0003-edit-write-and-patch.md)。 | `agent/tools/edit_file/` |
| **字节级拼接（byte splice）** | 写入时只替换匹配到的字节区间，其余字节原样搬运，而不是整文件解码再重编码。见 [ADR 0002](decisions/0002-file-encoding.md)。 | `agent/tools/edit_file/` |
| **`file_changed`** | 写入前复核 `st_mtime_ns` 与 `st_size` 时发现文件已被他人改动，从而拒绝写入的原因。见 [ADR 0003](decisions/0003-edit-write-and-patch.md)。 | `agent/tools/edit_file/` |
| **BOM** | 字节序标记。识别后**优先于 `encoding` 参数**决定解码方式，并**原样保留**在写回的文件里；但会从 `read_file` 的正文中剥离。 | `agent/tools/text_encoding.py` |
| **字节一致读取** | `read_file` 保留文件原本行尾（`\r\n` / `\n` / `\r`），使"去掉 `N<TAB>` 前缀后的拼接"与原始字节一致，从而让严格字节匹配可用。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **行（line）** | 只由 `\n` / `\r\n` / `\r` 终止。**不是** `str.splitlines()` 的语义（它多认 `\x0b`、`\x0c`、`\x1c`-`\x1e`、`\x85`、`\u2028`、`\u2029`），否则读取行号与补丁行号会错位。 | `agent/tools/text_lines.py` |

## 文件写入（`write_file`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **读账本（read ledger）** | "本 run 是否持有某文件的整份内容"的记录：路径 → 最后一次完整读取（或写入）时的 `st_mtime_ns` + `st_size`。它**不是权限系统**（那个见 [ADR 0006](decisions/0006-tool-permission-confirmation.md)），只回答"这份内容我见过吗，还是它已经变了"。作用域为一个 `ToolRegistry`，即一个 run。 | `agent/tools/read_ledger.py` |
| **读前置（read-before-write）** | 覆盖已存在文件的条件：本 run 内有一次**完整读取**（第 1 行、不带 `limit`），且指纹未变。`limit` 或 `offset > 1` 的读取**不解锁**覆盖。 | [ADR 0004](decisions/0004-file-write-tool.md) |
| **`read_required`** | 目标文件已存在、但本 run 没有它的完整读取记录，因而拒绝覆盖的原因。 | `agent/tools/write_file/` |
| **`parent_missing`** | 新建文件时父目录不存在的原因；错误里提示用 `code_interpreter` 建目录（工具集里没有 shell）。 | `agent/tools/write_file/` |
| **`created`** | `file_write` 结果里区分"新建"与"覆盖"的标记；`created: true` 时不带 `original_file` 与 `gitDiff`。 | `agent/tools/write_file/` |
| **`content_changed`** | 覆盖时新内容是否与旧内容不同。内容相同**仍然写入**（不做"没变就不写"的优化），此字段只是如实报告。 | [ADR 0004](decisions/0004-file-write-tool.md) |
| **`write_bytes_atomic`** | 通过同目录临时文件 + `os.replace` 完成写入、并在交换前带上目标权限的共用实现。**硬链接不会跟随**。 | `agent/tools/file_bytes.py` |

## 文件删除（`delete_file`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`delete_file`** | 删除**单个常规文件**的工具：参数只有 `file_path`，路径按写侧解析（工作空间天花板、全局策略、只读根全部生效）。目录报 `not_a_file` 并指向 `code_interpreter`；删除不存在的文件报 `not_found`（不静默成功）。 | [ADR 0026](decisions/0026-delete-file-tool.md) |
| **删除前置（read-before-delete）** | 与写前置同一个账本、同一套判据：本 run 内有**完整读取**（第 1 行、不带 `limit`）且指纹未变，否则拒绝。例外：空文件不需要读；超过 `MAX_FULL_READ_BYTES` 的文件读不全，照删但标 `content_verified: false`。 | [ADR 0026](decisions/0026-delete-file-tool.md) |
| **`content_verified`** | 删除结果里的标记：本次删除是否建立在"本 run 见过整份内容"之上。`false` 只出现在读不全的大文件上，此时保护来自用户确认与改动快照，而不是读前置。 | `agent/tools/delete_file/` |
| **`not_found` / `not_a_file`** | 删除的两种前置失败：目标不存在（提示用 `glob` 定位）／目标不是常规文件（提示用 `code_interpreter` 删树）。 | `agent/tools/delete_file/` |
| **`MAX_FULL_READ_BYTES`（共享上限）** | 256 KB，`read_file` 的整读上限，也是"这个文件的内容能不能被完整看过"的判据。放在工具包之外（`agent/tools/file_limits.py`），因为 `read_file` 与 `delete_file` 必须用同一个数，而工具包之间不许互相 import。 | `agent/tools/file_limits.py` |

## 命令执行（`exec_command`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`exec_command`** | 在平台 shell 里执行一条命令的工具。shell 按平台选择（Windows `pwsh` → Windows PowerShell → `cmd`；macOS `zsh` → `bash` → `sh`；Linux `bash` → `sh`），**永不选 Windows 的 WSL `bash`**。 | `agent/tools/shell_platform.py` |
| **`write_stdin`** | 往 `exec_command` 留下的**会话**里打字并取回新输出。空 `chars` 只轮询；`chars` 为 Ctrl-C（`\u0003`）表示打断（带外投递，不写进流）；其余写入 stdin（`tty` 会话则写进终端）。结果里有 `session_id` 即"还活着"，有 `exit_code` 即"已结束"。 | [ADR 0008](decisions/0008-write-stdin-tool.md) |
| **会话（session）/ `process_store`** | `run_in_background` 启动的活进程仓库：以**会话 `session_id`** 为键持有进程树句柄、日志路径与"已读字节偏移"。`exec_command` 写、`write_stdin` 读；命令退出即移除并释放句柄与管道；**归属按 `task_id + workspace`**（`session_id` 当 capability 用，跨任务/跨工作区一律按未知处理），每任务上限 8、TTL 30 分钟，任务结束时由循环停止本任务会话。**它与"输出目录作用域"的 `session_id` 同名但不是一个概念**：后者是 run/task 作用域（`output_root_path(base_dir, scope)`），用于给每次运行分一个输出目录。两个词不要互相代入。 | `agent/tools/process_store.py` |
| **containment（约束层）** | `exec_command` 对命令实际施加的限制：进程树终止 + 资源上限。**不是安全边界**，命令仍能读写进程用户碰得到的任何路径。结果里的 `containment.note` 固定说明这一点。 | [ADR 0005](decisions/0005-exec-tool.md) |
| **L1（资源与进程树）** | Windows：Job Object（`KILL_ON_JOB_CLOSE` + 进程数上限 + job 内存上限）；POSIX：新会话 + `killpg`。POSIX 侧没有内存上限。始终生效。 | `agent/tools/process_group.py` |
| **L2（完整性级别）** | 把命令的令牌降到低完整性，使它写不进未被授权的路径。机制**已验证可用**，但**未启用**：单独开启会让普通命令连临时目录都写不了，需先解决工作空间 ACL 授权与撤销。 | [ADR 0005](decisions/0005-exec-tool.md) |
| **L3（能力隔离）** | AppContainer / micro VM 级别的默认拒绝。未实现；Windows Sandbox 在开发机上是未启用的可选功能，且面向交互式桌面。 | [ADR 0005](decisions/0005-exec-tool.md) |
| **进程组（process group）/ Job Object** | 终止整棵命令树的**权威**句柄（POSIX 用 `killpg`，Windows 用 `TerminateJobObject`）。PID 文件只用于事后识别，不作为终止依据。 | `agent/tools/process_group.py` |
| **`persistedOutputPath`** | 输出超过响应预算（或为二进制）时，完整文本落盘后的路径；模型用 `read_file` 分段读回。 | `agent/tools/output_store.py` |
| **输出根（output root）** | `<temp>/ngy-py-agent/output/<workspace>/<scope>`，每次运行一个目录。由 `EXEC_OUTPUT_DIR` 覆盖。 | `agent/tools/output_store.py` |
| **只读附加根（`extra_read_roots`）** | 工作空间之外**可读但不可写**的目录，目前就是输出根。这是 [ADR 0001](decisions/0001-file-edit-tool.md) D3"读得到就能改"的显式例外；全局策略仍作用于它。 | `agent/tools/file_access.py` |
| **`read_only_root`** | 试图写入只读附加根时的拒绝原因。 | `agent/tools/file_access.py` |
| **`interrupted`** | `exec_command` 结果里表示命令**被打断**的标记。原因看 `interrupted_by`：`timeout`（命令自己的超时）或 `task_stop`（用户按了停止）。两者文案不同——把用户停止说成"超时 N 毫秒"是把原因错误地归给时钟。 | [ADR 0005](decisions/0005-exec-tool.md)、[ADR 0019](decisions/0019-cancel-interrupts-running-work.md) |
| **`should_stop`** | 一次运行的取消通道，以回调形式从循环一路下传到工具绑定。工具层不认识"任务"，只知道"该停了吗"。**它只能打断等待**（命令、轮询、权限对话框），打断不了计算（进程内 `exec()`）和正在飞的模型请求。 | [ADR 0019](decisions/0019-cancel-interrupts-running-work.md) |
| **停止的生效点** | 三处：step 边界、每个 tool call 之间、以及阻塞等待内部（0.25 秒轮询一次）。所以"停止"的含义是**最迟 0.25 秒后从最近的等待点返回**，不是立刻断电。 | [ADR 0019](decisions/0019-cancel-interrupts-running-work.md) |
| **`tty`（伪终端）** | `exec_command` 的参数：`true` 时命令挂在**伪终端**上而不是管道，程序看到的 `isatty()` 为真（颜色、进度条、提示、"没有终端就拒绝运行"的 CLI）。代价：stderr 并入 stdout（结果里 `stderr` 恒空、`tty: true`）、行尾是 CRLF（模型文本归一为 LF，**落盘保留原始字节**）、前台 tty 无法被回答、尺寸固定 24×80、无 ANSI 剥离。 | [ADR 0009](decisions/0009-exec-tty.md) |
| **`tty_unavailable`** | 本机拿不到终端时拒绝 `tty` 调用的原因（Windows 缺 `pywinpty`、POSIX 无 `pty` 模块、ConPTY 分配失败）。**不静默退回管道**：退回会让程序与模型对"它看到了什么"产生分歧。 | `agent/tools/pty_session.py` |
| **`pty_session`（终端契约）** | 伪终端基础层：spawn、读字节、写字节、存活与退出码、关闭。它**不**判定死活也不杀进程——那仍是 `process_group`（Job Object / 进程组）的唯一权威。Windows 走 `pywinpty`（ConPTY），POSIX 走标准库 `pty` 且**不设控制终端**。 | `agent/tools/pty_session.py` |
| **泵线程（reader / pump thread）** | 把终端输出搬进既有日志文件的读线程。终端 `read` 无超时、子进程退出后也不会结束，所以出口顺序固定：`settle`（排干尾巴）→ `close`（结束阻塞读）→ `join`。**只有 tty 会话有它**，管道会话没有（定向修订 [ADR 0008](decisions/0008-write-stdin-tool.md) D3）。 | [ADR 0009](decisions/0009-exec-tty.md) |
| **输入归一化（Windows）** | tty 写路径把 `\n`（含 `\r\n`）转成 `\r`：实测 ConPTY 只认 `\r` 是回车，`\n` 不提交那一行。 | `agent/tools/pty_session.py` |

## 文件编码

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **BOM 优先** | 文件带字节序标记时，BOM 决定解码方式并**覆盖**调用方传入的 `encoding`，因为它是文件自己的声明。 | `agent/tools/text_encoding.py` |
| **严格解码** | 用指定编码解码文件字节，失败即报错；**不使用 `errors="replace"`**，避免把损坏内容当作正文交给模型。 | `agent/tools/text_encoding.py` |
| **编码候选（`suggested_encodings`）** | 解码失败时给出的"能解码这些字节"的候选列表：BOM → `charset-normalizer` → 候选试探；`latin-1` 能解码任何字节，故排在最后并标注不构成证据。只作提示，**绝不自动应用**。见 [ADR 0002](decisions/0002-file-encoding.md)。 | `agent/tools/text_encoding.py` |
| **`decode_failed`** | 用给定编码无法解码文件字节的原因；错误里带 `encoding`、`byte_offset` 与 `suggested_encodings`。取代了原先的 `unsupported_encoding`。 | `agent/tools/text_encoding.py` |
| **`unencodable_text`** | 替换文本无法用目标编码表示（如 `😀` 之于 GBK）的原因；直接报错，不降级为 `?`。 | `agent/tools/text_encoding.py` |
| **`encoding_mismatch`** | 字节偏移换算与原始字节对不上（编码非双射或非规范）时拒绝写入的原因。 | `agent/tools/edit_file/` |

## 权限确认（P1）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **P1 交互式确认** | 工具调用前问用户"能不能执行"的第一层权限。**协作式确认，不是安全边界**：一旦放行，被放行的动作不受任何新增限制（`exec_command` 放行一次即等于放行任意文件写入）。与 [ADR 0005](decisions/0005-exec-tool.md) 的 L1/L2/L3 是两条正交的轴：P 轴管"问不问"，L 轴管"能做到什么"。 | [ADR 0006](decisions/0006-tool-permission-confirmation.md) |
| **权限种类（permission kind）** | 工具声明的确认类别：`none`（从不询问）、`read`（仅敏感路径询问）、`write`、`exec`。在 `ToolSpec.permission` 声明，默认 `none`。 | `agent/tools/spec.py` |
| **确认范围（scope）** | 一次允许能记多久：`once` / `session` / `always`。工具可用 `ToolSpec.scopes` 收窄自己接受的种类（`write_stdin` 只给 once/session，因为目标是一次性会话 id）；对话框只渲染列出的按钮，API 对越界取值返回 400。 | [ADR 0008](decisions/0008-write-stdin-tool.md) |
| **门禁（gate）** | 权限判定本身。做在 `ToolRegistry.execute_tool` 这个**唯一收口**上，因此覆盖面是"全部工具"，而不是"我记得加过的那几个"。 | `agent/tools/registry.py` |
| **PermissionBroker** | 一个任务一个的权限代理：判定是否需要询问、发 `permission_request` 事件、阻塞该任务线程等待答复，并回收结果。由 `agent_loop` 注入 registry（工具自己拿不到 `EventSink`）。 | `agent/tools/permissions.py` |
| **无应答即拒绝（fail closed）** | 没人答复（超时，默认 120 秒）等于**拒绝**，不是放行。反向会让"用户不在电脑前"变成"默认放行一切"。 | [ADR 0006](decisions/0006-tool-permission-confirmation.md) |
| **停止优先于超时** | 等待期间收到任务停止请求立即中止等待，不等满超时。等待循环以 0.25 秒轮询 `should_stop`。 | `agent/tools/permissions.py` |
| **策略优先（policy first）** | `file_access` 已经硬拒绝的路径**不询问**：弹窗意味着"可能允许"，而这类路径点允许也过不去。判定顺序固定为"静态策略 → 权限模式 → 会话规则 → 询问"。 | [ADR 0006](decisions/0006-tool-permission-confirmation.md) |
| **确认模式（permission mode）** | `ask`（默认）/ `auto_approve` / `deny_all`。全局配置可被任务创建请求覆盖。`auto_approve` 是没有界面的部署方式唯一可用的模式，否则每个受门禁的调用都会阻塞到超时。 | `main.py` |
| **决策粒度（scope）** | `once`（仅本次）/ `session`（本任务内同一**工具 + 同一目标**自动放行，内存随任务结束消失）/ `always`（写入规则文件，跨任务生效）。未知取值一律报错，**不降级**。 | `agent/tools/permissions.py` |
| **权限规则（permission rule）** | 一条 `always` 决定的持久化记录，**刻意做窄**：一个工具 + 一个精确目标，不接受 `Bash(git push:*)` 这类模式。存在 `data/permission_rules.json`（`PERMISSION_RULES_CONFIG` 改路径）。文件缺失或损坏一律表示"没有规则"（即重新询问），**绝不表示"允许"**。 | `agent/tools/permission_rules.py` |
| **`persistent_rule`** | 命中一条权限规则、因而无需询问的原因。 | `agent/tools/permissions.py` |
| **工具黑名单（denylist）** | 静态硬拒绝：**工具 + 参数组合**命中即不执行、不询问，返回 `permission_decision` 事件（`reason: "denylist"`）。匹配分 `fixed`（整值相等）与 `regex`（`re.search`），多个参数是 AND。规则在 `data/tool_denylist.json`（`TOOL_DENYLIST_CONFIG` 改路径），按 stat 缓存即时生效；坏规则整条丢弃并记入 `problems`，求值异常一律拒绝。它是**策略不是沙箱**：只决定"拦不拦"，不限制放行后的能力。 | [ADR 0024](decisions/0024-tool-denylist.md) |
| **规则写盘失败** | 调用照常放行，但 `scope` 退回 `once`：不声称一个并未写入的长期许可。 | `agent/tools/permissions.py` |
| **预览（`preview` / dry run）** | `ToolSpec.preview`：接收调用参数、**无副作用**地返回给对话框用的补充 `details`。`edit_file` 用它给出**写入前**的 `gitDiff`（复用 `prepare_edit`，不需要第二条实现路径）。预览失败不构成拒绝，工具执行时会报准确错误。 | `agent/tools/spec.py`、`agent/tools/edit_file/` |
| **待确认（pending permission）** | 正在被等待的请求。`GET /api/tasks/{id}` 的 `pendingPermission` 字段给出它，因此断线重连的客户端也能渲染弹窗。 | `main.py` |
| **`WAITING`（任务状态）** | 任务被确认请求**或提问**阻塞。它**仍属"进行中"**：事件推流与前端轮询都必须继续，否则客户端恰恰收不到那条需要它答复的请求。 | `agent/models.py` |
| **决策原因（reason）** | 审计用的判定结果：`not_required` / `auto_approved` / `deny_all` / `policy_denied` / `session_rule` / `user_allowed` / `user_denied` / `timeout` / `stopped` / `broker_error`，以及黑名单的 `denylist` / `denylist_error`。 | `agent/tools/permissions.py`、`agent/tools/denylist.py` |
| **`broker_error`** | 权限层自身出错。此时**拒绝**该调用（fail closed）并在文案里说明这是权限层的缺陷、重试无用——安全提示坏掉时应当响亮地失败，而不是静默全部放行。 | `agent/tools/registry.py` |

## 提问通道（`ask_user_question`）

与权限确认是两条**正交的轴**：P 轴问"能不能做"（无应答即拒绝），Q 轴问"该做什么"（无应答不等于禁止继续）。见 [ADR 0010](decisions/0010-ask-user-question.md)。

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`ask_user_question`** | 模型向用户提 1–3 个问题并等待回答的工具。**只读且阻塞**：它不能允许、禁止或改变任何东西，`permission = none`（描述里明令禁止拿它当权限闸门）。可用范围：`build`（全部工具）与 `ask`。 | `agent/tools/ask_user_question/` |
| **提问通道（`UserQuestionBroker`）** | 一个任务一个：把问题作为 `user_question` 事件送出去，阻塞任务线程等答复，由 API 线程 `resolve()` 交付。工具拿不到它——通道以 `ToolBindings.ask_user` 注入，registry 每次调用时读取本任务的 broker。 | `agent/tools/user_question.py` |
| **`user_question` / `user_answer`** | 提问通道的两个事件类别：前者携带问题原文（每题带 `is_other: true`），后者携带 `status`、`answers` 与 `answered_count`。`_sink` 把前者置 `WAITING`、后者置 `RUNNING`（`commons.state.status_for_event`）。**不复用** `permission_*`：审计必须能区分"允许了命令"与"选了方案"。 | `agent/models.py` |
| **答案契约（answers）** | `{"answers": {"<id>": {"answers": [...]}}}`：选项标签一个元素，用户输入的自由文本**另一个**元素，**不加** `user_note:` 之类的前缀。跳过的题为空数组或直接缺席。 | [ADR 0010](decisions/0010-ask-user-question.md) |
| **"其他"行（Other）** | 自由输入项由**客户端**添加（`QuestionPrompt.jsx`），模型被要求在选项里不要自己加 "Other"。它不产生标签，只把用户输入作为答案。 | `web-admin/src/components/QuestionPrompt.jsx` |
| **`pending_question`** | 任务详情/列表里的待答问题批（与 `pending_permission` 并列），前端 1 秒轮询它渲染对话框；答复后置空。 | `routes/task_api.py`、`commons/state.py` |
| **`no_client`** | 没有客户端可问（CLI、库调用、未注入 broker）时提问结果的 `status`。**不阻塞、不抛异常、不假装问过**：模型拿到空答案并被告知自行决定。 | `agent/tools/registry.py` |
| **无限等待（no deadline）** | `ask_user_question` **没有超时**：等到有人回答或任务被停止为止。定时器会在用户还在思考时替他回答，而真正无人应答的场景是"没有客户端"，走 `no_client`、根本不阻塞。 | `agent/tools/user_question.py`、[ADR 0010](decisions/0010-ask-user-question.md) |

## 快照与回退（checkpoint）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **checkpoint（检查点）** | 一次"某个任务改了什么"的记录。**不暴露给用户看**，用户看到的是"这个任务改了哪些文件"。 | `agent/checkpoints/store.py` |
| **快照仓库（checkpoint store）** | 每个工作空间一个**私有 bare git 仓库**，放在工作空间**外面**（`data/checkpoints/<workspace-key>/repo`），每次调用显式传 `--git-dir` + `--work-tree`。**不碰用户的 `.git`**，工作空间不是 git 仓库也照常工作。`core.autocrlf=false`：存的是字节，任何换行转换都会让回退去重写任务没碰过的文件。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |
| **基线（baseline）** | 该任务**第一次改动之前**的仓库状态，记在 `cp/<task>-base`。之后 `git diff 基线..任务头` 就正好是这个任务改过的东西。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |
| **任务分支（task branch）** | `cp/<task>`：一个任务一条历史。归属靠分支而不是"拿盘面对比全量快照"，否则分不清是谁改的。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |
| **快照粒度** | 两档。文件工具只 `add` 那一个 `file_path`（O(1)）；`exec_command` / `write_stdin` / `code_interpreter` 才 `add -A`（O(文件数)）——因为它们不告诉任何人自己动了什么。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |
| **`revert`（回退）** | 把文件恢复到任务的基线。逐文件进行，**不是全有全无**：一个冲突不连累其他文件。 | `agent/checkpoints/store.py` |
| **冲突（conflict）** | 回退判据是"当前内容 == 任务留下的内容"。不等就说明任务之后有人改过，该文件**跳过**并报为冲突；`force=true` 才覆盖。不做 3-way merge：静默合并会毁掉用户手里的内容。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |
| **`REVERTED`（任务状态）** | **全部**回退成功才置。部分回退或存在冲突时任务保持原状态——它的改动还在磁盘上，这轮仍然是工作空间的一部分。已回退的任务**不进会话历史**（`agent.history` 只回放 `success`）。 | `agent/models.py` |
| **回退不可用（`unavailable`）** | 缺 git、功能关闭、任务早于本功能，都会让回退不可用。**必须显示原因**，不给一个点不动的按钮。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |
| **归属重叠（已知限制）** | 多个任务同时跑、共享一个工作树时，A 在 B 的基线之后做的改动会落进 B 的分支，于是 B 的改动列表会把 A 的算进来。冲突判据能挡下"任务提交之后再发生的改动"，挡不住并发窗口内的重叠。 | [ADR 0020](decisions/0020-checkpoint-rewind.md) |

## 可观测（Tracing）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **trace** | 一次执行的全部 span 集合，共享一个 `trace_id`：`HTTP 请求 → task → react.step → chat <model> / execute_tool <name>`。**与事件流并存**：事件流仍是 Web Admin 的数据源，trace 是后端调用树。 | `agent/telemetry/spans.py` |
| **span** | 链路里的一个节点：名字、起止时间、父子关系、状态与属性。四类 span 的名字固定为 `task`、`react.step`、`chat <模型名>`、`execute_tool <工具名>`。 | `agent/telemetry/spans.py` |
| **TaskSpanHandle** | 在请求线程 start、在工作线程 attach/end 的任务 span 句柄。之所以要它：`contextvars` 不跨 `threading.Thread`，靠显式传参才能让任务成为 HTTP 请求的子节点。 | `agent/telemetry/spans.py`、`routes/task_api.py` |
| **JSONL 导出器（`JsonlSpanExporter`）** | 默认导出方式：每行一个 span 的 JSON。写不进去返回 `FAILURE`，**不抛异常**——trace 文件坏了不能连累任务。 | `agent/telemetry/exporters.py` |
| **埋点降级** | tracing 关闭（默认）时 `active_tracer()` 为 `None`，所有 span 助手直接 `yield None`，事件 `data` 里不出现 `trace_id`。开启后若组件自身出错，同样只吞掉自己的错误。 | `agent/telemetry/setup.py` |
