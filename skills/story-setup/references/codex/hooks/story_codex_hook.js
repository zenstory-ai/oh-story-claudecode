#!/usr/bin/env node
"use strict"

// Codex hook adapter for oh-story writing projects. It has no third-party
// dependencies and delegates all story guardrails to the shared story_hook_core.js
// module while preserving Codex's stdin/stdout JSON envelopes.

const fs = require("node:fs")
const path = require("node:path")
const { spawnSync } = require("node:child_process")

const VALID_EVENTS = new Set([
  "session-start",
  "pre-tool-prose-guard",
  "pre-tool-commit-advisory",
  "pre-compact",
  "post-compact",
  "stop",
])

let cachedCore = null
function loadCore() {
  if (!cachedCore) cachedCore = require("./story_hook_core.js")
  return cachedCore
}

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
    const hooksDir = path.resolve(__dirname)
    if (path.basename(hooksDir) === "hooks" && path.basename(path.dirname(hooksDir)) === ".codex") {
      const root = path.dirname(path.dirname(hooksDir))
      if (fs.existsSync(root) && fs.statSync(root).isDirectory()) return fs.realpathSync(root)
    }
  } catch {}
  return null
}

function projectRoot() {
  const { existingDir } = loadCore()
  for (const name of ["CODEX_PROJECT_DIR", "CLAUDE_PROJECT_DIR"]) {
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
    if (result.status === 0 && result.stdout.trim()) {
      const gitRoot = existingDir(result.stdout.trim())
      if (gitRoot) return gitRoot
    }
  } catch {}
  return existingDir(cwd) || path.resolve(cwd)
}

function isPathInside(root, candidate, pathApi = path) {
  const relation = pathApi.relative(root, candidate)
  return relation === "" || (
    !pathApi.isAbsolute(relation)
    && relation !== ".."
    && !relation.startsWith(`..${pathApi.sep}`)
  )
}

function findCommand(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of ["command", "cmd", "script"]) {
      if (typeof value[key] === "string") return value[key]
    }
    for (const key of ["tool_input", "input", "parameters", "args"]) {
      const found = findCommand(value[key])
      if (found) return found
    }
  }
  return ""
}

function targetPaths(input) {
  const { existingDir, extractProseTargets, extractPatchTargets, resolveTarget } = loadCore()
  const root = projectRoot()
  const inputCwd = existingDir(input.cwd)
  const base = inputCwd && isPathInside(root, inputCwd) ? inputCwd : root
  const name = String(input.tool_name || "")
  const payload = input.tool_input && typeof input.tool_input === "object" && !Array.isArray(input.tool_input)
    ? input.tool_input
    : {}
  const rawTargets = []
  for (const key of ["file_path", "filePath", "path", "target", "filename"]) {
    if (typeof payload[key] === "string") rawTargets.push(payload[key])
  }
  const command = typeof payload.command === "string" ? payload.command : ""
  if (command) {
    if (name === "Bash") rawTargets.push(...extractProseTargets(command))
    else rawTargets.push(...extractPatchTargets(command), ...extractProseTargets(command))
  }
  return [...new Set(rawTargets.filter(Boolean).map((value) => resolveTarget(root, value, base)))]
}

function sessionStart() {
  const { readSentinel, agentsVersionNotice, discoverActiveBook, safeRelative, continuityFindings } = loadCore()
  const root = projectRoot()
  const messages = []
  const sentinel = readSentinel(root)
  if (sentinel !== null) {
    const versionNotice = agentsVersionNotice(root, { sentinel, setupCommand: "$story-setup" })
    if (versionNotice) messages.push(versionNotice)
    const targetCli = sentinel.target_cli || ""
    if (!targetCli) {
      messages.push("[story-setup] .story-deployed 缺少 target_cli 字段；建议重新运行 $story-setup。")
    } else if (!targetCli.split(",").map((item) => item.trim()).includes("codex")) {
      messages.push("[story-setup] 当前部署标记未包含 codex；如需 Codex hooks/agents，请重新运行 $story-setup 并选择 Codex。")
    }
  }
  const book = discoverActiveBook(root)
  if (book) {
    const context = path.join(book, "追踪", "上下文.md")
    if (fs.existsSync(context)) {
      messages.push(`[story context] Active book: ${safeRelative(root, book)}. Read ${safeRelative(root, context)} before continuing long-form writing.`)
    } else {
      messages.push(`[story context] Active story project detected: ${safeRelative(root, book)}.`)
    }
  }
  messages.push(...continuityFindings(root))
  if (messages.length) emit(hookContext("SessionStart", messages.join("\n")))
}

function preToolProseGuard() {
  const { proseBlockReason, prosePreWriteWarnings, formatPreWriteAdvisory } = loadCore()
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
  const { isGitCommitCommand, stagedMarkdownWarnings } = loadCore()
  const command = findCommand(hookInput)
  if (!command || !isGitCommitCommand(command)) return
  const warnings = stagedMarkdownWarnings(projectRoot())
  if (warnings) emit(hookContext("PreToolUse", warnings))
}

