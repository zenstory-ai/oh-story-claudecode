#!/usr/bin/env node
"use strict"

import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { execFileSync, spawnSync } from "node:child_process"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const require = createRequire(import.meta.url)
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const HOOKS_SRC = path.join(REPO_ROOT, "skills/story-setup/references/zcode/hooks")
const CONTRACT = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "scripts/current-contract.json"), "utf8"))
const CURRENT_AGENTS_VERSION = CONTRACT.agents_version

function mkTmp(prefix) {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)))
}

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content, "utf8")
}

// 细纲须写了内容（不计 # 号和空白 ≥30 字）写正文守卫才放行；空文件会被当成空细纲拦下。
function writeOutline(file) {
  write(file, "# 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。\n")
}

function writeCleanState(book, lastCommitted = 0, revision = 0) {
  write(
    path.join(book, "追踪/_tracking-state.json"),
    JSON.stringify({ schema_version: 4, state_revision: revision, last_committed_chapter: lastCommitted }) + "\n"
  )
  write(path.join(book, "追踪/上下文.md"), `> 状态修订：${revision}\n`)
}

function deployZCodeHooks(root) {
  const dst = path.join(root, ".zcode/hooks")
  fs.mkdirSync(dst, { recursive: true })
  fs.copyFileSync(path.join(HOOKS_SRC, "story_zcode_hook.js"), path.join(dst, "story_zcode_hook.js"))
  fs.copyFileSync(path.join(HOOKS_SRC, "story_hook_core.js"), path.join(dst, "story_hook_core.js"))
  return path.join(dst, "story_zcode_hook.js")
}

function runHook(hook, event, payload, { cwd, env = {} } = {}) {
  const res = spawnSync(process.execPath, [hook, event], {
    cwd,
    input: typeof payload === "string" ? payload : JSON.stringify(payload),
    encoding: "utf8",
    env: { ...process.env, ...env },
  })
  assert.equal(res.status, 0, `${event} exited ${res.status}: ${res.stderr}`)
  return res.stdout
}

function assertContract(output, expectedEvent, label) {
  assert.ok(output, `${label}: expected non-empty JSON stdout`)
  const obj = JSON.parse(output)
  assert.deepEqual(Object.keys(obj), ["hookSpecificOutput"], `${label}: unexpected top-level keys`)
  const specific = obj.hookSpecificOutput
  const allowed = new Set(["hookEventName", "additionalContext"])
  if (expectedEvent === "PreToolUse") {
    allowed.add("permissionDecision")
    allowed.add("permissionDecisionReason")
    allowed.add("updatedInput")
  }
  for (const key of Object.keys(specific)) {
    assert.ok(allowed.has(key), `${label}: disallowed key ${key} for ${expectedEvent}`)
  }
  assert.equal(specific.hookEventName, expectedEvent, `${label}: hookEventName mismatch`)
  return specific
}

function assertDenied(output, label) {
  const specific = assertContract(output, "PreToolUse", label)
  assert.equal(specific.permissionDecision, "deny", `${label}: expected deny`)
  assert.ok(specific.permissionDecisionReason, `${label}: expected non-empty denial reason`)
  return specific.permissionDecisionReason
}

