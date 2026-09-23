# ADR 0009: `exec_command` 的 `tty`（伪终端）

- 状态：已接受（Accepted）
- 日期：2026-09-23
- 相关：`agent/tools/pty_session.py`、`agent/tools/process_group.py`、`agent/tools/exec_command/`、`agent/tools/write_stdin/`、`pyproject.toml`
- 前置：[ADR 0005](0005-exec-tool.md)、[ADR 0006](0006-tool-permission-confirmation.md)、[ADR 0008](0008-write-stdin-tool.md)

## 背景

ADR 0008 把 PTY 明确留作"后续独立子项目"，理由是"平台差异大、失败模式多"。这一轮落地它，依据是参考实现（Codex）的 `tty` 参数：

```rust
(
    "tty".to_string(),
    JsonSchema::boolean(Some(
        "True allocates a PTY for the command; false or omitted uses plain pipes.".to_string(),
    )),
),
```

`tty=true` 在参考实现里走 `codex_utils_pty::pty::spawn_process`（Windows 是 ConPTY 的 `CreatePseudoConsole`，POSIX 是 `openpty`），`tty=false` 走管道；**`tty` 直接决定 `stdin_open`**，也就是"这个会话能不能被打字"。

本仓库的情况与参考不同，决定了不能照抄：

| 参考实现 | 本仓库 |
| --- | --- |
| 没有前台概念：命令没结束就返回 `session_id` | 前台阻塞等结果，后台返回 `session_id` |
| 非 PTY 会话的 stdin 是关闭的，只允许 Ctrl-C | 后台会话**本来就有**可写 stdin（管道），`write_stdin` 一直能打字（ADR 0008 的刻意偏离） |
| POSIX PTY 设置控制终端（`setsid` + `TIOCSCTTY`） | 本仓库拒绝 `preexec_fn`（任务都跑在线程里，`process_group` 有明文理由） |
| 输出由内存 channel/broadcast 汇聚 | 后台会话的输出契约是"日志文件 + 已读偏移"，`process_store.read_new` 按字节偏移读 |

本机事实（写这份 ADR 时实测）：Windows 11 build 26200，Python 3.12.10，`pywinpty` 未安装（本轮装入 3.0.5），`uv.lock` 中原本没有任何 PTY 相关包。

## 决策

### D1. 一个参数覆盖两种模式，但前台 tty 必须写明"没人能回答它"

`tty` 对前台与后台都生效（它在 spawn 层，不是会话层）。前台 tty 的价值不是交互，而是**让程序以为自己在跟终端说话**：颜色、进度条、不缓冲输出、以及"没有终端就拒绝运行"的 CLI（`gh`、部分 `npm` 子命令）。

代价写进工具描述，因为模型一定会踩：

- 前台 tty 命令卡在提示上时**无法被回答**（前台在等它结束），要交互就必须配 `run_in_background`；
- 不引入参考实现那种"参数互斥"校验，只在描述里说清。

前台 tty 的等待因此不是 `communicate`：管道没了，改为"轮询子进程 + 有界排干"（见 D5）。

### D2. Windows 用 `pywinpty`（ConPTY），POSIX 用标准库 `pty`

- **Windows**：新增依赖 `pywinpty>=2.0.0; sys_platform == "win32"`（实测 3.0.5）。它是参考实现 `portable-pty` 的同一层封装，直接调 `CreatePseudoConsole`。用环境标记而不是可选 extra：Linux 服务器不需要它，也不该装它；缺依赖就是不可用，不是"静默退回管道"。
- **POSIX**：`pty.openpty()` + `subprocess.Popen(start_new_session=True)`，三个标准流都接 slave 端。

