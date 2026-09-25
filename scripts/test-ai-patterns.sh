#!/bin/bash
# test-ai-patterns.sh — regression tests for the deterministic AI-pattern detector.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository" >&2
  exit 1
fi

SCRIPT="$REPO_ROOT/skills/story-deslop/scripts/check-ai-patterns.js"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

FIXTURE="$TMP_DIR/fixture.md"
OUT="$TMP_DIR/out.json"

cat > "$FIXTURE" <<'EOF'
---
title: 不是A，而是B
---
是不是这里不该报。
他不是冷漠，而是绝望。
她不是害怕，是累了。
他不是笨是太急。
他不是冷漠；是绝望。
它不是普通的粥！
是药。
她不是不想走，也不是不敢走。
他不是讨厌你，只是累了。
他不是走了，可是没人发现。
他不是不愿意，于是答应了。
她不是生气，倒是有点担心。
他不是哭就是闹。
这事不是真的就是假的。
这不是你的东西，是吗？
他不是傻子。是吗？
他不是傻子，是吧。
不是这样，是嘛。
他不是第一次来。

是的，他还记得门口那盏灯。
他不是没听见。是啊，他只是没回头。
他不是不想答应，是呢，话到嘴边又咽回去。
```
他不是冷漠，而是绝望。
```
~~~md
他不是普通表达，而是代码示例。
~~~
EOF

set +e
node "$SCRIPT" --json "$FIXTURE" > "$OUT"
status=$?
set -e

if [ "$status" -ne 1 ]; then
  echo "FAIL: expected detector to exit 1 for positive findings, got $status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi

node - "$OUT" <<'NODE'
const fs = require('fs');
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const excerpts = report.findings.map((finding) => finding.excerpt);

// Genuine flips that MUST be detected: 而是 / “，是” / compact / “；是” / hard-stop + 是.
const expected = [
  '不是冷漠，而是绝望',
  '不是害怕，是累了',
  '不是笨是太急',
  '不是冷漠；是绝望',
  '不是普通的粥！ 是药',
];

// Natural prose that MUST NOT be flagged (conjunction 只是/可是/于是/倒是, either-or
// 不是A就是B, tag questions 是吗/是吧/是嘛/是的/是啊/是呢, issue #166) is guarded by the
// exact finding count below: any extra hit breaks it.
if (report.findings.length !== expected.length) {
  throw new Error(`expected ${expected.length} findings, got ${report.findings.length}: ${JSON.stringify(excerpts)}`);
}

for (const excerpt of expected) {
  if (!excerpts.includes(excerpt)) {
    throw new Error(`missing expected excerpt: ${excerpt}; got ${JSON.stringify(excerpts)}`);
  }
}

NODE

echo "AI pattern detector regression tests passed."

# --- 段落级检测：碎句号 / 长段落 / 破折号（issue #188） ---
FIXTURE2="$TMP_DIR/fixture-prose.md"
LONG_PARA="他沿着长廊一直往里走，"
i=0
while [ "$i" -lt 16 ]; do
  LONG_PARA="${LONG_PARA}走过一道又一道紧闭的木门，"
  i=$((i + 1))
done
LONG_PARA="${LONG_PARA}终于在尽头停下，盯着那点暗红看了很久。"
{
  # 6 句连续短叙述句 → 碎句号
  printf '%s\n' '他站起来。' '他走过去。' '门开了。' '风进来。' '他停住。' '心一沉。'
  # 破折号 → em-dash（按功能改写，不机械替换）
  printf '%s\n' '她借着月光看清了桌上那张纸的边角——那是一张旧纸。'
  # 单段超长 → long-paragraph
  printf '%s\n' "$LONG_PARA"
} > "$FIXTURE2"

set +e
node "$SCRIPT" --json "$FIXTURE2" > "$OUT"
status=$?
set -e
if [ "$status" -ne 1 ]; then
  echo "FAIL: expected prose detector to exit 1 for positive findings, got $status" >&2
  cat "$OUT" >&2 || true
  exit 1
fi

node - "$OUT" <<'NODE'
const fs = require('fs');
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const counts = report.findings.reduce((m, f) => ((m[f.type] = (m[f.type] || 0) + 1), m), {});

// Exactly one of each new prose type, nothing else. Quoted short lines not
// counting toward 碎句号 is owned by FIXTURE4 below.
if (report.findings.length !== 3) {
  throw new Error(`expected 3 prose findings, got ${report.findings.length}: ${JSON.stringify(report.findings.map((f) => `${f.type}@${f.line}`))}`);
}
for (const type of ['period-stutter', 'em-dash', 'long-paragraph']) {
  if (counts[type] !== 1) throw new Error(`expected exactly 1 ${type}, got ${counts[type] || 0}`);
}
// 碎句号 must flag the narrative block (line 1).
const stutter = report.findings.find((f) => f.type === 'period-stutter');
if (stutter.line !== 1) {
  throw new Error(`period-stutter should start at the narrative block (line 1), got line ${stutter.line}`);
}
NODE

# --- MEDIUM-1：碎句号混合行（叙述 + 引号内物件）不能被一个引号整行豁免（#188 review） ---
FIXTURE3="$TMP_DIR/fixture-mixed-quote.md"
printf '%s\n' '他站起。他看见“门”。风进来。他回头。灯灭了。心一沉。' > "$FIXTURE3"
set +e
node "$SCRIPT" --json "$FIXTURE3" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const st = r.findings.filter((f) => f.type === 'period-stutter');
if (st.length !== 1) throw new Error('混合引号叙述应命中碎句号: ' + JSON.stringify(r.findings.map((f) => f.type)));
if (st[0].severity !== 'advisory') throw new Error('period-stutter 应为 advisory');
NODE

# 纯对话成片短句仍豁免（体裁手法）。
FIXTURE4="$TMP_DIR/fixture-pure-dialogue.md"
printf '%s\n' '“走。”' '“快。”' '“跑。”' '“停。”' '“看。”' '“听。”' > "$FIXTURE4"
set +e
pure_out="$(node "$SCRIPT" "$FIXTURE4" 2>&1)"
pure_status=$?
set -e
if [ "$pure_status" -ne 0 ]; then
  echo "FAIL: 纯对话成片短句被误判碎句号 (exit $pure_status):" >&2
  echo "$pure_out" >&2
  exit 1
fi

# --- markdown 结构行不算长段落（#188 review 新发现）---
FIXTURE5="$TMP_DIR/fixture-heading.md"
node -e 'process.stdout.write("## " + "长".repeat(230) + "\n")' > "$FIXTURE5"
set +e
head_out="$(node "$SCRIPT" "$FIXTURE5" 2>&1)"
head_status=$?
set -e
if [ "$head_status" -ne 0 ]; then
  echo "FAIL: markdown 标题被误判 long-paragraph (exit $head_status):" >&2
  echo "$head_out" >&2
  exit 1
fi

# --- severity 字段 + --fail-on 语义：仅 advisory（long-paragraph）时默认退出 1，blocking 模式退出 0 ---
FIXTURE6="$TMP_DIR/fixture-advisory.md"
node -e 'process.stdout.write("他沿着长廊一直往里走，" + "走过一道又一道紧闭的木门，".repeat(16) + "终于在尽头停下。\n")' > "$FIXTURE6"
set +e
node "$SCRIPT" --json "$FIXTURE6" > "$OUT"
adv_all=$?
node "$SCRIPT" --fail-on=blocking "$FIXTURE6" >/dev/null 2>&1
adv_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (!r.findings.length) throw new Error('expected long-paragraph finding');
if (!r.findings.every((f) => f.severity === 'advisory')) {
  throw new Error('long-paragraph-only fixture 应全为 advisory: ' + JSON.stringify(r.findings.map((f) => f.severity)));
}
NODE
[ "$adv_all" -eq 1 ] || { echo "FAIL: advisory-only 默认 --fail-on=all 应退出 1，实际 $adv_all" >&2; exit 1; }
[ "$adv_blk" -eq 0 ] || { echo "FAIL: advisory-only --fail-on=blocking 应退出 0，实际 $adv_blk" >&2; exit 1; }

# blocking（em-dash）：severity=blocking，--fail-on=blocking 退出 1。
FIXTURE7="$TMP_DIR/fixture-blocking.md"
printf '%s\n' '她停住——没说话。' > "$FIXTURE7"
set +e
node "$SCRIPT" --json "$FIXTURE7" > "$OUT"
node "$SCRIPT" --fail-on=blocking "$FIXTURE7" >/dev/null 2>&1
blk_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const dash = r.findings.find((f) => f.type === 'em-dash');
if (!dash || dash.severity !== 'blocking') throw new Error('em-dash 应为 blocking: ' + JSON.stringify(dash));
NODE
[ "$blk_blk" -eq 1 ] || { echo "FAIL: em-dash --fail-on=blocking 应退出 1，实际 $blk_blk" >&2; exit 1; }

