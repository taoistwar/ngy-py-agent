import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import {
  createAgent,
  createDenyRule,
  createMcpServer,
  createModel,
  createProvider,
  createSession,
  createTask,
  createWorkspace,
  deleteAgent,
  deleteDenyRule,
  deleteMcpServer,
  deleteModel,
  deleteProvider,
  deleteSession,
  deleteSkill,
  deleteTask,
  deleteWorkspace,
  fetchAgentMeta,
  fetchAgents,
  fetchContextUsage,
  fetchDenyList,
  fetchSkills,
  fetchHealth,
  fetchMcpServers,
  fetchModels,
  fetchProviders,
  fetchRetentionConfig,
  fetchMaxStepsConfig,
  updateMaxStepsConfig,
  fetchAgentsMdConfig,
  updateAgentsMdConfig,
  fetchPermissionModeConfig,
  updatePermissionModeConfig,
  fetchPermissionRules,
  deletePermissionRule,
  fetchSessions,
  fetchTask,
  fetchTaskEvents,
  fetchTasks,
  fetchTools,
  fetchWorkspaces,
  importSkill,
  renameSession,
  revertAndDeleteTask,
  stopTask,
  updateAgent,
  updateMcpServer,
  updateModel,
  updateProvider,
  updateRetentionConfig,
  updateSkillsRoot,
  updateWorkspace,
} from "./api"
import {
  getDefaultLocale,
  getLocaleOptions,
  getTaskStatusClass,
  getTaskStatusText,
  isTaskRunningStatus,
  LOCALE_KEY,
  t,
} from "./i18n"
import ContextMeter from "./components/ContextMeter"
import EventTimeline from "./components/EventTimeline"
import PermissionPrompt from "./components/PermissionPrompt"
import QuestionPrompt from "./components/QuestionPrompt"
import RevertChangesDialog from "./components/RevertChangesDialog"
import SessionTabs from "./components/SessionTabs"
import TaskChangesDialog from "./components/TaskChangesDialog"
import TaskPromptPanel from "./components/TaskPromptPanel"
import TaskResultPanel from "./components/TaskResultPanel"
import TaskRowActions from "./components/TaskRowActions"
import TaskToolbarActions from "./components/TaskToolbarActions"
import { SearchIcon, SkillIcon } from "./components/icons"
import AgentManager from "./components/admin/AgentManager"
import DenyListManager from "./components/admin/DenyListManager"
import McpServerManager from "./components/admin/McpServerManager"
import ModelManager from "./components/admin/ModelManager"
import PermissionRulesManager from "./components/admin/PermissionRulesManager"
import ProviderManager from "./components/admin/ProviderManager"
import {
  AgentsMdManager,
  MaxStepsManager,
  PermissionModeManager,
  RetentionManager,
} from "./components/admin/SettingsPanels"
import SkillManager from "./components/admin/SkillManager"
import AppSidebar from "./components/shell/AppSidebar"
import AppTopbar from "./components/shell/AppTopbar"
import { DEFAULT_MENU } from "./components/shell/navigation"
import OverviewPage from "./pages/OverviewPage"
import ToolManager from "./components/admin/ToolManager"
import WorkspaceManager from "./components/admin/WorkspaceManager"
import AgentPicker from "./components/AgentPicker"
import { AgentIcon, agentIconName } from "./components/agentIcons"
import { PROVIDER_OPTIONS, agentDisplayName } from "./components/admin/shared"
import {
  loadRememberedModel,
  resolveModelId,
  saveRememberedModel,
} from "./utils/composerModelMemory"
import { formatTime } from "./utils/format"
import { buildTaskEditDraft, replaceTaskWithEdit } from "./utils/taskEditFlow"
import { forkTaskSession } from "./utils/taskForkFlow"

const EVENT_PAGE_SIZE = 30
const TASK_PAGE_SIZE = 12

function resolveAgent(agentId, agents) {
  return (agents || []).find((item) => item.agent_id === agentId)
}

function resolveAgentName(agentId, agents, translate) {
  const agent = resolveAgent(agentId, agents)
  if (agent) return agentDisplayName(agent, translate)
  return translate(modeLabelKey(agentId))
}

const TASK_COLUMN_MIN_LEFT = 160
const TASK_COLUMN_MIN_MID = 220
const TASK_COLUMN_MIN_DETAIL = 280
const TASK_COLUMN_RESIZER_WIDTH = 8
const TASK_COLUMN_COLLAPSED_WIDTH = 44
const TASK_COLUMN_WIDTHS_KEY = "web-admin.taskColumnWidths"
const TASK_COLUMN_COLLAPSED_KEY = "web-admin.leftColumnCollapsed"
const TASK_COLUMN_DEFAULT_WIDTHS = { left: 260, mid: 360 }
// The composer split: the handle row plus the smallest task list it may leave.
const TASK_COMPOSER_HEIGHT_KEY = "web-admin.taskComposerHeight"
const TASK_COMPOSER_DEFAULT_HEIGHT = 176
const TASK_COMPOSER_MIN_HEIGHT = 168
const TASK_COMPOSER_RESIZER_HEIGHT = 10
const TASK_LIST_MIN_HEIGHT = 140
// One draft per session, so a refresh restores what was being typed and two
// sessions never show each other's text.
const COMPOSER_DRAFT_KEY_PREFIX = "web-admin.composerDraft."
// The context meter only moves when a turn completes, so it is read on a slow tick
// instead of alongside the 1s task poll (which also refreshes it on its own).
const CONTEXT_USAGE_POLL_MS = 5000

function composerDraftKey(sessionId) {
  return `${COMPOSER_DRAFT_KEY_PREFIX}${sessionId}`
}

function loadComposerDraft(sessionId) {
  if (typeof window === "undefined" || !sessionId) return ""
  try {
    return window.localStorage.getItem(composerDraftKey(sessionId)) || ""
  } catch {
    return ""
  }
}

function saveComposerDraft(sessionId, text) {
  if (typeof window === "undefined" || !sessionId) return
  try {
    if (text) {
      window.localStorage.setItem(composerDraftKey(sessionId), text)
    } else {
      // An empty composer is not a draft: drop the key instead of storing "".
      window.localStorage.removeItem(composerDraftKey(sessionId))
    }
  } catch {
    // ignore persistence errors
  }
}

function loadLeftColumnCollapsed() {
  if (typeof window === "undefined") return false
  try {
    return window.localStorage.getItem(TASK_COLUMN_COLLAPSED_KEY) === "1"
  } catch {
    return false
  }
}

