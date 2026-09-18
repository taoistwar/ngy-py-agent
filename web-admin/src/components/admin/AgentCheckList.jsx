// Generic checkable list (one row per item) used by the agent tool / skill pickers.

export default function AgentCheckList({
  items,
  selectedIds,
  disabled,
  onToggle,
  onShowDetail,
  emptyLabel,
  detailLabel,
  fallbackDescription,
}) {
  if (items.length === 0) {
    return <p className="hint">{emptyLabel}</p>
  }

  return (
    <div className="agent-check-list">
      {items.map((item) => (
        <div className="agent-check-row" key={item.id}>
          <label className="checkbox-label agent-check-check">
            <input
              type="checkbox"
              disabled={disabled}
              checked={disabled || selectedIds.includes(item.id)}
              onChange={() => onToggle(item.id)}
            />
          </label>
          <div className="agent-check-body">
            <span className="agent-check-head">
              <span className="agent-check-title">{item.title}</span>
              {item.badge ? (
                <span className={`badge ${item.badgeClass || "badge-builtin"}`}>{item.badge}</span>
              ) : null}
            </span>
            <span className="agent-check-desc">{item.description || fallbackDescription}</span>
          </div>
          <button type="button" className="btn btn-xs" onClick={() => onShowDetail(item)}>
            {detailLabel}
          </button>
        </div>
      ))}
    </div>
  )
}
