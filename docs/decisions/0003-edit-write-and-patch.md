# ADR 0003: `edit_file` 的写入与补丁语义

- 状态：已接受（Accepted）
- 日期：2026-09-20
- 相关：`agent/tools/file_edit_tool.py`、`agent/tools/text_lines.py`
- 取代：[ADR 0001](0001-file-edit-tool.md) 的 D7（补丁语义）

## 背景

ADR 0001 让 `edit_file` 产出 `structured_patch` 与 `gitDiff`，供 UI 与外部消费者使用。但实现是把 `old_string` / `new_string` 的 `splitlines()` 结果直接拼成 `-` / `+` 行，而不是文件的真实行，于是有四个问题（全部用 `git apply --check` 实测）：

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| LF 文件 + 整行匹配 | 可应用 | 可应用 |
| 子串匹配（`xfooy` 里换 `foo`） | **拒绝** | 可应用 |
| 同一行多处匹配（`aaa`） | **拒绝** | 可应用 |
| CRLF 文件 | **拒绝** | 可应用 |

另有一个行号漂移问题：`read_file` 用文件流读，只按 `\n` / `\r\n` / `\r` 断行；而 `text_lines` 用的是 `str.splitlines()`，它还会在 `\x0b`、`\x0c`、`\x1c`-`\x1e`、`\x85`、`\u2028`、`\u2029` 处断行。含换页符的文件里，读取报告 4 行、补丁按 5 行算。

## 决策

### D1. 行只由 `\n` / `\r\n` / `\r` 终止

`text_lines.split_lines` 不再用 `str.splitlines()`，改为与文件流语义一致的实现，保证"读到的行号"和"补丁里的行号"永远一致。

### D2. 补丁按整行表示

匹配落在哪几行，`-` 行就是这几行的**完整原文**，`+` 行是替换后的**完整新文**；同一行上的多处匹配合成一个 hunk。理由：模型只收到一行成功摘要、补丁不进模型上下文，细粒度没有收益，而整行才能让补丁真的可应用。

### D3. `gitDiff` 保留 `\r`，`structured_patch` 剥离

`gitDiff` 要能被 `git apply` 使用：CRLF 文件的行必须带 `\r`，否则每一行上下文都匹配不上（实测）。`structured_patch` 只给人看，剥掉整个行尾。

### D4. `structured_patch` 每个 hunk 对应一组同行匹配；`gitDiff` 额外合并相接触的上下文

`gitDiff` 把上下文窗口相接触的 hunk 合并成一个（与修复前一致），保证补丁可用。

### D5. 原子写保留权限

`os.replace` 会换掉整个 inode，所以交换前必须把原文件的 `st_mode` 复制到临时文件，否则 0755 的脚本会变成 0600（POSIX；CI 跑在 ubuntu 上，有断言覆盖）。**硬链接不会跟随**——已知并接受。

### D6. 写入前复核"文件自读取后未被改动"

读时记录 `st_mtime_ns` 与 `st_size`，`os.replace` 之前复核，不一致则报 `file_changed` 让模型重读。这是此前唯一会**静默覆盖别人改动**的路径。

### D7. 插入文本采纳文件已有的换行风格

`new_string` 里的行尾统一改写为文件的主导行尾，并在 `details.inserted_line_ending` 中报告。否则往 CRLF 文件插入 LF 文本会让"保留换行"只对没被改的行成立。

### D8. 参数不再静默容忍

非字符串的 `old_string` / `new_string`、非布尔的 `replace_all` 返回 `invalid_argument`（此前会抛裸 `TypeError`，突破"失败也走结构化错误"的契约）。`file_path` 不再被 `strip()`：带首尾空格的文件名是可访问的真实名字，找不到时错误里给 `hint` 提示。

## 后果

- `structured_patch` 对子串匹配的语义变了：`xfooy` 里换 `foo` 现在是 `-xfooy` / `+xbary`，不再是 `-foo` / `+bar`。
- 旧的 `test_git_diff_is_a_valid_unified_patch` 只断言字符串出现、从不验证可应用性（名字在骗人）；新用例改用 `git apply --check`，环境没有 git 时跳过。
- `original_file` 仍是解码后的文本。要**字节级**还原原文件，应使用记录下来的 `old_string` / `new_string` + `encoding` 反向编辑，而不是依赖 `original_file` 重新编码（非双射编码下两者不等价）。