**POSIX 不设控制终端。** 让子进程拿到控制终端需要在子进程里 `setsid` + `ioctl(TIOCSCTTY)`，唯一入口是 `preexec_fn`，而 `process_group` 已经明文拒绝它（多线程进程里 fork 不安全，而本项目每个任务都跑在线程里）。子进程仍然 `isatty() == True`，代价写在 D6（Ctrl-C 不能靠终端驱动投递）。这是本 ADR 里最"不完整"的一处，明写出来而不是假装做到了。

### D3. 终端的输出整形：stderr 合并、模型看 LF、落盘留原始字节

终端只有一条流，所以：

- `details["stderr"]` 恒为空串，`details["tty"] = true` 说明原因，避免消费者以为诊断信息丢了；
- **模型可见文本**把 `\r\n` 归一为 `\n`（终端每行都带 CRLF，进上下文纯属噪声）；
- **落盘的完整文本保留原始字节**：文件声称是命令的输出，就应当是命令产出的字节（`_render_foreground_text` 同时产出这两个版本）。

### D4. 后台 tty 需要泵线程（定向修订 ADR 0008 D3）

终端没法像管道那样被重定向进日志文件，所以输出只能读出来再写进去：每个 tty 会话由一个读线程把 master 泵进**原有的日志文件**，`process_store` 的"偏移 + 增量"契约一字未改。

这是对 ADR 0008 D3"不加 reader 线程"的定向修订，范围被刻意压到最小：**管道会话仍然没有 reader 线程**，只有 tty 会话有。

### D5. 终端的生命周期顺序是固定的：settle → close → join

实测两件事，决定了这套顺序不能改：

1. `read` 在两个平台都**没有超时**，而且**子进程退出后不会结束**（pywinpty 的 socket 不关就一直阻塞；POSIX 要等 slave 端全部关闭）；
2. 数据可能在子进程退出后仍留在终端缓冲里。

因此 `RunningCommand.release()` 固定为：

```text
reader.settle()      # 排干尾巴：安静一小段（有上限）即认为读完
terminal.close()     # 唯一能结束阻塞读的手段
reader.join()        # 线程收口
```

少了 `settle` 会丢日志尾部；少了 `close` 会永久泄漏一个线程；顺序颠倒同理。`close` 在 Windows 上还会顺带停掉仍持有控制台的幸存者——与 `KILL_ON_JOB_CLOSE` 同一语义，不另造一套。

命令死活仍然只由 `process.poll()` 判定，读线程不参与判定（"读到 EOF"不等于"命令退出"）。

### D6. 中断保持带外，不照抄参考实现

参考实现对 tty 会话是把 `\u0003` 原样写进终端，靠**控制终端**的驱动投递 SIGINT。我们按 D2 不设控制终端，终端驱动没有前台进程组可投递，写 `\u0003` 在 POSIX 上不会产生 SIGINT（最坏情况被驱动吞掉，程序什么也收不到）。

所以 `chars == \u0003` 一律走带外 `process_group.interrupt()`（POSIX `killpg(SIGINT)`，Windows Job 终止），tty 与管道完全一致。这是一处**有意的分歧**，不是遗漏。

### D7. 输入收口在 `RunningCommand`，Windows 上 `\n` 转 `\r`

tty 命令没有 `process.stdin`，所以输入不能再从消费者那里直接摸流：`RunningCommand.has_stdin()` / `write_input()` 是唯一入口，管道与终端各自实现（`write_stdin` 据此改写，行为不变）。

Windows 写路径把 `\n` 转成 `\r`（`\r\n` 也归一为 `\r`）。实测：ConPTY 下写 `\n` 只有回显、**不提交那一行**，写 `\r` 才是回车。

### D8. L1 约束不变，tty 不开特例

tty 命令照样按 pid 挂进 Job Object（进程数 + 内存上限 + 整树终止），拿不到 job 就退化成 `KIND_PLAIN`，与管道路径的既有降级一致。`containment` 报告、`containment.note`（"not a security boundary"）一字未改。

### D9. 拿不到终端就报错，不静默降级，也不做开关

