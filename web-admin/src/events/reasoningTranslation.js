import { useCallback, useEffect, useRef, useState } from "react"

import { fetchReasoningTranslations, translateTaskReasoning } from "../api"
import { isTaskRunningStatus } from "../i18n"

const NO_ITEMS = {}

// The server rejects the manual action with this phrasing when no model is set, so a
// model removed between the page load and the click still opens the "configure" dialog.
const NO_MODEL_MARKER = "translation model"

/**
 * The translated deep-think traces of the selected task, for the console's language.
 *
 * Translations live on the server, keyed by event and language, so they survive a
 * reload and are shared by every browser. This hook only decides *when* to ask:
 *
 * - opening a task reads what is already stored (no model call);
 * - a task that has just finished is translated once, when a model is configured;
 * - the log's manual action asks for whatever is still missing.
 *
 * @param {{task: object|null, locale: string, enabled: boolean,
 *          onError?: (message: string) => void}} options
 */
export function useReasoningTranslation({ task, locale, enabled, onError }) {
  const taskId = task?.task_id || ""
  const running = isTaskRunningStatus(task?.status)
  const [state, setState] = useState({ taskId: "", locale: "", items: NO_ITEMS })
  const [busy, setBusy] = useState(false)
  const [needsModel, setNeedsModel] = useState(false)
  // Which task+language the automatic pass already ran for: a poll re-renders this
  // hook every second and must not become a second translation request.
  const autoKeyRef = useRef("")

  const items =
    state.taskId === taskId && state.locale === locale ? state.items : NO_ITEMS

  const merge = useCallback((targetTaskId, targetLocale, incoming) => {
    setState((prev) => {
      const sameScope = prev.taskId === targetTaskId && prev.locale === targetLocale
      return {
        taskId: targetTaskId,
        locale: targetLocale,
        items: { ...(sameScope ? prev.items : NO_ITEMS), ...incoming },
      }
    })
  }, [])

  const reportNoModel = useCallback((error) => {
    const message = String(error?.message || "")
    if (message.toLowerCase().includes(NO_MODEL_MARKER)) {
      setNeedsModel(true)
      return
    }
    onError?.(message)
  }, [onError])

  // Stored translations only: opening a 100-step task must not start 100 model calls.
  useEffect(() => {
    if (!taskId || !enabled) return undefined
    let alive = true
    fetchReasoningTranslations(taskId, locale)
      .then((payload) => {
        if (alive) merge(taskId, locale, payload?.items || {})
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
    translateTaskReasoning(taskId, locale)
      .then((payload) => merge(taskId, locale, payload?.items || {}))
      // The finished task stays readable; only the translation is missing. A model
      // deleted since the page loaded is reported where the user can act on it.
      .catch(reportNoModel)
    return undefined
  }, [enabled, taskId, running, locale, merge, reportNoModel])

  const translateNow = useCallback(async () => {
    if (!enabled) {
      setNeedsModel(true)
      return null
    }
    if (!taskId) return null
    setBusy(true)
    try {
      const payload = await translateTaskReasoning(taskId, locale)
      merge(taskId, locale, payload?.items || {})
      return payload
    } catch (error) {
      reportNoModel(error)
      return null
    } finally {
      setBusy(false)
    }
  }, [enabled, taskId, locale, merge, reportNoModel])

  const dismissNeedsModel = useCallback(() => setNeedsModel(false), [])

  return {
    items,
    hasTranslation: Object.keys(items).length > 0,
    busy,
    translateNow,
    needsModel,
    dismissNeedsModel,
  }
}
