#!/usr/bin/env node
"use strict"

// story_hook_cli.js — Claude Code 统一 Node.js Hook 适配器
// 承接 .claude/settings.local.json 注册的全部 8 个 Claude Code hook 事件，以及
// chapter-extractor.md 的 frontmatter 内联守卫 `analysis-input-guard`。
// 共享写正文守卫/正文兜底网/缺口检测/连续性/commit 校验逻辑全部来自同目录的
// story_hook_core.js（五端字节一致，由 lint-repo.py --only shared 守卫）。

const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")
const { spawnSync } = require("node:child_process")

const REQUIRED_HOOK_FILES = ["run-story-hook.sh", "story_hook_cli.js", "story_hook_core.js"]
const NESTED_INPUT_KEYS = ["tool_input", "input", "parameters", "args"]

function readStdin() {
  if (process.stdin.isTTY) return ""
  try {
    return fs.readFileSync(0, "utf8")
  } catch {
    return ""
  }
}

function readRawInput() {
  return process.env.CLAUDE_TOOL_INPUT || process.env.HOOK_INPUT || readStdin()
}

function digString(value, keys, allowEmpty = false) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of keys) {
      const found = value[key]
      if (typeof found === "string" && (allowEmpty || found)) return found
    }
    for (const key of NESTED_INPUT_KEYS) {
      const found = digString(value[key], keys, allowEmpty)
      if (found) return found
    }
  }
  return ""
}

const digTargetPath = (value) => digString(value, ["file_path", "path", "filePath"])
const digCommand = (value) => digString(value, ["command", "cmd", "script"], true)
const digWorkingDirectory = (value) =>
  digString(value, ["cwd", "working_directory", "workingDirectory"])

function existingDirFallback(value) {
  if (typeof value !== "string" || !value.trim()) return null
  try {
    const resolved = fs.realpathSync(path.resolve(value))
    return fs.statSync(resolved).isDirectory() ? resolved : null
  } catch {
    return null
  }
}

function deployedWorkspaceRoot() {
  try {
    const hooksDir = path.resolve(__dirname)
    if (path.basename(hooksDir) === "hooks" && path.basename(path.dirname(hooksDir)) === ".claude") {
      const root = path.dirname(path.dirname(hooksDir))
      if (fs.existsSync(root) && fs.statSync(root).isDirectory()) return fs.realpathSync(root)
    }
  } catch {}
  return null
}

function projectRoot(input = null) {
  const envRoot = existingDirFallback(process.env.CLAUDE_PROJECT_DIR)
  if (envRoot) return envRoot
  const inputCwd = input ? existingDirFallback(digWorkingDirectory(input)) : null
  const cwd = inputCwd || process.cwd()
  try {
    const result = spawnSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      windowsHide: true,
    })
    if (result.status === 0 && result.stdout.trim()) {
      const gitRoot = existingDirFallback(result.stdout.trim())
      if (gitRoot) return gitRoot
    }
  } catch {}
  const deployed = deployedWorkspaceRoot()
  if (deployed) return deployed
  return existingDirFallback(cwd) || path.resolve(cwd)
}

function isPathInside(root, candidate, pathApi = path) {
  const relation = pathApi.relative(root, candidate)
  return relation === "" || (
    !pathApi.isAbsolute(relation)
    && relation !== ".."
    && !relation.startsWith(`..${pathApi.sep}`)
  )
}

function targetBase(root, obj) {
  const requested = existingDirFallback(digWorkingDirectory(obj))
  if (requested && isPathInside(root, requested)) return requested
  return root
}

function gitText(root, args) {
  try {
    const result = spawnSync("git", ["-C", root, ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      windowsHide: true,
    })
    if (result.status === 0 && result.stdout) return result.stdout.replace(/\r?\n$/, "")
  } catch {}
  return ""
}

function gitNullCount(root, args) {
  try {
    const result = spawnSync("git", ["-C", root, "-c", "core.quotepath=false", ...args], {
      encoding: "buffer",
      stdio: ["ignore", "pipe", "ignore"],
      windowsHide: true,
    })
    if (result.status === 0 && result.stdout) {
      return result.stdout.toString("utf8").split("\0").filter(Boolean).length
    }
  } catch {}
  return 0
}

