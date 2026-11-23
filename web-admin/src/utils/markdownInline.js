// Inline Markdown: emphasis, code spans, links, math and hard breaks.
//
// The tokens below never carry HTML: ``components/MarkdownView.jsx`` turns them into
// React elements, so a model answer may quote arbitrary markup and it still shows as
// text instead of being parsed.

const ESCAPABLE = "\\`*_{}[]()#+-.!|>~$"
const LINK_PATTERN = /^\[([^\]\n]*)\]\(([^()\s]*)(?:\s+"[^"\n]*")?\)/
const AUTOLINK_PATTERN = /^<(https?:\/\/[^>\s]+)>/
const BARE_URL_PATTERN = /^(?:https?:\/\/|www\.)[^\s<>()[\]]+/
// Sentence punctuation after a bare URL is not part of it - including the CJK marks
// that model answers written in Chinese end sentences with.
const TRAILING_PUNCTUATION = /[.,;:!?。，、；：！？]+$/

function isWordChar(char) {
  return Boolean(char) && /[\p{L}\p{N}_]/u.test(char)
}

/**
 * Index of the closing run of ``marker`` at least ``width`` wide, or -1.
 *
 * Code spans are skipped (a ``**`` inside backticks is literal), and a single ``*``
 * never closes on the first half of ``**``.
 */
function findClosingRun(text, from, marker, width) {
  let index = from
  while (index < text.length) {
    const char = text[index]
    if (char === "\\") {
      index += 2
      continue
    }
    if (char === "`") {
      const end = text.indexOf("`", index + 1)
      if (end > index) {
        index = end + 1
        continue
      }
    }
    if (char !== marker) {
      index += 1
      continue
    }

    let run = 0
    while (text[index + run] === marker) run += 1

    if (run >= width) {
      // ``snake_case`` is a name, not emphasis: the closing ``_`` must not touch a word.
      if (marker === "_" && isWordChar(text[index + width])) {
        index += run
        continue
      }
      if (width === 1 && run >= 2) {
        index += run
        continue
      }
      return index
    }
    index += run
  }
  return -1
}

function matchStrongStar(text, index) {
  const width = text.startsWith("**", index) ? 2 : 1
  const open = index + width
  const close = findClosingRun(text, open, "*", width)
  if (close < 0) return null
  const inner = text.slice(open, close)
  if (!inner.trim()) return null
  return {
    node: { type: width === 2 ? "strong" : "em", children: parseInline(inner) },
    next: close + width,
  }
}

function matchEmphasis(text, index) {
  const marker = text[index]

  if (marker === "~") {
    if (!text.startsWith("~~", index)) return null
    const close = text.indexOf("~~", index + 2)
    if (close < 0 || close === index + 2) return null
    return {
      node: { type: "del", children: parseInline(text.slice(index + 2, close)) },
      next: close + 2,
    }
  }

  if (marker === "*") {
    return matchStrongStar(text, index)
  }

  // ``_`` only opens emphasis at a word boundary, otherwise ``a_b_c`` is a name.
  if (isWordChar(text[index - 1])) return null
  const width = text.startsWith("__", index) ? 2 : 1
  const open = index + width
  const close = findClosingRun(text, open, "_", width)
  if (close < 0) return null
  const inner = text.slice(open, close)
  if (!inner.trim()) return null
  return {
    node: { type: width === 2 ? "strong" : "em", children: parseInline(inner) },
    next: close + width,
  }
}

function matchLink(text, index) {
  const match = LINK_PATTERN.exec(text.slice(index))
  if (!match) return null
  return {
    node: { type: "link", href: match[2], children: parseInline(match[1]) },
    next: index + match[0].length,
  }
}

function matchAutolink(text, index) {
  const match = AUTOLINK_PATTERN.exec(text.slice(index))
  if (!match) return null
  return {
    node: { type: "link", href: match[1], children: [match[1]] },
    next: index + match[0].length,
  }
}

function matchBareUrl(text, index) {
  const match = BARE_URL_PATTERN.exec(text.slice(index))
  if (!match) return null
  const url = match[0].replace(TRAILING_PUNCTUATION, "")
  if (!url) return null
  const href = url.startsWith("www.") ? `https://${url}` : url
  return {
    node: { type: "link", href, children: [url] },
    next: index + url.length,
  }
}

/** Index of the closing ``$`` (or ``$$``) run, or -1. Escaped dollars are literal. */
function findDollarClose(text, from, width) {
  let index = from
  while (index < text.length) {
    const char = text[index]
    if (char === "\\") {
      index += 2
      continue
    }
    if (char === "$") {
      if (width === 1) return index
      if (text[index + 1] === "$") return index
      index += 1
      continue
    }
    index += 1
  }
  return -1
}

/**
 * ``$...$`` math and ``$$...$$`` display math written inside a line.
 *
 * Currency stays text: a single-``$`` opener may not be followed by a space, its
 * closer may not follow a space, and a closer followed by a digit (``$5-$10``) is
 * not math either - the same rules GitHub uses.
 */
function matchMath(text, index) {
  const display = text.startsWith("$$", index)
  const width = display ? 2 : 1
  const open = index + width
  const first = text[open] || ""

  if (!display && (!first || /\s/.test(first))) return null

  const close = findDollarClose(text, open, width)
  if (close < 0) return null

  const content = text.slice(open, close)
  if (!content.trim()) return null
  if (!display && /\s$/.test(content)) return null
  if (!display && /\d/.test(text[close + 1] || "")) return null

  return {
    node: { type: "math", text: content, display },
    next: close + width,
  }
}

/**
 * Parses one line (or one already-joined run of text) into inline tokens.
 *
 * Tokens are plain strings for literal text, otherwise ``{type, ...}`` objects with
 * ``strong`` / ``em`` / ``del`` carrying nested ``children``.
 */
export function parseInline(text) {
  const source = String(text ?? "")
  const nodes = []
  let buffer = ""
  let index = 0

  const flush = () => {
    if (buffer) {
      nodes.push(buffer)
      buffer = ""
    }
  }

  while (index < source.length) {
    const char = source[index]

    if (char === "\\" && ESCAPABLE.includes(source[index + 1] || "")) {
      buffer += source[index + 1]
      index += 2
      continue
    }

    if (char === "`") {
      const end = source.indexOf("`", index + 1)
      if (end > index + 1) {
        flush()
        nodes.push({ type: "code", text: source.slice(index + 1, end) })
        index = end + 1
        continue
      }
    }

    if (char === "$") {
      const math = matchMath(source, index)
      if (math) {
        flush()
        nodes.push(math.node)
        index = math.next
        continue
      }
    }

    if (char === "*" || char === "_" || char === "~") {
      const emphasis = matchEmphasis(source, index)
      if (emphasis) {
        flush()
        nodes.push(emphasis.node)
        index = emphasis.next
        continue
      }
    }

    if (char === "[") {
      const link = matchLink(source, index)
      if (link) {
        flush()
        nodes.push(link.node)
        index = link.next
        continue
      }
    }

    if (char === "<") {
      const autolink = matchAutolink(source, index)
      if (autolink) {
        flush()
        nodes.push(autolink.node)
        index = autolink.next
        continue
      }
    }

    if ((char === "h" || char === "w") && !isWordChar(source[index - 1])) {
      const bare = matchBareUrl(source, index)
      if (bare) {
        flush()
        nodes.push(bare.node)
        index = bare.next
        continue
      }
    }

    buffer += char
    index += 1
  }

  flush()
  return nodes
}
