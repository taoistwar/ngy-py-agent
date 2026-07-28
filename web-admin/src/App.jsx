import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { default as MonacoEditor } from "@monaco-editor/react"
import {
  createTask,
  deleteTask,
  fetchHealth,
  fetchRetentionConfig,
  fetchTask,
  fetchTaskEvents,
  fetchTasks,
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

const MENU_GROUPS = [
  {
    key: "operations",
    labelKey: "menuGroupOperations",
    items: [
      { key: "tasks", labelKey: "menuTasks" },
      { key: "backup", labelKey: "menuBackup" },
    ],
  },
]

const PROVIDER_OPTIONS = [
  "openai-compatible",
  "openai",
  "anthropic",
  "anthropic-compatible",
  "ollama",
  "gemini",
]

const TASK_COLUMNS = [
  {
    key: "task_id",
    labelKey: "taskListColumnId",
    width: "120px",
    align: "left",
    sortable: true,
  },
  {
    key: "query",
    labelKey: "taskListColumnQuery",
    width: "1.8fr",
    align: "left",
    sortable: true,
  },
  {
    key: "status",
    labelKey: "taskListColumnStatus",
    width: "120px",
    align: "left",
    sortable: true,
  },
  {
    key: "provider",
    labelKey: "taskListColumnProvider",
    width: "130px",
    align: "left",
    sortable: true,
  },
  {
    key: "created_at",
    labelKey: "taskListColumnCreated",
    width: "155px",
    align: "left",
    sortable: true,
  },
]

const TASK_SORT_DEFAULT = "created_at"
const TASK_SORT_DEFAULT_DIR = "desc"

function getTaskListValue(task, key) {
  if (key === "status") {
    return String(task.status || "").toLowerCase()
  }
  if (key === "created_at") {
    return task[key] ? new Date(task[key]).getTime() : 0
  }
  return task[key] ?? ""
}

function compareTaskValues(a, b) {
  if (a === b) return 0
  if (typeof a === "number" && typeof b === "number") {
    return a - b
  }
  return String(a).localeCompare(String(b))
}

function createTaskGridTemplate(columns) {
  return `34px ${columns.map((column) => column.width || "1fr").join(" ")} 84px`
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

function TaskList({
  tasks,
  selectedId,
  columns,
  sortBy,
  sortDirection,
  draggingColumn,
  dragTargetColumn,
  selectedTaskIds,
  isAllPageSelected,
  onSelect,
  onAddTask,
  onSelectOne,
  onSelectAllPage,
  onSort,
  onColumnDragStart,
  onColumnDragOver,
  onColumnDrop,
  onColumnDragEnd,
  onRefresh,
  taskSearchQuery,
  onTaskSearch,
  onDelete,
  onBatchDelete,
  page,
  totalPages,
  onPageChange,
  translate,
}) {
  const selectedCount = selectedTaskIds.size
  const gridTemplateColumns = createTaskGridTemplate(columns)

  const renderColumnCell = (item, column) => {
    if (column.key === "task_id") {
      return <span className="task-id">{shortenText(item.task_id, 14)}</span>
    }
    if (column.key === "query") {
      return (
        <span className="task-query" title={item.query}>
          {shortenText(item.query, 90)}
        </span>
      )
    }
    if (column.key === "status") {
      return (
        <span className={`status ${getTaskStatusClass(item.status)}`}>
          {getTaskStatusText(translate, item.status)}
        </span>
      )
    }
    if (column.key === "created_at") {
      return <span>{formatTime(item.created_at)}</span>
    }
    return <span>{item[column.key]}</span>
  }

  const headerSortedClass = (columnKey) =>
    `${columnKey === sortBy ? "sorted" : ""} ${draggingColumn === columnKey ? "dragging" : ""} ${
      dragTargetColumn === columnKey ? "drop-target" : ""
    }`.trim()

  const onDropColumn = (columnKey) => {
    onColumnDrop(columnKey)
  }

  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("taskListTitle")}</h2>
          <div className="hint">
            {selectedCount > 0
              ? `${translate("taskListSelected")}: ${selectedCount}`
              : `${translate("taskListHint")}`}
          </div>
        </div>
        <div className="task-toolbar-actions">
          <button type="button" className="btn" onClick={onAddTask}>
            {translate("taskListAdd")}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={onBatchDelete}
            disabled={selectedCount === 0}
          >
            {translate("taskListBatchDelete")}
          </button>
          <button type="button" className="btn" onClick={onRefresh}>
            {translate("taskListRefresh")}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <div className="task-search-bar">
          <label className="task-search-label">
            {translate("sidebarTaskSearch")}
            <input
              type="text"
              className="task-search-input"
              value={taskSearchQuery}
              placeholder={translate("taskSearchPlaceholder")}
              onChange={(event) => onTaskSearch(event.target.value)}
              aria-label={translate("sidebarTaskSearch")}
            />
          </label>
        </div>
        {tasks.length === 0 ? (
          <div className="empty">{translate("taskNoTasks")}</div>
        ) : (
          <>
            <div className="task-list-head" style={{ gridTemplateColumns }}>
              <span className="task-col task-select-col">
                <label className="task-select-label">
                  <input
                    type="checkbox"
                    checked={isAllPageSelected}
                    onChange={onSelectAllPage}
                  />
                  {translate("taskListColumnSelect")}
                </label>
              </span>
              {columns.map((column) => (
                <span
                  key={column.key}
                  className={`task-col ${headerSortedClass(column.key)} ${column.align === "right" ? "task-col-right" : ""}`}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "move"
                    onColumnDragStart(column.key)
                  }}
                  onDragOver={(event) => {
                    event.preventDefault()
                    onColumnDragOver(column.key)
                  }}
                  onDrop={() => onDropColumn(column.key)}
                  onDragEnd={onColumnDragEnd}
                  onClick={() => onSort(column.key)}
                  role="button"
                  aria-label={translate(column.labelKey)}
                >
                  <span>{translate(column.labelKey)}</span>
                  <span className="task-sort-icon">
                    {sortBy === column.key ? (sortDirection === "asc" ? "\u25B2" : "\u25BC") : ""}
                  </span>
                </span>
              ))}
              <span className="task-col task-action-col">{translate("taskListColumnActions")}</span>
            </div>
            <div className="task-list-body" style={{ gridTemplateColumns }}>
              {tasks.map((item) => (
                <div
                  key={item.task_id}
                  className={`task-row ${item.task_id === selectedId ? "active" : ""}`}
                  onClick={() => onSelect(item.task_id)}
                  role="button"
                  style={{ gridTemplateColumns }}
                >
                  <label
                    className="task-select-label"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={selectedTaskIds.has(item.task_id)}
                      onChange={() => onSelectOne(item.task_id)}
                    />
                  </label>
                  {columns.map((column) => (
                    <div className={`task-col task-body-col`} key={`${item.task_id}-${column.key}`}>
                      {renderColumnCell(item, column)}
                    </div>
                  ))}
                  <span>
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
                  </span>
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
          <span>{translate("detailStatus")}</span>
          <strong className={`status ${getTaskStatusClass(task.status)}`}>
            {getTaskStatusText(translate, task.status)}
          </strong>
        </div>
      </section>
      <section className="detail-section">
        <p className="detail-section-title">{translate("taskDetailRuntime")}</p>
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

function TaskDetailPage({
  task,
  taskResult,
  taskTab,
  setTaskTab,
  events,
  hasMoreEvents,
  isLoadingEvents,
  onLoadMore,
  onBack,
  translate,
}) {
  return (
    <section className="panel">
      <div className="task-page-titlebar">
        <button type="button" className="btn btn-compact" onClick={onBack}>
          {translate("taskListBack")}
        </button>
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
          <EventTimeline
            task={task}
            events={events}
            hasMore={hasMoreEvents}
            loadingMore={isLoadingEvents}
            onLoadMore={onLoadMore}
            translate={translate}
          />
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

function CreateTaskForm({ onCreate, focusSignal, translate }) {
  const [query, setQuery] = useState("")
  const [provider, setProvider] = useState("openai-compatible")
  const [maxSteps, setMaxSteps] = useState("8")
  const [busy, setBusy] = useState(false)
  const textAreaRef = useRef(null)

  useEffect(() => {
    if (!textAreaRef.current) return
    textAreaRef.current.focus()
  }, [focusSignal])

  const submit = async (event) => {
    event.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    try {
      await onCreate({
        query,
        provider,
        max_steps: Number(maxSteps || 8),
        stream: false,
      })
      setQuery("")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form-grid" onSubmit={submit}>
      <label>
        <span>{translate("taskFormPrompt")}</span>
        <textarea
          ref={textAreaRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={translate("taskFormPlaceholder")}
        />
      </label>
      <div className="form-row">
        <label>
          <span>{translate("taskFormProvider")}</span>
          <select value={provider} onChange={(event) => setProvider(event.target.value)}>
            {PROVIDER_OPTIONS.map((item) => (
              <option value={item} key={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{translate("taskFormMaxSteps")}</span>
          <input
            type="number"
            min="1"
            max="40"
            value={maxSteps}
            onChange={(event) => setMaxSteps(event.target.value)}
            aria-label={translate("taskFormMaxSteps")}
          />
        </label>
      </div>
      <button className="btn" type="submit" disabled={busy || !query.trim()}>
        {busy ? translate("taskFormCreating") : translate("taskFormCreate")}
      </button>
    </form>
  )
}

function CreateTaskDialog({ open, onClose, onCreate, focusSignal, translate }) {
  if (!open) return null

  return (
    <div
      className="task-create-overlay"
      role="dialog"
      aria-modal="true"
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          onClose()
        }
      }}
      onClick={onClose}
    >
      <section className="panel task-create-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="panel-titlebar">
          <h2>{translate("taskFormTitle")}</h2>
          <button type="button" className="btn btn-compact" onClick={onClose}>
            {translate("dialogClose")}
          </button>
        </div>
        <div className="panel-body">
          <CreateTaskForm onCreate={onCreate} focusSignal={focusSignal} translate={translate} />
        </div>
      </section>
    </div>
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
            <input
              type="number"
              min="0"
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
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

function AdminSidebar({
  activeMenu,
  onChangeMenu,
  systemTime,
  translate,
}) {
  return (
    <aside className="admin-sidebar">
      <div className="sidebar-brand">
        <h1>{translate("appTitle")}</h1>
        <p>{translate("appSubtitle")}</p>
      </div>
      <div className="sidebar-groups" aria-label={translate("menuAriaLabel")}>
        {MENU_GROUPS.map((group) => (
          <section className="sidebar-group" key={group.key}>
            <p className="sidebar-group-title">{translate(group.labelKey)}</p>
            <nav className="sidebar-menu">
              {group.items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`sidebar-menu-item ${activeMenu === item.key ? "active" : ""}`}
                  onClick={() => onChangeMenu(item.key)}
                >
                  {translate(item.labelKey)}
                </button>
              ))}
            </nav>
          </section>
        ))}
      </div>
      <div className="sidebar-system">
        <p className="sidebar-system-title">{translate("sidebarSystemTitle")}</p>
        <p>
          {translate("sidebarSystemTime")}:
          <strong>{systemTime ? formatTime(systemTime) : "-"}</strong>
        </p>
        <p className="sidebar-system-hint">{translate("apiHint")}</p>
      </div>
    </aside>
  )
}

function HeaderStats({
  health,
  activeMenu,
  tasks,
  locale,
  localeOptions,
  setLocale,
  translate,
}) {
  return (
    <header className="admin-header">
      <div className="header-left">
        <p className="breadcrumb">
          {activeMenu === "tasks" ? translate("menuTasks") : translate("menuBackup")}
        </p>
        <h2>{activeMenu === "tasks" ? translate("taskSectionTitle") : translate("backupSectionTitle")}</h2>
      </div>
      <div className="header-right">
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
      </div>
    </header>
  )
}

function StatsBar({ stats, translate }) {
  return (
    <section className="stats-grid">
      <article className="stat-card">
        <p>{translate("metricTotal")}</p>
        <strong>{stats.total}</strong>
      </article>
      <article className="stat-card">
        <p>{translate("metricRunning")}</p>
        <strong>{stats.running}</strong>
      </article>
      <article className="stat-card">
        <p>{translate("metricSuccess")}</p>
        <strong>{stats.success}</strong>
      </article>
      <article className="stat-card">
        <p>{translate("metricFailed")}</p>
        <strong>{stats.failed}</strong>
      </article>
    </section>
  )
}

export default function App() {
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState("")
  const [selectedTask, setSelectedTask] = useState(null)
  const [events, setEvents] = useState([])
  const [hasMoreEvents, setHasMoreEvents] = useState(false)
  const [isLoadingEvents, setIsLoadingEvents] = useState(false)
  const [error, setError] = useState("")
  const [retentionConfig, setRetentionConfig] = useState(null)
  const [health, setHealth] = useState("unknown")
  const [activeMenu, setActiveMenu] = useState("tasks")
  const [taskTab, setTaskTab] = useState("detail")
  const [taskPageMode, setTaskPageMode] = useState("list")
  const [locale, setLocale] = useState(getDefaultLocale())
  const [selectedTaskIds, setSelectedTaskIds] = useState(new Set())
  const [taskPage, setTaskPage] = useState(1)
  const [systemTime, setSystemTime] = useState(() => new Date())
  const [taskSearchQuery, setTaskSearchQuery] = useState("")
  const [isTaskCreateOpen, setIsTaskCreateOpen] = useState(false)
  const [createFormFocusSignal, setCreateFormFocusSignal] = useState(0)
  const [taskColumns, setTaskColumns] = useState(TASK_COLUMNS)
  const [taskSortBy, setTaskSortBy] = useState(TASK_SORT_DEFAULT)
  const [taskSortDirection, setTaskSortDirection] = useState(TASK_SORT_DEFAULT_DIR)
  const [draggingTaskColumn, setDraggingTaskColumn] = useState("")
  const [taskColumnDragTarget, setTaskColumnDragTarget] = useState("")

  const translate = useCallback((key) => t(locale, key), [locale])
  const localeOptions = useMemo(() => getLocaleOptions(locale), [locale])

  const taskStats = useMemo(() => {
    let running = 0
    let success = 0
    let failed = 0

    tasks.forEach((task) => {
      const statusClass = getTaskStatusClass(task.status)
      if (statusClass === "running") {
        running += 1
      } else if (statusClass === "success") {
        success += 1
      } else if (statusClass === "failed") {
        failed += 1
      }
    })

    return {
      total: tasks.length,
      running,
      success,
      failed,
    }
  }, [tasks])

  const taskResult = useMemo(() => getTaskResult(selectedTask, events), [selectedTask, events])
  const taskSearchValue = taskSearchQuery.trim().toLowerCase()

  const filteredTasks = useMemo(() => {
    if (!taskSearchValue) return tasks
    return tasks.filter((task) => {
      const matchText = [
        task.task_id,
        task.provider,
        task.status,
        task.query,
      ].join(" ").toLowerCase()
      return matchText.includes(taskSearchValue)
    })
  }, [tasks, taskSearchValue])

  const sortedTasks = useMemo(() => {
    const rows = [...filteredTasks]
    const directionMultiplier = taskSortDirection === "asc" ? 1 : -1

    rows.sort((left, right) => {
      const leftValue = getTaskListValue(left, taskSortBy)
      const rightValue = getTaskListValue(right, taskSortBy)
      return compareTaskValues(leftValue, rightValue) * directionMultiplier
    })

    return rows
  }, [filteredTasks, taskSortBy, taskSortDirection])

  const totalTaskPages = useMemo(
    () => Math.max(1, Math.ceil(sortedTasks.length / TASK_PAGE_SIZE)),
    [sortedTasks.length]
  )
  const currentTaskPage = Math.min(Math.max(taskPage, 1), totalTaskPages)

  const pagedTasks = useMemo(
    () =>
      sortedTasks.slice(
        (currentTaskPage - 1) * TASK_PAGE_SIZE,
        currentTaskPage * TASK_PAGE_SIZE
      ),
    [sortedTasks, currentTaskPage]
  )

  const isAllPageSelected = useMemo(
    () => pagedTasks.length > 0 && pagedTasks.every((item) => selectedTaskIds.has(item.task_id)),
    [pagedTasks, selectedTaskIds]
  )

  const nextOffsetRef = useRef(0)
  const isRunningRef = useRef(false)

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
    setTaskPage(currentTaskPage)
  }, [currentTaskPage, totalTaskPages])

  useEffect(() => {
    setTaskPage(1)
  }, [taskSearchValue, taskSortBy, taskSortDirection, taskColumns, totalTaskPages])

  useEffect(() => {
    if (activeMenu !== "tasks") return
    const taskIdSet = new Set(tasks.map((task) => task.task_id))
    setSelectedTaskIds((prev) => {
      const next = new Set()
      prev.forEach((id) => {
        if (taskIdSet.has(id)) {
          next.add(id)
        }
      })
      if (next.size === prev.size) {
        let unchanged = true
        prev.forEach((id) => {
          if (!next.has(id)) {
            unchanged = false
          }
        })
        if (unchanged) {
          return prev
        }
      }
      return next
    })
  }, [activeMenu, tasks])

  const refreshTasks = useCallback(async () => {
    const list = await fetchTasks()
    setTasks(list)

    if (list.length === 0) {
      setSelectedId("")
      setTaskPageMode("list")
      return
    }

    if (!selectedId || !list.some((item) => item.task_id === selectedId)) {
      setSelectedId(list[0].task_id)
    }
  }, [selectedId])

  const refreshTask = useCallback(async (taskId) => {
    const target = taskId || selectedId
    if (!target) return
    const task = await fetchTask(target)
    setSelectedTask(task)
    return task
  }, [selectedId])

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
    const target = taskId || selectedId
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
  }, [selectedId, selectedTask?.status, translate])

  const selectTask = useCallback(
    (taskId) => {
      setSelectedId(taskId)
      setSelectedTask(null)
      setEvents([])
      nextOffsetRef.current = 0
      setHasMoreEvents(false)
      setError("")
      setTaskTab("detail")
      setTaskPageMode("detail")
      refreshTask(taskId)
      loadEvents(taskId, true, null, true)
    },
    [loadEvents, refreshTask]
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
        pagedTasks.forEach((task) => {
          next.delete(task.task_id)
        })
      } else {
        pagedTasks.forEach((task) => {
          next.add(task.task_id)
        })
      }
      return next
    })
  }, [isAllPageSelected, pagedTasks])

  const changeTaskSort = useCallback((columnKey) => {
    setTaskSortBy((prevBy) => {
      if (prevBy === columnKey) {
        setTaskSortDirection((prevDirection) => (prevDirection === "asc" ? "desc" : "asc"))
        return prevBy
      }
      setTaskSortDirection(TASK_SORT_DEFAULT_DIR)
      return columnKey
    })
  }, [])

  const startTaskColumnDrag = useCallback((columnKey) => {
    setDraggingTaskColumn(columnKey)
  }, [])

  const updateTaskColumnDragTarget = useCallback((columnKey) => {
    if (draggingTaskColumn !== columnKey) {
      setTaskColumnDragTarget(columnKey)
    }
  }, [draggingTaskColumn])

  const endTaskColumnDrag = useCallback(() => {
    setDraggingTaskColumn("")
    setTaskColumnDragTarget("")
  }, [])

  const dropTaskColumn = useCallback(
    (columnKey) => {
      if (!draggingTaskColumn || draggingTaskColumn === columnKey) {
        endTaskColumnDrag()
        return
      }

      setTaskColumns((prev) => {
        const next = [...prev]
        const sourceIndex = next.findIndex((item) => item.key === draggingTaskColumn)
        const targetIndex = next.findIndex((item) => item.key === columnKey)
        if (sourceIndex < 0 || targetIndex < 0) {
          return prev
        }
        const [movedItem] = next.splice(sourceIndex, 1)
        next.splice(targetIndex, 0, movedItem)
        return next
      })
      endTaskColumnDrag()
    },
    [draggingTaskColumn, endTaskColumnDrag]
  )

  const openCreateDialog = useCallback(() => {
    setCreateFormFocusSignal((count) => count + 1)
    setIsTaskCreateOpen(true)
  }, [])

  const closeCreateDialog = useCallback(() => {
    setIsTaskCreateOpen(false)
  }, [])

  const createNewTask = useCallback(async (payload) => {
    try {
      setError("")
      const result = await createTask(payload)
      if (result?.task_id) {
        setSelectedId(result.task_id)
        setEvents([])
        nextOffsetRef.current = 0
        setHasMoreEvents(false)
        setTaskTab("detail")
        setTaskPageMode("detail")
        closeCreateDialog()
        const task = await refreshTask(result.task_id)
        await loadEvents(result.task_id, true, task?.status, true)
      }
      await refreshTasks()
    } catch (createError) {
      setError(createError?.message || translate("errorUnknown"))
    }
  }, [closeCreateDialog, loadEvents, refreshTask, refreshTasks, translate])

  const deleteTaskItem = useCallback(async (taskId) => {
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

      const taskDeleted = selectedId === taskId
      const nextTasks = tasks.filter((item) => item.task_id !== taskId)

      if (taskDeleted) {
        setSelectedTask(null)
        setEvents([])
        nextOffsetRef.current = 0
        setHasMoreEvents(false)
        setTaskTab("detail")

        if (nextTasks.length > 0) {
          const nextId = nextTasks[0].task_id
          setTaskPageMode("detail")
          setSelectedId(nextId)
          const task = await refreshTask(nextId)
          await loadEvents(nextId, true, task?.status, true)
        } else {
          setSelectedId("")
          setTaskPageMode("list")
        }
      }

      await refreshTasks()
    } catch (deleteError) {
      setError(deleteError?.message || translate("errorUnknown"))
    }
  }, [refreshTask, refreshTasks, selectedId, tasks, translate, loadEvents, selectedTaskIds])

  const deleteTaskSelection = useCallback(async () => {
    const ids = Array.from(selectedTaskIds)
    if (ids.length === 0) return

    if (!window.confirm(`${translate("taskListBatchDeleteConfirm")} (${ids.length})`)) return

    try {
      setError("")
      const idSet = new Set(ids)
      await Promise.all(ids.map((taskId) => deleteTask(taskId)))
      setSelectedTaskIds(new Set())

      if (selectedId && idSet.has(selectedId)) {
        const remaining = tasks.filter((task) => !idSet.has(task.task_id))
        setSelectedTask(null)
        setEvents([])
        nextOffsetRef.current = 0
        setHasMoreEvents(false)

        if (remaining.length > 0) {
          const nextId = remaining[0].task_id
          setTaskPageMode("detail")
          setSelectedId(nextId)
          const task = await fetchTask(nextId)
          await loadEvents(nextId, true, task?.status, true)
        } else {
          setSelectedId("")
          setTaskPageMode("list")
        }
      }

      await refreshTasks()
    } catch (deleteError) {
      setError(deleteError?.message || translate("errorUnknown"))
    }
  }, [loadEvents, refreshTasks, selectedId, selectedTaskIds, tasks, translate])

  const changeTaskPage = useCallback((nextPage) => {
    if (nextPage < 1 || nextPage > totalTaskPages) return
    setTaskPage(nextPage)
  }, [totalTaskPages])

  const updateRetention = useCallback(async (daysValue) => {
    try {
      const config = await updateRetentionConfig(daysValue)
      setRetentionConfig(config)
    } catch (retentionError) {
      setError(retentionError?.message || translate("errorUnknown"))
    }
  }, [translate])

  useEffect(() => {
    if (activeMenu === "tasks") {
      refreshTasks().catch((err) => setError(err?.message || translate("errorLoadFailed")))
    }
    refreshRetention().catch((err) => setError(err?.message || translate("errorLoadFailed")))
    refreshHealth().catch(() => {})

    const timer = setInterval(() => {
      refreshRetention().catch((err) => setError(err?.message || translate("errorLoadFailed")))
      refreshHealth().catch(() => {})
      if (activeMenu === "tasks") {
        refreshTasks().catch((err) => setError(err?.message || translate("errorLoadFailed")))
      }
    }, 5000)

    return () => clearInterval(timer)
  }, [activeMenu, refreshRetention, refreshHealth, refreshTasks, translate])

  useEffect(() => {
    if (taskPageMode !== "detail" || !selectedId || activeMenu !== "tasks") return

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

  useEffect(() => {
    if (taskPageMode !== "detail" || !selectedId || activeMenu !== "tasks") return

    const init = async () => {
      const task = await refreshTask(selectedId)
      await loadEvents(selectedId, true, task?.status, true)
    }
    init().catch((err) => setError(err?.message || translate("errorLoadFailed")))
  }, [activeMenu, selectedId, loadEvents, refreshTask, taskPageMode, translate])

  return (
    <div className="admin-root">
      <AdminSidebar
        activeMenu={activeMenu}
        onChangeMenu={(menu) => {
          setActiveMenu(menu)
          setTaskTab("detail")
          setTaskPageMode("list")
          if (menu !== "tasks") {
            setIsTaskCreateOpen(false)
          }
        }}
        systemTime={systemTime}
        translate={translate}
      />
      <section className="admin-workspace">
        <HeaderStats
          health={health}
          activeMenu={activeMenu}
          tasks={tasks}
          locale={locale}
          localeOptions={localeOptions}
          setLocale={setLocale}
          translate={translate}
        />
        {error && <div className="global-error">{error}</div>}
        <main className="admin-content">
          {activeMenu === "tasks" ? (
            <>
              {taskPageMode === "list" ? (
                <>
                  <StatsBar stats={taskStats} translate={translate} />
                  <TaskList
                    columns={taskColumns}
                    sortBy={taskSortBy}
                    sortDirection={taskSortDirection}
                    draggingColumn={draggingTaskColumn}
                    tasks={pagedTasks}
                    selectedId={selectedId}
                    selectedTaskIds={selectedTaskIds}
                    isAllPageSelected={isAllPageSelected}
                    onSelect={selectTask}
                    onSelectOne={selectTaskForBatch}
                    onSelectAllPage={selectAllPageForBatch}
                    onSort={changeTaskSort}
                    onAddTask={openCreateDialog}
                    onColumnDragStart={startTaskColumnDrag}
                    onColumnDragOver={updateTaskColumnDragTarget}
                    onColumnDrop={dropTaskColumn}
                    onColumnDragEnd={endTaskColumnDrag}
                    dragTargetColumn={taskColumnDragTarget}
                    onRefresh={refreshTasks}
                    taskSearchQuery={taskSearchQuery}
                    onTaskSearch={setTaskSearchQuery}
                    onDelete={deleteTaskItem}
                    onBatchDelete={deleteTaskSelection}
                    page={currentTaskPage}
                    totalPages={totalTaskPages}
                    onPageChange={changeTaskPage}
                    translate={translate}
                  />
                </>
              ) : (
                <TaskDetailPage
                  task={selectedTask}
                  taskResult={taskResult}
                  taskTab={taskTab}
                  setTaskTab={setTaskTab}
                  events={events}
                  hasMoreEvents={hasMoreEvents}
                  isLoadingEvents={isLoadingEvents}
                  onLoadMore={() => loadEvents(selectedId, false, null, true)}
                  onBack={() => setTaskPageMode("list")}
                  translate={translate}
                />
              )}
            </>
          ) : (
            <RetentionManager
              retentionConfig={retentionConfig}
              onSave={updateRetention}
              onRefresh={() =>
                refreshRetention().catch((error) => setError(error?.message || translate("errorLoadFailed")))
              }
              translate={translate}
            />
          )}
        </main>
        <CreateTaskDialog
          open={isTaskCreateOpen}
          onClose={closeCreateDialog}
          onCreate={createNewTask}
          focusSignal={createFormFocusSignal}
          translate={translate}
        />
      </section>
    </div>
  )
}



