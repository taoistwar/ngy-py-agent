import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { default as MonacoEditor } from "@monaco-editor/react"
import {
  createModel,
  createSession,
  createTask,
  deleteModel,
  deleteSession,
  deleteTask,
  fetchHealth,
  fetchModels,
  fetchRetentionConfig,
  fetchMaxStepsConfig,
  updateMaxStepsConfig,
  fetchSessions,
  fetchTask,
  fetchTaskEvents,
  fetchTasks,
  renameSession,
  updateModel,
  updateRetentionConfig,
} from "./api"
import {
  getDefaultLocale,
  getEventCategoryText,
  getLocaleOptions,
  getTaskStatusClass,
  getTaskStatusText,
  isTaskRunningStatus,
  LOCALE_KEY,
  t,
} from "./i18n"
import "./App.css"

const EVENT_PAGE_SIZE = 30
const TASK_PAGE_SIZE = 12

const MENU_ITEMS = [
  { key: "tasks", labelKey: "menuTasks" },
  { key: "models", labelKey: "menuModels" },
  { key: "config", labelKey: "menuConfig" },
]

const PROVIDER_OPTIONS = [
  "openai-compatible",
  "openai",
  "anthropic",
  "anthropic-compatible",
  "ollama",
  "gemini",
]

const MODE_OPTIONS = [
  { value: "build", labelKey: "modeBuild" },
  { value: "ask", labelKey: "modeAsk" },
  { value: "plan", labelKey: "modePlan" },
]

const MODE_LABEL_KEYS = {
  build: "modeBuild",
  ask: "modeAsk",
  plan: "modePlan",
}

const modeLabelKey = (mode) => MODE_LABEL_KEYS[mode] || "modeBuild"

const INPUT_TOKEN_PRESETS = [32768, 65536, 131072, 262144]
const OUTPUT_TOKEN_PRESETS = [8192, 16384, 32768, 65536]

function formatTokenCount(value) {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) return ""
  if (num % 1024 === 0) return `${num / 1024}K`
  if (num % 1000 === 0) return `${num / 1000}K`
  return String(num)
}

function formatTime(value) {
  if (!value) return ""
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) {
    return String(value)
  }
  return time.toLocaleString()
}

