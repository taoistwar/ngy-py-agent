# ADR 0001: `edit_file` 工具的设计

- 状态：已接受（Accepted）；D4 / D7 已被后续 ADR 取代（见文末「后续修订」）
- 日期：2026-09-18
- 相关：`agent/tools/file_edit_tool.py`、`agent/tools/file_read_tool.py`、`agent/tools/file_access.py`、`agent/tools/registry.py`、`agent/agent_loop.py`、`agent/models.py`

## 背景

Agent 目前只有 `read_file`，没有写能力。需要新增一个"精确替换"式编辑工具，输入 `file_path` / `old_string` / `new_string` / `replace_all`，并产出可被 UI 与外部消费者消费的结构化改动记录。

现有实现带来四个必须正面处理的约束：

1. **模型与 UI 共用一条通道**：`ToolRegistry.execute_tool` 的返回值既是 `messages` 里 `role="tool"` 的内容（模型看到），又是 `ToolResultData.result` → `TOOL_RESULT` 事件 → SQLite → events API → UI。二者无法自然分离。
2. **`read_file` 的输出受 token 预算强约束**：`check_text` 超限即报错。而"原文全文 + patch + gitDiff"会绕过这个约束。
3. **`file_access.py` 是"读"策略**：函数名 `resolve_read_path`、文案 "…can be read"、`allow_dirs` 的语义是"仅这些目录可读"，理由常量是 `outside_allow_dirs`。写操作直接复用会让语义含糊。
4. **`read_file` 会规范化换行**：读取时 `raw.rstrip("\r\n")`，再用 `"\n"` 拼接。模型据此重建的 `old_string` 对 CRLF 文件**天然不是字节一致的**。

## 决策

### D1. 双通道：成功摘要给模型，结构化记录走独立事件

- **模型**：成功时只收到一句话，例如 `The file {path} has been updated successfully`。
- **UI / 外部消费者**：完整的 `original_file` / `structured_patch` / `gitDiff` 通过**新事件类别 `file_edit`** 发送，与 `TOOL_RESULT` 解耦。

实现契约：工具回调返回一个 `ToolOutcome`（`model_text` + 可选事件类别/标题 + `details`）。`ToolRegistry.execute_tool` 对 `ToolOutcome` **原样透传**（不 `json.dumps`），由 `agent_loop` 拆分：`model_text` 进 `messages`，`details` 作为事件 `data` 发送。

理由：模型不需要（也不该）看到原文全文；UI 需要完整记录用于展示与审计。把两者塞进同一个 JSON 是最初 `read_file` 的做法，但会让模型上下文被 UI 数据污染。

### D2. `original_file` 不设上限

按规格返回替换前全文，**不做截断/省略**。

已知风险（接受）：全文会随 `file_edit` 事件写入 SQLite 的 `events.data`，并通过 events API 返回。超大文件会导致单条事件行巨大，进而影响分页与前端渲染。若日后成为问题，优先方案是新增"事件体量上限 + 落盘引用"，而不是改本决策。

### D3. 写权限复用读策略

`file_access.py` 新增 `resolve_write_path`，**沿用同一套 `deny_dirs` / `deny_files` / `allow_dirs` 规则与工作空间根约束**：读得到的文件就能改。

理由：只有一套策略时，用户心智最简单，也不会出现"能读不能写"的意外组合。代价是文案与理由常量需要从"读"泛化为"访问"（`outside_allow_dirs` 等复用），命名上以 `resolve_write_path` 明确区分入口。

### D4. 编码：仅 UTF-8（含 BOM），换行保真

- 只接受能**严格解码**为 UTF-8 的文件；解码失败即报错，不做 `errors="replace"`。
- 保留文件原有的行尾风格（CRLF / LF / CR）；写入时不统一成 `\n`。
- BOM：识别并**原样保留**。

理由：编辑是破坏性操作，`errors="replace"` 会静默损坏非 UTF-8 字节（`read_file` 可以容忍，因为只读）。非 UTF-8 编码显式拒绝，好过悄悄改坏。

### D5. 严格字节匹配

`old_string` 必须与文件字节**精确一致**，不做任何换行规范化。附加规则：

- `old_string` 为空串 → 报错（否则会命中任意位置）。
- `old_string == new_string` → 报错（无意义改动）。
- 匹配数 `0` → 报错。
- `replace_all=false` 且匹配数 `>1` → 报错，并在错误文案里**明确要求提供更多上下文**（"请多给点上下文"）。
- `replace_all=true` → 替换全部匹配。

