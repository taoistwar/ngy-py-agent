// Renders a TeX snippet with KaTeX.
//
// KaTeX is the one place allowed to write raw HTML: it builds its own tree from the
// TeX source and, with ``trust: false``, never emits user markup or links. Everything
// else in the Markdown renderer stays element-based.
//
// ``display`` picks KaTeX display mode (centred, own line); ``block`` picks the DOM
// wrapper. Inline display math (``$$x$$`` inside a sentence) keeps a ``<span>`` so the
// element stays valid inside a paragraph.

import { useMemo } from "react"
import katex from "katex"
import "katex/dist/katex.min.css"

const KATEX_OPTIONS = {
  throwOnError: false,
  errorColor: "var(--danger)",
  strict: "ignore",
  trust: false,
  output: "htmlAndMathml",
}

export default function KatexMath({ tex, display = false, block = display }) {
  const html = useMemo(() => {
    const source = String(tex ?? "").trim()
    if (!source) return ""
    try {
      return katex.renderToString(source, { ...KATEX_OPTIONS, displayMode: display })
    } catch {
      return ""
    }
  }, [tex, display])

  if (!html) return null

  const Tag = block ? "div" : "span"
  const className = display ? "md-math md-math-display" : "md-math"

  return <Tag className={className} dangerouslySetInnerHTML={{ __html: html }} />
}