echo "Prose pattern (碎句号/长段落/破折号) regression tests passed."

# --- issue #205：跨空行的「不是A。/（空行）/是B」揭示句必须命中（旧 skipGap 只吞一个换行会漏）---
FIXTURE8="$TMP_DIR/fixture-cross-para.md"
printf '%s\n' '中年男人消失了。' '' '不是被拖走。' '' '是整个人像被橡皮擦抹掉，全没了。' > "$FIXTURE8"
set +e
node "$SCRIPT" --json "$FIXTURE8" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ni = r.findings.filter((f) => f.type === 'not-is-comparison');
if (ni.length !== 1) throw new Error('跨空行 不是A。/是B 应命中 1 处 not-is: ' + JSON.stringify(r.findings.map((f) => `${f.type}@${f.line}`)));
if (ni[0].line !== 3) throw new Error('not-is 应定位到「不是」所在行 3，实际 ' + ni[0].line);
if (ni[0].severity !== 'blocking') throw new Error('not-is 应为 blocking');
NODE

# 引号内台词「不是A，是B」是口语辩解，不算叙述层 AI 对比句式（与碎句号一致豁免引号内容）。
FIXTURE9="$TMP_DIR/fixture-dialogue-notis.md"
printf '%s\n' '“你们看见了啊，不是我要闹，是物业非法限制人身自由。”' > "$FIXTURE9"
set +e
dlg_out="$(node "$SCRIPT" "$FIXTURE9" 2>&1)"
dlg_status=$?
set -e
if [ "$dlg_status" -ne 0 ]; then
  echo "FAIL: 引号内台词 不是A，是B 被误判 not-is (exit $dlg_status):" >&2
  echo "$dlg_out" >&2
  exit 1
fi

# 引号外叙述的翻转句仍必须命中（豁免只针对引号内，别把整行叙述放过）。
FIXTURE10="$TMP_DIR/fixture-narration-notis.md"
printf '%s\n' '他冷笑一声。这不是巧合，是有人安排的。' > "$FIXTURE10"
set +e
node "$SCRIPT" --json "$FIXTURE10" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ni = r.findings.filter((f) => f.type === 'not-is-comparison');
if (ni.length !== 1) throw new Error('引号外叙述翻转句应命中 1 处 not-is: ' + JSON.stringify(r.findings.map((f) => f.type)));
NODE

# 引号不成对（多段台词只在末段收引号、全半角混用漏收）不得让 not-is 整段静默失效：
# 引号片段按行封顶，未闭合的开引号只吃掉本行剩余部分，后面几行叙述照常参与扫描。
FIXTURE_UNCLOSED_QUOTE="$TMP_DIR/fixture-unclosed-quote-notis.md"
printf '%s\n' \
  '她终于开口：“我不想再提这件事。' \
  '他没接话。' \
  '他不是不明白，是懒得解释。' \
  '她低头，“算了。”' > "$FIXTURE_UNCLOSED_QUOTE"
set +e
node "$SCRIPT" --json "$FIXTURE_UNCLOSED_QUOTE" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ni = r.findings.filter((f) => f.type === 'not-is-comparison');
if (ni.length !== 1) throw new Error('未闭合引号后的叙述翻转句应命中 1 处 not-is: ' + JSON.stringify(r.findings.map((f) => `${f.type}@${f.line}`)));
if (ni[0].line !== 3) throw new Error('not-is 应定位到「不是」所在行 3，实际 ' + ni[0].line);
NODE

echo "issue #205 (跨空行翻转命中 / 引号内台词豁免 / 未闭合引号不吞叙述) regression tests passed."

# --- issue #205：微动作复读（「了下/了一下」式轻量补语高密度=电报体指纹）---
FIXTURE11="$TMP_DIR/fixture-micro-tic.md"
printf '%s\n' \
  '父亲的手停了一下。绳在铁环上松了半圈。' \
  '他把绳拉紧，在秆子上勒了一道印。' \
  '他拍了两下，手背上沾了叶子。' \
  '母亲切了一阵，停了。锅铲刮了一下锅底。' \
  '他把线头绕了一下，又攥了一下石头。' > "$FIXTURE11"
set +e
node "$SCRIPT" --json "$FIXTURE11" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const mt = r.findings.filter((f) => f.type === 'micro-action-tic');
if (mt.length !== 1) throw new Error('高密度「了下/了一下」应报 1 处 micro-action-tic: ' + JSON.stringify(r.findings.map((f) => f.type)));
if (mt[0].severity !== 'advisory') throw new Error('micro-action-tic 应为 advisory');
NODE

# advisory 不触发 --fail-on=blocking（微动作复读是提示，不阻塞收尾流程）。
set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE11" > /dev/null 2>&1
tic_blk=$?
set -e
[ "$tic_blk" -eq 0 ] || { echo "FAIL: micro-action-tic --fail-on=blocking 应退出 0，实际 $tic_blk" >&2; exit 1; }

# 低密度（正常中文里偶尔一个「了一下/了一眼」）不报；引号内台词的「了下/了一下」不计入。
FIXTURE12="$TMP_DIR/fixture-micro-tic-normal.md"
printf '%s\n' \
  '他回到家的时候，父亲正在院子里绑架子车上的绳子，车斗里堆着几捆刚掰下来的玉米秆。' \
  '他说要去北京谈观测站的事，父亲的手停了一下，然后把绳子重新拉紧，没有接话。' \
  '“你等我一下，我去把鸡圈门修完了一下午也就过去了。”父亲蹲在鸡圈边上，头也没抬。' \
  '傍晚收拾行李的时候，他把断渠捡回来的那块石头看了一眼，装进了外套口袋里。' \
  '母亲在厨房里切菜，刀落在案板上的声音比平时快了不少，他站在门口听了一会儿才进去。' > "$FIXTURE12"
set +e
node "$SCRIPT" --json "$FIXTURE12" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const mt = r.findings.filter((f) => f.type === 'micro-action-tic');
if (mt.length !== 0) throw new Error('低密度/引号内「了下/了一下」不应报 micro-action-tic: ' + JSON.stringify(mt));
NODE

# issue #205 三轮：省略「一/两」的短尾巴（了下/了眼/了声）也是电报体反向指纹；
# PR 文档不能推荐一个脚本抓不到、反复复用后又会显得机械的替换模板。
FIXTURE13="$TMP_DIR/fixture-micro-tic-short-tail.md"
printf '%s\n' \
  '他扯了下嘴角，没接那句话。母亲把碗推过去，他看了眼，又挪开。' \
  '院门响了声，父亲停了下，手里的绳子绕了圈，重新压住秆子。' \
  '她扫了眼桌上的信封，笑了声，指尖在信纸边缘顿了下。' \
  '屋里静了会，锅盖颤了下，水汽贴着墙慢慢往上爬。' > "$FIXTURE13"
set +e
node "$SCRIPT" --json "$FIXTURE13" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const mt = r.findings.filter((f) => f.type === 'micro-action-tic');
if (mt.length !== 1) throw new Error('省略量词的「了下/了眼/了声」高密度也应报 micro-action-tic: ' + JSON.stringify(r.findings));
if (!mt[0].excerpt.includes('了下') || !mt[0].excerpt.includes('了眼')) {
  throw new Error('micro-action-tic excerpt 应包含短尾巴样本: ' + JSON.stringify(mt[0]));
}
NODE

echo "micro-action-tic (电报体微动作复读) regression tests passed."

# --- 套式反应细节：部位微动作/语气比喻成片，提示删除测试而非禁身体描写 ---
FIXTURE_STOCK_REACTION="$TMP_DIR/fixture-stock-reaction.md"
printf '%s\n' \
  '指尖在窗台上轻轻叩了一下。' \
  '她望向窗外别处，指尖却在袖口里攥紧了一下。' \
  '徐管事的语气平静得像在念一份货单。' \
  '他扶着栏杆的那只手，指节泛白。' \
  '指尖在窗棂上轻轻叩了一下。' > "$FIXTURE_STOCK_REACTION"
