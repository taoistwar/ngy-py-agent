# ADR 0024: 工具黑名单——命中即拒绝，不进入确认

- 状态：已接受（Accepted）
- 日期：2026-11-16
- 相关：`agent/tools/denylist.py`、`agent/tools/registry.py`、`test/tools/denylist_test.py`、`docs/dev.md`
- 前置：[ADR 0006](0006-tool-permission-confirmation.md)（同一个收口，黑名单先于门禁）

## 背景

ADR 0006 的权限确认回答的是"这一次能不能做"，而答案依赖有人在场。三种模式都表达不了同一件事：**某类调用无论谁在、无论什么模式，都不该执行**。

| 现状 | 表达不了的场景 |
| --- | --- |
| `ask`（默认） | 危险调用仍会被摆到用户面前；点"允许"就执行，而"允许"是对话框里最顺手的按钮 |
| `auto_approve`（无界面部署唯一可用的模式） | 没有任何"绝对不做"的表达方式 |
| `deny_all` | 按 permission kind 整类拒绝，粒度过粗：想禁 `exec_command` 里的一条命令，得连 `read_file` 一起禁 |

而把"要不要执行这条 `rm -rf /`"做成对话框本身就是错的决定：答案已经是否，弹窗只会训练模型"再试一次也许行"。因此需要一层**静态硬拒绝**：命中的调用不执行、不询问，只把原因交回模型与事件流。

## 决策

### D1. 规则 = 工具匹配 + 0..N 个参数匹配，全部命中才拒绝

```json
{
  "rules": [
    {"id": "no-rm-root", "tool": "exec_command", "args": {"command": "rm -rf /"}},
    {"id": "no-force-push", "tool": "exec_command",
     "args": {"command": {"match": "regex", "pattern": "git\\s+push\\b.*(--force|-f\\b)"}},
     "reason": "Force-push rewrites shared history."},
    {"id": "no-computer", "tool": {"match": "regex", "pattern": "^computer_"}}
  ]
}
```

- `tool` 必填；`args` 缺省（或空对象）表示**整个工具禁用**。
- `args` 的多个字段是 **AND**：一处不命中就整条规则不适用。这既是"参数组合"的字面含义，也避免了"任一命中就拒绝"那种会悄悄扩大拦截面的语义。
- 参数名支持点号路径（`a.b`、`urls.0`）以覆盖嵌套参数；**参数缺失视为不命中**，规则不会因为模型少传一个字段而误伤。
- 非字符串参数按其 JSON 形态匹配（`json.dumps(..., ensure_ascii=False, sort_keys=True)`）：数字 `30`、布尔 `true`、列表 `["a"]` 都按它们在调用里的样子写。

### D2. 收口仍在 `ToolRegistry.execute_tool`，且先于权限门

与 ADR 0006 D1 同一个理由：`execute_tool` 是唯一必经之路，写在这里自动覆盖全部工具（包括将来新增的）。按工具逐个加拦截的默认结局是漏掉某个工具，而"漏掉"等于没有。

顺序固定为 **黑名单 → 权限门 → 工具函数**：

- 黑名单在权限门之前，因为这种调用不值得问（同 ADR 0006 D9 对 `file_access` 硬拒绝的处理：弹窗意味着"可能允许"）。
- 命中后返回 `ToolOutcome`，事件类别复用 `permission_decision`，`details.reason = "denylist"`，并带上 `rule` 与 `matched_fields`。复用而不新增类别，是因为前端已经有这一类的样式，UI 侧零改动；拒绝是**结果**而不是失败（ADR 0006 D4），步骤不会被标成 failed。
- 被拦的调用不进入 checkpoint（ADR 0020）：它没有改动磁盘，不该出现在撤销历史里。

### D3. 两种匹配：`fixed` 是整值相等，`regex` 是 `re.search`

- `fixed`：参数值必须**完全等于**配置的字符串。**不做子串匹配**——"看起来像同一个规则、实际更宽"的黑名单比没有更危险（ADR 0006 D8 对权限规则的同一条理由）。
- `regex`：`re.search`，因此子串模式（`git\\s+push\\b.*--force`）天然可用；需要整值锚定就自己写 `^...$`。
- 字符串简写等价于 `fixed`：`{"command": "rm -rf /"}` 与 `{"command": {"match": "fixed", "value": "rm -rf /"}}` 相同。
- `args` 也可写成列表 `[{"field": "command", ...}]`，与解析后的 `to_payload()` 形状一致，便于管理接口回读。

### D4. 配置文件、stat 缓存、坏规则整条丢弃

- 文件：`data/tool_denylist.json`，`TOOL_DENYLIST_CONFIG` 可改路径。文件缺失或不是合法 JSON 一律表示"没有规则"——这是只会**更宽松地不拦截**，不会放宽任何访问。
- 读盘按 `(mtime_ns, size)` 缓存：改完文件下一次调用即生效，不必重启，也不必每次调用解析一遍 JSON（黑名单在**每一次**工具调用上求值，比权限门更靠前，缓存是必要的）。
- **单条规则写错（未知 `match`、坏正则、缺 `tool`、empty value）时整条丢弃**，原因记在 `ToolDenyList.problems`。不保留半解析的规则：它匹配到的调用集合与写规则的人看到的不是同一个集合。丢弃方向是"不拦截"，所以不会误伤，但配置错误必须可见。
- 规则顺序即优先级；命中第一条即返回。

### D5. 求值异常 fail closed

`_denylist_denial` 捕获任异常并拒绝，`details.reason = "denylist_error"`。与权限门对 broker 异常的处理一致：这是安全层，坏了必须"拒绝并大声说"，不能悄悄放行。

### D6. 默认没有规则，且它不是安全边界

仓库不附带任何规则文件，所以默认行为与之前完全一致。和其它策略一样，这是**协作式的护栏**，不是安全边界：放行之后没有新的限制，`exec_command` 仍是进程用户的完整 shell（ADR 0006 的同一句声明继续成立）。

## 后果

- 运维可以不重启地追加/收紧规则；配置错误会出现在 `problems` 里，而不是静默失效。
- 被拦的调用在任务事件流里表现为一次 `permission_decision`，模型收到的文案明确写"不要重试，也不要绕过"。
- 黑名单对 `permission="none"` 的工具同样生效：这个层的覆盖面不依赖工具声明的权限种类。
- 未来若加管理 API，`ToolDenyList.list()/problems` 已足够支撑列表与诊断，不需要再改匹配层。

## 备选方案（未采用）

- **塞进 `PermissionBroker`**：broker 的语义是"问一个问题"，而黑名单的语义是"不许问"。混在一起后，`auto_approve` 与 `deny_all` 会把静态拒绝当成一次决定来记录，`pending`/`resolve` 也会多出一条永远不该出现的路径。
- **写进各工具内部**：工具拿不到统一收口，漏一个工具就是一次静默放行；而且每个工具都要复制一遍匹配逻辑。
- **只支持工具名**：表达不了"同一条命令、不同参数"这个最需要拦的组合（`exec_command` 万能，只禁工具名等于禁用整个终端）。
- **支持 glob/前缀等更多模式**：正则已经覆盖这些，多一种模式就多一种"用户看不全的匹配"，与 D3 的取舍冲突。
- **给命中加缓存/熔断（同一调用直接失败）**：模型重试同一调用本来就应当被再次拒绝，缓存只会让事件流少一条审计记录。
