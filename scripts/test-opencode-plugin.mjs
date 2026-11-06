#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import childProcess, { execFileSync } from "node:child_process";
import { createRequire, syncBuiltinESMExports } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = path.join(repoRoot, "skills/story-setup/references/opencode");
const tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "story-opencode-plugin-")));
const originalCwd = process.cwd();
const originalExecSync = childProcess.execSync;
const originalSpawnSync = childProcess.spawnSync;
const childProcessCalls = [];

// 用真实 child_process 调用的薄代理记录 options：这会覆盖插件和共享核实际解构到的
// execSync/spawnSync，能验证运行时参数，而不是只扫源码里有没有 windowsHide 字样。
childProcess.execSync = (command, options) => {
  childProcessCalls.push({ method: "execSync", command, options });
  return originalExecSync(command, options);
};
childProcess.spawnSync = (command, args, options) => {
  childProcessCalls.push({ method: "spawnSync", command, args, options });
  return originalSpawnSync(command, args, options);
};
syncBuiltinESMExports();

// plugin.ts imports "./lib/story_hook_core.js"（与 ZCode 共享的 prose-guard 核，部署到
// .opencode/plugins/lib/）。仓库源码里核是平铺的，只有部署布局才有 lib/ 子目录；在 tmp 里
// 复刻部署布局，import 才能解析到核。
const deployDir = path.join(tmp, "plugins");
fs.mkdirSync(path.join(deployDir, "lib"), { recursive: true });
fs.copyFileSync(path.join(srcDir, "plugin.ts"), path.join(deployDir, "plugin.ts"));
fs.copyFileSync(
  path.join(srcDir, "story_hook_core.js"),
  path.join(deployDir, "lib", "story_hook_core.js")
);
const pluginPath = path.join(deployDir, "plugin.ts");

async function expectBlocked(action, label) {
  await assert.rejects(action, /写正文被拦截/, label);
}

function writeCleanState(book, lastCommitted = 0) {
  fs.mkdirSync(path.join(book, "追踪"), { recursive: true });
  fs.writeFileSync(
    path.join(book, "追踪", "_tracking-state.json"),
    JSON.stringify({ schema_version: 4, state_revision: 0, last_committed_chapter: lastCommitted }) + "\n",
    "utf8"
  );
  fs.writeFileSync(path.join(book, "追踪", "上下文.md"), "> 状态修订：0\n", "utf8");
}

