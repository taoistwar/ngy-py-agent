export function getHealthClass(healthStatus) {
  if (healthStatus === "ok") return "success"
  if (healthStatus === "unavailable") return "failed"
  return "running"
}

export function getHealthText(healthStatus, translate) {
  if (healthStatus === "ok") return translate("healthOk")
  if (healthStatus === "unavailable") return translate("healthUnavailable")
  if (healthStatus === "degraded") return translate("statusDegraded")
  return translate("unknown")
}