set +e
node "$SCRIPT" --json "$FIXTURE_STOCK_REACTION" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sr = r.findings.filter((f) => f.type === 'stock-reaction-tic');
if (sr.length !== 1) throw new Error('成片身体微动作/语气比喻应报 1 处 stock-reaction-tic: ' + JSON.stringify(r.findings));
if (sr[0].severity !== 'advisory') throw new Error('stock-reaction-tic 应为 advisory');
if (!sr[0].excerpt.includes('指尖在窗台') || !sr[0].excerpt.includes('语气平静得像在念')) {
  throw new Error('stock-reaction-tic excerpt 应返回可定位原句: ' + JSON.stringify(sr[0]));
}
NODE

FIXTURE_STOCK_REACTION_VARIANTS="$TMP_DIR/fixture-stock-reaction-variants.md"
printf '%s\n' \
  '胸口像被什么东西轻轻撞了一下。' \
  '他喉结滚了滚，没接话。' \
  '她的声音也放轻了。' \
  '老人的眼圈一下就红了。' > "$FIXTURE_STOCK_REACTION_VARIANTS"
set +e
node "$SCRIPT" --json "$FIXTURE_STOCK_REACTION_VARIANTS" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sr = r.findings.filter((f) => f.type === 'stock-reaction-tic');
if (sr.length !== 1) throw new Error('胸口碰撞/喉结/声音放轻/眼圈红等同族反应成片也应报 1 处: ' + JSON.stringify(r.findings));
if (!sr[0].excerpt.includes('胸口像被') || !sr[0].excerpt.includes('声音也放轻')) {
  throw new Error('stock-reaction-tic 变体 excerpt 应返回可定位原句: ' + JSON.stringify(sr[0]));
}
NODE

set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE_STOCK_REACTION" > /dev/null 2>&1
stock_reaction_blk=$?
set -e
[ "$stock_reaction_blk" -eq 0 ] || { echo "FAIL: stock-reaction-tic --fail-on=blocking 应退出 0，实际 $stock_reaction_blk" >&2; exit 1; }

FIXTURE_STOCK_REACTION_NORMAL="$TMP_DIR/fixture-stock-reaction-normal.md"
printf '%s\n' \
  '他握扳手的手指发白，钢丝割开虎口，血顺着扳手滴进齿轮；机器仍旧卡着。' \
  '她在引用栏抄下“指节泛白”，随后删掉，改回谈判破裂后的实际结果。' \
  '门外的人催了第二遍，他把缺页的合同递回去，拒绝签字。' > "$FIXTURE_STOCK_REACTION_NORMAL"
set +e
node "$SCRIPT" --json "$FIXTURE_STOCK_REACTION_NORMAL" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sr = r.findings.filter((f) => f.type === 'stock-reaction-tic');
if (sr.length !== 0) throw new Error('低密度且有物理后果的身体细节/引号内引用不应报 stock-reaction-tic: ' + JSON.stringify(sr));
NODE

echo "stock-reaction-tic (套式反应细节) regression tests passed."

# --- issue #205：抽象总结复读（命运/棋局/这一刻终于明白/才刚刚开始）---
# 尾部补 16 行中性叙述：把「才刚刚开始」推出 trailer-ending 的文末 600 字窗口，
# 让本 fixture 保持只验证 advisory 的 abstract-summary-tic。
FIXTURE14="$TMP_DIR/fixture-abstract-summary.md"
printf '%s\n' \
  '从这一刻开始，所有安排都被推到台前。' \
  '命运像早已布好的棋局，把他推向那扇门。' \
  '他生出前所未有的决意。' \
  '属于他的反击，才刚刚开始。' > "$FIXTURE14"
for _ in $(seq 1 16); do
  printf '%s\n' '院子里的灯还亮着，母亲把晒好的被子抱进屋里，他在门口帮着把竹竿收回来，又把水缸的盖子盖好。' >> "$FIXTURE14"
done
set +e
node "$SCRIPT" --json "$FIXTURE14" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ast = r.findings.filter((f) => f.type === 'abstract-summary-tic');
if (ast.length !== 1) throw new Error('高密度抽象总结应报 1 处 abstract-summary-tic: ' + JSON.stringify(r.findings));
if (ast[0].severity !== 'advisory') throw new Error('abstract-summary-tic 应为 advisory');
if (!ast[0].excerpt.includes('从这一刻开始') || !ast[0].excerpt.includes('才刚刚开始')) {
  throw new Error('abstract-summary-tic excerpt 应包含总结腔样本: ' + JSON.stringify(ast[0]));
}
NODE

# advisory 不触发 --fail-on=blocking；低密度题材词与引号内台词/引用不报。
set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE14" > /dev/null 2>&1
ast_blk=$?
set -e
[ "$ast_blk" -eq 0 ] || { echo "FAIL: abstract-summary-tic --fail-on=blocking 应退出 0，实际 $ast_blk" >&2; exit 1; }

FIXTURE15="$TMP_DIR/fixture-abstract-summary-normal.md"
printf '%s\n' \
  '她把旧棋盘从柜子里搬出来，棋子少了两枚，只能用纽扣代替。' \
  '父亲说：“从这一刻开始，你要自己记账。”她点点头，把账本翻到空白页。' \
  '院外的雨停了，屋檐还在滴水，她先把潮掉的纸拿到窗边晾开。' > "$FIXTURE15"
set +e
node "$SCRIPT" --json "$FIXTURE15" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ast = r.findings.filter((f) => f.type === 'abstract-summary-tic');
if (ast.length !== 0) throw new Error('低密度/引号内抽象总结词不应报 abstract-summary-tic: ' + JSON.stringify(ast));
NODE

echo "abstract-summary-tic (抽象总结复读) regression tests passed."


# --- prompt-corpus：监控摄像头式动作清单（番茄高分样本中该分布为 0，作为 advisory 提醒）---
FIXTURE_ACTION_LIST="$TMP_DIR/fixture-action-list.md"
printf '%s\n' \
  '她伸手拿起桌上的杯子，取过旁边的药瓶，拧开瓶盖，倒出两片药，端起水杯，仰头咽下去，放下杯子，推开椅子，转身走到门口。' > "$FIXTURE_ACTION_LIST"
set +e
node "$SCRIPT" --json "$FIXTURE_ACTION_LIST" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const al = r.findings.filter((f) => f.type === 'action-list-tic');
if (al.length !== 1) throw new Error('连续通用动作清单应报 1 处 action-list-tic: ' + JSON.stringify(r.findings));
if (al[0].severity !== 'advisory') throw new Error('action-list-tic 应为 advisory');
if (!al[0].message.includes('监控摄像头式动作清单')) throw new Error('action-list-tic message 应说明动作清单问题: ' + JSON.stringify(al[0]));
NODE

set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE_ACTION_LIST" > /dev/null 2>&1
action_list_blk=$?
set -e
[ "$action_list_blk" -eq 0 ] || { echo "FAIL: action-list-tic --fail-on=blocking 应退出 0，实际 $action_list_blk" >&2; exit 1; }

FIXTURE_ACTION_LIST_NORMAL="$TMP_DIR/fixture-action-list-normal.md"
printf '%s\n' \
  '她把药瓶攥在手里。门外又喊了一遍名字，椅子腿在地砖上拖出刺耳的一声。' \
  '她站起来，又坐回去，半天才把水杯推远。' > "$FIXTURE_ACTION_LIST_NORMAL"
set +e
node "$SCRIPT" --json "$FIXTURE_ACTION_LIST_NORMAL" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const al = r.findings.filter((f) => f.type === 'action-list-tic');
if (al.length !== 0) throw new Error('有心理/环境缓冲的动作段不应报 action-list-tic: ' + JSON.stringify(al));
NODE

echo "action-list-tic (监控摄像头式动作清单) regression tests passed."

# --- issue #205：套词密度过高（高危套词聚集，具体化改写方向）---
FIXTURE16="$TMP_DIR/fixture-cliche-density.md"
printf '%s\n' \
  '夜色静静笼罩着城市，远处霓虹隐约闪烁。' \
  '林澈心中涌起一股说不清的情绪，仿佛某种预兆正在缓缓靠近。' \
  '苏晚眼中闪过一丝复杂的神色，嘴角勾起一抹若有若无的笑意。' \
  '她语气不容置疑，声音里透着不易察觉的冷意。' \
  '林澈深吸一口气，淡淡开口，语气平静无波。' \
  '苏晚指节泛白，目光锐利，沉默在两人之间蔓延。' > "$FIXTURE16"
