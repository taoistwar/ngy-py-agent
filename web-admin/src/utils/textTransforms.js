// Display-only text tools for the event log.
//
// The reader of a log entry sometimes needs the same payload as pretty JSON, as one
// line, as unicode escapes, or as an escaped string literal. All of these are views,
// not edits: the stored event is never touched, and every function returns the input
// unchanged when the operation does not apply (format/minify on non-JSON, say).

/** True when ``text`` is a JSON object or array; format/minify are JSON-only. */
export function isJsonText(text) {
  if (typeof text !== "string") return false
  const trimmed = text.trim()
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return false
  try {
    JSON.parse(trimmed)
    return true
  } catch {
    return false
  }
}

/** Pretty-print JSON with two-space indentation; anything else is returned as is. */
export function formatJsonText(text) {
  if (!isJsonText(text)) return text
  return JSON.stringify(JSON.parse(text), null, 2)
}

/** The same JSON on a single line; anything else is returned as is. */
export function minifyJsonText(text) {
  if (!isJsonText(text)) return text
  return JSON.stringify(JSON.parse(text))
}

function hex4(code) {
  return code.toString(16).padStart(4, "0")
}

/**
 * Every non-ASCII character as ``\uXXXX``; astral characters become a surrogate pair,
 * so the output is the escaping JSON itself would use and the inverse reads it back.
 */
export function toUnicodeEscapes(text) {
  let out = ""
  for (const char of String(text)) {
    const code = char.codePointAt(0)
    if (code < 0x80) {
      out += char
      continue
    }
    if (code <= 0xffff) {
      out += `\\u${hex4(code)}`
      continue
    }
    const offset = code - 0x10000
    out += `\\u${hex4(0xd800 + (offset >> 10))}\\u${hex4(0xdc00 + (offset & 0x3ff))}`
  }
  return out
}

/** ``\uXXXX`` (and ``\u{XXXX}``) escapes back to characters. */
export function fromUnicodeEscapes(text) {
  return String(text)
    .replace(/\\u\{([0-9a-fA-F]{1,6})\}/g, (match, hex) => {
      const code = parseInt(hex, 16)
      return code <= 0x10ffff ? String.fromCodePoint(code) : match
    })
    .replace(/\\u([0-9a-fA-F]{4})/g, (match, hex) => String.fromCharCode(parseInt(hex, 16)))
}

// The escapes a JSON/JS string literal uses for characters that cannot stay literal.
// ``\uXXXX`` is deliberately absent: decoding it is the unicode button's job, so the
// two pairs of buttons stay inverses of each other.
const SIMPLE_ESCAPES = {
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
  '"': '"',
  "\\": "\\",
  "/": "/",
}

/** Escape a payload for use inside a JSON/JS string literal (one line). */
export function escapeText(text) {
  return String(text)
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\r/g, "\\r")
    .replace(/\n/g, "\\n")
    .replace(/\t/g, "\\t")
}

/** Undo the escapes {@link escapeText} adds; anything unrecognised is kept verbatim. */
export function unescapeText(text) {
  const source = String(text)
  let out = ""
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index]
    if (char !== "\\") {
      out += char
      continue
    }
    const next = source[index + 1]
    if (next === undefined) {
      out += char
      continue
    }
    const decoded = SIMPLE_ESCAPES[next]
    if (decoded === undefined) {
      out += char
      continue
    }
    out += decoded
    index += 1
  }
  return out
}
