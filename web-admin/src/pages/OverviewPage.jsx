// Landing page: session context, KPI tiles, recent tasks and the shortcuts the
// operators reach for most often. Everything here is derived from data the shell
// already polls, so the page never fires extra requests.
import { formatTime } from "../utils/format"
import { getHealthClass, getHealthText } from "../utils/health"
import { NAV_ICONS } from "../components/shell/navigation"
import { getTaskStatusClass, getTaskStatusText } from "../i18n"

const QUICK_LINKS = [
  { key: "agents", icon: "bot", labelKey: "overviewQuickAgents" },
  { key: "tools", icon: "wrench", labelKey: "overviewQuickTools" },
  { key: "models", icon: "cpu", labelKey: "overviewQuickModels" },
  { key: "config", icon: "settings", labelKey: "overviewQuickConfig" },
]

function StatTile({ icon, value, label }) {
  const TileIcon = NAV_ICONS[icon] || NAV_ICONS.overview
  return (
    <div className="stat-tile">
      <span className="stat-tile-icon">
        <TileIcon />
      </span>
      <span className="stat-tile-value">{value}</span>
      <span className="stat-tile-label">{label}</span>
    </div>
  )
}

export default function OverviewPage({
  activeSession,
  agents,
  health,
  mcpServers,
  models,
  onNavigate,
  onNewTask,
  onOpenTask,
  providers,
  sessions,
  tasks,
  tools,
  translate,
  workspaces,
}) {
  const recentTasks = tasks.slice(-5).reverse()
  const stats = [
    { key: "sessions", icon: "tasks", labelKey: "overviewStatSessions", value: sessions.length },
    { key: "tasks", icon: "overview", labelKey: "overviewStatTasks", value: tasks.length },
    { key: "agents", icon: "bot", labelKey: "overviewStatAgents", value: agents.length },
    { key: "tools", icon: "wrench", labelKey: "overviewStatTools", value: tools.length },
    { key: "models", icon: "cpu", labelKey: "overviewStatModels", value: models.length },
    { key: "providers", icon: "server", labelKey: "overviewStatProviders", value: providers.length },
  ]

  return (
    <div className="overview-page">
      <section className="overview-hero">
        <div className="overview-hero-copy">
          <span className="overview-eyebrow">{translate("overviewEyebrow")}</span>
          <p className="overview-session">
            {activeSession ? (
              <>
                <span>{translate("overviewCurrentSession")}</span>
                <strong>{activeSession.name || activeSession.session_id}</strong>
              </>
            ) : (
              <span className="is-muted">{translate("overviewNoSession")}</span>
            )}
          </p>
          <p className="overview-hint">{translate("overviewHint")}</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={onNewTask}>
          {translate("overviewNewTask")}
        </button>
      </section>

      <section className="overview-stats" aria-label={translate("overviewEyebrow")}>
        {stats.map((stat) => (
          <StatTile
            key={stat.key}
            icon={stat.icon}
            value={stat.value}
            label={translate(stat.labelKey)}
          />
        ))}
      </section>

      <div className="overview-columns">
        <section className="panel overview-recent">
          <div className="panel-titlebar">
            <h2>{translate("overviewRecent")}</h2>
            <button type="button" className="btn btn-compact" onClick={() => onNavigate("tasks")}>
              {translate("overviewViewAll")}
            </button>
          </div>
          <div className="panel-body overview-recent-body">
            {recentTasks.length === 0 ? (
              <div className="empty">{translate("overviewRecentEmpty")}</div>
            ) : (
              recentTasks.map((task) => (
                <button
                  key={task.task_id}
                  type="button"
                  className="overview-task"
                  onClick={() => onOpenTask(task.task_id)}
                >
                  <span className={`status ${getTaskStatusClass(task.status)}`}>
                    {getTaskStatusText(translate, task.status)}
                  </span>
                  <span className="overview-task-title">{task.name || task.query}</span>
                  <span className="overview-task-time">{formatTime(task.created_at)}</span>
                </button>
              ))
            )}
          </div>
        </section>

        <div className="overview-side">
          <section className="panel overview-quick">
            <div className="panel-titlebar">
              <h2>{translate("overviewQuick")}</h2>
            </div>
            <div className="panel-body quick-links">
              {QUICK_LINKS.map((link) => {
                const LinkIcon = NAV_ICONS[link.icon]
                return (
                  <button
                    key={link.key}
                    type="button"
                    className="quick-link"
                    onClick={() => onNavigate(link.key)}
                  >
                    <span className="quick-link-icon">
                      <LinkIcon />
                    </span>
                    <span className="quick-link-label">{translate(link.labelKey)}</span>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="panel overview-system">
            <div className="panel-titlebar">
              <h2>{translate("overviewSystem")}</h2>
            </div>
            <div className="panel-body overview-facts">
              <div className="overview-fact">
                <span>{translate("overviewSystemHealth")}</span>
                <strong className={`status ${getHealthClass(health)}`}>
                  {getHealthText(health, translate)}
                </strong>
              </div>
              <div className="overview-fact">
                <span>{translate("overviewSystemWorkspaces")}</span>
                <strong>{workspaces.length}</strong>
              </div>
              <div className="overview-fact">
                <span>{translate("overviewSystemMcp")}</span>
                <strong>{mcpServers.length}</strong>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
