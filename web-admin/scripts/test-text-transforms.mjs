// Unit checks for the display-only text transforms used by the event log.
//
// No test runner in this package (the checks are one script, run by CI): the module is
// pure and ESM, so node:assert is enough. Run with `npm run test:text`.

import assert from "node:assert/strict"
import {
  escapeText,
  formatJsonText,
  fromUnicodeEscapes,
  isJsonText,
  minifyJsonText,
  toUnicodeEscapes,
  unescapeText,
} from "../src/utils/textTransforms.js"

// ---------------------------------------------------------------- JSON detection

assert.equal(isJsonText('{"a":1}'), true)
assert.equal(isJsonText('[1, 2]'), true)
assert.equal(isJsonText("ls -la"), false)
assert.equal(isJsonText('{"a":'), false)
assert.equal(isJsonText(""), false)

// ------------------------------------------------------------ format and minify

assert.equal(formatJsonText('{"a":1,"b":[2]}'), '{\n  "a": 1,\n  "b": [\n    2\n  ]\n}')
assert.equal(formatJsonText("plain text"), "plain text")
assert.equal(minifyJsonText('{\n  "a": 1\n}'), '{"a":1}')
assert.equal(minifyJsonText("plain text"), "plain text")

// ------------------------------------------------------------ unicode escapes

const chinese = "中文 abc"
const escapedChinese = "\\u4e2d\\u6587 abc"
assert.equal(toUnicodeEscapes(chinese), escapedChinese)
assert.equal(fromUnicodeEscapes(escapedChinese), chinese)
assert.equal(toUnicodeEscapes("ascii only"), "ascii only")

// Astral characters become the surrogate pair JSON itself would emit, and the
// inverse pairs them back into one code point.
const emoji = "😀"
const escapedEmoji = "\\ud83d\\ude00"
assert.equal(toUnicodeEscapes(emoji), escapedEmoji)
assert.equal(fromUnicodeEscapes(escapedEmoji), emoji)
assert.equal(fromUnicodeEscapes("\\u{1f600}"), emoji)
// An out-of-range code point is left alone rather than throwing.
assert.equal(fromUnicodeEscapes("\\u{110000}"), "\\u{110000}")

// ------------------------------------------------------------------ escaping

const multiline = 'say "hi"\npath\\to\tthing'
assert.equal(escapeText(multiline), 'say \\"hi\\"\\npath\\\\to\\tthing')
assert.equal(unescapeText(escapeText(multiline)), multiline)
// ``\uXXXX`` belongs to the unicode button, so unescaping leaves it intact.
assert.equal(unescapeText("a\\u0041"), "a\\u0041")
// An unknown escape stays verbatim instead of being swallowed.
assert.equal(unescapeText("a\\qb"), "a\\qb")

console.log("text transforms OK")
