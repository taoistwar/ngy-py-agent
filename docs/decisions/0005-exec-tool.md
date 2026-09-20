# ADR 0005: `exec` 工具与沙箱分层

- 状态：已接受（Accepted）
- 日期：2026-09-20
- 相关：`agent/tools/exec_tool.py`、`agent/tools/process_group.py`、`agent/tools/shell_platform.py`、`agent/tools/output_store.py`、`agent/tools/file_access.py`
- 前置：[ADR 0001](0001-file-edit-tool.md)、[ADR 0002](0002-file-encoding.md)、[ADR 0004](0004-file-write-tool.md)

## 背景

Agent 需要执行外部命令（跑测试、git、构建）。这与前三轮建立的"边界"直接相关，因此在写代码前先做了一轮事实核查，结论是**这份规格里的五个前提在本仓库不成立**：

| 规格里的前提 | 核查结果 |
| --- | --- |
| 存在可被 `dangerouslyDisableSandbox` 禁用的沙箱 | 全仓库 `sandbox` 0 命中，没有任何沙箱实现 |
| `description` 给权限系统看 | 没有权限系统、没有交互式确认；任务跑在守护线程里，没有人可以问 |
| `run_in_background` / `interrupted` 需要进程管理 | `agent/` 下 `Popen`/`terminate`/`kill` 0 命中；`stop` 是**协作式**的，正在执行的命令杀不掉 |
| 大输出持久化后模型看得到 | `read_file` 受工作空间约束，读不到工作空间外的路径 |
| `isImage` | provider 层没有 vision 支持，字段没有消费者 |

最关键的一条：**`code_interpreter` 已经提供了不受约束的任意执行**。实测它可以 `subprocess.run(shell=True)`、写工作空间之外的路径、读 `os.environ`（本机就有 `ANTHROPIC_API_KEY`）、联网，而它的参数只有 `code`，不经过 `file_access` 策略。

## 决策

### D1. 不与 `code_interpreter` 收敛；把它记为**显式接受的风险**

决定（选 b）：`exec` 与 `code_interpreter` 并存，后者的问题后续专门处理。

后果必须写明，不能让读者以为这套边界是完整的：

- `exec` 的进程树/资源约束**只约束 `exec`**。模型用 `code_interpreter` 一步即可绕过工作空间约束、访问策略、编码保证与并发复核。
- 因此本 ADR 中出现"containment"一词时，指的是**资源与进程生命周期**，不是文件或网络隔离。
- 相关工具的用户可见文案不得宣称"已沙箱化"。`exec` 在结果里固定上报 `containment.note`，原文包含 "not a security boundary"。

### D2. 分层：L1 已实现，L2 机制已验证但**未启用**

**L1 进程树 + 资源上限（已实现，始终生效）**

- Windows：Job Object，`KILL_ON_JOB_CLOSE` + `ActiveProcessLimit`（默认 64）+ job 内存上限（默认 2 GiB，可用 `EXEC_ACTIVE_PROCESS_LIMIT` / `EXEC_JOB_MEMORY_LIMIT_MB` 覆盖）。
- POSIX：`start_new_session=True` 新建会话/进程组，用 `killpg` 终止。
- **实测**：一次 `TerminateJobObject` 杀掉了子进程与其孙进程（pid 30188 / 39124 都变为不存在），不需要 `taskkill /T`，也不需要自己记账 PID。
- POSIX **不做内存上限**：per-child 限制只能靠 `preexec_fn`（在多线程进程里官方标注不安全，而本项目的任务都跑在线程里）或 Linux 专有的 `resource.prlimit`。宁可不做也不假装做了。

已知限制（诚实记录）：进程是在创建**之后**才加入 Job 的，因此理论上存在一个"命令在加入 Job 前就 spawn 出孙进程"的窗口。实际窗口在毫秒级（新进程要先把镜像加载起来），但这不是一个证明。要彻底关掉需要 `CREATE_SUSPENDED` + 原生 `CreateProcess` 或枚举线程后 `ResumeThread`。

**L2 低完整性令牌（机制已验证，未启用）**

