#!/bin/bash
# test-outline-copy.sh — regression tests for the outline-copy detector.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository" >&2
  exit 1
fi

SCRIPT="$REPO_ROOT/skills/story-long-write/scripts/check-outline-copy.js"
DETECTOR_COPIES=(
  "$REPO_ROOT/skills/story-long-write/scripts/check-outline-copy.js"
  "$REPO_ROOT/skills/story-short-write/scripts/check-outline-copy.js"
)
for detector_copy in "${DETECTOR_COPIES[@]}"; do
  node --check "$detector_copy" >/dev/null
  cmp -s "$SCRIPT" "$detector_copy" || {
    echo "FAIL: detector copy drifted from story-long-write source: $detector_copy" >&2
    exit 1
  }
done

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

CASE=""
STATUS=0
OUTPUT=""

fail() {
  echo "FAIL [$CASE]: $1" >&2
  [ -n "$OUTPUT" ] && echo "--- detector output ---" >&2 && echo "$OUTPUT" >&2
  exit 1
}

run() {
  set +e
  OUTPUT="$(node "$SCRIPT" "$@" 2>&1)"
  STATUS=$?
  set -e
}

expect_status() {
  [ "$STATUS" -eq "$1" ] || fail "expected exit $1, got $STATUS"
}

expect_contains() {
  case "$OUTPUT" in
  *"$1"*) ;;
  *) fail "expected output to contain: $1" ;;
  esac
}

# Git Bash 会把传给 Node 的 /tmp/... 参数转换成 Windows 原生路径。
# 按同一公共进程边界取得预期路径，不把 POSIX 拼写当作 CLI 输出契约。
expect_path() {
  expect_contains "$(node -p 'process.argv[1]' "$1")"
}

expect_missing() {
  case "$OUTPUT" in
  *"$1"*) fail "expected output NOT to contain: $1" ;;
  *) ;;
  esac
}

# 22 字未授权重合，单独就超过 15 字阈值
COPIED="他握紧那柄旧刀在雨里站了整整一夜没有离开半步"
# 6 字锚句，短于阈值：只有被挖除后剩余片段仍达阈值时才谈得上误赦免
OATH="此誓天地可鉴"
VOW="虽死无悔"
# 18 字锚句，本身即超过阈值：用于验证豁免仍然生效（防止改过头）
# 取自 demo/长篇 第 1 章的系统奖励串——真实的功能性重合样本，本就该逐字一致
PANEL="天王级唱功大师级导演能力中国军魂伴奏"

# --- 1. 锚句之前存在超阈值重合：必须报出前段，不得因片段含锚句而整段赦免 ---
CASE="anchor-tail"
cat >"$TMP_DIR/o1.md" <<EOF
#### 情节细化
- 点1：${COPIED}，${OATH}。
- 复沓锚句：
  点1：${OATH}
EOF
printf '%s，%s。\n' "$COPIED" "$OATH" >"$TMP_DIR/p1.md"
run --outline "$TMP_DIR/o1.md" "$TMP_DIR/p1.md"
expect_status 1
expect_contains "22 字「${COPIED}」"
expect_contains "1 处 6 字为复沓锚句"

# --- 2. 锚句之后存在超阈值重合 ---
CASE="anchor-head"
cat >"$TMP_DIR/o2.md" <<EOF
#### 情节细化
- 点1：${OATH}，${COPIED}。
- 复沓锚句：
  点1：${OATH}
EOF
printf '%s，%s。\n' "$OATH" "$COPIED" >"$TMP_DIR/p2.md"
run --outline "$TMP_DIR/o2.md" "$TMP_DIR/p2.md"
expect_status 1
expect_contains "22 字「${COPIED}」"

# --- 3. 一个重合片段里包含多个锚句：中间段照报，两端各自扣除 ---
CASE="multi-anchor"
cat >"$TMP_DIR/o3.md" <<EOF
#### 情节细化
- 点1：${OATH}，${COPIED}，${VOW}。
- 复沓锚句：
  点1：${OATH}
  点1：${VOW}
EOF
printf '%s，%s，%s。\n' "$OATH" "$COPIED" "$VOW" >"$TMP_DIR/p3.md"
run --outline "$TMP_DIR/o3.md" "$TMP_DIR/p3.md"
expect_status 1
expect_contains "22 字「${COPIED}」"
expect_contains "10 字为复沓锚句"

# --- 4. 片段完全等于锚句：豁免仍然生效，静默放行并报出豁免量 ---
CASE="pure-anchor"
cat >"$TMP_DIR/o4.md" <<EOF
#### 情节细化
- 点1：面板弹出，主角确认奖励到手。
- 复沓锚句：
  点1：${PANEL}
EOF
printf '眼前忽然亮起一行小字。\n%s\n他抬手把那行字抹掉。\n' "$PANEL" >"$TMP_DIR/p4.md"
run --outline "$TMP_DIR/o4.md" "$TMP_DIR/p4.md"
expect_status 0
expect_contains "无未授权誊抄"
expect_contains "1 处 18 字"

