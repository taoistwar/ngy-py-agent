# API：工具管理

「工具管理」页面把 `agent/tools/catalog.py` 注册的工具按分类分组，一类一张表（文件读写 / 命令与进程 / 桌面操作 / 计算与代码 / 信息查询 / 用户交互），可搜索工具名、描述或智能体；点「详情」查看权限门禁、确认框可提供的答复、实现文件与参数结构（参数渲染与智能体编辑里的工具详情一致）。

- `GET /api/tools`：返回 `{tools}`，每个工具包含：
  - `name` / `description` / `parameters`：与模型看到的工具声明一致；
  - `category`：列表分组，取值见 `agent/tools/spec.py` 的 `CATEGORY_KINDS`；页面认识的分类用本地化名称，不认识的直接显示原值；
  - `description_i18n`：`{语言: {description, parameters}}`，只用于页面展示，不会进入模型看到的 schema；
  - `permission`：权限门禁种类 `none` / `read` / `write` / `exec` / `computer`（见 `agent/tools/permissions.py`），`none` 表示永不询问；
  - `scopes`：确认框可以给出的答复（`once` / `session` / `always`），只包含该工具实际接受的范围；
  - `has_preview`：是否提供确认前的无副作用预演；
  - `source`：实现文件，相对仓库根目录；
  - `agent_ids`：允许调用该工具的智能体 id；智能体的 `tool_names` 为 `null` 表示"全部工具"，此时它会出现在每个工具的列表里。

工具说明与参数说明是双语的：英文是源文本，页面上始终显示；当前语言不是英文时，会在英文下方再显示该语言的翻译。英文界面只显示英文。每个工具都自带 `zh-CN` / `zh-TW` / `fr` / `de` / `ru` 五套文案，与界面可选语言一致。

翻译放在每个工具包自己的 `i18n.py` 里（`ToolText`，由 `spec.py` 通过 `localized_texts(...)` 装配成 `description_i18n`），与 `description.py` 分开，因为模型永远只看英文。新增或修改工具参数时要同步补这五套翻译：`test/tool_api_test.py` 会校验每个工具的每个语种都覆盖了全部参数。

详情弹窗里每个参数都有一个输入框（按参数类型给文本框 / 下拉 / JSON 文本），点右上角「测试」会在后台真实执行一次该工具，并显示模型会收到的结果；`ToolOutcome` 的 `details` 另列为 JSON。

- `POST /api/tools/{tool_name}/test`：请求体 `{"arguments": {...}}`，返回 `{tool, ok, result, details, error, truncated, duration_ms}`。
  - `ok=false` 表示工具抛出了异常（参数不对就是这种），不是 HTTP 错误；工具自己返回的错误仍是 `ok=true`，错误文本在 `result` 里。
  - **不经过权限确认**：它不属于任何任务，没有 broker 可以询问。页面在测试需要确认的工具（`permission != none`）前会先弹一次浏览器确认；不要把它当作通用执行接口。
  - `result` / `details` 超过 2 万字符会截断，`truncated=true`。