function loadTaskColumnWidths() {
  const fallback = { ...TASK_COLUMN_DEFAULT_WIDTHS }
  if (typeof window === "undefined") return fallback
  try {
    const raw = window.localStorage.getItem(TASK_COLUMN_WIDTHS_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    const left = Number(parsed?.left)
    const mid = Number(parsed?.mid)
    return {
      left: Number.isFinite(left) ? Math.max(TASK_COLUMN_MIN_LEFT, left) : fallback.left,
      mid: Number.isFinite(mid) ? Math.max(TASK_COLUMN_MIN_MID, mid) : fallback.mid,
    }
  } catch {
    return fallback
  }
}

function loadComposerHeight() {
  if (typeof window === "undefined") return TASK_COMPOSER_DEFAULT_HEIGHT
  try {
    const stored = Number(window.localStorage.getItem(TASK_COMPOSER_HEIGHT_KEY))
    if (!Number.isFinite(stored) || stored <= 0) return TASK_COMPOSER_DEFAULT_HEIGHT
    return Math.max(TASK_COMPOSER_MIN_HEIGHT, Math.round(stored))
  } catch {
    return TASK_COMPOSER_DEFAULT_HEIGHT
  }
}

// The composer may not eat the task list, so its ceiling follows the space the
// middle column actually has instead of a fixed pixel value.
function maxComposerHeight(containerHeight) {
  const available = containerHeight - TASK_COMPOSER_RESIZER_HEIGHT - TASK_LIST_MIN_HEIGHT
  return Math.max(TASK_COMPOSER_MIN_HEIGHT, Math.round(available))
}

const MODE_LABEL_KEYS = {
  build: "modeBuild",
  ask: "modeAsk",
  plan: "modePlan",
}

const modeLabelKey = (mode) => MODE_LABEL_KEYS[mode] || "modeBuild"

// The task list is served oldest first, so the task to resume is the last one
// in the list - "the first entry" would be the oldest task of the session.
function latestTaskId(list) {
  return list && list.length > 0 ? list[list.length - 1].task_id : ""
}

function shortenText(value, maxLength) {
  if (!value) return ""
  const text = String(value)
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 1)}...`
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

function TaskList({
  tasks,
  selectedId,
  onSelect,
  onEdit,
  onRerun,
  onFork,
  onRevert,
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
  agents,
  translate,
}) {
  const selectedCount = selectedTaskIds.size
  const rowsRef = useRef(null)
  const taskCount = tasks.length

  // Tasks are listed oldest first, so a task created now lands at the bottom:
  // follow the selection instead of leaving the scroll position on old rows.
  useEffect(() => {
    const container = rowsRef.current
    if (!container || !selectedId) return
    const activeRow = container.querySelector(".session-task-row.active")
    if (!activeRow) return
    const containerRect = container.getBoundingClientRect()
    const rowRect = activeRow.getBoundingClientRect()
    if (rowRect.top < containerRect.top) {
      container.scrollTop -= containerRect.top - rowRect.top
    } else if (rowRect.bottom > containerRect.bottom) {
      container.scrollTop += rowRect.bottom - containerRect.bottom
    }
    // A poll refresh keeps the same ids, so only a different selection, a
    // longer/shorter list or another page may move the scroll - not every tick.
  }, [selectedId, taskCount, page])

  return (
    <section className="panel session-task-panel">
      <div className="panel-titlebar">
        <h2>{translate("taskListTitle")}</h2>
        <TaskToolbarActions
          selectedCount={selectedCount}
          onRefresh={onRefresh}
          onBatchDelete={onBatchDelete}
          translate={translate}
        />
      </div>
      <div className="panel-body session-task-body">
        <div className="task-search-bar">
          <span className="task-search-field">
            <SearchIcon />
            <input
              type="text"
              className="task-search-input"
              value={taskSearchQuery}
              placeholder={translate("taskSearchPlaceholder")}
              onChange={(event) => onTaskSearch(event.target.value)}
            />
          </span>
        </div>
        {tasks.length === 0 ? (
          <div className="empty">{translate("taskNoTasks")}</div>
        ) : (
          <>
            <div className="session-task-rows" ref={rowsRef}>
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
                      {shortenText(item.name || item.query, 90)}
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
                        <AgentIcon name={agentIconName(resolveAgent(item.mode, agents))} />
                        {resolveAgentName(item.mode, agents, translate)}
                      </span>
                      <span className="hint">
                        {translate("taskEventCountPrefix")}: {item.event_count}
                      </span>
                      {/* Kept on the meta line so the name above owns the full width. */}
                      <TaskRowActions
                        prompt={item.query}
                        running={isTaskRunningStatus(item.status)}
                        onEdit={() => onEdit(item)}
                        onRerun={() => onRerun(item)}
                        onFork={() => onFork(item)}
                        onRevert={() => onRevert(item.task_id)}
                        onDelete={() => onDelete(item.task_id)}
                        translate={translate}
                      />
                    </div>
                  </div>
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
            <div className="session-task-head">
              <label className="task-select-label">
                <input type="checkbox" checked={isAllPageSelected} onChange={onSelectAllPage} />
                {translate("taskListColumnSelect")}
              </label>
              <span className="hint">
                {translate("taskListSelected")}: {selectedCount}
              </span>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function SkillPicker({ anchor, innerRef, skills, onPick, onImport, translate }) {
  const [search, setSearch] = useState("")

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return skills
    return skills.filter((item) =>
      `${item.display_name || ""} ${item.name || ""} ${item.description || ""}`
        .toLowerCase()
        .includes(keyword)
    )
  }, [skills, search])

  if (typeof document === "undefined") return null

  // Render in a portal with fixed positioning so the popup is not clipped by
  // (or limited to) the task composer panel.
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const width = Math.min(340, Math.max(240, viewportWidth - 16))
  const left = anchor ? Math.min(Math.max(8, anchor.left), Math.max(8, viewportWidth - width - 8)) : 8
  const bottom = anchor ? Math.max(8, viewportHeight - anchor.top + 6) : 8
  const maxHeight = anchor ? Math.max(200, anchor.top - 16) : 340

  return createPortal(
    <div
      ref={innerRef}
      className="skill-picker"
      style={{
        left: `${left}px`,
        bottom: `${bottom}px`,
        width: `${width}px`,
        maxHeight: `${maxHeight}px`,
      }}
      onClick={(event) => event.stopPropagation()}
    >
      <input
        className="skill-picker-search"
        autoFocus
        value={search}
        placeholder={translate("skillSearchPlaceholder")}
        onChange={(event) => setSearch(event.target.value)}
      />
      <div className="skill-picker-list">
        {filtered.length === 0 ? (
          <div className="empty skill-picker-empty">{translate("skillPickerEmpty")}</div>
        ) : (
          filtered.map((skill) => (
            <button
              type="button"
              className="skill-picker-item"
              key={skill.name}
              onClick={() => onPick(skill)}
            >
              <span className="skill-picker-badge">
                {(skill.display_name || skill.name || "?").slice(0, 1).toUpperCase()}
              </span>
              <span className="skill-picker-text">
                <span className="skill-picker-name">{skill.display_name || skill.name}</span>
                <span className="skill-picker-desc">{skill.description || skill.name}</span>
              </span>
            </button>
          ))
        )}
      </div>
      <button type="button" className="skill-picker-import" onClick={onImport}>
        {translate("skillImport")}
      </button>
    </div>,
    document.body,
  )
}

function TaskComposer({
  models,
  agents,
  skills,
  sessionId,
  workspaceId,
  composerRunning,
  editRequest,
  onCancelEdit,
  onCreate,
  onStop,
  onRequestCreateAgent,
  onImportSkill,
  focusSignal,
  translate,
}) {
  const [query, setQuery] = useState(() => loadComposerDraft(sessionId))
  const [modelId, setModelId] = useState(() => loadRememberedModel(sessionId, workspaceId))
  const [provider, setProvider] = useState("openai-compatible")
  const [agentId, setAgentId] = useState("")
  const [busy, setBusy] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [pickerAnchor, setPickerAnchor] = useState(null)
  const [pickedSkills, setPickedSkills] = useState([])
  const [contextUsage, setContextUsage] = useState(null)
  const skillsButtonRef = useRef(null)
  const pickerRef = useRef(null)
  const textareaRef = useRef(null)
  // The draft an edit filled over, so cancelling can bring it back.
  const preEditDraftRef = useRef("")

  // The remembered model may no longer be in the list, in which case the picker
  // shows the first model instead of an empty selection.
  const effectiveModelId = useMemo(() => resolveModelId(models, modelId), [modelId, models])
  const effectiveAgentId = agentId || (agents && agents.length ? agents[0].agent_id : "")

  // Writing the draft from the edit handlers (not from an effect) keeps every
  // write inside the session on screen: on a session switch the textarea still
  // holds the previous session's text for one render, and an effect keyed on
  // ``query`` would save that text into the new session's key.
  const updateQuery = (value) => {
    setQuery(value)
    saveComposerDraft(sessionId, value)
  }

  useEffect(() => {
    setQuery(loadComposerDraft(sessionId))
  }, [sessionId])

  // Same rule for the model: a session restores its own last pick, and a session
  // that never picked one starts from what the workspace used last. Re-reading on
  // a workspace switch keeps the picker describing the conversation on screen.
  useEffect(() => {
    setModelId(loadRememberedModel(sessionId, workspaceId))
  }, [sessionId, workspaceId])

  const selectModel = (nextModelId) => {
    setModelId(nextModelId)
    saveRememberedModel(sessionId, workspaceId, nextModelId)
  }

  // Editing a task fills the composer with that turn's prompt, agent and model.
  useEffect(() => {
    if (!editRequest) return
    preEditDraftRef.current = query
    updateQuery(editRequest.query)
    setAgentId(editRequest.agentId || "")
    if (editRequest.modelId) selectModel(editRequest.modelId)
    textareaRef.current?.focus()
    // Keyed on the request object alone: every edit click builds a new one, and
    // re-running this on each keystroke would overwrite what the user is typing.
  }, [editRequest])

  const cancelEdit = () => {
    updateQuery(preEditDraftRef.current)
    preEditDraftRef.current = ""
    onCancelEdit()
  }

  // The meter answers "how much room is left before the next task", so it follows the
  // session and the selected model, and is re-read when a task starts or settles.
  useEffect(() => {
    if (!sessionId) {
      setContextUsage(null)
      return undefined
    }
    let cancelled = false
    const load = () => {
      fetchContextUsage(sessionId, effectiveModelId)
        .then((usage) => {
          if (!cancelled) setContextUsage(usage)
        })
        .catch(() => {
          // A reading is a hint: a failed poll must not raise the global error banner.
        })
    }
    load()
    const timer = setInterval(load, CONTEXT_USAGE_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [sessionId, effectiveModelId, composerRunning])

  // The overview "new task" shortcut jumps here; focusing the textarea makes the
  // shortcut complete one visible action instead of only switching pages.
  useEffect(() => {
    if (!focusSignal) return
    textareaRef.current?.focus()
  }, [focusSignal])

  useEffect(() => {
    if (!skillsOpen) return undefined
    const closePicker = (event) => {
      if (pickerRef.current && pickerRef.current.contains(event.target)) return
      if (skillsButtonRef.current && skillsButtonRef.current.contains(event.target)) return
      setSkillsOpen(false)
    }
    const handleViewportChange = () => setSkillsOpen(false)
    window.addEventListener("click", closePicker)
    window.addEventListener("resize", handleViewportChange)
    window.addEventListener("scroll", handleViewportChange, true)
    return () => {
      window.removeEventListener("click", closePicker)
      window.removeEventListener("resize", handleViewportChange)
      window.removeEventListener("scroll", handleViewportChange, true)
    }
  }, [skillsOpen])

  const submit = async (event) => {
    event.preventDefault()
    if (composerRunning || !query.trim()) return
    setBusy(true)
    try {
      // Streamed by default: the reasoning trace many models emit is only sent
      // incrementally, and the event log shows the turn sooner.
      const payload = { query, stream: true, agent_id: effectiveAgentId }
      if (models && models.length) {
        payload.model_id = effectiveModelId
      } else {
        payload.provider = provider
      }
      await onCreate(payload)
      updateQuery("")
      setPickedSkills([])
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

  const applySkill = (skill) => {
    const label = skill.display_name || skill.name
    const line = skill.description ? `使用技能 ${label}：${skill.description}` : `使用技能 ${label}`
    updateQuery(query ? `${query}\n${line}` : line)
    setPickedSkills((prev) => (prev.includes(skill.name) ? prev : [...prev, skill.name]))
    setSkillsOpen(false)
  }

  return (
    <section className={`panel task-composer-panel${editRequest ? " is-editing" : ""}`}>
      <div className="panel-titlebar">
        <div>
          <h2>
            {translate(editRequest ? "taskComposerEditTitle" : "taskComposerTitle")}
          </h2>
          {editRequest ? <span className="hint">{translate("composerEditNotice")}</span> : null}
        </div>
        {editRequest ? (
          <button type="button" className="btn btn-compact" onClick={cancelEdit}>
            {translate("taskComposerEditCancel")}
          </button>
        ) : null}
      </div>
      <div className="panel-body">
        <form className="task-composer" onSubmit={submit}>
          <textarea
            ref={textareaRef}
            className="composer-textarea"
            value={query}
            onChange={(event) => updateQuery(event.target.value)}
            onKeyDown={onQueryKeyDown}
            placeholder={translate("taskFormPlaceholder")}
          />
          <div className="composer-toolbar">
            <AgentPicker
              agents={agents}
              value={effectiveAgentId}
              onSelect={setAgentId}
              onCreate={onRequestCreateAgent}
              translate={translate}
            />

            {models && models.length > 0 ? (
              <select
                className="composer-select"
                value={effectiveModelId}
                onChange={(event) => selectModel(event.target.value)}
                title={translate("taskFormModel")}
              >
                {models.map((item) => (
                  <option value={item.model_id} key={item.model_id}>
                    {item.name}
                  </option>
                ))}
              </select>
            ) : (
              <select
                className="composer-select"
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                title={translate("taskFormProvider")}
              >
                {PROVIDER_OPTIONS.map((item) => (
                  <option value={item} key={item}>
                    {item}
                  </option>
                ))}
              </select>
            )}

            <div className="composer-skills">
              <button
                ref={skillsButtonRef}
                type="button"
                className={`composer-skills-btn ${skillsOpen ? "active" : ""}`}
                title={translate("taskFormSkills")}
                aria-label={translate("taskFormSkills")}
                onClick={(event) => {
                  event.stopPropagation()
                  if (skillsOpen) {
                    setSkillsOpen(false)
                    return
                  }
                  const rect = skillsButtonRef.current?.getBoundingClientRect()
                  setPickerAnchor(rect ? { left: rect.left, top: rect.top } : null)
                  setSkillsOpen(true)
                }}
              >
                <SkillIcon />
                {pickedSkills.length > 0 && (
                  <span className="composer-skill-count">{pickedSkills.length}</span>
                )}
              </button>
              {skillsOpen && (
                <SkillPicker
                  anchor={pickerAnchor}
                  innerRef={pickerRef}
                  skills={skills || []}
                  onPick={applySkill}
                  onImport={onImportSkill}
                  translate={translate}
                />
              )}
            </div>

            {/* The meter sits with the send button, where CodeBuddy puts it: the
                reading describes the next request this button will send. */}
            <div className="composer-actions">
              <ContextMeter usage={contextUsage} translate={translate} />
              {composerRunning ? (
                <button
                  type="button"
                  className="composer-icon-btn stop"
                  onClick={onStop}
                  title={translate("taskStop")}
                  aria-label={translate("taskStop")}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect
                      x="6"
                      y="6"
                      width="12"
                      height="12"
                      rx="2.5"
                      fill="currentColor"
                    />
                  </svg>
                </button>
              ) : (
                <button
                  type="submit"
                  className="composer-icon-btn create"
                  disabled={busy || !query.trim()}
                  title={translate("taskFormCreate")}
                  aria-label={translate("taskFormCreate")}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M2 21l21-9L2 3v7l15 2-15 2z" fill="currentColor" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </section>
  )
}

function TaskDetail({ task, result, agents, translate, onChangesReverted }) {
  const [changesOpen, setChangesOpen] = useState(false)

  if (!task) {
    return <div className="empty">{translate("taskSelectHint")}</div>
  }

  // Tokens are settled once a turn has answered, so the backend's sum is final for a
  // finished task. The clock is not: a running task appends nothing while the model
  // thinks, so its stored ``updated_at`` would freeze mid-run - count from creation
  // instead, which reads correctly on the parent's one-second poll.
  const durationMs = isTaskRunningStatus(task.status)
    ? Math.max(0, Date.now() - new Date(task.created_at).getTime())
    : Number(task.duration_ms) || 0

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
          <span>{translate("detailAgent")}</span>
          <strong className="agent-name">
            <AgentIcon name={agentIconName(resolveAgent(task.mode, agents))} />
            {resolveAgentName(task.mode, agents, translate)}
          </strong>
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
      <TaskPromptPanel query={task.query || ""} translate={translate} />
      <TaskResultPanel
        result={result}
        usage={{
          input_tokens: task.input_tokens,
          output_tokens: task.output_tokens,
          total_tokens: task.total_tokens,
        }}
        durationMs={durationMs}
        translate={translate}
        onOpenChanges={() => setChangesOpen(true)}
      />
      {/* The dialog renders through a portal, so its place in this grid costs no layout. */}
      {changesOpen ? (
        <TaskChangesDialog
          taskId={task.task_id}
          translate={translate}
          onClose={() => setChangesOpen(false)}
          onReverted={onChangesReverted}
        />
      ) : null}
    </div>
  )
}

function TaskDetailPage({ task, taskResult, agents, taskTab, setTaskTab, events, hasMoreEvents, isLoadingEvents, onLoadMore, onChangesReverted, translate, locale }) {
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
          // Remounted per task: the Monaco editors only read ``defaultValue`` once,
          // so without a key the previous task's prompt and result stayed on screen.
          <TaskDetail
            key={task?.task_id || "none"}
            task={task}
            result={taskResult}
            agents={agents}
            translate={translate}
            onChangesReverted={onChangesReverted}
          />
        ) : (
          <EventTimeline
            task={task}
            events={events}
            hasMore={hasMoreEvents}
            loadingMore={isLoadingEvents}
            onLoadMore={onLoadMore}
            translate={translate}
            locale={locale}
          />
        )}
      </div>
    </section>
  )
}

export default function App() {
  const [sessions, setSessions] = useState([])
  const [workspaces, setWorkspaces] = useState([])
  const [agents, setAgents] = useState([])
  const [mcpServers, setMcpServers] = useState([])
  const [tools, setTools] = useState([])
  const [agentMeta, setAgentMeta] = useState(null)
  const [agentCreateSignal, setAgentCreateSignal] = useState(0)
  const [skills, setSkills] = useState([])
  const [skillsRoot, setSkillsRoot] = useState("")
  const [composerTaskId, setComposerTaskId] = useState("")
  // Non-null while the composer is filled from a task row: sending it then replaces
  // that task instead of appending a new turn.
  const [composerEdit, setComposerEdit] = useState(null)
  const [taskColumnWidths, setTaskColumnWidths] = useState(loadTaskColumnWidths)
  const [leftColumnCollapsed, setLeftColumnCollapsed] = useState(loadLeftColumnCollapsed)
  const [resizingColumn, setResizingColumn] = useState("")
  const [composerHeight, setComposerHeight] = useState(loadComposerHeight)
  const [resizingComposer, setResizingComposer] = useState(false)
  const taskWorkspaceRef = useRef(null)
  const taskColumnMainRef = useRef(null)
  const [activeSessionId, setActiveSessionId] = useState("")
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("")
  // Empty means "not scoped": the console lists every workspace. A scope is set
  // only by opening one workspace from the workspace list.
  const [workspaceScopeId, setWorkspaceScopeId] = useState("")
  // The model the composer remembers per workspace is keyed by the workspace the
  // open session belongs to, not by the sidebar highlight: clicking a workspace
  // node only focuses it and must not change the model of the session on screen.
  const activeSessionWorkspaceId = useMemo(
    () =>
      sessions.find((item) => item.session_id === activeSessionId)?.workspace_id ||
      activeWorkspaceId ||
      "",
    [activeSessionId, activeWorkspaceId, sessions]
  )
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState("")
  const [selectedTask, setSelectedTask] = useState(null)
  const [events, setEvents] = useState([])
  const [hasMoreEvents, setHasMoreEvents] = useState(false)
  const [isLoadingEvents, setIsLoadingEvents] = useState(false)
  const [error, setError] = useState("")
  const [retentionConfig, setRetentionConfig] = useState(null)
  const [maxStepsConfig, setMaxStepsConfig] = useState(null)
  const [agentsMdConfig, setAgentsMdConfig] = useState(null)
  const [permissionModeConfig, setPermissionModeConfig] = useState(null)
  const [permissionRules, setPermissionRules] = useState(null)
  const [denyList, setDenyList] = useState(null)
  const [health, setHealth] = useState("unknown")
  const [providers, setProviders] = useState([])
  const [models, setModels] = useState([])
  const [activeMenu, setActiveMenu] = useState(DEFAULT_MENU)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem("web-admin.sidebarCollapsed") === "1"
    } catch {
      return false
    }
  })
  const [taskTab, setTaskTab] = useState("detail")
  const [composerFocusSignal, setComposerFocusSignal] = useState(0)
  const handleNavigate = useCallback((menu) => {
    setActiveMenu(menu)
    setTaskTab("detail")
    // Reaching the console from the sidebar means "all workspaces"; only the
    // workspace list opens one workspace in scope.
    setWorkspaceScopeId("")
  }, [])
  const startNewTask = useCallback(() => {
    setActiveMenu("tasks")
    setTaskTab("detail")
    setWorkspaceScopeId("")
    setComposerEdit(null)
    setComposerFocusSignal((prev) => prev + 1)
  }, [])
  const [locale, setLocale] = useState(getDefaultLocale())
  const [selectedTaskIds, setSelectedTaskIds] = useState(new Set())
  // Empty means "the undo dialog is closed": the dialog owns its own fetching.
  const [revertTaskId, setRevertTaskId] = useState("")
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
  // Which task owns the event request currently in flight. One request per task: a
  // request started for a task the user has already left must neither block the new
  // one nor write its events into the pane.
  const inFlightEventsRef = useRef("")

  // Selection goes through here so the ref already names the new task when the fetch
  // it triggers resolves. The plain state setter only updates the ref on the next
  // render, which is exactly what makes a stale response win the race.
  const applySelection = useCallback((taskId) => {
    selectedIdRef.current = taskId
    setSelectedId(taskId)
  }, [])

  const taskResult = useMemo(() => getTaskResult(selectedTask, events), [selectedTask, events])

  useEffect(() => {
    try {
      window.localStorage.setItem("web-admin.sidebarCollapsed", sidebarCollapsed ? "1" : "0")
    } catch {
      // ignore persistence errors
    }
  }, [sidebarCollapsed])

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

  // A new search or another session opens on the first page. The page count is
  // deliberately not a reset trigger: the clamp above already keeps the pointer
  // in range, and resetting on every new task would fight the follow effect below.
  useEffect(() => {
    setTaskPage(1)
  }, [taskSearchValue, activeSessionId])

  // The selected task has to be on screen, and a task created now sits on the
  // last page, so the list follows the selection there. Only a changed selection
  // or a changed number of rows may move the page: depending on the array itself
  // would drag the user back on every five-second poll while they read older pages.
  useEffect(() => {
    if (!selectedId) return
    const index = filteredTasks.findIndex((item) => item.task_id === selectedId)
    if (index < 0) return
    setTaskPage(Math.floor(index / TASK_PAGE_SIZE) + 1)
  }, [selectedId, filteredTasks.length])

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
      applySelection("")
    } else if (!current || !list.some((item) => item.task_id === current)) {
      applySelection(latestTaskId(list))
    }
  }, [applySelection])

  const refreshTask = useCallback(async (taskId) => {
    const target = taskId || selectedIdRef.current
    if (!target) return null
    const task = await fetchTask(target)
    // A click or a poll may have moved the selection while this was in flight: the
    // pane shows whatever is selected now, not whichever request landed last.
    if (selectedIdRef.current === target) setSelectedTask(task)
    return task
  }, [])

  const refreshProviders = useCallback(async () => {
    const list = await fetchProviders()
    setProviders(list)
    return list
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

  const refreshWorkspaces = useCallback(async () => {
    const list = await fetchWorkspaces()
    setWorkspaces(list)
    return list
  }, [])

  const refreshAgents = useCallback(async () => {
    const list = await fetchAgents()
    setAgents(list)
    return list
  }, [])

  const refreshAgentMeta = useCallback(async () => {
    const data = await fetchAgentMeta()
    setAgentMeta(data)
    return data
  }, [])

  const refreshMcpServers = useCallback(async () => {
    const list = await fetchMcpServers()
    setMcpServers(list)
    return list
  }, [])

  const refreshTools = useCallback(async () => {
    const list = await fetchTools()
    setTools(list)
    return list
  }, [])

  const refreshSkills = useCallback(async () => {
    const data = await fetchSkills()
    setSkills(data.skills ?? [])
    setSkillsRoot(data.skills_root ?? "")
    return data
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
    // Only a second request for the same task is redundant; one that is still in
    // flight for a task the user left must not swallow the new task's first page.
    if (!target || inFlightEventsRef.current === target) return

    inFlightEventsRef.current = target
    setIsLoadingEvents(true)

    try {
      const offset = reset ? 0 : nextOffsetRef.current
      const result = await fetchTaskEvents(target, { offset, limit: EVENT_PAGE_SIZE })
      // Selected another task mid-request: appending this page would mix one task's
      // events into another's log.
      if (selectedIdRef.current !== target) return
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
      if (inFlightEventsRef.current === target) {
        inFlightEventsRef.current = ""
        setIsLoadingEvents(false)
      }
    }
  }, [selectedTask?.status, translate])

  const selectTask = useCallback(
    (taskId) => {
      applySelection(taskId)
      setSelectedTask(null)
      setEvents([])
      nextOffsetRef.current = 0
      setHasMoreEvents(false)
      setError("")
      setTaskTab("detail")
      refreshTask(taskId)
      loadEvents(taskId, true, null, true)
    },
    [applySelection, loadEvents, refreshTask]
  )

  const selectSession = useCallback(
    async (sessionId) => {
      setActiveSessionId(sessionId)
      // An edit belongs to one session's task list; carrying it into another one
      // would let its send delete a task of a different conversation.
      setComposerEdit(null)
      applySelection("")
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
          applySelection(latestTaskId(list))
        } else {
          applySelection("")
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [applySelection, translate]
  )

  const changeTaskPage = useCallback(
    (nextPage) => {
      if (nextPage < 1 || nextPage > totalTaskPages) return
      setTaskPage(nextPage)
    },
    [totalTaskPages]
  )

  const handleSelectSession = useCallback(
    (sessionId) => {
      const target = sessions.find((item) => item.session_id === sessionId)
      setActiveWorkspaceId(target?.workspace_id || "")
      selectSession(sessionId)
    },
    [selectSession, sessions]
  )

  const handleSelectWorkspace = useCallback((workspaceId) => {
    setActiveWorkspaceId(workspaceId || "")
  }, [])

  const clearWorkspaceScope = useCallback(() => setWorkspaceScopeId(""), [])

  // Opening a workspace from the workspace list: scope the session tree to it and
  // land on its most recent session, so the task list and the detail pane already
  // belong to the workspace that was clicked.
  const openWorkspaceConsole = useCallback(
    async (workspaceId) => {
      if (!workspaceId) return
      setActiveMenu("tasks")
      setTaskTab("detail")
      setTaskSearchQuery("")
      setWorkspaceScopeId(workspaceId)
      setActiveWorkspaceId(workspaceId)
      try {
        const scoped = sessions
          .filter((item) => (item.workspace_id || "") === workspaceId)
          .sort(
            (a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
          )
        if (scoped.length > 0) {
          await selectSession(scoped[0].session_id)
          return
        }
        // A workspace without a session still needs one: a task created with an
        // empty session id would silently run in the default session instead.
        const created = await createSession("", workspaceId)
        await refreshSessions()
        if (created?.session_id) {
          await selectSession(created.session_id)
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [refreshSessions, selectSession, sessions, translate]
  )

  const createNewSession = useCallback(
    async (workspaceId = null) => {
      const target = workspaceId === null ? activeWorkspaceId || "" : workspaceId || ""
      try {
        const scoped = sessions.filter((item) => (item.workspace_id || "") === target)
        const latestSession = scoped[scoped.length - 1]
        if (latestSession && (latestSession.task_count || 0) === 0) {
          setActiveWorkspaceId(target)
          await selectSession(latestSession.session_id)
          return
        }
        const created = await createSession("", target || undefined)
        await refreshSessions()
        if (created?.session_id) {
          setActiveWorkspaceId(target)
          await selectSession(created.session_id)
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [activeWorkspaceId, refreshSessions, selectSession, sessions, translate]
  )

  const createWorkspaceHandler = useCallback(
    async (payload) => {
      try {
        await createWorkspace(payload)
        await refreshWorkspaces()
      } catch (workspaceError) {
        setError(workspaceError?.message || translate("errorLoadFailed"))
        throw workspaceError
      }
    },
    [refreshWorkspaces, translate]
  )

  const updateWorkspaceHandler = useCallback(
    async (workspaceId, payload) => {
      try {
        await updateWorkspace(workspaceId, payload)
        await refreshWorkspaces()
        await refreshSessions()
      } catch (workspaceError) {
        setError(workspaceError?.message || translate("errorLoadFailed"))
        throw workspaceError
      }
    },
    [refreshSessions, refreshWorkspaces, translate]
  )

  const renameWorkspaceHandler = useCallback(
    async (workspaceId, name) => {
      try {
        await updateWorkspace(workspaceId, { name })
        await refreshWorkspaces()
      } catch (workspaceError) {
        setError(workspaceError?.message || translate("errorLoadFailed"))
      }
    },
    [refreshWorkspaces, translate]
  )

  const deleteWorkspaceHandler = useCallback(
    async (workspaceId) => {
      if (!window.confirm(translate("workspaceDeleteConfirm"))) return
      try {
        await deleteWorkspace(workspaceId)
        if (activeWorkspaceId === workspaceId) setActiveWorkspaceId("")
        // The scope cannot survive the workspace it names.
        if (workspaceScopeId === workspaceId) setWorkspaceScopeId("")
        await refreshWorkspaces()
        await refreshSessions()
      } catch (workspaceError) {
        setError(workspaceError?.message || translate("errorLoadFailed"))
      }
    },
    [activeWorkspaceId, refreshSessions, refreshWorkspaces, translate, workspaceScopeId]
  )

  const manageWorkspaces = useCallback(() => setActiveMenu("workspaces"), [])

  const createAgentHandler = useCallback(
    async (payload) => {
      try {
        await createAgent(payload)
        await refreshAgents()
      } catch (agentError) {
        setError(agentError?.message || translate("errorLoadFailed"))
        throw agentError
      }
    },
    [refreshAgents, translate]
  )

  const updateAgentHandler = useCallback(
    async (agentId, payload) => {
      try {
        await updateAgent(agentId, payload)
        await refreshAgents()
      } catch (agentError) {
        setError(agentError?.message || translate("errorLoadFailed"))
        throw agentError
      }
    },
    [refreshAgents, translate]
  )

  const deleteAgentHandler = useCallback(
    async (agentId) => {
      try {
        await deleteAgent(agentId)
        await refreshAgents()
      } catch (agentError) {
        setError(agentError?.message || translate("errorLoadFailed"))
      }
    },
    [refreshAgents, translate]
  )

  const requestCreateAgent = useCallback(() => {
    setActiveMenu("agents")
    setAgentCreateSignal((prev) => prev + 1)
  }, [])

  const saveSkillsRootHandler = useCallback(
    async (root) => {
      try {
        const data = await updateSkillsRoot(root)
        setSkillsRoot(data.skills_root ?? "")
        await refreshSkills()
      } catch (skillError) {
        setError(skillError?.message || translate("errorLoadFailed"))
        throw skillError
      }
    },
    [refreshSkills, translate]
  )

  const importSkillHandler = useCallback(
    async (sourcePath) => {
      try {
        await importSkill(sourcePath)
        await refreshSkills()
      } catch (skillError) {
        setError(skillError?.message || translate("errorLoadFailed"))
        throw skillError
      }
    },
    [refreshSkills, translate]
  )

  const deleteSkillHandler = useCallback(
    async (name) => {
      try {
        await deleteSkill(name)
        await refreshSkills()
      } catch (skillError) {
        setError(skillError?.message || translate("errorLoadFailed"))
      }
    },
    [refreshSkills, translate]
  )

  useEffect(() => {
    try {
      window.localStorage.setItem(TASK_COLUMN_WIDTHS_KEY, JSON.stringify(taskColumnWidths))
    } catch {
      // ignore persistence errors
    }
  }, [taskColumnWidths])

  useEffect(() => {
    try {
      window.localStorage.setItem(TASK_COLUMN_COLLAPSED_KEY, leftColumnCollapsed ? "1" : "0")
    } catch {
      // ignore persistence errors
    }
  }, [leftColumnCollapsed])

  useEffect(() => {
    try {
      window.localStorage.setItem(TASK_COMPOSER_HEIGHT_KEY, String(Math.round(composerHeight)))
    } catch {
      // ignore persistence errors
    }
  }, [composerHeight])

  // Shrinking the window must not leave the composer taller than the middle
  // column has room for, or the task list above it collapses to nothing.
  useEffect(() => {
    const clampComposer = () => {
      const containerHeight = taskColumnMainRef.current?.clientHeight
      if (!containerHeight) return
      const ceiling = maxComposerHeight(containerHeight)
      setComposerHeight((prev) => Math.min(prev, ceiling))
    }
    window.addEventListener("resize", clampComposer)
    return () => window.removeEventListener("resize", clampComposer)
  }, [])

  const startColumnResize = (event, which) => {
    event.preventDefault()
    const startX = event.clientX
    const containerWidth = taskWorkspaceRef.current?.clientWidth || window.innerWidth
    const available = Math.max(
      TASK_COLUMN_MIN_LEFT + TASK_COLUMN_MIN_MID,
      containerWidth - TASK_COLUMN_RESIZER_WIDTH * 2 - TASK_COLUMN_MIN_DETAIL
    )
    const startLeft = taskColumnWidths.left
    const startMid = taskColumnWidths.mid

    setResizingColumn(which)
    const previousUserSelect = document.body.style.userSelect
    const previousCursor = document.body.style.cursor
    document.body.style.userSelect = "none"
    document.body.style.cursor = "col-resize"

    const onMove = (moveEvent) => {
      const delta = moveEvent.clientX - startX
      if (which === "left") {
        const maxLeft = Math.max(TASK_COLUMN_MIN_LEFT, available - startMid)
        const next = Math.min(Math.max(startLeft + delta, TASK_COLUMN_MIN_LEFT), maxLeft)
        setTaskColumnWidths((prev) => ({ ...prev, left: Math.round(next) }))
      } else {
        const maxMid = Math.max(TASK_COLUMN_MIN_MID, available - startLeft)
        const next = Math.min(Math.max(startMid + delta, TASK_COLUMN_MIN_MID), maxMid)
        setTaskColumnWidths((prev) => ({ ...prev, mid: Math.round(next) }))
      }
    }

    const onUp = () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      document.body.style.userSelect = previousUserSelect
      document.body.style.cursor = previousCursor
      setResizingColumn("")
    }

    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
  }

  const startComposerResize = (event) => {
    event.preventDefault()
    const startY = event.clientY
    const containerHeight = taskColumnMainRef.current?.clientHeight || window.innerHeight
    const ceiling = maxComposerHeight(containerHeight)
    const startHeight = composerHeight

    setResizingComposer(true)
    const previousUserSelect = document.body.style.userSelect
    const previousCursor = document.body.style.cursor
    document.body.style.userSelect = "none"
    document.body.style.cursor = "row-resize"

    const onMove = (moveEvent) => {
      // Dragging up gives the composer more room, following the handle.
      const next = startHeight + (startY - moveEvent.clientY)
      setComposerHeight(Math.round(Math.min(Math.max(next, TASK_COMPOSER_MIN_HEIGHT), ceiling)))
    }

    const onUp = () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      document.body.style.userSelect = previousUserSelect
      document.body.style.cursor = previousCursor
      setResizingComposer(false)
    }

    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
  }

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
          // A scoped console stays in its workspace: falling back to a session of
          // another workspace would select something the tree does not show.
          const pool = workspaceScopeId
            ? nextList.filter((item) => (item.workspace_id || "") === workspaceScopeId)
            : nextList
          const next = pool[0]
          if (next) {
            setActiveWorkspaceId(next.workspace_id || workspaceScopeId || "")
            await selectSession(next.session_id)
          } else {
            setActiveSessionId("")
            setTasks([])
            applySelection("")
            setSelectedTask(null)
          }
        }
      } catch (sessionError) {
        setError(sessionError?.message || translate("errorLoadFailed"))
      }
    },
    [applySelection, selectSession, translate, workspaceScopeId]
  )

  const createNewTask = useCallback(
    async (payload) => {
      try {
        setError("")
        const result = await createTask({ ...payload, session_id: activeSessionRef.current })
        if (result?.task_id) {
          // Select and clear together: leaving the previous task in place meant the
          // highlighted row and the pane disagreed until this task's fetch landed.
          applySelection(result.task_id)
          setSelectedTask(null)
          setComposerTaskId(result.task_id)
          setEvents([])
          nextOffsetRef.current = 0
          setHasMoreEvents(false)
          // A task that just started is watched, not read: open its log.
          setTaskTab("events")
          const task = await refreshTask(result.task_id)
          await loadEvents(result.task_id, true, task?.status, true)
          await refreshTasks()
          await refreshSessions()
        }
        return result
      } catch (createError) {
        setError(createError?.message || translate("errorUnknown"))
        throw createError
      }
    },
    [applySelection, loadEvents, refreshTask, refreshTasks, refreshSessions, translate]
  )

  // Re-running replays the original request; a model that no longer exists falls
  // back to the provider recorded on the task. Undo and delete the old task first,
  // so the replay starts from a clean workspace and leaves no duplicate behind.
  const rerunTaskHandler = useCallback(
    async (task) => {
      if (!task?.task_id) return
      const payload = { query: task.query, agent_id: task.mode || "build", stream: true }
      if (task.model_id && models.some((item) => item.model_id === task.model_id)) {
        payload.model_id = task.model_id
      } else if (task.provider) {
        payload.provider = task.provider
      }
      try {
        setError("")
        const result = await revertAndDeleteTask(task.task_id)
        if (!result.deleted) {
          // Keep the task: its undo dialog is the only place to resolve these files.
          setError(
            result.blocked.length > 0
              ? `${translate("revertFailed")} ${translate("revertConflictNote")} ${result.blocked.join(", ")}`
              : translate("revertFailed")
          )
          refreshTasks().catch(() => {})
          return
        }
        setSelectedTaskIds((prev) => {
          const next = new Set(prev)
          next.delete(task.task_id)
          return next
        })
        await createNewTask(payload)
      } catch (rerunError) {
        setError(rerunError?.message || translate("errorUnknown"))
        refreshTasks().catch(() => {})
      }
    },
    [createNewTask, models, refreshTasks, translate]
  )

  // Forking branches a new session at this turn: it and every turn before it are
  // copied there, and the branch becomes the conversation on screen. The original
  // session keeps all of its turns, so the two conversations can diverge.
  const forkTaskHandler = useCallback(
    async (task) => {
      if (!task?.task_id) return
      try {
        setError("")
        await forkTaskSession(task, { refreshSessions, selectSession, selectTask })
      } catch (forkError) {
        setError(forkError?.message || translate("errorUnknown"))
      }
    },
    [refreshSessions, selectSession, selectTask, translate]
  )

  // Filling the composer from a task row: its prompt, agent and model come back so
  // the user can correct them and run the turn again.
  const editTaskHandler = useCallback(
    (task) => {
      if (!task?.task_id) return
      setError("")
      setActiveMenu("tasks")
      setComposerEdit(buildTaskEditDraft(task, { agents, models }))
      setComposerFocusSignal((prev) => prev + 1)
    },
    [agents, models]
  )

  // Sending an edited task replaces the original turn: it and every turn after it
  // are deleted first, so the edited content becomes the session's last turn and
  // nothing that ran later can reach it as context.
  const submitComposerTask = useCallback(
    async (payload) => {
      const edit = composerEdit
      if (!edit) return createNewTask(payload)
      try {
        setError("")
        const outcome = await replaceTaskWithEdit(edit, activeSessionRef.current)
        if (!outcome.deleted) {
          // The undo hit a conflict: keep the edit so nothing has to be retyped.
          refreshTasks().catch(() => {})
          throw new Error(
            outcome.blocked.length > 0
              ? `${translate("revertFailed")} ${translate("revertConflictNote")} ${outcome.blocked.join(", ")}`
              : translate("revertFailed")
          )
        }
        setComposerEdit(null)
        setSelectedTaskIds((prev) => {
          const next = new Set(prev)
          outcome.removed.forEach((taskId) => next.delete(taskId))
          return next
        })
        if (outcome.removed.includes(selectedIdRef.current)) {
          // The pane must not keep describing a turn that no longer exists.
          applySelection("")
          setSelectedTask(null)
          setEvents([])
          nextOffsetRef.current = 0
          setHasMoreEvents(false)
        }
        return await createNewTask(payload)
      } catch (editError) {
        setError(editError?.message || translate("errorUnknown"))
        refreshTasks().catch(() => {})
        throw editError
      }
    },
    [applySelection, composerEdit, createNewTask, refreshTasks, translate]
  )

  const stopComposerTask = useCallback(async () => {
    if (!composerTaskId) return
    const taskId = composerTaskId
    // Answer the click at once: the backend settles the task record, but what the
    // user reads as "it worked" is the stop button turning back into "send" - waiting
    // for the round trip made the click look dead.
    setComposerTaskId("")
    try {
      await stopTask(taskId)
      await refreshTasks()
      await refreshTask(taskId)
    } catch (stopError) {
      // The stop did not land: keep watching the task it was meant for.
      setComposerTaskId(taskId)
      setError(stopError?.message || translate("errorUnknown"))
    }
  }, [composerTaskId, refreshTask, refreshTasks, translate])

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
            const nextId = latestTaskId(nextTasks)
            applySelection(nextId)
            const task = await refreshTask(nextId)
            await loadEvents(nextId, true, task?.status, true)
          } else {
            applySelection("")
          }
        }

        await refreshTasks()
      } catch (deleteError) {
        setError(deleteError?.message || translate("errorUnknown"))
      }
    },
    [applySelection, loadEvents, refreshTask, refreshTasks, tasks, translate]
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
          const nextId = latestTaskId(remaining)
          applySelection(nextId)
          const task = await refreshTask(nextId)
          await loadEvents(nextId, true, task?.status, true)
        } else {
          applySelection("")
        }
      }

      await refreshTasks()
    } catch (deleteError) {
      setError(deleteError?.message || translate("errorUnknown"))
    }
  }, [applySelection, loadEvents, refreshTask, refreshTasks, selectedTaskIds, tasks, translate])

  const createProviderHandler = useCallback(
    async (payload) => {
      try {
        await createProvider(payload)
        await refreshProviders()
      } catch (providerError) {
        setError(providerError?.message || translate("errorUnknown"))
        throw providerError
      }
    },
    [refreshProviders, translate]
  )

  const updateProviderHandler = useCallback(
    async (providerId, payload) => {
      try {
        await updateProvider(providerId, payload)
        await refreshProviders()
      } catch (providerError) {
        setError(providerError?.message || translate("errorUnknown"))
        throw providerError
      }
    },
    [refreshProviders, translate]
  )

  const deleteProviderHandler = useCallback(
    async (providerId) => {
      try {
        await deleteProvider(providerId)
        await refreshProviders()
      } catch (providerError) {
        setError(providerError?.message || translate("errorUnknown"))
      }
    },
    [refreshProviders, translate]
  )

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

  const createMcpServerHandler = useCallback(
    async (payload) => {
      try {
        await createMcpServer(payload)
        await refreshMcpServers()
      } catch (mcpError) {
        setError(mcpError?.message || translate("errorUnknown"))
        throw mcpError
      }
    },
    [refreshMcpServers, translate]
  )

  const updateMcpServerHandler = useCallback(
    async (mcpId, payload) => {
      try {
        await updateMcpServer(mcpId, payload)
        await refreshMcpServers()
      } catch (mcpError) {
        setError(mcpError?.message || translate("errorUnknown"))
        throw mcpError
      }
    },
    [refreshMcpServers, translate]
  )

  const deleteMcpServerHandler = useCallback(
    async (mcpId) => {
      try {
        await deleteMcpServer(mcpId)
        await refreshMcpServers()
      } catch (mcpError) {
        setError(mcpError?.message || translate("errorUnknown"))
      }
    },
    [refreshMcpServers, translate]
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

  const refreshAgentsMd = useCallback(async () => {
    const config = await fetchAgentsMdConfig()
    setAgentsMdConfig(config)
    return config
  }, [])

  const updateAgentsMd = useCallback(
    async (enabledValue, maxBytesValue) => {
      try {
        const config = await updateAgentsMdConfig(enabledValue, maxBytesValue)
        setAgentsMdConfig(config)
      } catch (agentsMdError) {
        setError(agentsMdError?.message || translate("errorUnknown"))
      }
    },
    [translate]
  )

  const refreshPermissionMode = useCallback(async () => {
    const config = await fetchPermissionModeConfig()
    setPermissionModeConfig(config)
    return config
  }, [])

  const updatePermissionMode = useCallback(
    async (modeValue) => {
      try {
        const config = await updatePermissionModeConfig(modeValue)
        setPermissionModeConfig(config)
      } catch (permissionError) {
        setError(permissionError?.message || translate("errorUnknown"))
      }
    },
    [translate]
  )

  const refreshPermissionRules = useCallback(async () => {
    const config = await fetchPermissionRules()
    setPermissionRules(config)
    return config
  }, [])

  const deletePermissionRuleHandler = useCallback(
    async (tool, target) => {
      try {
        await deletePermissionRule(tool, target)
        await refreshPermissionRules()
      } catch (ruleError) {
        setError(ruleError?.message || translate("errorUnknown"))
      }
    },
    [refreshPermissionRules, translate]
  )

  const refreshDenyList = useCallback(async () => {
    const config = await fetchDenyList()
    setDenyList(config)
    return config
  }, [])

  // Creation errors stay in the form so the reason a pattern was rejected is
  // visible next to the field instead of in the page-wide banner.
  const createDenyRuleHandler = useCallback(
    async (payload) => {
      await createDenyRule(payload)
      await refreshDenyList()
    },
    [refreshDenyList]
  )

  const deleteDenyRuleHandler = useCallback(
    async (id) => {
      try {
        await deleteDenyRule(id)
        await refreshDenyList()
      } catch (ruleError) {
        setError(ruleError?.message || translate("errorUnknown"))
      }
    },
    [refreshDenyList, translate]
  )

  // A decision unblocks the task thread, so pull the task and its events right
  // away instead of waiting for the next poll tick.
  const handlePermissionDecided = useCallback(() => {
    const taskId = selectedIdRef.current
    if (taskId) {
      refreshTask(taskId)
        .then((task) => loadEvents(taskId, false, task?.status))
        .catch(() => {})
    }
    refreshTasks().catch(() => {})
    // An "always allow" answer adds a rule; keep the list honest.
    refreshPermissionRules().catch(() => {})
  }, [loadEvents, refreshPermissionRules, refreshTask, refreshTasks])

  // Same refresh for an answer: the task thread resumes, so the events and the
  // pending question both change in the same instant.
  const handleQuestionAnswered = useCallback(() => {
    const taskId = selectedIdRef.current
    if (taskId) {
      refreshTask(taskId)
        .then((task) => loadEvents(taskId, false, task?.status))
        .catch(() => {})
    }
    refreshTasks().catch(() => {})
  }, [loadEvents, refreshTask, refreshTasks])

  useEffect(() => {
    let cancelled = false
    const loadAll = async () => {
      try {
        const sessionList = await fetchSessions()
        if (cancelled) return
        setSessions(sessionList)
        const workspaceList = await fetchWorkspaces()
        if (cancelled) return
        setWorkspaces(workspaceList)
        const agentList = await fetchAgents()
        if (cancelled) return
        setAgents(agentList)
        const skillData = await fetchSkills()
        if (cancelled) return
        setSkills(skillData.skills ?? [])
        setSkillsRoot(skillData.skills_root ?? "")
        const providerList = await fetchProviders()
        if (cancelled) return
        setProviders(providerList)
        const modelList = await fetchModels()
        if (cancelled) return
        setModels(modelList)
        const mcpList = await fetchMcpServers()
        if (cancelled) return
        setMcpServers(mcpList)
        const toolList = await fetchTools()
        if (cancelled) return
        setTools(toolList)

        const sid = activeSessionRef.current || (sessionList[0]?.session_id ?? "")
        if (sid) {
          if (sid !== activeSessionRef.current) setActiveSessionId(sid)
          const currentSession = sessionList.find((item) => item.session_id === sid)
          setActiveWorkspaceId(currentSession?.workspace_id || "")
          const taskList = await fetchTasks(sid)
          if (cancelled) return
          setTasks(taskList)
          if (taskList.length > 0) {
            const current = selectedIdRef.current
            if (!current || !taskList.some((item) => item.task_id === current)) {
              applySelection(latestTaskId(taskList))
            }
          } else {
            applySelection("")
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
    refreshAgentsMd().catch((agentsMdError) =>
      setError(agentsMdError?.message || translate("errorLoadFailed"))
    )
    refreshPermissionMode().catch((permissionError) =>
      setError(permissionError?.message || translate("errorLoadFailed"))
    )
    refreshPermissionRules().catch(() => {})
    refreshDenyList().catch(() => {})
    refreshHealth().catch(() => {})
    refreshAgentMeta().catch(() => {})

    const timer = setInterval(() => {
      refreshHealth().catch(() => {})
      refreshRetention().catch((retentionError) =>
        setError(retentionError?.message || translate("errorLoadFailed"))
      )
      if (activeMenu === "overview") {
        refreshTasks().catch((tasksError) => setError(tasksError?.message || translate("errorLoadFailed")))
        refreshSessions().catch(() => {})
        refreshAgents().catch(() => {})
        refreshTools().catch(() => {})
        refreshModels().catch(() => {})
        refreshProviders().catch(() => {})
        refreshMcpServers().catch(() => {})
        refreshWorkspaces().catch(() => {})
      }
      if (activeMenu === "tasks") {
        refreshTasks().catch((tasksError) => setError(tasksError?.message || translate("errorLoadFailed")))
        refreshSessions().catch(() => {})
        refreshWorkspaces().catch(() => {})
        refreshAgents().catch(() => {})
        refreshSkills().catch(() => {})
      }
      if (activeMenu === "agents") {
        refreshAgents().catch(() => {})
        refreshAgentMeta().catch(() => {})
        refreshMcpServers().catch(() => {})
      }
      if (activeMenu === "tools") {
        refreshTools().catch(() => {})
      }
      if (activeMenu === "skills") {
        refreshSkills().catch(() => {})
      }
      if (activeMenu === "mcp") {
        refreshMcpServers().catch(() => {})
      }
      if (activeMenu === "workspaces") {
        refreshWorkspaces().catch(() => {})
      }
      if (activeMenu === "providers") {
        refreshProviders().catch(() => {})
      }
      if (activeMenu === "models") {
        refreshModels().catch(() => {})
        refreshProviders().catch(() => {})
      }
      if (activeMenu === "config") {
        refreshMaxSteps().catch(() => {})
        refreshAgentsMd().catch(() => {})
        refreshPermissionMode().catch(() => {})
      }
      if (activeMenu === "permissions") {
        refreshPermissionRules().catch(() => {})
      }
      if (activeMenu === "denylist") {
        refreshDenyList().catch(() => {})
      }
    }, 5000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [activeMenu, applySelection, refreshAgentMeta, refreshAgents, refreshDenyList, refreshHealth, refreshMaxSteps, refreshPermissionMode, refreshPermissionRules, refreshMcpServers, refreshModels, refreshProviders, refreshRetention, refreshSessions, refreshSkills, refreshTasks, refreshTools, refreshWorkspaces, translate])

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

  useEffect(() => {
    if (!composerTaskId) return undefined

    let cancelled = false
    const check = async () => {
      try {
        const task = await fetchTask(composerTaskId)
        if (cancelled) return
        if (!task || !isTaskRunningStatus(task.status)) {
          setComposerTaskId("")
        }
      } catch {
        if (!cancelled) setComposerTaskId("")
      }
    }

    check()
    const timer = setInterval(check, 1500)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [composerTaskId])

  return (
    <div className="app-shell">
      <AppSidebar
        activeMenu={activeMenu}
        collapsed={sidebarCollapsed}
        health={health}
        onNavigate={handleNavigate}
        onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
        systemTime={systemTime}
        translate={translate}
      />
      <div className="app-main">
        <AppTopbar
          activeMenu={activeMenu}
          locale={locale}
          localeOptions={localeOptions}
          onLocaleChange={setLocale}
          translate={translate}
        />
        {error && <div className="global-error">{error}</div>}
        <main className={`app-content ${activeMenu === "tasks" ? "is-fill" : ""}`}>
          {activeMenu === "overview" ? (
            <OverviewPage
              activeSession={sessions.find((session) => session.session_id === activeSessionId) || null}
              agents={agents}
              health={health}
              mcpServers={mcpServers}
              models={models}
              onNavigate={handleNavigate}
              onNewTask={startNewTask}
              onOpenTask={(taskId) => {
                selectTask(taskId)
                handleNavigate("tasks")
              }}
              providers={providers}
              sessions={sessions}
              tasks={tasks}
              tools={tools}
              translate={translate}
              workspaces={workspaces}
            />
          ) : activeMenu === "tasks" ? (
          <div
            className="task-workspace"
            ref={taskWorkspaceRef}
            style={{
              gridTemplateColumns: `minmax(0, ${
                leftColumnCollapsed ? TASK_COLUMN_COLLAPSED_WIDTH : taskColumnWidths.left
              }px) ${leftColumnCollapsed ? 0 : TASK_COLUMN_RESIZER_WIDTH}px minmax(0, ${
                taskColumnWidths.mid
              }px) ${TASK_COLUMN_RESIZER_WIDTH}px minmax(0, 1fr)`,
            }}
          >
            {leftColumnCollapsed ? (
              <aside className="task-column task-column-collapsed">
                <button
                  type="button"
                  className="session-collapse-btn"
                  onClick={() => setLeftColumnCollapsed(false)}
                  title={translate("sessionExpand")}
                  aria-label={translate("sessionExpand")}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M9 5l7 7-7 7"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              </aside>
            ) : (
              <aside className="task-column">
                <SessionTabs
                  workspaces={workspaces}
                  sessions={sessions}
                  activeSessionId={activeSessionId}
                  activeWorkspaceId={activeWorkspaceId}
                  scopedWorkspaceId={workspaceScopeId}
                  onSelect={handleSelectSession}
                  onSelectWorkspace={handleSelectWorkspace}
                  onOpenWorkspace={openWorkspaceConsole}
                  onCreate={createNewSession}
                  onRename={renameSessionHandler}
                  onDelete={deleteSessionHandler}
                  onRenameWorkspace={renameWorkspaceHandler}
                  onDeleteWorkspace={deleteWorkspaceHandler}
                  onManageWorkspaces={manageWorkspaces}
                  onClearScope={clearWorkspaceScope}
                  onCollapse={() => setLeftColumnCollapsed(true)}
                  translate={translate}
                />
              </aside>
            )}
            <div
              className={`task-resizer ${resizingColumn === "left" ? "active" : ""} ${
                leftColumnCollapsed ? "disabled" : ""
              }`}
              role="separator"
              aria-orientation="vertical"
              title={translate("taskColumnResize")}
              onPointerDown={(event) => startColumnResize(event, "left")}
            />
            <section
              className="task-column-main"
              ref={taskColumnMainRef}
              style={{
                gridTemplateRows: `minmax(0, 1fr) ${TASK_COMPOSER_RESIZER_HEIGHT}px ${composerHeight}px`,
              }}
            >
              <TaskList
                tasks={pagedTasks}
                selectedId={selectedId}
                onSelect={selectTask}
                onEdit={editTaskHandler}
                onRerun={rerunTaskHandler}
                onFork={forkTaskHandler}
                onRevert={setRevertTaskId}
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
                agents={agents}
                translate={translate}
              />
              <div
                className={`task-composer-resizer ${resizingComposer ? "active" : ""}`}
                role="separator"
                aria-orientation="horizontal"
                title={translate("taskComposerResize")}
                onPointerDown={startComposerResize}
              />
              <TaskComposer
                models={models}
                agents={agents}
                skills={skills}
                sessionId={activeSessionId}
                workspaceId={activeSessionWorkspaceId}
                composerRunning={Boolean(composerTaskId)}
                editRequest={composerEdit}
                onCancelEdit={() => setComposerEdit(null)}
                onCreate={submitComposerTask}
                onStop={stopComposerTask}
                onRequestCreateAgent={requestCreateAgent}
                onImportSkill={importSkillHandler}
                focusSignal={composerFocusSignal}
                translate={translate}
              />
            </section>
            <div
              className={`task-resizer ${resizingColumn === "mid" ? "active" : ""}`}
              role="separator"
              aria-orientation="vertical"
              title={translate("taskColumnResize")}
              onPointerDown={(event) => startColumnResize(event, "mid")}
            />
            <section className="task-detail-pane">
              <TaskDetailPage
                task={selectedTask}
                taskResult={taskResult}
                agents={agents}
                taskTab={taskTab}
                setTaskTab={setTaskTab}
                events={events}
                hasMoreEvents={hasMoreEvents}
                isLoadingEvents={isLoadingEvents}
                onLoadMore={() => loadEvents(selectedId, false, null, true)}
                onChangesReverted={() => {
                  // An undo can settle the task (status "reverted"), so both the list
                  // and the open detail panel have to catch up.
                  refreshTasks().catch(() => {})
                  if (selectedIdRef.current) refreshTask(selectedIdRef.current).catch(() => {})
                }}
                translate={translate}
                locale={locale}
              />
            </section>
          </div>
        ) : activeMenu === "agents" ? (
          <AgentManager
            agents={agents}
            meta={agentMeta}
            createSignal={agentCreateSignal}
            mcpServers={mcpServers}
            onManageMcp={() => setActiveMenu("mcp")}
            onCreate={createAgentHandler}
            onUpdate={updateAgentHandler}
            onDelete={deleteAgentHandler}
            onRefresh={refreshAgents}
            translate={translate}
          />
        ) : activeMenu === "tools" ? (
          <ToolManager
            tools={tools}
            agents={agents}
            locale={locale}
            onRefresh={refreshTools}
            translate={translate}
          />
        ) : activeMenu === "skills" ? (
          <SkillManager
            skills={skills}
            skillsRoot={skillsRoot}
            onSaveRoot={saveSkillsRootHandler}
            onImport={importSkillHandler}
            onDelete={deleteSkillHandler}
            onRefresh={refreshSkills}
            translate={translate}
          />
        ) : activeMenu === "mcp" ? (
          <McpServerManager
            servers={mcpServers}
            onCreate={createMcpServerHandler}
            onUpdate={updateMcpServerHandler}
            onDelete={deleteMcpServerHandler}
            onRefresh={refreshMcpServers}
            translate={translate}
          />
        ) : activeMenu === "workspaces" ? (
          <WorkspaceManager
            workspaces={workspaces}
            onCreate={createWorkspaceHandler}
            onUpdate={updateWorkspaceHandler}
            onDelete={deleteWorkspaceHandler}
            onOpenTasks={openWorkspaceConsole}
            onRefresh={refreshWorkspaces}
            translate={translate}
          />
        ) : activeMenu === "providers" ? (
          <ProviderManager
            providers={providers}
            onCreate={createProviderHandler}
            onUpdate={updateProviderHandler}
            onDelete={deleteProviderHandler}
            onRefresh={refreshProviders}
            translate={translate}
          />
        ) : activeMenu === "models" ? (
          <ModelManager
            models={models}
            providers={providers}
            onCreate={createModelHandler}
            onUpdate={updateModelHandler}
            onDelete={deleteModelHandler}
            onRefresh={refreshModels}
            onManageProviders={() => setActiveMenu("providers")}
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
            <AgentsMdManager
              agentsMdConfig={agentsMdConfig}
              onSave={updateAgentsMd}
              onRefresh={() =>
                refreshAgentsMd().catch((refreshError) =>
                  setError(refreshError?.message || translate("errorLoadFailed"))
                )
              }
              translate={translate}
            />
            <PermissionModeManager
              permissionModeConfig={permissionModeConfig}
              onSave={updatePermissionMode}
              onRefresh={() =>
                refreshPermissionMode().catch((refreshError) =>
                  setError(refreshError?.message || translate("errorLoadFailed"))
                )
              }
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
        ) : activeMenu === "permissions" ? (
          <PermissionRulesManager
            rules={permissionRules}
            onDelete={deletePermissionRuleHandler}
            onRefresh={() =>
              refreshPermissionRules().catch((refreshError) =>
                setError(refreshError?.message || translate("errorLoadFailed"))
              )
            }
            translate={translate}
          />
        ) : activeMenu === "denylist" ? (
          <DenyListManager
            denylist={denyList}
            onCreate={createDenyRuleHandler}
            onDelete={deleteDenyRuleHandler}
            onRefresh={() =>
              refreshDenyList().catch((refreshError) =>
                setError(refreshError?.message || translate("errorLoadFailed"))
              )
            }
            translate={translate}
          />
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
        <PermissionPrompt
          request={selectedTask?.pending_permission}
          onDecided={handlePermissionDecided}
          translate={translate}
        />
        <QuestionPrompt
          request={selectedTask?.pending_question}
          onAnswered={handleQuestionAnswered}
          translate={translate}
        />
        {revertTaskId ? (
          <RevertChangesDialog
            taskId={revertTaskId}
            translate={translate}
            onClose={() => setRevertTaskId("")}
            onReverted={() => {
              refreshTasks().catch(() => {})
              // Only refresh the detail panel when the undone task is the one it
              // is showing; otherwise this would replace an unrelated selection.
              if (revertTaskId === selectedIdRef.current) {
                refreshTask(revertTaskId).catch(() => {})
              }
            }}
          />
        ) : null}
      </div>
    </div>
  )
}
