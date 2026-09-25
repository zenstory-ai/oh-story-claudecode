#!/bin/bash
# check-doc-budget.sh — 热路径文档预算守卫（防 skill / agent 模板无声膨胀）
#
# 背景：skill 文本是每个用户每次会话都要付的 token。逐条加规则每次都只贵一点点，
# 累积起来就是日更路径翻倍。本守卫给「每次会话或每章都进上下文」的文件设上限，
# 超了就红，逼作者要么删等量旧文本，要么显式在 scripts/doc-budget.json 里调高预算。
#
# 度量：去掉所有空白后的字符数。中英文都算，改标点/换行/缩进不影响读数。
# 冷路径（story-setup 部署、UPGRADING、拆文库模板）不登记，不受限。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$SCRIPT_DIR/doc-budget.json"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      [ "$#" -ge 2 ] || { echo "FAIL: --root 缺少路径"; exit 2; }
      REPO_ROOT="$2"
      shift 2
      ;;
    --manifest)
      [ "$#" -ge 2 ] || { echo "FAIL: --manifest 缺少路径"; exit 2; }
      MANIFEST="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: bash scripts/check-doc-budget.sh [--root DIR] [--manifest FILE]"
      exit 0
      ;;
    *)
      echo "FAIL: 未知参数：$1"
      exit 2
      ;;
  esac
done

if [ ! -f "$MANIFEST" ]; then
  echo "FAIL: 预算清单缺失：$MANIFEST"
  exit 1
fi

node -e '
const fs = require("fs");
const path = require("path");
const [manifestPath, repoRoot] = process.argv.slice(1);
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

// 去空白字符数：改标点/换行/缩进不影响，加删正文才影响。
const weigh = (rel) => {
  const abs = path.join(repoRoot, rel);
  if (!fs.existsSync(abs)) return null;
  return fs.readFileSync(abs, "utf8").replace(/\s/g, "").length;
};

const fail = [];
const note = [];

console.log("热路径文档预算");
console.log("".padEnd(78, "-"));
console.log("  用量 /   预算  余量  文件");

for (const entry of manifest.files) {
  const used = weigh(entry.path);
  if (used === null) {
    fail.push(`预算登记的文件不存在：${entry.path}（改名/删除后请同步 doc-budget.json）`);
    continue;
  }
  const left = entry.budget - used;
  const mark = left < 0 ? "OVER" : "ok";
  console.log(`  ${String(used).padStart(6)} / ${String(entry.budget).padStart(6)} ${String(left).padStart(6)}  ${entry.path}  [${mark}]`);
  if (left < 0) {
    fail.push(`${entry.path} 超预算 ${-left} 字（${used} > ${entry.budget}）：${entry.why}`);
  } else if (left >= Math.ceil(entry.budget * 0.05)) {
    note.push(`${entry.path} 比预算低 ${left} 字，可把 budget 降到 ${Math.ceil(used / 100) * 100} 锁住这次精简`);
  }
}

console.log("");
console.log("已登记路径合计（不含项目资料与未登记条件项）");
console.log("".padEnd(78, "-"));
const checkPath = (label, budget, files) => {
  let total = 0;
  const missing = [];
  for (const rel of files) {
    const used = weigh(rel);
    if (used === null) { missing.push(rel); continue; }
    total += used;
  }
  if (missing.length) {
    for (const rel of missing) fail.push(`路径「${label}」登记的文件不存在：${rel}`);
    return;
  }
  const left = budget - total;
  console.log(`  ${String(total).padStart(6)} / ${String(budget).padStart(6)} ${String(left).padStart(6)}  ${label}  [${left < 0 ? "OVER" : "ok"}]`);
  if (left < 0) {
    fail.push(`路径「${label}」超预算 ${-left} 字（${total} > ${budget}）`);
  }
};
// agent 模板 frontmatter 的 `skills: [...]` 会把整份 SKILL.md 预加载进该 agent 的每次调用；
// 这部分以前不进任何预算（写手曾因此每次多付一整份 story-deslop）。登记了 agent 的路径自动计入，
// 而带预加载的 agent 模板必须至少有一条 agent 路径，否则预加载就又成了看不见的成本。
const AGENT_DIR = "skills/story-setup/references/templates/agents";
const preloads = (rel) => {
  const abs = path.join(repoRoot, rel);
  if (!fs.existsSync(abs)) return null;
  const head = fs.readFileSync(abs, "utf8").split(/^---\s*$/m)[1] || "";
  const inline = head.match(/^skills:[ \t]*\[([^\]]*)\]/m);
  if (inline) return inline[1].split(",").map((s) => s.trim()).filter(Boolean);
  const block = head.match(/^skills:[ \t]*\r?\n((?:[ \t]+-[^\n]*\n?)+)/m);
  if (block) return block[1].split("\n").map((s) => s.replace(/^[ \t]+-[ \t]*/, "").trim()).filter(Boolean);
  // 读不出的 skills 写法不能当成「没有预加载」放过去。
  if (/^skills:/m.test(head)) fail.push(`${rel} 的 skills 预加载写法认不出，改成 skills: [a, b] 或逐行 - a`);
  return [];
};
const agentPaths = new Set();
for (const group of manifest.paths || []) {
  let files = group.files;
  if (group.agent) {
    agentPaths.add(group.agent);
    const skills = preloads(group.agent);
    if (skills === null) { fail.push(`路径「${group.label}」登记的 agent 不存在：${group.agent}`); continue; }
    files = [group.agent, ...files, ...skills.map((name) => `skills/${name}/SKILL.md`)];
  }
  if (group.branches) {
    for (const branch of group.branches) {
      checkPath(`${group.label}（${branch.label}）`, branch.budget, [...files, ...branch.files]);
    }
  } else {
    checkPath(group.label, group.budget, files);
  }
}
const agentDir = path.join(repoRoot, AGENT_DIR);
if (fs.existsSync(agentDir)) {
  for (const name of fs.readdirSync(agentDir).filter((n) => n.endsWith(".md")).sort()) {
    const rel = `${AGENT_DIR}/${name}`;
    const skills = preloads(rel) || [];
    if (skills.length && !agentPaths.has(rel)) {
      fail.push(`${rel} 预加载了 ${skills.join("、")}，但没有登记 agent 路径——预加载内容进该 agent 每次调用，须计入预算`);
    }
  }
}

if (note.length) {
  console.log("");
  console.log("提示（不阻断）：");
  for (const n of note) console.log(`  - ${n}`);
}

if (fail.length) {
  console.log("");
  console.log("FAIL: 热路径文档超预算");
  for (const f of fail) console.log(`  - ${f}`);
  console.log("");
  console.log("处理顺序：① 先找同一文件里能删的旧文本（重复指令、已被脚本确定性拦住的规则、");
  console.log("设计理由旁白、只在极少数场景才用得上的分支），删等量再提交；");
  console.log("② 确实是必须加的新规则，就在 scripts/doc-budget.json 调高 budget，");
  console.log("并在 PR 里写清为什么这段值得每个用户每次会话都付。");
  process.exit(1);
}

console.log("");
console.log("Result: 热路径文档预算检查通过");
' "$MANIFEST" "$REPO_ROOT"
