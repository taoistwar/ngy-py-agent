// The left column of the task console: workspaces, their sessions, and the
// scope that limits the tree to a single workspace.
import { useEffect, useMemo, useState } from "react"

const SESSION_PREVIEW_LIMIT = 10

export default function SessionTabs({
  workspaces,
  sessions,
  activeSessionId,
  activeWorkspaceId,
  scopedWorkspaceId,
  onSelect,
  onSelectWorkspace,
  onOpenWorkspace,
  onCreate,
  onRename,
  onDelete,
  onRenameWorkspace,
  onDeleteWorkspace,
  onManageWorkspaces,
  onClearScope,
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

  // A console entered from the workspace list is scoped to that one workspace:
  // the tree shows its sessions instead of every workspace in the account.
  const scopedWorkspace = useMemo(
    () =>
      scopedWorkspaceId
        ? workspaces.find((item) => item.workspace_id === scopedWorkspaceId) || null
        : null,
    [scopedWorkspaceId, workspaces]
  )
  const visibleWorkspaces = useMemo(
    () => (scopedWorkspace ? [scopedWorkspace] : workspaces),
    [scopedWorkspace, workspaces]
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
          {scopedWorkspace && (
            <div className="workspace-scope-bar">
              <span className="workspace-scope-label">{translate("workspaceScopeLabel")}</span>
              <span className="workspace-scope-name" title={scopedWorkspace.root_path}>
                {scopedWorkspace.name}
              </span>
              <button type="button" className="workspace-scope-clear" onClick={onClearScope}>
                {translate("workspaceScopeClear")}
              </button>
            </div>
          )}
          <div className="session-group">
            <div className="session-group-head">
              <button type="button" className="session-group-title" onClick={onManageWorkspaces}>
                {translate("workspaceGroupTitle")}
              </button>
              <span className="session-group-count">{visibleWorkspaces.length}</span>
              <button
                type="button"
                className="session-group-action"
                onClick={onManageWorkspaces}
                title={translate("workspaceManage")}
              >
                +
              </button>
            </div>
            {visibleWorkspaces.length === 0 ? (
              <div className="session-group-empty">{translate("workspaceEmpty")}</div>
            ) : (
              visibleWorkspaces.map((workspace) => {
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
                        // A double click enters the single-workspace console, the
                        // same way opening the workspace from the workspace list does.
                        onDoubleClick={() => onOpenWorkspace(workspace.workspace_id)}
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

          {/* A scoped console is about one workspace, so the workspace-less
              sessions have no place in it. */}
          {!scopedWorkspace && (
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
              <button type="button" className="btn btn-compact btn-primary" onClick={submitRename}>
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

