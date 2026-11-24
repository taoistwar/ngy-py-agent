// Single source of truth for the console information architecture. The sidebar
// renders this tree; the top bar derives its breadcrumb from the same data.
import {
  BotIcon,
  CpuIcon,
  FolderIcon,
  OverviewIcon,
  PlugIcon,
  ServerIcon,
  SettingsIcon,
  ShieldCheckIcon,
  ShieldOffIcon,
  SkillIcon,
  TasksIcon,
  WrenchIcon,
} from "../icons"

export const DEFAULT_MENU = "overview"

export const NAV_GROUPS = [
  {
    key: "workspace",
    labelKey: "navGroupWorkspace",
    items: [
      { key: "overview", labelKey: "menuOverview", icon: "overview" },
      { key: "tasks", labelKey: "menuTasks", icon: "tasks" },
      { key: "workspaces", labelKey: "menuWorkspaces", icon: "folder" },
    ],
  },
  {
    key: "build",
    labelKey: "navGroupBuild",
    items: [
      { key: "agents", labelKey: "menuAgents", icon: "bot" },
      { key: "tools", labelKey: "menuTools", icon: "wrench" },
      { key: "skills", labelKey: "menuSkills", icon: "skill" },
      { key: "mcp", labelKey: "menuMcp", icon: "plug" },
    ],
  },
  {
    key: "models",
    labelKey: "navGroupModels",
    items: [
      { key: "models", labelKey: "menuModels", icon: "cpu" },
      { key: "providers", labelKey: "menuProviders", icon: "server" },
    ],
  },
  {
    key: "system",
    labelKey: "navGroupSystem",
    items: [
      { key: "config", labelKey: "menuConfig", icon: "settings" },
      { key: "permissions", labelKey: "menuPermissionRules", icon: "shield" },
      { key: "denylist", labelKey: "menuDenyList", icon: "shieldOff" },
    ],
  },
]

export const NAV_ICONS = {
  overview: OverviewIcon,
  tasks: TasksIcon,
  folder: FolderIcon,
  bot: BotIcon,
  wrench: WrenchIcon,
  skill: SkillIcon,
  plug: PlugIcon,
  cpu: CpuIcon,
  server: ServerIcon,
  settings: SettingsIcon,
  shield: ShieldCheckIcon,
  shieldOff: ShieldOffIcon,
}

export const NAV_GROUP_KEYS = NAV_GROUPS.map((group) => group.key)

export function findNavLocation(menuKey) {
  for (const group of NAV_GROUPS) {
    const item = group.items.find((entry) => entry.key === menuKey)
    if (item) return { group, item }
  }
  return { group: NAV_GROUPS[0], item: NAV_GROUPS[0].items[0] }
}

export function getAllMenuKeys() {
  return NAV_GROUPS.flatMap((group) => group.items.map((item) => item.key))
}
