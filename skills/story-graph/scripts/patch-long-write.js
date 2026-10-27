#!/usr/bin/env node
"use strict";

/**
 * patch-long-write.js — 给已部署的 story-long-write 技能注入图谱更新步骤（幂等）
 *
 * 写作流程原本不含知识图谱步骤（图更新依赖 hook 提示 + AI 自觉执行 /story-graph update）。
 * 本脚本在部署图谱时收口写作流程：
 *   - SKILL.md Phase 4 单章流程 Step 12 之后注入 12b（单章场景写完即更新图）
 *   - workflow-daily.md Step 3/4 之间注入批量收尾（日更批末一次更新全部章节）
 * 注入块带 `<!-- story-graph:update-step -->` 标记，重复执行自动跳过；
 * 文件缺失（未部署 story-long-write）时跳过并在结果中标注。
 *
 * 用法: node patch-long-write.js <项目根目录>
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2] || ".");
const SKILL_MD = path.join(ROOT, ".claude", "skills", "story-long-write", "SKILL.md");
const DAILY_MD = path.join(ROOT, ".claude", "skills", "story-long-write", "references", "workflow-daily.md");

const MARKER = "story-graph:update-step";

const SKILL_STEP = `<!-- story-graph:update-step -->
12b. **知识图谱更新**（story-graph 已部署时）：若 \`{书}/story.db\` 存在，执行 \`/story-graph update\` —— 增量提取本章实体/事件/钩子（幂等；与追踪文件同步更新，hook 的「📊 知识图谱需更新」提示仅是兜底提醒）。
<!-- /story-graph:update-step -->`;

const DAILY_STEP = `<!-- story-graph:update-step -->
> **批量收尾（story-graph 已部署时）**：若 \`{书}/story.db\` 存在，本批全部章节写完后执行 \`/story-graph update\`（一次更新本批全部章节，幂等；单章场景已由 SKILL.md Step 12b 更新，此处可跳过）。
<!-- /story-graph:update-step -->`;

/**
 * 在 anchor 之前注入 step；文件不存在 → {reason: "missing"}；已含标记 → {reason: "already"}
 */
function patch(target, step, anchor) {
  if (!fs.existsSync(target)) return { patched: false, reason: "missing", target };
  let text = fs.readFileSync(target, "utf8");
  if (text.includes(MARKER)) return { patched: false, reason: "already", target };
  const idx = text.indexOf(anchor);
  if (idx >= 0) {
    text = text.slice(0, idx) + step + "\n\n" + text.slice(idx);
  } else {
    text += "\n\n" + step;
  }
  fs.writeFileSync(target, text, "utf8");
  return { patched: true, target };
}

const results = {
  skill: patch(SKILL_MD, SKILL_STEP, "13. **中途快照**"),
  daily: patch(DAILY_MD, DAILY_STEP, "## Step 4：进度摘要"),
};

process.stdout.write(JSON.stringify(results, null, 2) + "\n");
