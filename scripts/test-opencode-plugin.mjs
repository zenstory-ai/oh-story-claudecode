#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = path.join(repoRoot, "skills/story-setup/references/opencode");
const tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "story-opencode-plugin-")));
const originalCwd = process.cwd();

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

  fs.writeFileSync("book/大纲/细纲_第1章.md", "# 细纲\n", "utf8");
  await assert.rejects(
    () => before("write", { path: "book/正文/第001章_开局.md" }),
    /_tracking-state\.json 缺失/,
    "long prose with outline but no tracking checkpoint must fail closed"
  );
  writeCleanState("book");
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
  fs.writeFileSync("cwd-book/大纲/细纲_第8章.md", "# 细纲\n", "utf8");
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
  fs.writeFileSync("book/大纲/细纲_第4章.md", "# 细纲\n", "utf8");
  await before("patch", { patchText: addPatch("book/正文/第004章_补丁.md") });

  // *** Move to: 是 patch 的搬家/改名形态（Update/Delete File 段的子指令），落盘路径是
  // 目的地。只认 Add/Update File 时「Update draft.md + Move to 书/正文/第N章.md」只抽到
  // draft.md：细纲门整条空过、写后兜底网扫的还是已不存在的源，等于把无细纲草稿直接搬成新章。
  const movePatch = (source, destination, verb = "Update") =>
    `*** Begin Patch\n*** ${verb} File: ${source}\n*** Move to: ${destination}\n+正文第一句。\n*** End Patch\n`;
  fs.writeFileSync("draft.md", "草稿一句。\n", "utf8");
  await expectBlocked(
    () => before("patch", { patchText: movePatch("draft.md", "book/正文/第009章_搬家.md") }),
    "patch *** Move to: must not bypass the outline guard"
  );
  // 判据必须落在目的地那一章（第 9 章），而不是源 draft.md（源不是正文，本就不该被判）
  await assert.rejects(
    () => before("patch", { patchText: movePatch("draft.md", "book/正文/第009章_搬家.md") }),
    /第 9 章缺少细纲/,
    "Move 的拦截判据必须算在目的地章号上"
  );
  // Delete File + Move to（搬走后删源）也是搬家：目的地同样要进表
  await expectBlocked(
    () => before("patch", { patchText: movePatch("draft.md", "book/正文/第010章_搬家.md", "Delete") }),
    "*** Delete File: + *** Move to: must gate the destination too"
  );
  // 补上细纲就放行：门是补细纲能过的门，不是把 Move 一律拦死
  fs.writeFileSync("book/大纲/细纲_第9章.md", "# 细纲\n", "utf8");
  writeCleanState("book", 8);
  await before("patch", { patchText: movePatch("draft.md", "book/正文/第009章_搬家.md") });
  // 反向：把正文搬出 正文/（目的地不是正文）不该被拦——源不再被当成写入目标
  await before("patch", { patchText: movePatch("book/正文/第002章_续写.md", "draft_out.md") });
  // 纯 Delete 不入表（共享核里写明的取舍）：删一个不存在、也没细纲的章号不该被误报成写正文
  await before("patch", {
    patchText: "*** Begin Patch\n*** Delete File: book/正文/第011章_删稿.md\n*** End Patch\n",
  });

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

  // 反向：搬出 正文/ 的补丁不该拿源去扫（源已不存在；目的地不是正文）——结果原样返回
  assert.equal(
    await after("patch", { patchText: movePatch("book/正文/第009章_搬家.md", "draft_out.md") }, "unchanged"),
    "unchanged"
  );

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

  console.log("OK: OpenCode plugin guards outlines and reports after-write findings behaviorally");
} finally {
  process.chdir(originalCwd);
  fs.rmSync(tmp, { recursive: true, force: true });
}
