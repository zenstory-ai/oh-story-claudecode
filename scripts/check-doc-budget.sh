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
for (const group of manifest.paths || []) {
  if (group.branches) {
    for (const branch of group.branches) {
      checkPath(`${group.label}（${branch.label}）`, branch.budget, [...group.files, ...branch.files]);
    }
  } else {
    checkPath(group.label, group.budget, group.files);
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