### D6. `read_file` 改为保留原始换行（字节一致）

为了兑现 D5，`read_file` 不再把行尾统一成 `\n`：输出仍然是 `N<TAB>` 前缀 +正文，但**正文之间保留文件原本的行尾**，使得"去掉 `N<TAB>` 前缀后的拼接结果"与该行区间的原始字节一致。

影响：LF 文件仅多保留"文件末尾本就存在的换行"；CRLF 文件不再被转成 LF。这**改变了 `read_file` 的既有输出**，需要同步更新 `read_file` 的说明与测试。

理由：D5 选了严格字节匹配，就必须让模型拿到的文本能反推出精确字节；否则在 Windows 项目上多行编辑必然失配，工具形同虚设。

### D7. `gitDiff` 纯 Python 生成；`structured_patch` 用 3 行上下文

- `gitDiff` 自建 unified diff（对齐 git 格式），**不依赖本机 git 可执行文件**，也不需要临时文件。
- `structured_patch`：每处 hunk 上下各 **3 行**上下文（与 git 默认一致）；多匹配时，每处 hunk 的 `newStart` 按"**已应用前面 hunk 之后的新文件**"计算（unified diff 语义）。

### D8. 失败也走双通道

失败（不匹配 / 多匹配 / 文件不存在 / 编码不支持 / 越权）时：

- **模型**：收到可读的 `error` 文案（可据此重试，例如补上下文后重试），**不抛异常**。
- **UI**：拿到完整 `details`（含 `reason`、`match_count` 等）。

理由：本工具的主要失败模式是"模型可以自我修正的"（上下文不够、路径写错），把错误变成异常会让该步骤直接失败、模型的纠错能力被浪费。这与 `registry.execute_tool` 注释里"异常应抛出"的一般原则**有意不一致**，理由如上；`read_file` 也采用同类策略。

## 后果

- `ToolOutcome` 成为"工具结果分流"的通用契约，后续需要"模型摘要 + 富记录"的工具可复用。
- 新增事件类别 `file_edit` 需要前端 i18n 与标签样式补齐（否则显示为"未知"）。
- `original_file` 无上限（D2）是**已知且被接受**的风险。
- 本工具**无法创建新文件**（`old_string` 必须已存在）。创建能力留给未来的 `write_file` 工具，不在本次范围。
- D5 与 D6 是**成对**的：只保留其一都会让工具在 CRLF 项目上失效，改动时必须一起评估。

## 备选方案（未采用）

- **结构化记录挂到 `TOOL_RESULT`**：改动最小，但会让 UI 数据继续与模型输出耦合，且模型侧需靠约定忽略大字段。
- **`details` 落盘为 `data/edits/*.json`**：能避免 SQLite 膨胀，但引入文件生命周期与清理问题，events API 也要多一跳。
- **规范化匹配 + 写回保真**：实用性最好，但违背"严格字节匹配"，且会让"匹配到的位置"与用户看到的字节不一致。
- **调用 `git diff --no-index` 生成 `gitDiff`**：最贴近真实 git 输出，但要求环境有 git、需要临时文件、且对未跟踪文件行为依赖 git 版本。

## 后续修订

本 ADR 记录的是 2026-09-18 的决定。以下条目后来被改动，理由见对应 ADR：

- **D4（仅接受 UTF-8）** → 由 [ADR 0002](0002-file-encoding.md) 取代：改为支持任何可解码的编码，写入改为字节级拼接，解码失败不再直接拒绝而是给出候选编码让模型重试。
- **D7（补丁语义）** → 由 [ADR 0003](0003-edit-write-and-patch.md) 取代：补丁改为整行表示，`gitDiff` 保留 `\r` 以保持可 `git apply`。
- **D6（`read_file` 保留原始换行）**：结论不变，但把"行"的终止符收紧为 `\n` / `\r\n` / `\r`（原先补丁侧用的是 `str.splitlines()`，会把换页符当换行），并在结果里新增 `encoding` 与 `bom`。
- **D2（`original_file` 不设上限）**：确认维持不变。
- **D5（严格字节匹配）**：结论不变，实现由"先解码再按字符匹配"明确为"按前缀编码换算字节偏移并校验"。
