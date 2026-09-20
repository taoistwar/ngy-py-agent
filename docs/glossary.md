# 术语表（Glossary）

本仓库共用的领域术语。按主题分组；每条给出定义与定义位置，避免同一概念在不同文件里叫不同名字。

## Agent 运行时

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **ReAct 循环** | Agent 的主循环：请求模型 → 解析工具调用 → 执行工具 → 把结果回填到消息列表 → 继续，直到模型不再调用工具或达到步数上限。 | `agent/agent_loop.py` |
| **`base_dir` / 工作空间根** | 当前会话绑定的本地根目录。相对路径以它为基准解析，且不得逃出该目录。为空表示**未绑定会话（unbound session）**。 | `agent/tools/file_access.py` |
| **未绑定会话** | 没有 `base_dir` 的会话。此时只剩下全局 `file_access` 策略生效，文件工具默认可以访问工作空间之外。 | `agent/tools/file_access.py` |
| **token 预算** | 单次工具输出允许占用的 token 上限，超限即报错而非截断。`read_file` 依赖它防止撑爆上下文。 | `agent/tools/token_budget.py` |
| **行号前缀** | `read_file` 输出中每行开头的 `N<分隔符>`，分隔符是**制表符**。模型看不到真实行号，因此永远带前缀、不提供关闭开关。 | `agent/tools/file_read_tool.py` |

## 工具与结果

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **ToolSpec** | 工具的声明式定义：模型可见的 `name`、`description`、JSON Schema `parameters`、绑定的 `handler`，以及**权限种类** `permission`。 | `agent/tools/specs.py` |
| **ToolRegistry** | 工具注册表：注册工具、把 schema 适配成各 provider 格式、按名分发调用。 | `agent/tools/registry.py` |
| **ToolOutcome** | **工具结果分流契约**。工具回调可返回它，携带 `model_text`（给模型）与可选事件类别/标题 + `details`（给 UI/外部消费者）。`execute_tool` 对其原样透传，由 `agent_loop` 拆分。 | `agent/models.py` |
| **双通道（dual channel）** | 一次工具调用产生两份输出：给**模型**的精简文本、给 **UI/外部消费者**的结构化记录。二者不再共用同一条消息。见 [ADR 0001](decisions/0001-file-edit-tool.md)。 | `agent/agent_loop.py` |
| **`model_text`** | `ToolOutcome` 中回填进 `messages`（`role="tool"`）的文本，是模型实际"看到"的内容。 | `agent/models.py` |
| **`details`** | `ToolOutcome` 中随事件发送的结构化负载，模型看不到。 | `agent/models.py` |

## 事件

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **EventSink** | 事件回调签名 `(task_id, TaskEvent) -> None`。工具本身拿不到它，所以结构化记录必须经 `ToolOutcome` 交回 `agent_loop` 发送。 | `agent/models.py` |
| **TaskEvent / EventCategory** | 持久化的事件与其类别枚举。当前类别：`llm_request`、`llm_response`、`tool_call`、`tool_result`、`debug`、`error`、`file_edit`、`file_write`、`exec`、`permission_request`、`permission_decision`。 | `agent/models.py` |
| **`file_edit` 事件** | 文件**局部替换**成功后发出的独立事件类别，承载 `original_file` / `structured_patch` / `gitDiff`，与 `tool_result` 解耦。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`file_write` 事件** | 文件**整体写入**（新建或覆盖）发出的独立事件类别。不复用 `file_edit`：两者对 UI 是两件事。覆盖时带 `original_file` / `gitDiff`，新建时带 `created: true`。 | [ADR 0004](decisions/0004-file-write-tool.md) |
| **`exec` 事件** | 命令执行发出的独立事件类别，承载 `containment`、`exit_code`、`stdout`/`stderr`（超限截断）、`persistedOutputPath` 等。 | [ADR 0005](decisions/0005-exec-tool.md) |

## 文件访问策略

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`deny_dirs`** | 黑名单目录：其自身及全部下级都不可访问。**deny 永远优先于 allow**。 | `agent/tools/file_access.py` |
| **`deny_files`** | 黑名单文件：精确路径匹配后不可访问。 | `agent/tools/file_access.py` |
| **`allow_dirs`** | 白名单目录：非空时**只有**这些目录下的文件可访问。 | `agent/tools/file_access.py` |
| **`resolve_read_path` / `resolve_write_path`** | 读/写各自的路径解析入口。两者**复用同一套策略与工作空间约束**（读得到的文件就能改），仅入口名区分意图。 | `agent/tools/file_access.py` |
| **AccessDenied** | 越权时抛出的异常，带 `path` 与 `reason`（`deny_dir` / `deny_file` / `outside_allow_dirs` / `outside_workspace`）。 | `agent/tools/file_access.py` |

