// A read-only Monaco that grows to fit its content. The detail pane is the only
// scroll container, so a fixed-height editor would add a nested scrollbar.
import { useState } from "react"
import { default as MonacoEditor } from "@monaco-editor/react"

const MIN_EDITOR_HEIGHT = 56

export default function AutoHeightMonaco({ value, language, theme, options }) {
  const [height, setHeight] = useState(MIN_EDITOR_HEIGHT)

  const syncHeight = (editor) => {
    const next = Math.max(MIN_EDITOR_HEIGHT, editor.getContentHeight())
    setHeight((previous) => (previous === next ? previous : next))
  }

  return (
    <MonacoEditor
      height={`${height}px`}
      language={language}
      value={value}
      theme={theme}
      options={options}
      onMount={(editor) => {
        syncHeight(editor)
        // Word wrap changes the line count on resize, so follow content updates
        // instead of measuring once.
        editor.onDidContentSizeChange(() => syncHeight(editor))
      }}
    />
  )
}
