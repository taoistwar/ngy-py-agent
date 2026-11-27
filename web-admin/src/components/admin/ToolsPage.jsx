// Everything that describes what an agent may call lives on one screen: the tool
// inventory plus the two network tool backends are tabs of the same panel, so the
// sidebar advertises a single "tools" entry instead of three.
import { useState } from "react"
import { LanguagesIcon, RefreshIcon } from "../icons"
import ToolManager from "./ToolManager"
import WebFetchManager from "./WebFetchManager"
import WebSearchManager from "./WebSearchManager"

const TABS = [
  { key: "tools", labelKey: "toolManagerTitle", refreshLabelKey: "toolListRefresh" },
  { key: "websearch", labelKey: "menuWebSearch", refreshLabelKey: "webSearchRefresh" },
  { key: "webfetch", labelKey: "menuWebFetch", refreshLabelKey: "webFetchRefresh" },
]

export default function ToolsPage({
  tools,
  agents,
  locale,
  webSearchConfig,
  webFetchConfig,
  onRefreshTools,
  onRefreshWebSearch,
  onRefreshWebFetch,
  onSaveWebSearch,
  onSaveWebFetch,
  translate,
}) {
  const [activeTab, setActiveTab] = useState(TABS[0].key)
  // One language at a time: the locale's descriptions, or the English source when
  // this is switched on. The detail dialog reads the same flag, so the list and the
  // dialog never disagree about which language they show.
  const [englishDescriptions, setEnglishDescriptions] = useState(false)
  const tab = TABS.find((item) => item.key === activeTab) || TABS[0]
  // Each tab refreshes its own source: the tool inventory, one config each.
  const refreshActiveTab = {
    tools: onRefreshTools,
    websearch: onRefreshWebSearch,
    webfetch: onRefreshWebFetch,
  }[tab.key]
  const refreshLabel = translate(tab.refreshLabelKey)
  const toggleLanguage = () => setEnglishDescriptions((previous) => !previous)
  // Nothing to toggle on the network tabs, and none when the UI is already English:
  // there every description is English anyway.
  const canToggleLanguage = tab.key === "tools" && locale !== "en"
  const languageLabel = translate("toolDetailLanguageToggle")

  return (
    <section className="panel model-manager tool-tabs-panel">
      <div className="panel-titlebar">
        <div className="tab-strip" role="tablist" aria-label={translate("tabAria")}>
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={item.key === tab.key}
              className={`tab-btn ${item.key === tab.key ? "active" : ""}`}
              onClick={() => setActiveTab(item.key)}
            >
              {translate(item.labelKey)}
            </button>
          ))}
        </div>
        <div className="manager-toolbar-actions">
          <button
            type="button"
            className="icon-btn"
            title={refreshLabel}
            aria-label={refreshLabel}
            onClick={refreshActiveTab}
          >
            <RefreshIcon />
          </button>
          {canToggleLanguage ? (
            <button
              type="button"
              className={`icon-btn ${englishDescriptions ? "is-active" : ""}`}
              title={languageLabel}
              aria-label={languageLabel}
              aria-pressed={englishDescriptions}
              onClick={toggleLanguage}
            >
              <LanguagesIcon />
            </button>
          ) : null}
        </div>
      </div>
      <div className="panel-body">
        {tab.key === "tools" ? (
          <ToolManager
            tools={tools}
            agents={agents}
            locale={locale}
            showEnglish={englishDescriptions}
            onToggleLanguage={toggleLanguage}
            translate={translate}
          />
        ) : tab.key === "websearch" ? (
          <WebSearchManager
            config={webSearchConfig}
            onSave={onSaveWebSearch}
            translate={translate}
          />
        ) : (
          <WebFetchManager
            config={webFetchConfig}
            onSave={onSaveWebFetch}
            translate={translate}
          />
        )}
      </div>
    </section>
  )
}
