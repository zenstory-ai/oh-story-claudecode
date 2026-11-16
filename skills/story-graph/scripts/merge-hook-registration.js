#!/usr/bin/env node
"use strict";

/**
 * merge-hook-registration.js — 将知识图谱 hooks 合并到 settings.local.json
 *
 * 在现有 hook 注册中追加 graph session-start 和 post-write 检查，
 * 保持用户已有配置不变（按 command 字符串去重）。
 *
 * 使用方式:
 *   node merge-hook-registration.js <项目根目录>
 */

const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(process.argv[2] || ".");
const settingsPath = path.join(projectRoot, ".claude", "settings.local.json");

// ── 要注册的 hooks ──────────────────────────────────────────

const GRAPH_HOOKS = {
  SessionStart: {
    type: "command",
    command: `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/session-start-graph.sh`,
    timeout: 10
  },
  PostToolUse: {
    matcher: "Write|Edit|MultiEdit",
    type: "command",
    command: `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/graph-update-check.sh`,
    timeout: 10
  }
};

// ── 读取现有配置 ────────────────────────────────────────────

let settings = {};
if (fs.existsSync(settingsPath)) {
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  } catch (e) {
    console.error(`[ERROR] 无法解析 ${settingsPath}: ${e.message}`);
    process.exit(1);
  }
}

// 确保 hooks 对象存在
if (!settings.hooks) settings.hooks = {};

// ── 合并 SessionStart ───────────────────────────────────────

if (!settings.hooks.SessionStart) settings.hooks.SessionStart = [];
if (settings.hooks.SessionStart.length === 0) {
  settings.hooks.SessionStart.push({ hooks: [] });
}

// 在第一个 SessionStart group 中追加 graph hook
const ssGroup = settings.hooks.SessionStart[0];
if (!ssGroup.hooks) ssGroup.hooks = [];

// 去重：检查是否已注册
const ssAlreadyRegistered = ssGroup.hooks.some(
  h => h.command && h.command.includes("session-start-graph.sh")
);

if (!ssAlreadyRegistered) {
  ssGroup.hooks.push(GRAPH_HOOKS.SessionStart);
  console.log("[graph] 已注册 SessionStart hook: session-start-graph.sh");
} else {
  console.log("[graph] SessionStart hook 已存在，跳过");
}

// ── 合并 PostToolUse ────────────────────────────────────────

if (!settings.hooks.PostToolUse) settings.hooks.PostToolUse = [];

// 找到 matcher 为 Write|Edit|MultiEdit 的 group，追加 graph hook
let ptGroup = settings.hooks.PostToolUse.find(
  g => g.matcher === "Write|Edit|MultiEdit"
);

if (!ptGroup) {
  ptGroup = { matcher: "Write|Edit|MultiEdit", hooks: [] };
  settings.hooks.PostToolUse.push(ptGroup);
}

if (!ptGroup.hooks) ptGroup.hooks = [];

const ptAlreadyRegistered = ptGroup.hooks.some(
  h => h.command && h.command.includes("graph-update-check.sh")
);

if (!ptAlreadyRegistered) {
  ptGroup.hooks.push(GRAPH_HOOKS.PostToolUse);
  console.log("[graph] 已注册 PostToolUse hook: graph-update-check.sh");
} else {
  console.log("[graph] PostToolUse hook 已存在，跳过");
}

// ── 写回 ────────────────────────────────────────────────────

// 确保目录存在
const settingsDir = path.dirname(settingsPath);
if (!fs.existsSync(settingsDir)) fs.mkdirSync(settingsDir, { recursive: true });

fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n", "utf8");
console.log(`[graph] 配置已写入 ${settingsPath}`);
