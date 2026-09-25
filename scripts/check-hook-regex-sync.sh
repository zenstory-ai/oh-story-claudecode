#!/bin/bash
# check-hook-regex-sync.sh — 行为级校验 detect-story-gaps.sh 的伏笔状态检测
#
# 设计意图：SessionStart hook 只提示过期或异常伏笔，避免把长篇中正常
# 当前合法状态（已埋/已回收/放弃）误判为问题，诱发 daily 流程中的全量伏笔审计。
# 本脚本运行真实 hook fixture，验证正常状态不报警、已过期/异常状态报警。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOOK_FILE="$REPO_ROOT/skills/story-setup/references/templates/hooks/detect-story-gaps.sh"
COMMON_FILE="$REPO_ROOT/skills/story-setup/references/templates/hooks/lib/common.sh"
PROTOCOL_FILE="$REPO_ROOT/skills/story-long-write/scripts/tracking_commit.py"

for file in "$HOOK_FILE" "$COMMON_FILE" "$PROTOCOL_FILE"; do
  if [ ! -f "$file" ]; then
    echo "FAIL: required file not found: $file"
    exit 1
  fi
done

STATUS_ENUM=$(sed -n 's/^FORESHADOW_STATUSES = (\(.*\))$/\1/p' "$PROTOCOL_FILE" 2>/dev/null | head -1 | tr -d '" ' | tr ',' '/' || true)
if [ -z "$STATUS_ENUM" ]; then
  echo "FAIL: No foreshadow status enum found in protocol file"
  exit 1
fi

echo "Protocol defines status values: $STATUS_ENUM"

TMP_DIR=$(mktemp -d)
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

setup_fixture() {
  local name="$1"
  local foreshadow_body="$2"
  local root="$TMP_DIR/$name"
  mkdir -p "$root/.claude/hooks/lib" "$root/book/追踪" "$root/book/正文" "$root/book/设定" "$root/book/大纲"
  cp "$HOOK_FILE" "$root/.claude/hooks/detect-story-gaps.sh"
  cp "$COMMON_FILE" "$root/.claude/hooks/lib/common.sh"
  chmod +x "$root/.claude/hooks/detect-story-gaps.sh"
  touch "$root/.story-deployed"
  cat > "$root/book/追踪/上下文.md" <<'CTX'
# 写作进度
## 当前位置
- 章: 第1章
CTX
  # 表头状态枚举从 $STATUS_ENUM 展开，不再另抄一份：协议加状态时 fixture 也跟着变，
  # 否则新状态永远不会被行为级 fixture 走到（表头行本身由 hook 的 ^状态\{ 分支跳过）。
  cat > "$root/book/追踪/伏笔.md" <<EOF_FORESHADOW
# 伏笔追踪

## 伏笔状态表

| ID | 伏笔内容 | 埋设章节 | 预计回收章节 | 状态{$STATUS_ENUM} | 重要度{高/中/低} |
|----|---------|---------|-------------|-----------------------------|----------------|
$foreshadow_body
EOF_FORESHADOW
  printf '%s' "$root"
}

run_hook() {
  local root="$1"
  (cd "$root" && bash .claude/hooks/detect-story-gaps.sh)
}

assert_no_foreshadow_warn() {
  local case_name="$1"
  local body="$2"
  local root output
  root=$(setup_fixture "$case_name" "$body")
  output=$(run_hook "$root" || true)
  if echo "$output" | grep -q '伏笔'; then
    echo "FAIL: $case_name should not emit foreshadow warning"
    echo "Output:"
    echo "$output"
    exit 1
  fi
  echo "  OK no warn: $case_name"
}

assert_foreshadow_warn() {
  local case_name="$1"
  local body="$2"
  local root output
  root=$(setup_fixture "$case_name" "$body")
  output=$(run_hook "$root" || true)
  if ! echo "$output" | grep -q '检测到过期或异常的伏笔条目'; then
    echo "FAIL: $case_name should emit overdue/abnormal foreshadow warning"
    echo "Output:"
    echo "$output"
    exit 1
  fi
  echo "  OK warn: $case_name"
}

assert_no_foreshadow_warn "header-only" ""

