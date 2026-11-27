// The confirmation modes a schedule may pin to its runs.
//
// Empty is not in the list because it is not a mode: it means "follow the global
// setting", and the backend stores that as an empty column.
export const PERMISSION_MODE_LABEL_KEYS = {
  ask: "permissionModeAsk",
  auto_approve: "permissionModeAuto",
  deny_all: "permissionModeDenyAll",
}

export const PERMISSION_MODE_VALUES = Object.keys(PERMISSION_MODE_LABEL_KEYS)

export function permissionModeLabel(translate, mode) {
  const key = PERMISSION_MODE_LABEL_KEYS[mode]
  // An unknown value (a hand-edited row) is shown as itself rather than as a blank.
  return key ? translate(key) : mode
}
