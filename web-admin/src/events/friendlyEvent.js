// Turns a raw task event into a view model a non-programmer can read.
//
// The raw payload is written for debugging (provider plumbing, token budgets, trace
// ids); the friendly view keeps the same facts but answers "what did the agent just
// do?" first, and hides identifiers nobody outside the codebase needs.
import { dictionaryFor, fieldLabel, fillTemplate, valueLabel } from "./eventDictionary.js"

const TRACE_KEYS = new Set(["trace_id", "span_id", "parent_span_id"])
// Payloads carried for the raw viewer only: they are megabytes of provider-shaped JSON.
const RAW_KEYS = new Set([
  "raw_request",
  "raw_response",
  "request_payload",
  "response_payload",
  "request",
  "tools",
])
const LONG_TEXT_KEYS = new Set([
  "content",
  "text",
  "stdout",
  "stderr",
  "output",
  "query",
  "prompt",
  "error",
  "message",
  "body",
])
const MONO_KEYS = new Set([
  "path",
  "file_path",
  "command",
  "base_dir",
  "session_id",
  "task_id",
  "request_id",
  "tool_call_id",
  "model_id",
  "agent_id",
  "encoding",
])
const FIELD_ORDER = [
  "step",
  "name",
  "action",
  "path",
  "file_path",
  "command",
  "model",
  "provider",
  "mode",
  "status",
  "success",
  "is_error",
  "kind",
  "target",
  "scope",
  "reason",
  "exit_code",
  "start_line",
  "end_line",
  "returned_lines",
  "total_lines",
  "truncated",
  "file_bytes_read",
  "bytes_written",
  "created",
  "finish_reason",
  "message_count",
  "tool_count",
  "tool_call_count",
  "tool_choice",
  "history_messages",
  "max_steps",
  "max_output_tokens",
  "thinking_mode",
  "supports_tool_calls",
  "stream",
  "timeout_seconds",
  "answered_count",
  "question_count",
  "duration_ms",
  "type",
  "endpoint",
  "tool_call_id",
]

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function normalizeCategory(category) {
  return String(category || "").toLowerCase()
}