function compareSemver(a, b) {
  const pa = String(a).split(".").map((n) => Number.parseInt(n, 10) || 0)
  const pb = String(b).split(".").map((n) => Number.parseInt(n, 10) || 0)
  const len = Math.max(pa.length, pb.length)
  for (let i = 0; i < len; i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0)
    if (diff !== 0) return diff
  }
  return 0
}

function checkVersionUpdate(root) {
  if (process.env.STORY_NO_UPDATE_CHECK) return ""
  const home = process.env.HOME || process.env.USERPROFILE || os.homedir() || ""
  const candidates = [
    path.join(root, ".claude", "skills", "story", "VERSION"),
    home ? path.join(home, ".claude", "skills", "story", "VERSION") : "",
  ].filter(Boolean)
  const vfile = candidates.find((candidate) => fs.existsSync(candidate))
  if (!vfile) return ""
  let cur = ""
  try {
    cur = fs.readFileSync(vfile, "utf8").replace(/[^0-9.]/g, "")
  } catch {
    return ""
  }
  if (!cur) return ""

  const cacheBase = home || root
  const cacheFile = path.join(cacheBase, ".claude", ".story-update-cache")
  const now = Math.floor(Date.now() / 1000)
  let last = 0
  let latest = ""
  try {
    if (fs.existsSync(cacheFile)) {
      const lines = fs.readFileSync(cacheFile, "utf8").split(/\r?\n/)
      const parsedLast = Number.parseInt(lines[0] || "0", 10)
      if (Number.isFinite(parsedLast)) last = parsedLast
      latest = (lines[1] || "").trim()
    }
  } catch {}

  if (now - last < 86400) return ""

  latest = ""
  try {
    const res = spawnSync(
      "curl",
      ["-fsS", "--max-time", "5", "https://api.github.com/repos/zenstory-ai/oh-story-claudecode/releases/latest"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], windowsHide: true }
    )
    if (res.status === 0 && res.stdout) {
      const tagMatch = res.stdout.match(/"tag_name"\s*:\s*"([^"]+)"/)
      const verMatch = tagMatch && tagMatch[1].match(/[0-9][0-9.]*/)
      if (verMatch) latest = verMatch[0]
    }
  } catch {}

  try {
    fs.mkdirSync(path.dirname(cacheFile), { recursive: true })
    fs.writeFileSync(cacheFile, `${now}\n${latest}\n`, "utf8")
  } catch {}

  if (latest && latest !== cur && compareSemver(latest, cur) > 0) {
    return `[INFO] 网文工具箱有新版本 v${latest}（当前 v${cur}）。更新：npx skills add zenstory-ai/oh-story-claudecode -y -g 后重跑 /story-setup；或对 /story 说“检查更新”。关掉提醒：export STORY_NO_UPDATE_CHECK=1\n`
  }
  return ""
}

function countFileLines(file) {
  try {
    const text = fs.readFileSync(file, "utf8")
    if (!text) return 0
    return text.endsWith("\n") ? text.split("\n").length - 1 : text.split("\n").length
  } catch {
    return 0
  }
}

function hasTopLevelMarkdown(dirPath) {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true }).some((entry) => entry.isFile() && entry.name.endsWith(".md"))
  } catch {
    return false
  }
}

