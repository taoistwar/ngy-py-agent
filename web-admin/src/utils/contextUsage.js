// The composer's context meter: how much of the model window this session already
// uses, in the shape CodeBuddy shows next to its input ("0.0% · 0 / 256.0K ...").

// Token counts are binary, like the model manager's presets: a 262144-token window
// reads as "256.0K", which is the number the user configured.
export function formatTokenTotal(value) {
  const count = Math.max(0, Math.round(Number(value) || 0))
  if (count >= 1024 * 1024) return `${(count / (1024 * 1024)).toFixed(1)}M`
  if (count >= 1024) return `${(count / 1024).toFixed(1)}K`
  return String(count)
}

// One decimal, always: "0.0%" says "nothing yet" more clearly than "0%".
export function formatContextPercent(value) {
  const percent = Number(value)
  if (!Number.isFinite(percent) || percent <= 0) return "0.0%"
  return `${percent.toFixed(1)}%`
}

// The meter turns red before the provider refuses a request, not after.
export function contextUsageLevel(percent) {
  const value = Number(percent) || 0
  if (value >= 95) return "danger"
  if (value >= 80) return "warn"
  return "normal"
}
