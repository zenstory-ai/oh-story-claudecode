#!/usr/bin/env node
"use strict"

// ZCode hook adapter for oh-story writing projects. It has no third-party
// dependencies and emits only fields accepted by ZCode 3.3.4's strict hook
// output schema. Diagnostics go to stderr; a healthy no-op keeps stdout empty.

const fs = require("node:fs")
const path = require("node:path")
const { spawnSync } = require("node:child_process")
const core = require("./story_hook_core.js")
const {
  readSentinel,
  agentsVersionNotice,
  existingDir,
  safeRelative,
  resolveTarget,
  firstLine,
  findFirst,
  discoverActiveBook,
  discoverAllBooks,
  continuityFindings,
  extractProseTargets,
  extractPatchTargets,
  proseBlockReason,
  prosePreWriteWarnings,
  formatPreWriteAdvisory,
  isProsePath,
  duplicateTitleFindings,
  proseAfterWrite,
  shellWords,
  isGitCommitCommand,
  stagedMarkdownWarnings,
  skippableLine,
  proseNetFindings,
} = core

let hookInput = {}

function readHookInput() {
  if (process.stdin.isTTY) return {}
  try {
    const raw = fs.readFileSync(0, "utf8")
    if (raw.trim()) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed
    }
  } catch {}
  return {}
}

function emit(value) {
  if (value && typeof value === "object") process.stdout.write(JSON.stringify(value))
}

function hookContext(event, text) {
  return {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext: text,
    },
  }
}

function deployedWorkspaceRoot() {
  try {
    const hooksDir = __dirname
    if (path.basename(hooksDir) === "hooks" && path.basename(path.dirname(hooksDir)) === ".zcode") {
      return path.dirname(path.dirname(hooksDir))
    }
  } catch {}
  return null
}

function projectRoot() {
  for (const name of ["ZCODE_PROJECT_DIR", "CLAUDE_PROJECT_DIR"]) {
    const candidate = existingDir(process.env[name])
    if (candidate) return candidate
  }
  const deployed = deployedWorkspaceRoot()
  if (deployed) return deployed
  const inputCwd = existingDir(hookInput.cwd)
  const cwd = inputCwd || process.cwd()
  try {
    const result = spawnSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      windowsHide: true,
    })
    if (result.status === 0 && result.stdout.trim()) return path.resolve(result.stdout.trim())
  } catch {}
  return path.resolve(cwd)
}

function sessionStart() {
  const root = projectRoot()
  const messages = []
  const sentinel = readSentinel(root)
  if (sentinel !== null) {
    const versionNotice = agentsVersionNotice(root, { sentinel, setupCommand: "$story-setup" })
    if (versionNotice) messages.push(versionNotice)
    const targetCli = sentinel.target_cli || ""
    if (!targetCli) {
      messages.push("[story-setup] .story-deployed 缺少 target_cli；建议重新运行 $story-setup。")
    } else if (!targetCli.split(",").map((item) => item.trim()).includes("zcode")) {
      messages.push("[story-setup] 当前部署标记未包含 zcode；如需 ZCode 项目适配，请重新运行 $story-setup 并选择 ZCode。")
    }
  }
  const book = discoverActiveBook(root)
  if (book) {
    const context = path.join(book, "追踪", "上下文.md")
    if (fs.existsSync(context)) {
      messages.push(`[story context] 当前书目：${safeRelative(root, book)}。继续长篇写作前先读取 ${safeRelative(root, context)}。`)
    } else {
      messages.push(`[story context] 检测到写作项目：${safeRelative(root, book)}。`)
    }
  }
  messages.push(...continuityFindings(root))
  if (messages.length) emit(hookContext("SessionStart", messages.join("\n")))
}

function toolName(input) {
  return String(input.tool_name || input.toolName || input.tool || input.name || "")
}

function toolPayload(input) {
  for (const key of ["tool_input", "toolInput", "input", "parameters", "args"]) {
    const value = input[key]
    if (value && typeof value === "object" && !Array.isArray(value)) return value
  }
  return {}
}

function isPathInside(root, candidate, pathApi = path) {
  const relation = pathApi.relative(root, candidate)
  return relation === "" || (
    !pathApi.isAbsolute(relation)
    && relation !== ".."
    && !relation.startsWith(`..${pathApi.sep}`)
  )
}

function targetPaths(input) {
  const root = projectRoot()
  const inputCwd = existingDir(input.cwd)
  const base = inputCwd && isPathInside(root, inputCwd) ? inputCwd : root
  const name = toolName(input)
  const payload = toolPayload(input)
  const rawTargets = []
  for (const key of ["file_path", "filePath", "path", "target", "filename"]) {
    if (typeof payload[key] === "string") rawTargets.push(payload[key])
  }
  const command = typeof payload.command === "string" ? payload.command : ""
  if (command) {
    if (/bash/i.test(name)) rawTargets.push(...extractProseTargets(command))
    else rawTargets.push(...extractPatchTargets(command), ...extractProseTargets(command))
  }
  for (const key of ["patch", "content", "text"]) {
    if (typeof payload[key] === "string" && /applypatch|patch/i.test(name)) rawTargets.push(...extractPatchTargets(payload[key]))
  }
  return [...new Set(rawTargets.filter(Boolean).map((value) => resolveTarget(root, value, base)))]
}

function preToolProseGuard() {
  const root = projectRoot()
  const warnings = []
  for (const target of targetPaths(hookInput)) {
    const reason = proseBlockReason(root, target)
    if (reason) {
      emit({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: reason,
        },
      })
      return
    }
    warnings.push(...prosePreWriteWarnings(root, target))
  }
  const advisory = formatPreWriteAdvisory(warnings)
  if (advisory) emit(hookContext("PreToolUse", advisory))
}

function preToolCommitAdvisory() {
  const payload = toolPayload(hookInput)
  const command = typeof payload.command === "string" ? payload.command : ""
  if (!command || !isGitCommitCommand(command)) return
  const warnings = stagedMarkdownWarnings(projectRoot())
  if (warnings) emit(hookContext("PreToolUse", warnings))
}

function postToolProseCheck() {
  const root = projectRoot()
  const notes = targetPaths(hookInput).map((target) => proseAfterWrite(root, target)).filter(Boolean)
  if (notes.length) emit(hookContext("PostToolUse", notes.join("\n\n")))
}

function main() {
  const event = process.argv[2] || ""
  hookInput = readHookInput()
  try {
    if (event === "session-start") sessionStart()
    else if (event === "pre-tool-prose-guard") preToolProseGuard()
    else if (event === "pre-tool-commit-advisory") preToolCommitAdvisory()
    else if (event === "post-tool-prose-check") postToolProseCheck()
    else {
      process.stderr.write(`unknown oh-story ZCode hook event: ${event}\n`)
      process.exitCode = 2
    }
  } catch (error) {
    // Hook checks are defensive guardrails. Unexpected parse/filesystem failures
    // fail open and are diagnosable without corrupting strict stdout JSON.
    process.stderr.write(`[oh-story zcode hook] ${error instanceof Error ? error.message : String(error)}\n`)
  }
}

if (require.main === module) main()

module.exports = {
  continuityFindings,
  proseNetFindings,
  extractProseTargets,
  extractPatchTargets,
  isGitCommitCommand,
  isPathInside,
}
