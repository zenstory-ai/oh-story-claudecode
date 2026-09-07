#!/bin/bash
# test-degeneration.sh — regression tests for the model-degeneration detector.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository" >&2
  exit 1
fi

SCRIPT="$REPO_ROOT/skills/story-deslop/scripts/check-degeneration.js"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

POS="$TMP_DIR/degen-positive.md"
NEG="$TMP_DIR/degen-negative.md"
OUT="$TMP_DIR/out.json"

# Positive: 紧邻整行复读 + 长句复读3次 + AI自指 + 括号省略占位符 + 末尾截断。
cat > "$POS" <<'EOF'
他握紧了拳头，慢慢站起身来，眼里全是不甘。
他握紧了拳头，慢慢站起身来，眼里全是不甘。
她看着窗外那场下了整夜的大雨，心里空落落的。
过了一会儿。
她看着窗外那场下了整夜的大雨，心里空落落的。
又过了一会儿。
她看着窗外那场下了整夜的大雨，心里空落落的。
作为一个AI语言模型，我无法继续生成这段内容。
（此处省略五百字）
他转过身，慢慢地走向门口，手还在
EOF

# Negative: 通俗网文体裁内的「正常重复」必须不报——弹幕道歉刷屏、短句排比、对话复沓。
cat > "$NEG" <<'EOF'
他站在原地，看着那条消息，久久没有动。
“对不起。”
“对不起。”
“对不起。”
我等你。我等你。我等你。
风很大，吹得人睁不开眼。
作为一个人工智能时代的产物，他对孤独习以为常。
“作为人工智能，我会一直陪着你。”
这一刻，他终于明白了什么叫做释怀。
EOF

set +e
node "$SCRIPT" --json "$POS" > "$OUT"
pos_status=$?
set -e
if [ "$pos_status" -ne 1 ]; then
  echo "FAIL: expected degeneration detector to exit 1 on positive fixture, got $pos_status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi

node - "$OUT" <<'NODE'
const fs = require('fs');
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const counts = report.findings.reduce((m, f) => ((m[f.type] = (m[f.type] || 0) + 1), m), {});
const want = { 'verbatim-repeat': 2, 'placeholder-leak': 2, 'truncated': 1 };
if (report.findings.length !== 5) {
  throw new Error(`expected 5 positive findings, got ${report.findings.length}: ${JSON.stringify(report.findings.map((f) => `${f.type}@${f.line}`))}`);
}
for (const [type, n] of Object.entries(want)) {
  if (counts[type] !== n) throw new Error(`expected ${n} ${type}, got ${counts[type] || 0}`);
}
NODE

# Negative fixture must be clean (exit 0). 通俗网文 的排比/复沓/弹幕刷屏不是退化。
set +e
neg_out="$(node "$SCRIPT" "$NEG" 2>&1)"
neg_status=$?
set -e
if [ "$neg_status" -ne 0 ]; then
  echo "FAIL: degeneration detector false-positive on legit 重复/排比/弹幕 prose (exit $neg_status):" >&2
  echo "$neg_out" >&2
  exit 1
fi

# --- AI 自指（不带拒绝语）：上面正例的第29行其实是被「生成拒绝语」规则接住的，AI 自指规则
#     本身此前零覆盖——带型号后缀的最典型退化开场（AI语言模型/AI助手/人工智能语言模型/AI模型）
#     整类漏检也照样通过。这条只留自指、不含 我无法/我不能，逐条锁到 label 上。
AI_SELF="$TMP_DIR/ai-selfref.md"
cat > "$AI_SELF" <<'EOF'
作为一个AI语言模型，我需要提醒您。
作为一个AI助手，这段内容涉及敏感话题。
作为一个人工智能语言模型，我会尽力帮您续写。
作为一个AI模型，这段情节需要调整。
他把灯关了。
EOF
set +e
node "$SCRIPT" --json "$AI_SELF" > "$OUT"
ai_self_status=$?
set -e
if [ "$ai_self_status" -ne 1 ]; then
  echo "FAIL: AI 自指 fixture 应退出 1，实际 $ai_self_status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const leaks = r.findings.filter((f) => f.type === 'placeholder-leak');
