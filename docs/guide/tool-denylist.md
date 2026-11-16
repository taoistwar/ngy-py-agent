# 工具黑名单（denylist）

在 `data/tool_denylist.json` 里声明「这条调用绝对不做」。命中的调用**不会执行、也不会弹确认框**，模型收到一条「被策略拒绝、不要重试」的结果。`TOOL_DENYLIST_CONFIG` 可改文件位置；改动**无需重启**，下一次工具调用即生效。

一条规则 = 工具 + 参数组合（多个参数是「且」的关系，全部命中才拒绝）：

```json
{
  "rules": [
    {"id": "no-rm-root", "tool": "exec_command", "args": {"command": "rm -rf /"}},
    {"id": "no-force-push", "tool": "exec_command",
     "args": {"command": {"match": "regex", "pattern": "git\\s+push\\b.*(--force|-f\\b)"}},
     "reason": "禁止强推，避免改写共享历史"},
    {"id": "no-desktop", "tool": {"match": "regex", "pattern": "^computer_"}}
  ]
}
```

| 写法 | 含义 |
| --- | --- |
| `"tool": "exec_command"` | 工具名完全相等 |
| `"tool": {"match": "regex", "pattern": "^computer_"}` | 工具名正则，一次禁掉一类工具 |
| `"args": {"command": "rm -rf /"}` | 参数值完全相等（字符串简写＝`fixed`） |
| `"args": {"command": {"match": "regex", "pattern": "..."}}` | 参数值正则（`re.search`，子串命中即可） |
| 省略 `args` | 这个工具的所有调用都拒绝 |

- `fixed` 是**整值相等**，不做子串匹配；要「包含」就用正则。
- 多个参数是 AND；参数缺失算不命中；参数名可用点号取嵌套字段（`a.b`、`urls.0`）。
- 非字符串参数按 JSON 形态匹配：配置里可以直接写 `{"timeout": 30}`、`{"urls": ["https://example.com"]}`，比较的是参数在调用里的样子。对象值（dict）要写成 `{"match": "fixed", "value": {...}}`，因为对象位置留给匹配器。
- 写错的规则会整条忽略（不会部分生效）；文件缺失或不是合法 JSON 等于没有黑名单。
- 黑名单只做拒绝，不是沙箱：放行之后仍受权限确认与 `file_access` 约束（见 [ADR 0024](../decisions/0024-tool-denylist.md)）。
