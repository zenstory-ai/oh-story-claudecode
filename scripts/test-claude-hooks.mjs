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
const HOOKS_SRC = path.join(REPO_ROOT, "skills/story-setup/references/templates/hooks")
const OPENCODE_SRC = path.join(REPO_ROOT, "skills/story-setup/references/opencode")

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

function writeCleanState(book, lastCommitted = 0, revision = 0) {
  write(
    path.join(book, "追踪/_tracking-state.json"),
    JSON.stringify({ schema_version: 4, state_revision: revision, last_committed_chapter: lastCommitted }) + "\n"
  )
  write(path.join(book, "追踪/上下文.md"), `> 状态修订：${revision}\n`)
}

function deployClaudeHooks(root) {
  const dst = path.join(root, ".claude/hooks")
  fs.mkdirSync(dst, { recursive: true })
  for (const name of ["run-story-hook.sh", "story_hook_cli.js", "story_hook_core.js"]) {
    fs.copyFileSync(path.join(HOOKS_SRC, name), path.join(dst, name))
  }
  fs.chmodSync(path.join(dst, "run-story-hook.sh"), 0o755)
  fs.chmodSync(path.join(dst, "story_hook_cli.js"), 0o755)
  return path.join(dst, "run-story-hook.sh")
}

function runLauncher(launcher, event, { root, input = "", env = {}, cwd = root } = {}) {
  return spawnSync("bash", [launcher, event], {
    cwd,
    input: typeof input === "string" ? input : JSON.stringify(input),
    encoding: "utf8",
    env: { ...process.env, CLAUDE_PROJECT_DIR: root, STORY_NO_UPDATE_CHECK: "1", ...env },
  })
}

function detectGbkLocale() {
  for (const cand of ["zh_CN.GBK", "zh_CN.gbk", "zh_CN.GB18030", "zh_CN.gb18030", "zh_CN.GB2312", "zh_CN.gb2312"]) {
    const res = spawnSync("locale", ["charmap"], {
      encoding: "utf8",
      env: { ...process.env, LC_ALL: cand, LANG: cand },
    })
    const cm = (res.stdout || "").trim().toUpperCase().replace(/-/g, "")
    if (["GBK", "GB18030", "GB2312"].includes(cm)) return cand
  }
  return ""
}