实测结果：进程把自己的令牌完整性级别从 Medium（S-1-16-8192）降到 Low（S-1-16-4096）**成功**，之后对用户临时目录的写入被拒（`Permission denied`），新 spawn 的子进程同样无法写入。

但同一实验暴露了**为什么不能默认开启**：低完整性进程连自己的临时目录都写不了，Python 连启动都失败（`No usable temporary directory found`）。要让 L2 可用，必须：

1. 给低完整性 SID（`S-1-16-4096`）在工作空间与一个专用临时目录上授予写权限（ACL，检查 `icacls ... /grant *S-1-16-4096:(OI)(CI)M`），
2. 在命令结束后**撤销**该授权，
3. 处理"我们崩在中间"的残留授权。

那是对用户文件系统的持久性改动，还顺带把工作空间对"任何低完整性进程"开放。因此 L2 记为一个**独立子项目**，而不是本次顺手打开的一个开关。届时需要先回答：是否接受为工作空间加 ACL？

（实现配方保存在此，避免下次重新踩坑：`OpenProcessToken` 的句柄必须声明 `restype`/`argtypes`，否则 64 位句柄被截断成 `ERROR_INVALID_HANDLE`；`TOKEN_MANDATORY_LABEL` 的 SID 必须放在结构体**之后**，放在前面会被 `Attributes` 字段覆盖，报 `ERROR_INVALID_SID`。）

`dangerouslyDisableSandbox` 因此有了精确含义：**跳过 L2（以及未来的 L3）能力层，L1 不可关闭**。

**L3 能力隔离（AppContainer / micro VM）：不做**

- Windows Sandbox 是本机（Windows 11 Pro，build 26200）**未启用**的可选功能（`WindowsSandbox.exe` 不存在），且它面向交互式桌面会话、启动成本按秒与数百 MB 计，不适合高频工具调用。
- AppContainer 是真正默认拒绝（文件/网络/注册表）的进程级隔离，内置免费，代价是要给 AC SID 授权 ACL 且部分 CLI 工具不兼容。若将来要做强隔离，正确形态是**可选的执行后端**，不是默认路径。

### D3. 哪个 shell，以及不选哪个

按平台优先回退，第一个命中者胜出：

- Windows：`pwsh`（7+）→ Windows PowerShell → `cmd`
- macOS：`zsh` → `bash` → `sh`
- Linux 及其它 POSIX：`bash` → `sh`

**Windows 上永不选 `bash`**：本机的 `C:\Windows\System32\bash.exe` 是 WSL 启动器，命令会跑在**另一个文件系统**里，"同一个路径指向不同文件"是最难排查的一类错。MSYS/Git 的 `sh` 因路径转换同理排除。

描述按平台生成（`build_exec_description`），结果里报告**实际使用的 shell 与版本**（本机实测 `pwsh 7.4.20`），因为模型必须知道自己在写哪种方言（`$env:FOO` 还是 `$FOO`）。参数集合跨平台保持一致，只有描述不同。

### D4. 大输出落系统临时目录 + **只读附加根**

沿用参考设计：输出超过响应预算就落盘，模型拿到短预览 + 路径，用 `read_file` 分段读回。布局 `<temp>/ngy-py-agent/output/<workspace>/<scope>/<name>`，`<scope>` 是会话/任务 id。阈值用现有的 `token_budget`（不是字符数，保持系统里只有一个预算概念），预览保留 2000 字符。

**这是对 ADR 0001 D3 的显式例外。** D3 的规则是"读得到的文件就能改"，理由是避免出现"能读不能写"的意外组合；而输出目录恰恰要反过来。于是 `file_access` 引入 `extra_read_roots`：其中的路径**可读、不可写**（写报 `read_only_root`），并且**全局策略依然生效**——`deny_dirs` 或非空 `allow_dirs` 仍可让它不可达。这是有意的取舍：宁可让"策略配置后读不到输出"，也不悄悄放宽用户设定的访问策略。

### D5. `description` 是**预留**字段，今天不阻塞任何东西

参考文档描述的是目标设计：`description` 有三个消费者——权限对话框展示、分类器输入、`allow` 规则生成（`Bash(git push origin main:*)`）。本仓库这三个都不存在。