try {
  execFileSync("git", ["init", "-q", tmp]);
  process.chdir(tmp);
  const imported = await import(`${pathToFileURL(pluginPath).href}?test=${Date.now()}`);
  const plugin = imported.default;
  assert.equal(plugin.id, "oh-story.story-hooks");
  assert.equal(typeof plugin.setup, "function");

  // OpenCode 2.x 插件上下文的最小替身：只提供插件用到的 location / tool.hook / session.hook。
  const hooks = { tool: {}, session: {} };
  const register = (domain) => async (name, callback) => {
    hooks[domain][name] = callback;
    return { dispose: async () => {} };
  };
  // setup 在项目外的 cwd 里跑：真实后台服务加载插件时 process.cwd() 也不是用户项目。
  process.chdir(os.tmpdir());
  try {
    await plugin.setup({
      location: { directory: tmp },
      tool: { hook: register("tool") },
      session: { hook: register("session") },
    });
  } finally {
    process.chdir(tmp);
  }
  assert.equal(typeof hooks.tool["execute.before"], "function");
  assert.equal(typeof hooks.tool["execute.after"], "function");
  assert.equal(typeof hooks.session.context, "function");
  assert.equal(typeof hooks.session.compaction, "function");

  // async 包一层：钩子同步 throw 也表现为 rejected promise，与运行时的 Promise 包装一致。
  const before = async (tool, input) => hooks.tool["execute.before"]({ tool, input });
  const after = async (tool, input, content) => {
    const event = { tool, input, status: "completed", result: { content } };
    await hooks.tool["execute.after"](event);
    return event.result.content;
  };

  fs.mkdirSync("book/正文", { recursive: true });
  fs.mkdirSync("book/大纲", { recursive: true });
  fs.mkdirSync("book/追踪", { recursive: true });
  fs.writeFileSync("book/追踪/上下文.md", "# 上下文\n当前位置\n", "utf8");
  fs.writeFileSync(".active-book", "book\n", "utf8");

  await expectBlocked(
    () => before("write", { path: "book/正文/第001章_开局.md" }),
    "new long prose without an outline"
  );

  fs.writeFileSync("book/大纲/细纲_第1章.md", "# 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。\n", "utf8");
  await assert.rejects(
    () => before("write", { path: "book/正文/第001章_开局.md" }),
    /_tracking-state\.json 缺失/,
    "long prose with outline but no tracking checkpoint must fail closed"
  );
  writeCleanState("book");
  // 细纲文件在但只有标题：照拦，文案说清是细纲空了。
  fs.writeFileSync("book/大纲/细纲_第1章.md", "# 细纲\n## 目标情绪\n", "utf8");
  await assert.rejects(
    () => before("write", { path: "book/正文/第001章_开局.md" }),
    /第 1 章的细纲（book\/大纲\/细纲_第1章\.md）是空的/,
    "long prose with an empty outline must be blocked"
  );
  fs.writeFileSync("book/大纲/细纲_第1章.md", "# 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。\n", "utf8");
  await before("write", { path: "book/正文/第001章_开局.md" });

  // 2.x 后台服务一个进程服务多个项目，process.cwd() 不是用户项目：守卫只认 ctx.location。
  // 换到项目外的 cwd 后，有细纲的章照样放行、无细纲的章照样按项目内路径拦截。
  process.chdir(os.tmpdir());
  try {
    await before("write", { path: "book/正文/第001章_开局.md" });
    await assert.rejects(
      () => before("write", { path: "book/正文/第005章_外部.md" }),
      /第 5 章缺少细纲（book\/大纲\/细纲_第005章\.md）/,
      "project root must come from ctx.location, not process.cwd()"
    );
  } finally {
    process.chdir(tmp);
  }

  // shell 变量展不开：仍拦，但如实说路径没解析出来，不谎报缺细纲。
  await assert.rejects(
    () => before("shell", { command: 'PROJ=$PWD/book; cat draft.md > "$PROJ/正文/第001章_开局.md"' }),
    (error) => /未展开的 shell 变量/.test(error.message) && !/缺少细纲/.test(error.message),
    "shell-variable prose target must be blocked as unresolved, not as a missing outline"
  );

  fs.mkdirSync("bare/正文", { recursive: true });
  await expectBlocked(
    () => before("write", { path: "bare/正文/第1章_首章.md" }),
    "bare long project without scaffolding must fail closed"
  );

  fs.mkdirSync("cwd-book/正文", { recursive: true });
  fs.mkdirSync("cwd-book/大纲", { recursive: true });
  await assert.rejects(
    () =>
      before("shell", {
        command: "cat draft.md > 正文/第8章_相对.md",
        workdir: path.join(tmp, "cwd-book"),
      }),
    /cwd-book\/大纲/,
    "relative Shell target must resolve from the tool workdir"
  );
  await assert.rejects(
    () => before("shell", { command: "cat draft.md > 正文/第8章_相对.md", workdir: "cwd-book" }),
    /cwd-book\/大纲/,
    "relative workdir must resolve from the session directory"
  );
  fs.writeFileSync("cwd-book/大纲/细纲_第8章.md", "# 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。\n", "utf8");
  writeCleanState("cwd-book", 7);
  await before("shell", {
    command: "cat draft.md > 正文/第8章_相对.md",
    workdir: path.join(tmp, "cwd-book"),
  });

  fs.writeFileSync("book/正文/第002章_续写.md", "已有正文。\n", "utf8");
  await before("edit", { path: "book/正文/第002章_续写.md" });
  fs.writeFileSync(
    "book/追踪/_tracking-state.json",
    JSON.stringify({ schema_version: 4, state_revision: 1, last_committed_chapter: 0 }) + "\n",
    "utf8"
  );
  await assert.rejects(
    () => before("edit", { path: "book/正文/第002章_续写.md" }),
    /mode=revision 事务重建派生视图/,
    "existing prose revision must be blocked while derived state is inconsistent"
  );
  writeCleanState("book", 3);

  await assert.rejects(
    () => before("shell", { command: "cat draft.md > book/正文/第003章_绕过.md" }),
    /写正文被拦截[\s\S]*已从 Shell 命令识别到正文写入目标/,
    "shell redirect must be blocked without claiming the static parser is unbypassable"
  );
  await before("shell", { command: "grep 'book/正文/第003章_绕过.md' notes.md" });

  // patch 是 OpenCode 的 edit 类工具，部分模型只暴露它、隐藏 write/edit：
  // 守卫与落盘兜底都必须认它，否则那类模型整场没有大纲守卫和正文兜底。
  const addPatch = (target) =>
    `*** Begin Patch\n*** Add File: ${target}\n+正文第一句。\n*** End Patch\n`;
  await expectBlocked(
    () => before("patch", { patchText: addPatch("book/正文/第004章_补丁.md") }),
    "patch must not bypass the outline guard"
  );
  fs.writeFileSync("book/大纲/细纲_第4章.md", "# 细纲\n江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。\n", "utf8");
  await before("patch", { patchText: addPatch("book/正文/第004章_补丁.md") });

  // *** Move to: 是 patch 的搬家/改名形态，落盘路径是目的地。目标抽取的各形态（Delete+Move、
  // 搬出 正文/、纯 Delete）归 test-prose-net-parity.sh B 段；这里只验插件把 patchText 交给核、
  // 并按目的地章号拦下（源 draft.md 不是正文，本就不该被判）。
  const movePatch = (source, destination) =>
    `*** Begin Patch\n*** Update File: ${source}\n*** Move to: ${destination}\n+正文第一句。\n*** End Patch\n`;
  await assert.rejects(
    () => before("patch", { patchText: movePatch("draft.md", "book/正文/第009章_搬家.md") }),
    /写正文被拦截[\s\S]*第 9 章缺少细纲/,
    "patch *** Move to: 的拦截判据必须算在目的地章号上"
  );

  fs.mkdirSync("short", { recursive: true });
  fs.writeFileSync("short/设定.md", "# 设定\n", "utf8");
  await expectBlocked(
    () => before("write", { path: "short/正文.md" }),
    "new short prose without section outline"
  );
  fs.writeFileSync("short/小节大纲.md", "# 小节大纲\n", "utf8");
  await before("write", { path: "short/正文.md" });

  fs.writeFileSync(
    "book/正文/第001章_开局.md",
    `${"街灯一盏盏亮起。".repeat(30)}\nTODO 此处待补`,
    "utf8"
  );
  const afterOutput = await after("write", { path: "book/正文/第001章_开局.md" }, "write complete");
  assert.match(afterOutput, /^write complete\n\n/);
  assert.match(afterOutput, /正文兜底检测/);
  assert.match(afterOutput, /占位符/);

  // content 是结构化数组时追加一段 text，不改写原有条目
  const structured = await after("write", { path: "book/正文/第001章_开局.md" }, [
    { type: "text", text: "write complete" },
  ]);
  assert.equal(structured[0].text, "write complete");
  assert.match(structured.at(-1).text, /正文兜底检测/);

  fs.writeFileSync("notes.md", "TODO\n", "utf8");
  assert.equal(await after("write", { path: "notes.md" }, "unchanged"), "unchanged");

  fs.writeFileSync(
    "book/正文/第004章_补丁.md",
    `${"街灯一盏盏亮起。".repeat(30)}\nTODO 此处待补`,
    "utf8"
  );
  const patchAfterOutput = await after(
    "patch",
    { patchText: addPatch("book/正文/第004章_补丁.md") },
    "patch applied"
  );
  assert.match(patchAfterOutput, /正文兜底检测/);
  assert.match(patchAfterOutput, /占位符/);

  assert.equal(await after("patch", { patchText: addPatch("notes.md") }, "unchanged"), "unchanged");

  // 搬家式补丁的写后兜底：要扫的是**目的地**那一章。只认 Add/Update File 时这里抽到 draft.md，
  // 网整条空过——搬进 正文/ 的章带着 TODO 也没人回话。
  fs.writeFileSync(
    "book/正文/第009章_搬家.md",
    `${"街灯一盏盏亮起。".repeat(30)}\nTODO 此处待补`,
    "utf8"
  );
  const moveAfterOutput = await after(
    "patch",
    { patchText: movePatch("draft.md", "book/正文/第009章_搬家.md") },
    "patch applied"
  );
  assert.match(moveAfterOutput, /正文兜底检测（book\/正文\/第009章_搬家\.md）/);
  assert.match(moveAfterOutput, /占位符/);

  // Shell 重定向写正文的写后兜底：与 write/edit/patch 一样扫落盘后的目标章
  const shellAfterOutput = await after(
    "shell",
    { command: "cat draft.md > book/正文/第001章_开局.md" },
    "shell write complete"
  );
  assert.match(shellAfterOutput, /正文兜底检测（book\/正文\/第001章_开局\.md）/);
  assert.match(shellAfterOutput, /占位符/);
  assert.equal(await after("shell", { command: "ls -la" }, "unchanged"), "unchanged");

  // 失败的工具调用不做写后兜底：结果原样保留
  const failed = { tool: "write", input: { path: "book/正文/第001章_开局.md" }, status: "error", error: { message: "x" } };
  await hooks.tool["execute.after"](failed);
  assert.equal(failed.result, undefined);

  // 非写类工具必须在 dispatch 前返回，不为 read/grep/... fork 一次 git rev-parse
  // （插件常驻 OpenCode 服务进程，这笔同步 execSync 会卡事件循环）。
  // 用只记账的 git shim 顶掉 PATH：读类工具后账本必须为空，写类工具后必须有记录——
  // 后一条防止这个断言变成永真。
  if (process.platform !== "win32") {
    const shimDir = path.join(tmp, "bin");
    const gitLog = path.join(tmp, "git-calls.log");
    fs.mkdirSync(shimDir, { recursive: true });
    fs.writeFileSync(
      path.join(shimDir, "git"),
      `#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(gitLog)}\nprintf '%s\\n' ${JSON.stringify(tmp)}\n`,
      { mode: 0o755 }
    );
    const realPath = process.env.PATH;
    process.env.PATH = shimDir;
    try {
      for (const tool of ["read", "grep", "glob", "question", "subagent", "webfetch"]) {
        await before(tool, {});
      }
      assert.equal(
        fs.existsSync(gitLog),
        false,
        "non-write tools must not fork git rev-parse"
      );
      await before("write", { path: "book/正文/第002章_续写.md" });
      assert.match(
        fs.readFileSync(gitLog, "utf8"),
        /rev-parse/,
        "git shim must actually intercept projectRoot()"
      );
    } finally {
      process.env.PATH = realPath;
    }
  }

  const compact = { system: [] };
  await hooks.session.compaction(compact);
  assert(compact.system.some((part) => part.type === "text" && part.text.includes("Writing context: book/追踪/上下文.md")));

  // session.context：主会话首轮请求注入部署状态、当前书目上下文与连续性提醒；同会话后续轮次与子代理跳过。
  fs.writeFileSync(".story-deployed", "target_cli: claude-code\n", "utf8");
  const subagentCtx = { sessionID: "ses_1", agent: "consistency-checker", system: [] };
  await hooks.session.context(subagentCtx);
  assert.equal(subagentCtx.system.length, 0, "subagent requests must skip main-session context injection");

  const primaryCtx = { sessionID: "ses_1", agent: "code", system: [] };
  await hooks.session.context(primaryCtx);
  assert.equal(primaryCtx.system.length, 1);
  assert.match(primaryCtx.system[0].text, /当前部署标记未包含 opencode/);
  assert.match(primaryCtx.system[0].text, /\[story context\] 当前书目：book。继续长篇写作前先读取 book\/追踪\/上下文\.md。/);

  const secondTurnCtx = { sessionID: "ses_1", agent: "code", system: [] };
  await hooks.session.context(secondTurnCtx);
  assert.equal(secondTurnCtx.system.length, 0, "same session must not re-inject session context on every turn");
  fs.unlinkSync(".story-deployed");

  // 共享核 staged commit 检查也会拉 git。直接调用已部署布局中的真实模块，代理只记录并
  // 转发，确保断言命中 stagedMarkdownWarnings() 实际传给 spawnSync 的 options。
  const require = createRequire(import.meta.url);
  const core = require(path.join(deployDir, "lib", "story_hook_core.js"));
  core.stagedMarkdownWarnings(tmp);

  const projectRootCalls = childProcessCalls.filter(
    (call) => call.method === "execSync" && call.command === "git rev-parse --show-toplevel"
  );
  assert(projectRootCalls.length > 0, "projectRoot() must exercise execSync");
  assert(
    projectRootCalls.every((call) => call.options?.windowsHide === true),
    "projectRoot() must hide the git console window on Windows"
  );

  const tryGitCalls = childProcessCalls.filter(
    (call) => call.method === "execSync" && /^git diff --name-only(?: --cached)?$/.test(call.command)
  );
  assert.equal(tryGitCalls.length, 2, "preCompactOutput() must exercise both tryGit() calls");
  assert(
    tryGitCalls.every((call) => call.options?.windowsHide === true),
    "tryGit() must hide the git console window on Windows"
  );

  const stagedWarningCalls = childProcessCalls.filter(
    (call) => call.method === "spawnSync" && call.command === "git" && call.args?.includes("--cached")
  );
  assert.equal(stagedWarningCalls.length, 1, "stagedMarkdownWarnings() must exercise spawnSync once");
  assert.equal(
    stagedWarningCalls[0].options?.windowsHide,
    true,
    "stagedMarkdownWarnings() must hide the git console window on Windows"
  );

  // shell git commit 暂存提醒：execute.before 在提交清暂存区前捕获硬编码角色属性，execute.after
  // 在 pre-commit 未输出过警告时补齐到工具结果；若 pre-commit 已输出则不重复追加。
  fs.writeFileSync("book/正文/第001章_开局.md", "他今年年龄：18，走进了旧书店。\n", "utf8");
  execFileSync("git", ["-C", tmp, "add", "book/正文/第001章_开局.md"]);
  await hooks.tool["execute.before"]({
    id: "call_commit_1",
    tool: "shell",
    input: { command: "git commit -m 'test commit'" },
  });
  const commitEvent = {
    id: "call_commit_1",
    tool: "shell",
    input: { command: "git commit -m 'test commit'" },
    status: "completed",
    result: { content: "[main abc1234] test commit" },
  };
  await hooks.tool["execute.after"](commitEvent);
  assert.match(commitEvent.result.content, /Story Commit Warnings/);
  assert.match(commitEvent.result.content, /正文硬编码角色属性/);

  await hooks.tool["execute.before"]({
    id: "call_commit_2",
    tool: "shell",
    input: { command: "git commit -m 'test commit'" },
  });
  const dedupCommitEvent = {
    id: "call_commit_2",
    tool: "shell",
    input: { command: "git commit -m 'test commit'" },
    status: "completed",
    result: { content: "=== Story Commit Warnings（advisory only）===\nexisting\n=== End Warnings ===" },
  };
  await hooks.tool["execute.after"](dedupCommitEvent);
  assert.equal(
    dedupCommitEvent.result.content.match(/Story Commit Warnings/g)?.length,
    1,
    "must not duplicate Story Commit Warnings when pre-commit hook already emitted it"
  );

  console.log("OK: OpenCode plugin guards outlines and reports after-write findings behaviorally");
} finally {
  childProcess.execSync = originalExecSync;
  childProcess.spawnSync = originalSpawnSync;
  syncBuiltinESMExports();
  process.chdir(originalCwd);
  fs.rmSync(tmp, { recursive: true, force: true });
}
