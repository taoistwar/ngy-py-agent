// Renders the tokens from ``utils/markdown`` as React elements.
//
// Building elements (instead of an HTML string) is what keeps model output inert:
// anything that looks like markup renders as text.

import { useMemo } from "react"
import { parseMarkdown } from "../utils/markdown"

const SAFE_PROTOCOLS = ["http:", "https:", "mailto:"]

/** Drops URLs whose scheme could execute script (``javascript:`` and friends). */
function safeHref(href) {
  const value = String(href || "").trim()
  if (!value) return ""
  if (value.startsWith("#") || value.startsWith("/") || value.startsWith("./") || value.startsWith("../")) {
    return value
  }
  try {
    const url = new URL(value, window.location.origin)
    return SAFE_PROTOCOLS.includes(url.protocol) ? value : ""
  } catch {
    return ""
  }
}

function renderInline(nodes, keyPrefix) {
  return nodes.map((node, index) => {
    if (typeof node === "string") {
      return node
    }

    const key = `${keyPrefix}-${index}`
    switch (node.type) {
      case "code":
        return (
          <code key={key} className="md-inline-code">
            {node.text}
          </code>
        )
      case "strong":
        return <strong key={key}>{renderInline(node.children, key)}</strong>
      case "em":
        return <em key={key}>{renderInline(node.children, key)}</em>
      case "del":
        return <del key={key}>{renderInline(node.children, key)}</del>
      case "link": {
        const href = safeHref(node.href)
        if (!href) {
          return <span key={key}>{renderInline(node.children, key)}</span>
        }
        return (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer">
            {renderInline(node.children, key)}
          </a>
        )
      }
      case "break":
        return <br key={key} />
      default:
        return null
    }
  })
}

function renderList(block, key) {
  const Tag = block.ordered ? "ol" : "ul"

  return (
    <Tag key={key} start={block.ordered && block.start !== 1 ? block.start : undefined}>
      {block.items.map((item, index) => (
        <li key={`${key}-${index}`}>{renderListItem(item, `${key}-${index}`)}</li>
      ))}
    </Tag>
  )
}

function renderListItem(item, keyPrefix) {
  const [first, ...rest] = item.blocks
  if (!first) {
    return null
  }

  // The opening paragraph *is* the item: wrapping it in <p> adds block margins
  // between a bullet and its own text. Nested blocks keep their own markup.
  if (first.type !== "paragraph") {
    return renderBlocks(item.blocks, keyPrefix)
  }

  return (
    <>
      {renderInline(first.inline, keyPrefix)}
      {rest.length > 0 ? renderBlocks(rest, keyPrefix) : null}
    </>
  )
}

function renderTable(block, key) {
  return (
    <div className="md-table-wrap" key={key}>
      <table>
        <thead>
          <tr>
            {block.header.map((cell, index) => (
              <th key={`${key}-h${index}`}>{renderInline(cell, `${key}-h${index}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={`${key}-r${rowIndex}`}>
              {block.header.map((_, cellIndex) => (
                <td key={`${key}-r${rowIndex}c${cellIndex}`}>
                  {renderInline(row[cellIndex] || [], `${key}-r${rowIndex}c${cellIndex}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderBlocks(blocks, keyPrefix) {
  return blocks.map((block, index) => {
    const key = `${keyPrefix}-${index}`

    switch (block.type) {
      case "heading": {
        const Tag = `h${Math.min(block.level, 6)}`
        return <Tag key={key}>{renderInline(block.inline, key)}</Tag>
      }
      case "paragraph":
        return <p key={key}>{renderInline(block.inline, key)}</p>
      case "code":
        return (
          <pre key={key} className="md-code" data-lang={block.lang || undefined}>
            {block.lang ? <span className="md-code-lang">{block.lang}</span> : null}
            <code>{block.text}</code>
          </pre>
        )
      case "list":
        return renderList(block, key)
      case "quote":
        return <blockquote key={key}>{renderBlocks(block.blocks, key)}</blockquote>
      case "table":
        return renderTable(block, key)
      case "hr":
        return <hr key={key} />
      default:
        return null
    }
  })
}

/** Renders a Markdown string as styled flow content. */
export default function MarkdownView({ text, className = "" }) {
  const blocks = useMemo(() => parseMarkdown(text), [text])
  return <div className={`markdown-body ${className}`.trim()}>{renderBlocks(blocks, "b")}</div>
}
