import { readFile } from "node:fs/promises"
import { join } from "node:path"

const LOCALE_FILES = {
  en: join(process.cwd(), "src", "locales", "en.json"),
  zhCN: join(process.cwd(), "src", "locales", "zh-CN.json"),
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

function formatDifference(keysA, keysB) {
  const onlyInA = [...keysA].filter((key) => !keysB.has(key)).sort()
  const onlyInB = [...keysB].filter((key) => !keysA.has(key)).sort()
  return {
    onlyInA,
    onlyInB,
  }
}

async function main() {
  const en = await loadMessages(LOCALE_FILES.en)
  const zh = await loadMessages(LOCALE_FILES.zhCN)

  const { onlyInA: missingZh, onlyInB: missingEn } = formatDifference(en.keys, zh.keys)
  let hasError = false

  if (missingZh.length > 0) {
    console.error("Missing keys in zh-CN locale:")
    missingZh.forEach((key) => console.error(`  - ${key}`))
    hasError = true
  }

  if (missingEn.length > 0) {
    console.error("Missing keys in en locale:")
    missingEn.forEach((key) => console.error(`  - ${key}`))
    hasError = true
  }

  if (hasError) {
    process.exitCode = 1
    return
  }

  console.log("i18n keys are aligned.")
}

main().catch((err) => {
  console.error("i18n check failed:", err.message)
  process.exitCode = 1
})
