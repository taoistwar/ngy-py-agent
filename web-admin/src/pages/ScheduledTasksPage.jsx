// The scheduled-task console: what is running now, the schedules themselves, and the
// run history of the one that is selected.
//
// The page polls on its own (it is not part of the shell's five-second refresh) so
// opening it costs nothing while it is closed, and "is it running yet" answers within
// one tick of a manual run.
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  createSchedule,
  deleteSchedule,
  fetchRunningSchedules,
  fetchScheduleRuns,
  fetchSchedules,
  runScheduleNow,
  updateSchedule,
} from "../api"
import { formatTime } from "../utils/format"
import RunningScheduleTasks from "../components/scheduled/RunningScheduleTasks"
import ScheduleForm from "../components/scheduled/ScheduleForm"
import ScheduleRunsPanel from "../components/scheduled/ScheduleRunsPanel"
import { permissionModeLabel } from "../components/scheduled/permissionOptions"

const REFRESH_MS = 5000
const RUNS_LIMIT = 50
// The form is closed, creating, or editing one id.
const FORM_CLOSED = ""
const FORM_NEW = "new"

export default function ScheduledTasksPage({
  agents,
  models,
  workspaces,
  onOpenRun,
  translate,
}) {
  const [schedules, setSchedules] = useState([])
  const [running, setRunning] = useState([])
  const [runs, setRuns] = useState([])
  const [selectedId, setSelectedId] = useState("")
  const [formMode, setFormMode] = useState(FORM_CLOSED)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  const selected = useMemo(
    () => schedules.find((item) => item.schedule_id === selectedId) || null,
    [schedules, selectedId]
  )
  const editing = useMemo(
    () => schedules.find((item) => item.schedule_id === formMode) || null,
    [formMode, schedules]
  )

  const refresh = useCallback(async () => {
    const [list, live] = await Promise.all([fetchSchedules(), fetchRunningSchedules()])
    setSchedules(list)
    setRunning(live)
    return list
  }, [])

  useEffect(() => {
    let cancelled = false
    const load = () => {
      refresh().catch((refreshError) => {
        if (!cancelled) setError(refreshError?.message || translate("errorLoadFailed"))
      })
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [refresh, translate])

  // The history belongs to the selected schedule and follows the same tick as the
  // list, so a run started by the scheduler appears without a page reload.
  useEffect(() => {
    if (!selectedId) {
      setRuns([])
      return undefined
    }
    let cancelled = false
    const load = () => {
      fetchScheduleRuns(selectedId, RUNS_LIMIT)
        .then((list) => {
          if (!cancelled) setRuns(list)
        })
        .catch(() => {
          // A failed history refresh must not replace the page with an error banner:
          // the list itself already reports a broken backend.
        })
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [selectedId])

  // Errors are re-thrown so the form can print them next to the field that caused
  // them instead of only in the page-wide banner.
  const submitForm = useCallback(
    async (payload) => {
      if (formMode === FORM_NEW) {
        const created = await createSchedule(payload)
        setFormMode(FORM_CLOSED)
        setSelectedId(created.schedule_id)
      } else {
        await updateSchedule(formMode, payload)
        setFormMode(FORM_CLOSED)
      }
      await refresh()
    },
    [formMode, refresh]
  )

  const toggleEnabled = useCallback(
    async (schedule) => {
      setBusy(schedule.schedule_id)
      setError("")
      try {
        await updateSchedule(schedule.schedule_id, { enabled: !schedule.enabled })
        await refresh()
      } catch (toggleError) {
        setError(toggleError?.message || translate("errorUnknown"))
      } finally {
        setBusy("")
      }
    },
    [refresh, translate]
  )

  const runNow = useCallback(
    async (schedule) => {
      setBusy(schedule.schedule_id)
      setError("")
      try {
        await runScheduleNow(schedule.schedule_id)
        setSelectedId(schedule.schedule_id)
        await refresh()
        // Selecting the same schedule again does not re-run the effect, so the fresh
        // attempt is read here; a different one is read by its own effect.
        setRuns(await fetchScheduleRuns(schedule.schedule_id, RUNS_LIMIT))
      } catch (runError) {
        setError(runError?.message || translate("errorUnknown"))
      } finally {
        setBusy("")
      }
    },
    [refresh, translate]
  )

  const remove = useCallback(
    async (schedule) => {
      if (!window.confirm(translate("scheduleDeleteConfirm"))) return
      setBusy(schedule.schedule_id)
      setError("")
      try {
        await deleteSchedule(schedule.schedule_id)
        if (selectedId === schedule.schedule_id) setSelectedId("")
        if (formMode === schedule.schedule_id) setFormMode(FORM_CLOSED)
        await refresh()
      } catch (deleteError) {
        setError(deleteError?.message || translate("errorUnknown"))
      } finally {
        setBusy("")
      }
    },
    [formMode, refresh, selectedId, translate]
  )

  return (
    <div className="schedule-page">
      <RunningScheduleTasks tasks={running} onOpenRun={onOpenRun} translate={translate} />

      <section className="panel">
        <div className="panel-titlebar">
          <div>
            <h2>{translate("schedulesTitle")}</h2>
            <span className="hint">{translate("schedulesHint")}</span>
          </div>
          <div className="schedule-titlebar-actions">
            <button
              type="button"
              className="btn btn-compact"
              onClick={() =>
                refresh().catch((refreshError) =>
                  setError(refreshError?.message || translate("errorLoadFailed"))
                )
              }
            >
              {translate("sidebarQuickRefresh")}
            </button>
            <button
              type="button"
              className="btn btn-primary btn-compact"
              onClick={() => {
                setError("")
                setFormMode(FORM_NEW)
              }}
            >
              {translate("scheduleNew")}
            </button>
          </div>
        </div>
        <div className="panel-body">
          {error ? <p className="form-error">{error}</p> : null}

          {formMode !== FORM_CLOSED ? (
            <ScheduleForm
              key={formMode}
              schedule={editing}
              agents={agents}
              models={models}
              workspaces={workspaces}
              onSubmit={submitForm}
              onCancel={() => setFormMode(FORM_CLOSED)}
              translate={translate}
            />
          ) : null}

          {schedules.length === 0 ? (
            <div className="empty">{translate("schedulesEmpty")}</div>
          ) : (
            <ul className="schedule-list">
              {schedules.map((schedule) => {
                const active = schedule.schedule_id === selectedId
                const working = busy === schedule.schedule_id
                return (
                  <li
                    key={schedule.schedule_id}
                    className={`schedule-card ${active ? "active" : ""}`}
                  >
                    <div
                      className="schedule-card-main"
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedId(schedule.schedule_id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault()
                          setSelectedId(schedule.schedule_id)
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
                        onClick={() => runNow(schedule)}
                      >
                        {translate("scheduleRunNow")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-compact"
                        disabled={working}
                        onClick={() => toggleEnabled(schedule)}
                      >
                        {translate(schedule.enabled ? "schedulePause" : "scheduleResume")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-compact"
                        onClick={() => {
                          setError("")
                          setFormMode(schedule.schedule_id)
                        }}
                      >
                        {translate("scheduleEdit")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-compact btn-danger"
                        disabled={working}
                        onClick={() => remove(schedule)}
                      >
                        {translate("scheduleDelete")}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </section>

      <ScheduleRunsPanel
        schedule={selected}
        runs={runs}
        onOpenRun={onOpenRun}
        translate={translate}
      />
    </div>
  )
}