set +e
node "$SCRIPT" --json "$FIXTURE16" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cd = r.findings.filter((f) => f.type === 'cliche-density-tic');
if (cd.length !== 1) throw new Error('高密度 AI 套词应报 1 处 cliche-density-tic: ' + JSON.stringify(r.findings));
if (cd[0].severity !== 'advisory') throw new Error('cliche-density-tic 应为 advisory');
if (!cd[0].excerpt.includes('仿佛') || !cd[0].excerpt.includes('眼中闪过')) {
  throw new Error('cliche-density-tic excerpt 应包含套词样本: ' + JSON.stringify(cd[0]));
}
NODE

# advisory 不触发 --fail-on=blocking；低密度题材词/引号内引用不报。
set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE16" > /dev/null 2>&1
cliche_blk=$?
set -e
[ "$cliche_blk" -eq 0 ] || { echo "FAIL: cliche-density-tic --fail-on=blocking 应退出 0，实际 $cliche_blk" >&2; exit 1; }

FIXTURE17="$TMP_DIR/fixture-cliche-density-normal.md"
printf '%s\n' \
  '她在旧本子上抄了一句“仿佛某种预兆”，旁边画了个叉，提醒自己别这么写。' \
  '窗外的雨把纸箱泡软了，林澈把最上面的文件抽出来，摊在暖气片旁边。' \
  '苏晚说话声音不大，办公室太空，反而显得每个字都落得很清楚。' > "$FIXTURE17"
set +e
node "$SCRIPT" --json "$FIXTURE17" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cd = r.findings.filter((f) => f.type === 'cliche-density-tic');
if (cd.length !== 0) throw new Error('低密度/引号内套词不应报 cliche-density-tic: ' + JSON.stringify(cd));
NODE

echo "cliche-density-tic (套词密度过高) regression tests passed."

# --- issue #205：比喻密度过高（像字比喻成片复现，回到具体画面）---
FIXTURE_METAPHOR="$TMP_DIR/fixture-metaphor-density.md"
printf '%s\n' \
  '门口的雨还没停。路灯像泡在脏水里的眼珠，光晕晃得人心里发毛。' \
  '保安室的玻璃好像蒙了一层油，谁的脸贴上去都发灰。' \
  '人群挤在台阶下，仿佛一团被水浇透的纸。' \
  '周砚的声音像是老旧电梯里的报站声，卡在喉咙口。' \
  '公告牌上的红字如同钉子，一颗一颗往墙上扎。' \
  '孩子的哭声像从楼缝里漏出来的风，细得让人背后发凉。' \
  '胸牌亮起来，像一块透明的旧手机屏。' > "$FIXTURE_METAPHOR"
set +e
node "$SCRIPT" --json "$FIXTURE_METAPHOR" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const md = r.findings.filter((f) => f.type === 'metaphor-density-tic');
if (md.length !== 1) throw new Error('高密度比喻应报 1 处 metaphor-density-tic: ' + JSON.stringify(r.findings));
if (md[0].severity !== 'advisory') throw new Error('metaphor-density-tic 应为 advisory');
if (!md[0].excerpt.includes('路灯像') || !md[0].excerpt.includes('玻璃好像')) {
  throw new Error('metaphor-density-tic excerpt 应包含比喻样本: ' + JSON.stringify(md[0]));
}
NODE

set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE_METAPHOR" > /dev/null 2>&1
metaphor_blk=$?
set -e
[ "$metaphor_blk" -eq 0 ] || { echo "FAIL: metaphor-density-tic --fail-on=blocking 应退出 0，实际 $metaphor_blk" >&2; exit 1; }

FIXTURE_METAPHOR_NORMAL="$TMP_DIR/fixture-metaphor-density-normal.md"
printf '%s\n' \
  '群头像换成了黑底白字，周砚盯着看了两秒。' \
  '她在本子上写下“像水一样”四个字，又拿红笔划掉。' \
  '雨声从棚顶漏下来，像有人在慢慢倒豆子。' \
  '他把收据塞进口袋，转身去敲 3 单元的门。' > "$FIXTURE_METAPHOR_NORMAL"
set +e
node "$SCRIPT" --json "$FIXTURE_METAPHOR_NORMAL" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const md = r.findings.filter((f) => f.type === 'metaphor-density-tic');
if (md.length !== 0) throw new Error('低密度/引号内/头像不应报 metaphor-density-tic: ' + JSON.stringify(md));
NODE

echo "metaphor-density-tic (比喻密度过高) regression tests passed."

# --- issue #205：解释链密度过高（读感像逻辑报告时的读顺处理提示）---
FIXTURE18="$TMP_DIR/fixture-reasoning-chain.md"
cat > "$FIXTURE18" <<'TEXT'
周砚站在门岗亭前，看着群消息一行行跳出来。他知道眼下最重要的任务是稳住人群，避免恐慌继续扩大。他也明白，如果业主继续围在北门，公共区域秩序会很快失控。这意味着每一句广播都必须谨慎，因为错误指令可能带来新的死亡。

真正的问题在于，他没有完整规则，却必须在规则惩罚之前做出判断。在这种情况下，任何安慰都可能变成误导，任何沉默也可能被理解成默认。他需要先确认谁还在外面，再确认哪些楼栋还能进门。只有这样，他才有可能把混乱压回可控范围。

周砚看着胸牌上的蓝光，心里不断分析当前局面。系统给出的任务是让所有存活业主回家，限制条件是零点之前，风险来源是红线之外和错误指令。按照这个逻辑，他应该先减少移动中的人，再建立单元门口的临时秩序，最后逐个核对门牌。

他清楚自己只是实习物业，但现在系统把责任交给了他。也就是说，他必须承担一个原本不该由他承担的结果。他需要保持冷静，需要筛选信息，需要判断每个人的风险等级。想到这里，他终于意识到，今晚考验的是信息不足时的决策能力，也是他能不能承担公共秩序的开始。
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE18" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rc = r.findings.filter((f) => f.type === 'reasoning-chain-tic');
if (rc.length !== 1) throw new Error('高密度解释链应报 1 处 reasoning-chain-tic: ' + JSON.stringify(r.findings));
if (rc[0].severity !== 'advisory') throw new Error('reasoning-chain-tic 应为 advisory');
if (!rc[0].excerpt.includes('他知道') || !rc[0].excerpt.includes('这意味着')) {
  throw new Error('reasoning-chain-tic excerpt 应包含解释链样本: ' + JSON.stringify(rc[0]));
}
NODE

# advisory 不触发 --fail-on=blocking；动作化改写/引号内引用不报。
set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE18" > /dev/null 2>&1
reason_blk=$?
set -e
[ "$reason_blk" -eq 0 ] || { echo "FAIL: reasoning-chain-tic --fail-on=blocking 应退出 0，实际 $reason_blk" >&2; exit 1; }

FIXTURE19="$TMP_DIR/fixture-reasoning-chain-normal.md"
cat > "$FIXTURE19" <<'TEXT'
周砚站在门岗亭前，群消息还在往上跳。

“周砚你说话！”

“北门到底怎么回事？”

他把广播键按住，又松开。门口还有十几个人没走，抱猫粮的女人蹲在地上，手一直在抖；遛狗的大爷把狗绳缠在腕子上，眼睛盯着红线外那串钥匙。

周砚翻开物业值班表，用指甲在纸上划了三下。北门，三号楼，儿童区。他先把还在外面的名字圈出来，又拿笔把能看见的楼栋写在旁边。

他在本子边上写了一句“这意味着责任”，又立刻划掉，换成三号楼三个门牌号。

“所有人离北门十米。”他说，“三号楼业主先回单元门口，不进电梯。家里有人没回来的，把门牌号发群里，不要刷屏。”
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE19" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rc = r.findings.filter((f) => f.type === 'reasoning-chain-tic');
if (rc.length !== 0) throw new Error('动作化改写/引号内解释链不应报 reasoning-chain-tic: ' + JSON.stringify(rc));
NODE

FIXTURE20="$TMP_DIR/fixture-reasoning-chain-domain-words.md"
cat > "$FIXTURE20" <<'TEXT'
门口的规则牌被风刮歪了，周砚伸手扶正。责任区三个字露在雨水里，下面贴着旧表格，风险提示已经掉了一角。

保安把秩序线往前挪了半米，绳子蹭过地砖，留下两道泥印。周砚拿起笔，在登记本上补了一行责任人，又把规则牌下面的钉子按回去。

三号楼的人还堵在门口。有人指着风险提示骂，有人拽着秩序线不放。周砚没解释，只把扩音器递给老保安，自己弯腰去捡掉在水里的门禁卡。