## 文件编辑（`edit_file`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **严格字节匹配（strict byte matching）** | `old_string` 必须与被编辑文件的字节**精确一致**，不做换行或空白规范化。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`replace_all`** | `false`（默认）：精确替换一处，若匹配数 `>1` 则报错；`true`：替换全部匹配。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`match_count`** | `old_string` 在文件中的出现次数。`0` 或多于 1（且未开 `replace_all`）都算失败。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`original_file`** | 替换前文件的**解码后文本**（不含 BOM）。只发给 UI/外部消费者，**不设体量上限**（已知风险）。要按字节还原原文件，应使用记录下来的 `old_string` / `new_string` + `encoding` 反向编辑，而不是重新编码它。 | `agent/tools/file_edit_tool.py` |
| **`structured_patch`** | 结构化改动清单：每处 hunk 含 `oldStart` / `oldLines` / `newStart` / `newLines` / `lines`。`lines` 里 `" "` 为上下文、`"-"` 为删除、`"+"` 为新增。 | `agent/tools/file_edit_tool.py` |
| **hunk** | 一处连续的改动块（含上下文行）。多匹配时对应多个 hunk。 | `agent/tools/file_edit_tool.py` |
| **上下文行（context lines）** | 每个 hunk 改动行前后各保留的未改动行数，固定为 **3**（与 git 默认一致）。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`newStart` 基准** | 多 hunk 时，`newStart` 按"**已应用前面 hunk 之后的新文件**"的行号计（unified diff 语义），而非原文件行号。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **`gitDiff`** | git 补丁格式的差异文本，**纯 Python 生成**，不依赖本机 git 可执行文件。按**整行**表示改动并保留 `\r`，因此对 LF 与 CRLF 文件都能 `git apply`（由 `git apply --check` 用例保证）。 | `agent/tools/file_edit_tool.py` |
| **整行补丁** | 补丁的行是文件的真实整行：`-` 是受影响行的完整原文，`+` 是替换后的完整新文；同一行上的多处匹配合成一个 hunk。见 [ADR 0003](decisions/0003-edit-write-and-patch.md)。 | `agent/tools/file_edit_tool.py` |
| **字节级拼接（byte splice）** | 写入时只替换匹配到的字节区间，其余字节原样搬运，而不是整文件解码再重编码。见 [ADR 0002](decisions/0002-file-encoding.md)。 | `agent/tools/file_edit_tool.py` |
| **`file_changed`** | 写入前复核 `st_mtime_ns` 与 `st_size` 时发现文件已被他人改动，从而拒绝写入的原因。见 [ADR 0003](decisions/0003-edit-write-and-patch.md)。 | `agent/tools/file_edit_tool.py` |
| **BOM** | 字节序标记。识别后**优先于 `encoding` 参数**决定解码方式，并**原样保留**在写回的文件里；但会从 `read_file` 的正文中剥离。 | `agent/tools/text_encoding.py` |
| **字节一致读取** | `read_file` 保留文件原本行尾（`\r\n` / `\n` / `\r`），使"去掉 `N<TAB>` 前缀后的拼接"与原始字节一致，从而让严格字节匹配可用。 | [ADR 0001](decisions/0001-file-edit-tool.md) |
| **行（line）** | 只由 `\n` / `\r\n` / `\r` 终止。**不是** `str.splitlines()` 的语义（它多认 `\x0b`、`\x0c`、`\x1c`-`\x1e`、`\x85`、`\u2028`、`\u2029`），否则读取行号与补丁行号会错位。 | `agent/tools/text_lines.py` |

## 文件写入（`write_file`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **读账本（read ledger）** | "本 run 是否持有某文件的整份内容"的记录：路径 → 最后一次完整读取（或写入）时的 `st_mtime_ns` + `st_size`。它**不是权限系统**（那个见 [ADR 0006](decisions/0006-tool-permission-confirmation.md)），只回答"这份内容我见过吗，还是它已经变了"。作用域为一个 `ToolRegistry`，即一个 run。 | `agent/tools/read_ledger.py` |
| **读前置（read-before-write）** | 覆盖已存在文件的条件：本 run 内有一次**完整读取**（第 1 行、不带 `limit`），且指纹未变。`limit` 或 `offset > 1` 的读取**不解锁**覆盖。 | [ADR 0004](decisions/0004-file-write-tool.md) |
| **`read_required`** | 目标文件已存在、但本 run 没有它的完整读取记录，因而拒绝覆盖的原因。 | `agent/tools/file_write_tool.py` |
| **`parent_missing`** | 新建文件时父目录不存在的原因；错误里提示用 `code_interpreter` 建目录（工具集里没有 shell）。 | `agent/tools/file_write_tool.py` |
| **`created`** | `file_write` 结果里区分"新建"与"覆盖"的标记；`created: true` 时不带 `original_file` 与 `gitDiff`。 | `agent/tools/file_write_tool.py` |
| **`content_changed`** | 覆盖时新内容是否与旧内容不同。内容相同**仍然写入**（不做"没变就不写"的优化），此字段只是如实报告。 | [ADR 0004](decisions/0004-file-write-tool.md) |
| **`write_bytes_atomic`** | 通过同目录临时文件 + `os.replace` 完成写入、并在交换前带上目标权限的共用实现。**硬链接不会跟随**。 | `agent/tools/file_bytes.py` |

