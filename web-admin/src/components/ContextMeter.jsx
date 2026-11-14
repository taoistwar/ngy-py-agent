// How much of the model's context window the open session already uses.
//
// The reading comes from the backend's event log (the provider's own token counts),
// so it says what the next request will actually cost rather than what the text
// would estimate. A session nobody has asked anything in yet shows 0.
import { contextUsageLevel, formatContextPercent, formatTokenTotal } from "../utils/contextUsage"

export default function ContextMeter({ usage, translate }) {
  if (!usage) return null

  const used = Number(usage.used_tokens) || 0
  const max = Number(usage.max_tokens) || 0
  const percent = formatContextPercent(usage.percent)
  const title =
    usage.limit_source === "loop"
      ? translate("composerContextTitleLoop")
      : translate("composerContextTitle")

  return (
    <span
      className={`composer-context is-${contextUsageLevel(usage.percent)}`}
      title={title}
      aria-label={`${percent} ${formatTokenTotal(used)} / ${formatTokenTotal(max)} ${translate(
        "composerContextUsed",
      )}`}
    >
      {max > 0 ? `${percent} · ${formatTokenTotal(used)} / ${formatTokenTotal(max)}` : formatTokenTotal(used)}{" "}
      <span className="composer-context-label">{translate("composerContextUsed")}</span>
    </span>
  )
}