function formatBytes(value) {
  const size = Number(value)
  if (!Number.isFinite(size)) return String(value)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatScalar(dict, key, value, options = {}) {
  if (value === null || value === undefined || value === "") return dict.text.empty
  if (typeof value === "boolean") return value ? dict.text.yes : dict.text.no
  if (typeof value === "number") {
    if (key.includes("bytes")) return formatBytes(value)
    // Zero means "no configured limit", which reads as a broken setting otherwise.
    if (value === 0 && key === "max_output_tokens") return dict.text.unlimited
    return String(value)
  }
  if (Array.isArray(value)) {
    return fillTemplate(dict.text.listItem, { count: value.length })
  }
  if (isPlainObject(value)) {
    return fillTemplate(dict.text.objectItem, { count: Object.keys(value).length })
  }
  const text = String(value)
  const mapped = valueLabel(dict, key, text)
  if (mapped) return mapped
  const limit = options.limit || 160
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function prettyJson(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJsonLoose(value) {
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    return null
  }
}

function makeField(dict, key, value) {
  return {
    label: fieldLabel(dict, key),
    value: formatScalar(dict, key, value),
    mono: MONO_KEYS.has(key),
    raw: value,
  }
}

function objectRows(dict, value, depth = 0) {
  if (!isPlainObject(value)) return []
  return Object.entries(value)
    .filter(([key]) => !TRACE_KEYS.has(key) && !RAW_KEYS.has(key))
    .map(([key, item]) => ({
      label: fieldLabel(dict, key),
      value:
        depth >= 1 && (isPlainObject(item) || Array.isArray(item))
          ? prettyJson(item)
          : formatScalar(dict, key, item),
      mono: MONO_KEYS.has(key),
    }))
}

function arrayAsText(dict, key, value) {
  if (value.every((item) => !isPlainObject(item) && !Array.isArray(item))) {
    return value.map((item) => formatScalar(dict, key, item)).join("\n")
  }
  return prettyJson(value)
}

// Splits a payload into the two things the friendly view renders: short rows for the
// summary table, and larger blocks for text the reader may want to read in full.
function describeData(dict, data, options = {}) {
  const skip = new Set(options.skip || [])
  const order = options.order || FIELD_ORDER
  const fields = []
  const sections = []
  const seen = new Set()

  const visit = (key) => {
    if (seen.has(key) || skip.has(key) || TRACE_KEYS.has(key) || RAW_KEYS.has(key)) return
    const value = data[key]
    if (value === undefined) return
    seen.add(key)

    if (isPlainObject(value)) {
      const rows = objectRows(dict, value)
      if (rows.length > 0) {
        sections.push({ kind: "entries", title: fieldLabel(dict, key), rows })
      }
      return
    }

    if (Array.isArray(value)) {
      if (value.length === 0) return
      // A short list of plain values ("this time only") reads better inline than as
      // its own block; anything longer keeps the block so it stays scannable.
      const scalarsOnly = value.every((item) => !isPlainObject(item) && !Array.isArray(item))
      if (scalarsOnly) {
        const joined = value.map((item) => formatScalar(dict, key, item)).join(dict.text.listSeparator)
        if (joined.length <= 60) {
          fields.push({ label: fieldLabel(dict, key), value: joined, mono: false, raw: value })
          return
        }
      }
      sections.push({
        kind: "text",
        title: fieldLabel(dict, key),
        text: arrayAsText(dict, key, value),
        mono: true,
      })
      return
    }

    const text = typeof value === "string" ? value : ""
    if (LONG_TEXT_KEYS.has(key) && text.length > 0) {
      sections.push({
        kind: "text",
        title: fieldLabel(dict, key),
        text,
        mono: key !== "query",
      })
      return
    }

    fields.push(makeField(dict, key, value))
  }

  order.forEach(visit)
  Object.keys(data).forEach(visit)
  return { fields, sections }
}

function roleText(dict, role) {
  const normalized = String(role || "").toLowerCase()
  const table = {
    system: dict.text.roleSystem,
    user: dict.text.roleUser,
    assistant: dict.text.roleAssistant,
    tool: dict.text.roleTool,
    developer: dict.text.roleDeveloper,
  }
  return table[normalized] || dict.text.roleUnknown
}

function messageContentText(dict, content) {
  if (content === null || content === undefined || content === "") return dict.text.emptyMessage
  if (typeof content === "string") return content
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part
        if (!isPlainObject(part)) return String(part)
        if (typeof part.text === "string") return part.text
        if (part.type === "image_url" || part.type === "image") return dict.text.imagePlaceholder
        return prettyJson(part)
      })
      .join("\n")
  }
  return prettyJson(content)
}

function toolCallsOf(message) {
  const calls = message?.tool_calls
  if (!Array.isArray(calls)) return []
  return calls.map((call) => {
    const name = call?.function?.name || call?.name || ""
    const args = call?.function?.arguments ?? call?.arguments
    return { name, args: typeof args === "string" ? args : prettyJson(args ?? {}) }
  })
}

function requestMessages(data) {
  const raw = data.raw_request || data.request_payload
  if (!isPlainObject(raw) || !Array.isArray(raw.messages)) return []
  return raw.messages
}

function requestTools(data) {
  const raw = data.raw_request || data.request_payload
  const tools = isPlainObject(raw) ? raw.tools : null
  if (!Array.isArray(tools)) return []
  return tools
    .map((tool) => {
      const fn = tool?.function || tool
      const name = fn?.name || ""
      const description = fn?.description || ""
      return { name, description }
    })
    .filter((tool) => tool.name)
}

function responseMessage(data) {
  const raw = data.raw_response || data.response_payload || data.response
  if (!isPlainObject(raw)) return null
  const choice = Array.isArray(raw.choices) ? raw.choices[0] : null
  return choice?.message || null
}

function responseUsage(data) {
  const raw = data.raw_response || data.response_payload || data.response
  return isPlainObject(raw) && isPlainObject(raw.usage) ? raw.usage : null
}

function thinkingText(value) {
  if (typeof value === "string") return value
  if (Array.isArray(value)) {
    return value.map(thinkingText).filter(Boolean).join("\n\n")
  }
  if (isPlainObject(value)) {
    if (typeof value.text === "string") return value.text
    if (typeof value.thinking === "string") return value.thinking
  }
  return ""
}

// Providers disagree on the field name and a few send an array of blocks, so all
// known spellings are folded into one string. The event itself carries the trace
// for streamed turns, which is where it is read from first.
function responseThinking(data) {
  const explicit = thinkingText(data.reasoning)
  if (explicit) return explicit.trim()

  const message = responseMessage(data)
  if (!message) return ""
  return ["reasoning", "reasoning_content", "thinking"]
    .map((key) => thinkingText(message[key]))
    .filter(Boolean)
    .join("\n\n")
    .trim()
}

