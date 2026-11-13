// Shared inline stroke icons (Feather-style) used by the icon-only buttons.

export function Icon({ children }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

export function RefreshIcon() {
  return (
    <Icon>
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </Icon>
  )
}

export function RerunIcon() {
  return (
    <Icon>
      <polyline points="1 4 1 10 7 10" />
      <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
    </Icon>
  )
}

export function SkillIcon() {
  return (
    <Icon>
      <path d="M10 3l1.7 4.3L16 9l-4.3 1.7L10 15l-1.7-4.3L4 9l4.3-1.7z" />
      <line x1="18" y1="14" x2="18" y2="20" />
      <line x1="15" y1="17" x2="21" y2="17" />
    </Icon>
  )
}

export function UndoIcon() {
  return (
    <Icon>
      <polyline points="9 14 4 9 9 4" />
      <path d="M4 9h9a6 6 0 0 1 0 12h-3" />
    </Icon>
  )
}

export function TrashIcon() {
  return (
    <Icon>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </Icon>
  )
}

export function ExternalLinkIcon() {
  return (
    <Icon>
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </Icon>
  )
}

export function ExpandIcon() {
  return (
    <Icon>
      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
      <path d="M16 3h3a2 2 0 0 1 2 2v3" />
      <path d="M21 16v3a2 2 0 0 1-2 2h-3" />
      <path d="M3 16v3a2 2 0 0 0 2 2h3" />
    </Icon>
  )
}

export function CloseIcon() {
  return (
    <Icon>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </Icon>
  )
}

export function ChevronsUpIcon() {
  return (
    <Icon>
      <polyline points="17 11 12 6 7 11" />
      <polyline points="17 18 12 13 7 18" />
    </Icon>
  )
}

export function ChevronsDownIcon() {
  return (
    <Icon>
      <polyline points="7 13 12 18 17 13" />
      <polyline points="7 6 12 11 17 6" />
    </Icon>
  )
}

export function SunIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="4" />
      <line x1="12" y1="2" x2="12" y2="4" />
      <line x1="12" y1="20" x2="12" y2="22" />
      <line x1="4.93" y1="4.93" x2="6.34" y2="6.34" />
      <line x1="17.66" y1="17.66" x2="19.07" y2="19.07" />
      <line x1="2" y1="12" x2="4" y2="12" />
      <line x1="20" y1="12" x2="22" y2="12" />
      <line x1="4.93" y1="19.07" x2="6.34" y2="17.66" />
      <line x1="17.66" y1="6.34" x2="19.07" y2="4.93" />
    </Icon>
  )
}

export function MoonIcon() {
  return (
    <Icon>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </Icon>
  )
}

// Navigation icons. Keep them geometric and stroke-only so the sidebar reads as
// one family regardless of the active skin.

export function OverviewIcon() {
  return (
    <Icon>
      <rect x="3" y="3" width="7" height="7" rx="1.6" />
      <rect x="14" y="3" width="7" height="7" rx="1.6" />
      <rect x="3" y="14" width="7" height="7" rx="1.6" />
      <rect x="14" y="14" width="7" height="7" rx="1.6" />
    </Icon>
  )
}

export function TasksIcon() {
  return (
    <Icon>
      <path d="M9 6h12M9 12h12M9 18h12" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" />
    </Icon>
  )
}

export function FolderIcon() {
  return (
    <Icon>
      <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v7.5A1.5 1.5 0 0 1 17.5 19h-13A1.5 1.5 0 0 1 3 17.5z" />
    </Icon>
  )
}

export function BotIcon() {
  return (
    <Icon>
      <rect x="4" y="7" width="16" height="12" rx="3" />
      <path d="M12 3v4M9 13h.01M15 13h.01M9.5 16.5h5" />
    </Icon>
  )
}

export function WrenchIcon() {
  return (
    <Icon>
      <path d="M14.5 6.5a4 4 0 0 1 5 5L9 22l-4-4 10.5-11.5z" />
      <path d="M3 3l4 4" />
    </Icon>
  )
}

export function PlugIcon() {
  return (
    <Icon>
      <path d="M9 3v6M15 3v6" />
      <path d="M6 9h12v3a6 6 0 0 1-12 0z" />
      <path d="M12 18v3" />
    </Icon>
  )
}

export function CpuIcon() {
  return (
    <Icon>
      <rect x="6" y="6" width="12" height="12" rx="2.5" />
      <path d="M10 10h4v4h-4zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
    </Icon>
  )
}

export function ServerIcon() {
  return (
    <Icon>
      <rect x="3" y="4" width="18" height="6" rx="2" />
      <rect x="3" y="14" width="18" height="6" rx="2" />
      <path d="M7 7h.01M7 17h.01" />
    </Icon>
  )
}

export function ShieldCheckIcon() {
  return (
    <Icon>
      <path d="M12 21s7.5-3.6 7.5-9.4V5.6L12 3 4.5 5.6v6c0 5.8 7.5 9.4 7.5 9.4z" />
      <path d="M9 11.8l2 2 4-4.2" />
    </Icon>
  )
}

export function SettingsIcon() {
  return (
    <Icon>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </Icon>
  )
}

export function ChevronIcon() {
  return (
    <Icon>
      <polyline points="6 9 12 15 18 9" />
    </Icon>
  )
}

export function SearchIcon() {
  return (
    <Icon>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </Icon>
  )
}

export function SidebarIcon({ collapsed = false }) {
  return (
    <Icon>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <path d="M9 4v16" />
      {collapsed ? <path d="M13 9l3 3-3 3" /> : <path d="M16 9l-3 3 3 3" />}
    </Icon>
  )
}
