import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { default as MonacoEditor } from "@monaco-editor/react"
import {
  createAgent,
  createMcpServer,
  createModel,
  createSession,
  createTask,
  createWorkspace,
  deleteAgent,
  deleteMcpServer,
  deleteModel,
  deleteSession,
  deleteSkill,
  deleteTask,
  deleteWorkspace,
  fetchAgentMeta,
  fetchAgents,
  fetchSkills,
  fetchHealth,
  fetchMcpServers,
  fetchModels,
  fetchRetentionConfig,
  fetchMaxStepsConfig,
  updateMaxStepsConfig,
  fetchPermissionModeConfig,
  updatePermissionModeConfig,
  fetchPermissionRules,
  deletePermissionRule,
  fetchSessions,
  fetchTask,
  fetchTaskEvents,
  fetchTasks,
  fetchWorkspaces,
  importSkill,
  renameSession,
  stopTask,
  updateAgent,
  updateMcpServer,
  updateModel,
  updateRetentionConfig,
  updateSkillsRoot,
  updateWorkspace,
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
import PermissionPrompt from "./components/PermissionPrompt"
import TaskRowActions from "./components/TaskRowActions"
import TaskToolbarActions from "./components/TaskToolbarActions"
import AgentManager from "./components/admin/AgentManager"
import McpServerManager from "./components/admin/McpServerManager"
import ModelManager from "./components/admin/ModelManager"
import {
  MaxStepsManager,
  PermissionModeManager,
  PermissionRulesManager,
  RetentionManager,
} from "./components/admin/SettingsPanels"
import SkillManager from "./components/admin/SkillManager"
import WorkspaceManager from "./components/admin/WorkspaceManager"
import { PROVIDER_OPTIONS, agentDisplayName } from "./components/admin/shared"
import "./App.css"

const EVENT_PAGE_SIZE = 30
const TASK_PAGE_SIZE = 12
const SESSION_PREVIEW_LIMIT = 10

const MENU_ITEMS = [
  { key: "tasks", labelKey: "menuTasks" },
  { key: "agents", labelKey: "menuAgents" },
  { key: "skills", labelKey: "menuSkills" },
  { key: "mcp", labelKey: "menuMcp" },
  { key: "workspaces", labelKey: "menuWorkspaces" },
  { key: "models", labelKey: "menuModels" },
  { key: "config", labelKey: "menuConfig" },
]

const AGENT_CREATE_OPTION = "__create_agent__"

function resolveAgentName(agentId, agents, translate) {
  const agent = (agents || []).find((item) => item.agent_id === agentId)
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

const MODE_LABEL_KEYS = {
  build: "modeBuild",
  ask: "modeAsk",
  plan: "modePlan",
}

const modeLabelKey = (mode) => MODE_LABEL_KEYS[mode] || "modeBuild"

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

function SessionTabs({
  workspaces,
  sessions,
  activeSessionId,
  activeWorkspaceId,
  onSelect,
  onSelectWorkspace,
  onCreate,
  onRename,
  onDelete,
  onRenameWorkspace,
  onDeleteWorkspace,
  onManageWorkspaces,
  onCollapse,
  translate,
}) {
  const [renaming, setRenaming] = useState(false)
  const [renameTargetId, setRenameTargetId] = useState("")
  const [renameValue, setRenameValue] = useState("")
  const [collapsedWorkspaces, setCollapsedWorkspaces] = useState({})
  const [expandedGroups, setExpandedGroups] = useState({})
  const [menu, setMenu] = useState(null)
  const [wsMenu, setWsMenu] = useState(null)

  const orphanSessions = useMemo(
    () => sessions.filter((item) => !item.workspace_id),
    [sessions]
  )

  const sessionsByWorkspace = useMemo(() => {
    const grouped = {}
    sessions.forEach((item) => {
      if (!item.workspace_id) return
      if (!grouped[item.workspace_id]) grouped[item.workspace_id] = []
      grouped[item.workspace_id].push(item)
    })
    return grouped
  }, [sessions])

  useEffect(() => {
    if (!menu && !wsMenu) return undefined
    const closeMenu = () => {
      setMenu(null)
      setWsMenu(null)
    }
    window.addEventListener("click", closeMenu)
    window.addEventListener("contextmenu", closeMenu)
    window.addEventListener("scroll", closeMenu, true)
    return () => {
      window.removeEventListener("click", closeMenu)
      window.removeEventListener("contextmenu", closeMenu)
      window.removeEventListener("scroll", closeMenu, true)
    }
  }, [menu, wsMenu])

  const toggleWorkspace = (workspaceId) => {
    setCollapsedWorkspaces((prev) => ({ ...prev, [workspaceId]: !prev[workspaceId] }))
  }

  const beginRename = (sessionId) => {
    const current = sessions.find((item) => item.session_id === sessionId)
    setRenameTargetId(sessionId)
    setRenameValue(current?.name || "")
    setRenaming(true)
  }

  const submitRename = () => {
    const value = renameValue.trim()
    if (!value || !renameTargetId) return
    onRename(renameTargetId, value)
    setRenaming(false)
  }

  const beginWorkspaceRename = (workspaceId) => {
    const current = workspaces.find((item) => item.workspace_id === workspaceId)
    const next = window.prompt(translate("workspaceRenamePrompt"), current?.name || "")
    if (next === null) return
    const value = next.trim()
    if (!value) return
    onRenameWorkspace(workspaceId, value)
  }

  const openSessionMenu = (event, sessionId) => {
    event.preventDefault()
    event.stopPropagation()
    setWsMenu(null)
    setMenu({
      sessionId,
      x: Math.min(event.clientX, window.innerWidth - 150),
      y: Math.min(event.clientY, window.innerHeight - 84),
    })
  }

  const openWorkspaceMenu = (event, workspaceId) => {
    event.preventDefault()
    event.stopPropagation()
    setMenu(null)
    setWsMenu({
      workspaceId,
      x: Math.min(event.clientX, window.innerWidth - 150),
      y: Math.min(event.clientY, window.innerHeight - 84),
    })
  }

  const renderSessionRow = (item) => (
    <button
      key={item.session_id}
      type="button"
      className={`session-node session-node-child ${item.session_id === activeSessionId ? "active" : ""}`}
      onClick={() => onSelect(item.session_id)}
      onContextMenu={(event) => openSessionMenu(event, item.session_id)}
    >
      <span className="session-node-name">{item.name}</span>
      {item.task_count > 0 && <span className="session-tab-count">{item.task_count}</span>}
    </button>
  )

  const renderSessionGroup = (groupKey, items, emptyText) => {
    if (items.length === 0) {
      return <div className="session-group-empty">{emptyText}</div>
    }
    const sorted = [...items].sort(
      (a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
    )
    const expanded = expandedGroups[groupKey] === true
    const visible = expanded ? sorted : sorted.slice(0, SESSION_PREVIEW_LIMIT)
    const hidden = sorted.length - visible.length
    return (
      <>
        {visible.map(renderSessionRow)}
        {hidden > 0 && (
          <button
            type="button"
            className="session-more"
            onClick={() => setExpandedGroups((prev) => ({ ...prev, [groupKey]: true }))}
          >
            {translate("sessionShowMore")} ({hidden})
          </button>
        )}
      </>
    )
  }

  return (
    <section className="panel session-tabs-panel">
      <div className="panel-titlebar session-tabs-titlebar">
        <h2>{translate("sessionTitle")}</h2>
        <button
          type="button"
          className="session-collapse-btn"
          onClick={onCollapse}
          title={translate("sessionCollapse")}
          aria-label={translate("sessionCollapse")}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M15 5l-7 7 7 7"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
      <div className="panel-body session-tabs-body">
        <div className="session-tree">
          <div className="session-group">
            <div className="session-group-head">
              <button type="button" className="session-group-title" onClick={onManageWorkspaces}>
                {translate("workspaceGroupTitle")}
              </button>
              <span className="session-group-count">{workspaces.length}</span>
              <button
                type="button"
                className="session-group-action"
                onClick={onManageWorkspaces}
                title={translate("workspaceManage")}
              >
                +
              </button>
            </div>
            {workspaces.length === 0 ? (
              <div className="session-group-empty">{translate("workspaceEmpty")}</div>
            ) : (
              workspaces.map((workspace) => {
                const collapsed = collapsedWorkspaces[workspace.workspace_id] === true
                const children = sessionsByWorkspace[workspace.workspace_id] || []
                return (
                  <div className="workspace-node" key={workspace.workspace_id}>
                    <div
                      className={`session-node workspace-node-head ${
                        workspace.workspace_id === activeWorkspaceId ? "active" : ""
                      }`}
                    >
                      <button
                        type="button"
                        className="session-node-caret"
                        onClick={() => toggleWorkspace(workspace.workspace_id)}
                      >
                        {collapsed ? "▸" : "▾"}
                      </button>
                      <button
                        type="button"
                        className="session-node-main"
                        title={workspace.root_path}
                        onClick={() => {
                          onSelectWorkspace(workspace.workspace_id)
                          setCollapsedWorkspaces((prev) => ({
                            ...prev,
                            [workspace.workspace_id]: false,
                          }))
                        }}
                        onContextMenu={(event) => openWorkspaceMenu(event, workspace.workspace_id)}
                      >
                        <svg className="workspace-icon" viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            d="M3 6.5A2.5 2.5 0 0 1 5.5 4h3.2l1.8 2h8A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"
                            fill="currentColor"
                          />
                        </svg>
                        <span className="session-node-name">{workspace.name}</span>
                      </button>
                      <button
                        type="button"
                        className="session-node-action"
                        title={translate("sessionAdd")}
                        onClick={() => onCreate(workspace.workspace_id)}
                      >
                        +
                      </button>
                    </div>
                    {!collapsed && (
                      <div className="workspace-children">
                        {renderSessionGroup(
                          workspace.workspace_id,
                          children,
                          translate("workspaceNoSessions")
                        )}
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>

          <div className="session-group">
            <div className="session-group-head">
              <span className="session-group-title static">{translate("taskGroupTitle")}</span>
              <span className="session-group-count">{orphanSessions.length}</span>
              <button
                type="button"
                className="session-group-action"
                onClick={() => onCreate("")}
                title={translate("sessionAdd")}
              >
                +
              </button>
            </div>
            <div className="workspace-children">
              {renderSessionGroup("__orphan__", orphanSessions, translate("taskGroupEmpty"))}
            </div>
          </div>

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
      </div>
      {menu && (
        <div
          className="session-menu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => {
              setMenu(null)
              beginRename(menu.sessionId)
            }}
          >
            {translate("sessionRename")}
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => {
              setMenu(null)
              onDelete(menu.sessionId)
            }}
          >
            {translate("sessionDelete")}
          </button>
        </div>
      )}
      {wsMenu && (
        <div
          className="session-menu"
          style={{ left: wsMenu.x, top: wsMenu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => {
              setWsMenu(null)
              beginWorkspaceRename(wsMenu.workspaceId)
            }}
          >
            {translate("sessionRename")}
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => {
              setWsMenu(null)
              onDeleteWorkspace(wsMenu.workspaceId)
            }}
          >
            {translate("workspaceDelete")}
          </button>
        </div>
      )}
    </section>
  )
}

function TaskList({
  tasks,
  selectedId,
  onSelect,
  onRerun,
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
                        {resolveAgentName(item.mode, agents, translate)}
                      </span>
                      <span className="hint">
                        {translate("taskEventCountPrefix")}: {item.event_count}
                      </span>
                    </div>
                  </div>
                  <TaskRowActions
                    running={isTaskRunningStatus(item.status)}
                    onRerun={() => onRerun(item)}
                    onDelete={() => onDelete(item.task_id)}
                    translate={translate}
                  />
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
  composerRunning,
  onCreate,
  onStop,
  onRequestCreateAgent,
  onImportSkill,
  translate,
}) {
  const [query, setQuery] = useState("")
  const [modelId, setModelId] = useState("")
  const [provider, setProvider] = useState("openai-compatible")
  const [agentId, setAgentId] = useState("")
  const [busy, setBusy] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [pickerAnchor, setPickerAnchor] = useState(null)
  const [pickedSkills, setPickedSkills] = useState([])
  const skillsButtonRef = useRef(null)
  const pickerRef = useRef(null)

  const effectiveModelId = modelId || (models && models.length ? models[0].model_id : "")
  const effectiveAgentId = agentId || (agents && agents.length ? agents[0].agent_id : "")

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
      const payload = { query, stream: false, agent_id: effectiveAgentId }
      if (models && models.length) {
        payload.model_id = effectiveModelId
      } else {
        payload.provider = provider
      }
      await onCreate(payload)
      setQuery("")
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
    setQuery((prev) => (prev ? `${prev}\n${line}` : line))
    setPickedSkills((prev) => (prev.includes(skill.name) ? prev : [...prev, skill.name]))
    setSkillsOpen(false)
  }

  return (
    <section className="panel task-composer-panel">
      <div className="panel-titlebar">
        <h2>{translate("taskComposerTitle")}</h2>
      </div>
      <div className="panel-body">
        <form className="task-composer" onSubmit={submit}>
          <textarea
            className="composer-textarea"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onQueryKeyDown}
            placeholder={translate("taskFormPlaceholder")}
          />
          <div className="composer-toolbar">
            <select
              className="composer-select"
              value={effectiveAgentId}
              onChange={(event) => {
                const value = event.target.value
                if (value === AGENT_CREATE_OPTION) {
                  onRequestCreateAgent()
                  return
                }
                setAgentId(value)
              }}
              title={translate("taskFormAgent")}
            >
              {(agents || []).map((item) => (
                <option value={item.agent_id} key={item.agent_id}>
                  {agentDisplayName(item, translate)}
                </option>
              ))}
              <option value={AGENT_CREATE_OPTION}>{translate("agentCreateOption")}</option>
            </select>

            {models && models.length > 0 ? (
              <select
                className="composer-select"
                value={effectiveModelId}
                onChange={(event) => setModelId(event.target.value)}
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
                {translate("taskFormSkills")}
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

            {composerRunning ? (
              <button
                type="button"
                className="composer-icon-btn stop"
                onClick={onStop}
                title={translate("taskStop")}
                aria-label={translate("taskStop")}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M6 6l12 12M18 6L6 18"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
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
        </form>
      </div>
    </section>
  )
}

function TaskDetail({ task, result, agents, translate }) {
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
          <span>{translate("detailAgent")}</span>
          <strong>{resolveAgentName(task.mode, agents, translate)}</strong>
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

function TaskDetailPage({ task, taskResult, agents, taskTab, setTaskTab, events, hasMoreEvents, isLoadingEvents, onLoadMore, translate }) {
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
          <TaskDetail task={task} result={taskResult} agents={agents} translate={translate} />
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
  const isLlmPayload = event.category === "llm_request" || event.category === "llm_response"
  const editorHeight = isLlmPayload ? "450px" : "150px"

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
              height={editorHeight}
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

export default function App() {
  const [sessions, setSessions] = useState([])
  const [workspaces, setWorkspaces] = useState([])
  const [agents, setAgents] = useState([])
  const [mcpServers, setMcpServers] = useState([])
  const [agentMeta, setAgentMeta] = useState(null)
  const [agentCreateSignal, setAgentCreateSignal] = useState(0)
  const [skills, setSkills] = useState([])
  const [skillsRoot, setSkillsRoot] = useState("")
  const [composerTaskId, setComposerTaskId] = useState("")
  const [taskColumnWidths, setTaskColumnWidths] = useState(loadTaskColumnWidths)
  const [leftColumnCollapsed, setLeftColumnCollapsed] = useState(loadLeftColumnCollapsed)
  const [resizingColumn, setResizingColumn] = useState("")
  const taskWorkspaceRef = useRef(null)
  const [activeSessionId, setActiveSessionId] = useState("")
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("")
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState("")
  const [selectedTask, setSelectedTask] = useState(null)
  const [events, setEvents] = useState([])
  const [hasMoreEvents, setHasMoreEvents] = useState(false)
  const [isLoadingEvents, setIsLoadingEvents] = useState(false)
  const [error, setError] = useState("")
  const [retentionConfig, setRetentionConfig] = useState(null)
  const [maxStepsConfig, setMaxStepsConfig] = useState(null)
  const [permissionModeConfig, setPermissionModeConfig] = useState(null)
  const [permissionRules, setPermissionRules] = useState(null)
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
        await refreshWorkspaces()
        await refreshSessions()
      } catch (workspaceError) {
        setError(workspaceError?.message || translate("errorLoadFailed"))
      }
    },
    [activeWorkspaceId, refreshSessions, refreshWorkspaces, translate]
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
          setActiveWorkspaceId(nextList[0]?.workspace_id || "")
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
          setComposerTaskId(result.task_id)
          setEvents([])
          nextOffsetRef.current = 0
          setHasMoreEvents(false)
          setTaskTab("detail")
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
    [loadEvents, refreshTask, refreshTasks, refreshSessions, translate]
  )

  // Re-running replays the original request; a model that no longer exists falls
  // back to the provider recorded on the task.
  const rerunTaskHandler = useCallback(
    (task) => {
      if (!task) return
      const payload = { query: task.query, agent_id: task.mode || "build", stream: false }
      if (task.model_id && models.some((item) => item.model_id === task.model_id)) {
        payload.model_id = task.model_id
      } else if (task.provider) {
        payload.provider = task.provider
      }
      createNewTask(payload).catch(() => {})
    },
    [createNewTask, models]
  )

  const stopComposerTask = useCallback(async () => {
    if (!composerTaskId) return
    try {
      await stopTask(composerTaskId)
      await refreshTasks()
      await refreshTask(composerTaskId)
    } catch (stopError) {
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
        const modelList = await fetchModels()
        if (cancelled) return
        setModels(modelList)
        const mcpList = await fetchMcpServers()
        if (cancelled) return
        setMcpServers(mcpList)

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
    refreshPermissionMode().catch((permissionError) =>
      setError(permissionError?.message || translate("errorLoadFailed"))
    )
    refreshPermissionRules().catch(() => {})
    refreshHealth().catch(() => {})
    refreshAgentMeta().catch(() => {})

    const timer = setInterval(() => {
      refreshHealth().catch(() => {})
      refreshRetention().catch((retentionError) =>
        setError(retentionError?.message || translate("errorLoadFailed"))
      )
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
      if (activeMenu === "skills") {
        refreshSkills().catch(() => {})
      }
      if (activeMenu === "mcp") {
        refreshMcpServers().catch(() => {})
      }
      if (activeMenu === "workspaces") {
        refreshWorkspaces().catch(() => {})
      }
      if (activeMenu === "models") {
        refreshModels().catch(() => {})
      }
      if (activeMenu === "config") {
        refreshMaxSteps().catch(() => {})
        refreshPermissionMode().catch(() => {})
        refreshPermissionRules().catch(() => {})
      }
    }, 5000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [activeMenu, refreshAgentMeta, refreshAgents, refreshHealth, refreshMaxSteps, refreshPermissionMode, refreshPermissionRules, refreshMcpServers, refreshModels, refreshRetention, refreshSessions, refreshSkills, refreshTasks, refreshWorkspaces, translate])

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
                  onSelect={handleSelectSession}
                  onSelectWorkspace={handleSelectWorkspace}
                  onCreate={createNewSession}
                  onRename={renameSessionHandler}
                  onDelete={deleteSessionHandler}
                  onRenameWorkspace={renameWorkspaceHandler}
                  onDeleteWorkspace={deleteWorkspaceHandler}
                  onManageWorkspaces={manageWorkspaces}
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
            <section className="task-column-main">
              <TaskList
                tasks={pagedTasks}
                selectedId={selectedId}
                onSelect={selectTask}
                onRerun={rerunTaskHandler}
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
              <TaskComposer
                models={models}
                agents={agents}
                skills={skills}
                composerRunning={Boolean(composerTaskId)}
                onCreate={createNewTask}
                onStop={stopComposerTask}
                onRequestCreateAgent={requestCreateAgent}
                onImportSkill={importSkillHandler}
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
                translate={translate}
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
            onRefresh={refreshWorkspaces}
            translate={translate}
          />
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
      <PermissionPrompt
        request={selectedTask?.pending_permission}
        onDecided={handlePermissionDecided}
        translate={translate}
      />
    </div>
  )
}
