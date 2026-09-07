#!/usr/bin/env node
"use strict"

import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import process from "node:process"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const source = path.join(repo, "skills/story-setup/references/antigravity/hooks")
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "oh story 中文 hook-"))
const hookDir = path.join(fixture, ".agents/hooks")
const artifact = path.join(fixture, ".antigravity-artifacts")
const hook = path.join(hookDir, "story_antigravity_hook.js")

function write(relative, content) {
  const file = path.join(fixture, relative)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content, "utf8")
  return file
}

const events = {
  "pre-tool-use": "PreToolUse",
  "post-tool-use": "PostToolUse",
  "pre-invocation": "PreInvocation",
  stop: "Stop",
}

function invoke(event, input, shell = false) {
  const registered = JSON.parse(fs.readFileSync(path.join(fixture, ".agents/hooks.json"), "utf8"))
  const entries = registered["oh-story"][events[event]]
  assert.equal(entries.length, 1, `${event}: expected one registered entry`)
  const entry = entries[0]
  if (entry.matcher && input.toolCall?.name) {
    assert.ok(new RegExp(entry.matcher).test(input.toolCall.name), `${event}: tool is not routed`)
  }
  const handlers = entry.hooks || [entry]
  assert.equal(handlers.length, 1, `${event}: expected one registered handler`)
  const { command } = handlers[0]
  // Exercise actual registration, not a reconstructed argv that hides quoting bugs.
  // Shell execution follows the documented command contract. Literal whitespace
  // tokenization additionally locks portability to hosts that forward quote chars;
  // it is a compatibility probe, not an emulation of Antigravity's private parser.
  const [program, ...args] = command.trim().split(/\s+/)
  const result = spawnSync(shell ? command : program, shell ? [] : args, {
    shell,
    cwd: path.join(fixture, ".agents"),
    input: JSON.stringify({
      conversationId: "fixture-conversation",
      workspacePaths: [fixture],
      artifactDirectoryPath: artifact,
      ...input,
    }),
    encoding: "utf8",
  })
  assert.equal(result.status, 0, `${event} failed: ${result.stderr}`)
  assert.doesNotThrow(() => JSON.parse(result.stdout), `${event} emitted invalid JSON: ${result.stdout}`)
  return { raw: result.stdout, value: JSON.parse(result.stdout) }
}