plain_header_root="$TMP_DIR/plain-header"
mkdir -p "$plain_header_root/.claude/hooks/lib" "$plain_header_root/book/追踪" "$plain_header_root/book/正文" "$plain_header_root/book/设定" "$plain_header_root/book/大纲"
cp "$HOOK_FILE" "$plain_header_root/.claude/hooks/detect-story-gaps.sh"
cp "$COMMON_FILE" "$plain_header_root/.claude/hooks/lib/common.sh"
chmod +x "$plain_header_root/.claude/hooks/detect-story-gaps.sh"
cat > "$plain_header_root/book/追踪/伏笔.md" <<'EOF_PLAIN_HEADER'
# 伏笔追踪

| ID | 名称 | 埋下 | 回收 | 状态 | 备注 |
|----|------|------|------|------|------|
| F001 | 玉佩 | 第1章 | 第20章 | 已埋 | ok |
EOF_PLAIN_HEADER
plain_header_output=$(run_hook "$plain_header_root" || true)
if echo "$plain_header_output" | grep -q '伏笔'; then
  echo "FAIL: plain-header should not emit foreshadow warning"
  echo "Output:"
  echo "$plain_header_output"
  exit 1
fi
echo "  OK no warn: plain-header"

assert_no_foreshadow_warn "normal-open-planted" "| F002 | 正常开放伏笔 | 第1章 | 第20章 | 已埋 | 高 |"
assert_no_foreshadow_warn "closed-recovered" "| F003 | 已回收伏笔 | 第1章 | 第3章 | 已回收 | 低 |"
assert_no_foreshadow_warn "closed-abandoned" "| F006 | 已放弃伏笔 | 第1章 | 第3章 | 放弃 | 低 |"
assert_foreshadow_warn "overdue" "| F004 | 过期伏笔 | 第1章 | 第2章 | 已过期 | 高 |"
assert_foreshadow_warn "retired-unplanted-status" "| F001 | 尚未真正埋设 | 第5章 | 第10章 | 未埋 | 中 |"
assert_foreshadow_warn "unknown-status" "| F005 | 异常状态 | 第1章 | 第2章 | 状态损坏 | 高 |"

# Guard against reverting to the old broad regex or warning wording.
if grep -q "状态\.\*(未埋|已埋|已过期)" "$HOOK_FILE"; then
  echo "FAIL: old broad foreshadow regex is still present in hook"
  exit 1
fi
if grep -q 'Open foreshadowing[[:space:]]threads' "$HOOK_FILE"; then
  echo "FAIL: old open-foreshadow warning wording is still present in hook"
  exit 1
fi

# Ensure every protocol status is explicitly classified by the hook's awk classifier:
# either an explicit warn state (status == "X") or an explicit normal state (status != "X").
# The old second clause grepped PROTOCOL_FILE — the very file STATUS_ENUM was extracted
# from — so it always matched and the whole loop could never fail. A status added to the
# protocol without teaching the hook falls into the classifier's else branch and gets
# reported as 异常 on every SessionStart; that drift must turn this check red.
for state in $(echo "$STATUS_ENUM" | tr '/' ' '); do
  if ! grep -qF "status == \"$state\"" "$HOOK_FILE" \
    && ! grep -qF "status != \"$state\"" "$HOOK_FILE"; then
    echo "FAIL: protocol status not classified by hook: $state"
    echo "  add status == \"$state\" (warn) or status != \"$state\" (normal) to the 伏笔 awk in $HOOK_FILE"
    exit 1
  fi
done

echo ""
echo "OK: hook foreshadow detection warns only on overdue/abnormal states"

# ── 毒句式 js↔py 同步锁 ─────────────────────────────────────────────────────
# 写后正文网的确定性毒句式规则在两处各有一份同构实现：JS 共享核 story_hook_core.js
# （Claude/OpenCode/ZCode 三副本字节一致由 check-shared-files.sh 保证）与 codex
# story_codex_hook.py（Stop 回合末复扫）。每条正则/常量/文案的规范文本必须在两份里
# 逐字出现，改一处漏改另一处即 fail——与 test-prose-net-parity.sh 的 fixture 级
# 功能 parity 互补（这里锁源文本，那里锁行为输出）。
JS_CORE="$REPO_ROOT/skills/story-setup/references/templates/hooks/story_hook_core.js"
PY_HOOK="$REPO_ROOT/skills/story-setup/references/codex/hooks/story_codex_hook.py"
for file in "$JS_CORE" "$PY_HOOK"; do
  if [ ! -f "$file" ]; then
    echo "FAIL: required file not found: $file"
    exit 1
  fi