## 命令执行（`exec`）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **`exec`** | 在平台 shell 里执行一条命令的工具。shell 按平台选择（Windows `pwsh` → Windows PowerShell → `cmd`；macOS `zsh` → `bash` → `sh`；Linux `bash` → `sh`），**永不选 Windows 的 WSL `bash`**。 | `agent/tools/shell_platform.py` |
| **containment（约束层）** | `exec` 对命令实际施加的限制：进程树终止 + 资源上限。**不是安全边界**，命令仍能读写进程用户碰得到的任何路径。结果里的 `containment.note` 固定说明这一点。 | [ADR 0005](decisions/0005-exec-tool.md) |
| **L1（资源与进程树）** | Windows：Job Object（`KILL_ON_JOB_CLOSE` + 进程数上限 + job 内存上限）；POSIX：新会话 + `killpg`。POSIX 侧没有内存上限。始终生效。 | `agent/tools/process_group.py` |
| **L2（完整性级别）** | 把命令的令牌降到低完整性，使它写不进未被授权的路径。机制**已验证可用**，但**未启用**：单独开启会让普通命令连临时目录都写不了，需先解决工作空间 ACL 授权与撤销。 | [ADR 0005](decisions/0005-exec-tool.md) |
| **L3（能力隔离）** | AppContainer / micro VM 级别的默认拒绝。未实现；Windows Sandbox 在开发机上是未启用的可选功能，且面向交互式桌面。 | [ADR 0005](decisions/0005-exec-tool.md) |
| **进程组（process group）/ Job Object** | 终止整棵命令树的**权威**句柄（POSIX 用 `killpg`，Windows 用 `TerminateJobObject`）。PID 文件只用于事后识别，不作为终止依据。 | `agent/tools/process_group.py` |
| **`persistedOutputPath`** | 输出超过响应预算（或为二进制）时，完整文本落盘后的路径；模型用 `read_file` 分段读回。 | `agent/tools/output_store.py` |
| **输出根（output root）** | `<temp>/ngy-py-agent/output/<workspace>/<scope>`，每次运行一个目录。由 `EXEC_OUTPUT_DIR` 覆盖。 | `agent/tools/output_store.py` |
| **只读附加根（`extra_read_roots`）** | 工作空间之外**可读但不可写**的目录，目前就是输出根。这是 [ADR 0001](decisions/0001-file-edit-tool.md) D3"读得到就能改"的显式例外；全局策略仍作用于它。 | `agent/tools/file_access.py` |
| **`read_only_root`** | 试图写入只读附加根时的拒绝原因。 | `agent/tools/file_access.py` |
| **`interrupted`** | `exec` 结果里表示命令**因超时被打断**的标记。它**不等于**"用户停止"：`stop` 是协作式的，杀不掉正在执行的命令。 | [ADR 0005](decisions/0005-exec-tool.md) |

## 文件编码

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **BOM 优先** | 文件带字节序标记时，BOM 决定解码方式并**覆盖**调用方传入的 `encoding`，因为它是文件自己的声明。 | `agent/tools/text_encoding.py` |
| **严格解码** | 用指定编码解码文件字节，失败即报错；**不使用 `errors="replace"`**，避免把损坏内容当作正文交给模型。 | `agent/tools/text_encoding.py` |
| **编码候选（`suggested_encodings`）** | 解码失败时给出的"能解码这些字节"的候选列表：BOM → `charset-normalizer` → 候选试探；`latin-1` 能解码任何字节，故排在最后并标注不构成证据。只作提示，**绝不自动应用**。见 [ADR 0002](decisions/0002-file-encoding.md)。 | `agent/tools/text_encoding.py` |
| **`decode_failed`** | 用给定编码无法解码文件字节的原因；错误里带 `encoding`、`byte_offset` 与 `suggested_encodings`。取代了原先的 `unsupported_encoding`。 | `agent/tools/text_encoding.py` |
| **`unencodable_text`** | 替换文本无法用目标编码表示（如 `😀` 之于 GBK）的原因；直接报错，不降级为 `?`。 | `agent/tools/text_encoding.py` |
| **`encoding_mismatch`** | 字节偏移换算与原始字节对不上（编码非双射或非规范）时拒绝写入的原因。 | `agent/tools/file_edit_tool.py` |

## 权限确认（P1）