// Roles whose content is prose written for the model: the system prompt and the user
// instructions read as Markdown by default and as source on demand, the same two modes
// the task result offers. Assistant history and tool output stay verbatim - they are
// data (often JSON), and reflowing them would misrepresent what was sent.
const PROSE_ROLES = new Set(["system", "user"])

function messageItems(dict, messages) {
  return messages.map((message, index) => {
    const calls = toolCallsOf(message)
    return {
      title: fillTemplate(dict.text.messageTitle, {
        index: index + 1,
        role: roleText(dict, message?.role),
      }),
      meta:
        calls.length > 0
          ? fillTemplate(dict.text.messageToolMeta, { tools: calls.map((call) => call.name).join(", ") })
          : "",
      text: messageContentText(dict, message?.content),
      markdown: PROSE_ROLES.has(String(message?.role || "").toLowerCase()),
    }
  })
}

function toolCallItems(dict, calls) {
  return calls.map((call, index) => ({
    title: `${index + 1}. ${call.name || fieldLabel(dict, "name")}`,
    meta: "",
    text: call.args,
    // The arguments are a JSON document the reader may want to reformat, unescape
    // or read as unicode - the same display tools the standalone tool-call event has.
    transforms: true,
  }))
}

function buildStartTask({ event, data, dict }) {
  const { fields, sections } = describeData(dict, data, {
    order: [
      "provider",
      "model",
      "model_id",
      "agent_id",
      "mode",
      "max_steps",
      "history_messages",
      "base_dir",
      "session_id",
      "stream",
      "supports_tool_calls",
      "thinking_mode",
      "max_output_tokens",
    ],
  })
  return {
    tone: "info",
    headline: data.model
      ? fillTemplate(dict.text.startTask, { model: data.model })
      : dict.text.startTaskNoModel,
    fields,
    sections,
  }
}

function buildLlmRequest({ data, dict }) {
  const messages = requestMessages(data)
  const tools = requestTools(data)
  const fields = []
  if (data.step !== undefined) fields.push(makeField(dict, "step", data.step))
  if (data.model !== undefined) fields.push(makeField(dict, "model", data.model))
  if (data.provider !== undefined) fields.push(makeField(dict, "provider", data.provider))
  const messageCount = data.message_count ?? messages.length
  if (messageCount) fields.push(makeField(dict, "message_count", messageCount))
  const toolCount = data.tool_count ?? tools.length
  if (toolCount) fields.push(makeField(dict, "tool_count", toolCount))
  if (data.tool_choice !== undefined) fields.push(makeField(dict, "tool_choice", data.tool_choice))

  const sections = []
  if (messages.length > 0) {
    sections.push({ kind: "blocks", title: dict.text.sectionMessages, items: messageItems(dict, messages) })
  }
  if (tools.length > 0) {
    sections.push({
      kind: "entries",
      title: dict.text.sectionTools,
      rows: tools.map((tool, index) => ({
        label: `${index + 1}. ${tool.name}`,
        value: tool.description,
      })),
    })
  }

  return {
    tone: "info",
    headline: data.step
      ? fillTemplate(dict.text.llmRequest, { step: data.step, count: messageCount || 0 })
      : fillTemplate(dict.text.llmRequestNoStep, { count: messageCount || 0 }),
    fields,
    sections,
  }
}

