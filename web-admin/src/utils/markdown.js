// Block-level Markdown for the task result pane: headings, lists, fenced code,
// display math, blockquotes, tables and horizontal rules.
//
// This is a renderer, not a spec-complete parser: it covers what model answers
// actually write. Rendering lives in ``components/MarkdownView.jsx``.

import { parseInline } from "./markdownInline"

const FENCE_PATTERN = /^\s{0,3}(`{3,}|~{3,})\s*([\w#+.-]*)\s*$/
const MATH_PATTERN = /^\s{0,3}\$\$/
const HEADING_PATTERN = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const RULE_PATTERN = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/
const QUOTE_PATTERN = /^\s{0,3}>\s?(.*)$/
const BULLET_PATTERN = /^(\s*)([-*+])\s+(.*)$/
const NUMBER_PATTERN = /^(\s*)(\d{1,9})[.)]\s+(.*)$/
const DIVIDER_CELL_PATTERN = /^:?-{1,}:?$/

function leadingSpaces(line) {
  let count = 0
  while (line[count] === " ") count += 1
  return count
}

function stripIndent(line, width) {
  let removed = 0
  while (removed < width && line[removed] === " ") removed += 1
  return line.slice(removed)
}

function matchListMarker(line) {
  if (!line) return null
  const numbered = NUMBER_PATTERN.exec(line)
  if (numbered) {
    return {
      indent: numbered[1].length,
      ordered: true,
      number: Number(numbered[2]),
      content: numbered[3],
    }
  }
  const bullet = BULLET_PATTERN.exec(line)
  if (bullet) {
    return {
      indent: bullet[1].length,
      ordered: false,
      number: 0,
      content: bullet[3],
    }
  }
  return null
}

/** Splits a table row on unescaped pipes, dropping the optional outer pipes. */
function splitRow(line) {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "")
  const cells = []
  let current = ""

  for (let index = 0; index < trimmed.length; index += 1) {
    const char = trimmed[index]
    if (char === "\\" && trimmed[index + 1] === "|") {
      current += "|"
      index += 1
      continue
    }
    if (char === "|") {
      cells.push(current.trim())
      current = ""
      continue
    }
    current += char
  }

  cells.push(current.trim())
  return cells
}

function isTableDivider(line) {
  if (!line || !line.includes("-")) return false
  const cells = splitRow(line)
  return cells.length > 0 && cells.every((cell) => DIVIDER_CELL_PATTERN.test(cell))
}

/** True for a line that starts a block and therefore ends a paragraph. */
function startsBlock(line) {
  return (
    FENCE_PATTERN.test(line) ||
    MATH_PATTERN.test(line) ||
    HEADING_PATTERN.test(line) ||
    RULE_PATTERN.test(line) ||
    QUOTE_PATTERN.test(line) ||
    Boolean(matchListMarker(line))
  )
}

/**
 * Soft-wraps a paragraph: single newlines join with a space, two trailing spaces (or
 * a trailing backslash) force a line break.
 */
function parseParagraphLines(lines) {
  const nodes = []

  lines.forEach((line, index) => {
    if (index > 0) {
      const previous = lines[index - 1]
      nodes.push(/ {2,}$/.test(previous) || /\\$/.test(previous) ? { type: "break" } : " ")
    }
    parseInline(line.replace(/\\$/, "")).forEach((node) => nodes.push(node))
  })

  return nodes
}

function parseFence(lines, start, match) {
  const marker = match[1][0]
  const closer = new RegExp(`^\\s{0,3}${marker}{${match[1].length},}\\s*$`)
  const body = []
  let index = start + 1

  while (index < lines.length && !closer.test(lines[index])) {
    body.push(lines[index])
    index += 1
  }
  if (index < lines.length) index += 1

  return {
    block: { type: "code", lang: match[2] || "", text: body.join("\n") },
    next: index,
  }
}

/**
 * ``$$ ... $$`` display math, either on one line (``$$x^2$$``) or with the body on
 * its own lines. An unterminated opener returns null so the answer is not swallowed
 * up to the end of the document.
 */
function parseMathBlock(lines, start) {
  const opening = lines[start].trim().slice(2)
  const inlineClose = opening.indexOf("$$")

  if (inlineClose >= 0) {
    const text = opening.slice(0, inlineClose).trim()
    // Trailing words after the closer mean the line is prose with inline math; leaving
    // it to the paragraph parser keeps that text instead of dropping it.
    if (!text || opening.slice(inlineClose + 2).trim()) return null
    return { block: { type: "math", text, display: true }, next: start + 1 }
  }

  const body = opening.trim() ? [opening] : []
  let index = start + 1

  while (index < lines.length) {
    const line = lines[index]
    const close = line.indexOf("$$")
    if (close >= 0) {
      body.push(line.slice(0, close))
      const text = body.join("\n").trim()
      if (!text) return null
      return { block: { type: "math", text, display: true }, next: index + 1 }
    }
    body.push(line)
    index += 1
  }

  return null
}

function parseQuote(lines, start) {
  const body = []
  let index = start

  while (index < lines.length && QUOTE_PATTERN.test(lines[index])) {
    body.push(QUOTE_PATTERN.exec(lines[index])[1])
    index += 1
  }

  return { block: { type: "quote", blocks: parseBlocks(body) }, next: index }
}

function parseTable(lines, start) {
  const header = splitRow(lines[start]).map(parseInline)
  const rows = []
  let index = start + 2

  while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
    rows.push(splitRow(lines[index]).map(parseInline))
    index += 1
  }

  return { block: { type: "table", header, rows }, next: index }
}

/** Whether the blank line at ``index`` is inside the current item (loose list). */
function continuesAfterBlank(lines, index, baseIndent, ordered) {
  let lookahead = index
  while (lookahead < lines.length && !lines[lookahead].trim()) lookahead += 1
  if (lookahead >= lines.length) return false

  const line = lines[lookahead]
  const marker = matchListMarker(line)
  if (marker) {
    return marker.indent >= baseIndent && marker.ordered === ordered
  }
  return leadingSpaces(line) > baseIndent
}

function parseListItems(lines, start, head) {
  const items = []
  let index = start

  while (index < lines.length) {
    const marker = matchListMarker(lines[index])
    if (!marker || marker.ordered !== head.ordered || marker.indent !== head.indent) {
      break
    }

    const itemLines = [marker.content]
    index += 1

    while (index < lines.length) {
      const line = lines[index]
      const nested = matchListMarker(line)
      // A marker at this indent or shallower starts the next item / ends the list.
      if (nested && nested.indent <= head.indent) {
        break
      }

      if (!line.trim()) {
        if (!continuesAfterBlank(lines, index + 1, head.indent, head.ordered)) {
          break
        }
        itemLines.push("")
        index += 1
        continue
      }

      itemLines.push(stripIndent(line, head.indent + 2))
      index += 1
    }

    items.push({ number: marker.number, blocks: parseBlocks(itemLines) })
  }

  return { items, next: index }
}

function parseList(lines, start) {
  const head = matchListMarker(lines[start])
  const { items, next } = parseListItems(lines, start, head)

  return {
    block: { type: "list", ordered: head.ordered, start: head.number || 1, items },
    next,
  }
}

function parseBlocks(lines) {
  const blocks = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    const fence = FENCE_PATTERN.exec(line)
    if (fence) {
      const parsed = parseFence(lines, index, fence)
      blocks.push(parsed.block)
      index = parsed.next
      continue
    }

    if (MATH_PATTERN.test(line)) {
      const parsed = parseMathBlock(lines, index)
      if (parsed) {
        blocks.push(parsed.block)
        index = parsed.next
        continue
      }
    }

    const heading = HEADING_PATTERN.exec(line)
    if (heading) {
      blocks.push({
        type: "heading",
        level: heading[1].length,
        inline: parseInline(heading[2]),
      })
      index += 1
      continue
    }

    if (RULE_PATTERN.test(line)) {
      blocks.push({ type: "hr" })
      index += 1
      continue
    }

    if (QUOTE_PATTERN.test(line)) {
      const parsed = parseQuote(lines, index)
      blocks.push(parsed.block)
      index = parsed.next
      continue
    }

    if (matchListMarker(line)) {
      const parsed = parseList(lines, index)
      blocks.push(parsed.block)
      index = parsed.next
      continue
    }

    if (line.includes("|") && isTableDivider(lines[index + 1])) {
      const parsed = parseTable(lines, index)
      blocks.push(parsed.block)
      index = parsed.next
      continue
    }

    const paragraph = [line]
    let cursor = index + 1
    while (cursor < lines.length && lines[cursor].trim() && !startsBlock(lines[cursor])) {
      paragraph.push(lines[cursor])
      cursor += 1
    }
    blocks.push({ type: "paragraph", inline: parseParagraphLines(paragraph) })
    index = cursor
  }

  return blocks
}

/** Parses a Markdown document into the block list ``MarkdownView`` renders. */
export function parseMarkdown(text) {
  const normalized = String(text ?? "").replace(/\r\n?/g, "\n")
  if (!normalized.trim()) {
    return []
  }
  return parseBlocks(normalized.split("\n"))
}