function gitNullList(root, args) {
  try {
    const result = spawnSync("git", ["-C", root, "-c", "core.quotepath=false", ...args], {
      encoding: "buffer",
      stdio: ["ignore", "pipe", "ignore"],
      windowsHide: true,
    })
    if (result.status !== 0 || !result.stdout) return null
    return result.stdout.toString("utf8").split("\0").filter(Boolean)
  } catch {
    return null
  }
}

function compactSummary() {
  const { discoverActiveBook, safeRelative } = loadCore()
  const root = projectRoot()
  const lines = ["=== Story Compact Summary ==="]
  const book = discoverActiveBook(root)
  if (book) {
    const ctx = path.join(book, "追踪", "上下文.md")
    if (fs.existsSync(ctx)) {
      let lineCount = 0
      try {
        const text = fs.readFileSync(ctx, "utf8")
        lineCount = text ? text.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n").length : 0
      } catch {}
      lines.push(`Writing context: ${safeRelative(root, ctx)} (${lineCount} lines)`)
    } else {
      lines.push(`Active story project: ${safeRelative(root, book)}`)
    }
  } else {
    lines.push("Active state: not found")
  }
  const changed = gitNullList(root, ["diff", "--relative", "--name-only", "-z", "--", "."])
  const staged = gitNullList(root, ["diff", "--relative", "--name-only", "--cached", "-z", "--", "."])
  if (changed !== null && staged !== null) {
    lines.push(`Git: ${changed.length} unstaged, ${staged.length} staged`)
  }
  emit({ systemMessage: lines.join("\n") })
}

function findChangedProseFiles(root) {
  const { isProsePath } = loadCore()
  const out = []
  const seen = new Set()
  const commands = [
    ["diff", "--relative", "--name-only", "-z", "--diff-filter=ACM", "--", "."],
    ["diff", "--relative", "--name-only", "--cached", "-z", "--diff-filter=ACM", "--", "."],
    ["ls-files", "--others", "--exclude-standard", "-z"],
  ]
  for (const args of commands) {
    const entries = gitNullList(root, args)
    if (!entries) continue
    for (const rel of entries) {
      if (!rel.endsWith(".md")) continue
      const abs = path.resolve(root, rel)
      if (seen.has(abs) || !fs.existsSync(abs)) continue
      if (isProsePath(abs)) {
        seen.add(abs)
        out.push(abs)
      }
    }
  }
  return out
}

function stopEvent() {
  // Codex 无 PostToolUse，正文内容网在回合结束的 Stop 事件兜底：对本回合 git 改动过的正文
  // 复扫硬信号与毒句式（短篇 正文.md 按 short 模式放宽并区分为软提醒，对齐其余四端 proseAfterWrite）。
  // 非阻塞、无发现静默；解析失败一律 {continue:true}。
  try {
    const {
      proseDegenerationFindings,
      proseNetFindings,
      loadStyleWhitelist,
      toxicRescanHint,
      safeRelative,
    } = loadCore()
    const root = projectRoot()
    const blocks = []
    let hasHardOrLong = false
    for (const abs of findChangedProseFiles(root)) {
      let text
      try { text = fs.readFileSync(abs, "utf8") } catch { continue }
      const isShort = path.basename(abs) === "正文.md"
      const findings = proseNetFindings(text, loadStyleWhitelist(abs), toxicRescanHint(abs), {
        mode: isShort ? "short" : "long",
      })
      if (findings.length) {
        if (!isShort || proseDegenerationFindings(text).length > 0) {
          hasHardOrLong = true
        }
        blocks.push(`=== ${safeRelative(root, abs)} ===\n${findings.join("\n")}`)
      }
    }
    if (blocks.length) {
      const lead = hasHardOrLong
        ? "=== 正文兜底检测（回合结束复扫，模型无关）===\n硬信号命中即回正文改掉、复扫到净：\n"
        : "=== 正文兜底检测（回合结束复扫，短篇软提醒，非阻断）===\n确属情绪、反转或节奏需要可保留，其余精修时一并处理：\n"
      emit({
        continue: true,
        systemMessage: lead + blocks.join("\n"),
      })
      return
    }
  } catch {}
  emit({ continue: true })
}

function main() {
  const event = process.argv[2] || ""
  if (!VALID_EVENTS.has(event)) {
    process.stderr.write(`unknown oh-story Codex hook event: ${event}\n`)
    process.exitCode = 2
    return
  }
  hookInput = readHookInput()
  try {
    loadCore()
  } catch (error) {
    process.stderr.write(`[oh-story codex hook] failed to load story_hook_core.js: ${error instanceof Error ? error.message : String(error)}\n`)
    if (event === "stop") emit({ continue: true })
    return
  }
  try {
    if (event === "session-start") sessionStart()
    else if (event === "pre-tool-prose-guard") preToolProseGuard()
    else if (event === "pre-tool-commit-advisory") preToolCommitAdvisory()
    else if (event === "pre-compact") compactSummary()
    else if (event === "post-compact") compactSummary()
    else if (event === "stop") stopEvent()
  } catch (error) {
    process.stderr.write(`[oh-story codex hook] ${error instanceof Error ? error.message : String(error)}\n`)
    if (event === "stop") emit({ continue: true })
  }
}

if (require.main === module) main()

module.exports = {
  isPathInside,
  findChangedProseFiles,
}
