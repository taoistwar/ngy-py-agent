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
import { PlusIcon, RefreshIcon } from "../components/icons"
import RunningScheduleTasks from "../components/scheduled/RunningScheduleTasks"
import ScheduleForm from "../components/scheduled/ScheduleForm"
import ScheduleList from "../components/scheduled/ScheduleList"
import ScheduleRunsPanel from "../components/scheduled/ScheduleRunsPanel"

const REFRESH_MS = 5000
const RUNS_LIMIT = 50
// The form is closed, creating, or editing one id.
const FORM_CLOSED = ""
const FORM_NEW = "new"

// One panel, three views. "schedules" is the default: it is the tab that can create
// or edit a schedule, and the other two are read-only reports about those.
const TABS = [
  { key: "running", labelKey: "scheduleRunningTitle" },
  { key: "schedules", labelKey: "schedulesTitle" },
  { key: "runs", labelKey: "scheduleRunsTitle" },
]
const DEFAULT_TAB = "schedules"

// The tab strip carries the hint the old stacked panels each had in their titlebar.
function tabHintFor(activeTab, runningCount, selected, translate) {
  if (activeTab === "running") {
    return `${translate("scheduleRunningHint")} (${runningCount})`
  }
  if (activeTab === "runs") {
    // Nothing selected means the empty state below already explains it; repeating
    // the sentence in the titlebar would print it twice.
    return selected ? `${selected.name || translate("scheduleUnnamed")} - ${selected.cron}` : ""
  }
  return translate("schedulesHint")
}

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
  const [activeTab, setActiveTab] = useState(DEFAULT_TAB)

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

  // A card and its history are one click apart: the list switches the tab itself so
  // "select a schedule, then find the runs tab" is not a two-step guess.
  const showRuns = useCallback((schedule) => {
    setSelectedId(schedule.schedule_id)
    setActiveTab("runs")
  }, [])

  // The three views used to be stacked panels; they are tabs of one panel now, so
  // only the active one is mounted and the others stop costing layout space.
  const tabHint = tabHintFor(activeTab, running.length, selected, translate)

  return (
    <div className="schedule-page">
      <section className="panel schedule-panel">
        <div className="panel-titlebar">
          <div className="schedule-tabbar">
            <div className="tab-strip" role="tablist" aria-label={translate("scheduleTabAria")}>
              {TABS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  aria-selected={item.key === activeTab}
                  className={`tab-btn ${item.key === activeTab ? "active" : ""}`}
                  onClick={() => setActiveTab(item.key)}
                >
                  {translate(item.labelKey)}
                </button>
              ))}
            </div>
            <span className="hint">{tabHint}</span>
          </div>
          {activeTab === "schedules" ? (
            <div className="schedule-titlebar-actions">
              <button
                type="button"
                className="icon-btn"
                title={translate("sidebarQuickRefresh")}
                aria-label={translate("sidebarQuickRefresh")}
                onClick={() =>
                  refresh().catch((refreshError) =>
                    setError(refreshError?.message || translate("errorLoadFailed"))
                  )
                }
              >
                <RefreshIcon />
              </button>
              <button
                type="button"
                className="icon-btn icon-btn-accent"
                title={translate("scheduleNew")}
                aria-label={translate("scheduleNew")}
                onClick={() => {
                  setError("")
                  setFormMode(FORM_NEW)
                }}
              >
                <PlusIcon />
              </button>
            </div>
          ) : null}
        </div>
        <div className="panel-body">
          {/* The banner sits above the tabs' content: a broken backend is not a
              property of the one tab that happened to trigger the request. */}
          {error ? <p className="form-error">{error}</p> : null}

          {activeTab === "running" ? (
            <RunningScheduleTasks tasks={running} onOpenRun={onOpenRun} translate={translate} />
          ) : null}

          {activeTab === "schedules" ? (
            <>
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
              <ScheduleList
                schedules={schedules}
                selectedId={selectedId}
                busy={busy}
                onSelect={setSelectedId}
                onShowRuns={showRuns}
                onRun={runNow}
                onToggle={toggleEnabled}
                onEdit={(schedule) => {
                  setError("")
                  setFormMode(schedule.schedule_id)
                }}
                onDelete={remove}
                translate={translate}
              />
            </>
          ) : null}

          {activeTab === "runs" ? (
            <ScheduleRunsPanel
              schedule={selected}
              runs={runs}
              onOpenRun={onOpenRun}
              translate={translate}
            />
          ) : null}
        </div>
      </section>
    </div>
  )
}