done

TOXIC_SYNC=(
  # 正则（js 字面量与 py raw string 的公共文本）
  '声音(?:并)?不[大高响亮][^。！？!?\n]{0,16}[却但偏]'
  '(?:没有[^。！？!?\n，,]{1,12}[，,]){2}'
  '是[^。！？!?\n，,]{1,12}[，,]\s*(?:而)?不是[^。！？!?\n]{1,20}'
  '不是[^。！？!?\n]{1,16}[，,]\s*(?:而)?是'
  '没人知道|谁也不知道|谁也没想到|殊不知|(?:这)?才刚刚开(?:始|头)|正(?:朝着|向着)[^。！？!?\n]{0,24}(?:压|涌|袭|逼)(?:了?过去|了?过来|来)|(?<!正式)拉开(?:序幕|帷幕)|即将(?:开始|来临|降临)'
  '这一(?:夜|天|刻|战|年|局|役)[，,]?[^。！？!?，,\n]{0,6}(?<!命中)(?<!是)注定[^。！？!?\n]{0,8}[。！]'
  '就这样[，,][^。！？!?，,\n]{0,8}(?:一切|全部)[^。！？!?，,\n]{0,4}(?:结束了|落幕|收场)[。！]'
  '这一切[，,]?[^。！？!?，,\n]{0,6}(?:都)?(?:说明|意味着|结束了)(?!的)(?:(?!什么)[^。！？!?\n]){0,6}[。！]'
  '(?:新的篇章|新的旅程|崭新的篇章|新的人生)[^。！？!?\n]{0,6}(?:开始|拉开|展开)|命运[^。！？!?\n]{0,6}齿轮'
  '.*[，,]\s*(?:而)?不是([^。！？!?\n]*)$'
  # 常量（文末窗口、分句边界、疑问尾/确认语排除集）
  'TOXIC_TRAILER_WINDOW = 600'
  '，,。.！!？?；;：:、…—~ \t　'
  '"吗", "吧", "嘛"'
  '"的", "啊", "呀", "呢"'
  # 文案（findings 行格式与各规则修法、清零要求 + 完整扫描提示，两端须逐字一致）
  '行 毒句式['
  '删「不X…却Y」反差腔，直接写具体效果或动作。'
  '「没有…，没有…」排比删到只剩一个或全删，改写正面在场的细节。'
  '删否定铺垫，直接写肯定项，或改成动作细节。'
  '删章尾预告腔，用正在发生的动作或画面收章。'
  '删章尾状态总结句，收束状态是细纲的规划口径，正文落到具体动作、画面或台词上。'
  '毒句式是确定性 AI 指纹：本章须清零后再继续。完整扫描：node <skill>/scripts/check-ai-patterns.js --check <正文文件>'
  '处未清毒句式欠账，'
  '去味:跳过'
  '去味(：|:)跳过'
  '\r?\n'
)
toxic_fail=0
for needle in "${TOXIC_SYNC[@]}"; do
  for file in "$JS_CORE" "$PY_HOOK"; do
    if ! grep -Fq -- "$needle" "$file"; then
      echo "FAIL: 毒句式规范串缺失/漂移 — 「${needle}」未出现在 $(basename "$file")"
      toxic_fail=1
    fi
  done
done

# 欠账门的豁免标记与门文案 js↔py 同步。Claude bash 侧前置门（guard-outline-before-prose.sh）
# 的判定与文案由 test-prose-net-parity.sh D 段按真实写入逐场景锁。
GATE_SYNC=(
  '去味(：|:)跳过'
  '未清毒句式欠账'
  '<!-- 去味:跳过 --> 后重试'
)
for needle in "${GATE_SYNC[@]}"; do
  for file in "$JS_CORE" "$PY_HOOK"; do
    if ! grep -Fq -- "$needle" "$file"; then
      echo "FAIL: 欠账门规范串缺失/漂移 — 「${needle}」未出现在 $(basename "$file")"
      toxic_fail=1
    fi
  done
done
if [ "$toxic_fail" -ne 0 ]; then
  exit 1
fi

echo "OK: 毒句式正则/常量/文案 js↔py 逐字同步（含欠账门标记/文案）"