雨越下越大，纸上的责任栏洇开了，规则两个字糊成一团。秩序线那头，小孩把伞举歪，鞋尖踩进水坑里。
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE20" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rc = r.findings.filter((f) => f.type === 'reasoning-chain-tic');
if (rc.length !== 0) throw new Error('规则/责任/风险等领域名词密集但无推理连接词时不应报 reasoning-chain-tic: ' + JSON.stringify(rc));
NODE

FIXTURE20B="$TMP_DIR/fixture-reasoning-chain-negated.md"
cat > "$FIXTURE20B" <<'TEXT'
周砚不知道规则后面还有什么，也不明白责任到底怎么分。他还不清楚风险来自哪一条线，不需要判断结果，也不需要确认谁承担。

门岗亭里的旧表格被雨水洇开，任务栏、条件栏、责任栏糊在一起。老保安问他要不要广播，他摇头，只把那张纸夹回文件夹里。

他不知道三号楼的人为什么还不走，也不明白秩序线怎么突然松了半截。孩子的伞骨翻起来，鞋尖踩进水坑，门禁卡贴在地砖上。

周砚不清楚这些规则是不是还算数，也不需要分析每个人的风险来源。他把扩音器放回桌上，先去把北门的雨棚往外拽了一点。
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE20B" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rc = r.findings.filter((f) => f.type === 'reasoning-chain-tic');
if (rc.length !== 0) throw new Error('不知道/不明白/不需要等否定认知不应被当作解释链核心命中: ' + JSON.stringify(rc));
NODE

echo "reasoning-chain-tic (解释链密度过高) regression tests passed."

# --- issue #205：系统公告公文腔过密（方括号规则行硬词过密）---
FIXTURE21="$TMP_DIR/fixture-notice-formality.md"
cat > "$FIXTURE21" <<'TEXT'
【夜间不得离开本区域。】

【零点前，所有人员必须返回登记住所。】

【管理人员必须维持公共区域秩序。公共区域失控，管理人员承担优先惩罚。】

【本公告不可撤回，不可转发，不可截图。】

【当前区域：一号楼。】

【当前安全等级：0。】

【当前公共区域秩序：混乱。】

【第一夜任务：务必在零点前，使所有人员返回登记住所。】

【任务失败：管理人员优先承担惩罚。】

【提示：管理人员发言将被视为公共秩序指令。错误指令造成的死亡，同样计入管理人员责任。】
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE21" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const nf = r.findings.filter((f) => f.type === 'system-notice-formality-tic');
if (nf.length !== 1) throw new Error('成片硬规则公告应报 1 处 system-notice-formality-tic: ' + JSON.stringify(r.findings));
if (nf[0].severity !== 'advisory') throw new Error('system-notice-formality-tic 应为 advisory');
if (!nf[0].excerpt.includes('不得') || !nf[0].excerpt.includes('必须')) {
  throw new Error('system-notice-formality-tic excerpt 应包含硬规则词样本: ' + JSON.stringify(nf[0]));
}
NODE

set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE21" > /dev/null 2>&1
notice_blk=$?
set -e
[ "$notice_blk" -eq 0 ] || { echo "FAIL: system-notice-formality-tic --fail-on=blocking 应退出 0，实际 $notice_blk" >&2; exit 1; }

FIXTURE22="$TMP_DIR/fixture-notice-natural.md"
cat > "$FIXTURE22" <<'TEXT'
【夜间不能离开本区域。】

【零点之前，所有人员都要返回登记住所。】

【管理人员要维护好公共区域的秩序。公共区域出现混乱的时候，管理人员要先受到处罚。】

【本公告不能撤回，不能转发，不能截图。】

【现在的区域是一号楼。】

【目前的安全等级为0。】

【目前公共区域的秩序很乱。】

【夜间任务是在零点之前让所有人员返回登记住所。】

【任务失败后，管理人员先承担惩罚。】

【提示：管理人员发出的指令就是公共秩序指令。造成死亡的错误指令也要算在管理人员的责任之内。】
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE22" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const nf = r.findings.filter((f) => f.type === 'system-notice-formality-tic');
if (nf.length !== 0) throw new Error('白话化规则公告不应报 system-notice-formality-tic: ' + JSON.stringify(nf));
NODE

echo "system-notice-formality-tic (系统公告公文腔过密) regression tests passed."

# --- issue #205：长文本过度精炼短段（读顺处理提示；不机械注水）---
FIXTURE23="$TMP_DIR/fixture-overcompressed-prose.md"
: > "$FIXTURE23"
for _ in $(seq 1 60); do
  cat >> "$FIXTURE23" <<'TEXT'
周砚抬头。

TEXT
done
for _ in $(seq 1 40); do
  cat >> "$FIXTURE23" <<'TEXT'
灰雾贴住红线外侧，北门灯光晃成一团冷斑，脚步声压回门岗亭前。

TEXT
done
set +e
node "$SCRIPT" --json "$FIXTURE23" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const oc = r.findings.filter((f) => f.type === 'overcompressed-prose-tic');
if (oc.length !== 1) throw new Error('长文本短段过密且自然连接偏少应报 overcompressed-prose-tic: ' + JSON.stringify(r.findings));
if (oc[0].severity !== 'advisory') throw new Error('overcompressed-prose-tic 应为 advisory');
NODE

set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE23" > /dev/null 2>&1
overcompressed_blk=$?
set -e
[ "$overcompressed_blk" -eq 0 ] || { echo "FAIL: overcompressed-prose-tic --fail-on=blocking 应退出 0，实际 $overcompressed_blk" >&2; exit 1; }

FIXTURE24="$TMP_DIR/fixture-overcompressed-prose-natural.md"
: > "$FIXTURE24"
for _ in $(seq 1 40); do
  cat >> "$FIXTURE24" <<'TEXT'
周砚抬头。

TEXT
done
for _ in $(seq 1 40); do
  cat >> "$FIXTURE24" <<'TEXT'
灰雾还贴在红线外面，北门的灯光已经晃成了一团冷斑，脚步声也被压回了门岗亭前。

TEXT
done
set +e
node "$SCRIPT" --json "$FIXTURE24" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const oc = r.findings.filter((f) => f.type === 'overcompressed-prose-tic');
if (oc.length !== 0) throw new Error('短段占比未过阈值/自然连接足够时不应报 overcompressed-prose-tic: ' + JSON.stringify(oc));
NODE

FIXTURE25="$TMP_DIR/fixture-overcompressed-prose-fast-natural.md"
: > "$FIXTURE25"
for _ in $(seq 1 60); do
  cat >> "$FIXTURE25" <<'TEXT'
他就停了一秒。

TEXT
done
for _ in $(seq 1 40); do
  cat >> "$FIXTURE25" <<'TEXT'
雨还在门口落着，灯光也被水汽糊住了，大家都往后退了一点。

TEXT
done
set +e
node "$SCRIPT" --json "$FIXTURE25" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const oc = r.findings.filter((f) => f.type === 'overcompressed-prose-tic');
if (oc.length !== 0) throw new Error('快节奏但自然连接充足的短段不应报 overcompressed-prose-tic: ' + JSON.stringify(oc));
NODE

FIXTURE26="$TMP_DIR/fixture-overcompressed-prose-repaired-beats.md"
: > "$FIXTURE26"
for _ in $(seq 1 50); do
  cat >> "$FIXTURE26" <<'TEXT'
周砚抬头时，北门外那条马路已经看不见了。更怪的是声音也跟着没了，业主群里刷屏的问号停了三秒。

TEXT
done
set +e
node "$SCRIPT" --json "$FIXTURE26" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const oc = r.findings.filter((f) => f.type === 'overcompressed-prose-tic');
if (oc.length !== 0) throw new Error('读顺后的同一镜头短拍不应报 overcompressed-prose-tic: ' + JSON.stringify(oc));
NODE

echo "overcompressed-prose-tic (过度精炼短段) regression tests passed."