test("ZCode pre-tool-prose-guard covers outlines, tracking, cwd resolution, cross-volume safety, ApplyPatch, Bash, short, and story-import", () => {
  const root = mkTmp("zcode-guard-")
  try {
    const hook = deployZCodeHooks(root)
    const invoke = (event, payload) =>
      runHook(hook, event, payload, { cwd: root, env: { ZCODE_PROJECT_DIR: root } })

    fs.mkdirSync(path.join(root, "book/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "book/大纲"), { recursive: true })
    fs.mkdirSync(path.join(root, "book/设定"), { recursive: true })

    assertDenied(
      invoke("pre-tool-prose-guard", {
        hook_event_name: "PreToolUse",
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第001章_开端.md" },
      }),
      "long prose without outline"
    )

    writeOutline(path.join(root, "book/大纲/细纲_第1章.md"))
    let reason = assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第001章_开端.md" },
      }),
      "long prose without tracking metadata"
    )
    assert.match(reason, /_tracking-state\.json 缺失/)

    writeCleanState(path.join(root, "book"))
    write(path.join(root, "book/大纲/细纲_第1章.md"), "# 第1章 细纲\n## 目标情绪\n")
    reason = assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第001章_开端.md" },
      }),
      "long prose with an empty outline"
    )
    assert.match(reason, /细纲（book\/大纲\/细纲_第1章\.md）是空的/)

    writeOutline(path.join(root, "book/大纲/细纲_第1章.md"))
    assert.equal(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第001章_开端.md" },
      }),
      "",
      "long prose with outline"
    )

    // Bare project without scaffolding fails closed; relative targets resolve from hook cwd
    fs.mkdirSync(path.join(root, "bare/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "cwd-book/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "cwd-book/大纲"), { recursive: true })
    assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "bare/正文/第1章_首章.md" },
      }),
      "bare long project without scaffolding"
    )

    const relPayload = {
      cwd: path.resolve(root, "cwd-book"),
      tool_name: "Write",
      tool_input: { file_path: "正文/第8章_相对.md" },
    }
    assert.match(
      assertDenied(invoke("pre-tool-prose-guard", relPayload), "relative prose target from hook cwd"),
      /cwd-book\/大纲/
    )
    writeOutline(path.join(root, "cwd-book/大纲/细纲_第8章.md"))
    assertDenied(invoke("pre-tool-prose-guard", relPayload), "relative prose target without tracking metadata")
    writeCleanState(path.join(root, "cwd-book"), 7)
    assert.equal(invoke("pre-tool-prose-guard", relPayload), "", "relative prose target with cwd-local outline")

    // Existing prose rewrite: corrupt state still hard-denies; manual 上下文.md mismatch emits non-blocking advisory
    write(path.join(root, "book/正文/第009章_已存在.md"), "")
    write(path.join(root, "book/追踪/_tracking-state.json"), "{corrupt-json\n")
    reason = assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第009章_已存在.md" },
      }),
      "existing prose rewrite with corrupt tracking state"
    )
    assert.match(reason, /无法解析/)

    write(
      path.join(root, "book/追踪/_tracking-state.json"),
      JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 0 }) + "\n"
    )
    let softSpec = assertContract(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第009章_已存在.md" },
      }),
      "PreToolUse",
      "existing prose rewrite with mismatched derived state (soft advisory)"
    )
    assert.equal(softSpec.permissionDecision, undefined)
    assert.match(softSpec.additionalContext, /写正文前软门禁提醒/)
    assert.match(softSpec.additionalContext, /状态修订/)
    writeCleanState(path.join(root, "book"), 1)

    // Prior-chapter toxic prose & chapter jump emit strict-schema non-blocking PreToolUse additionalContext
    write(path.join(root, "book/正文/第001章_旧.md"), "# 第1章\n声音不大，却带着一股狠劲。他声音不高，却压住了整间屋子。\n")
    writeOutline(path.join(root, "book/大纲/细纲_第2章.md"))
    softSpec = assertContract(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第002章_新局.md" },
      }),
      "PreToolUse",
      "prior-chapter toxic prose soft advisory"
    )
    assert.equal(softSpec.permissionDecision, undefined)
    assert.match(softSpec.additionalContext, /疑似 AI 毒句式/)
    fs.unlinkSync(path.join(root, "book/大纲/细纲_第2章.md"))

    writeOutline(path.join(root, "book/大纲/细纲_第5章.md"))
    softSpec = assertContract(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "book/正文/第005章_跳章.md" },
      }),
      "PreToolUse",
      "out-of-order chapter jump soft advisory"
    )
    assert.equal(softSpec.permissionDecision, undefined)
    assert.match(softSpec.additionalContext, /有意跳章起草/)
    writeCleanState(path.join(root, "book"))

    // Windows cross-volume safety for isPathInside
    const mod = require(path.join(HOOKS_SRC, "story_zcode_hook.js"))
    assert.equal(mod.isPathInside("C:\\repo", "D:\\elsewhere", path.win32), false)
    assert.equal(mod.isPathInside("C:\\repo", "C:\\repo\\..draft", path.win32), true)
    assert.equal(mod.isPathInside("C:\\repo", "C:\\repo\\sub", path.win32), true)

    // ApplyPatch and Bash write vs read-only mention
    assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "ApplyPatch",
        tool_input: { patch: "*** Begin Patch\n*** Add File: book/正文/第002章_新局.md\n+正文\n*** End Patch" },
      }),
      "ApplyPatch prose without outline"
    )
    assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Bash",
        tool_input: { command: "echo x | tee book/正文/第003章_命令.md" },
      }),
      "Bash prose write without outline"
    )
    assert.equal(
      invoke("pre-tool-prose-guard", {
        tool_name: "Bash",
        tool_input: { command: "grep -n book/正文/第003章_命令.md notes.md" },
      }),
      "",
      "Bash mention without write"
    )

    // Short prose
    write(path.join(root, "short/设定.md"), "")
    assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "short/正文.md" },
      }),
      "short prose without outline"
    )
    write(path.join(root, "short/小节大纲.md"), "")
    assert.equal(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "short/正文.md" },
      }),
      "",
      "short prose with outline"
    )

    // story-import migration window vs post-init tracking guard
    fs.mkdirSync(path.join(root, "impbook/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "拆文库/impbook"), { recursive: true })
    assert.equal(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "impbook/正文/第1章_导入.md" },
      }),
      "",
      "story-import long migration"
    )
    writeOutline(path.join(root, "impbook/大纲/细纲_第2章.md"))
    write(path.join(root, "impbook/追踪/_tracking-state.json"), "{corrupt-json\n")
    write(path.join(root, "impbook/追踪/上下文.md"), "> 状态修订：0\n")
    assertDenied(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "impbook/正文/第2章_导入后续.md" },
      }),
      "imported project must not permanently bypass corrupt tracking guard"
    )
    write(
      path.join(root, "impbook/追踪/_tracking-state.json"),
      JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 1 }) + "\n"
    )
    softSpec = assertContract(
      invoke("pre-tool-prose-guard", {
        tool_name: "Write",
        tool_input: { file_path: "impbook/正文/第2章_导入后续.md" },
      }),
      "PreToolUse",
      "imported project manual context mismatch emits soft advisory"
    )
    assert.equal(softSpec.permissionDecision, undefined)
    assert.match(softSpec.additionalContext, /状态修订/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("ZCode post-tool-prose-check, session-start (context, agents_version staleness, continuity), commit advisory, fail-open, and self-location", () => {
  const tmp = mkTmp("zcode-session-")
  const root = path.join(tmp, "project")
  try {
    const hook = deployZCodeHooks(root)
    const invoke = (event, payload) =>
      runHook(hook, event, payload, { cwd: root, env: { ZCODE_PROJECT_DIR: root } })

    fs.mkdirSync(path.join(root, "book/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "book/大纲"), { recursive: true })
    fs.mkdirSync(path.join(root, "book/设定"), { recursive: true })
    write(path.join(root, "short/设定.md"), "")
    write(path.join(root, "short/小节大纲.md"), "")

    // post-tool-prose-check (Write + Bash)
    write(path.join(root, "short/正文.md"), "这是正文里的 TODO，而且最后一句被截断")
    let specific = assertContract(
      invoke("post-tool-prose-check", {
        hook_event_name: "PostToolUse",
        tool_name: "Write",
        tool_input: { file_path: "short/正文.md" },
      }),
      "PostToolUse",
      "post-write prose check"
    )
    assert.match(specific.additionalContext, /占位符/)
    assert.match(specific.additionalContext, /疑似截断/)

    write(path.join(root, "short/正文.md"), "命令写入的正文 TODO。")
    specific = assertContract(
      invoke("post-tool-prose-check", {
        hook_event_name: "PostToolUse",
        tool_name: "Bash",
        tool_input: { command: "cat input.txt > short/正文.md" },
      }),
      "PostToolUse",
      "post-bash prose check"
    )
    assert.match(specific.additionalContext, /占位符/)

    // session-start: stale agents_version warning
    write(
      path.join(root, ".story-deployed"),
      [
        `agents_version: ${CURRENT_AGENTS_VERSION - 1}`,
        "setup_skill_version: 1.2.9",
        "target_cli: zcode",
        "resolver_strategy: project-local-skill-reference",
        "references_dir: .zcode/skills/story-setup/references/agent-references",
        "",
      ].join("\n")
    )
    write(path.join(root, ".active-book"), "book\n")
    write(path.join(root, "book/追踪/上下文.md"), "# 上下文\n")
    specific = assertContract(
      invoke("session-start", { hook_event_name: "SessionStart", source: "compact" }),
      "SessionStart",
      "session start stale agents_version"
    )
    assert.match(specific.additionalContext, /当前书目/)
    assert.match(specific.additionalContext, new RegExp(`低于 v${CURRENT_AGENTS_VERSION}`))
    assert.match(specific.additionalContext, /\$story-setup/)

    // session-start: future agents_version downgrade warning
    write(
      path.join(root, ".story-deployed"),
      `agents_version: ${CURRENT_AGENTS_VERSION + 1}\ntarget_cli: zcode\n`
    )
    specific = assertContract(
      invoke("session-start", { hook_event_name: "SessionStart", source: "resume" }),
      "SessionStart",
      "session start future agents_version"
    )
    assert.match(specific.additionalContext, new RegExp(`高于本 hook 支持的 v${CURRENT_AGENTS_VERSION}`))
    assert.match(specific.additionalContext, /不要降级覆盖/)

    // session-start: missing numeric agents_version warning
    write(path.join(root, ".story-deployed"), "target_cli: zcode\n")
    specific = assertContract(
      invoke("session-start", { hook_event_name: "SessionStart", source: "resume" }),
      "SessionStart",
      "session start missing numeric agents_version"
    )
    assert.match(specific.additionalContext, /缺少数字 agents_version/)

    // session-start: current agents_version stays silent on version check
    write(
      path.join(root, ".story-deployed"),
      `agents_version: ${CURRENT_AGENTS_VERSION}\ntarget_cli: zcode\n`
    )
    specific = assertContract(
      invoke("session-start", { hook_event_name: "SessionStart", source: "resume" }),
      "SessionStart",
      "session start current agents_version"
    )
    assert.ok(!specific.additionalContext.includes(`低于 v${CURRENT_AGENTS_VERSION}`))
    assert.ok(!specific.additionalContext.includes("高于本 hook"))
    assert.ok(!specific.additionalContext.includes("缺少数字 agents_version"))

    // session-start: tracking revision mismatch
    write(
      path.join(root, "book/追踪/_tracking-state.json"),
      JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 0 }) + "\n"
    )
    specific = assertContract(
      invoke("session-start", { hook_event_name: "SessionStart", source: "resume" }),
      "SessionStart",
      "session tracking mismatch warning"
    )
    assert.match(specific.additionalContext, /状态修订/)
    writeCleanState(path.join(root, "book"))

    // session-start: continuity (stale context via fs.utimesSync instead of sleep 2 + duplicate titles)
    const ctxFile = path.join(root, "book/追踪/上下文.md")
    write(ctxFile, "# 旧上下文\n")
    const oldTime = new Date(Date.now() - 10_000)
    fs.utimesSync(ctxFile, oldTime, oldTime)
    write(path.join(root, "book/正文/第001章_撞名.md"), "# 第1章\n正文。\n")
    write(path.join(root, "book/正文/第002章_撞名.md"), "# 第2章\n正文。\n")
    specific = assertContract(
      invoke("session-start", { hook_event_name: "SessionStart", source: "resume" }),
      "SessionStart",
      "session continuity"
    )
    assert.match(specific.additionalContext, /续写状态卡更早/)
    assert.match(specific.additionalContext, /标题重复/)

    // pre-tool-commit-advisory
    execFileSync("git", ["-C", root, "init", "-q"])
    execFileSync("git", ["-C", root, "config", "user.email", "zcode-hook@example.invalid"])
    execFileSync("git", ["-C", root, "config", "user.name", "zcode-hook-test"])
    write(path.join(root, "book/正文/第010章_属性.md"), "年龄：18\n")
    execFileSync("git", ["-C", root, "add", path.join(root, "book/正文/第010章_属性.md")])
    specific = assertContract(
      invoke("pre-tool-commit-advisory", {
        tool_name: "Bash",
        tool_input: { command: "git -C . commit -m test" },
      }),
      "PreToolUse",
      "commit advisory"
    )
    assert.match(specific.additionalContext, /硬编码角色属性/)
    assert.equal(
      invoke("pre-tool-commit-advisory", {
        tool_name: "Bash",
        tool_input: { command: "echo git commit docs" },
      }),
      "",
      "non-commit command"
    )

    // malformed input fail-open
    assert.equal(
      runHook(hook, "pre-tool-prose-guard", "not-json", { cwd: root, env: { ZCODE_PROJECT_DIR: root } }),
      "",
      "malformed input fail-open"
    )

    // deployed __dirname self-location with env vars unset and unrelated cwd
    writeOutline(path.join(root, "book/大纲/细纲_第8章.md"))
    writeCleanState(path.join(root, "book"), 7)
    const cleanEnv = { ...process.env }
    delete cleanEnv.ZCODE_PROJECT_DIR
    delete cleanEnv.CLAUDE_PROJECT_DIR
    const selfRes = spawnSync(process.execPath, [hook, "pre-tool-prose-guard"], {
      cwd: tmp,
      input: JSON.stringify({ tool_name: "Write", tool_input: { file_path: "book/正文/第8章_自定位.md" } }),
      encoding: "utf8",
      env: cleanEnv,
    })
    assert.equal(selfRes.status, 0, selfRes.stderr)
    assert.equal(selfRes.stdout, "", "deployed __dirname self-location")
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})