function buildLlmResponse({ data, dict }) {
  const message = responseMessage(data)
  const calls = toolCallsOf(message)
  const fields = []
  if (data.step !== undefined) fields.push(makeField(dict, "step", data.step))
  if (data.model !== undefined) fields.push(makeField(dict, "model", data.model))
  if (data.finish_reason !== undefined) fields.push(makeField(dict, "finish_reason", data.finish_reason))
  const callCount = data.tool_call_count ?? calls.length
  if (callCount) fields.push(makeField(dict, "tool_call_count", callCount))
  // How the answer arrived, next to how long it took to start: a step that "felt
  // slow" is usually the wait for the first token, not the generation.
  if (data.stream !== undefined) fields.push(makeField(dict, "stream", data.stream))
  if (data.first_token_ms !== undefined && data.first_token_ms !== null) {
    fields.push(makeField(dict, "first_token_ms", `${data.first_token_ms} ms`))
  }
  if (data.duration_ms !== undefined && data.duration_ms !== null) {
    fields.push(makeField(dict, "duration_ms", `${data.duration_ms} ms`))
  }

  const sections = []
  // Reasoning first: it is what the model thought before producing the answer below.
  const thinking = responseThinking(data)
  if (thinking) {
    sections.push({
      kind: "thinking",
      title: dict.text.sectionThinking,
      text: thinking,
      meta: fillTemplate(dict.text.thinkingMeta, { lines: thinking.split("\n").length }),
    })
  }
  const content = data.content ?? message?.content
  const contentText = messageContentText(dict, content)
  if (contentText && contentText !== dict.text.emptyMessage) {
    // The answer is Markdown: it reads as prose by default and as source on demand,
    // the same two modes the task result pane offers.
    sections.push({
      kind: "text",
      title: dict.text.sectionContent,
      text: contentText,
      mono: false,
      markdown: true,
    })
  }
  if (calls.length > 0) {
    sections.push({ kind: "blocks", title: dict.text.sectionToolCalls, items: toolCallItems(dict, calls) })
  }
  const usage = responseUsage(data)
  if (usage) {
    sections.push({ kind: "entries", title: dict.text.sectionUsage, rows: objectRows(dict, usage) })
  }

  const headline =
    calls.length > 0 && data.step
      ? fillTemplate(dict.text.llmResponseTools, { step: data.step, count: calls.length })
      : data.step
        ? fillTemplate(dict.text.llmResponse, { step: data.step })
        : dict.text.llmResponseNoStep

  return { tone: "info", headline, fields, sections }
}

function buildToolCall({ data, dict }) {
  const { fields, sections } = describeData(dict, data, {
    skip: ["arguments"],
    order: ["step", "name", "tool_call_id"],
  })
  const args = data.arguments
  if (isPlainObject(args) && Object.keys(args).length > 0) {
    // Flattening keeps a whole-file `content` argument a block instead of a table
    // cell, and the rows read as "what this call is about". The blocks keep the
    // display tools: an argument value is often the JSON a reader wants to reformat.
    const described = describeData(dict, args)
    fields.push(...described.fields)
    sections.push(
      ...described.sections.map((section) =>
        section.kind === "text" ? { ...section, transforms: true } : section,
      ),
    )
  } else if (typeof args === "string" && args.trim()) {
    sections.push({
      kind: "text",
      title: dict.text.sectionArguments,
      text: args,
      mono: true,
      transforms: true,
    })
  }

  return {
    tone: "info",
    headline: data.step
      ? fillTemplate(dict.text.toolCall, { step: data.step, name: data.name || dict.text.empty })
      : fillTemplate(dict.text.toolCallNoStep, { name: data.name || dict.text.empty }),
    fields,
    sections,
  }
}

function buildToolResult({ data, dict }) {
  const failed = Boolean(data.is_error)
  // "Failed: No" on a successful call is noise the reader has to filter out.
  const { fields, sections } = describeData(dict, data, {
    skip: failed ? ["result"] : ["result", "is_error"],
  })
  const parsed = parseJsonLoose(data.result)
  if (isPlainObject(parsed) && Object.keys(parsed).length > 0) {
    // Tool results often carry a JSON document (read_file sends path/line counts and
    // the file body): flatten it so the facts become rows and the file stays a block.
    const described = describeData(dict, parsed, { skip: ["token_budget"] })
    fields.push(...described.fields)
    sections.push(...described.sections)
  } else if (data.result !== undefined && data.result !== null && data.result !== "") {
    sections.push({ kind: "text", title: dict.text.sectionResult, text: String(data.result), mono: true })
  }

  const name = data.name || dict.text.empty
  const headline = failed
    ? fillTemplate(dict.text.toolResultFail, { name })
    : fillTemplate(dict.text.toolResultOk, { name })

  return { tone: failed ? "danger" : "success", headline, fields, sections }
}

function firstLineText(value, limit = 60) {
  const line = String(value || "").trim().split(/\r?\n/)[0].trim()
  if (!line) return ""
  return line.length > limit ? `${line.slice(0, limit)}…` : line
}

