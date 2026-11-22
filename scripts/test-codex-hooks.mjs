#!/usr/bin/env node
"use strict"

import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import childProcess, { execFileSync, spawnSync } from "node:child_process"
import { createRequire, syncBuiltinESMExports } from "node:module"
import { fileURLToPath } from "node:url"

const require = createRequire(import.meta.url)
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const HOOKS_SRC = path.join(REPO_ROOT, "skills/story-setup/references/codex/hooks")

function mkTmp(prefix) {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)))
}

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content, "utf8")
}

function writeOutline(file) {
  write(file, "# 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。\n")
}

function writeCleanState(book, lastCommitted = 0) {
  write(
    path.join(book, "追踪/_tracking-state.json"),
    JSON.stringify({ schema_version: 4, state_revision: 0, last_committed_chapter: lastCommitted }) + "\n"
  )
  write(path.join(book, "追踪/上下文.md"), "> 状态修订：0\n")
}

function deployCodexHooks(root) {
  const dst = path.join(root, ".codex/hooks")
  fs.mkdirSync(dst, { recursive: true })
  for (const name of ["story_codex_hook.js", "story_hook_core.js", "run-story-hook.sh", "run-story-hook.cmd"]) {
    fs.copyFileSync(path.join(HOOKS_SRC, name), path.join(dst, name))
  }
  fs.copyFileSync(path.join(HOOKS_SRC, "hooks.json"), path.join(root, ".codex/hooks.json"))
  fs.chmodSync(path.join(dst, "run-story-hook.sh"), 0o755)
  fs.chmodSync(path.join(dst, "story_codex_hook.js"), 0o755)
  return path.join(dst, "story_codex_hook.js")
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

function assertDenied(raw, label) {
  const obj = JSON.parse(raw)
  assert.equal(obj.hookSpecificOutput?.hookEventName, "PreToolUse", label)
  assert.equal(obj.hookSpecificOutput?.permissionDecision, "deny", label)
  assert.ok(obj.hookSpecificOutput?.permissionDecisionReason, label)
  return obj.hookSpecificOutput.permissionDecisionReason
}

test("Codex pre-tool-prose-guard, commit advisory, session-start, compact, and stop sweep", () => {
  const root = mkTmp("codex-hook-test-")
  try {
    const hook = deployCodexHooks(root)
    execFileSync("git", ["-C", root, "init", "-q"])
    execFileSync("git", ["-C", root, "config", "user.email", "codex-hook@example.invalid"])
    execFileSync("git", ["-C", root, "config", "user.name", "codex-hook-test"])
    const invoke = (event, payload) => runHook(hook, event, payload, { cwd: root, env: { CODEX_PROJECT_DIR: root } })

    fs.mkdirSync(path.join(root, "book/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "book/大纲"), { recursive: true })
    fs.mkdirSync(path.join(root, "book/设定"), { recursive: true })

    // Missing outline
    let reason = assertDenied(
      invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: "cat > book/正文/第001章_开端.md <<EOF\n正文\nEOF" } }),
      "long prose without outline"
    )
    assert.match(reason, /细纲_第001章\.md/)

    // Unexpanded shell var
    reason = assertDenied(
      invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: 'PROJ=$PWD/book; cat > "$PROJ/正文/第001章_开端.md" <<EOF\n正文\nEOF' } }),
      "unexpanded shell var"
    )
    assert.match(reason, /未展开的 shell 变量/)
    assert.ok(!reason.includes("缺少细纲"))

    // Missing tracking state
    writeOutline(path.join(root, "book/大纲/细纲_第1章.md"))
    reason = assertDenied(
      invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: "cat > book/正文/第001章_开端.md <<EOF\n正文\nEOF" } }),
      "missing tracking state"
    )
    assert.match(reason, /_tracking-state\.json 缺失/)

    // Empty outline
    writeCleanState(path.join(root, "book"))
    write(path.join(root, "book/大纲/细纲_第1章.md"), "# 第1章 细纲\n## 目标情绪\n")
    reason = assertDenied(
      invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: "cat > book/正文/第001章_开端.md <<EOF\n正文\nEOF" } }),
      "empty outline"
    )
    assert.match(reason, /细纲（book\/大纲\/细纲_第1章\.md）是空的/)

    // Valid outline + state allows
    writeOutline(path.join(root, "book/大纲/细纲_第1章.md"))
    assert.equal(
      invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: "cat > book/正文/第001章_开端.md <<EOF\n正文\nEOF" } }),
      ""
    )

    // Bare project & relative target from hook cwd
    fs.mkdirSync(path.join(root, "bare/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "cwd-book/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "cwd-book/大纲"), { recursive: true })
    assertDenied(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "bare/正文/第1章_首章.md" } }), "bare project")

    const relPayload = { cwd: path.join(root, "cwd-book"), tool_name: "Write", tool_input: { file_path: "正文/第8章_相对.md" } }
    assert.match(assertDenied(invoke("pre-tool-prose-guard", relPayload), "relative cwd"), /cwd-book\/大纲/)
    writeOutline(path.join(root, "cwd-book/大纲/细纲_第8章.md"))
    assertDenied(invoke("pre-tool-prose-guard", relPayload), "relative cwd missing tracking")
    writeCleanState(path.join(root, "cwd-book"), 7)
    assert.equal(invoke("pre-tool-prose-guard", relPayload), "")

    // apply_patch, existing rewrite, corrupt state (HARD) vs mismatch/jump/prior-toxic (SOFT)
    assertDenied(
      invoke("pre-tool-prose-guard", { tool_name: "apply_patch", tool_input: { command: "*** Begin Patch\n*** Add File: book/正文/第002章_新局.md\n+正文\n*** End Patch\n" } }),
      "apply_patch missing outline"
    )
    write(path.join(root, "book/正文/第009章_已存在.md"), "")
    assert.equal(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "book/正文/第009章_已存在.md" } }), "")

    // Corrupt _tracking-state.json still hard-denies
    write(path.join(root, "book/追踪/_tracking-state.json"), "{not-json\n")
    assert.match(
      assertDenied(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "book/正文/第009章_已存在.md" } }), "corrupt state"),
      /无法解析/
    )

    // Manual 上下文.md revision mismatch is softened to non-blocking additionalContext (no permissionDecision:"deny")
    write(path.join(root, "book/追踪/_tracking-state.json"), JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 0 }))
    const mismatchOut = JSON.parse(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "book/正文/第009章_已存在.md" } }))
    assert.equal(mismatchOut.hookSpecificOutput?.hookEventName, "PreToolUse")
    assert.equal(mismatchOut.hookSpecificOutput?.permissionDecision, undefined)
    assert.match(mismatchOut.hookSpecificOutput?.additionalContext, /写正文前软门禁提醒/)
    assert.match(mismatchOut.hookSpecificOutput?.additionalContext, /状态修订/)
    writeCleanState(path.join(root, "book"), 1)

    // Prior-chapter toxic prose & out-of-order chapter jump emit non-blocking additionalContext
    write(path.join(root, "book/正文/第001章_旧.md"), "# 第1章\n声音不大，却带着一股狠劲。他声音不高，却压住了整间屋子。\n")
    writeOutline(path.join(root, "book/大纲/细纲_第2章.md"))
    const toxicOut = JSON.parse(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "book/正文/第002章_新局.md" } }))
    assert.equal(toxicOut.hookSpecificOutput?.permissionDecision, undefined)
    assert.match(toxicOut.hookSpecificOutput?.additionalContext, /疑似 AI 毒句式/)
    writeOutline(path.join(root, "book/大纲/细纲_第5章.md"))
    const jumpOut = JSON.parse(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "book/正文/第005章_跳章.md" } }))
    assert.equal(jumpOut.hookSpecificOutput?.permissionDecision, undefined)
    assert.match(jumpOut.hookSpecificOutput?.additionalContext, /有意跳章起草/)
    writeCleanState(path.join(root, "book"))

    // Short prose & story-import window
    write(path.join(root, "short/设定.md"), "")
    assertDenied(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "short/正文.md" } }), "short missing outline")
    write(path.join(root, "short/小节大纲.md"), "")
    assert.equal(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "short/正文.md" } }), "")

    fs.mkdirSync(path.join(root, "impbook/正文"), { recursive: true })
    fs.mkdirSync(path.join(root, "拆文库/impbook"), { recursive: true })
    assert.equal(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "impbook/正文/第1章_导入.md" } }), "")
    writeOutline(path.join(root, "impbook/大纲/细纲_第2章.md"))
    write(path.join(root, "impbook/追踪/_tracking-state.json"), "{corrupt-json\n")
    write(path.join(root, "impbook/追踪/上下文.md"), "> 状态修订：0\n")
    assertDenied(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "impbook/正文/第2章_导入后续.md" } }), "post-import corrupt state")
    write(path.join(root, "impbook/追踪/_tracking-state.json"), JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 1 }))
    const impSoftOut = JSON.parse(invoke("pre-tool-prose-guard", { tool_name: "Write", tool_input: { file_path: "impbook/正文/第2章_导入后续.md" } }))
    assert.equal(impSoftOut.hookSpecificOutput?.permissionDecision, undefined)
    assert.match(impSoftOut.hookSpecificOutput?.additionalContext, /状态修订/)

    // Bash mention vs write
    assert.equal(invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: "grep -n book/正文/第7章.md notes.md" } }), "")
    assertDenied(invoke("pre-tool-prose-guard", { tool_name: "Bash", tool_input: { command: "cat draft.md > book/正文/第7章_x.md" } }), "bash write")

    // Commit advisory
    write(path.join(root, "book/正文/第1章.md"), "年龄：18\n")
    write(path.join(root, "short/正文.md"), "身高: 180\n")
    execFileSync("git", ["-C", root, "add", "book/正文/第1章.md", "short/正文.md"])
    const commitOut = JSON.parse(invoke("pre-tool-commit-advisory", { tool_name: "Bash", tool_input: { command: "git commit -m test" } }))
    assert.match(commitOut.hookSpecificOutput.additionalContext, /正文硬编码角色属性/)
    assert.match(commitOut.hookSpecificOutput.additionalContext, /short\/正文\.md/)
    assert.equal(invoke("pre-tool-commit-advisory", { tool_name: "Bash", tool_input: { command: "echo git commit docs" } }), "")

    // SessionStart + agents_version staleness + compact + stop sweep
    const contract = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "scripts/current-contract.json"), "utf8"))
    const currentAgentsVer = contract.agents_version
    write(path.join(root, ".active-book"), "book\n")

    write(path.join(root, ".story-deployed"), `agents_version: ${currentAgentsVer - 1}\ntarget_cli: codex\n`)
    const ssStale = JSON.parse(invoke("session-start", { hook_event_name: "SessionStart" }))
    assert.match(ssStale.hookSpecificOutput.additionalContext, new RegExp(`低于 v${currentAgentsVer}`))
    assert.match(ssStale.hookSpecificOutput.additionalContext, /\$story-setup/)

    write(path.join(root, ".story-deployed"), `agents_version: ${currentAgentsVer + 1}\ntarget_cli: codex\n`)
    const ssFuture = JSON.parse(invoke("session-start", { hook_event_name: "SessionStart" }))
    assert.match(ssFuture.hookSpecificOutput.additionalContext, new RegExp(`高于本 hook 支持的 v${currentAgentsVer}`))
    assert.match(ssFuture.hookSpecificOutput.additionalContext, /不要降级覆盖/)

    write(path.join(root, ".story-deployed"), "target_cli: codex\n")
    const ssMissingVer = JSON.parse(invoke("session-start", { hook_event_name: "SessionStart" }))
    assert.match(ssMissingVer.hookSpecificOutput.additionalContext, /缺少数字 agents_version/)

    write(path.join(root, ".story-deployed"), `agents_version: ${currentAgentsVer}\ntarget_cli: codex\n`)
    const ss = JSON.parse(invoke("session-start", { hook_event_name: "SessionStart" }))
    assert.match(ss.hookSpecificOutput.additionalContext, /Active book/)
    assert.ok(!ss.hookSpecificOutput.additionalContext.includes(`低于 v${currentAgentsVer}`))
    assert.ok(!ss.hookSpecificOutput.additionalContext.includes("高于本 hook"))
    assert.ok(!ss.hookSpecificOutput.additionalContext.includes("缺少数字 agents_version"))
    const preC = JSON.parse(invoke("pre-compact", { hook_event_name: "PreCompact" }))
    assert.match(preC.systemMessage, /Story Compact Summary/)
    const postC = JSON.parse(invoke("post-compact", { hook_event_name: "PostCompact" }))
    assert.match(postC.systemMessage, /Story Compact Summary/)

    // Stop sweep flags untracked truncated prose and ignores committed files
    const pad = "江晨握紧拳头慢慢走向门口盘算着每一步。".repeat(6)
    write(path.join(root, "book/正文/第006章_截断.md"), `# 第6章\n\n${pad}\n他冲过去一拳砸在`)
    const stopHit = JSON.parse(invoke("stop", { hook_event_name: "Stop" }))
    assert.equal(stopHit.continue, true)
    assert.match(stopHit.systemMessage, /截断/)
    assert.match(stopHit.systemMessage, /第006章_截断\.md/)
    execFileSync("git", ["-C", root, "add", "-A"])
    execFileSync("git", ["-C", root, "commit", "-qm", "wip"])
    const stopClean = JSON.parse(invoke("stop", { hook_event_name: "Stop" }))
    assert.deepEqual(stopClean, { continue: true })

    // SessionStart continuity (staleness + duplicate titles)
    writeCleanState(path.join(root, "contbook"))
    const ctxFile = path.join(root, "contbook/追踪/上下文.md")
    const oldTime = new Date(Date.now() - 10_000)
    fs.utimesSync(ctxFile, oldTime, oldTime)
    write(path.join(root, "contbook/正文/第001章_决战.md"), "# 第1章 决战\n正文。\n")
    write(path.join(root, "contbook/正文/第002章_决战.md"), "# 第2章 决战\n正文。\n")
    const ssCont = JSON.parse(invoke("session-start", { hook_event_name: "SessionStart" }))
    assert.match(ssCont.hookSpecificOutput.additionalContext, /续写状态卡更早/)
    assert.match(ssCont.hookSpecificOutput.additionalContext, /标题重复/)

    // __dirname self-location when env is bogus and cwd is unrelated
    writeOutline(path.join(root, "book/大纲/细纲_第8章.md"))
    writeCleanState(path.join(root, "book"), 7)
    const selfOut = runHook(
      hook,
      "pre-tool-prose-guard",
      { tool_name: "Write", tool_input: { file_path: "book/正文/第8章_x.md" } },
      { cwd: os.tmpdir(), env: { CODEX_PROJECT_DIR: path.join(root, "does-not-exist") } }
    )
    assert.equal(selfOut, "")
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("Codex non-git launcher root resolution, missing-deployment no-op, isPathInside, and windowsHide", () => {
  const tmp = mkTmp("codex-launcher-")
  try {
    const nonGit = path.join(tmp, "non-git-project")
    deployCodexHooks(nonGit)
    fs.mkdirSync(path.join(nonGit, "book/正文"), { recursive: true })
    fs.mkdirSync(path.join(nonGit, "book/大纲"), { recursive: true })
    const nested = path.join(nonGit, "nested/a/b")
    fs.mkdirSync(nested, { recursive: true })

    const hooksJson = JSON.parse(fs.readFileSync(path.join(nonGit, ".codex/hooks.json"), "utf8"))
    const entry = hooksJson.hooks.PreToolUse[0].hooks[0]
    const cleanEnv = { ...process.env }
    delete cleanEnv.CODEX_PROJECT_DIR
    delete cleanEnv.CLAUDE_PROJECT_DIR

    const payload = JSON.stringify({ tool_name: "Write", tool_input: { file_path: "book/正文/第004章_非Git.md" } })
    if (process.platform === "win32") {
      const res = spawnSync(entry.commandWindows, { cwd: nested, input: payload, encoding: "utf8", shell: true, env: cleanEnv })
      assert.equal(res.status, 0, res.stderr)
      assertDenied(res.stdout, "commandWindows nested deny")
    } else {
      const res = spawnSync("sh", ["-c", entry.command], { cwd: nested, input: payload, encoding: "utf8", env: cleanEnv })
      assert.equal(res.status, 0, res.stderr)
      assertDenied(res.stdout, "POSIX launcher nested deny")

      writeOutline(path.join(nonGit, "book/大纲/细纲_第4章.md"))
      writeCleanState(path.join(nonGit, "book"), 3)
      const allow = spawnSync("sh", ["-c", entry.command], { cwd: nested, input: payload, encoding: "utf8", env: cleanEnv })
      assert.equal(allow.status, 0, allow.stderr)
      assert.equal(allow.stdout, "")

      const noDeploy = path.join(tmp, "no-deploy/x/y")
      fs.mkdirSync(noDeploy, { recursive: true })
      const noop = spawnSync("sh", ["-c", entry.command], { cwd: noDeploy, input: payload, encoding: "utf8", env: cleanEnv })
      assert.equal(noop.status, 0)
      assert.equal(noop.stdout, "")
      assert.ok(!noop.stderr.includes("//.codex"))
    }

    // isPathInside cross-volume safety & windowsHide on git subprocesses
    const origSpawn = childProcess.spawnSync
    const calls = []
    try {
      childProcess.spawnSync = (cmd, args, opts) => {
        calls.push({ cmd, args, opts })
        return origSpawn(cmd, args, opts)
      }
      syncBuiltinESMExports()
      const hookPath = path.join(HOOKS_SRC, "story_codex_hook.js")
      delete require.cache[require.resolve(hookPath)]
      const mod = require(hookPath)
      assert.equal(mod.isPathInside("C:\\repo", "D:\\elsewhere", path.win32), false)
      assert.equal(mod.isPathInside("C:\\repo", "C:\\repo\\..draft", path.win32), true)
      assert.equal(mod.isPathInside("C:\\repo", "C:\\repo\\sub", path.win32), true)

      execFileSync("git", ["-C", nonGit, "init", "-q"])
      mod.findChangedProseFiles(nonGit)
      const gitCalls = calls.filter((c) => c.cmd === "git")
      assert.ok(gitCalls.length >= 3, "expected findChangedProseFiles to invoke git")
      assert.ok(gitCalls.every((c) => c.opts?.windowsHide === true), "every Codex hook git call must pass windowsHide: true")
    } finally {
      childProcess.spawnSync = origSpawn
      syncBuiltinESMExports()
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})

test("Codex hooks fail open when story_hook_core.js is missing or corrupt, and handle symlinked workspace roots", () => {
  const tmp = mkTmp("codex-failopen-")
  try {
    // Missing story_hook_core.js (direct hook + launcher)
    const missingProj = path.join(tmp, "missing-core")
    const missingHook = deployCodexHooks(missingProj)
    fs.rmSync(path.join(missingProj, ".codex/hooks/story_hook_core.js"))

    const stopDirect = runHook(missingHook, "stop", { hook_event_name: "Stop" }, { cwd: missingProj, env: { CODEX_PROJECT_DIR: missingProj } })
    assert.deepEqual(JSON.parse(stopDirect), { continue: true }, "stop must emit continue:true when story_hook_core.js is missing")
    const ssDirect = runHook(missingHook, "session-start", { hook_event_name: "SessionStart" }, { cwd: missingProj, env: { CODEX_PROJECT_DIR: missingProj } })
    assert.equal(ssDirect, "", "session-start must fail open cleanly when story_hook_core.js is missing")

    if (process.platform === "win32") {
      const launcher = path.join(missingProj, ".codex/hooks/run-story-hook.cmd")
      const stopLauncher = spawnSync(launcher, ["stop"], { cwd: missingProj, input: "{}", encoding: "utf8", shell: true })
      assert.equal(stopLauncher.status, 0, stopLauncher.stderr)
      assert.deepEqual(JSON.parse(stopLauncher.stdout.trim()), { continue: true })
      const ssLauncher = spawnSync(launcher, ["session-start"], { cwd: missingProj, input: "{}", encoding: "utf8", shell: true })
      assert.equal(ssLauncher.status, 0, ssLauncher.stderr)
    } else {
      const launcher = path.join(missingProj, ".codex/hooks/run-story-hook.sh")
      const stopLauncher = spawnSync("sh", [launcher, "stop"], { cwd: missingProj, input: "{}", encoding: "utf8" })
      assert.equal(stopLauncher.status, 0, stopLauncher.stderr)
      assert.deepEqual(JSON.parse(stopLauncher.stdout), { continue: true })
      const ssLauncher = spawnSync("sh", [launcher, "session-start"], { cwd: missingProj, input: "{}", encoding: "utf8" })
      assert.equal(ssLauncher.status, 0, ssLauncher.stderr)
      assert.equal(ssLauncher.stdout, "")
    }

    // Corrupt story_hook_core.js (syntax error / runtime throw)
    const corruptProj = path.join(tmp, "corrupt-core")
    const corruptHook = deployCodexHooks(corruptProj)
    fs.writeFileSync(path.join(corruptProj, ".codex/hooks/story_hook_core.js"), "throw new Error('corrupt core')\n", "utf8")

    const stopCorrupt = runHook(corruptHook, "stop", { hook_event_name: "Stop" }, { cwd: corruptProj, env: { CODEX_PROJECT_DIR: corruptProj } })
    assert.deepEqual(JSON.parse(stopCorrupt), { continue: true }, "stop must emit continue:true when story_hook_core.js is corrupt")
    const guardCorrupt = runHook(
      corruptHook,
      "pre-tool-prose-guard",
      { tool_name: "Write", tool_input: { file_path: "book/正文/第1章.md" } },
      { cwd: corruptProj, env: { CODEX_PROJECT_DIR: corruptProj } }
    )
    assert.equal(guardCorrupt, "", "pre-tool-prose-guard must fail open cleanly when story_hook_core.js is corrupt")

    // Symlinked workspace root with subdir input.cwd and unset CODEX_PROJECT_DIR
    if (process.platform !== "win32") {
      const realProj = path.join(tmp, "real-proj")
      deployCodexHooks(realProj)
      fs.mkdirSync(path.join(realProj, "sub-book/正文"), { recursive: true })
      fs.mkdirSync(path.join(realProj, "sub-book/大纲"), { recursive: true })
      const linkProj = path.join(tmp, "link-proj")
      fs.symlinkSync(realProj, linkProj)
      const linkHook = path.join(linkProj, ".codex/hooks/story_codex_hook.js")
      const cleanEnv = { ...process.env }
      delete cleanEnv.CODEX_PROJECT_DIR
      delete cleanEnv.CLAUDE_PROJECT_DIR
      const res = spawnSync(process.execPath, [linkHook, "pre-tool-prose-guard"], {
        cwd: linkProj,
        input: JSON.stringify({
          cwd: path.join(linkProj, "sub-book"),
          tool_name: "Write",
          tool_input: { file_path: "正文/第3章_软链.md" },
        }),
        encoding: "utf8",
        env: cleanEnv,
      })
      assert.equal(res.status, 0, res.stderr)
      assert.match(assertDenied(res.stdout, "symlinked workspace subdir cwd"), /sub-book\/大纲\/细纲_第003章\.md/)
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
})
