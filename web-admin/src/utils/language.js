// Monaco language ids for the file kinds the agent's tools actually write.
//
// An unknown extension is plain text on purpose: guessing a grammar would colour
// the diff with tokens the file does not have, and a comment in a `.env` is not a
// broken string.

const LANGUAGE_BY_EXTENSION = {
  bash: "shell",
  c: "c",
  cc: "cpp",
  cfg: "ini",
  cjs: "javascript",
  conf: "ini",
  cpp: "cpp",
  cs: "csharp",
  css: "css",
  cxx: "cpp",
  dart: "dart",
  go: "go",
  h: "c",
  hpp: "cpp",
  htm: "html",
  html: "html",
  ini: "ini",
  java: "java",
  js: "javascript",
  json: "json",
  jsonc: "json",
  jsx: "javascript",
  kt: "kotlin",
  kts: "kotlin",
  less: "less",
  lua: "lua",
  markdown: "markdown",
  md: "markdown",
  mjs: "javascript",
  php: "php",
  ps1: "powershell",
  py: "python",
  pyi: "python",
  rb: "ruby",
  rs: "rust",
  scss: "scss",
  sh: "shell",
  sql: "sql",
  svg: "xml",
  swift: "swift",
  toml: "ini",
  ts: "typescript",
  tsx: "typescript",
  vue: "html",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
  zsh: "shell",
}

// Files Monaco has a grammar for without an extension to read.
const LANGUAGE_BY_NAME = {
  dockerfile: "dockerfile",
  makefile: "makefile",
}

/**
 * The Monaco language id for a workspace-relative path.
 *
 * Only the last path segment is looked at, so a directory called `json/` does not
 * decide the grammar of what is inside it.
 */
export function languageForPath(path) {
  const name = String(path || "").split("/").pop().toLowerCase()
  if (LANGUAGE_BY_NAME[name]) {
    return LANGUAGE_BY_NAME[name]
  }
  const dot = name.lastIndexOf(".")
  if (dot >= 0) {
    const language = LANGUAGE_BY_EXTENSION[name.slice(dot + 1)]
    if (language) return language
  }
  return "plaintext"
}
