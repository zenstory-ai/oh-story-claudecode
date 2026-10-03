#!/bin/bash
# deploy-graph.sh — 部署知识图谱增强系统到写作项目
#
# 将 graph agents、hook 脚本、Node.js 核心库部署到项目本地目录，
# 并注册 hooks 到 settings.local.json，更新 .gitignore。
#
# 使用方式:
#   bash deploy-graph.sh <项目根目录>
#
# 由 /story-graph setup 调用。也可手动运行。
set -euo pipefail

ROOT="${1:-$(pwd)}"
ROOT="$(cd "$ROOT" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== 知识图谱增强系统部署 ==="
echo "项目: $ROOT"

# ── 0. 部署 Skill 本身（让 /story-graph 命令可用） ──────────
# 尊重项目既有形态（skills CLI 安装形态）：.agents/skills/ 是真实文件存储，
# .claude/skills/{name} 是指向 ../../.agents/skills/{name} 的符号链接。
# 检测：.claude/skills/story 是符号链接 → 走链接形态；否则真实目录形态。
SKILL_DST="$ROOT/.claude/skills/story-graph"

echo "[graph] 部署 skill 定义..."
if [ -L "$ROOT/.claude/skills/story" ]; then
  # 链接形态：真实文件放 .agents/skills/story-graph，.claude/skills 只建同款链接
  LINK_PATTERN="$(readlink "$ROOT/.claude/skills/story")"   # 如 ../../.agents/skills/story
  LINK_DIR="$(dirname "$LINK_PATTERN")"                      # 如 ../../.agents/skills
  SKILL_STORE="$ROOT/.agents/skills/story-graph"
  echo "[graph] 检测到 .claude/skills 为符号链接形态（真实目录 .agents/skills/）"
  rm -rf "$SKILL_STORE" 2>/dev/null || true
  rm -f "$SKILL_DST" 2>/dev/null || true
  mkdir -p "$SKILL_STORE"
  cp "$SKILL_DIR/SKILL.md" "$SKILL_STORE/SKILL.md"
  cp -r "$SKILL_DIR/references" "$SKILL_STORE/references"
  cp -r "$SKILL_DIR/scripts" "$SKILL_STORE/scripts"
  cp -r "$SKILL_DIR/templates" "$SKILL_STORE/templates"
  ln -sfn "$LINK_DIR/story-graph" "$SKILL_DST"
  echo "  → 真实文件 $SKILL_STORE；$SKILL_DST → $LINK_DIR/story-graph"
  SKILL_DST="$SKILL_STORE"
else
  # 真实目录形态：直接复制到 .claude/skills/story-graph
  rm -rf "$SKILL_DST" 2>/dev/null || true
  mkdir -p "$SKILL_DST"
  cp "$SKILL_DIR/SKILL.md" "$SKILL_DST/SKILL.md"
  cp -r "$SKILL_DIR/references" "$SKILL_DST/references"
  cp -r "$SKILL_DIR/scripts" "$SKILL_DST/scripts"
  cp -r "$SKILL_DIR/templates" "$SKILL_DST/templates"
  echo "  → $SKILL_DST"
fi

# ── 1. 部署 Agents ──────────────────────────────────────────
AGENTS_SRC="$SKILL_DIR/templates/agents"
AGENTS_DST="$ROOT/.claude/agents"

if [ ! -d "$AGENTS_DST" ]; then
  echo "[graph] .claude/agents/ 不存在，请先运行 /story-setup"
  exit 1
fi

echo "[graph] 部署 agents..."
cp "$AGENTS_SRC/graph-builder.md" "$AGENTS_DST/graph-builder.md"
cp "$AGENTS_SRC/story-explorer.md" "$AGENTS_DST/story-explorer.md"
echo "  → graph-builder.md, story-explorer.md（图谱增强版）→ $AGENTS_DST"
echo "  ⚠ story-explorer.md 会覆盖 story-setup 部署的同名 agent（图可用时走图、不可用降级文件）；"
echo "    重跑 /story-setup 后会恢复为无图版本，需重新运行本部署脚本。"

# ── 2. 部署 Hook 脚本 ──────────────────────────────────────
HOOKS_DST="$ROOT/.claude/hooks"

if [ ! -d "$HOOKS_DST" ]; then
  echo "[graph] .claude/hooks/ 不存在，请先运行 /story-setup"
  exit 1
fi

echo "[graph] 部署 hook 脚本..."
cp "$SKILL_DIR/scripts/session-start-graph.sh" "$HOOKS_DST/session-start-graph.sh"
cp "$SKILL_DIR/scripts/graph-update-check.sh" "$HOOKS_DST/graph-update-check.sh"
cp "$SKILL_DIR/scripts/story_graph_cli.js" "$HOOKS_DST/story_graph_cli.js"
cp "$SKILL_DIR/scripts/story_graph_core.js" "$HOOKS_DST/story_graph_core.js"
cp "$SKILL_DIR/scripts/viz_html.js" "$HOOKS_DST/viz_html.js"
cp "$SKILL_DIR/scripts/deploy-graph.js" "$HOOKS_DST/deploy-graph.js"
chmod +x "$HOOKS_DST/session-start-graph.sh"
chmod +x "$HOOKS_DST/graph-update-check.sh"
echo "  → session-start-graph.sh, graph-update-check.sh, story_graph_cli.js, story_graph_core.js → $HOOKS_DST"

