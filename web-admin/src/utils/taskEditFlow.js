// Replacing a turn from the list: editing a row refills the composer, re-running
// replays the row's own content. Both start by removing the clicked turn and every
// turn that ran after it in the same session - a task is built from the session's
// transcript, so a later turn would otherwise be replayed as context for the new
// one (and, when every turn is dropped, the session's history is empty again).
//
// "Replace" is three steps, in this order:
//   1. the turn is undone (its file changes are reverted) and deleted, so the replay
//      starts from a clean workspace;
//   2. the turns created after it in the same session are deleted too;
//   3. the caller creates a task from the edited/replayed content.

import { deleteTask, fetchTasks, revertAndDeleteTask, stopTask } from "../api"
import { isTaskRunningStatus } from "../i18n"

// What the composer is filled with when "edit" is clicked on a row. An agent or a
// model that no longer exists is left out, so the composer keeps its own default
// instead of selecting something that cannot run.
export function buildTaskEditDraft(task, { agents = [], models = [] } = {}) {
  const agentKnown = agents.some((item) => item.agent_id === task.mode)
  const modelKnown = models.some((item) => item.model_id === task.model_id)
  return {
    taskId: task.task_id,
    query: task.query || "",
    agentId: agentKnown ? task.mode : "",
    modelId: modelKnown ? task.model_id : "",
  }
}

// Ids of the session's turns that came after ``taskId``, in the order they ran.
function turnIdsAfter(sessionTasks, taskId) {
  const index = sessionTasks.findIndex((item) => item.task_id === taskId)
  if (index < 0) return []
  return sessionTasks.slice(index + 1).map((item) => item.task_id)
}

// The composer carries the row it was filled from as ``taskId``; a task read from
// the API calls the same thing ``task_id``.
function taskIdOf(task) {
  return task?.task_id || task?.taskId || ""
}

// Delete ``task`` and every turn after it in the same session. A turn that is still
// running is stopped first: deleting a live task would leave its thread appending
// events to a record that no longer exists.
//
// Returns ``{deleted, blocked, removed}``. ``deleted: false`` means the undo hit a
// conflict and the task was kept - its undo dialog is the only place those files can
// be settled - so nothing at all is deleted.
export async function truncateSessionFromTask(task, sessionId) {
  const taskId = taskIdOf(task)
  if (!taskId) return { deleted: false, blocked: [], removed: [] }

  // Read the list before anything is removed: the turns to drop are only known by
  // their position relative to this one.
  const sessionTasks = sessionId ? await fetchTasks(sessionId) : []
  const laterIds = turnIdsAfter(sessionTasks, taskId)

  const result = await revertAndDeleteTask(taskId)
  if (!result.deleted) {
    return { deleted: false, blocked: result.blocked, removed: [] }
  }

  const removed = [taskId]
  for (const laterId of laterIds) {
    const later = sessionTasks.find((item) => item.task_id === laterId)
    if (later && isTaskRunningStatus(later.status)) {
      // A failed stop still lets the delete through: the record is what matters,
      // and the thread cannot outlive it for long.
      await stopTask(laterId).catch(() => {})
    }
    await deleteTask(laterId)
    removed.push(laterId)
  }

  return { deleted: true, blocked: [], removed }
}
