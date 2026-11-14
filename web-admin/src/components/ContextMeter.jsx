// How much of the model's context window the open session already uses, as a ring
// that fills up (CodeBuddy's shape next to the send button) plus a hover panel with
// the numbers behind it.
//
// The reading comes from the backend's event log (the provider's own token counts),
// so it says what the next request will actually cost rather than what the text
// would estimate. A session nobody has asked anything in yet shows an empty ring.
import { contextUsageLevel, formatContextPercent, formatTokenTotal } from "../utils/contextUsage"

// An 18px ring: four units of radius leave room for the stroke without clipping.
const RING_SIZE = 18
const RING_STROKE = 2.5
const RING_CENTER = RING_SIZE / 2
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

export default function ContextMeter({ usage, translate }) {
  if (!usage) return null

  const used = Number(usage.used_tokens) || 0
  const input = Number(usage.input_tokens) || 0
  const output = Number(usage.output_tokens) || 0
  const max = Number(usage.max_tokens) || 0
  const hasLimit = max > 0
  const filled = hasLimit ? Math.min(100, Math.max(0, Number(usage.percent) || 0)) : 0
  const dash = (RING_CIRCUMFERENCE * filled) / 100
  const percentText = hasLimit ? formatContextPercent(usage.percent) : ""
  const limitLabel =
    usage.limit_source === "loop"
      ? translate("composerContextLimitLoop")
      : translate("composerContextLimitModel")
  const reading = [percentText, formatTokenTotal(used), hasLimit ? formatTokenTotal(max) : ""]
    .filter(Boolean)
    .join(" ")

  return (
    <span
      className={`composer-context is-${contextUsageLevel(filled)}`}
      tabIndex={0}
      role="img"
      aria-label={`${reading} ${translate("composerContextUsed")}`}
    >
      <svg className="composer-context-ring" viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}>
        <circle
          className="composer-context-track"
          cx={RING_CENTER}
          cy={RING_CENTER}
          r={RING_RADIUS}
          fill="none"
          strokeWidth={RING_STROKE}
        />
        {dash > 0 && (
          <circle
            className="composer-context-fill"
            cx={RING_CENTER}
            cy={RING_CENTER}
            r={RING_RADIUS}
            fill="none"
            strokeWidth={RING_STROKE}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${RING_CIRCUMFERENCE}`}
            transform={`rotate(-90 ${RING_CENTER} ${RING_CENTER})`}
          />
        )}
      </svg>

      <span className="composer-context-tip" role="tooltip">
        <span className="composer-context-tip-head">
          <span>{translate("composerContextUsed")}</span>
          {percentText && <strong>{percentText}</strong>}
        </span>
        <span className="composer-context-tip-number">
          {hasLimit
            ? `${formatTokenTotal(used)} / ${formatTokenTotal(max)}`
            : formatTokenTotal(used)}
        </span>
        <span className="composer-context-tip-detail">
          {translate("composerContextInput")} {formatTokenTotal(input)} ·{" "}
          {translate("composerContextOutput")} {formatTokenTotal(output)}
        </span>
        <span className="composer-context-tip-detail">
          {translate("composerContextLimit")} {limitLabel}
          {usage.model_name ? ` · ${usage.model_name}` : ""}
        </span>
      </span>
    </span>
  )
}
