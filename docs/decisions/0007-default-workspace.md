# ADR 0007: 未绑定会话的相对路径基目录

- 状态：已接受（Accepted）
- 日期：2026-09-22
- 相关：`agent/tools/file_access.py`、`agent/agent_loop.py`、`.gitignore`
- 前置：[ADR 0001](0001-file-edit-tool.md)、[ADR 0004](0004-file-write-tool.md)

## 背景

需求：`write_file` 的 `file_path` 是相对路径时，若当前会话**没有绑定工作空间**，以「程序启动路径 + `data/default_workspace`」为基目录；有工作空间则照旧用它。

这不是理论问题，是现场问题。`data/permission_rules.json` 里留着一次真实会话的记录：

```json
{ "tool": "write_file", "target": "E:/projects/ngy-py-agent/test.py", "kind": "write" }
```

那次会话没有工作空间，相对路径落到了**进程的工作目录**——实际就是仓库根，于是模型写出的临时脚本混进了项目树（那个 `test.py` 至今还在仓库根）。

核查到的事实：

| 事实 | 位置 | 影响 |
| --- | --- | --- |
| 无工作空间时相对路径按 `Path.cwd()` 解析 | `file_access._resolve_path` | 就是上面那个 bug |
| 路径解析是三个文件工具**共用**的 | `resolve_read_path` / `resolve_write_path` | "只改 `write_file`" 反而需要**额外**代码 |
| 未绑定会话**完全不会**在 system prompt 里被告知工作目录 | `agent_loop._with_base_dir` 在 `base_dir` 为空时原样返回 prompt | 模型不知道相对路径会去哪，只改解析等于半个修复 |
| `write_file` 新建文件要求父目录已存在 | `file_write_tool.py` 报 `parent_missing` | 默认目录必须按需创建，否则相对写入必然失败 |
| 没有测试依赖 cwd 回退 | 无工作空间的既有用例全部用绝对路径 | 旧行为是**未被测试覆盖的偶然行为** |
| `data/file_access.json`（策略）锚在仓库根 | `file_access._repo_root()` | `data/` 从此有两个锚点（见 D3） |

## 决策

### D1. 改动放在共用解析器上，因此三个文件工具都生效

需求只提到 `write_file`，但实现放在 `file_access._resolve_path`——`read_file` / `edit_file` / `write_file` 的共同入口。

- 只给 `write_file` 加，需要为此写一个**特例**（更多代码），并且会产生"**写得进去、读不回来**"：模型写 `test.py` 落在默认目录，再读 `test.py` 却按 cwd 找。[ADR 0001](0001-file-edit-tool.md) D3 写的"读得到的文件就能改"，反过来同样成立：**写下的文件应当读得回来**。
- 三个工具的相对路径语义本来就必须一致，否则"基目录"这个概念会在工具之间漂移。

### D2. 它是**基目录，不是边界**

`default_workspace` 只决定相对路径从哪开始；未绑定会话**依然没有工作空间天花板**（见术语表的"未绑定会话"），`..` 仍可离开它，全局策略照旧生效。

把它当边界是另一个更大的改动（等于给未绑定会话凭空加一个约束），需求没要求，也没有"为什么"支撑。

### D3. 锚在**程序启动路径**（`Path.cwd()`），可用 `DEFAULT_WORKSPACE_DIR` 覆盖

需求原文是"程序的启动路径"，现场证据也吻合（当时 cwd 就是仓库根）。

代价必须记下来：`data/file_access.json`（访问策略）锚在**仓库根**（`_repo_root()`），所以 `data/` 这个名字现在有两个锚点——从别的目录启动进程时，策略文件仍读仓库根，默认工作空间却出现在启动处。若日后想让两者一致，把 `default_workspace_root` 改用 `_repo_root()` 即可（一行）。本 ADR 记下这个取舍，以免被当成 bug"修掉"。

### D4. 创建是**显式选择**：只有 `write_file` 创建，其余一律不创建

`write_file` 新建文件要求父目录存在（`parent_missing`），所以默认目录必须能被创建，否则相对写入永远失败。因此 `resolve_read_path` / `resolve_write_path` 增加 `create_default`，**默认 `False`**，只有 `write_file` 传 `True`。

这不只是"读取不创建"，而是"**解析一律不创建**"。最初的实现按 `action == "modified"` 决定创建，结果被测试套件抓到：**权限代理在判定阶段也会解析目标**（为了把路径显示在弹窗里），于是仅仅"判定"就留下一个空的 `data/default_workspace`——连 `deny_all` 模式下、调用注定被拒绝的情况也一样（实测 `before: False` → `after: True`，`reason: deny_all`）。一次查找不该有副作用，一次**拒绝**更不该有。

### D5. system prompt 同步说明默认目录

只改解析会让模型继续按错误的心智模型规划（它不知道相对路径去哪）。未绑定时 prompt 明确指出默认目录，并建议"需要确定位置时用绝对路径"；有工作空间时文案**完全不变**。

### D6. 运行期状态进 `.gitignore`

`data/default_workspace/` 与 `data/permission_rules.json` 都是运行期产物（后者是用户的权限决定，含机器相关的绝对路径），与既有的 `*.db` 同类，不该被提交。

## 后果

- 未绑定会话的临时文件不再混进项目树，且写下的文件读得回来。
- 未绑定会话的**相对路径含义变了**（原先 cwd → 现在默认目录）。没有既有测试依赖旧行为，而 `data/permission_rules.json` 里的现场记录说明了旧行为的危害。
- `exec` **不在**本次改动内：它的进程工作目录仍是原逻辑。shell 的 cwd 是另一件事，需要确定位置时在命令里写绝对路径即可。

## 备选方案（未采用）

- **只给 `write_file` 加**：需要特例代码，并且产生"写得进去、读不回来"的不对称。
- **把默认目录做成工作空间边界**：等于给未绑定会话新增约束，超出需求且没有理由。
- **锚在仓库根而不是启动路径**：与 `data/file_access.json` 的锚点一致（有诱惑力），但需求明确说的是启动路径，现场行为也是启动路径。若两者不一致造成困扰，改成仓库根是一行改动。
- **不告知模型**：等于只修一半，模型的心智模型仍然是错的。
