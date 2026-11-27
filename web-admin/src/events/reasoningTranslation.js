import { useCallback, useEffect, useRef, useState } from "react"

import { fetchReasoningTranslations, translateTaskReasoning } from "../api"
import { isTaskRunningStatus } from "../i18n"

const NO_ITEMS = {}

// The server rejects the manual action with this phrasing when no model is set, so a
// model removed between the page load and the click still opens the "configure" dialog.
const NO_MODEL_MARKER = "translation model"

// The pass runs on a server thread (a task can carry dozens of traces, each at least
// one model call). Until it reports done, the log reads back what it has so far.
const POLL_INTERVAL_MS = 1500

// Notices the toolbar shows for a moment; translation states are not log entries.
const TRANSLATE_STARTED = "eventsTranslateStarted"
const TRANSLATE_WORKING = "eventsTranslateWorking"
const TRANSLATE_DONE = "eventsTranslateDone"
const TRANSLATE_EMPTY = "eventsTranslateEmpty"
const TRANSLATE_DEFERRED = "eventsTranslateDeferred"

/**
 * The translated deep-think traces of the selected task, for the console's language.
 *
 * Translations live on the server, keyed by event and language, so they survive a
 * reload and are shared by every browser. This hook only decides *when* to ask:
 *
 * - opening a task reads what is already stored (no model call);
 * - a task that has just finished is translated once, when a model is configured;
 * - the log's manual action asks for whatever is still missing, answers at once
 *   ("a pass started") and then polls until the pass is done.
 *
 * @param {{task: object|null, locale: string, enabled: boolean,
 *          onError?: (message: string) => void}} options
 */
export function useReasoningTranslation({ task, locale, enabled, onError }) {
  const taskId = task?.task_id || ""
  const running = isTaskRunningStatus(task?.status)
  const [state, setState] = useState({ taskId: "", locale: "", items: NO_ITEMS, running: false })
  const [noticeKey, setNoticeKey] = useState("")
  const [needsModel, setNeedsModel] = useState(false)
  // Which task+language the automatic pass already asked for: a poll re-renders this
  // hook every second and must not become a second request.
  const autoKeyRef = useRef("")
  // Whether the pass in flight was asked for by a click. An automatic pass fills the
  // log silently; only a click has to report that it started and how it ended.
  const manualRef = useRef(false)

  const inScope = state.taskId === taskId && state.locale === locale
  const items = inScope ? state.items : NO_ITEMS
  const translating = inScope && state.running

  const merge = useCallback((targetTaskId, targetLocale, incoming, flags = {}) => {
    setState((prev) => {
      const sameScope = prev.taskId === targetTaskId && prev.locale === targetLocale
      return {
        taskId: targetTaskId,
        locale: targetLocale,
        items: { ...(sameScope ? prev.items : NO_ITEMS), ...incoming },
        running: flags.running ?? (sameScope ? prev.running : false),
      }
    })
  }, [])

  const reportNoModel = useCallback(
    (error) => {
      const message = String(error?.message || "")
      if (message.toLowerCase().includes(NO_MODEL_MARKER)) {
        setNeedsModel(true)
        return
      }
      onError?.(message)
    },
    [onError],
  )

  // Stored translations only: opening a 100-step task must not start 100 model calls.
  useEffect(() => {
    if (!taskId || !enabled) return undefined
    let alive = true
    fetchReasoningTranslations(taskId, locale)
      .then((payload) => {
        if (!alive) return
        // A pass another tab already started: follow it, but report it as what it is
        // (a running pass), not as something this click caused.
        merge(taskId, locale, payload?.items || {}, { running: Boolean(payload?.running) })
      })
      // A failed read is not worth a page-level error: the log simply shows originals.
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [taskId, locale, enabled, merge])

  useEffect(() => {
    if (!enabled || !taskId || running) return undefined
    const key = `${taskId}|${locale}`
    if (autoKeyRef.current === key) return undefined
    autoKeyRef.current = key
    manualRef.current = false
    translateTaskReasoning(taskId, locale)
      .then((payload) =>
        merge(taskId, locale, payload?.items || {}, { running: Boolean(payload?.running) }),
      )
      // The finished task stays readable; only the translation is missing. A model
      // deleted since the page loaded is reported where the user can act on it.
      .catch(reportNoModel)
    return undefined
  }, [enabled, taskId, running, locale, merge, reportNoModel])

  // The pass is done when the reader endpoint stops running: say how it went, but only
  // when the reader asked for it. A silent automatic pass finishing is not news.
  const finish = useCallback((payload) => {
    if (!manualRef.current) return
    manualRef.current = false
    if (Number(payload?.deferred || 0) > 0) setNoticeKey(TRANSLATE_DEFERRED)
    else if (Number(payload?.translated || 0) > 0) setNoticeKey(TRANSLATE_DONE)
    else setNoticeKey(TRANSLATE_EMPTY)
  }, [])

  useEffect(() => {
    if (!translating || !taskId) return undefined
    let alive = true
    const timer = setInterval(() => {
      fetchReasoningTranslations(taskId, locale)
        .then((payload) => {
          if (!alive) return
          merge(taskId, locale, payload?.items || {}, { running: Boolean(payload?.running) })
          if (!payload?.running) finish(payload)
        })
        // One failed read says nothing about the pass; the next tick asks again.
        .catch(() => {})
    }, POLL_INTERVAL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [translating, taskId, locale, merge, finish])

  const translateNow = useCallback(async () => {
    if (!enabled) {
      setNeedsModel(true)
      return null
    }
    if (!taskId) return null
    manualRef.current = true
    try {
      const payload = await translateTaskReasoning(taskId, locale)
      merge(taskId, locale, payload?.items || {}, { running: Boolean(payload?.running) })
      // The answer comes before the work: say so, the poll fills the log in.
      setNoticeKey(payload?.started === false ? TRANSLATE_WORKING : TRANSLATE_STARTED)
      if (!payload?.running) finish(payload)
      return payload
    } catch (error) {
      manualRef.current = false
      reportNoModel(error)
      return null
    }
  }, [enabled, taskId, locale, merge, finish, reportNoModel])

  const dismissNeedsModel = useCallback(() => setNeedsModel(false), [])

  // Switching task or language drops the note: it described the previous panel.
  useEffect(() => {
    setNoticeKey("")
  }, [taskId, locale])

  // A finished note is a status line, not a log entry; it goes away on its own.
  useEffect(() => {
    if (!noticeKey || noticeKey === TRANSLATE_STARTED || noticeKey === TRANSLATE_WORKING) {
      return undefined
    }
    const timer = setTimeout(() => setNoticeKey(""), 8000)
    return () => clearTimeout(timer)
  }, [noticeKey])

  return {
    items,
    hasTranslation: Object.keys(items).length > 0,
    translating,
    translateNow,
    noticeKey,
    needsModel,
    dismissNeedsModel,
  }
}