test("Claude post-tool-prose-check: zero over-capture, hard signals, whitelist, rescan hint, triage wording", () => {
  const root = mkTmp("claude-backstop-")
  try {
    const launcher = deployClaudeHooks(root)
    const pad = "江晨握紧拳头慢慢走向门口心里盘算着接下来的每一步棋。".repeat(8)

    write(path.join(root, "某书/设定.md"), "# 设定\n主角江晨。\n")
    write(path.join(root, "某书/大纲/细纲_第001章.md"), "## 细纲（第1章）\n- 情节点序列：本章细纲，作为AI我无法继续。他握紧拳头。他握紧拳头。\n")
    write(path.join(root, "某书/大纲/大纲.md"), "# 大纲\n第1章 第2章 细纲 本章 下一章\n")
    write(path.join(root, "某书/大纲/卷纲_第1卷.md"), "# 卷纲\n本卷细纲。\n")
    write(path.join(root, "某书/x.js"), "const x=1; // 细纲 本章 下一章 作为AI我无法继续\n")
    write(path.join(root, "docs/正文.md"), "## 正文\n按照细纲，作为AI我无法继续。\n")
    write(path.join(root, "游离/正文/第005章.md"), "## 第5章\n按照细纲，作为AI我无法继续。\n")
    write(path.join(root, "某书/正文/第001章_极短.md"), "他")

    const run = (filePath) => {
      const res = runLauncher(launcher, "post-tool-prose-check", {
        root,
        input: { tool_input: { file_path: filePath } },
      })
      assert.equal(res.status, 0, res.stderr)
      return res.stdout
    }

    // Non-prose files must be silent
    for (const nonProse of [
      "某书/大纲/细纲_第001章.md",
      "某书/大纲/大纲.md",
      "某书/大纲/卷纲_第1卷.md",
      "某书/x.js",
      "某书/设定.md",
      "docs/正文.md",
      "游离/正文/第005章.md",
    ]) {
      assert.equal(run(path.join(root, nonProse)), "", `over-capture on ${nonProse}`)
    }

    assert.match(run(path.join(root, "某书/正文/第001章_极短.md")), /【落盘】/)

    write(path.join(root, "某书/正文/第010章_决战.md"), `# 第10章 决战\n\n${pad}\n要么生，要么死。\n要么战，要么逃。\n「作为AI管家，我陪你到最后。」\n他终于停下了脚步。\n`)
    assert.equal(run(path.join(root, "某书/正文/第010章_决战.md")), "")

    write(path.join(root, "某书/正文/第011章_截断.md"), `# 第11章\n\n${pad}\n他猛地冲过去一拳砸在`)
    assert.match(run(path.join(root, "某书/正文/第011章_截断.md")), /截断/)

    write(path.join(root, "某书/正文/第012章_拒绝.md"), `# 第12章\n\n${pad}\n作为AI我无法继续创作这部分内容。\n`)
    assert.match(run(path.join(root, "某书/正文/第012章_拒绝.md")), /元信息泄漏/)

    write(path.join(root, "某书/正文/第013章_工程词.md"), `# 第13章\n\n${pad}\n按照本章细纲的情节点，他该出场了。\n他出场了。\n`)
    assert.match(run(path.join(root, "某书/正文/第013章_工程词.md")), /工程词/)

    write(path.join(root, "某书/正文/第014章_复读.md"), `# 第14章\n\n${pad}\n他握紧拳头一步步走过去缓缓逼近。\n他握紧拳头一步步走过去缓缓逼近。\n他停下了。\n`)
    assert.match(run(path.join(root, "某书/正文/第014章_复读.md")), /复读/)

    write(path.join(root, "某书/正文/第015章_单处常态.md"), `# 第15章 单处豁免\n\n${pad}\n声音不大，却带着一股狠劲。\n这不是退让，而是试探。\n没有伴奏，没有和声，没有提词器。\n没人知道他去了哪里。\n他把门关上了。\n`)
    assert.equal(run(path.join(root, "某书/正文/第015章_单处常态.md")), "")

    // Book-local .deslop-whitelist + rescan hints + triage wording
    write(path.join(root, "白名单书/.deslop-whitelist"), "# 白名单\n声音不大，却带着一股狠劲\n")
    for (const b of ["白名单书", "对照书"]) {
      fs.mkdirSync(path.join(root, b, "大纲"), { recursive: true })
      write(path.join(root, b, "正文/第001章_开场.md"), `# 第1章 开场\n\n${pad}\n声音不大，却带着一股狠劲。\n他声音不高，却压住了整间屋子。\n他把门关上了。\n`)
    }
    const ctrlOut = run(path.join(root, "对照书/正文/第001章_开场.md"))
    assert.match(ctrlOut, /voice-contrast/)
    assert.match(ctrlOut, /storyctl\.js chapter check --project <书目录> --chapter 1/)
    assert.ok(!ctrlOut.includes("check-ai-patterns.js"))
    assert.match(ctrlOut, /截断\/拒绝语\/工程词→重写该段；毒句式→就地改写/)
    assert.ok(!run(path.join(root, "白名单书/正文/第001章_开场.md")).includes("毒句式"))

    write(path.join(root, "短篇书/设定.md"), "# 设定\n")
    write(path.join(root, "短篇书/正文.md"), `# 正文\n\n${pad}\n声音不大，却带着一股狠劲。\n他声音不高，却压住了整间屋子。\n他把门关上了。\n`)
    const shortOut = run(path.join(root, "短篇书/正文.md"))
    assert.match(shortOut, /check-ai-patterns\.js --check <正文文件>/)
    assert.ok(!shortOut.includes("storyctl"))
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("Claude detect-story-gaps continuity (staleness, dup-title, state checks, clean silent, short non-staleness)", () => {
  const makeBook = (root) => {
    for (const s of ["角色.md", "世界.md", "力量.md"]) write(path.join(root, "某书/设定", s), "x\n")
    write(path.join(root, "某书/大纲/卷纲.md"), "卷纲\n")
    writeCleanState(path.join(root, "某书"), 0, 0)
  }

  // Staleness + duplicate title
  const t1 = mkTmp("claude-cont1-")
  try {
    const launcher = deployClaudeHooks(t1)
    makeBook(t1)
    const oldTime = new Date(Date.now() - 10_000)
    fs.utimesSync(path.join(t1, "某书/追踪/上下文.md"), oldTime, oldTime)
    write(path.join(t1, "某书/正文/第001章_决战.md"), "# 第1章 决战\n正文。\n")
    write(path.join(t1, "某书/正文/第002章_决战.md"), "# 第2章 决战\n正文。\n")
    const out = runLauncher(launcher, "detect-story-gaps", { root: t1 }).stdout
    assert.match(out, /续写状态卡更早/)
    assert.match(out, /标题重复/)
  } finally {
    fs.rmSync(t1, { recursive: true, force: true })
  }

  // Mismatched / malformed / missing state
  for (const [kind, setup, expected] of [
    ["mismatch", (b) => write(path.join(b, "追踪/_tracking-state.json"), JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 0 })), /状态修订/],
    ["malformed", (b) => write(path.join(b, "追踪/_tracking-state.json"), "{not-json"), /无法解析/],
    ["missing", (b) => fs.unlinkSync(path.join(b, "追踪/_tracking-state.json")), /_tracking-state\.json 缺失/],
  ]) {
    const tm = mkTmp(`claude-cont-${kind}-`)
    try {
      const launcher = deployClaudeHooks(tm)
      makeBook(tm)
      write(path.join(tm, "某书/正文/第001章_开端.md"), "# 第1章 开端\n正文。\n")
      setup(path.join(tm, "某书"))
      const out = runLauncher(launcher, "detect-story-gaps", { root: tm }).stdout
      assert.match(out, expected, kind)
    } finally {
      fs.rmSync(tm, { recursive: true, force: true })
    }
  }

  // Clean project silent
  const t2 = mkTmp("claude-cont2-")
  try {
    const launcher = deployClaudeHooks(t2)
    makeBook(t2)
    write(path.join(t2, "某书/正文/第001章_开端.md"), "# 第1章 开端\n正文。\n")
    write(path.join(t2, "某书/正文/第002章_转折.md"), "# 第2章 转折\n正文。\n")
    const future = new Date(Date.now() + 5000)
    fs.utimesSync(path.join(t2, "某书/追踪/上下文.md"), future, future)
    assert.equal(runLauncher(launcher, "detect-story-gaps", { root: t2 }).stdout, "")
  } finally {
    fs.rmSync(t2, { recursive: true, force: true })
  }
})

test("Claude pre-tool-prose-guard drive-letter paths (issue #184), analysis-input-guard, and windowsHide", () => {
  const root = mkTmp("claude-paths-")
  try {
    const launcher = deployClaudeHooks(root)
    // POSIX contrapositive for issue #184: create fixture ONLY under $root/C:/book184
    let createdColonDir = false
    try {
      writeOutline(path.join(root, "C:/book184/大纲/细纲_第2章.md"))
      writeCleanState(path.join(root, "C:/book184"), 1)
      createdColonDir = true
    } catch {}
    if (createdColonDir && process.platform !== "win32") {
      for (const fp of ["C:/book184/正文/第2章_x.md", "C:\\book184\\正文\\第2章_x.md"]) {
        const res = runLauncher(launcher, "pre-tool-prose-guard", {
          root,
          input: { tool_name: "Write", tool_input: { file_path: fp } },
        })
        assert.equal(res.status, 2, `Windows drive path should not root-join: ${fp}`)
      }
      fs.rmSync(path.join(root, "C:"), { recursive: true, force: true })
    }

    // analysis-input-guard stays working directly via story_hook_cli.js
    const cli = path.join(root, ".claude/hooks/story_hook_cli.js")
    write(path.join(root, "拆文库/示例/_progress.md"), "# 进度\n")
    const ok = spawnSync(process.execPath, [cli, "analysis-input-guard"], {
      cwd: root,
      input: JSON.stringify({ tool_input: { file_path: "拆文库/示例/_analysis_cache/输入-RAW-1-3.md" } }),
      encoding: "utf8",
      env: { ...process.env, CLAUDE_PROJECT_DIR: root },
    })
    assert.equal(ok.status, 0, ok.stderr)

    const bad = spawnSync(process.execPath, [cli, "analysis-input-guard"], {
      cwd: root,
      input: JSON.stringify({ tool_input: { file_path: "拆文库/示例/正文.md" } }),
      encoding: "utf8",
      env: { ...process.env, CLAUDE_PROJECT_DIR: root },
    })
    assert.equal(bad.status, 2)
    assert.match(bad.stderr, /chapter-extractor 写入被拦截/)

    // Pre-write hard blocks vs soft advisory warnings (exit 0 + additionalContext JSON)
    const softBook = path.join(root, "软门禁书")
    writeOutline(path.join(softBook, "大纲/细纲_第2章.md"))
    writeOutline(path.join(softBook, "大纲/细纲_第5章.md"))
    write(path.join(softBook, "正文/第1章_旧.md"), "# 第1章\n声音不大，却带着一股狠劲。他声音不高，却压住了整间屋子。\n")

    // Corrupt _tracking-state.json still hard-blocks (exit 2)
    write(path.join(softBook, "追踪/_tracking-state.json"), "{corrupt-json\n")
    const corruptRes = runLauncher(launcher, "pre-tool-prose-guard", {
      root,
      input: { tool_name: "Write", tool_input: { file_path: "软门禁书/正文/第2章_新.md" } },
    })
    assert.equal(corruptRes.status, 2)
    assert.match(corruptRes.stderr, /无法解析/)

    // Wrong schema_version still hard-blocks (exit 2)
    write(path.join(softBook, "追踪/_tracking-state.json"), JSON.stringify({ schema_version: 3, state_revision: 0, last_committed_chapter: 1 }))
    const schemaRes = runLauncher(launcher, "pre-tool-prose-guard", {
      root,
      input: { tool_name: "Write", tool_input: { file_path: "软门禁书/正文/第2章_新.md" } },
    })
    assert.equal(schemaRes.status, 2)
    assert.match(schemaRes.stderr, /schema_version=4/)

    // Prior-chapter toxic prose: exit 0 (ALLOWED) + non-blocking PreToolUse additionalContext JSON
    writeCleanState(softBook, 1, 0)
    const toxicRes = runLauncher(launcher, "pre-tool-prose-guard", {
      root,
      input: { tool_name: "Write", tool_input: { file_path: "软门禁书/正文/第2章_新.md" } },
    })
    assert.equal(toxicRes.status, 0, toxicRes.stderr)
    const toxicJson = JSON.parse(toxicRes.stdout)
    assert.equal(toxicJson.hookSpecificOutput?.hookEventName, "PreToolUse")
    assert.match(toxicJson.hookSpecificOutput?.additionalContext, /写正文前软门禁提醒/)
    assert.match(toxicJson.hookSpecificOutput?.additionalContext, /疑似 AI 毒句式/)

    // Out-of-order chapter jump via Bash: exit 0 (ALLOWED) + non-blocking additionalContext JSON
    const jumpRes = runLauncher(launcher, "pre-tool-prose-guard", {
      root,
      input: { tool_name: "Bash", tool_input: { command: "cat > 软门禁书/正文/第5章_跳章.md <<EOF\n正文\nEOF" } },
    })
    assert.equal(jumpRes.status, 0, jumpRes.stderr)
    const jumpJson = JSON.parse(jumpRes.stdout)
    assert.equal(jumpJson.hookSpecificOutput?.hookEventName, "PreToolUse")
    assert.match(jumpJson.hookSpecificOutput?.additionalContext, /有意跳章起草/)

    // Manual 上下文.md revision mismatch: exit 0 (ALLOWED) + non-blocking additionalContext JSON
    write(path.join(softBook, "追踪/上下文.md"), "> 状态修订：99\n")
    const revRes = runLauncher(launcher, "pre-tool-prose-guard", {
      root,
      input: { tool_name: "Write", tool_input: { file_path: "软门禁书/正文/第1章_旧.md" } },
    })
    assert.equal(revRes.status, 0, revRes.stderr)
    const revJson = JSON.parse(revRes.stdout)
    assert.match(revJson.hookSpecificOutput?.additionalContext, /状态修订/)

    // Verify story_hook_cli.js passes windowsHide: true on git rev-parse
    const origSpawn = childProcess.spawnSync
    const calls = []
    try {
      childProcess.spawnSync = (cmd, args, opts) => {
        calls.push({ cmd, args, opts })
        return origSpawn(cmd, args, opts)
      }
      syncBuiltinESMExports()
      const cliSrc = path.join(HOOKS_SRC, "story_hook_cli.js")
      delete require.cache[require.resolve(cliSrc)]
      const mod = require(cliSrc)
      const prevEnv = process.env.CLAUDE_PROJECT_DIR
      delete process.env.CLAUDE_PROJECT_DIR
      try {
        mod.projectRoot({ cwd: REPO_ROOT })
      } finally {
        if (prevEnv !== undefined) process.env.CLAUDE_PROJECT_DIR = prevEnv
      }
      const gitCalls = calls.filter((c) => c.cmd === "git")
      assert.ok(gitCalls.length >= 1)
      assert.ok(gitCalls.every((c) => c.opts?.windowsHide === true), "story_hook_cli.js git calls must pass windowsHide: true")
    } finally {
      childProcess.spawnSync = origSpawn
      syncBuiltinESMExports()
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("Claude hooks end-to-end under real GBK locale (zh_CN.GBK when available)", (t) => {
  const gbk = detectGbkLocale()
  if (!gbk) {
    t.skip("no zh_CN.GBK-class locale available on this host")
    return
  }
  const root = mkTmp("claude-gbk-")
  try {
    const launcher = deployClaudeHooks(root)
    execFileSync("git", ["-C", root, "init", "-q"])
    execFileSync("git", ["-C", root, "config", "user.email", "t@t.t"])
    execFileSync("git", ["-C", root, "config", "user.name", "t"])
    const gbkEnv = { LANG: gbk, LC_ALL: gbk }

    const book = path.join(root, "让你管账号")
    fs.mkdirSync(path.join(book, "正文"), { recursive: true })
    fs.mkdirSync(path.join(book, "大纲"), { recursive: true })
    fs.mkdirSync(path.join(book, "设定"), { recursive: true })
    write(path.join(root, ".active-book"), "让你管账号\n")

    const guard = (fp) =>
      runLauncher(launcher, "pre-tool-prose-guard", {
        root,
        input: { tool_name: "Write", tool_input: { file_path: fp } },
        env: gbkEnv,
      }).status

    assert.equal(guard("让你管账号/正文/第1章_开端.md"), 2)
    writeOutline(path.join(book, "大纲/细纲_第1章.md"))
    writeCleanState(book, 0, 0)
    assert.equal(guard("让你管账号/正文/第1章_开端.md"), 0)
    assert.equal(guard("让你管账号/正文/第001章_开端.md"), 0)

    write(path.join(book, "大纲/细纲_第1章.md"), "# 细纲\n他推门进屋看见师父坐在柜台后面他推门进屋看见师父坐在柜\n")
    assert.equal(guard("让你管账号/正文/第1章_开端.md"), 2)
    write(path.join(book, "大纲/细纲_第1章.md"), "# 细纲\n他推门进屋看见师父坐在柜台后面他推门进屋看见师父坐在柜台\n")
    assert.equal(guard("让你管账号/正文/第1章_开端.md"), 0)

    write(
      path.join(book, "追踪/伏笔.md"),
      "| ID | 伏笔内容 | 埋设章节 | 预计回收章节 | 状态{已埋/已回收/已过期/放弃} | 重要度{高/中/低} |\n|----|---------|---------|-------------|-----------------------------|----------------|\n| F001 | 玉佩身世 | 第1章 | 第20章 |　已埋　| 高 |\n| F002 | 师门往事 | 第3章 | 第25章 | 已回收 | 中 |\n"
    )
    const gapClean = runLauncher(launcher, "detect-story-gaps", { root, env: gbkEnv }).stdout
    assert.ok(!gapClean.includes("伏笔"))

    for (let i = 1; i <= 11; i += 1) write(path.join(book, `正文/第${i}章.md`), "")
    const gapHit = runLauncher(launcher, "detect-story-gaps", { root, env: gbkEnv }).stdout
    assert.match(gapHit, /让你管账号/)

    write(path.join(book, "正文/第1章_开端.md"), "年龄　：18\n")
    execFileSync("git", ["-C", root, "add", "-A"])
    const commitOut = runLauncher(launcher, "pre-tool-commit-advisory", {
      root,
      env: { ...gbkEnv, STORY_COMMIT_COMMAND: "git commit -m x" },
    }).stdout
    assert.match(commitOut, /正文硬编码角色属性/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("Claude session-start checks agents_version via shared story_hook_core.js", () => {
  const contract = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "scripts/current-contract.json"), "utf8"))
  const ver = contract.agents_version
  const root = mkTmp("claude-agents-ver-")
  try {
    const launcher = deployClaudeHooks(root)
    write(path.join(root, ".claude/skills/story-setup/references/agent-references/dummy.md"), "# ref\n")

    const writeSentinel = (agentsLine) =>
      write(
        path.join(root, ".story-deployed"),
        [
          agentsLine,
          "setup_skill_version: 1.2.6",
          "target_cli: claude-code",
          "resolver_strategy: project-local-skill-reference",
          "references_dir: .claude/skills/story-setup/references/agent-references",
          "",
        ]
          .filter(Boolean)
          .join("\n")
      )

    writeSentinel(`agents_version: ${ver - 1}`)
    let out = runLauncher(launcher, "session-start", { root }).stdout
    assert.match(out, new RegExp(`低于 v${ver}`))
    assert.match(out, /\/story-setup/)

    writeSentinel(`agents_version: ${ver + 1}`)
    out = runLauncher(launcher, "session-start", { root }).stdout
    assert.match(out, new RegExp(`高于本 hook 支持的 v${ver}`))
    assert.match(out, /不要降级覆盖/)

    writeSentinel("agents_version: invalid")
    out = runLauncher(launcher, "session-start", { root }).stdout
    assert.match(out, /缺少数字 agents_version/)

    writeSentinel(`agents_version: ${ver}`)
    out = runLauncher(launcher, "session-start", { root }).stdout
    assert.ok(!out.includes(`低于 v${ver}`))
    assert.ok(!out.includes("高于本 hook"))
    assert.ok(!out.includes("缺少数字 agents_version"))
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("OpenCode pre-commit.sh delegates to shared story_hook_core.js and is valid POSIX sh", () => {
  const preCommitSrc = path.join(OPENCODE_SRC, "pre-commit.sh")
  const syntax = spawnSync("sh", ["-n", preCommitSrc], { encoding: "utf8" })
  assert.equal(syntax.status, 0, syntax.stderr)

  const repo = mkTmp("opencode-precommit-")
  try {
    execFileSync("git", ["-C", repo, "init", "-q"])
    const hook = path.join(repo, ".git/hooks/pre-commit")
    fs.copyFileSync(preCommitSrc, hook)
    fs.chmodSync(hook, 0o755)
    fs.mkdirSync(path.join(repo, ".opencode/plugins/lib"), { recursive: true })
    fs.copyFileSync(path.join(OPENCODE_SRC, "story_hook_core.js"), path.join(repo, ".opencode/plugins/lib/story_hook_core.js"))

    write(path.join(repo, "book/正文/第1章.md"), "身高: 180\n")
    write(path.join(repo, "设定/关系.md"), "# 角色关系图\n")
    write(path.join(repo, "设定/反派.md"), "无名字\n")
    execFileSync("git", ["-C", repo, "add", "-A"])

    const res = spawnSync("sh", [hook], { cwd: repo, encoding: "utf8" })
    assert.equal(res.status, 0, res.stderr)
    assert.match(res.stdout, /Story Commit Warnings/)
    assert.match(res.stdout, /正文硬编码角色属性/)
    assert.match(res.stdout, /反派\.md/)
    assert.ok(!res.stdout.includes("关系.md"))

    // Fail-open when core is missing
    fs.unlinkSync(path.join(repo, ".opencode/plugins/lib/story_hook_core.js"))
    const noop = spawnSync("sh", [hook], { cwd: repo, encoding: "utf8" })
    assert.equal(noop.status, 0)
    assert.equal(noop.stdout, "")
  } finally {
    fs.rmSync(repo, { recursive: true, force: true })
  }
})