function handleSessionStart(core) {
  const raw = readRawInput()
  let obj = {}
  try {
    if (raw.trim()) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) obj = parsed
    }
  } catch {}

  const root = projectRoot(obj)
  const source = typeof obj.source === "string" ? obj.source : ""
  let output = ""

  const pendingRestart = path.join(root, ".claude", ".agents-pending-restart")
  if (fs.existsSync(pendingRestart) && source !== "compact" && source !== "clear") {
    output += "[INFO] story-setup 刚部署/更新了 agents，本会话已重新加载——story-architect、narrative-writer 等 custom agent 现已注册可用。\n"
    output += "  若写作 skill 仍提示 spawn 失败 / 降级 solo，说明你还在部署时的旧会话里，请再新开一个 Claude Code 会话。\n\n"
    try { fs.unlinkSync(pendingRestart) } catch {}
  }

  const sentinel = core.readSentinel(root)
  if (sentinel !== null) {
    const missingHooks = REQUIRED_HOOK_FILES.filter((file) => !fs.existsSync(path.join(root, ".claude", "hooks", file)))
    if (missingHooks.length) {
      output += `[WARN] .story-deployed 存在但缺少 hook：${missingHooks.join(" ")} \n`
      output += "  修复：重新运行 /story-setup 恢复缺失的 hook。\n\n"
    }

    const versionNotice = core.agentsVersionNotice(root, { sentinel, setupCommand: "/story-setup" })
    if (versionNotice) {
      output += `${versionNotice}\n\n`
    }

    for (const field of ["setup_skill_version", "target_cli", "resolver_strategy", "references_dir"]) {
      if (!sentinel[field]) {
        output += `[WARN] .story-deployed 缺少 ${field} 字段。重新运行 /story-setup 刷新部署元信息。\n\n`
      }
    }

    const refsRaw = sentinel.references_dir || ""
    if (refsRaw) {
      const missingRefs = []
      for (const entry of refsRaw.split(",").map((item) => item.trim()).filter(Boolean)) {
        const resolved = path.isAbsolute(entry) ? entry : path.resolve(root, entry)
        if (!hasTopLevelMarkdown(resolved)) missingRefs.push(entry)
      }
      if (missingRefs.length) {
        output += `[WARN] story-setup 参考资料包缺失或为空：${missingRefs.join(", ")}。重新运行 /story-setup；若重跑后仍报这条，是 skill 包本身没装全，按你的安装方式重装 oh-story-claudecode（npx skills add 或 marketplace 面板）再部署。\n\n`
      }
    }
  } else {
    output += "[WARN] 写作环境未部署。运行 /story-setup 初始化。\n\n"
  }

  const branch = gitText(root, ["branch", "--show-current"])
  if (branch) {
    output += "=== 写作进度 ===\n"
    output += `分支：${branch}\n`
    const recent = gitText(root, ["log", "--oneline", "-5"])
    if (recent) output += `${recent}\n`
    output += "\n"
  }

  const book = core.discoverActiveBook(root)
  if (book) {
    const contextFile = path.join(book, "追踪", "上下文.md")
    if (fs.existsSync(contextFile)) {
      let snapshot = ""
      try {
        snapshot = fs.readFileSync(contextFile, "utf8").split(/\r?\n/).slice(0, 18).join("\n")
      } catch {}
      output += `--- 当前位置 ---\n${snapshot}\n---\n\n`
    }
  }

  const incomplete = core.discoverIncompleteAnalyses(root)
  if (incomplete.length > 0) {
    output += `[INFO] 拆文库/ 中有 ${incomplete.length} 个未完成拆文。运行 /story-long-analyze 或 /story-short-analyze。\n`
  }

  output += checkVersionUpdate(root)

  if (output) process.stdout.write(output)
}

function handleDetectStoryGaps(core) {
  const root = projectRoot()
  const out = core.detectStoryGaps(root)
  if (out) process.stdout.write(out)
}