参考实现用 `Feature::UnifiedExecTty` 门禁 `tty`（关掉时把属性从 schema 里删掉，运行时回一句"TTY execution is disabled by config"）。本仓库不做开关：`tty` 永远在 schema 里，拿不到终端时以 `ExecError(reason="tty_unavailable")` 明确报错。

**绝不静默退回管道**：模型要终端是因为程序在两种情况下表现不同，退回管道会让它继续以为程序看到了 TTY——与 ADR 0005 D1"不假装有边界"是同一条原则。

### D10. 尺寸固定 24×80，不做 resize

参考实现的 `TerminalSize::default()` 就是 24×80（`codex-rs/utils/pty/src/process.rs:63-67`），另有 `command/exec/resize` 接口。这里只取默认值：模型看不见终端宽度，给它 cols/rows 只会让它猜；`write_stdin` 也没有 resize 入口。

## 后果

- 模型可以显式要求终端，并按需在 `run_in_background` + `write_stdin` 里交互；不做终端时行为与之前**逐字一致**（管道路径未改）。
- `details` 新增 `tty`（两种模式都有），`pidFile` 记录 `tty`，`write_stdin` 的结果也带 `tty`。
- 新增依赖一个（仅 Windows），新增共享模块一个（`pty_session.py`）。
- 已知限制（明写，不掩盖）：
  - **不剥离 ANSI**。ConPTY 启动时会先吐一小段握手转义（实测 `\x1b[1t\x1b[c\x1b[?1004h\x1b[?9001h`，以及 pwsh 的标题序列 `\x1b]0;…\x1b\`）。参考实现靠"回答终端查询"消化它们，这里没做，所以输出会带这层噪声。工具描述里提前告知模型，避免它把噪声当输出。
  - 终端输出由 `pywinpty` 按 UTF-8 解码（`read` 返回 `str`），因此 Windows 上不经过本仓库的编码探测路径（`decode_capture`）；`pty_session` 把 `str` 编回 UTF-8 字节，保持整条流水线仍是字节。
  - Windows 上 `pwsh` 会把"原生命令写了 stderr 且非零退出"统一变成退出码 1（实测：管道与终端**都是 1**）。这是 shell 的策略，不是终端的行为，因此没有为此加特例，也没有按参考实现把信号死亡映射成 `128+N`（POSIX 侧无法在本机验证）。
- 本机实测记录的边界：`PtyProcess.read` 在子进程退出后不会 EOF（所以 D5 的 close 是必需的）；`setwinsize` 可用但我们不用。

## 备选方案（未采用）

- **用 ctypes 自己写 ConPTY（`CreatePseudoConsole` + `CreateProcessW` + 两个管道）**：把参考实现用一个 crate 换来的东西手工重做，附带句柄/线程/关闭时序的失败模式，收益只是省一个依赖。放弃。
- **POSIX 用 `preexec_fn` 设控制终端**：能让 Ctrl-C 由驱动投递，代价是在多线程进程里 fork，`process_group` 已明文拒绝。放弃，改为带外投递（D6）。
- **把 `\u0003` 原样写进终端**（照抄参考）：在没有控制终端的 POSIX 上静默无效，是最难排查的一类失败。放弃。
- **tty 会话不落日志、让 `write_stdin` 直接读终端**：没人读的时候输出就丢了，且违背 ADR 0008 D3"日志是这一路输出的唯一通道"。放弃。
- **剥离 ANSI 转义**：会把程序的真实输出（颜色、进度条）一起改掉，且"哪些转义算噪声"没有稳定答案。不做，只归一化行尾并如实报告限制。
- **暴露 `tty_cols` / `tty_rows`（含 resize）**：模型无法感知终端宽度，等于给它一个只能猜的参数。放弃。
- **Windows 暂不支持，只做 POSIX**：本仓库的开发与验证都在 Windows 上，等于这个功能本地一行都跑不了。放弃。
