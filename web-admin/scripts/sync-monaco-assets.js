import fs from "node:fs"
import path from "node:path"

const source = path.resolve("node_modules", "monaco-editor", "min", "vs")
const destination = path.resolve("public", "monaco-editor", "min", "vs")

function removeDirectoryIfExists(target) {
  if (fs.existsSync(target)) {
    fs.rmSync(target, { recursive: true, force: true })
  }
}

function ensureDirectory(target) {
  fs.mkdirSync(path.dirname(target), { recursive: true })
}

function copyDirectory(src, dst) {
  fs.cpSync(src, dst, { recursive: true })
}

try {
  if (!fs.existsSync(source)) {
    console.error(`[monaco-sync] source missing: ${source}`)
    process.exit(1)
  }

  removeDirectoryIfExists(destination)
  ensureDirectory(destination)
  copyDirectory(source, destination)
  console.log(`[monaco-sync] copied: ${path.relative(process.cwd(), source)} -> ${path.relative(process.cwd(), destination)}`)
} catch (error) {
  console.error(`[monaco-sync] failed: ${error?.message || error}`)
  process.exit(1)
}