try {
  fs.mkdirSync(hookDir, { recursive: true })
  fs.mkdirSync(artifact, { recursive: true })
  fs.copyFileSync(path.join(source, "story_antigravity_hook.js"), hook)
  fs.copyFileSync(path.join(source, "story_hook_core.js"), path.join(hookDir, "story_hook_core.js"))
  fs.copyFileSync(path.join(source, "hooks.json"), path.join(fixture, ".agents/hooks.json"))

  // All four registered commands must launch in a project path containing spaces
  // and Chinese characters, both through the OS shell and literal argv dispatch.
  for (const shell of [false, true]) {
    assert.deepEqual(invoke("pre-tool-use", {
      toolCall: { name: "write_to_file", args: { TargetFile: "普通笔记.md" } },
    }, shell).value, { decision: "allow" })
    assert.equal(invoke("post-tool-use", {}, shell).raw, "{}")
    assert.deepEqual(invoke("pre-invocation", { invocationNum: 1 }, shell).value, {})
    assert.deepEqual(invoke("stop", { fullyIdle: true, terminationReason: "model_stop" }, shell).value,
      { decision: "stop" })
  }

  write("短篇/设定.md", "# 设定\n")
  const shortProse = path.join(fixture, "短篇/正文.md")
  let response = invoke("pre-tool-use", {
    toolCall: { name: "write_to_file", args: { TargetFile: shortProse } },
  }).value
  assert.equal(response.decision, "deny")
  assert.match(response.reason, /小节大纲/)

  write("短篇/小节大纲.md", "# 小节大纲\n")
  response = invoke("pre-tool-use", {
    toolCall: { name: "write_to_file", args: { TargetFile: "短篇/正文.md" } },
  }).value
  assert.deepEqual(response, { decision: "allow" })

  write("另一短篇/设定.md", "# 设定\n")
  response = invoke("pre-tool-use", {
    toolCall: {
      name: "run_command",
      args: { CommandLine: "printf draft > \"另一短篇/正文.md\"", Cwd: fixture },
    },
  }).value
  assert.equal(response.decision, "deny")
  assert.match(response.reason, /另一短篇.*小节大纲/s)

  write("普通笔记.md", "hello\n")
  response = invoke("pre-tool-use", {
    toolCall: { name: "replace_file_content", args: { TargetFile: "普通笔记.md" } },
  }).value
  assert.deepEqual(response, { decision: "allow" })

  write("短篇/正文.md", "# 标题\n\n本章将在下一章继续展开")
  let post = invoke("post-tool-use", {
    toolCall: { name: "write_to_file", args: { TargetFile: "短篇/正文.md" } },
  })
  assert.equal(post.raw, "{}", "PostToolUse must emit exactly {}")
  const pending = path.join(artifact, "oh-story-pending.json")
  assert.ok(fs.existsSync(pending), "PostToolUse must persist pending findings")
  post = invoke("post-tool-use", {
    toolCall: { name: "run_command", args: { CommandLine: "printf draft > \"短篇/正文.md\"", Cwd: fixture } },
  })
  assert.equal(post.raw, "{}", "run_command PostToolUse must also emit exactly {}")

  response = invoke("pre-invocation", { invocationNum: 1 }).value
  assert.ok(Array.isArray(response.injectSteps) && response.injectSteps.length === 1)
  assert.match(response.injectSteps[0].ephemeralMessage, /正文兜底检测/)
  assert.match(response.injectSteps[0].ephemeralMessage, /疑似截断|元信息泄漏|毒句式/)

  response = invoke("stop", { fullyIdle: false, terminationReason: "model_stop" }).value
  assert.equal(response.decision, "stop", "Stop must not continue while background work is active")
  response = invoke("stop", { fullyIdle: true, terminationReason: "error" }).value
  assert.equal(response.decision, "stop", "Stop must not continue an error termination")
  response = invoke("stop", { fullyIdle: true, terminationReason: "model_stop" }).value
  assert.equal(response.decision, "continue")
  response = invoke("stop", { fullyIdle: true, terminationReason: "model_stop" }).value
  assert.equal(response.decision, "stop", "Stop may force at most one continuation")

  const clean = "雨落在旧瓦上，檐角的水沿着石阶往下淌，院门外传来车轮碾过碎石的轻响。".repeat(4)
  write("短篇/正文.md", `# 标题\n\n${clean}\n`)
  post = invoke("post-tool-use", {
    toolCall: { name: "multi_replace_file_content", args: { TargetFile: "短篇/正文.md" } },
  })
  assert.equal(post.raw, "{}")
  assert.ok(!fs.existsSync(pending), "clean rewrite must clear pending findings")
  assert.deepEqual(invoke("pre-invocation", { invocationNum: 1 }).value, {})

  write(".story-deployed", "agents_version: 26\ntarget_cli: antigravity\n")
  write(".active-book", "长书\n")
  write("长书/设定/世界观.md", "# 世界观\n")
  write("长书/追踪/上下文.md", "# 上下文\n")
  response = invoke("pre-invocation", { invocationNum: 0 }).value
  assert.ok(Array.isArray(response.injectSteps))
  assert.match(response.injectSteps.map((item) => item.ephemeralMessage).join("\n"), /Active book: 长书/)

  const git = (args) => spawnSync("git", args, { cwd: fixture, encoding: "utf8" })
  assert.equal(git(["init", "-q"]).status, 0)
  write("长书/设定/角色/甲.md", "# 角色甲\n\n年龄：20\n")
  assert.equal(git(["add", "."]).status, 0)
  response = invoke("pre-tool-use", {
    toolCall: { name: "run_command", args: { CommandLine: "git commit -m fixture", Cwd: fixture } },
  }).value
  assert.equal(response.decision, "allow")
  assert.match(response.reason, /Story Commit Warnings/)

  post = invoke("post-tool-use", { error: "fixture failure" })
  assert.equal(post.raw, "{}")
  process.stdout.write("Antigravity hook contract tests passed.\n")
} finally {
  fs.rmSync(fixture, { recursive: true, force: true })
}
