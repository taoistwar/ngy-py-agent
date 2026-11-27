# ADR 0035: 跨会话记忆——索引进提示词，正文按需读取

- 状态：已接受（Accepted）
- 日期：2026-11-27
- 相关：`agent/tools/memory_notes.py`、`agent/tools/memory_store.py`、`agent/tools/memory_save/`、`agent/tools/memory_search/`、`agent/agent_loop/memory_context.py`、`agent/agent_loop/loop.py`、`agent/runtime/memories.py`、`agent/runtime/memory_extract.py`、`agent/runtime/runner.py`、`dao/memories.py`、`routes/memory_api.py`、`web-admin/src/components/admin/MemoryManager.jsx`
- 前置：[ADR 0019](0019-cancel-interrupts-running-work.md)（工具层不 import `commons`/`dao`）、[ADR 0022](0022-agents-md.md)（提示词里的常驻段落）、[ADR 0033](0033-task-board.md)（任务板：另一种跨会话状态）

## 背景

每个任务都从零开始。会话历史（`agent/history.py`）只覆盖同一会话里的前几轮；`AGENTS.md` 装的是**项目**规则，装不下"这个用户偏好制表符""上次说好用 pytest 不用 unittest"；任务板（ADR 0033）记的是**工作项**，不是知识。于是同一条偏好要反复说，说了也没人记。

参考实现 `learn-claude-code/s09_memory` 给了四个动作：存储（一条记忆一个文件）、召回（索引 + 相关性选择后加载正文）、提取（回合结束后由模型提出候选）、整理（数量到阈值时合并）。本 ADR 说明哪些照做、哪些按本仓库的约束换一种做法。

## 决策

### D1. 存在 SQLite 的 `memories` 表，不是 Markdown 目录

参考实现用 `.memory/<name>.md` 加一份 `MEMORY.md` 索引，好处是人可以直接编辑、可以进 git。这里仍然选数据库：

- `dao/` 是全仓库唯一的 SQLite 读写层（ADR 0025），记忆是**跨会话的持久状态**，性质与任务、会话、设置同类；
- 记忆页要能改、能删，而页面读的是 `dao`；两套持久化会让"模型写进去的"和"页面看到的"有机会不一致；
- 文件目录还要自己处理并发写、路径穿越、工作区绑定，这些都已经被数据库解决了。

代价：不能用编辑器直接改、不能随仓库做版本化。补偿是管理 API 完整（列、增、改、删、开关），导出留给以后的接口。

### D2. `name` 就是身份：同名保存 = 替换

一条记忆 = 一行，主键 `memory_id`（页面按它改/删），`name`（slug）唯一且是**模型的键**。写入走 `INSERT … ON CONFLICT(name) DO UPDATE`：`created_at` 不变（那时学到的），`updated_at` 变（那时纠正的）。

为什么不让同名报错：修正记忆和新增记忆必须是同一个动作，否则模型遇到"这条我记过但记错了"时只能删除再重建，中间那段空窗期里索引是缺的。

### D3. 只有索引进提示词，正文用 `memory_search` 读

系统提示词里加一段 `## Remembered from earlier conversations`，每条一行：`- [type] name: description`。正文（`body`）**永不**自动进入上下文。

- 索引默认上限 4,000 字符（管理页可在 0–12,000 之间调，`memory_config.max_prompt_chars`），放不下时最后一行写"还有 N 条未显示，用 `memory_search` 查"。因此记忆库从 5 条长到 200 条，每次请求的固定开销是有界的。
- 与参考实现的差别：它每轮用一次**模型调用**做相关性选择（挑最多 5 条再加载正文）。这里省掉那次调用——索引已经短到可以整段放进提示词，"哪条相关"交给模型在读请求时判断，需要细节再调 `memory_search`（名称命中权重 3、描述 2、正文 1 的确定性排序，实现在 `memory_notes.rank_memories`）。对本地小模型或按次计费的 provider，省下的是每个任务一次往返。
- 段落里写死两句必须在的话：这些笔记是**背景知识不是新指令**（冲突时以当前请求为准），以及学习到长期信息时用 `memory_save`。少了第一句，一条过时偏好会压过用户刚说的话。

### D4. 写入两条路径，共用一套校验

- `memory_save`：模型主动保存（用户说"记住…"，或它自己判断值得记）。
- 任务结束后的提取（`agent/runtime/memory_extract.py`）：读一次「用户请求 + 最终答复」，让模型给出 JSON 候选数组。用户很少说"记住"，只靠工具就永远学不到东西。

候选与工具调用走**同一个** `parse_record` / `should_store`（`agent/tools/memory_notes.py`）。规则只写一份的理由很直接：只在一处生效的规则，等于另一处可以写进它拒绝的东西。