function shortenText(value, maxLength) {
  if (!value) return ""
  const text = String(value)
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 1)}...`
}

function safeStringify(value) {
  if (value === undefined) return ""
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function getRawEventPayload(event) {
  const category = String(event?.category || "").toLowerCase()
  const data = event?.data
  if (!data || typeof data !== "object") {
    return data
  }

  if (category === "llm_request") {
    if (data.raw_request !== undefined) {
      return data.raw_request
    }
    if (data.request_payload !== undefined) {
      return data.request_payload
    }
  }

  if (category === "llm_response") {
    if (data.response !== undefined) {
      return data.response
    }
    if (data.raw_response !== undefined) {
      return data.raw_response
    }
    if (data.response_payload !== undefined) {
      return data.response_payload
    }
  }

  return data
}

function getTaskResultFromEvents(events) {
  if (!Array.isArray(events)) {
    return null
  }

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const item = events[index]
    if (!item || typeof item !== "object") continue
    if (String(item.category).toLowerCase() !== "debug") continue
    const data = item.data
    if (!data || typeof data !== "object") continue
    if (!Object.prototype.hasOwnProperty.call(data, "result")) continue
    return data.result
  }
  return null
}

function getTaskResult(task, events) {
  if (task && Object.prototype.hasOwnProperty.call(task, "result") && task.result !== undefined) {
    return task.result
  }
  return getTaskResultFromEvents(events)
}

function getTagClass(category) {
  return `tag ${category}`
}

function getHealthClass(healthStatus) {
  if (healthStatus === "ok") {
    return "success"
  }
  if (healthStatus === "unavailable") {
    return "failed"
  }
  return "running"
}

function getHealthText(healthStatus, translate) {
  if (healthStatus === "ok") {
    return translate("healthOk")
  }
  if (healthStatus === "unavailable") {
    return translate("healthUnavailable")
  }
  if (healthStatus === "degraded") {
    return translate("statusDegraded")
  }
  return translate("unknown")
}

function TopBar({ activeMenu, onChangeMenu, health, tasks, locale, localeOptions, setLocale, systemTime, translate }) {
  return (
    <header className="admin-topbar">
      <div className="topbar-brand">
        <h1>{translate("appTitle")}</h1>
        <span className="topbar-subtitle">{translate("appSubtitle")}</span>
      </div>
      <nav className="topbar-nav">
        {MENU_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`nav-item ${activeMenu === item.key ? "active" : ""}`}
            onClick={() => onChangeMenu(item.key)}
          >
            {translate(item.labelKey)}
          </button>
        ))}
      </nav>
      <div className="topbar-right">
        <div className="metric-item">
          <em>{translate("healthLabel")}:</em>
          <strong className={`status ${getHealthClass(health)}`}>{getHealthText(health, translate)}</strong>
        </div>
        <div className="metric-item">
          <em>{translate("headerTaskCount")}:</em>
          <strong>{tasks.length}</strong>
        </div>
        <label className="lang-switch">
          <span>{translate("languageLabel")}</span>
          <select
            value={locale}
            className="lang-select"
            onChange={(event) => setLocale(event.target.value)}
          >
            {localeOptions.map((item) => (
              <option value={item.value} key={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="metric-item">
          <em>{translate("sidebarSystemTime")}:</em>
          <strong>{formatTime(systemTime)}</strong>
        </div>
      </div>
    </header>
  )
}

function SessionTabs({ sessions, activeSessionId, onSelect, onCreate, onRename, onDelete, translate }) {
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState("")
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState("")
  const addInputRef = useRef(null)

  useEffect(() => {
    if (adding) addInputRef.current?.focus()
  }, [adding])

  const beginRename = () => {
    const current = sessions.find((item) => item.session_id === activeSessionId)
    setRenameValue(current?.name || "")
    setRenaming(true)
  }

  const submitNew = () => {
    const value = newName.trim()
    if (!value) return
    onCreate(value)
    setNewName("")
    setAdding(false)
  }

  const submitRename = () => {
    const value = renameValue.trim()
    if (!value) return
    onRename(activeSessionId, value)
    setRenaming(false)
  }

  return (
    <section className="panel session-tabs-panel">
      <div className="panel-titlebar session-tabs-titlebar">
        <h2>{translate("sessionTitle")}</h2>
        <div className="task-toolbar-actions">
          {!adding && (
            <button type="button" className="btn btn-compact" onClick={() => setAdding(true)}>
              {translate("sessionAdd")}
            </button>
          )}
          {activeSessionId && !renaming && (
            <>
              <button type="button" className="btn btn-compact" onClick={beginRename}>
                {translate("sessionRename")}
              </button>
              <button
                type="button"
                className="btn btn-compact btn-danger"
                onClick={() => onDelete(activeSessionId)}
              >
                {translate("sessionDelete")}
              </button>
            </>
          )}
        </div>
      </div>
      <div className="panel-body session-tabs-body">
        <div className="session-tabs">
          {sessions.map((item) => (
            <button
              key={item.session_id}
              type="button"
              className={`session-tab ${item.session_id === activeSessionId ? "active" : ""}`}
              onClick={() => onSelect(item.session_id)}
            >
              <span className="session-tab-name">{item.name}</span>
              {item.task_count > 0 && <span className="session-tab-count">{item.task_count}</span>}
            </button>
          ))}
        </div>
        {adding && (
          <div className="session-add-row">
            <input
              ref={addInputRef}
              className="session-add-input"
              value={newName}
              placeholder={translate("sessionNamePlaceholder")}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") submitNew()
                if (event.key === "Escape") {
                  setAdding(false)
                  setNewName("")
                }
              }}
            />
            <button type="button" className="btn btn-compact" onClick={submitNew}>
              {translate("sessionAddConfirm")}
            </button>
            <button
              type="button"
              className="btn btn-compact"
              onClick={() => {
                setAdding(false)
                setNewName("")
              }}
            >
              {translate("dialogClose")}
            </button>
          </div>
        )}
        {renaming && (
          <div className="session-add-row">
            <input
              className="session-add-input"
              autoFocus
              value={renameValue}
              onChange={(event) => setRenameValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") submitRename()
                if (event.key === "Escape") setRenaming(false)
              }}
            />
            <button type="button" className="btn btn-compact" onClick={submitRename}>
              {translate("sessionAddConfirm")}
            </button>
            <button type="button" className="btn btn-compact" onClick={() => setRenaming(false)}>
              {translate("dialogClose")}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

function TaskList({
  tasks,
  selectedId,
  onSelect,
  onDelete,
  selectedTaskIds,
  isAllPageSelected,
  onSelectOne,
  onSelectAllPage,
  onBatchDelete,
  onRefresh,
  taskSearchQuery,
  onTaskSearch,
  page,
  totalPages,
  onPageChange,
  translate,
}) {
  const selectedCount = selectedTaskIds.size

  return (
    <section className="panel session-task-panel">
      <div className="panel-titlebar">
        <h2>{translate("taskListTitle")}</h2>
        <div className="task-toolbar-actions">
          <button type="button" className="btn btn-compact" onClick={onRefresh}>
            {translate("taskListRefresh")}
          </button>
          <button
            type="button"
            className="btn btn-compact btn-danger"
            onClick={onBatchDelete}
            disabled={selectedCount === 0}
          >
            {translate("taskListBatchDelete")}
          </button>
        </div>
      </div>
      <div className="panel-body session-task-body">
        <div className="task-search-bar">
          <input
            type="text"
            className="task-search-input"
            value={taskSearchQuery}
            placeholder={translate("taskSearchPlaceholder")}
            onChange={(event) => onTaskSearch(event.target.value)}
          />
        </div>
        {tasks.length === 0 ? (
          <div className="empty">{translate("taskNoTasks")}</div>
        ) : (
          <>
            <div className="session-task-head">
              <label className="task-select-label">
                <input type="checkbox" checked={isAllPageSelected} onChange={onSelectAllPage} />
                {translate("taskListColumnSelect")}
              </label>
              <span className="hint">
                {translate("taskListSelected")}: {selectedCount}
              </span>
            </div>
            <div className="session-task-rows">
              {tasks.map((item) => (
                <div
                  key={item.task_id}
                  className={`session-task-row ${item.task_id === selectedId ? "active" : ""}`}
                  onClick={() => onSelect(item.task_id)}
                  role="button"
                >
                  <label className="task-select-label" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedTaskIds.has(item.task_id)}
                      onChange={() => onSelectOne(item.task_id)}
                    />
                  </label>
                  <div className="session-task-info">
                    <div className="session-task-query" title={item.query}>
                      {shortenText(item.query, 90)}
                    </div>
                    <div className="session-task-meta">
                      <span className={`status ${getTaskStatusClass(item.status)}`}>
                        {getTaskStatusText(translate, item.status)}
                      </span>
                      <span className="hint">{formatTime(item.created_at)}</span>
                      {item.model_name ? (
                        <span className="hint">{item.model_name}</span>
                      ) : (
                        <span className="hint">{item.provider}</span>
                      )}
                      <span className={`badge badge-mode badge-mode-${item.mode || "build"}`}>
                        {translate(modeLabelKey(item.mode))}
                      </span>
                      <span className="hint">
                        {translate("taskEventCountPrefix")}: {item.event_count}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn btn-danger btn-xs"
                    onClick={(event) => {
                      event.stopPropagation()
                      onDelete(item.task_id)
                    }}
                  >
                    {translate("taskDelete")}
                  </button>
                </div>
              ))}
            </div>
            <div className="task-pagination">
              <button
                type="button"
                className="btn btn-compact"
                onClick={() => onPageChange(page - 1)}
                disabled={page <= 1}
              >
                {translate("taskListPrev")}
              </button>
              <span className="task-page-indicator">
                {translate("taskListPage")} {page} / {totalPages}
              </span>
              <button
                type="button"
                className="btn btn-compact"
                onClick={() => onPageChange(page + 1)}
                disabled={page >= totalPages}
              >
                {translate("taskListNext")}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function TaskComposer({ models, onCreate, translate }) {
  const [query, setQuery] = useState("")
  const [modelId, setModelId] = useState("")
  const [provider, setProvider] = useState("openai-compatible")
  const [mode, setMode] = useState("build")
  const [busy, setBusy] = useState(false)

  const effectiveModelId = modelId || (models && models.length ? models[0].model_id : "")

  const submit = async (event) => {
    event.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    try {
      const payload = { query, stream: false, mode }
      if (models && models.length) {
        payload.model_id = effectiveModelId
      } else {
        payload.provider = provider
      }
      await onCreate(payload)
      setQuery("")
    } catch {
      // surface errors through the global error banner
    } finally {
      setBusy(false)
    }
  }

  const onQueryKeyDown = (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      submit(event)
    }
  }

  return (
    <section className="panel task-composer-panel">
      <div className="panel-titlebar">
        <h2>{translate("taskComposerTitle")}</h2>
      </div>
      <div className="panel-body">
        <form className="task-composer" onSubmit={submit}>
          <label className="composer-field">
            <span>{translate("taskFormPrompt")}</span>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onQueryKeyDown}
              placeholder={translate("taskFormPlaceholder")}
            />
          </label>
          <div className="composer-fields">
            {models && models.length > 0 ? (
              <label className="composer-field">
                <span>{translate("taskFormModel")}</span>
                <select value={effectiveModelId} onChange={(event) => setModelId(event.target.value)}>
                  {models.map((item) => (
                    <option value={item.model_id} key={item.model_id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="composer-field">
                <span>{translate("taskFormProvider")}</span>
                <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                  {PROVIDER_OPTIONS.map((item) => (
                    <option value={item} key={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="composer-mode">
            <span className="composer-mode-label">{translate("modeLabel")}</span>
            <div className="segmented">
              {MODE_OPTIONS.map((option) => (
                <button
                  type="button"
                  key={option.value}
                  className={`segmented-item ${mode === option.value ? "active" : ""}`}
                  onClick={() => setMode(option.value)}
                >
                  {translate(option.labelKey)}
                </button>
              ))}
            </div>
            <span className="hint">{translate("modeHint")}</span>
          </div>
          <button className="btn" type="submit" disabled={busy || !query.trim()}>
            {busy ? translate("taskFormCreating") : translate("taskFormCreate")}
          </button>
        </form>
      </div>
    </section>
  )
}

function TaskDetail({ task, result, translate }) {
  if (!task) {
    return <div className="empty">{translate("taskSelectHint")}</div>
  }

  const hasResult = result !== undefined && result !== null
  const taskResult = hasResult ? (typeof result === "string" ? result : safeStringify(result)) : ""
  const resultText = hasResult ? taskResult : translate("detailNoResult")
  const queryText = task.query || ""

  return (
    <div className="detail-grid">
      <section className="detail-section">
        <p className="detail-section-title">{translate("taskDetailBasic")}</p>
        <div className="detail-item">
          <span>{translate("detailTaskId")}</span>
          <strong>{task.task_id}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("detailProvider")}</span>
          <strong>{task.provider}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("modeLabel")}</span>
          <strong>{translate(modeLabelKey(task.mode))}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("detailModel")}</span>
          <strong>{task.model_name || task.provider || "-"}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("detailStatus")}</span>
          <strong className={`status ${getTaskStatusClass(task.status)}`}>
            {getTaskStatusText(translate, task.status)}
          </strong>
        </div>
      </section>
      <section className="detail-section">
        <p className="detail-section-title">{translate("taskDetailRuntime")}</p>
        <div className="detail-item">
          <span>{translate("detailSession")}</span>
          <strong>{task.session_id || "-"}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("detailCreated")}</span>
          <strong>{formatTime(task.created_at)}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("detailUpdated")}</span>
          <strong>{formatTime(task.updated_at)}</strong>
        </div>
        <div className="detail-item">
          <span>{translate("detailEventsCount")}</span>
          <strong>{task.event_count || task.events?.length || 0}</strong>
        </div>
      </section>
      <section className="detail-section detail-section-query">
        <p className="detail-section-title">{translate("taskDetailPrompt")}</p>
        <div className="detail-json-editor">
          <MonacoEditor
            height="180px"
            defaultLanguage="plaintext"
            defaultValue={queryText}
            options={{
              readOnly: true,
              minimap: {
                enabled: false,
              },
              scrollBeyondLastLine: false,
              wordWrap: "on",
              fontSize: 14,
              lineNumbers: "on",
              renderLineHighlight: "none",
              automaticLayout: true,
            }}
            theme="vs-dark"
          />
        </div>
      </section>
      <section className="detail-section detail-section-result">
        <p className="detail-section-title">{translate("detailResult")}</p>
        <div className="detail-json-editor">
          <MonacoEditor
            height="180px"
            defaultLanguage="json"
            defaultValue={resultText}
            options={{
              readOnly: true,
              minimap: {
                enabled: false,
              },
              scrollBeyondLastLine: false,
              wordWrap: "on",
              fontSize: 14,
              folding: true,
              lineNumbers: "on",
              renderLineHighlight: "none",
              automaticLayout: true,
            }}
            theme="vs-dark"
          />
        </div>
      </section>
    </div>
  )
}

function TaskDetailPage({ task, taskResult, taskTab, setTaskTab, events, hasMoreEvents, isLoadingEvents, onLoadMore, translate }) {
  return (
    <section className="panel">
      <div className="task-page-titlebar">
        <div className="tab-strip" role="tablist" aria-label={translate("tabAria")}>
          <button
            type="button"
            className={`tab-btn ${taskTab === "detail" ? "active" : ""}`}
            onClick={() => setTaskTab("detail")}
          >
            {translate("taskDetailTitle")}
          </button>
          <button
            type="button"
            className={`tab-btn ${taskTab === "events" ? "active" : ""}`}
            onClick={() => setTaskTab("events")}
          >
            {translate("taskEventsTitle")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        {taskTab === "detail" ? (
          <TaskDetail task={task} result={taskResult} translate={translate} />
        ) : (
          <EventTimeline task={task} events={events} hasMore={hasMoreEvents} loadingMore={isLoadingEvents} onLoadMore={onLoadMore} translate={translate} />
        )}
      </div>
    </section>
  )
}

function EventItem({ event, collapsed, onToggle, translate }) {
  const rawPayload = getRawEventPayload(event)
  const jsonBody = safeStringify(rawPayload)

  return (
    <div className="event-card">
      <div className="event-header" onClick={onToggle}>
        <div className="event-title">
          <span className={getTagClass(event.category)}>
            {getEventCategoryText(translate, event.category)}
          </span>
          <span>{event.title}</span>
        </div>
        <div className="hint">{formatTime(event.timestamp)}</div>
      </div>
      {!collapsed && (
        <div className="event-body">
          <div className="event-json-editor">
            <MonacoEditor
              height="240px"
              defaultLanguage="json"
              defaultValue={jsonBody}
              options={{
                readOnly: true,
                minimap: {
                  enabled: false,
                },
                scrollBeyondLastLine: false,
                wordWrap: "on",
                fontSize: 14,
                folding: true,
                lineNumbers: "on",
                renderLineHighlight: "none",
                renderWhitespace: "all",
                automaticLayout: true,
              }}
              theme="vs-dark"
            />
          </div>
        </div>
      )}
    </div>
  )
}

function EventTimeline({ task, events, hasMore, loadingMore, onLoadMore, translate }) {
  const [collapsedMap, setCollapsedMap] = useState({})

  useEffect(() => {
    const next = {}
    events.forEach((event) => {
      if (collapsedMap[event.event_id] === undefined) {
        next[event.event_id] = event.collapsed ?? true
      }
    })
    if (Object.keys(next).length > 0) {
      setCollapsedMap((prev) => ({ ...prev, ...next }))
    }
  }, [events])

  if (!task) {
    return <div className="timeline-empty">{translate("taskEventsNoTask")}</div>
  }

  const ordered = [...events].reverse()

  return (
    <div>
      {ordered.length === 0 ? (
        <div className="timeline-empty">{translate("taskEventsNoRecords")}</div>
      ) : (
        <div className="timeline">
          {ordered.map((event) => (
            <EventItem
              key={event.event_id}
              event={event}
              collapsed={collapsedMap[event.event_id]}
              onToggle={() =>
                setCollapsedMap((prev) => ({
                  ...prev,
                  [event.event_id]: !prev[event.event_id],
                }))
              }
              translate={translate}
            />
          ))}
        </div>
      )}
      {events.length > 0 && (
        <div className="load-more">
          <button
            type="button"
            className="btn"
            onClick={onLoadMore}
            disabled={loadingMore || !hasMore}
          >
            {loadingMore ? translate("eventsLoading") : translate("eventsLoadMore")}
          </button>
          {!hasMore && <span className="hint">{translate("eventsNoMore")}</span>}
        </div>
      )}
    </div>
  )
}

function TokenLimitField({ label, value, presets, onChange, translate }) {
  const current = String(value ?? "").trim()

  return (
    <div className="token-field">
      <span className="token-field-label">{label}</span>
      <input
        type="text"
        inputMode="numeric"
        value={current}
        placeholder={translate("modelFormTokensDefault")}
        onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))}
      />
      <div className="token-presets">
        {presets.map((preset) => {
          const isActive = current === String(preset)
          return (
            <button
              key={preset}
              type="button"
              className={`token-preset ${isActive ? "active" : ""}`}
              onClick={() => onChange(isActive ? "" : String(preset))}
            >
              {formatTokenCount(preset)}
            </button>
          )
        })}
        <button
          type="button"
          className="token-preset token-preset-clear"
          disabled={!current}
          onClick={() => onChange("")}
        >
          {translate("modelFormTokensClear")}
        </button>
      </div>
      <span className="token-field-hint">
        {current ? `${current} tokens` : translate("modelFormTokensDefaultHint")}
      </span>
    </div>
  )
}

function ModelManager({ models, onCreate, onUpdate, onDelete, onRefresh, translate }) {
  const [form, setForm] = useState({
    model_id: "",
    name: "",
    provider: "openai-compatible",
    base_url: "",
    api_key: "",
    supports_tool_calls: true,
    supports_image_input: false,
    thinking_mode: false,
    max_input_tokens: "",
    max_output_tokens: "",
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const editingId = form.model_id

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const startEdit = (model) => {
    setError("")
    setForm({
      model_id: model.model_id,
      name: model.name || "",
      provider: model.provider || "openai-compatible",
      base_url: model.base_url || "",
      api_key: model.api_key || "",
      supports_tool_calls: model.supports_tool_calls !== false,
      supports_image_input: model.supports_image_input === true,
      thinking_mode: model.thinking_mode === true,
      max_input_tokens: model.max_input_tokens ? String(model.max_input_tokens) : "",
      max_output_tokens: model.max_output_tokens ? String(model.max_output_tokens) : "",
    })
  }

  const resetForm = () => {
    setForm({
      model_id: "",
      name: "",
      provider: "openai-compatible",
      base_url: "",
      api_key: "",
      supports_tool_calls: true,
      supports_image_input: false,
      thinking_mode: false,
      max_input_tokens: "",
      max_output_tokens: "",
    })
    setError("")
  }

  const submit = async (event) => {
    event.preventDefault()
    setError("")
    if (!form.name.trim()) {
      setError(translate("modelNameRequired"))
      return
    }
    setBusy(true)
    const payload = {
      name: form.name.trim(),
      provider: form.provider,
      base_url: form.base_url.trim(),
      api_key: form.api_key,
      supports_tool_calls: form.supports_tool_calls,
      supports_image_input: form.supports_image_input,
      thinking_mode: form.thinking_mode,
      max_input_tokens: Number(form.max_input_tokens) || 0,
      max_output_tokens: Number(form.max_output_tokens) || 0,
    }
    try {
      if (editingId) {
        await onUpdate(editingId, payload)
      } else {
        await onCreate(payload)
      }
      resetForm()
    } catch {
      // error surfaced through the global banner
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (model) => {
    if (!window.confirm(`${translate("modelDeleteConfirm")} (${model.name})`)) return
    try {
      await onDelete(model.model_id)
    } catch {
      // error surfaced through the global banner
    }
  }

  return (
    <section className="panel model-manager">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("modelManagerTitle")}</h2>
          <span className="hint">{translate("modelManagerHint")}</span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("modelListRefresh")}
        </button>
      </div>
      <div className="panel-body">
        <form className="model-form form-grid" onSubmit={submit}>
          <p className="model-form-heading">
            {editingId ? translate("modelFormEdit") : translate("modelFormCreate")}
          </p>
          <label>
            <span>{translate("modelFormName")}</span>
            <input value={form.name} onChange={(event) => setField("name", event.target.value)} placeholder={translate("modelFormNamePlaceholder")} />
          </label>
          <label>
            <span>{translate("modelFormProvider")}</span>
            <select value={form.provider} onChange={(event) => setField("provider", event.target.value)}>
              {PROVIDER_OPTIONS.map((item) => (
                <option value={item} key={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{translate("modelFormBaseUrl")}</span>
            <input value={form.base_url} onChange={(event) => setField("base_url", event.target.value)} placeholder={translate("modelFormBaseUrlPlaceholder")} />
          </label>
          <label>
            <span>{translate("modelFormApiKey")}</span>
            <input type="password" value={form.api_key} onChange={(event) => setField("api_key", event.target.value)} placeholder={translate("modelFormApiKeyPlaceholder")} />
          </label>
          <div className="model-form-checks">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.supports_tool_calls}
                onChange={(event) => setField("supports_tool_calls", event.target.checked)}
              />
              {translate("modelFormToolCalls")}
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.supports_image_input}
                onChange={(event) => setField("supports_image_input", event.target.checked)}
              />
              {translate("modelFormImageInput")}
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.thinking_mode}
                onChange={(event) => setField("thinking_mode", event.target.checked)}
              />
              {translate("modelFormThinking")}
            </label>
          </div>
          <div className="model-form-tokens">
            <TokenLimitField
              label={translate("modelFormMaxInput")}
              value={form.max_input_tokens}
              presets={INPUT_TOKEN_PRESETS}
              onChange={(value) => setField("max_input_tokens", value)}
              translate={translate}
            />
            <TokenLimitField
              label={translate("modelFormMaxOutput")}
              value={form.max_output_tokens}
              presets={OUTPUT_TOKEN_PRESETS}
              onChange={(value) => setField("max_output_tokens", value)}
              translate={translate}
            />
          </div>
          {error && <div className="form-error">{error}</div>}
          <div className="model-form-actions">
            <button type="submit" className="btn" disabled={busy}>
              {busy ? translate("modelFormSaving") : editingId ? translate("modelFormUpdate") : translate("modelFormSave")}
            </button>
            {editingId && (
              <button type="button" className="btn btn-compact" onClick={resetForm}>
                {translate("modelFormCancel")}
              </button>
            )}
          </div>
        </form>

        <div className="model-list">
          {models.length === 0 ? (
            <div className="empty">{translate("modelListEmpty")}</div>
          ) : (
            <table className="model-table">
              <thead>
                <tr>
                  <th>{translate("modelListName")}</th>
                  <th>{translate("modelListProvider")}</th>
                  <th>{translate("modelListBaseUrl")}</th>
                  <th>{translate("modelListToolCalls")}</th>
                  <th>{translate("modelListImageInput")}</th>
                  <th>{translate("modelListThinking")}</th>
                  <th>{translate("modelListTokens")}</th>
                  <th>{translate("modelListActions")}</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model) => (
                  <tr key={model.model_id}>
                    <td className="model-name">{model.name}</td>
                    <td>
                      <code>{model.provider}</code>
                    </td>
                    <td className="mono">{model.base_url || "-"}</td>
                    <td className={model.supports_tool_calls ? "flag-on" : "flag-off"}>
                      {model.supports_tool_calls ? translate("yes") : translate("no")}
                    </td>
                    <td className={model.supports_image_input ? "flag-on" : "flag-off"}>
                      {model.supports_image_input ? translate("yes") : translate("no")}
                    </td>
                    <td className={model.thinking_mode ? "flag-on" : "flag-off"}>
                      {model.thinking_mode ? translate("yes") : translate("no")}
                    </td>
                    <td className="mono">
                      {model.max_input_tokens ? formatTokenCount(model.max_input_tokens) : "-"}/
                      {model.max_output_tokens ? formatTokenCount(model.max_output_tokens) : "-"}
                    </td>
                    <td className="model-actions">
                      <button type="button" className="btn btn-xs" onClick={() => startEdit(model)}>
                        {translate("modelEdit")}
                      </button>
                      <button type="button" className="btn btn-danger btn-xs" onClick={() => handleDelete(model)}>
                        {translate("modelDelete")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  )
}

function MaxStepsManager({ maxStepsConfig, onSave, onRefresh, translate }) {
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!maxStepsConfig) return
    setValue(String(maxStepsConfig.max_steps ?? 8))
  }, [maxStepsConfig])

  const submit = async (event) => {
    event.preventDefault()
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < 1) return
    setBusy(true)
    try {
      await onSave(Math.max(1, Math.min(parsed, 40)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("maxStepsTitle")}</h2>
          <span className="hint">
            {translate("maxStepsCurrentSource")}:{" "}
            {maxStepsConfig?.source === "database"
              ? translate("maxStepsSourceDb")
              : translate("maxStepsSourceEnv")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshMaxSteps")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("maxStepsCurrent")}</span>
            <input type="text" readOnly value={maxStepsConfig ? maxStepsConfig.max_steps : ""} />
          </label>
          <label>
            <span>{translate("maxStepsSet")}</span>
            <input type="number" min="1" max="40" value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
          <button type="submit" className="btn" disabled={busy || !value}>
            {busy ? translate("maxStepsSaving") : translate("maxStepsSave")}
          </button>
        </form>
        <div className="hint">{translate("maxStepsHint")}</div>
      </div>
    </section>
  )
}

function RetentionManager({ retentionConfig, onSave, onRefresh, translate }) {
  const [days, setDays] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!retentionConfig) return
    setDays(String(retentionConfig.retention_days ?? 0))
  }, [retentionConfig])

  const submit = async (event) => {
    event.preventDefault()
    const parsed = Number(days)
    if (!Number.isFinite(parsed) || parsed < 0) return
    setBusy(true)
    try {
      await onSave(parsed)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("retentionTitle")}</h2>
          <span className="hint">
            {translate("retentionCurrentSource")}:{" "}
            {retentionConfig?.retention_source === "database"
              ? translate("retentionSourceDb")
              : translate("retentionSourceEnv")}
          </span>
        </div>
        <button type="button" className="btn btn-compact" onClick={onRefresh}>
          {translate("sidebarQuickRefreshRetention")}
        </button>
      </div>
      <div className="panel-body">
        <form className="form-grid" onSubmit={submit}>
          <label>
            <span>{translate("retentionCurrentDays")}</span>
            <input type="text" readOnly value={retentionConfig ? retentionConfig.retention_days : ""} />
          </label>
          <label>
            <span>{translate("retentionSetDays")}</span>
            <input type="number" min="0" value={days} onChange={(event) => setDays(event.target.value)} />
          </label>
          <button type="submit" className="btn" disabled={busy || !days}>
            {busy ? translate("retentionSaving") : translate("retentionSave")}
          </button>
        </form>
        <div className="hint">{translate("retentionHint")}</div>
      </div>
    </section>
  )
}

export default function App() {
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState("")
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState("")
  const [selectedTask, setSelectedTask] = useState(null)
  const [events, setEvents] = useState([])
  const [hasMoreEvents, setHasMoreEvents] = useState(false)
  const [isLoadingEvents, setIsLoadingEvents] = useState(false)
  const [error, setError] = useState("")
  const [retentionConfig, setRetentionConfig] = useState(null)
  const [maxStepsConfig, setMaxStepsConfig] = useState(null)
  const [health, setHealth] = useState("unknown")
  const [models, setModels] = useState([])
  const [activeMenu, setActiveMenu] = useState("tasks")
  const [taskTab, setTaskTab] = useState("detail")
  const [locale, setLocale] = useState(getDefaultLocale())
  const [selectedTaskIds, setSelectedTaskIds] = useState(new Set())
  const [taskPage, setTaskPage] = useState(1)
  const [systemTime, setSystemTime] = useState(() => new Date())
  const [taskSearchQuery, setTaskSearchQuery] = useState("")

  const translate = useCallback((key) => t(locale, key), [locale])
  const localeOptions = useMemo(() => getLocaleOptions(locale), [locale])

  const activeSessionRef = useRef(activeSessionId)
  const selectedIdRef = useRef(selectedId)
  activeSessionRef.current = activeSessionId
  selectedIdRef.current = selectedId
  const nextOffsetRef = useRef(0)
  const isRunningRef = useRef(false)

  const taskResult = useMemo(() => getTaskResult(selectedTask, events), [selectedTask, events])

  const taskSearchValue = taskSearchQuery.trim().toLowerCase()
  const filteredTasks = useMemo(() => {
    if (!taskSearchValue) return tasks
    return tasks.filter((task) => {
      const matchText = [task.task_id, task.provider, task.status, task.query, task.model_name]
        .join(" ")
        .toLowerCase()
      return matchText.includes(taskSearchValue)
    })
  }, [tasks, taskSearchValue])

  const totalTaskPages = useMemo(
    () => Math.max(1, Math.ceil(filteredTasks.length / TASK_PAGE_SIZE)),
    [filteredTasks.length]
  )
  const currentTaskPage = Math.min(Math.max(taskPage, 1), totalTaskPages)

  const pagedTasks = useMemo(
    () =>
      filteredTasks.slice((currentTaskPage - 1) * TASK_PAGE_SIZE, currentTaskPage * TASK_PAGE_SIZE),
    [filteredTasks, currentTaskPage]
  )

  const isAllPageSelected = useMemo(
    () => pagedTasks.length > 0 && pagedTasks.every((item) => selectedTaskIds.has(item.task_id)),
    [pagedTasks, selectedTaskIds]
  )

  useEffect(() => {
    if (typeof window === "undefined") return
    try {
      window.localStorage.setItem(LOCALE_KEY, locale)
    } catch {
      // ignore storage errors
    }
  }, [locale])

  useEffect(() => {
    const timer = setInterval(() => setSystemTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setTaskPage(1)
  }, [taskSearchValue, totalTaskPages, activeSessionId])

  useEffect(() => {
    const idSet = new Set(tasks.map((task) => task.task_id))
    setSelectedTaskIds((prev) => {
      const next = new Set()
      let changed = false
      prev.forEach((id) => {
        if (idSet.has(id)) next.add(id)
        else changed = true
      })
      if (!changed && next.size === prev.size) return prev
      return next
    })
  }, [tasks])

  const refreshTasks = useCallback(async () => {
    const sid = activeSessionRef.current
    if (!sid) return
    const list = await fetchTasks(sid)
    setTasks(list)
    const current = selectedIdRef.current
    if (list.length === 0) {
      setSelectedId("")
    } else if (!current || !list.some((item) => item.task_id === current)) {
      setSelectedId(list[0].task_id)
    }
  }, [])

  const refreshTask = useCallback(async (taskId) => {
    const target = taskId || selectedIdRef.current
    if (!target) return null
    const task = await fetchTask(target)
    setSelectedTask(task)
    return task
  }, [])

  const refreshModels = useCallback(async () => {
    const list = await fetchModels()
    setModels(list)
    return list
  }, [])

  const refreshSessions = useCallback(async () => {
    const list = await fetchSessions()
    setSessions(list)
    return list
  }, [])

  const refreshRetention = useCallback(async () => {
    const config = await fetchRetentionConfig()
    setRetentionConfig(config)
  }, [])

  const refreshHealth = useCallback(async () => {
    try {
      const result = await fetchHealth()
      setHealth(result?.status === "ok" ? "ok" : result?.status || "degraded")
    } catch {
      setHealth("unavailable")
    }
  }, [])

  const loadEvents = useCallback(async (taskId, reset = false, taskStatus = null, force = false) => {
    const target = taskId || selectedIdRef.current
    const status = taskStatus ?? selectedTask?.status

    if (!force && status && !isTaskRunningStatus(status)) {
      return
    }
    if (!target || isRunningRef.current) return

    setIsLoadingEvents(true)
    isRunningRef.current = true

    try {
      const offset = reset ? 0 : nextOffsetRef.current
      const result = await fetchTaskEvents(target, { offset, limit: EVENT_PAGE_SIZE })
      const items = result?.items || []

      if (reset) {
        setEvents(items)
      } else {
        setEvents((prev) => {
          const existed = new Set(prev.map((item) => item.event_id))
          return [...prev, ...items.filter((item) => !existed.has(item.event_id))]
        })
      }

      setHasMoreEvents(Boolean(result?.has_more))
      nextOffsetRef.current = result?.next_offset || 0
    } catch (loadError) {
      setError(loadError?.message || translate("errorUnknown"))
    } finally {
      setIsLoadingEvents(false)
      isRunningRef.current = false
    }
  }, [selectedTask?.status, translate])

  const selectTask = useCallback(
    (taskId) => {
      setSelectedId(taskId)
      setSelectedTask(null)
      setEvents([])
      nextOffsetRef.current = 0
      setHasMoreEvents(false)
      setError("")
      setTaskTab("detail")
      refreshTask(taskId)
      loadEvents(taskId, true, null, true)
    },
    [loadEvents, refreshTask]
  )

  const selectSession = useCallback(
    async (sessionId) => {
      setActiveSessionId(sessionId)
      setSelectedId("")
      setSelectedTask(null)
      setEvents([])
      nextOffsetRef.current = 0
      setHasMoreEvents(false)
      setTaskPage(1)
      setError("")
      try {
        const list = await fetchTasks(sessionId)
        setTasks(list)
        if (list.length > 0) {
          setSelectedId(list[0].task_id)
        } else {
          setSelectedId("")
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [translate]
  )

  const changeTaskPage = useCallback(
    (nextPage) => {
      if (nextPage < 1 || nextPage > totalTaskPages) return
      setTaskPage(nextPage)
    },
    [totalTaskPages]
  )

  const createNewSession = useCallback(
    async (name) => {
      try {
        const created = await createSession(name)
        await refreshSessions()
        if (created?.session_id) {
          await selectSession(created.session_id)
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [refreshSessions, selectSession, translate]
  )

  const renameSessionHandler = useCallback(
    async (sessionId, name) => {
      try {
        await renameSession(sessionId, name)
        await refreshSessions()
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [refreshSessions, translate]
  )

  const deleteSessionHandler = useCallback(
    async (sessionId) => {
      if (!window.confirm(translate("sessionDeleteConfirm"))) return
      try {
        const list = await fetchSessions()
        if (list.length <= 1) {
          setError(translate("sessionDeleteLast"))
          return
        }
        await deleteSession(sessionId)
        const nextList = await fetchSessions()
        setSessions(nextList)
        if (sessionId === activeSessionRef.current) {
          const nextId = nextList[0]?.session_id || ""
          await selectSession(nextId)
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [selectSession, translate]
  )

  const createNewTask = useCallback(
    async (payload) => {
      try {
        setError("")
        const result = await createTask({ ...payload, session_id: activeSessionRef.current })
        if (result?.task_id) {
          setSelectedId(result.task_id)
          setEvents([])
          nextOffsetRef.current = 0
          setHasMoreEvents(false)
          setTaskTab("detail")
          const task = await refreshTask(result.task_id)
          await loadEvents(result.task_id, true, task?.status, true)
          await refreshTasks()
          await refreshSessions()
        }
      } catch (createError) {
        setError(createError?.message || translate("errorUnknown"))
        throw createError
      }
    },
    [loadEvents, refreshTask, refreshTasks, refreshSessions, translate]
  )

  const selectTaskForBatch = useCallback((taskId) => {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      if (next.has(taskId)) {
        next.delete(taskId)
      } else {
        next.add(taskId)
      }
      return next
    })
  }, [])

  const selectAllPageForBatch = useCallback(() => {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      if (isAllPageSelected) {
        pagedTasks.forEach((task) => next.delete(task.task_id))
      } else {
        pagedTasks.forEach((task) => next.add(task.task_id))
      }
      return next
    })
  }, [isAllPageSelected, pagedTasks])

  const deleteTaskItem = useCallback(
    async (taskId) => {
      if (!taskId) return
      if (!window.confirm(translate("taskDeleteConfirm"))) return

      try {
        setError("")
        await deleteTask(taskId)
        setSelectedTaskIds((prev) => {
          const next = new Set(prev)
          next.delete(taskId)
          return next
        })

        const taskDeleted = selectedIdRef.current === taskId
        const nextTasks = tasks.filter((item) => item.task_id !== taskId)

        if (taskDeleted) {
          setSelectedTask(null)
          setEvents([])
          nextOffsetRef.current = 0
          setHasMoreEvents(false)
          if (nextTasks.length > 0) {
            const nextId = nextTasks[0].task_id
            setSelectedId(nextId)
            const task = await refreshTask(nextId)
            await loadEvents(nextId, true, task?.status, true)
          } else {
            setSelectedId("")
          }
        }

        await refreshTasks()
      } catch (deleteError) {
        setError(deleteError?.message || translate("errorUnknown"))
      }
    },
    [loadEvents, refreshTask, refreshTasks, tasks, translate]
  )

  const deleteTaskSelection = useCallback(async () => {
    const ids = Array.from(selectedTaskIds)
    if (ids.length === 0) return
    if (!window.confirm(`${translate("taskListBatchDeleteConfirm")} (${ids.length})`)) return

    try {
      setError("")
      await Promise.all(ids.map((taskId) => deleteTask(taskId)))
      setSelectedTaskIds(new Set())

      if (selectedIdRef.current && ids.includes(selectedIdRef.current)) {
        const remaining = tasks.filter((task) => !ids.includes(task.task_id))
        setSelectedTask(null)
        setEvents([])
        nextOffsetRef.current = 0
        setHasMoreEvents(false)
        if (remaining.length > 0) {
          const nextId = remaining[0].task_id
          setSelectedId(nextId)
          const task = await fetchTask(nextId)
          await loadEvents(nextId, true, task?.status, true)
        } else {
          setSelectedId("")
        }
      }

      await refreshTasks()
    } catch (deleteError) {
      setError(deleteError?.message || translate("errorUnknown"))
    }
  }, [loadEvents, refreshTasks, selectedTaskIds, tasks, translate])

  const createModelHandler = useCallback(
    async (payload) => {
      try {
        await createModel(payload)
        await refreshModels()
      } catch (modelError) {
        setError(modelError?.message || translate("errorUnknown"))
        throw modelError
      }
    },
    [refreshModels, translate]
  )

  const updateModelHandler = useCallback(
    async (modelId, payload) => {
      try {
        await updateModel(modelId, payload)
        await refreshModels()
      } catch (modelError) {
        setError(modelError?.message || translate("errorUnknown"))
        throw modelError
      }
    },
    [refreshModels, translate]
  )

  const deleteModelHandler = useCallback(
    async (modelId) => {
      try {
        await deleteModel(modelId)
        await refreshModels()
      } catch (modelError) {
        setError(modelError?.message || translate("errorUnknown"))
      }
    },
    [refreshModels, translate]
  )

  const updateRetention = useCallback(
    async (daysValue) => {
      try {
        const config = await updateRetentionConfig(daysValue)
        setRetentionConfig(config)
      } catch (retentionError) {
        setError(retentionError?.message || translate("errorUnknown"))
      }
    },
    [translate]
  )

  const refreshMaxSteps = useCallback(async () => {
    const config = await fetchMaxStepsConfig()
    setMaxStepsConfig(config)
    return config
  }, [])

  const updateMaxSteps = useCallback(
    async (stepsValue) => {
      try {
        const config = await updateMaxStepsConfig(stepsValue)
        setMaxStepsConfig(config)
      } catch (maxStepsError) {
        setError(maxStepsError?.message || translate("errorUnknown"))
      }
    },
    [translate]
  )

  useEffect(() => {
    let cancelled = false
    const loadAll = async () => {
      try {
        const sessionList = await fetchSessions()
        if (cancelled) return
        setSessions(sessionList)
        const modelList = await fetchModels()
        if (cancelled) return
        setModels(modelList)

        const sid = activeSessionRef.current || (sessionList[0]?.session_id ?? "")
        if (sid) {
          if (sid !== activeSessionRef.current) setActiveSessionId(sid)
          const taskList = await fetchTasks(sid)
          if (cancelled) return
          setTasks(taskList)
          if (taskList.length > 0) {
            const current = selectedIdRef.current
            if (!current || !taskList.some((item) => item.task_id === current)) {
              setSelectedId(taskList[0].task_id)
            }
          } else {
            setSelectedId("")
          }
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError?.message || translate("errorLoadFailed"))
      }
    }

    loadAll().catch((loadError) => setError(loadError?.message || translate("errorLoadFailed")))
    refreshRetention().catch((retentionError) =>
      setError(retentionError?.message || translate("errorLoadFailed"))
    )
    refreshMaxSteps().catch((maxStepsError) =>
      setError(maxStepsError?.message || translate("errorLoadFailed"))
    )
    refreshHealth().catch(() => {})

    const timer = setInterval(() => {
      refreshHealth().catch(() => {})
      refreshRetention().catch((retentionError) =>
        setError(retentionError?.message || translate("errorLoadFailed"))
      )
      if (activeMenu === "tasks") {
        refreshTasks().catch((tasksError) => setError(tasksError?.message || translate("errorLoadFailed")))
      }
      if (activeMenu === "models") {
        refreshModels().catch(() => {})
      }
      if (activeMenu === "config") {
        refreshMaxSteps().catch(() => {})
      }
    }, 5000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [activeMenu, refreshHealth, refreshMaxSteps, refreshModels, refreshRetention, refreshTasks, translate])

  useEffect(() => {
    if (!selectedId || activeMenu !== "tasks") return

    const init = async () => {
      const task = await refreshTask(selectedId)
      await loadEvents(selectedId, true, task?.status, true)
    }
    init().catch((loadError) => setError(loadError?.message || translate("errorLoadFailed")))
  }, [activeMenu, selectedId, loadEvents, refreshTask, translate])

  useEffect(() => {
    if (!selectedId || activeMenu !== "tasks") return

    const timer = setInterval(() => {
      refreshTask(selectedId)
        .then((task) => {
          if (!task) return
          if (isTaskRunningStatus(task.status)) {
            loadEvents(selectedId, false, task.status)
          }
        })
        .catch(() => {})
    }, 1000)

    return () => clearInterval(timer)
  }, [activeMenu, selectedId, loadEvents, refreshTask])

  return (
    <div className="admin-root">
      <TopBar
        activeMenu={activeMenu}
        onChangeMenu={(menu) => {
          setActiveMenu(menu)
          setTaskTab("detail")
        }}
        health={health}
        tasks={tasks}
        locale={locale}
        localeOptions={localeOptions}
        setLocale={setLocale}
        systemTime={systemTime}
        translate={translate}
      />
      {error && <div className="global-error">{error}</div>}
      <main className="admin-content">
        {activeMenu === "tasks" ? (
          <div className="task-workspace">
            <aside className="task-column">
              <SessionTabs
                sessions={sessions}
                activeSessionId={activeSessionId}
                onSelect={selectSession}
                onCreate={createNewSession}
                onRename={renameSessionHandler}
                onDelete={deleteSessionHandler}
                translate={translate}
              />
              <TaskList
                tasks={pagedTasks}
                selectedId={selectedId}
                onSelect={selectTask}
                onDelete={deleteTaskItem}
                selectedTaskIds={selectedTaskIds}
                isAllPageSelected={isAllPageSelected}
                onSelectOne={selectTaskForBatch}
                onSelectAllPage={selectAllPageForBatch}
                onBatchDelete={deleteTaskSelection}
                onRefresh={refreshTasks}
                taskSearchQuery={taskSearchQuery}
                onTaskSearch={setTaskSearchQuery}
                page={currentTaskPage}
                totalPages={totalTaskPages}
                onPageChange={changeTaskPage}
                translate={translate}
              />
              <TaskComposer models={models} onCreate={createNewTask} translate={translate} />
            </aside>
            <section className="task-detail-pane">
              <TaskDetailPage
                task={selectedTask}
                taskResult={taskResult}
                taskTab={taskTab}
                setTaskTab={setTaskTab}
                events={events}
                hasMoreEvents={hasMoreEvents}
                isLoadingEvents={isLoadingEvents}
                onLoadMore={() => loadEvents(selectedId, false, null, true)}
                translate={translate}
              />
            </section>
          </div>
        ) : activeMenu === "models" ? (
          <ModelManager
            models={models}
            onCreate={createModelHandler}
            onUpdate={updateModelHandler}
            onDelete={deleteModelHandler}
            onRefresh={refreshModels}
            translate={translate}
          />
        ) : activeMenu === "config" ? (
          <div className="config-stack">
            <MaxStepsManager
              maxStepsConfig={maxStepsConfig}
              onSave={updateMaxSteps}
              onRefresh={refreshMaxSteps}
              translate={translate}
            />
            <RetentionManager
              retentionConfig={retentionConfig}
              onSave={updateRetention}
              onRefresh={() =>
                refreshRetention().catch((refreshError) =>
                  setError(refreshError?.message || translate("errorLoadFailed"))
                )
              }
              translate={translate}
            />
          </div>
        ) : (
          <RetentionManager
            retentionConfig={retentionConfig}
            onSave={updateRetention}
            onRefresh={() =>
              refreshRetention().catch((refreshError) =>
                setError(refreshError?.message || translate("errorLoadFailed"))
              )
            }
            translate={translate}
          />
        )}
      </main>
    </div>
  )
}
