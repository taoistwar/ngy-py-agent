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