# ── 3. 注册 Hooks ──────────────────────────────────────────
echo "[graph] 注册 hooks 到 settings.local.json..."
node "$SKILL_DIR/scripts/merge-hook-registration.js" "$ROOT"

# ── 4. 更新 .gitignore ─────────────────────────────────────
GITIGNORE="$ROOT/.gitignore"
if [ -f "$GITIGNORE" ]; then
  if ! grep -q "^story.db$" "$GITIGNORE" 2>/dev/null; then
    echo "" >> "$GITIGNORE"
    echo "# 知识图谱数据库（不进 git）" >> "$GITIGNORE"
    echo "story.db" >> "$GITIGNORE"
    echo "story.db-wal" >> "$GITIGNORE"
    echo "story.db-shm" >> "$GITIGNORE"
    echo "[graph] 已添加 story.db 到 .gitignore"
  else
    echo "[graph] story.db 已在 .gitignore 中，跳过"
  fi
else
  echo "story.db" > "$GITIGNORE"
  echo "story.db-wal" >> "$GITIGNORE"
  echo "story.db-shm" >> "$GITIGNORE"
  echo "[graph] 已创建 .gitignore（story.db）"
fi

# ── 5. 注入 CLAUDE.md 知识图谱段 ────────────────────────────
CLAUDE_MD="$ROOT/CLAUDE.md"
GRAPH_SECTION="## 知识图谱

\`story.db\` 存在时，写作循环自动走图（story-explorer 是图谱增强版查询 agent，图不可用自动降级读文件）：
- 写前：spawn story-explorer 做 context_load，获取角色状态/钩子/闪回建议/时空位置
- 写中：根据 context_load 结果决定内容——角色在哪写哪、钩子触发写触发、闪回评分高就插回忆
- 写后：每批次完成后自动 \`/story-graph update\`
- 图不可用时 story-explorer 降级读文件，不影响写作

\`/story-graph seed\`（初始化）· \`/story-graph update\`（增量）· \`/story-graph\`（统计）"

if [ -f "$CLAUDE_MD" ]; then
  if grep -q "^## 知识图谱$" "$CLAUDE_MD" 2>/dev/null; then
    # 已存在则替换
    node -e "
      const fs = require('fs');
      const content = fs.readFileSync('$CLAUDE_MD', 'utf8');
      const section = process.argv[1];
      const re = /^## 知识图谱\n[\s\S]*?(?=^## |\n## |\n*$)/m;
      const updated = content.replace(re, section);
      fs.writeFileSync('$CLAUDE_MD', updated);
      console.log('[graph] CLAUDE.md 知识图谱段已更新');
    " "$GRAPH_SECTION"
  else
    # 不存在则追加在 Compact 段之前
    node -e "
      const fs = require('fs');
      let content = fs.readFileSync('$CLAUDE_MD', 'utf8');
      const section = process.argv[1];
      const compactIdx = content.indexOf('## Compact');
      if (compactIdx > 0) {
        content = content.slice(0, compactIdx) + section + '\n\n' + content.slice(compactIdx);
      } else {
        content += '\n' + section + '\n';
      }
      fs.writeFileSync('$CLAUDE_MD', content);
      console.log('[graph] CLAUDE.md 已追加知识图谱段');
    " "$GRAPH_SECTION"
  fi
else
  echo "[graph] CLAUDE.md 不存在，跳过（请先运行 /story-setup）"
fi

# ── 6. 安装依赖（装进 skill 目录，项目根保持干净）──────────
# 写作项目根通常没有 package.json；依赖统一装到 .claude/skills/story-graph/node_modules，
# story_graph_core.js 会按部署拓扑解析（.claude/hooks → ../skills/story-graph/node_modules）。
echo ""
echo "[graph] 安装 better-sqlite3 到 skill 目录（项目根保持干净）..."
if [ -d "$SKILL_DST/node_modules/better-sqlite3" ]; then
  echo "[graph] better-sqlite3 已安装"
else
  if (cd "$SKILL_DST" && npm install better-sqlite3 --no-save --no-package-lock 2>/dev/null); then
    echo "[graph] better-sqlite3 已安装 → $SKILL_DST/node_modules"
  else
    echo "[graph] ⚠ npm install 失败。请手动运行: cd \"$SKILL_DST\" && npm install better-sqlite3 --no-save"
  fi
fi

# ── 7. 写作流程收口：给已部署的 story-long-write 技能注入图谱更新步骤 ──
# 写作流程原本不含图更新步骤（依赖 hook 提示 + AI 自觉）；部署图谱时收口：
# SKILL.md Step 12 后注入 12b（单章写完即更新），workflow-daily.md 注入批量收尾。
echo ""
echo "[graph] 收口写作流程（story-long-write 注入图谱更新步骤，幂等）..."
if node "$SKILL_DIR/scripts/patch-long-write.js" "$ROOT" >/dev/null 2>&1; then
  echo "[graph] 写作流程收口完成（story-long-write 已注入图谱更新步骤；未部署时自动跳过）"
else
  echo "[graph] ⚠ 写作流程收口失败（需 node 可用）"
fi

echo ""
echo "=== 部署完成 ==="
echo ""
echo "下一步:"
echo "  1. 新开 Claude Code 会话，让 agents 和 hooks 生效"
echo "  2. 运行 /story-graph seed 从设定和大纲构建初始知识图谱"
echo "  3. 写作时 story-explorer agent 可查询时间切片、钩子雷达等（图优先，文件降级）"
echo "  4. 正文落盘后系统会自动提示增量更新图谱（写作流程已收口，提示仅是兜底）"