function formatLocalTimestamp(date) {
  const pad = (n) => String(n).padStart(2, "0")
  const offsetMin = -date.getTimezoneOffset()
  const sign = offsetMin >= 0 ? "+" : "-"
  const abs = Math.abs(offsetMin)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${sign}${pad(Math.floor(abs / 60))}${pad(abs % 60)}`
}

function handleSessionEnd(core) {
  if (process.env.STORY_SESSION_LOG !== "1") return
  const root = projectRoot()
  const book = core.discoverActiveBook(root)
  if (!book) return
  const trackingDir = path.join(book, "追踪")
  try {
    if (fs.existsSync(trackingDir) && fs.statSync(trackingDir).isDirectory()) {
      fs.appendFileSync(path.join(trackingDir, "session-log.txt"), `[${formatLocalTimestamp(new Date())}] session ended\n`, "utf8")
    }
  } catch {}
}

function handlePreCompact(core) {
  const root = projectRoot()
  const lines = ["=== Pre-Compact Summary ==="]
  const book = core.discoverActiveBook(root)
  const ctx = book ? path.join(book, "追踪", "上下文.md") : ""
  if (book && fs.existsSync(ctx)) {
    lines.push(`Writing context: ${core.safeRelative(root, ctx)} (${countFileLines(ctx)} lines)`)
  } else {
    lines.push("Active state: not found")
  }
  const changed = gitNullCount(root, ["diff", "--name-only", "-z"])
  const staged = gitNullCount(root, ["diff", "--name-only", "--cached", "-z"])
  lines.push(`Git: ${changed} unstaged, ${staged} staged`)
  lines.push("=== Pre-Compact Complete ===")
  process.stdout.write(lines.join("\n") + "\n")
}

function handlePostCompact(core) {
  const root = projectRoot()
  const book = core.discoverActiveBook(root)
  const ctx = book ? path.join(book, "追踪", "上下文.md") : ""
  if (book && fs.existsSync(ctx)) {
    process.stdout.write(`Context was compacted. Read ${core.safeRelative(root, ctx)} (${countFileLines(ctx)} lines) to restore writing context.\n`)
  } else {
    process.stdout.write("Context was compacted. Check 追踪/上下文.md to restore context.\n")
  }
}

function handlePreToolProseGuard(core) {
  const raw = readRawInput()
  if (!raw || !raw.trim()) return
  let obj
  try {
    obj = JSON.parse(raw)
  } catch (error) {
    const detail = error && error.message ? error.message : String(error)
    process.stderr.write(`⚠ Bash 正文写入守卫解析失败，本次按 fail-open 放行；请改用 Write/Edit 或修复 hook：${detail}\n`)
    return
  }

  const root = projectRoot(obj)
  const base = targetBase(root, obj)
  const directTarget = digTargetPath(obj)
  if (directTarget) {
    const abs = core.resolveTarget(root, directTarget, base)
    const reason = core.proseBlockReason(root, abs)
    if (reason) {
      process.stderr.write(`${reason}\n`)
      process.exit(2)
    }
    const advisory = core.formatPreWriteAdvisory(core.prosePreWriteWarnings(root, abs))
    if (advisory) {
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          additionalContext: advisory,
        },
      }) + "\n")
    }
    return
  }

  const shellCommand = digCommand(obj)
  if (!shellCommand) return
  const seen = new Set()
  const warnings = []
  for (const target of core.extractProseTargets(shellCommand)) {
    const abs = core.resolveTarget(root, target, base)
    if (seen.has(abs)) continue
    seen.add(abs)
    const reason = core.proseBlockReason(root, abs)
    if (reason) {
      process.stderr.write(`${reason}（已从 Bash 命令识别到正文写入目标。）\n`)
      process.exit(2)
    }
    warnings.push(...core.prosePreWriteWarnings(root, abs))
  }
  const advisory = core.formatPreWriteAdvisory(warnings)
  if (advisory) {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext: advisory,
      },
    }) + "\n")
  }
}

function handlePreToolCommitAdvisory(core) {
  let command = process.env.STORY_COMMIT_COMMAND || ""
  let obj = {}
  if (!command) {
    const raw = readRawInput()
    if (!raw || !raw.trim()) return
    try {
      obj = JSON.parse(raw)
    } catch {
      return
    }
    command = digCommand(obj)
  }
  if (!command || !core.isGitCommitCommand(command)) return
  const root = projectRoot(obj)
  const warnings = core.stagedMarkdownWarnings(root)
  if (warnings) process.stdout.write(`${warnings}\n`)
}

function handlePostToolProseCheck(core) {
  const raw = readRawInput()
  if (!raw || !raw.trim()) return
  let obj
  try {
    obj = JSON.parse(raw)
  } catch {
    return
  }
  const target = digTargetPath(obj)
  if (!target) return
  const root = projectRoot(obj)
  const base = targetBase(root, obj)
  const abs = core.resolveTarget(root, target, base)
  const out = core.proseAfterWrite(root, abs)
  if (out) process.stdout.write(`${out}\n`)
}

function canonicalPath(value) {
  let cur = path.resolve(value)
  const tail = []
  while (true) {
    try {
      const real = fs.realpathSync(cur)
      return tail.length ? path.join(real, ...tail.reverse()) : real
    } catch {
      const parent = path.dirname(cur)
      if (parent === cur) return path.resolve(value)
      tail.push(path.basename(cur))
      cur = parent
    }
  }
}

function handleAnalysisInputGuard() {
  // chapter-extractor 的 PreToolUse(Write) 内联守卫：它只许把批次结果写到
  // {拆文目录}/_analysis_cache/输入-{RAW|REUSE}-{起章}-{止章}.md。拆文目录以存在
  // chapter_index.csv 或 _progress.md 认定，且必须在项目根内。exit 2 阻断并把原因交回子代理；
  // 读不到输入视为无从判断，放行（提交脚本仍会完整校验文件内容）。
  const raw = readRawInput()
  let obj
  try {
    obj = JSON.parse(raw)
  } catch {
    process.exit(0)
  }
  const target = digTargetPath(obj)
  if (!target) process.exit(0)
  const root = canonicalPath(process.env.CLAUDE_PROJECT_DIR || digString(obj, ["cwd"]) || process.cwd())
  const absolute = canonicalPath(path.resolve(root, target))
  const reasons = []
  const match = /^输入-(RAW|REUSE)-(\d+)-(\d+)\.md$/.exec(path.basename(absolute))
  if (!match) reasons.push("文件名必须是 输入-{RAW|REUSE}-{起章}-{止章}.md")
  else if (Number(match[2]) < 1 || Number(match[3]) < Number(match[2])) reasons.push("批次章号范围无效")
  const cacheDir = path.dirname(absolute)
  const bookDir = path.dirname(cacheDir)
  if (path.basename(cacheDir) !== "_analysis_cache") reasons.push("只能写在拆文目录的 _analysis_cache/ 下")
  else if (!["chapter_index.csv", "_progress.md"].some((name) => fs.existsSync(path.join(bookDir, name)))) {
    reasons.push("上级目录不是拆文目录（缺 chapter_index.csv 与 _progress.md）")
  }
  if (!isPathInside(root, absolute)) reasons.push("路径在项目目录之外")
  if (reasons.length) {
    process.stderr.write(
      `⛔ chapter-extractor 写入被拦截：${target}\n${reasons.join("；")}。\n` +
        "只允许写调用方给的 {拆文目录}/_analysis_cache/输入-{批次ID}.md（批次 ID 如 RAW-4-6），不写其他文件。"
    )
    process.exit(2)
  }
}

function main() {
  const command = process.argv[2] || ""
  if (command === "analysis-input-guard") {
    handleAnalysisInputGuard()
    return
  }

  let core
  try {
    core = require("./story_hook_core.js")
  } catch (error) {
    const detail = error && error.message ? error.message : String(error)
    if (command === "pre-tool-prose-guard") {
      process.stderr.write(`⚠ Bash 正文写入守卫解析失败，本次按 fail-open 放行；请改用 Write/Edit 或修复 hook：${detail}\n`)
      return
    }
    if (command === "session-start") {
      process.stdout.write(`[WARN] story_hook_core.js 加载失败：${detail}。重新运行 /story-setup 恢复。\n`)
      return
    }
    process.stderr.write(`[oh-story claude hook] failed to load story_hook_core.js: ${detail}\n`)
    return
  }

  try {
    if (command === "session-start") handleSessionStart(core)
    else if (command === "detect-story-gaps") handleDetectStoryGaps(core)
    else if (command === "session-end") handleSessionEnd(core)
    else if (command === "pre-compact") handlePreCompact(core)
    else if (command === "post-compact") handlePostCompact(core)
    else if (command === "pre-tool-prose-guard") handlePreToolProseGuard(core)
    else if (command === "pre-tool-commit-advisory") handlePreToolCommitAdvisory(core)
    else if (command === "post-tool-prose-check") handlePostToolProseCheck(core)
    else {
      process.stderr.write(`unknown oh-story Claude hook event: ${command}\n`)
      process.exit(2)
    }
  } catch (error) {
    const detail = error && error.message ? error.message : String(error)
    if (command === "pre-tool-prose-guard") {
      process.stderr.write(`⚠ Bash 正文写入守卫解析失败，本次按 fail-open 放行；请改用 Write/Edit 或修复 hook：${detail}\n`)
      return
    }
    process.stderr.write(`[oh-story claude hook] ${detail}\n`)
  }
}

if (require.main === module) main()

function loadCoreOrNull() {
  try {
    return require("./story_hook_core.js")
  } catch {
    return null
  }
}

module.exports = {
  get CURRENT_AGENTS_VERSION() {
    const core = loadCoreOrNull()
    return core ? core.CURRENT_AGENTS_VERSION : undefined
  },
  REQUIRED_HOOK_FILES,
  projectRoot,
  readSentinel(root) {
    const core = loadCoreOrNull()
    return core ? core.readSentinel(root) : null
  },
  isPathInside,
}
