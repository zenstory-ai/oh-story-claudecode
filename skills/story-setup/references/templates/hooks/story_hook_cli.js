#!/usr/bin/env node
"use strict"

// story_hook_cli.js — Claude Code bash hook 的 node 桥
// Claude 侧 hook 是 bash（settings.json 挂 bash 脚本），归核逻辑走这里 require 的
// 共享核 story_hook_core.js——和 OpenCode/ZCode 用的是同一份，由 check-shared-files
// 保证字节相同。归核（单份实现在 core）的面：正文网（prose-net）、路径抽取
// （extract-target）、Bash 正文写入前置门（prose-command-guard）、git commit 侦测
// （is-git-commit）、连续性（continuity）、追踪检查点（tracking-checkpoint）。
// 尚未归核、各端独立实现的面：
//   - Write/Edit/MultiEdit 的大纲/细纲阻断判定：Claude 走 guard-outline-before-prose.sh
//     纯 bash。它必须在无 node 的运行时也拦得住（官方推荐的原生二进制装法不带 Node），
//     所以保留纯 bash 判定。Bash 命令要先区分真正写入和只读提及，故经本 CLI 复用共享核；
//     node 缺席时该命令面降级放行。追踪检查点同样因要解析 JSON，经 tracking-checkpoint
//     子命令执行、node 缺席时降级放行。
//     codex prose_block_reason ↔ core proseBlockReason 由
//     scripts/test-prose-net-parity.sh Part E 锁 parity。
//   - staged markdown warnings：Claude 走 validate-story-commit.sh bash grep；codex
//     staged_markdown_warnings ↔ core stagedMarkdownWarnings 同由 Part E 锁 parity。
//     匹配语义与文案以 JS core 为准。
// 各端只留读写各自 hook I/O 格式的薄壳。node 天生按 UTF-8 写 stdout，顺带免掉了
// 旧内嵌 python 那套 cp936/LC_ALL 编码体操。

const fs = require("node:fs")
const path = require("node:path")
const core = require("./story_hook_core.js")

function readStdin() {
  try {
    return fs.readFileSync(0, "utf8")
  } catch {
    return ""
  }
}

const NESTED_INPUT_KEYS = ["tool_input", "input", "parameters", "args"]

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

const [command, ...args] = process.argv.slice(2)

