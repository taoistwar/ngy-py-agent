// The task prompt: plain text, fully expanded by default (the pane scrolls, the
// box does not) and foldable from its title bar so long prompts do not push the
// result off screen.
import { useState } from "react"
import { useTheme } from "../theme"
import AutoHeightMonaco from "./AutoHeightMonaco"
import CollapsibleSectionTitle from "./CollapsibleSectionTitle"

const PROMPT_EDITOR_OPTIONS = {
  readOnly: true,
  minimap: {
    enabled: false,
  },
  scrollBeyondLastLine: false,
  wordWrap: "on",
  fontSize: 14,
  lineNumbers: "on",
  renderLineHighlight: "none",
  automaticLayout: true,
}

export default function TaskPromptPanel({ query, translate }) {
  const { monacoTheme } = useTheme()
  const [open, setOpen] = useState(true)

  return (
    <section className={`detail-section detail-section-query${open ? "" : " is-collapsed"}`}>
      <div className="detail-section-header">
        <CollapsibleSectionTitle
          title={translate("taskDetailPrompt")}
          open={open}
          onToggle={() => setOpen((previous) => !previous)}
          translate={translate}
        />
      </div>
      {open ? (
        <div className="detail-json-editor">
          <AutoHeightMonaco
            value={query}
            language="plaintext"
            theme={monacoTheme}
            options={PROMPT_EDITOR_OPTIONS}
          />
        </div>
      ) : null}
    </section>
  )
}
