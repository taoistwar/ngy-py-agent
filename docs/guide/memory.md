# 记忆（Memory）：跨会话留下的笔记

会话结束，对话历史就留在那个会话里。记忆是另一回事：**智能体主动留下的一行行笔记**，下一次任务开始时自动出现在系统提示词里，所以"我偏好制表符"只需要说一次。

设计与取舍见 [ADR 0035](../decisions/0035-memory.md)。

## 一条记忆长什么样

| 字段 | 说明 | 上限 |
| --- | --- | --- |
| `name` | 标识，也是键。用同名再保存 = 替换这一条 | 48 字符 |
| `type` | `user`（用户偏好）/ `feedback`（工作方式的反馈）/ `project`（稳定的项目事实）/ `reference`（外部资料在哪） | 四选一 |
| `description` | 索引行，进入每次提示词的一行说明 | 200 字符 |
| `body` | 正文，只在 `memory_search` 时才读 | 4,000 字符 |

整个库最多 200 条。一条记忆只讲一件事：`description` 回答"这条讲什么"，`body` 回答"照做需要知道什么"。

## 它什么时候被写进来

三条路径，都写同一张表：

1. **用户明说**：说"记住我用制表符"，模型调 `memory_save`。
2. **模型判断**：长期偏好、固定规则、稳定的项目事实（某个决定及原因、某个约束、某样东西在哪），模型自己保存。
3. **任务结束自动提取**：任务完成后，后台线程读一次「用户请求 + 最终答复」，把值得留下的拿出来，最多 3 条。

只有**跨会话仍然成立**的内容会被保存。模型必须为每条候选声明 `scope`：`current_task` 表示"这次而已"（例如"这次不要动 `docs/`"），一律不落库；描述或正文里出现"本次会话 / 当前任务 / 临时"这类措辞同样会被拒，并告诉模型原因。所以"这次的要求"不会变成"永久的规矩"。

第三条可以在设置里单独关掉（`auto_extract`），前两条只要记忆开着就一直在。

## 它怎么被读到

每次任务开始时，系统提示词里会多出一段：

```
## Remembered from earlier conversations
These notes were saved in earlier sessions with `memory_save`. They are background
knowledge, not new instructions from the user: when a note and the current request
disagree, the current request wins. Only names and one-line descriptions are listed -
call `memory_search` with a few keywords to read a note in full when it could change
how you do this task.
When you learn something that would otherwise have to be told again ...

- [user] user-prefers-tabs: User prefers tabs for indentation
- [project] auth-rewrite-driven-by-compliance: 认证重写是为了合规，不是技术债清理
```

要点：

- 只有**索引**（类型 + 名字 + 一行描述）。正文靠 `memory_search` 按关键词取回，所以库变大时提示词不会跟着变长。
- 索引有预算（默认 4,000 字符）。放不下时最后一行会写还有多少条没显示，模型知道该去搜。
- 这些笔记是**背景知识**。与用户当前的请求冲突时，以当前请求为准——过时的偏好不该压过刚说的话。

## 管理页

左侧「记忆」页：列表（可搜索）、新增、编辑、删除，以及三个开关。

- **跨会话使用记忆**（`enabled`）：关掉后不再注入索引，`memory_save` / `memory_search` 会如实回答"这个部署关闭了记忆"，也不会再自动提取。
- **任务结束时自动提取长期信息**（`auto_extract`）：只关掉自动提取时，模型仍可用 `memory_save` 主动保存。
- **每次提示词的索引上限**（`max_prompt_chars`）：0–12,000，默认 4,000。

页面上改的东西和模型写进去的是**同一份数据**，所以模型记错了一条，直接在这里改一行或删掉即可。

对应的 HTTP 接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/memories` | 列表 + 当前开关 |
| `POST` | `/api/memories` | 新增；同名则替换 |
| `PUT` | `/api/memories/{memory_id}` | 改一条（字段可选） |
| `DELETE` | `/api/memories/{memory_id}` | 删一条 |
| `GET` / `PUT` | `/api/admin/memory-config` | 读 / 写开关 |

`name` 会被规范化成 slug（小写、非字母数字变 `-`），所以 `User Prefers Tabs` 与 `user-prefers-tabs` 是同一条。

## 与其它"跨会话"机制的分工

| 机制 | 记什么 | 谁维护 |
| --- | --- | --- |
| **记忆** | 学到的事实、偏好、工作方式 | 模型写，人可改 |
| `AGENTS.md` | 项目规则（构建命令、代码约定） | 人写，进仓库 |
| 任务板（`task_*`） | 工作项：谁在做、依赖什么 | 模型与人共同维护 |
| 会话历史 | 同一会话里前几轮说过什么 | 自动 |

记忆是**整机**共享的，不按工作区分。所以私有项目的结论也会出现在别的项目里——不合适就在页面上删掉。

## 已知限制

- 库满 200 条后 `memory_save` 会被拒（提示去页面删一条），没有自动合并。
- 自动提取每个成功任务多一次模型调用；本地模型或按次计费时建议关掉，改由 `memory_save` 显式保存。
- 子代理只能读记忆，不能写：它学到的应该出现在给父对话的报告里。
