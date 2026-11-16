# ADR 0026: `delete_file` 工具的设计

- 状态：已接受（Accepted）
- 日期：2026-11-16
- 相关：`agent/tools/delete_file/`、`agent/tools/file_limits.py`、`agent/tools/read_ledger.py`、`agent/checkpoints/store.py`、`agent/tools/permissions.py`
- 前置：[ADR 0004](0004-file-write-tool.md)（读前置）、[ADR 0006](0006-tool-permission-confirmation.md)（权限确认）、[ADR 0020](0020-checkpoint-rewind.md)（改动快照）

## 背景

工具集里有"建"（`write_file`）和"改"（`edit_file`），没有"删"。想删一个文件，模型只剩两条路：`exec_command`（`rm` / `Remove-Item`）或 `code_interpreter`（`os.remove`）。两者都**完全绕过**文件层的四道约束：

- 工作空间天花板与全局 `deny_files` / `deny_dirs` / `allow_dirs`（`file_access`）；
- 只读附加根（输出、结果、transcript 三类）；
- 权限确认里的目标：确认框只能显示"要跑这条命令"，显示不出"要删哪个文件"；
- 改动快照：命中的是整树扫描，事件里只留一条命令，事后看不出删了什么。

也就是说，文件集里最不可逆的操作，恰好是唯一没有任何工具级保护的。本 ADR 记录补上它时的取舍。

## 决策

### D1. 只删单个常规文件

一次调用删一个普通文件。目录一律拒绝（`not_a_file`），并在错误里指向真正能删树的工具：`code_interpreter`（`shutil.rmtree`）。

不做 `recursive` 开关：`recursive: true` 是"把这个目录下的东西全删"的另一种说法，它的失败模式（路径少写一层、`..` 拼错）比单文件删除大一个数量级，而现有工具已经能做这件事。同理，本工具也不接收通配符——删多个文件是模型的多次调用，每次都要过确认。

### D2. 删除前置与 `write_file` 同源：读过 + 没变，但有一处诚实例外

删除前必须同时满足：本 run 内对该文件有过一次**完整读取**（第 1 行、不带 `limit`），且 `st_mtime_ns` + `st_size` 与那次读取一致。不满足分别报 `read_required` 与 `file_changed`——与 ADR 0004 D2 同一套判据、同一个账本，因此"没见过的文件不会被摧毁"对删除同样成立。

两条补充规则：

- **空文件不需要读**：0 字节时"内容"已经没有什么可保护的，`content_verified` 直接为真。
- **超过 `read_file` 上限（`MAX_FULL_READ_BYTES`，256 KB）的文件不要求读**，结果里标 `content_verified: false`。这是本 ADR 里唯一"放松"的地方，理由是硬拒会更不安全：这种文件**读不全**，硬拒等于告诉模型"这个工具删不了"，它会退回 `exec_command` / `code_interpreter`——而那两个工具绕过本 ADR 背景里列的全部四道约束。放松之后删除仍要过确认，且在应用里可以回退（D6）。

已知的洞，明写出来而不是假装没有：**小文件也可能读不全**——单行超长的压缩产物会在 `read_file` 的 token 预算上失败，于是账本没有记录，删除被拒。这类文件本来就该由 `exec_command` / `code_interpreter` 处理（它们是构建产物，不是项目内容），但错误文案里不诱导模型绕路，只要求先读；读不动时模型应当把情况告诉用户。

### D3. 路径解析走 `resolve_write_path`

删除是**修改**工作空间，所以用写侧解析：工作空间天花板（`outside_workspace`）、全局策略（`deny_file` / `deny_dir` / `outside_allow_dirs`）、只读附加根（`read_only_root`）全部生效。不传 `create_default`：删除不该顺手把目录造出来（那是 `write_file` 新建文件的特例，ADR 0007 D4）。

路径不跟随链接之外的特例：解析仍是一次 `resolve()`，与另外三个文件工具完全一致——三者语义不能分叉（ADR 0007）。

### D4. 权限种类是 `write`，但 scope 收窄为 `once` / `session`

声明 `permission=PERMISSION_WRITE`，参数名必须是 `file_path`：权限门按这个字段解析目标（`permissions._target`），否则确认框拿不到"删哪个文件"。

**scope 只给 `once` 与 `session`**，不给 `always`。持久化规则是"工具 + 精确目标"（ADR 0006 D8），而删除执行完那个目标就不存在了：一条 `delete_file @ <path>` 的长期规则会活过它当初批准的文件，将来在同一路径重新出现的文件会被静默删除。这与 `write_stdin` 收窄 scope 是同一条理由（ADR 0008），只是原因不同——那里是目标永远不重复，这里是目标被自己销毁。

配套改 `permissions._build_request`：`write` 类工具的默认分支会把参数当成 `old_string` / `new_string` 并显示成 "Edit"；删除没有内容可显示，必须是 `Delete <绝对路径>`。

### D5. 独立事件类别 `file_delete`

不复用 `file_write`：事件标题会变成"写入了文件"，而文件刚刚消失；也不复用 `file_edit`。历史里"被覆盖"和"被删除"是两件事，一条分不清的审计记录等于没有记录（与 ADR 0004 D7 同一条理由）。

事件 `details`：`file_path`、`file_bytes`、`content_verified`；失败时另带 `reason` 与 `error`。

### D6. 进入改动快照，因此删除可回退

`CheckpointStore.FILE_TOOLS` 增加 `"delete_file": "file_path"`。`begin` 在删除前记下基线，`end` 用 `git add -A -- <path>` 暂存（`-A` 会把删除也暂存），于是任务的改动列表里出现一条 `deleted`，撤销时 `git checkout <base> -- <path>` 把它恢复（ADR 0020）。不接这一步的话，删除会像 `exec_command` 那样只留下"某次命令改过整棵树"，回退承诺就变成假阳性。

### D7. 删除后清掉账本记录

`ledger.forget(path)`。指纹描述的是已不存在的文件；留着它，同一路径上重新出现的文件就无需读取即可被删除，D2 的保护会在"删了又建"的循环里失效。

### D8. 失败一律回 `ToolOutcome`，原因码可判别

与另外两个文件工具一致：不向 registry 抛异常，模型收到 `Error: ...` 一行，`details.reason` 取值为 `invalid_argument` / `not_found` / `stat_failed` / `not_a_file` / `read_required` / `file_changed` / `delete_failed`；`AccessDenied` 的原因码原样透传。

删不存在的文件报 `not_found` 而不是静默成功：路径写错时必须让模型知道，提示里点名 `glob`。幂等的"删除已是空"看起来友好，代价是把打错的路径藏起来。

## 后果

- 模型侧只看到一行摘要（`The file X has been deleted successfully.`），结构化记录走事件，沿用 ADR 0001 的双通道契约。
- `write_file` 的 `content: ""` 不再有歧义：要文件空着用它，要文件消失用本工具。
- 前端需要为新事件类别补 i18n 与标签样式（已补 `category_file_delete`、`fileDelete` / `fileDeleteFailed` 词典条目与 `.tag.file_delete`）。
- 新增共享常量模块 `agent/tools/file_limits.py`：`read_file` 与 `delete_file` 必须用同一个 256 KB 上限，而工具包之间不许互相 import（`agent/tools/__init__.py`）。
- 小文件读不全（token 预算）时删不掉，见 D2 的已知洞。
- 软链接仍按"解析后的目标"处理：链接指向工作空间内时，删除的是目标而不是链接本身。与另外三个工具一致，属 ADR 0001 "解析一次"的既有取舍。