if (leaks.length !== 4) {
  throw new Error(`expected 4 AI 自指 findings, got ${leaks.length}: ${JSON.stringify(leaks.map((f) => `${f.line}:${f.excerpt}`))}`);
}
if (!leaks.every((f) => f.message.includes('AI 自指'))) {
  throw new Error('必须由 AI 自指规则命中（不得靠拒绝语规则代劳）: ' + JSON.stringify(leaks.map((f) => f.message)));
}
NODE

# --- 软拒绝语只豁免成对引号内部：混合行的引号外泄漏必须命中，合法台词仍静默 ---
QUOTE_SCOPE="$TMP_DIR/quote-scope.md"
cat > "$QUOTE_SCOPE" <<'EOF'
“任务完成。”作为AI，我无法继续创作。
作为AI，我无法继续创作。“你别怕。”
“甲说完了。”“乙也点头。”我无法继续创作。
“作为AI，我无法继续创作。”
他说：“作为AI，我无法继续创作。”
“任务完成。作为AI，我无法继续创作。
“I cannot continue writing this scene.”
don't 作为AI，我无法继续创作。 John's!
don’t 作为AI，我无法继续创作。 John’s!
don‘t 作为AI，我无法继续创作。 John’s!
他说：'作为AI，我无法继续创作。'然后关了门。
他说：‘作为AI，我无法继续创作。’然后关了门。
EOF
set +e
node "$SCRIPT" --json "$QUOTE_SCOPE" > "$OUT"
quote_scope_status=$?
set -e
if [ "$quote_scope_status" -ne 1 ]; then
  echo "FAIL: 引号外/未闭合引号内的退化文本应退出 1，实际 $quote_scope_status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi
node - "$OUT" <<'NODE'
const fs = require('fs');
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const leaks = report.findings.filter((f) => f.type === 'placeholder-leak');
const expected = new Map([
  [1, { column: 8, label: 'AI 自指' }],
  [2, { column: 1, label: 'AI 自指' }],
  [3, { column: 15, label: '生成拒绝语' }],
  [6, { column: 7, label: 'AI 自指' }],
  [8, { column: 7, label: 'AI 自指' }],
  [9, { column: 7, label: 'AI 自指' }],
  [10, { column: 7, label: 'AI 自指' }],
]);
if (leaks.length !== expected.size) {
  throw new Error(`expected ${expected.size} quote-scope leaks, got ${leaks.length}: ${JSON.stringify(leaks)}`);
}
for (const finding of leaks) {
  const want = expected.get(finding.line);
  if (!want) throw new Error(`纯引号台词被误报: ${JSON.stringify(finding)}`);
  if (finding.column !== want.column) throw new Error(`line ${finding.line} column expected ${want.column}, got ${finding.column}`);
  if (!finding.message.includes(want.label)) throw new Error(`line ${finding.line} expected ${want.label}: ${finding.message}`);
  if (!finding.excerpt.includes(finding.line === 3 ? '我无法继续创作' : '作为AI')) {
    throw new Error(`line ${finding.line} evidence 未指向真实泄漏: ${finding.excerpt}`);
  }
}
NODE

# --- 工程词泄漏 meta-leak（issue #173 comment 4814607240）---
META_POS="$TMP_DIR/meta-positive.md"
META_NEG="$TMP_DIR/meta-negative.md"

# 正例：纯工程词(细纲/情节点) + 章节结构词(本章/下一章，含对话里的) + 系统标签词(任务描述)。
cat > "$META_POS" <<'EOF'
## 第5章 真相
他握紧了拳头，慢慢站起身来。
本章他终于发现了真相。
“该到下一章了。”他低声说。
按照细纲，他应该先去找她。
这个情节点其实早就埋下了。
任务描述：保护好那个女孩。
EOF
set +e
node "$SCRIPT" --json "$META_POS" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const meta = report.findings.filter((f) => f.type === 'meta-leak');
if (meta.length !== 5) {
  throw new Error(`expected 5 meta-leak findings (本章/下一章/细纲/情节点/任务描述), got ${meta.length}: ${JSON.stringify(meta.map((f) => f.excerpt))}`);
}
NODE

