#!/usr/bin/env node
"use strict"

// Antigravity 2.0 hook adapter for oh-story writing projects. The shared story
// guard logic lives in story_hook_core.js; this file only translates the
// Antigravity camelCase hook contract and bridges PostToolUse (which must return
// {}) to the next PreInvocation through the session artifact directory.

const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")
const core = require("./story_hook_core.js")

function readInput() {
  try {
    const raw = fs.readFileSync(0, "utf8")
    const value = raw.trim() ? JSON.parse(raw) : {}
    return value && typeof value === "object" && !Array.isArray(value) ? value : {}
  } catch {
    return {}
  }
}

function emit(value) {
  process.stdout.write(JSON.stringify(value && typeof value === "object" ? value : {}))
}

const hookInput = readInput()

function deployedRoot() {
  try {
    const hooks = path.resolve(__dirname)
    if (path.basename(hooks) === "hooks" && path.basename(path.dirname(hooks)) === ".agents") {
      return path.dirname(path.dirname(hooks))
    }
  } catch {}
  return null
}

function projectRoot() {
  const deployed = deployedRoot()
  if (deployed && fs.existsSync(deployed)) return deployed
  for (const candidate of Array.isArray(hookInput.workspacePaths) ? hookInput.workspacePaths : []) {
    const existing = core.existingDir(candidate)
    if (existing) return existing
  }
  return path.resolve(process.cwd())
}

function toolCall() {
  const value = hookInput.toolCall
  return value && typeof value === "object" && !Array.isArray(value) ? value : null
}

function callArgs(call) {
  const value = call && call.args
  return value && typeof value === "object" && !Array.isArray(value) ? value : {}
}

function firstString(object, keys) {
  for (const key of keys) {
    if (typeof object[key] === "string" && object[key]) return object[key]
  }
  return ""
}

function isInside(root, candidate) {
  const relation = path.relative(path.resolve(root), path.resolve(candidate))
  return relation === "" || (!path.isAbsolute(relation) && relation !== ".." && !relation.startsWith(`..${path.sep}`))
}

function targetPaths(call) {
  if (!call) return []
  const root = projectRoot()
  const args = callArgs(call)
  const requestedCwd = core.existingDir(firstString(args, ["Cwd", "cwd", "WorkingDirectory"]))
  const base = requestedCwd && isInside(root, requestedCwd) ? requestedCwd : root
  const raw = []
  const direct = firstString(args, ["Path", "TargetFile", "targetFile", "FilePath", "filePath", "path"])
  if (direct) raw.push(direct)
  if (call.name === "run_command") {
    const command = firstString(args, ["CommandLine", "command", "cmd"])
    raw.push(...core.extractProseTargets(command), ...core.extractPatchTargets(command))
  }
  return [...new Set(raw.filter(Boolean).map((value) => core.resolveTarget(root, value, base)))]
}

function pendingPath() {
  const artifact = core.existingDir(hookInput.artifactDirectoryPath)
  if (artifact) return path.join(artifact, "oh-story-pending.json")
  const conversation = String(hookInput.conversationId || "").replace(/[^A-Za-z0-9_-]/g, "")
  return conversation ? path.join(os.tmpdir(), `oh-story-antigravity-${conversation}.json`) : null
}

function readPending() {
  const file = pendingPath()
  if (!file) return { findings: {}, stopAttempts: 0 }
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"))
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid pending state")
    const findings = value.findings && typeof value.findings === "object" && !Array.isArray(value.findings) ? value.findings : {}
    return { findings, stopAttempts: Number.isInteger(value.stopAttempts) ? value.stopAttempts : 0 }
  } catch {
    return { findings: {}, stopAttempts: 0 }
  }
}

function writePending(state) {
  const file = pendingPath()
  if (!file) return
  const keys = Object.keys(state.findings || {})
  if (!keys.length) {
    try { fs.unlinkSync(file) } catch {}
    return
  }
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    const temporary = `${file}.${process.pid}.tmp`
    fs.writeFileSync(temporary, JSON.stringify({ findings: state.findings, stopAttempts: state.stopAttempts || 0 }), "utf8")
    fs.renameSync(temporary, file)
  } catch {}
}