# --- 密度类规则的引号豁免：台词里塞满触发词也不计入。每条用例的引号内文本
# 都复用上面正例的原句，引号若被计入就足以命中对应规则；这里断言一条都不报。---
node - "$SCRIPT" "$TMP_DIR" <<'NODE'
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const [script, tmpDir] = process.argv.slice(2);
const say = (lines) => lines.map((line) => `他说：“${line}”`);
const repeat = (n, line) => Array.from({ length: n }, () => line);
const cases = [
  ['micro-action-tic', say([
    '父亲的手停了一下。绳在铁环上松了半圈。',
    '他把绳拉紧，在秆子上勒了一道印。',
    '他拍了两下，手背上沾了叶子。',
    '母亲切了一阵，停了。锅铲刮了一下锅底。',
    '他把线头绕了一下，又攥了一下石头。',
  ])],
  ['stock-reaction-tic', say([
    '指尖在窗台上轻轻叩了一下。',
    '她望向窗外别处，指尖却在袖口里攥紧了一下。',
    '徐管事的语气平静得像在念一份货单。',
    '他扶着栏杆的那只手，指节泛白。',
    '指尖在窗棂上轻轻叩了一下。',
  ])],
  ['abstract-summary-tic', say([
    '从这一刻开始，所有安排都被推到台前。',
    '命运像早已布好的棋局，把他推向那扇门。',
    '他生出前所未有的决意。',
    '属于他的反击，才刚刚开始。',
  ])],
  ['action-list-tic', say([
    '她伸手拿起桌上的杯子，取过旁边的药瓶，拧开瓶盖，倒出两片药，端起水杯，仰头咽下去，放下杯子，推开椅子，转身走到门口。',
  ])],
  ['cliche-density-tic', say([
    '夜色静静笼罩着城市，远处霓虹隐约闪烁。',
    '林澈心中涌起一股说不清的情绪，仿佛某种预兆正在缓缓靠近。',
    '苏晚眼中闪过一丝复杂的神色，嘴角勾起一抹若有若无的笑意。',
    '她语气不容置疑，声音里透着不易察觉的冷意。',
    '林澈深吸一口气，淡淡开口，语气平静无波。',
    '苏晚指节泛白，目光锐利，沉默在两人之间蔓延。',
  ])],
  ['metaphor-density-tic', say([
    '门口的雨还没停。路灯像泡在脏水里的眼珠，光晕晃得人心里发毛。',
    '保安室的玻璃好像蒙了一层油，谁的脸贴上去都发灰。',
    '人群挤在台阶下，仿佛一团被水浇透的纸。',
    '周砚的声音像是老旧电梯里的报站声，卡在喉咙口。',
    '公告牌上的红字如同钉子，一颗一颗往墙上扎。',
    '孩子的哭声像从楼缝里漏出来的风，细得让人背后发凉。',
    '胸牌亮起来，像一块透明的旧手机屏。',
  ])],
  ['reasoning-chain-tic', say([
    '他知道眼下最重要的任务是稳住人群，避免恐慌继续扩大。他也明白，如果业主继续围在北门，公共区域秩序会很快失控。这意味着每一句广播都必须谨慎，因为错误指令可能带来新的死亡。',
    '真正的问题在于，他没有完整规则，却必须在规则惩罚之前做出判断。在这种情况下，任何安慰都可能变成误导，任何沉默也可能被理解成默认。他需要先确认谁还在外面，再确认哪些楼栋还能进门。只有这样，他才有可能把混乱压回可控范围。',
    '他清楚自己只是实习物业，但现在系统把责任交给了他。也就是说，他必须承担一个原本不该由他承担的结果。他需要保持冷静，需要筛选信息，需要判断每个人的风险等级。想到这里，他终于意识到，今晚考验的是信息不足时的决策能力。',
  ])],
  ['overcompressed-prose-tic', say([
    ...repeat(60, '周砚抬头。'),
    ...repeat(40, '灰雾贴住红线外侧，北门灯光晃成一团冷斑，脚步声压回门岗亭前。'),
  ])],
];
const failures = [];
for (const [type, lines] of cases) {
  const file = path.join(tmpDir, `fixture-quoted-${type}.md`);
  fs.writeFileSync(file, lines.join('\n\n') + '\n');
  const run = spawnSync('node', [script, '--json', file], { encoding: 'utf8' });
  const hits = JSON.parse(run.stdout).findings.filter((f) => f.type === type);
  if (hits.length) failures.push(`${type}: ${JSON.stringify(hits)}`);
}
if (failures.length) throw new Error('引号内触发词不应计入密度规则:\n' + failures.join('\n'));
NODE

echo "density-rule quote exemption regression tests passed."

# --- issue #205：低连接密度 + 缺中长句（R10 保守 advisory，单低连接不够）---
FIXTURE27="$TMP_DIR/fixture-low-connective-density.md"
: > "$FIXTURE27"
for _ in $(seq 1 50); do
  cat >> "$FIXTURE27" <<'TEXT'
周砚抬头。红点跳高。北门灯冷。手机黑屏。脚步停住。

TEXT
done
set +e
node "$SCRIPT" --json "$FIXTURE27" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const lc = r.findings.filter((f) => f.type === 'low-connective-density-tic');
if (lc.length !== 1) throw new Error('低连接密度且缺中长句应报 1 处 low-connective-density-tic: ' + JSON.stringify(r.findings));
if (lc[0].severity !== 'advisory') throw new Error('low-connective-density-tic 应为 advisory');
if (!lc[0].message.includes('别机械注水')) throw new Error('low-connective-density-tic 必须提示禁止机械注水: ' + JSON.stringify(lc[0]));
NODE

set +e
node "$SCRIPT" --fail-on=blocking "$FIXTURE27" > /dev/null 2>&1
low_connective_blk=$?
set -e
[ "$low_connective_blk" -eq 0 ] || { echo "FAIL: low-connective-density-tic --fail-on=blocking 应退出 0，实际 $low_connective_blk" >&2; exit 1; }

# 引号内台词/弹幕/系统播报天然短促，不参与低连接密度统计；否则会把体裁特征误当电报体。
FIXTURE27B="$TMP_DIR/fixture-low-connective-quoted-stream.md"
: > "$FIXTURE27B"
for _ in $(seq 1 80); do
  cat >> "$FIXTURE27B" <<'TEXT'
“红点跳高。北门灯冷。手机黑屏。脚步停住。”

TEXT
done
cat >> "$FIXTURE27B" <<'TEXT'
周砚把群消息往上翻。门岗亭里只剩下空调声，他没有马上开口。
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE27B" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const lc = r.findings.filter((f) => f.type === 'low-connective-density-tic');
if (lc.length !== 0) throw new Error('引号内短促台词/弹幕流不应触发 low-connective-density-tic: ' + JSON.stringify(lc));
NODE

# 所有配置过的中英文引号都应从“引号外叙述”统计中剥离；引号内含 regex 元字符也不能影响剥离。
FIXTURE27C="$TMP_DIR/fixture-low-connective-all-quote-pairs.md"
: > "$FIXTURE27C"
for _ in $(seq 1 35); do
  cat >> "$FIXTURE27C" <<'TEXT'
「红点[跳高]*。北门灯冷+。手机黑屏?。」『红点[跳高]*。北门灯冷+。手机黑屏?。』【红点[跳高]*。北门灯冷+。手机黑屏?。】“红点[跳高]*。北门灯冷+。手机黑屏?。”‘红点[跳高]*。北门灯冷+。手机黑屏?。’"红点[跳高]*。北门灯冷+。手机黑屏?。"'红点[跳高]*。北门灯冷+。手机黑屏?。'

TEXT
done
cat >> "$FIXTURE27C" <<'TEXT'
周砚把群消息往上翻。门岗亭里只剩下空调声，他没有马上开口。
TEXT
set +e
node "$SCRIPT" --json "$FIXTURE27C" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const lc = r.findings.filter((f) => f.type === 'low-connective-density-tic');
if (lc.length !== 0) throw new Error('全部引号对都应剥离，不应触发 low-connective-density-tic: ' + JSON.stringify(lc));
NODE

# 单纯功能词/白话连接偏低，但中长承接句充足时不报；这是《盘龙》人工窗口误报反例的保护条件。
FIXTURE28="$TMP_DIR/fixture-low-connective-long-sentences.md"
: > "$FIXTURE28"
for _ in $(seq 1 30); do
  cat >> "$FIXTURE28" <<'TEXT'
周砚把红点截图发回群里，北门冷灯贴着灰雾晃成一片，脚步声压在门岗亭前不动。

TEXT
done
set +e
node "$SCRIPT" --json "$FIXTURE28" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const lc = r.findings.filter((f) => f.type === 'low-connective-density-tic');
if (lc.length !== 0) throw new Error('低连接但中长句充足时不应报 low-connective-density-tic: ' + JSON.stringify(lc));
NODE

echo "low-connective-density-tic (低连接密度 + 缺中长句) regression tests passed."

# ============================================================
# 实战测试漏网句式（A-E）：音量反差腔 / 否定排比 / 反序对比 / 预告式收尾 / 引号强调滥用
# 正例取自实战写作抓到的真实漏网句；反例含对话豁免、either-or、正常引用与真人语料边界句。
# ============================================================

