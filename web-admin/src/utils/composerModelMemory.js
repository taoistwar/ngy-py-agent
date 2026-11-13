// Remembering which model the task composer's picker is set to.
//
// Two scopes are kept in localStorage, mirroring the composer draft:
//   * session:   the choice made in one conversation;
//   * workspace: the last choice made anywhere in a workspace, which is what a
//                brand new session of that workspace starts from.
// The session scope wins, so switching back to a conversation restores the model
// it was last used with instead of the workspace default.

const SESSION_MODEL_KEY_PREFIX = "web-admin.composerModel.session."
const WORKSPACE_MODEL_KEY_PREFIX = "web-admin.composerModel.workspace."

function readStoredModel(key) {
  if (typeof window === "undefined" || !key) return ""
  try {
    return window.localStorage.getItem(key) || ""
  } catch {
    return ""
  }
}

function writeStoredModel(key, modelId) {
  if (typeof window === "undefined" || !key) return
  try {
    if (modelId) {
      window.localStorage.setItem(key, modelId)
    } else {
      // No pick is not the same as picking "" - drop the key.
      window.localStorage.removeItem(key)
    }
  } catch {
    // ignore persistence errors
  }
}

export function sessionModelKey(sessionId) {
  return sessionId ? `${SESSION_MODEL_KEY_PREFIX}${sessionId}` : ""
}

export function workspaceModelKey(workspaceId) {
  return workspaceId ? `${WORKSPACE_MODEL_KEY_PREFIX}${workspaceId}` : ""
}

// A session without a pick of its own inherits the workspace's last pick, which
// is how a freshly opened session gets the model the workspace was using. An
// unknown session in an unknown workspace yields "" (the caller then falls back
// to the first model of the list).
export function loadRememberedModel(sessionId, workspaceId) {
  return (
    readStoredModel(sessionModelKey(sessionId)) || readStoredModel(workspaceModelKey(workspaceId))
  )
}

// An explicit pick is written to both scopes: the session keeps its own choice
// and the workspace remembers it as the latest choice made in it.
export function saveRememberedModel(sessionId, workspaceId, modelId) {
  writeStoredModel(sessionModelKey(sessionId), modelId)
  writeStoredModel(workspaceModelKey(workspaceId), modelId)
}

// A remembered model can disappear from the list (deleted model, renamed
// provider). The picker then falls back to the first available model instead of
// rendering an empty selection.
export function resolveModelId(models, rememberedModelId) {
  if (!models || models.length === 0) return ""
  if (rememberedModelId && models.some((item) => item.model_id === rememberedModelId)) {
    return rememberedModelId
  }
  return models[0].model_id
}
