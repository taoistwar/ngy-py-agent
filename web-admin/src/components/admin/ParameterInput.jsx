// Editor for one tool argument, chosen from its JSON schema. Shared by the
// built-in tool test and the MCP tool test so both ask for a value the same way.

const TEXTUAL_TYPES = new Set(["string", "any", "null"])

export default function ParameterInput({ param, value, onChange, translate }) {
  const current = value ?? ""

  if (param.options.length > 0 || param.type === "boolean") {
    const options = param.options.length > 0 ? param.options : ["true", "false"]
    return (
      <select
        className="agent-param-input"
        value={current}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{translate("toolTestValueUnset")}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  }

  if (param.type === "object" || param.type === "array") {
    return (
      <textarea
        className="agent-param-input"
        rows={3}
        value={current}
        placeholder={param.type === "array" ? '["value"]' : '{"key": "value"}'}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }

  return (
    <input
      className="agent-param-input"
      type="text"
      inputMode={TEXTUAL_TYPES.has(param.type) ? undefined : "decimal"}
      value={current}
      placeholder={param.defaultValue !== undefined ? String(param.defaultValue) : param.name}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}