if (command === "extract-target") {
  // PostToolUse 工具输入 JSON → 目标文件路径。无输入/解析失败/无路径都以非零退出，
  // 让 bash 侧静默放行（与旧 python sys.exit(1) 一致）。
  const raw = process.env.HOOK_INPUT || readStdin()
  if (!raw) process.exit(1)
  let obj
  try {
    obj = JSON.parse(raw)
  } catch {
    process.exit(1)
  }
  const target = digTargetPath(obj)
  if (!target) process.exit(1)
  process.stdout.write(target)
} else if (command === "prose-command-guard") {
  // Claude Bash PreToolUse JSON → 真正的正文写入目标 → 共享核阻断原因。只识别共享核明确
  // 支持的重定向/tee/touch/cp/mv/install 写法；grep 等只读提及不会产生 target。无目标正常
  // 放行；解析/共享核异常用独立退出码交给 bash 壳显式告警后 fail-open，不能伪装成“无目标”。
  const root = args[0]
  const raw = process.env.HOOK_INPUT || readStdin()
  try {
    if (!root || !raw) process.exit(0)
    const obj = JSON.parse(raw)
    const shellCommand = digCommand(obj)
    if (!shellCommand) process.exit(0)
    let base = root
    const requestedBase = core.existingDir(digWorkingDirectory(obj))
    if (requestedBase) {
      const relative = path.relative(path.resolve(root), requestedBase)
      if (!relative.startsWith("..") && !path.isAbsolute(relative)) base = requestedBase
    }
    const seen = new Set()
    for (const target of core.extractProseTargets(shellCommand)) {
      const absolute = core.resolveTarget(root, target, base)
      if (seen.has(absolute)) continue
      seen.add(absolute)
      const reason = core.proseBlockReason(root, absolute)
      if (reason) {
        process.stdout.write(`${reason}（已从 Bash 命令识别到正文写入目标。）`)
        break
      }
    }
  } catch (error) {
    const detail = error && error.message ? error.message : String(error)
    process.stderr.write(`[story-guard] Bash 正文目标解析失败，已降级放行：${detail}`)
    process.exit(3)
  }
} else if (command === "prose-net") {
  // 轻量确定性网（含毒句式）。字数只由 storyctl 的公开命令测量，不在 Adapter 内复制。
  // 读文件失败静默退出（兜底不反噬流程）。
  const absolute = args[0]
  let text
  try {
    text = fs.readFileSync(absolute, "utf8")
  } catch {
    process.exit(0)
  }
  const out = core.proseNetFindings(text)
  if (out.length) process.stdout.write(out.join("\n"))
} else if (command === "prose-toxic") {
  // 毒句式确定性检测单跑（供 guard 前置门 / 手工复扫调用；prose-net 已含同一组结果）。
  // 契约：stdout 空 = 干净；非空 = findings 行（每行一条，末行为清零要求 + 完整扫描提示）。
  // 文件读不了或任何内部异常一律 exit 0 静默放行（与本 CLI 的降级哲学一致，兜底不反噬流程）。
  const absolute = args[0]
  try {
    const text = fs.readFileSync(absolute, "utf8")
    const out = core.toxicPhraseFindings(text)
    if (out.length) process.stdout.write(out.join("\n"))
  } catch {
    process.exit(0)
  }
} else if (command === "tracking-checkpoint") {
  // 追踪检查点门（BLOCKING 面）：guard-outline-before-prose.sh 调本子命令复用共享核
  // trackingCheckpointIssue，与 codex py / opencode / zcode 同一份判定（issue #305 之前
  // Claude 侧独缺这道门，同一工程同一次写正文，主力端放行、另三端拦下）。
  // 用法：tracking-checkpoint <root> <bookDir> <上一章号|->
  //   首建新章传上一章号，做「上一章事务是否已提交」的顺序校验；
  //   正文已存在（续写/改稿/回炉）传 `-`，只校验 state 自身的存在/schema/修订一致性。
  // 契约：stdout 空 = 放行；非空 = 完整拦截文案，与 core.proseBlockReason 逐字一致。
  // node 缺席时 bash 侧根本不调本子命令（等同放行），故内部异常也一律 exit 0 静默放行，
  // 与本 CLI 其余子命令的降级哲学一致（兜底不反噬流程）。
  const [root, book, expectedRaw] = args
  try {
    // 注意别写成 Number(expectedRaw) 直接判整数：空串会被转成 0，把「续写」误当成
    // 「首建第 1 章」去校验顺序。先排掉空串/缺省/占位符 `-`。
    const expected =
      expectedRaw && expectedRaw !== "-" && Number.isInteger(Number(expectedRaw))
        ? Number(expectedRaw)
        : null
    const issue = core.trackingCheckpointIssue(book, true, expected)
    if (issue) process.stdout.write(`⛔ 写正文被拦截：${core.safeRelative(root, book)} 的${issue}。`)
  } catch {
    process.exit(0)
  }
} else if (command === "is-git-commit") {
  // git commit 侦测。命令优先取 STORY_COMMIT_COMMAND，缺省再从 HOOK_INPUT 挖 command/cmd/script。
  // 用共享核 isGitCommitCommand（js 分词语义，与 OpenCode/ZCode 一致；对「引号内分隔符」这类
  // 边界与旧 python shlex 有已文档化、仅 advisory 的差异）。是 git commit → exit 0，否则 exit 1。
  let raw = process.env.STORY_COMMIT_COMMAND || ""
  if (!raw) {
    const hookInput = process.env.HOOK_INPUT || ""
    if (!hookInput) process.exit(1)
    let obj
    try {
      obj = JSON.parse(hookInput)
    } catch {
      obj = {}
    }
    raw = digCommand(obj)
  }
  if (!raw) process.exit(1)
  process.exit(core.isGitCommitCommand(raw) ? 0 : 1)
} else if (command === "continuity") {
  // 跨批连续性兜底：追踪 staleness + 章节标题去重。用共享核 continuityFindings（消息串与旧
  // python 逐字一致；多书/并列去重的排序按 js 语义，仅影响 advisory 顺序）。
  const root = args[0]
  const out = core.continuityFindings(root)
  if (out.length) process.stdout.write(out.join("\n") + "\n")
} else if (command === "analysis-input-guard") {
  // chapter-extractor 的 PreToolUse(Write) 内联守卫：它只许把批次结果写到
  // {拆文目录}/_analysis_cache/输入-{RAW|REUSE}-{起章}-{止章}.md。拆文目录以存在
  // chapter_index.csv 或 _progress.md 认定，且必须在项目根内。exit 2 阻断并把原因交回子代理；
  // 读不到输入视为无从判断，放行（提交脚本仍会完整校验文件内容）。
  const raw = process.env.HOOK_INPUT || readStdin()
  let obj
  try {
    obj = JSON.parse(raw)
  } catch {
    process.exit(0)
  }
  const target = digTargetPath(obj)
  if (!target) process.exit(0)
  const root = path.resolve(process.env.CLAUDE_PROJECT_DIR || digString(obj, ["cwd"]) || process.cwd())
  const absolute = path.resolve(root, target)
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
  const relative = path.relative(root, absolute)
  if (relative.startsWith("..") || path.isAbsolute(relative)) reasons.push("路径在项目目录之外")
  if (reasons.length) {
    process.stderr.write(
      `⛔ chapter-extractor 写入被拦截：${target}\n${reasons.join("；")}。\n` +
        "只允许写调用方给的 {拆文目录}/_analysis_cache/输入-{批次ID}.md（批次 ID 如 RAW-4-6），不写其他文件。"
    )
    process.exit(2)
  }
} else {
  process.exit(2)
}
