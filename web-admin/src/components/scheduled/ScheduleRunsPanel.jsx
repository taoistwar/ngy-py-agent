// Run history of one schedule: what each attempt created and how it ended.
//
// The status shown is the *task's* status whenever a task exists - the run row only
// records whether a task could be started - so this table never disagrees with the
// task list the console shows.
//
// Content only: the page renders it inside its "runs" tab, so the schedule name and
// cron are shown in the page's titlebar hint.
import { formatTime } from "../../utils/format"
import { getTaskStatusClass, getTaskStatusText } from "../../i18n"

const TRIGGER_LABEL_KEYS = {
  cron: "scheduleTriggerCron",
  manual: "scheduleTriggerManual",
}

function runState(run, translate) {
  if (run.status === "failed") {
    return { text: translate("scheduleRunFailed"), className: "failed" }
  }
  if (run.status === "skipped") {
    return { text: translate("scheduleRunSkipped"), className: "stopped" }
  }
  if (run.task_status) {
    return {
      text: getTaskStatusText(translate, run.task_status),
      className: getTaskStatusClass(run.task_status),
    }
  }
  return { text: translate("statusUnknown"), className: "running" }
}

export default function ScheduleRunsPanel({ schedule, runs, onOpenRun, translate }) {
  if (!schedule) {
    return <div className="empty">{translate("scheduleRunsSelectHint")}</div>
  }
  if (runs.length === 0) {
    return <div className="empty">{translate("scheduleRunsEmpty")}</div>
  }
  return (
    <div className="schedule-runs-wrap">
      <table className="schedule-runs">
        <thead>
          <tr>
            <th>{translate("scheduleRunsStartedAt")}</th>
            <th>{translate("scheduleRunsTrigger")}</th>
            <th>{translate("scheduleRunsStatus")}</th>
            <th>{translate("scheduleRunsTask")}</th>
            <th aria-label={translate("scheduleRunsOpen")} />
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const state = runState(run, translate)
            return (
              <tr key={run.run_id}>
                <td className="schedule-run-time">{formatTime(run.created_at)}</td>
                <td>{translate(TRIGGER_LABEL_KEYS[run.trigger] || "scheduleTriggerCron")}</td>
                <td>
                  <span className={`status ${state.className}`}>{state.text}</span>
                </td>
                <td className="schedule-run-task">
                  {run.task_id ? (
                    <span title={run.task_query || ""}>
                      {run.task_query || run.task_id.slice(0, 8)}
                    </span>
                  ) : (
                    <span className="schedule-run-error">{run.error}</span>
                  )}
                </td>
                <td>
                  {run.session_id ? (
                    <button
                      type="button"
                      className="btn btn-compact"
                      onClick={() => onOpenRun(run.session_id, run.task_id)}
                    >
                      {translate("scheduleRunsOpen")}
                    </button>
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
