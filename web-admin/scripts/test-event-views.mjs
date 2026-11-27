// Unit checks for the friendly view of the task log.
//
// No test runner in this package (the checks are one script, run by CI). The view
// model sits behind modules that import the message bundles, and node's ESM loader
// refuses those without an import attribute, so they are loaded through vite (already
// a devDependency) instead of a bare `import`. Run with `npm run test:events`.

import assert from "node:assert/strict"
import { createServer } from "vite"

const LOCALES = ["en", "zh-CN", "zh-TW", "fr", "de", "ru"]

const server = await createServer({
  root: process.cwd(),
  appType: "custom",
  server: { middlewareMode: true },
  logLevel: "error",
})

const { buildFriendlyEvent } = await server.ssrLoadModule("/src/events/friendlyEvent.js")

function command(overrides = {}) {
  return {
    session_id: "4a9c1e02",
    pid: 18344,
    command: "npm install",
    description: "Install dependencies",
    exit_code: 0,
    log_path: "C:/out/a.log",
    ...overrides,
  }
}

function backgroundEvent(commands) {
  return {
    category: "debug",
    title: "Background command finished",
    data: { step: 3, count: commands.length, commands },
  }
}

function rowValues(view, index) {
  const rows = view.sections[index]?.rows || []
  return rows.map((row) => row.value)
}

// --------------------------------------------------------------- the finished batch

const batch = buildFriendlyEvent(
  backgroundEvent([
    command(),
    command({
      session_id: "bbbb2222",
      pid: 999,
      command: "npm test",
      description: "",
      exit_code: 1,
      log_path: "C:/out/b.log",
    }),
  ]),
  "en",
)

assert.equal(batch.tone, "danger", "a non-zero exit code has to be visible as a failure")
assert.equal(batch.headline, "2 background commands finished, 1 failed")
assert.equal(batch.sections.length, 2, "one block per command, never one JSON blob")
assert.deepEqual(rowValues(batch, 0), ["npm install", "0", "18344", "4a9c1e02", "C:/out/a.log"])
// The description is what names the block; the command line only earns a row when it
// adds something the description does not say.
assert.equal(batch.sections[1].title, "2. npm test")
assert.deepEqual(rowValues(batch, 1), ["1", "999", "bbbb2222", "C:/out/b.log"])

const succeeded = buildFriendlyEvent(backgroundEvent([command()]), "en")
assert.equal(succeeded.tone, "success")
assert.equal(succeeded.headline, "Background command finished: Install dependencies")

// ------------------------------------------------------------------ unreadable exit

const unknown = buildFriendlyEvent(backgroundEvent([command({ exit_code: null, log_path: "" })]), "en")
assert.equal(unknown.tone, "info", "an exit code nobody saw is not a success")
assert.equal(unknown.headline, "Background command finished: Install dependencies")

// -------------------------------------------------------------------- every locale

for (const locale of LOCALES) {
  const view = buildFriendlyEvent(backgroundEvent([command(), command({ exit_code: 1 })]), locale)
  assert.ok(view.headline, `${locale}: empty headline`)
  assert.equal(view.sections.length, 2, `${locale}: blocks do not match the report`)
  assert.ok(
    !view.headline.includes("{name}") && !view.headline.includes("{count}"),
    `${locale}: unfilled template in ${view.headline}`,
  )
}

assert.equal(
  buildFriendlyEvent(backgroundEvent([command()]), "zh-CN").headline,
  "后台命令已完成：Install dependencies",
  "a locale without its own dictionary falls back to English",
)

// ------------------------------------------------ other debug records stay generic

const other = buildFriendlyEvent({ category: "debug", title: "Step timing", data: { step: 1 } }, "en")
assert.equal(other.headline, "A runtime note was recorded")
assert.ok(!other.headline.includes("Background command"))

console.log("event views OK")

await server.close()
