#!/usr/bin/env node
"use strict";

/**
 * deploy-graph.js — 知识图谱增强系统部署（跨平台 Node.js 版）
 *
 * 部署 graph agents、hook 脚本、Node.js 核心库到写作项目，
 * 注册 hooks 到 settings.local.json，注入 CLAUDE.md 段，更新 .gitignore。
 *
 * 使用: node deploy-graph.js [项目根目录]
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const SKILL_DIR = path.resolve(__dirname, "..");
const ROOT = path.resolve(process.argv[2] || ".");

function log(msg) { console.log("[graph] " + msg); }
function fail(msg) { console.error("[graph] ERROR: " + msg); process.exit(1); }

log("部署知识图谱增强系统 → " + ROOT);

// ── 0. 部署 skill 定义 ──────────────────────
// 尊重 skills CLI 安装形态：.agents/skills/ 是真实文件存储，
// .claude/skills/{name} 是指向 ../../.agents/skills/{name} 的符号链接。
let skillDst = path.join(ROOT, ".claude", "skills", "story-graph");
const linkProbe = path.join(ROOT, ".claude", "skills", "story");
let isLinkLayout = false;
try { isLinkLayout = fs.lstatSync(linkProbe).isSymbolicLink(); } catch (e) {}
if (isLinkLayout) {
  const linkTarget = fs.readlinkSync(linkProbe);            // ../../.agents/skills/story
  const linkDir = linkTarget.split("/").slice(0, -1).join("/"); // ../../.agents/skills
  const store = path.join(ROOT, ".agents", "skills", "story-graph");
  try { fs.rmSync(store, { recursive: true, force: true }); } catch (e) {}
  try { fs.rmSync(skillDst, { force: true }); } catch (e) {}
  fs.mkdirSync(store, { recursive: true });
  copyDir(SKILL_DIR, store, [".git", "node_modules"]);
  try {
    fs.symlinkSync(linkDir + "/story-graph", skillDst, "dir");
    log("skill 定义（符号链接形态，真实文件）→ " + store);
  } catch (e) {
    // Windows 无符号链接权限：退化为真实目录
    copyDir(SKILL_DIR, skillDst, [".git", "node_modules"]);
    log("⚠ 无法创建符号链接，已退化为真实目录 → " + skillDst);
  }
  skillDst = store;
} else {
  try { fs.rmSync(skillDst, { recursive: true, force: true }); } catch (e) {}
  fs.mkdirSync(skillDst, { recursive: true });
  copyDir(SKILL_DIR, skillDst, [".git", "node_modules"]);
  log("skill 定义 → " + skillDst);
}

// ── 1. 部署 Agents ──────────────────────────
const agentsDst = path.join(ROOT, ".claude", "agents");
if (!fs.existsSync(agentsDst)) fail(".claude/agents/ 不存在，请先运行 /story-setup");
const agentsSrc = path.join(SKILL_DIR, "templates", "agents");
for (const f of fs.readdirSync(agentsSrc)) {
  fs.copyFileSync(path.join(agentsSrc, f), path.join(agentsDst, f));
}
log("agents: graph-builder + story-explorer（图谱增强版）→ " + agentsDst);
log("⚠ story-explorer.md 覆盖 story-setup 同名 agent（图可用走图、不可用降级文件）；重跑 /story-setup 后需重跑本部署");

// ── 2. 部署 Hook 脚本 ──────────────────────
const hooksDst = path.join(ROOT, ".claude", "hooks");
if (!fs.existsSync(hooksDst)) fail(".claude/hooks/ 不存在，请先运行 /story-setup");
const hookFiles = ["story_graph_core.js", "story_graph_cli.js", "viz_html.js",
                   "session-start-graph.sh", "graph-update-check.sh", "deploy-graph.sh"];
for (const f of hookFiles) {
  const src = path.join(SKILL_DIR, "scripts", f);
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, path.join(hooksDst, f));
    if (f.endsWith(".sh")) fs.chmodSync(path.join(hooksDst, f), 0o755);
  }
}
log("hooks → " + hooksDst);

// ── 3. 注册 Hooks ───────────────────────────
const mergeScript = path.join(SKILL_DIR, "scripts", "merge-hook-registration.js");
const settingsPath = path.join(ROOT, ".claude", "settings.local.json");
let settings = {};
if (fs.existsSync(settingsPath)) {
  try { settings = JSON.parse(fs.readFileSync(settingsPath, "utf8")); } catch (e) {}
}
if (!settings.hooks) settings.hooks = {};
if (!settings.hooks.SessionStart) settings.hooks.SessionStart = [{ hooks: [] }];
if (!settings.hooks.PostToolUse) settings.hooks.PostToolUse = [];

const ssGroup = settings.hooks.SessionStart[0];
if (!ssGroup.hooks) ssGroup.hooks = [];
if (!ssGroup.hooks.some(h => h.command && h.command.includes("session-start-graph.sh"))) {
  ssGroup.hooks.push({
    type: "command",
    command: `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/session-start-graph.sh`,
    timeout: 10
  });
  log("注册 SessionStart: session-start-graph.sh");
}

let ptGroup = settings.hooks.PostToolUse.find(g => g.matcher === "Write|Edit|MultiEdit");
if (!ptGroup) { ptGroup = { matcher: "Write|Edit|MultiEdit", hooks: [] }; settings.hooks.PostToolUse.push(ptGroup); }
if (!ptGroup.hooks) ptGroup.hooks = [];
if (!ptGroup.hooks.some(h => h.command && h.command.includes("graph-update-check.sh"))) {
  ptGroup.hooks.push({
    type: "command",
    command: `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/graph-update-check.sh`,
    timeout: 10
  });
  log("注册 PostToolUse: graph-update-check.sh");
}

fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n", "utf8");
log("hooks 已注册到 settings.local.json");

// ── 4. 更新 .gitignore ─────────────────────
const giPath = path.join(ROOT, ".gitignore");
const giLines = fs.existsSync(giPath) ?
  fs.readFileSync(giPath, "utf8").split("\n") : [];
const giNeeded = ["story.db", "story.db-wal", "story.db-shm"];
let changed = false;
for (const n of giNeeded) {
  if (!giLines.some(l => l.trim() === n)) {
    giLines.push(n);
    changed = true;
  }
}
if (changed) {
  fs.writeFileSync(giPath, giLines.join("\n") + "\n", "utf8");
  log(".gitignore 已更新 (story.db)");
}

// ── 5. 注入 CLAUDE.md ──────────────────────
const claudePath = path.join(ROOT, "CLAUDE.md");
if (fs.existsSync(claudePath)) {
  const graphSection = `## 知识图谱

\`story.db\` 存在时，写作循环自动走图（story-explorer 是图谱增强版查询 agent，图不可用自动降级读文件）：
- 写前：spawn story-explorer 做 context_load，获取角色状态/钩子/闪回建议/时空位置
- 写中：根据 context_load 结果决定内容——角色在哪写哪、钩子触发写触发、闪回评分高就插回忆
- 写后：每批次完成后自动 \`/story-graph update\`
- 图不可用时 story-explorer 降级读文件，不影响写作

\`/story-graph seed\`（初始化）· \`/story-graph update\`（增量）· \`/story-graph\`（统计）`;

  let content = fs.readFileSync(claudePath, "utf8");
  const re = /^## 知识图谱\n[\s\S]*?(?=^## |\n## |\n*$)/m;
  if (re.test(content)) {
    content = content.replace(re, graphSection);
    log("CLAUDE.md 知识图谱段已更新");
  } else {
    const idx = content.indexOf("## Compact");
    if (idx > 0) {
      content = content.slice(0, idx) + graphSection + "\n\n" + content.slice(idx);
    } else {
      content += "\n" + graphSection + "\n";
    }
    log("CLAUDE.md 已追加知识图谱段");
  }
  fs.writeFileSync(claudePath, content, "utf8");
}

// ── 6. 安装依赖（装进 skill 目录，项目根保持干净）─────────
// 写作项目根通常没有 package.json；依赖统一装到 .claude/skills/story-graph/node_modules，
// story_graph_core.js 按部署拓扑解析（.claude/hooks → ../skills/story-graph/node_modules）。
const skillDeps = path.join(skillDst, "node_modules", "better-sqlite3");
if (fs.existsSync(skillDeps)) {
  log("better-sqlite3 已安装（skill 目录）");
} else {
  log("正在安装 better-sqlite3 到 skill 目录...");
  try {
    execSync("npm install better-sqlite3 --no-save --no-package-lock", { cwd: skillDst, stdio: "pipe" });
    log("better-sqlite3 已安装 → " + path.join(skillDst, "node_modules"));
  } catch (e2) {
    log("⚠ npm install 失败，请手动安装: cd " + skillDst + " && npm install better-sqlite3 --no-save");
  }
}

// ── 7. 写作流程收口 ─────────────────────────
// 给已部署的 story-long-write 注入图谱更新步骤（幂等）
log("收口写作流程（story-long-write 注入图谱更新步骤）...");
try {
  execSync(process.execPath + " " + JSON.stringify(path.join(SKILL_DIR, "scripts", "patch-long-write.js")) + " " + JSON.stringify(ROOT), { stdio: "pipe" });
  log("写作流程收口完成（未部署 story-long-write 时跳过）");
} catch (e) {
  log("⚠ 写作流程收口失败（需 node 可用）");
}

console.log("\n部署完成。新开会话后生效。");
console.log("  1. /story-graph seed — 构建初始图谱");
console.log("  2. 写作时 story-explorer 自动处理上下文（图优先，文件降级）");
console.log("  3. 正文落盘后系统自动提示增量更新（写作流程已收口，提示仅是兜底）");

// ── helpers ─────────────────────────────────
function copyDir(src, dst, exclude) {
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (exclude && exclude.includes(entry.name)) continue;
    const s = path.join(src, entry.name), d = path.join(dst, entry.name);
    if (entry.isDirectory()) { fs.mkdirSync(d, { recursive: true }); copyDir(s, d, exclude); }
    else fs.copyFileSync(s, d);
  }
}