function buildSubagent({ data, dict }) {
  const phase = String(data.phase || "started")
  const failed = phase === "failed" || data.is_error === true
  // The brief and the report are the two things a reader opens the card for, so they
  // become blocks; identifiers stay out of the table for the same reason trace ids do.
  const { fields, sections } = describeData(dict, data, {
    skip: ["prompt", "result", "arguments", "subagent_id"],
    order: ["phase", "steps_used", "tool_calls", "duration_ms", "step", "name"],
  })

  if (data.prompt) {
    sections.push({
      kind: "text",
      title: dict.text.sectionSubagentBrief,
      text: String(data.prompt),
      transforms: true,
    })
  }

  if (isPlainObject(data.arguments) && Object.keys(data.arguments).length > 0) {
    const described = describeData(dict, data.arguments)
    fields.push(...described.fields)
    sections.push(
      ...described.sections.map((section) =>
        section.kind === "text" ? { ...section, transforms: true } : section,
      ),
    )
  }

  if (data.result !== undefined && data.result !== null && data.result !== "") {
    sections.push({
      kind: "text",
      title: phase === "tool" ? dict.text.sectionResult : dict.text.sectionSubagentReport,
      text: String(data.result),
      mono: phase === "tool",
      transforms: phase === "tool",
    })
  }

  const brief = firstLineText(data.prompt)
  let headline
  if (phase === "tool") {
    headline = fillTemplate(dict.text.subagentTool, { name: data.name || dict.text.empty })
  } else if (phase === "done") {
    headline = dict.text.subagentDone
  } else if (phase === "failed") {
    headline = dict.text.subagentFailed
  } else {
    headline = brief
      ? fillTemplate(dict.text.subagentStarted, { prompt: brief })
      : dict.text.subagentStartedNoBrief
  }

  return {
    tone: failed ? "danger" : phase === "done" ? "success" : "info",
    headline,
    fields,
    sections,
  }
}

function buildError({ data, dict }) {
  const { fields, sections } = describeData(dict, data, {
    order: ["step", "name", "type", "endpoint", "error"],
  })
  return {
    tone: "danger",
    headline: data.error ? String(data.error).split("\n")[0] : dict.text.error,
    fields: fields.filter((item) => item.label !== fieldLabel(dict, "error")),
    sections,
  }
}

function buildFileEvent({ data, dict }, kind) {
  const path = data.file_path || data.path || ""
  const failed = data.success === false
  const templates = {
    write: [dict.text.fileWrite, dict.text.fileWriteFailed],
    edit: [dict.text.fileEdit, dict.text.fileEditFailed],
    delete: [dict.text.fileDelete, dict.text.fileDeleteFailed],
  }[kind] || [dict.text.fileWrite, dict.text.fileWriteFailed]
  const headline = fillTemplate(failed ? templates[1] : templates[0], { path })
  const { fields, sections } = describeData(dict, data)
  return { tone: failed ? "danger" : "success", headline: path ? headline : dict.text.generic, fields, sections }
}

function buildPermissionRequest({ data, dict }) {
  const { fields, sections } = describeData(dict, data, {
    order: ["kind", "target", "scopes", "timeout_seconds", "summary"],
    skip: ["request_id"],
  })
  const tool = data.tool || data.name
  const headline = tool ? `${dict.text.permissionRequest}：${tool}` : dict.text.permissionRequest
  return { tone: "warning", headline, fields, sections }
}

function buildPermissionDecision({ data, dict }) {
  const { fields, sections } = describeData(dict, data, {
    order: ["kind", "target", "scope", "reason"],
  })
  return { tone: "warning", headline: dict.text.permissionDecision, fields, sections }
}

function buildUserQuestion({ data, dict }) {
  const questions = Array.isArray(data.questions) ? data.questions : []
  const fields = []
  if (questions.length > 0) fields.push(makeField(dict, "question_count", questions.length))

  const sections = []
  if (questions.length > 0) {
    sections.push({
      kind: "blocks",
      title: dict.text.sectionQuestions,
      items: questions.map((question, index) => {
        const options = Array.isArray(question?.options)
          ? question.options
              .map((option) => (isPlainObject(option) ? option.label || option.value || "" : option))
              .filter(Boolean)
          : []
        return {
          title: `${index + 1}. ${question?.question || question?.header || ""}`,
          meta:
            options.length > 0
              ? `${fieldLabel(dict, "options")}${dict.text.labelSeparator}${options.join(" / ")}`
              : "",
          text: "",
        }
      }),
    })
  }

  return {
    tone: "warning",
    headline: fillTemplate(dict.text.userQuestion, { count: questions.length || data.question_count || 0 }),
    fields,
    sections,
  }
}

