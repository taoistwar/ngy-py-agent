// Agent icon set shared by the agent editor, the agent table and the task composer.
//
// The backend stores only an icon *key* (``agents.icon``), so every surface renders
// the same glyph for an agent without shipping an image per record.

import { Icon } from "./icons"

export const DEFAULT_AGENT_ICON = "bot"

// Built-in agents get an icon even when the row predates the ``icon`` column.
const BUILTIN_AGENT_ICONS = {
  build: "wrench",
  ask: "message",
  plan: "clipboard",
}

export const AGENT_ICON_KEYS = [
  "wrench",
  "message",
  "clipboard",
  "bot",
  "sparkles",
  "zap",
  "search",
  "code",
]

export const AGENT_LIBRARY_ICONS = {
  wrench: (
    <Icon>
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z" />
    </Icon>
  ),
  message: (
    <Icon>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </Icon>
  ),
  clipboard: (
    <Icon>
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <rect x="8" y="2" width="8" height="4" rx="1" />
    </Icon>
  ),
  bot: (
    <Icon>
      <rect x="4" y="8" width="16" height="12" rx="2" />
      <line x1="12" y1="4" x2="12" y2="8" />
      <circle cx="12" cy="3" r="1" />
      <line x1="9" y1="13" x2="9" y2="16" />
      <line x1="15" y1="13" x2="15" y2="16" />
    </Icon>
  ),
  sparkles: (
    <Icon>
      <path d="M10 3l1.7 4.3L16 9l-4.3 1.7L10 15l-1.7-4.3L4 9l4.3-1.7z" />
      <line x1="18" y1="14" x2="18" y2="20" />
      <line x1="15" y1="17" x2="21" y2="17" />
    </Icon>
  ),
  zap: (
    <Icon>
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </Icon>
  ),
  search: (
    <Icon>
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </Icon>
  ),
  code: (
    <Icon>
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </Icon>
  ),
}

/** Icon key to render for ``agent``; falls back to the built-in or default icon. */
export function agentIconName(agent) {
  if (!agent) return DEFAULT_AGENT_ICON
  if (agent.icon && AGENT_LIBRARY_ICONS[agent.icon]) return agent.icon
  return BUILTIN_AGENT_ICONS[agent.agent_id] || DEFAULT_AGENT_ICON
}

export function AgentIcon({ name, className }) {
  const glyph = AGENT_LIBRARY_ICONS[name] || AGENT_LIBRARY_ICONS[DEFAULT_AGENT_ICON]
  return (
    <span className={`agent-icon ${className || ""}`.trim()} aria-hidden="true">
      {glyph}
    </span>
  )
}