`scope` 门禁（参考实现的 `should_store_memory`）：调用方必须声明 `persistent` 还是 `current_task`，`current_task` 一律**拒绝并说明原因**；另外描述或正文里出现"this session / 当前任务 / 临时"这类只在本次对话成立的措辞也会被拒。这是"偏好"与"这次的要求"的分界线，也是记忆库不变成噪声源的关键。拒绝是**正常结果**（`success: true, saved: false` 不对，这里是 `success: false, reason: invalid_argument`，但模型文本是解释而非报错），模型读完继续做事即可。

### D5. 提取在任务结束之后、独立线程

与 `agent/runtime/naming.py`（会话命名）同一手法：`finish_task` 之后起一个 daemon 线程，成功时补一条 `debug` 事件 `Memories updated`。

- 不能同步：答案已经完整，用户不该为一次没人要求的提取等待。
- 不能省：这是唯一能在用户没开口时学到东西的路径。
- 失败的代价被限制在"这一次没记住"：provider 异常、JSON 不合法、单条写入失败都被吞掉，任务本身早已记录完成。
- 候选上限 3 条：一次任务产出十条"记忆"的，基本都是噪声。

### D6. 作用域是整机，不按工作区隔离

动机是**用户偏好与工作方式**（跨项目的知识）。按工作区切分会逼着同一条偏好在每个项目重学一遍，而工作区在本仓库里只是"某个会话绑定的目录"，并不是一个数据隔离单元。

已知代价写在这里，不藏着：私有项目的结论会出现在另一个项目的提示词里。缓解手段是管理页可删可改；将来若要分域，加一个 `scope` 列即可（D2 的 upsert 键随之变成 `(scope, name)`）。

### D7. 开关是一行配置，关闭是"如实说关"

`memory_config`（`settings` 表里的一行 JSON）：`enabled` / `auto_extract` / `max_prompt_chars`。启动时 `routes/admin_api.py::_load_memory_config` 读进 `commons.state`，`PUT /api/admin/memory-config` 立即生效（下一个任务），不需要重启。

关闭时构造 `MemoryBook(enabled=False)`，而不是把两个工具从 schema 里摘掉：

- 工具列表按 mode / agent 配置构建（`agent/modes.py`），临时摘工具会让"同一份配置下模型看到的工具集随开关变化"，与 `_adopt_dynamic_tools` 等既有假设打架；
- 摘掉工具后模型可能改用 `exec_command` 去翻文件，那更糟。显式回答"这个部署关闭了记忆"是唯一不会误导的做法。

### D8. 工具与子代理的可见性

- `ask` 模式只给 `memory_search`：读是只读的，写会改状态，而 ask 承诺不改状态（`agent/modes.py`）。
- 子代理（ADR 0032）不给 `memory_save`，保留 `memory_search`：子代理的上下文返回即弃，它学到的应该写进给父对话的报告，由父对话判断是否长期有效；读一条已有笔记是回答 brief 所需要的。清单在 `agent/tools/catalog.py::CHILD_EXCLUDED_TOOLS`。

## 后果

- 用户说一次"我用制表符"，之后每个任务都按制表符来；记错了在记忆页改一行即可，模型下次读到的是改后的。
- 每个成功任务多一次模型调用（`auto_extract` 关掉即无），提示词多一段有界开销（默认 ≤ 4,000 字符）。
- 库上限 200 条（`MAX_MEMORIES`）。到上限后 `memory_save` 返回 `reason: "full"` 并提示去页面删一条；**没有**自动合并（参考实现的 consolidation）。理由：自动合并要用一次模型调用重写整个库，错误不可见且不可逆；重复已经由"正文完全相同即不写"兜住，规模问题交给页面。
- 已知未做：按工作区/项目分域；导入导出；记忆命中率统计；在事件流里记录 `memory_search` 的每次查询（现在只在工具结果里）。
- 前端：新菜单「记忆」+ 六语言文案（`menuMemories`、`memory*` 共 38 个键），`npm run build` 里的 i18n 校验会拦住漏翻。

## 备选方案

- **文件式记忆（参考实现原样）**：可读、可 diff、可进 git，但与 `dao/` 的单一持久化约定冲突，且要自己处理并发与路径安全。
- **把正文也全部注入**：实现最简单，但每次请求的上下文随记忆库线性增长，最终会挤掉真正的工作上下文。
- **只提供 `memory_save`，不自动提取**：省一次调用，但用户不说"记住"就什么也学不到——参考实现认为这是最大的缺陷。
- **每轮做一次相关性模型调用**：与参考实现一致，但对"索引已经全在提示词里"的场景是多余往返。
