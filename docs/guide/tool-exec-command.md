# 工具：`exec_command`（命令执行）

模型执行外部命令用 `exec_command`。命令**不经过** `file_access` 的路径策略——它就是个 shell，能读写进程用户碰得到的任何路径（见 [ADR 0005](../decisions/0005-exec-tool.md)）。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `command` | string | 必填 | 交给当前平台 shell 执行的命令行。 |
| `timeout` | integer（**毫秒**） | `120000` | 上限 `1800000`（30 分钟）。超时会终止整棵进程树，结果里 `interrupted: true`。 |
| `description` | string | — | 一句话说明这条命令做什么，用于权限确认弹窗与审计记录。 |
| `run_in_background` | boolean | `false` | 立即返回 `pid` / `session_id` / 日志路径；结束时由后续轮次自动通知（见下文），运行期间可用 `write_stdin` 打字。 |
| `tty` | boolean | `false` | `true` 时把命令挂到**伪终端**而不是普通管道。 |
| `dangerouslyDisableSandbox` | boolean | `false` | 跳过额外的约束层；资源上限与整树终止不可关闭。 |

## 后台命令：占位结果 + 完成通知

`run_in_background: true` 时工具**立刻**返回占位结果（`pid`、`session_id`、日志路径），命令作为会话继续运行，Agent Loop 不等它。命令结束时不会再有一次「工具结果」——那次调用已经用占位结果回应过了，一次工具调用只有一个结果——所以完成信息以一条独立消息回到对话里：

```text
<task_notification>
Background command finished: Install dependencies (exit code 0)
session 4a9c1e02 (pid 18344); output: <输出目录>/20261127-101500-812233.log

Last output:
added 212 packages in 8s
</task_notification>
```

规则（[ADR 0034](../decisions/0034-background-notifications.md)）：

- **收集时机**：每轮模型调用前，把「本次运行启动、且已经结束」的命令一次性放进一条 `user` 消息；同一条命令只通知一次。
- **不轮询**：模型不需要用 `write_stdin` 或 `read_file` 反复看是否结束；`write_stdin` 只用于仍然在跑的会话（打字、取增量输出）。通知里带退出码和日志末尾 600 字符，要全文再用 `read_file` 读日志路径。
- **归属**：台账（`agent/tools/background.py`）是**每次运行**一份，只有本运行启动的命令会被通知；子 agent 启动的后台命令记在父运行的台账里，由父循环通知。
- **收尾**：通知即收尾——报告的同时释放会话句柄，与 `write_stdin` 发现进程结束时做的事一致；任务结束时进程树仍会被统一停掉（ADR 0008），因此不会有跨任务遗留的后台进程。

## `tty`：什么时候要，代价是什么

要终端的场合：程序**先问自己有没有终端**再决定行为时——`git` 的颜色与分页、`npm`/`gh` 的确认提示、`top` 这类全屏程序，以及"没有终端就拒绝运行"的 CLI（`sys.stdout.isatty()` 为 `True`）。

代价（工具描述里也写了，避免模型被吓一跳）：

- **stderr 并入 stdout**：终端只有一条流，结果里 `stderr` 恒为空串，`tty: true` 标记这次输出来自终端；
- 每行以 `\r\n` 结尾：模型看到的是 `\n` 版本，**落盘的完整文件保留原始字节**；
- 前台的 `tty` 命令**没法被回答**（前台在等它结束，提示无人可答）：要交互就配 `run_in_background`，再用 `write_stdin` 打字——Windows 上输入的 `\n` 会被转成回车，因为 ConPTY 只认 `\r`；
- Windows 的终端会在命令自己的输出前先吐一小段握手转义序列（ConPTY 初始化），它不是命令的输出；
- 终端尺寸固定 24×80，没有缩放开关。

平台与依赖：

- Windows 用 `pywinpty`（ConPTY），已在 `pyproject.toml` 以 `sys_platform == "win32"` 标记声明；
- macOS/Linux 用标准库 `pty`：子进程拿到自己的会话但**没有控制终端**，因此 Ctrl-C 由本工具带外投递（`killpg`）；
- 这个平台拿不到终端时报错 `tty_unavailable`（**不会**静默退回管道），也没有关掉它的配置开关。

`tty` 会话同样受进程树约束（Windows Job Object / POSIX 进程组）、同样有每任务 8 个会话上限与 30 分钟 TTL；原理与实测记录见 [ADR 0009](../decisions/0009-exec-tty.md)。