| 术语 | 定义 | 位置 |
| --- | --- | --- |
| **P1 交互式确认** | 工具调用前问用户"能不能执行"的第一层权限。**协作式确认，不是安全边界**：一旦放行，被放行的动作不受任何新增限制（`exec` 放行一次即等于放行任意文件写入）。与 [ADR 0005](decisions/0005-exec-tool.md) 的 L1/L2/L3 是两条正交的轴：P 轴管"问不问"，L 轴管"能做到什么"。 | [ADR 0006](decisions/0006-tool-permission-confirmation.md) |
| **权限种类（permission kind）** | 工具声明的确认类别：`none`（从不询问）、`read`（仅敏感路径询问）、`write`、`exec`。在 `ToolSpec.permission` 声明，默认 `none`。 | `agent/tools/specs.py` |
| **门禁（gate）** | 权限判定本身。做在 `ToolRegistry.execute_tool` 这个**唯一收口**上，因此覆盖面是"全部工具"，而不是"我记得加过的那几个"。 | `agent/tools/registry.py` |
| **PermissionBroker** | 一个任务一个的权限代理：判定是否需要询问、发 `permission_request` 事件、阻塞该任务线程等待答复，并回收结果。由 `agent_loop` 注入 registry（工具自己拿不到 `EventSink`）。 | `agent/tools/permissions.py` |
| **无应答即拒绝（fail closed）** | 没人答复（超时，默认 120 秒）等于**拒绝**，不是放行。反向会让"用户不在电脑前"变成"默认放行一切"。 | [ADR 0006](decisions/0006-tool-permission-confirmation.md) |
| **停止优先于超时** | 等待期间收到任务停止请求立即中止等待，不等满超时。等待循环以 0.25 秒轮询 `should_stop`。 | `agent/tools/permissions.py` |
| **策略优先（policy first）** | `file_access` 已经硬拒绝的路径**不询问**：弹窗意味着"可能允许"，而这类路径点允许也过不去。判定顺序固定为"静态策略 → 权限模式 → 会话规则 → 询问"。 | [ADR 0006](decisions/0006-tool-permission-confirmation.md) |
| **确认模式（permission mode）** | `ask`（默认）/ `auto_approve` / `deny_all`。全局配置可被任务创建请求覆盖。`auto_approve` 是没有界面的部署方式唯一可用的模式，否则每个受门禁的调用都会阻塞到超时。 | `main.py` |
| **决策粒度（scope）** | `once`（仅本次）/ `session`（本任务内同一**工具 + 同一目标**自动放行，内存随任务结束消失）/ `always`（写入规则文件，跨任务生效）。未知取值一律报错，**不降级**。 | `agent/tools/permissions.py` |
| **权限规则（permission rule）** | 一条 `always` 决定的持久化记录，**刻意做窄**：一个工具 + 一个精确目标，不接受 `Bash(git push:*)` 这类模式。存在 `data/permission_rules.json`（`PERMISSION_RULES_CONFIG` 改路径）。文件缺失或损坏一律表示"没有规则"（即重新询问），**绝不表示"允许"**。 | `agent/tools/permission_rules.py` |
| **`persistent_rule`** | 命中一条权限规则、因而无需询问的原因。 | `agent/tools/permissions.py` |
| **规则写盘失败** | 调用照常放行，但 `scope` 退回 `once`：不声称一个并未写入的长期许可。 | `agent/tools/permissions.py` |
| **预览（`preview` / dry run）** | `ToolSpec.preview`：接收调用参数、**无副作用**地返回给对话框用的补充 `details`。`edit_file` 用它给出**写入前**的 `gitDiff`（复用 `_prepare_edit`，不需要第二条实现路径）。预览失败不构成拒绝，工具执行时会报准确错误。 | `agent/tools/specs.py`、`agent/tools/file_edit_tool.py` |
| **待确认（pending permission）** | 正在被等待的请求。`GET /api/tasks/{id}` 的 `pendingPermission` 字段给出它，因此断线重连的客户端也能渲染弹窗。 | `main.py` |
| **`WAITING`（任务状态）** | 任务被确认请求阻塞。它**仍属"进行中"**：事件推流与前端轮询都必须继续，否则客户端恰恰收不到那条需要它答复的请求。 | `agent/models.py` |
| **决策原因（reason）** | 审计用的判定结果：`not_required` / `auto_approved` / `deny_all` / `policy_denied` / `session_rule` / `user_allowed` / `user_denied` / `timeout` / `stopped` / `broker_error`。 | `agent/tools/permissions.py` |
| **`broker_error`** | 权限层自身出错。此时**拒绝**该调用（fail closed）并在文案里说明这是权限层的缺陷、重试无用——安全提示坏掉时应当响亮地失败，而不是静默全部放行。 | `agent/tools/registry.py` |