因此：字段保留、写进事件供审计，但工具描述里**不写**"给权限系统看"，而是说明"记录到审计轨迹，不会暂停执行"。权限系统（对话框 + 分类器 + 规则存储 + 任务挂起/恢复）是独立项目；在它有真实消费者之前，任何"会有人审批"的暗示都会误导模型。

> **已被 [ADR 0006](0006-tool-permission-confirmation.md) 部分取代（2026-09-20）**：P1 交互式确认落地后，D5 预言的第 1 个消费者（**权限对话框展示 `description`**）已经存在，且 `exec` 会真的暂停等待答复。因此本节"工具描述不写'给权限系统看'"以及 `exec_tool.py` 里"it does not pause execution"的措辞**都已不成立并被修改**。仍成立的部分：分类器与 `allow` 规则生成未实现，持久化规则见 ADR 0006 D8。

### D6. 超时、后台、中断

- `timeout` 单位是**毫秒**（默认 120000，上限 1800000），schema 里 `minimum: 1000`。毫秒是个陷阱（模型可能按秒写 120 → 120 毫秒），所以描述里重复强调 MILLISECONDS，并用最小值兜底。
- `interrupted` **只表示超时**。`stop` 是协作式的，杀不掉正在执行的命令，所以它不代表"用户停止"；取消机制（把进程句柄登记到任务上）记为后续工作。
- `run_in_background` 只做轻量版：启动、返回 pid 与日志路径、写 PID 文件；**明确不保证**任务结束或重启后回收。进程组/Job Object 仍是权威（`_BACKGROUND` 持有句柄正是为了不因 GC 关掉 Job 而误杀）。

### D7. 环境变量中的凭据默认不下发

命令拿到的环境里会剔除名字像凭据的变量（`API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `CREDENTIAL`），并在结果里报告剔除数量（不报告名字与值）。实测 `$env:ANTHROPIC_API_KEY -ne $null` 返回 `False`。

**这是纵深防御，不是边界**：`code_interpreter` 仍能读到它们（见 D1）。设 `EXEC_PASS_SECRET_ENV=1` 可关闭该行为，供确实需要把密钥交给命令的场景。

### D8. 事件与载荷

- 新事件类别 `exec`（前端已补 `category_exec` 与 `.tag.exec`）。
- 命令输出**无上限**（与源文件不同：一条 `yes` 可以产出任意多字节），所以进入事件 `details` 的 `stdout`/`stderr` 被截到 64 KiB，完整文本落盘并在 `persistedOutputPath` 给出；`output_truncated` 标记是否发生过截断。这是对 ADR 0001 D2"不设上限"的**有意偏离**，理由是两类载荷的风险量级不同。
- 二进制输出不进模型上下文：落盘 + 说明。
- `isImage` **不做**（没有消费者）。真二进制输出（含 NUL）走上面的落盘路径。

## 后果

- 模型侧只看到可读文本（exit code、stdout、stderr、是否需要去读文件），UI 通过 `exec` 事件拿到结构化记录，沿用双通道契约。
- 命令**不受** `file_access` 策略约束（它就是个 shell）。这是 D1 的直接后果，不要试图在 `exec` 上假装有路径管控。
- 后台命令在 agent 进程退出时会随 Job 句柄关闭而被终止（`KILL_ON_JOB_CLOSE`）——这是特性，不是缺陷：不留孤儿进程。
- 输出目录是 scratch，**没有任何自动清理**；由操作系统临时目录清理机制处理。

## 备选方案（未采用）

- **用 micro VM（Windows Sandbox）做默认执行环境**：本机未启用，面向交互式桌面，每次调用起一台机器，成本与收益不成比例。
- **默认开启低完整性**：实测会让普通命令不可用（连临时目录都写不了），且需要持久修改工作空间 ACL。
- **把追加/文件写入也交给 shell**：会让前三轮的工作空间约束、编码保证、并发复核与事件记录全部失效（见 [ADR 0004](0004-file-write-tool.md) 的「追加（待定）」）。
- **在 `exec` 上套用 `file_access` 的路径策略**：无法强制执行（命令可自行读写任意路径），假装有管控比不做更糟。
