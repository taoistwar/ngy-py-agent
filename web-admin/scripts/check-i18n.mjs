import { readFile } from "node:fs/promises"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

// English is the source: every other bundle has to cover exactly the same keys.
const SOURCE_LOCALE = "en"
const LOCALE_FILES = {
  en: "en.json",
  "zh-CN": "zh-CN.json",
  "zh-TW": "zh-TW.json",
  fr: "fr.json",
  de: "de.json",
  ru: "ru.json",
}

// The task-log vocabulary is a JS module per locale (src/events/dictionary),
// keyed like the message bundles, so it gets the same treatment.
const DICTIONARY_SECTIONS = ["fields", "values", "text"]

function localePath(fileName) {
  return join(process.cwd(), "src", "locales", fileName)
}

function dictionaryPath(locale) {
  return join(process.cwd(), "src", "events", "dictionary", `${locale}.js`)
}

async function loadMessages(filePath) {
  let raw = await readFile(filePath, "utf-8")
  if (raw.charCodeAt(0) === 0xFEFF) {
    raw = raw.slice(1)
  }
  const data = JSON.parse(raw)
  const keys = new Set()

  const walk = (value, prefix = "") => {
    if (!value || typeof value !== "object") {
      if (prefix) {
        keys.add(prefix)
      }
      return
    }

    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index += 1) {
        walk(value[index], `${prefix}[${index}]`)
      }
      return
    }

    Object.entries(value).forEach(([k, v]) => {
      walk(v, prefix ? `${prefix}.${k}` : k)
    })
  }

  walk(data)
  return { data, keys }
}

async function loadDictionary(locale) {
  const module = await import(pathToFileURL(dictionaryPath(locale)).href)
  return module.default
}

/** Dotted paths of every leaf, so nested value groups are compared too. */
function flattenKeys(value, prefix = "") {
  const keys = new Set()

  Object.entries(value || {}).forEach(([name, item]) => {
    const path = prefix ? `${prefix}.${name}` : name
    if (item && typeof item === "object") {
      flattenKeys(item, path).forEach((key) => keys.add(key))
      return
    }
    keys.add(path)
  })

  return keys
}

function formatDifference(keysA, keysB) {
  const onlyInA = [...keysA].filter((key) => !keysB.has(key)).sort()
  const onlyInB = [...keysB].filter((key) => !keysA.has(key)).sort()
  return {
    onlyInA,
    onlyInB,
  }
}

/** Prints one mismatch block; returns whether there was anything to print. */
function reportMismatch(header, keys) {
  if (keys.length === 0) {
    return false
  }
  console.error(header)
  keys.forEach((key) => console.error(`  - ${key}`))
  return true
}

async function checkMessageBundles(locales) {
  const source = await loadMessages(localePath(LOCALE_FILES[SOURCE_LOCALE]))
  let hasError = false

  for (const locale of locales) {
    const messages = await loadMessages(localePath(LOCALE_FILES[locale]))
    const { onlyInA: missingInLocale, onlyInB: extraInLocale } = formatDifference(
      source.keys,
      messages.keys,
    )

    const missing = reportMismatch(`Missing keys in ${locale} locale:`, missingInLocale)
    const extra = reportMismatch(
      `Keys in ${locale} locale that ${SOURCE_LOCALE} does not have:`,
      extraInLocale,
    )
    hasError = hasError || missing || extra
  }

  return hasError
}

async function checkDictionaries(locales) {
  const source = await loadDictionary(SOURCE_LOCALE)
  let hasError = false

  for (const locale of locales) {
    const dictionary = await loadDictionary(locale)

    for (const section of DICTIONARY_SECTIONS) {
      const { onlyInA: missing, onlyInB: extra } = formatDifference(
        flattenKeys(source[section]),
        flattenKeys(dictionary[section]),
      )

      const missingReport = reportMismatch(
        `Missing ${section} keys in ${locale} event dictionary:`,
        missing,
      )
      const extraReport = reportMismatch(
        `Extra ${section} keys in ${locale} event dictionary:`,
        extra,
      )
      hasError = hasError || missingReport || extraReport
    }
  }

  return hasError
}

async function main() {
  const locales = Object.keys(LOCALE_FILES).filter((locale) => locale !== SOURCE_LOCALE)

  const bundlesBroken = await checkMessageBundles(locales)
  const dictionariesBroken = await checkDictionaries(locales)

  if (bundlesBroken || dictionariesBroken) {
    process.exitCode = 1
    return
  }

  console.log(`i18n keys are aligned across ${locales.length + 1} locales.`)
}

main().catch((err) => {
  console.error("i18n check failed:", err.message)
  process.exitCode = 1
})