# --- 实战漏网 A：voice-contrast（声音不高…却…，blocking）---
FIXTURE_VOICE="$TMP_DIR/fixture-voice-contrast.md"
printf '%s\n' \
  '声音不高，第一句却稳稳压住了整个大厅。' \
  '“他声音不大，却带着火气。”旁边的人小声嘀咕。' \
  '她的声音不大，台下前排听得清楚。' > "$FIXTURE_VOICE"
set +e
node "$SCRIPT" --json "$FIXTURE_VOICE" > "$OUT"
node "$SCRIPT" --fail-on=blocking "$FIXTURE_VOICE" >/dev/null 2>&1
voice_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const vc = r.findings.filter((f) => f.type === 'voice-contrast');
if (vc.length !== 1) throw new Error('音量反差腔应命中 1 处 voice-contrast: ' + JSON.stringify(r.findings.map((f) => `${f.type}@${f.line}`)));
if (vc[0].line !== 1 || vc[0].severity !== 'blocking') throw new Error('voice-contrast 应为 line 1 blocking: ' + JSON.stringify(vc[0]));
// 引号内台词（line 2）与无转折的平铺（line 3）不算音量反差腔。
if (vc[0].excerpt.includes('火气')) throw new Error('引号内台词不应命中 voice-contrast: ' + JSON.stringify(vc[0]));
NODE
[ "$voice_blk" -eq 1 ] || { echo "FAIL: voice-contrast --fail-on=blocking 应退出 1，实际 $voice_blk" >&2; exit 1; }

echo "voice-contrast (音量反差腔) regression tests passed."

# --- 实战漏网 B：negation-parade（没有X，没有Y…／没X…只是Y，blocking）---
FIXTURE_PARADE="$TMP_DIR/fixture-negation-parade.md"
printf '%s\n' \
  '没有伴奏，没有和声，没有提词器。' \
  '他没炫技，没有那种一张嘴就飙高音的架势。他只是唱，把每个字放平。' \
  '“没有饭，没有水，我们怎么过夜？”有人喊。' \
  '他没有回头。巷子里没有灯，他摸着墙走。' \
  '船沉没在雾里，没人回头，江面上就只有几块浮木。' \
  '他的话被淹没在掌声里，没多久，台上就只有他一个人。' \
  '雨下了没多久，没等她撑伞，巷子里就只有水声。' \
  '他没等她开口，没等她反应，只是转身走了。' > "$FIXTURE_PARADE"
set +e
node "$SCRIPT" --json "$FIXTURE_PARADE" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const np = r.findings.filter((f) => f.type === 'negation-parade');
if (np.length !== 3) throw new Error('否定排比应命中 3 处 negation-parade: ' + JSON.stringify(r.findings.map((f) => `${f.type}@${f.line}`)));
if (np[0].line !== 1 || np[1].line !== 2 || np[2].line !== 8) throw new Error('negation-parade 应命中 line 1/2 与重复「没等」的 line 8: ' + JSON.stringify(np));
if (!np.every((f) => f.severity === 'blocking')) throw new Error('negation-parade 应为 blocking');
// 引号内台词（line 3）与分句独立否定（line 4）不算排比；
// 黏着语素「沉没/淹没」（line 5/6）与单个时间惯用语「没多久」（line 6/7）不算；
// 但重复「没等 A，没等 B，只是 C」本身就是目标排比，不能被时间短语豁免吞掉。
NODE

echo "negation-parade (否定排比) regression tests passed."

# --- 第21章实战漏网：跨段否定三连 + 工整决策/否定并列 ---
# 这三类都能找到正常语境，只报 advisory 交语义审查；轻量 hook 不硬拦。
FIXTURE_CH21_GAP="$TMP_DIR/fixture-ch21-ai-flavor-gap.md"
printf '%s\n' \
  '至于拍不拍，怎么拍，等他把话说完再决定。' \
  '不带摄像机，不带采访灯。' \
  '“不带摄像机，不带采访灯。”' \
  '不是嚎啕大哭。' \
  '' \
  '也不是扯着嗓子喊不舍。' \
  '' \
  '只是一个人走远了，留在原地的人还站着。' \
  '不是生就是死。' \
  '至于拍摄方案怎么定，等人到了再说。' \
  '“不放辣，不放葱。”' \
  '他不带伞。她不带包。' \
  '不是她不想回家。' \
  '也不是母亲不肯原谅她。' \
  '只是末班车已经开走了。' > "$FIXTURE_CH21_GAP"
set +e
node "$SCRIPT" --json "$FIXTURE_CH21_GAP" > "$OUT"
node "$SCRIPT" --fail-on=blocking "$FIXTURE_CH21_GAP" >/dev/null 2>&1
ch21_gap_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const np = r.findings.filter((f) => f.type === 'negation-parade');
if (np.length !== 0) throw new Error('跨段否定三连不应进入 blocking negation-parade: ' + JSON.stringify(np));
const fp = r.findings.filter((f) => f.type === 'formulaic-parallelism');
if (fp.length !== 5) throw new Error('决策框架 + 否定并列 + 两处跨段三连应命中 5 处 advisory: ' + JSON.stringify(r.findings));
if (fp.some((f) => f.severity !== 'advisory')) throw new Error('formulaic-parallelism 只能 advisory: ' + JSON.stringify(fp));
if (fp.map((f) => f.line).join(',') !== '1,2,3,4,13') throw new Error('formulaic-parallelism 应定位 line 1/2/3/4/13: ' + JSON.stringify(fp));
// either-or、普通决策句、对象只有一个字的功能性短对话、跨句独立否定都不报。
// line 13 的正常辩解会被保守提示，但绝不得升成 blocking。
if (r.findings.some((f) => f.line >= 9 && f.line <= 12)) throw new Error('第9-12行自然反例被误报: ' + JSON.stringify(r.findings));
NODE
[ "$ch21_gap_blk" -eq 0 ] || { echo "FAIL: 语义型工整并列不应触发 --fail-on=blocking，实际 $ch21_gap_blk" >&2; exit 1; }

echo "chapter-21 AI-flavor gap regression tests passed."

# --- 实战漏网 C：reverse-not-is（是A，不是B — not-is 反序变种，blocking）---
FIXTURE_REVNOTIS="$TMP_DIR/fixture-reverse-not-is.md"
printf '%s\n' \
  '气息拉满不断，是真嗓子，不是修音修出来的。' \
  '“是我先来的，不是他。”她把票拍在窗口上。' \
  '反正就是这样，不是谁都能改的。' \
  '他也是这两年才学会的，不是天生就懂。' \
  '是啊，不是谁都有这个耐心。' \
  '他问是不是弄错了，不是他报的名。' \
  '他是走了，不是吗？' > "$FIXTURE_REVNOTIS"
set +e
node "$SCRIPT" --json "$FIXTURE_REVNOTIS" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const rn = r.findings.filter((f) => f.type === 'reverse-not-is');
if (rn.length !== 1) throw new Error('反序对比腔应命中 1 处 reverse-not-is: ' + JSON.stringify(r.findings.map((f) => `${f.type}@${f.line}`)));
if (rn[0].line !== 1 || rn[0].severity !== 'blocking') throw new Error('reverse-not-is 应为 line 1 blocking: ' + JSON.stringify(rn[0]));
if (!rn[0].excerpt.includes('是真嗓子')) throw new Error('reverse-not-is excerpt 应含正例片段: ' + JSON.stringify(rn[0]));
// 反例必须全部保持沉默：引号内辩解（2）、就是/也是合成词（3/4）、是啊确认语（5）、
// 是不是问句（6）、不是吗反问尾巴（7）。
NODE

echo "reverse-not-is (反序对比腔) regression tests passed."

# --- 实战漏网 D：trailer-ending（预告式总结收尾，仅文末 600 字窗口，blocking）---
# 反例：窗口外叙述里的「没人知道」（line 1）、窗口内对话里的「没人知道」、
# 真人语料报幕句「比赛正式拉开序幕」（《万疆》第120章原句式）。
FIXTURE_TRAILER="$TMP_DIR/fixture-trailer-ending.md"
printf '%s\n' '他把口琴收进兜里。没人知道他练了多久。' > "$FIXTURE_TRAILER"
for _ in $(seq 1 16); do
  printf '%s\n' '院子里的灯还亮着，母亲把晒好的被子抱进屋里，他在门口帮着把竹竿收回来，又把水缸的盖子盖好。' >> "$FIXTURE_TRAILER"
