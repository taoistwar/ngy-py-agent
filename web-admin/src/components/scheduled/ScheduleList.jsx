// The schedule cards of the console's "schedules" tab. It lives on its own because
// the page now swaps three tabs in one panel, so the list is only one of them.
import { formatTime } from "../../utils/format"
import { permissionModeLabel } from "./permissionOptions"

export default function ScheduleList({
  schedules,
  selectedId,
  busy,
  onSelect,
  onShowRuns,
  onRun,
  onToggle,
  onEdit,
  onDelete,
  translate,
}) {
  if (schedules.length === 0) {
    return <div className="empty">{translate("schedulesEmpty")}</div>
  }
  return (
    <ul className="schedule-list">
      {schedules.map((schedule) => {
        const active = schedule.schedule_id === selectedId
        const working = busy === schedule.schedule_id
        return (
          <li key={schedule.schedule_id} className={`schedule-card ${active ? "active" : ""}`}>
            <div
              className="schedule-card-main"
              role="button"
              tabIndex={0}
              onClick={() => onSelect(schedule.schedule_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  onSelect(schedule.schedule_id)
                }
              }}
            >
              <div className="schedule-card-head">
                <strong>{schedule.name || translate("scheduleUnnamed")}</strong>
                <code className="schedule-cron">{schedule.cron}</code>
                <span className={`badge ${schedule.enabled ? "schedule-badge-on" : "schedule-badge-off"}`}>
                  {translate(schedule.enabled ? "scheduleEnabledOn" : "scheduleEnabledOff")}
                </span>
                {schedule.running ? (
                  <span className="badge schedule-badge-running">
                    {translate("scheduleRunningBadge")}
                  </span>
                ) : null}
                {schedule.recurring ? null : (
                  <span className="badge">{translate("scheduleOnceBadge")}</span>
                )}
              </div>
              <p className="schedule-prompt" title={schedule.prompt}>
                {schedule.prompt}
              </p>
              <div className="schedule-meta">
                <span>
                  {translate("scheduleNextRun")}:{" "}
                  {schedule.enabled
                    ? formatTime(schedule.next_run_at) || translate("scheduleNever")
                    : translate("schedulePaused")}
                </span>
                <span>
                  {translate("scheduleLastRun")}:{" "}
                  {formatTime(schedule.last_run_at) || translate("scheduleNever")}
                </span>
                {/* Only shown when pinned: "follows the global mode" is the
                    normal case and would be noise on every row. */}
                {schedule.permission_mode ? (
                  <span>
                    {translate("scheduleFormPermission")}:{" "}
                    {permissionModeLabel(translate, schedule.permission_mode)}
                  </span>
                ) : null}
              </div>
            </div>
            <div className="schedule-actions">
              <button
                type="button"
                className="btn btn-compact"
                disabled={working}
                onClick={() => onRun(schedule)}
              >
                {translate("scheduleRunNow")}
              </button>
              <button
                type="button"
                className="btn btn-compact"
                onClick={() => onShowRuns(schedule)}
              >
                {translate("scheduleRunsTitle")}
              </button>
              <button
                type="button"
                className="btn btn-compact"
                disabled={working}
                onClick={() => onToggle(schedule)}
              >
                {translate(schedule.enabled ? "schedulePause" : "scheduleResume")}
              </button>
              <button
                type="button"
                className="btn btn-compact"
                onClick={() => onEdit(schedule)}
              >
                {translate("scheduleEdit")}
              </button>
              <button
                type="button"
                className="btn btn-compact btn-danger"
                disabled={working}
                onClick={() => onDelete(schedule)}
              >
                {translate("scheduleDelete")}
              </button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