# 负例：标题行「第N章 章名」(无 ## 前缀) 必须不算工程词泄漏；正常正文 0 命中。
cat > "$META_NEG" <<'EOF'
第1章 军宣新星
他站在台上，看着台下黑压压的人群。
风很大，吹得旗子猎猎作响。
他握紧了话筒，深吸一口气。
EOF
set +e
meta_neg_out="$(node "$SCRIPT" "$META_NEG" 2>&1)"
meta_neg_status=$?
set -e
if [ "$meta_neg_status" -ne 0 ]; then
  echo "FAIL: meta-leak false-positive on chapter title line / clean prose (exit $meta_neg_status):" >&2
  echo "$meta_neg_out" >&2
  exit 1
fi

# --- 引号整行豁免回归：混合行（叙述 + 引号内物件）的复读不能被一个引号整行跳过 ---
MIX="$TMP_DIR/mix-repeat.md"
cat > "$MIX" <<'EOF'
他把纸条展开，上面写着“归来”，她看着窗外那场整夜的大雨，心里空落落的。
他把纸条展开，上面写着“归来”，她看着窗外那场整夜的大雨，心里空落落的。
他把纸条展开，上面写着“归来”，她看着窗外那场整夜的大雨，心里空落落的。
EOF
set +e
node "$SCRIPT" --json "$MIX" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rep = r.findings.filter((f) => f.type === 'verbatim-repeat');
if (rep.length === 0) throw new Error('引号整行豁免回归：混合行复读未被检出');
if (!rep.every((f) => f.severity === 'blocking')) throw new Error('verbatim-repeat 应为 severity=blocking');
NODE

# 纯台词复沓仍豁免（体裁手法）：三行相同台词不报。
PURE_DLG="$TMP_DIR/pure-dialogue.md"
cat > "$PURE_DLG" <<'EOF'
“我不走。”
“我不走。”
“我不走。”
EOF
set +e
pure_dlg_out="$(node "$SCRIPT" "$PURE_DLG" 2>&1)"
pure_dlg_status=$?
set -e
if [ "$pure_dlg_status" -ne 0 ]; then
  echo "FAIL: 纯台词复沓被误判为复读 (exit $pure_dlg_status):" >&2
  echo "$pure_dlg_out" >&2
  exit 1
fi

# --- severity 字段 + --fail-on 语义：仅 advisory（tier2）时默认退出 1，--fail-on=blocking 退出 0 ---
ADV="$TMP_DIR/advisory-only.md"
cat > "$ADV" <<'EOF'
他翻看着那段记录，想起本章之前发生的事，那个伏笔一直没人提起。
EOF
set +e
node "$SCRIPT" --json "$ADV" > "$OUT"
adv_all_status=$?
node "$SCRIPT" --fail-on=blocking "$ADV" >/dev/null 2>&1
adv_blocking_status=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (r.findings.length === 0) throw new Error('expected tier2 advisory finding');
if (!r.findings.every((f) => f.severity === 'advisory')) {
  throw new Error('tier2-only fixture 应全为 advisory: ' + JSON.stringify(r.findings.map((f) => f.severity)));
}
NODE
if [ "$adv_all_status" -ne 1 ]; then
  echo "FAIL: advisory-only 默认 --fail-on=all 应退出 1，实际 $adv_all_status" >&2
  exit 1
fi
if [ "$adv_blocking_status" -ne 0 ]; then
  echo "FAIL: advisory-only --fail-on=blocking 应退出 0，实际 $adv_blocking_status" >&2
  exit 1
fi