done
printf '%s\n' \
  '“没人知道下一场在哪儿。”老赵嘟囔着收拾谱架。' \
  '钟声再度响起，比赛正式拉开序幕。' \
  '没人知道，这才刚刚开头。' \
  '一场从县城炸向省台的接力，正朝着他，缓缓压了过去。' >> "$FIXTURE_TRAILER"
set +e
node "$SCRIPT" --json "$FIXTURE_TRAILER" > "$OUT"
node "$SCRIPT" --fail-on=blocking "$FIXTURE_TRAILER" >/dev/null 2>&1
trailer_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const te = r.findings.filter((f) => f.type === 'trailer-ending');
if (te.length !== 3) throw new Error('章尾预告腔应命中 3 处 trailer-ending: ' + JSON.stringify(r.findings.map((f) => `${f.type}@${f.line}:${f.excerpt}`)));
if (!te.every((f) => f.severity === 'blocking')) throw new Error('trailer-ending 应为 blocking');
if (te.some((f) => f.line === 1)) throw new Error('窗口外（文首）的「没人知道」不应命中 trailer-ending');
if (te.some((f) => f.excerpt.includes('下一场'))) throw new Error('对话里的「没人知道」不应命中 trailer-ending');
if (te.some((f) => f.excerpt.includes('拉开序幕'))) throw new Error('真人报幕句「正式拉开序幕」不应命中 trailer-ending');
const excerpts = te.map((f) => f.excerpt).join(' | ');
for (const marker of ['没人知道', '这才刚刚开头', '压了过去']) {
  if (!excerpts.includes(marker)) throw new Error(`trailer-ending 缺少正例命中 ${marker}: ${excerpts}`);
}
NODE
[ "$trailer_blk" -eq 1 ] || { echo "FAIL: trailer-ending --fail-on=blocking 应退出 1，实际 $trailer_blk" >&2; exit 1; }

echo "trailer-ending (预告式总结收尾) regression tests passed."

# --- 实战漏网 E：quote-emphasis-tic（叙述里短词加引号强调，advisory 密度型）---
FIXTURE_QUOTE_EMPH="$TMP_DIR/fixture-quote-emphasis.md"
printf '%s\n' \
  '他是被请来“把关”的，来之前心里还揣着句现成的话。' \
  '这段“掉马神演”，正被一帧一帧拍下、剪好、甩上网。' \
  '没人出声，几千人像被那朵“花”钉在了座位上。' \
  '她说“好”，转身就走。' \
  '“嗯。”' \
  '“叮咚~”“叮咚~”“叮咚~”' \
  '他念了一遍“静”，又写下“定”。' > "$FIXTURE_QUOTE_EMPH"
set +e
node "$SCRIPT" --json "$FIXTURE_QUOTE_EMPH" > "$OUT"
node "$SCRIPT" --fail-on=blocking "$FIXTURE_QUOTE_EMPH" >/dev/null 2>&1
quote_emph_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const qe = r.findings.filter((f) => f.type === 'quote-emphasis-tic');
if (qe.length !== 1) throw new Error('叙述层引号强调 ≥3 处应报 1 条 quote-emphasis-tic: ' + JSON.stringify(r.findings.map((f) => f.type)));
if (qe[0].severity !== 'advisory') throw new Error('quote-emphasis-tic 应为 advisory');
if (!qe[0].message.includes('3 处')) throw new Error('引语动词邻接/独立台词/拟声词连发不应计数，应恰为 3 处: ' + JSON.stringify(qe[0]));
if (!qe[0].excerpt.includes('把关')) throw new Error('quote-emphasis-tic excerpt 应含「把关」正例: ' + JSON.stringify(qe[0]));
NODE
[ "$quote_emph_blk" -eq 0 ] || { echo "FAIL: quote-emphasis-tic --fail-on=blocking 应退出 0，实际 $quote_emph_blk" >&2; exit 1; }

# 低于阈值（<3 处）不报：单处强调是正常修辞；含真人语料边界句（《万疆》第40章海报标语）。
FIXTURE_QUOTE_EMPH_NORMAL="$TMP_DIR/fixture-quote-emphasis-normal.md"
printf '%s\n' \
  '凌晨十二点十分，番城旅游官网出现苏阳的照片，手里的海报变成了“我在番城”。' \
  '他是被请来“把关”的，来之前心里还揣着句现成的话。' > "$FIXTURE_QUOTE_EMPH_NORMAL"
set +e
node "$SCRIPT" --json "$FIXTURE_QUOTE_EMPH_NORMAL" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const qe = r.findings.filter((f) => f.type === 'quote-emphasis-tic');
if (qe.length !== 0) throw new Error('低于 3 处的引号强调不应报 quote-emphasis-tic: ' + JSON.stringify(qe));
NODE

echo "quote-emphasis-tic (引号强调滥用) regression tests passed."

# --- issue #255：章尾状态总结体（trailer-summary）------------------------------
# 细纲「结尾设定/收束状态」被原样写成总结句收章。与 trailer-ending 共用文末 600 字窗口。
FIXTURE_TRAILER_SUMMARY="$TMP_DIR/fixture-trailer-summary.md"
printf '%s\n' \
  '她把账单摊在桌上，指腹压出一道白痕，纸边被汗浸软了一角。' \
  '他端起杯子又放下，杯底磕在桌面上响了一声。' \
  '这一切都结束了。这一夜注定无眠。' > "$FIXTURE_TRAILER_SUMMARY"
set +e
node "$SCRIPT" --json "$FIXTURE_TRAILER_SUMMARY" > "$OUT"
node "$SCRIPT" --fail-on=blocking "$FIXTURE_TRAILER_SUMMARY" >/dev/null 2>&1
trailer_sum_blk=$?
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ts = r.findings.filter((f) => f.type === 'trailer-summary');
if (ts.length !== 2) throw new Error('章尾「这一切都结束了」+「这一夜注定」应各报一条: ' + JSON.stringify(ts));
if (ts.some((f) => f.severity !== 'blocking')) throw new Error('trailer-summary 应为 blocking: ' + JSON.stringify(ts));
NODE
[ "$trailer_sum_blk" -eq 1 ] || { echo "FAIL: trailer-summary --fail-on=blocking 应退出 1，实际 $trailer_sum_blk" >&2; exit 1; }

# 负例：语料实测出的六类结构性误报形状，逐条钉死——时间跳转（就这样，时间过去了）、
# 及物用法（才结束了这个话题）、场内报幕（宣布…圆满落幕）、条件从句（等这一切结束了，…）、
# 动补（说明得非常清楚）、嵌套从句（认为这一切都结束了的时候）、成语跨匹配（命中注定）、
# 系表（结果是注定的），以及「(这|那)一刻…终于明白」与裸认知句——后两者是短篇第一人称
# 审判金句的形状（short-craft「审判金句 / 心死余韵」是卖点），本规则一律不收。
FIXTURE_TRAILER_SUMMARY_NORMAL="$TMP_DIR/fixture-trailer-summary-normal.md"
printf '%s\n' \
  '就这样，一年的时间过去了，账本从抽屉挪进了保险柜。' \
  '就这样，主仆二人都自责了一番，才结束了这个话题。' \
  '就这样，四点多钟，季政委宣布这次相亲联谊会圆满落幕。' \
  '等这一切结束了，我们就能过上平静幸福的生活了。' \
  '尽管兽绝神木似乎将这一切都说明得非常清楚，但结果与所想并不一样。' \
  '就在他认为这一切都结束了的时候，门又被推开了。' \
  '世间的这一刻，所有人都接受了命中注定的结局！' \
  '加上装备的碾压，这一战的结果是注定的。' \
  '他捏着那张纸，不知道这一切意味着什么。' \
  '她盯着屏幕，不明白这一切都说明了什么。' \
  '那一刻我终于明白，母亲当年为什么总在夜里哭。' \
  '我猛地抬头，死死盯着手机，终于明白，为何女儿这半年总躲着我。' \
  '我抓起外套就往门口走，反手带上了那扇门。' > "$FIXTURE_TRAILER_SUMMARY_NORMAL"
set +e
node "$SCRIPT" --json "$FIXTURE_TRAILER_SUMMARY_NORMAL" > "$OUT"
set -e
node - "$OUT" <<'NODE'
const fs = require('fs');
const r = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ts = r.findings.filter((f) => f.type === 'trailer-summary');
if (ts.length !== 0) throw new Error('裸认知句/时间跳转不应报 trailer-summary: ' + JSON.stringify(ts));
NODE

echo "trailer-summary (章尾状态总结体) regression tests passed."
