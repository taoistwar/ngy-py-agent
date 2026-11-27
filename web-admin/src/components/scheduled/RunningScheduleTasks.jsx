// What the schedules are doing right now. A scheduled run can be parked on a tool
// confirmation ("waiting"), which is exactly when somebody has to see it.
import { formatTime } from "../../utils/format"
import { getTaskStatusClass, getTaskStatusText } from "../../i18n"

export default function RunningScheduleTasks({ tasks, onOpenRun, translate }) {
  return (
    <section className="panel">
      <div className="panel-titlebar">
        <div>
          <h2>{translate("scheduleRunningTitle")}</h2>
          <span className="hint">
            {translate("scheduleRunningHint")} ({tasks.length})
          </span>
        </div>
      </div>
      <div className="panel-body">
        {tasks.length === 0 ? (
          <div className="empty">{translate("scheduleRunningEmpty")}</div>
        ) : (
          <ul className="schedule-running-list">
            {tasks.map((task) => (
              <li key={task.run_id} className="schedule-running-row">
                <div className="schedule-running-main">
                  <div className="schedule-running-head">
                    <strong>{task.schedule_name || translate("scheduleUnnamed")}</strong>
                    <span className={`status ${getTaskStatusClass(task.task_status)}`}>
                      {getTaskStatusText(translate, task.task_status)}
                    </span>
                  </div>
                  <span className="schedule-running-query" title={task.task_query || ""}>
                    {task.task_query || ""}
                  </span>
                  <span className="hint">{formatTime(task.created_at)}</span>
                </div>
                <button
                  type="button"
                  className="btn btn-compact"
                  onClick={() => onOpenRun(task.session_id, task.task_id)}
                >
                  {translate("scheduleRunsOpen")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