# --- tier1 工程词：叙述行 blocking；对话行（写手/编剧题材合法台词）降级 advisory ---
TIER1="$TMP_DIR/tier1-dialogue.md"
cat > "$TIER1" <<'EOF'
“今天的字数目标是六千字。”他盯着屏幕，烟一根接一根。
按照字数目标，他还差六千字没写。
EOF
set +e
node "$SCRIPT" --json "$TIER1" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const meta = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).findings.filter((f) => f.type === 'meta-leak');
const dlg = meta.find((f) => f.line === 1);
const nar = meta.find((f) => f.line === 2);
if (!dlg || dlg.severity !== 'advisory') throw new Error('tier1 在对话行应为 advisory: ' + JSON.stringify(dlg));
if (!nar || nar.severity !== 'blocking') throw new Error('tier1 在叙述行应为 blocking: ' + JSON.stringify(nar));
NODE

# --- tier1 引号范围：只降级实际落在成对引号内的匹配，不因同一行别处有引号而整行降级 ---
TIER1_MIXED="$TMP_DIR/tier1-mixed-quote.md"
TIER1_QUOTED="$TMP_DIR/tier1-pure-quote.md"
cat > "$TIER1_MIXED" <<'EOF'
“别急。”按照字数目标，他还差六千字没写。
“字数目标别改。”他却按照细纲继续写。
EOF
printf '“今天的字数目标是六千字。”他盯着屏幕。\n' > "$TIER1_QUOTED"

set +e
node "$SCRIPT" --json --fail-on=blocking "$TIER1_MIXED" > "$OUT"
tier1_mixed_status=$?
set -e
if [ "$tier1_mixed_status" -ne 1 ]; then
  echo "FAIL: 混合行引号外 tier1 应以 blocking 退出 1，实际 $tier1_mixed_status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi
node - "$OUT" <<'NODE'
const fs = require('fs');
const findings = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).findings.filter((f) => f.type === 'meta-leak');
if (findings.length !== 2 || !findings.every((finding) => finding.severity === 'blocking')) {
  throw new Error('混合行引号外 tier1 必须 blocking: ' + JSON.stringify(findings));
}
if (findings[0].line !== 1 || findings[0].column !== 8 || !findings[0].excerpt.includes('字数目标')) {
  throw new Error('混合行 tier1 的位置/证据错误: ' + JSON.stringify(findings[0]));
}
if (findings[1].line !== 2 || findings[1].column !== 14 || !findings[1].excerpt.includes('细纲')) {
  throw new Error('引号内 tier1 不得抢先遮住引号外 tier1: ' + JSON.stringify(findings[1]));
}
NODE

set +e
node "$SCRIPT" --json --fail-on=blocking "$TIER1_QUOTED" > "$OUT"
tier1_quoted_status=$?
set -e
if [ "$tier1_quoted_status" -ne 0 ]; then
  echo "FAIL: 成对引号内 tier1 仅 advisory，--fail-on=blocking 应退出 0，实际 $tier1_quoted_status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi
node - "$OUT" <<'NODE'
const fs = require('fs');
const findings = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).findings.filter((f) => f.type === 'meta-leak');
if (findings.length !== 1 || findings[0].severity !== 'advisory' || findings[0].column !== 5) {
  throw new Error('成对引号内 tier1 应保留 advisory 与原位置: ' + JSON.stringify(findings));
}
NODE

# --- wiring：携带 check-degeneration.js 副本的 skill 必须在自己的工作流文本里实际调用它 ---
# 调用点可以在 SKILL.md，也可以在该 skill 的 references/ 工作流文件里（长篇的单章流程
# 就随 Phase 4-5 下沉到了 references/workflow-chapter.md）。只要求「在本 skill 内被调用」，
# 不再钉死在 SKILL.md 这一个文件上；一处都没有仍然 FAIL。
for skill_js in $(find "$REPO_ROOT/skills" -name check-degeneration.js); do
  skill_dir="$(dirname "$(dirname "$skill_js")")"
  skill_md="$skill_dir/SKILL.md"
  if [ -f "$skill_md" ] && ! grep -rq 'check-degeneration.js' "$skill_md" "$skill_dir/references" 2>/dev/null; then
    echo "FAIL: $skill_md 携带 check-degeneration.js 副本却未在本 skill 的工作流文本中调用" >&2
    exit 1
  fi
done

echo "Degeneration detector regression tests passed."