# --- 5. 短篇标准结构：正文.md + 小节大纲.md，单参调用必须自动发现 ---
CASE="short-story-autodiscover"
mkdir -p "$TMP_DIR/短篇"
cat >"$TMP_DIR/短篇/小节大纲.md" <<EOF
## 第一节
- 点1：${COPIED}。
EOF
printf '%s。\n' "$COPIED" >"$TMP_DIR/短篇/正文.md"
run "$TMP_DIR/短篇/正文.md"
expect_status 1
expect_contains "22 字「${COPIED}」"

# --- 6. 长篇标准结构：正文/第N章 + 大纲/细纲_第N章，单参调用必须自动发现 ---
CASE="long-form-autodiscover"
mkdir -p "$TMP_DIR/长篇/正文" "$TMP_DIR/长篇/大纲"
cat >"$TMP_DIR/长篇/大纲/细纲_第001章.md" <<EOF
## 第 1 章
- 点1：${COPIED}。
EOF
printf '# 第001章 雨夜\n\n%s。\n' "$COPIED" >"$TMP_DIR/长篇/正文/第001章_雨夜.md"
run "$TMP_DIR/长篇/正文/第001章_雨夜.md"
expect_status 1
expect_contains "22 字「${COPIED}」"

# --- 7. 存量细纲没有复沓锚句字段：按无锚句处理，照常检测且不报错 ---
CASE="legacy-no-anchor-field"
cat >"$TMP_DIR/o7.md" <<EOF
#### 情节细化
- 点1：${COPIED}，${OATH}。
EOF
printf '%s，%s。\n' "$COPIED" "$OATH" >"$TMP_DIR/p7.md"
run --outline "$TMP_DIR/o7.md" "$TMP_DIR/p7.md"
expect_status 1
expect_contains "28 字"
expect_missing "为复沓锚句"

# --- 8. 锚句字段写「无」：不得把「无」当成锚句 ---
CASE="anchor-field-none"
cat >"$TMP_DIR/o8.md" <<EOF
#### 情节细化
- 点1：${COPIED}。
- 复沓锚句：无
- 结尾设定：主角离开。
EOF
printf '%s。\n' "$COPIED" >"$TMP_DIR/p8.md"
run --outline "$TMP_DIR/o8.md" "$TMP_DIR/p8.md"
expect_status 1
expect_contains "22 字「${COPIED}」"
expect_missing "为复沓锚句"

# --- 9. 正文与细纲无重合：完全静默 ---
CASE="clean"
cat >"$TMP_DIR/o9.md" <<EOF
#### 情节细化
- 点1：${COPIED}。
EOF
printf '雨停了，他终于肯回头看一眼身后那扇门。\n' >"$TMP_DIR/p9.md"
run --outline "$TMP_DIR/o9.md" "$TMP_DIR/p9.md"
expect_status 0
[ -z "$OUTPUT" ] || fail "expected silent output on a clean chapter"

# --- 10. 自动发现不到细纲：明确跳过但不阻断普通独立正文 ---
CASE="missing-outline"
printf '%s。\n' "$COPIED" >"$TMP_DIR/orphan.md"
run "$TMP_DIR/orphan.md"
expect_status 0
expect_contains "跳过"
expect_path "$TMP_DIR/orphan.md"
expect_contains "未自动发现细纲"

# --- 11. 收尾复扫按通配传多章：每章各自比对，不得把第二个正文当成细纲 ---
CASE="multi-prose-batch"
mkdir -p "$TMP_DIR/批/正文" "$TMP_DIR/批/大纲"
cat >"$TMP_DIR/批/大纲/细纲_第005章.md" <<EOF
## 第 5 章
- 点1：${COPIED}。
EOF
cat >"$TMP_DIR/批/大纲/细纲_第006章.md" <<EOF
## 第 6 章
- 点1：${VOW}，主角转身离开。
EOF
printf '# 第005章 雨夜\n\n%s。\n' "$COPIED" >"$TMP_DIR/批/正文/第005章_雨夜.md"
printf '# 第006章 天明\n\n雨停了，他终于肯回头看一眼身后那扇门。\n' >"$TMP_DIR/批/正文/第006章_天明.md"
run "$TMP_DIR/批/正文/第005章_雨夜.md" "$TMP_DIR/批/正文/第006章_天明.md"
expect_status 1
expect_contains "第005章_雨夜.md"
expect_contains "22 字「${COPIED}」"

# --- 12. 多章里只有靠后的一章有重合：不得因首章干净就整体放行 ---
CASE="multi-prose-later-hit"
run "$TMP_DIR/批/正文/第006章_天明.md" "$TMP_DIR/批/正文/第005章_雨夜.md"
expect_status 1
expect_contains "第005章_雨夜.md"