function pendingMessage(state) {
  const notes = Object.values(state.findings || {}).filter((value) => typeof value === "string" && value)
  if (!notes.length) return ""
  return "[oh-story deterministic prose check]\n" + notes.join("\n\n") +
    "\nResolve these findings in the affected prose files and write the fixes before moving to another chapter or ending the task."
}

function preToolUse() {
  const call = toolCall()
  const root = projectRoot()
  for (const target of targetPaths(call)) {
    const reason = core.proseBlockReason(root, target)
    if (reason) return emit({ decision: "deny", reason })
  }

  if (call && call.name === "run_command") {
    const command = firstString(callArgs(call), ["CommandLine", "command", "cmd"])
    if (command && core.isGitCommitCommand(command)) {
      const warnings = core.stagedMarkdownWarnings(root)
      if (warnings) return emit({ decision: "allow", reason: warnings })
    }
  }
  emit({ decision: "allow" })
}

function postToolUse() {
  const call = toolCall()
  if (!call || hookInput.error) return emit({})
  const root = projectRoot()
  const state = readPending()
  let changed = false
  for (const target of targetPaths(call)) {
    const key = path.resolve(target)
    const finding = core.proseAfterWrite(root, key)
    if (finding) state.findings[key] = finding
    else delete state.findings[key]
    changed = true
  }
  if (changed) {
    state.stopAttempts = 0
    writePending(state)
  }
  emit({})
}

function sessionContext() {
  if (hookInput.invocationNum !== 0 || Number(hookInput.initialNumSteps || 0) > 1) return ""
  const root = projectRoot()
  const messages = []
  const sentinel = path.join(root, ".story-deployed")
  if (fs.existsSync(sentinel)) {
    let text = ""
    try { text = fs.readFileSync(sentinel, "utf8") } catch {}
    const target = text.match(/^target_cli:\s*(.+)$/m)
    if (!target) messages.push("[story-setup] .story-deployed is missing target_cli; rerun story-setup.")
    else if (!target[1].split(",").map((value) => value.trim()).includes("antigravity")) {
      messages.push("[story-setup] This deployment does not include antigravity; rerun story-setup and select Antigravity.")
    }
  }
  const book = core.discoverActiveBook(root)
  if (book) {
    const context = path.join(book, "追踪", "上下文.md")
    if (fs.existsSync(context)) messages.push(`[story context] Active book: ${core.safeRelative(root, book)}. Read ${core.safeRelative(root, context)} before continuing long-form writing.`)
    else messages.push(`[story context] Detected writing project: ${core.safeRelative(root, book)}.`)
  }
  messages.push(...core.continuityFindings(root))
  return messages.join("\n")
}

function preInvocation() {
  const messages = [sessionContext(), pendingMessage(readPending())].filter(Boolean)
  emit(messages.length ? { injectSteps: messages.map((message) => ({ ephemeralMessage: message })) } : {})
}

function stop() {
  const state = readPending()
  const message = pendingMessage(state)
  const termination = String(hookInput.terminationReason || "")
  const mayContinue = termination === "" || termination === "model_stop" || termination === "NO_TOOL_CALL"
  if (message && hookInput.fullyIdle !== false && mayContinue && state.stopAttempts < 1) {
    state.stopAttempts += 1
    writePending(state)
    return emit({ decision: "continue", reason: message })
  }
  emit({ decision: "stop" })
}

function main() {
  const event = process.argv[2] || ""
  try {
    if (event === "pre-tool-use") preToolUse()
    else if (event === "post-tool-use") postToolUse()
    else if (event === "pre-invocation") preInvocation()
    else if (event === "stop") stop()
    else {
      process.stderr.write(`unknown oh-story Antigravity hook event: ${event}\n`)
      process.exitCode = 2
    }
  } catch (error) {
    process.stderr.write(`[oh-story antigravity hook] ${error instanceof Error ? error.message : String(error)}\n`)
    if (event === "pre-tool-use") emit({ decision: "allow" })
    else if (event === "stop") emit({ decision: "stop" })
    else emit({})
  }
}

if (require.main === module) main()

module.exports = { isInside, targetPaths, pendingMessage }