function buildUserAnswer({ data, dict }) {
  const { fields, sections } = describeData(dict, data, {
    order: ["status", "answered_count", "question_count"],
  })
  return { tone: "success", headline: dict.text.userAnswer, fields, sections }
}

function buildGeneric({ data, dict }, tone) {
  const { fields, sections } = describeData(dict, data)
  return { tone: tone || "info", headline: "", fields, sections }
}

const BUILDERS = {
  llm_request: buildLlmRequest,
  llm_response: buildLlmResponse,
  tool_call: buildToolCall,
  tool_result: buildToolResult,
  subagent: buildSubagent,
  error: buildError,
  file_write: (ctx) => buildFileEvent(ctx, "write"),
  file_edit: (ctx) => buildFileEvent(ctx, "edit"),
  file_delete: (ctx) => buildFileEvent(ctx, "delete"),
  exec: ({ data, dict }) => {
    const { fields, sections } = describeData(dict, data)
    const failed = data.success === false
    const command = String(data.command || "").split("\n")[0].trim()
    let headline = failed ? dict.text.execFailed : dict.text.exec
    if (command) {
      const template = failed ? dict.text.execFailedWithCommand : dict.text.execWithCommand
      headline = fillTemplate(template, { command: command.length > 48 ? `${command.slice(0, 48)}…` : command })
    }
    return { tone: failed ? "danger" : "success", headline, fields, sections }
  },
  computer: ({ data, dict }) => {
    const { fields, sections } = describeData(dict, data)
    const failed = data.success === false
    return {
      tone: failed ? "danger" : "success",
      headline: failed ? dict.text.computerFailed : dict.text.computer,
      fields,
      sections,
    }
  },
  permission_request: buildPermissionRequest,
  permission_decision: buildPermissionDecision,
  user_question: buildUserQuestion,
  user_answer: buildUserAnswer,
}

function buildDebug({ event, data, dict }) {
  const title = String(event?.title || "")
  if (/start task execution/i.test(title)) {
    return buildStartTask({ event, data, dict })
  }
  const { fields, sections } = describeData(dict, data)
  return { tone: "info", headline: dict.text.debug, fields, sections }
}

function defaultTone(category, data) {
  if (category === "error" || data.is_error === true || data.success === false) return "danger"
  if (data.success === true || data.status === "success") return "success"
  return "info"
}

/**
 * Builds the readable representation of one event.
 *
 * @param {{category?: string, title?: string, data?: object}} event
 * @param {string} locale one of ``LOCALES`` (``src/i18n.js``).
 * @returns {{tone: string, headline: string, fields: Array, sections: Array}}
 */
export function buildFriendlyEvent(event, locale) {
  const dict = dictionaryFor(locale)
  const category = normalizeCategory(event?.category)
  const data = isPlainObject(event?.data) ? event.data : {}
  const builder = category === "debug" ? buildDebug : BUILDERS[category]
  const view = builder
    ? builder({ event, data, dict, category })
    : buildGeneric({ event, data, dict, category }, defaultTone(category, data))

  const headline =
    view.headline ||
    (event?.title ? String(event.title) : dict.text.generic)

  return {
    tone: view.tone || defaultTone(category, data),
    headline,
    fields: (view.fields || []).filter((field) => field && field.value !== undefined),
    sections: (view.sections || []).filter((section) => {
      if (!section) return false
      if (section.kind === "text" || section.kind === "thinking") return Boolean(section.text)
      if (section.kind === "entries") return Array.isArray(section.rows) && section.rows.length > 0
      if (section.kind === "blocks") return Array.isArray(section.items) && section.items.length > 0
      return false
    }),
    emptyText: dict.text.noDetails,
  }
}

/**
 * The reasoning trace on its own, for the tab that shows nothing else.
 *
 * Returning ``null`` when a turn has no trace is what lets the caller hide the tab
 * instead of opening it onto an empty panel.
 *
 * @param {{category?: string, title?: string, data?: object}} event
 * @param {string} locale
 * @returns {{kind: string, title: string, text: string, meta?: string} | null}
 */
export function buildReasoningView(event, locale) {
  const view = buildFriendlyEvent(event, locale)
  return view.sections.find((section) => section.kind === "thinking") || null
}