# --- 13. 显式细纲不存在：不是「干净」，必须准确报错并退 2 ---
CASE="explicit-missing-outline"
run --outline "$TMP_DIR/不存在的细纲.md" "$TMP_DIR/p9.md"
expect_status 2
expect_contains "无法读取显式细纲"
expect_path "$TMP_DIR/不存在的细纲.md"
expect_contains "不存在"

# --- 14. 正文不存在：必须准确报出正文路径并退 2 ---
CASE="missing-prose"
run --outline "$TMP_DIR/o9.md" "$TMP_DIR/不存在的正文.md"
expect_status 2
expect_contains "无法读取正文"
expect_path "$TMP_DIR/不存在的正文.md"
expect_contains "不存在"

# --- 15. 参数错误：缺少 --outline 值、未知选项、没有正文都退 2 ---
CASE="outline-option-without-value"
run --outline
expect_status 2
expect_contains "--outline 缺少路径"

CASE="unknown-option"
run --unknown "$TMP_DIR/p9.md"
expect_status 2
expect_contains "未知选项: --unknown"

CASE="no-prose"
run --outline "$TMP_DIR/o9.md"
expect_status 2
expect_contains "缺少正文路径"

# --- 16. 目录不是可读文本文件：跨平台稳定拒绝，不能依赖 EISDIR 文案 ---
CASE="outline-is-directory"
mkdir -p "$TMP_DIR/目录细纲"
run --outline "$TMP_DIR/目录细纲" "$TMP_DIR/p9.md"
expect_status 2
expect_contains "无法读取显式细纲"
expect_path "$TMP_DIR/目录细纲"
expect_contains "不是普通文件"

CASE="prose-is-directory"
mkdir -p "$TMP_DIR/目录正文"
run --outline "$TMP_DIR/o9.md" "$TMP_DIR/目录正文"
expect_status 2
expect_contains "无法读取正文"
expect_path "$TMP_DIR/目录正文"
expect_contains "不是普通文件"

# --- 17. 非预期异常：顶层不得吞掉异常后伪装成成功 ---
CASE="unexpected-exception"
printf '%s。\n' "$COPIED" >"$TMP_DIR/explode.md"
cat >"$TMP_DIR/throw-on-basename.js" <<'EOF'
const path = require('path')
const originalBasename = path.basename
path.basename = function basename(file, ...args) {
  if (originalBasename.call(this, file, ...args) === 'explode.md') throw new Error('synthetic unexpected failure')
  return originalBasename.call(this, file, ...args)
}
EOF
set +e
OUTPUT="$(node --require "$TMP_DIR/throw-on-basename.js" "$SCRIPT" "$TMP_DIR/explode.md" 2>&1)"
STATUS=$?
set -e
expect_status 2
expect_contains "细纲照搬检测异常"
expect_contains "synthetic unexpected failure"

# --- 21. 自动发现权限错误不能伪装成没有细纲 ---
CASE="auto-outline-permission-error"
cat >"$TMP_DIR/throw-on-readdir.js" <<'JS'
const fs = require('fs')
const original = fs.readdirSync
fs.readdirSync = function (dir, ...args) {
  if (String(dir).endsWith('大纲')) {
    const error = new Error(`EACCES: cannot read ${dir}`)
    error.code = 'EACCES'
    throw error
  }
  return original.call(this, dir, ...args)
}
JS
set +e
OUTPUT="$(node --require "$TMP_DIR/throw-on-readdir.js" "$SCRIPT" "$TMP_DIR/批/正文/第005章_雨夜.md" 2>&1)"
STATUS=$?
set -e
expect_status 2
expect_contains "EACCES"
expect_contains "大纲"

# --- 22. 找到路径后读取失败仍然是输入错误，不得跳过 ---
CASE="discovered-outline-read-error"
cat >"$TMP_DIR/throw-on-outline-read.js" <<'JS'
const fs = require('fs')
const original = fs.readFileSync
fs.readFileSync = function (file, ...args) {
  if (String(file).endsWith('细纲_第005章.md')) {
    const error = new Error(`EACCES: cannot read ${file}`)
    error.code = 'EACCES'
    throw error
  }
  return original.call(this, file, ...args)
}
JS
set +e
OUTPUT="$(node --require "$TMP_DIR/throw-on-outline-read.js" "$SCRIPT" "$TMP_DIR/批/正文/第005章_雨夜.md" 2>&1)"
STATUS=$?
set -e
expect_status 2
expect_contains "EACCES"
expect_contains "细纲_第005章.md"

# --- 23. 自动发现的目标是目录同样拒绝 ---
CASE="discovered-outline-is-directory"
mkdir -p "$TMP_DIR/非文件细纲/小节大纲.md"
printf '%s。\n' "$COPIED" >"$TMP_DIR/非文件细纲/正文.md"
run "$TMP_DIR/非文件细纲/正文.md"
expect_status 2
expect_contains "不是普通文件"

echo "PASS: check-outline-copy.js (23 cases)"
