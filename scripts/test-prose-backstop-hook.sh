#!/bin/bash
# test-prose-backstop-hook.sh — regression tests for check-prose-after-write.sh
# 核心保证：① 绝不过度捕获非正文文件（代码/细纲/设定/大纲/游离正文）；② 真正文兜底触发；
# ③ 轻量内容网抓对硬信号（截断/拒绝语/工程词/复读），干净正文（排比+对话+悬念）静默。
# 过度捕获用路径门验证（不依赖解释器）；内容网走 node 共享核（与 parity 测试同一份核）。
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO_ROOT" ] && { echo "Error: not in a git repository" >&2; exit 1; }
HOOK="$REPO_ROOT/skills/story-setup/references/templates/hooks/check-prose-after-write.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK" >&2; exit 1; }

bash -n "$HOOK" || { echo "FAIL: hook has syntax errors" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# 真书结构：设定.md + 大纲/ + 正文/
mkdir -p "$TMP/某书/正文" "$TMP/某书/大纲" "$TMP/docs/正文" "$TMP/游离/正文"
printf '# 设定\n主角江晨。\n' > "$TMP/某书/设定.md"
printf '## 细纲（第1章）\n- 情节点序列：本章细纲，作为AI我无法继续。他握紧拳头。他握紧拳头。\n' > "$TMP/某书/大纲/细纲_第001章.md"
printf '# 大纲\n第1章 第2章 细纲 本章 下一章\n' > "$TMP/某书/大纲/大纲.md"
printf '# 卷纲\n本卷细纲。\n' > "$TMP/某书/大纲/卷纲_第1卷.md"
printf 'const x=1; // 细纲 本章 下一章 作为AI我无法继续 复读复读复读\n' > "$TMP/某书/x.js"
printf '## 正文\n按照细纲，作为AI我无法继续。\n' > "$TMP/docs/正文.md"   # 正文.md 但无 设定.md 兄弟
printf '## 第5章\n按照细纲，作为AI我无法继续。\n' > "$TMP/游离/正文/第005章.md" # 正文/第N章 但无书结构
printf '他' > "$TMP/某书/正文/第001章_截断.md"                            # 真正文，极短 → 落盘触发

run() { CLAUDE_PROJECT_DIR="$TMP" CLAUDE_TOOL_INPUT="{\"tool_input\":{\"file_path\":\"$1\"}}" bash "$HOOK" 2>/dev/null; }

fails=0
expect_silent() {
  local out; out="$(run "$1")"
  if [ -n "$out" ]; then echo "FAIL: over-capture on non-正文 file: $1" >&2; echo "$out" | head -2 >&2; fails=$((fails+1)); fi
}
expect_fire() {
  local out; out="$(run "$1")"
  if [ -z "$out" ]; then echo "FAIL: backstop did not fire on real 正文: $1" >&2; fails=$((fails+1)); fi
}

# ① 绝不捕获这些非正文文件（含工程词/复读/拒绝语文本，证明确实没被扫）
expect_silent "$TMP/某书/大纲/细纲_第001章.md"
expect_silent "$TMP/某书/大纲/大纲.md"
expect_silent "$TMP/某书/大纲/卷纲_第1卷.md"
expect_silent "$TMP/某书/x.js"
expect_silent "$TMP/某书/设定.md"
expect_silent "$TMP/docs/正文.md"
expect_silent "$TMP/游离/正文/第005章.md"
# ② 真正文（极短→落盘信号）必须触发
expect_fire "$TMP/某书/正文/第001章_截断.md"

# ③ 内容网：真正文里的硬信号必须被抓，且抓对类型；干净正文（排比+AI角色对话+悬念收尾）静默。
expect_fire_kw() {
  local out; out="$(run "$1")"
  if ! printf '%s' "$out" | grep -q "$2"; then
    echo "FAIL: 内容网未抓到「$2」: $1" >&2; printf '%s\n' "$out" | head -4 >&2; fails=$((fails+1))
  fi
}
# bash 字符串重复填充正文（不走 python stdout：Windows runner 上 python<3.15 的文本 stdout
# 是 cp1252，写中文会 UnicodeEncodeError；printf 直出脚本里的 UTF-8 字节字面量才稳）。
PAD() { local s='江晨握紧拳头慢慢走向门口心里盘算着接下来的每一步棋。'; printf '%s' "$s$s$s$s$s$s$s$s"; }
# 干净：长正文 + 排比 + AI 角色对话（「作为AI…」在引号内豁免）+ 悬念收尾标点 → 完全静默
{ printf '# 第10章 决战\n\n'; PAD; printf '\n要么生，要么死。\n要么战，要么逃。\n「作为AI管家，我陪你到最后。」\n他终于停下了脚步。\n'; } > "$TMP/某书/正文/第010章_决战.md"
expect_silent "$TMP/某书/正文/第010章_决战.md"
# 截断：结尾无标点
{ printf '# 第11章\n\n'; PAD; printf '\n他猛地冲过去一拳砸在'; } > "$TMP/某书/正文/第011章_截断.md"
expect_fire_kw "$TMP/某书/正文/第011章_截断.md" 截断
# 生成拒绝语 / AI 自指（叙述行，非对话）
{ printf '# 第12章\n\n'; PAD; printf '\n作为AI我无法继续创作这部分内容。\n'; } > "$TMP/某书/正文/第012章_拒绝.md"
expect_fire_kw "$TMP/某书/正文/第012章_拒绝.md" 元信息泄漏
# 工程词漏进正文
{ printf '# 第13章\n\n'; PAD; printf '\n按照本章细纲的情节点，他该出场了。\n他出场了。\n'; } > "$TMP/某书/正文/第013章_工程词.md"
expect_fire_kw "$TMP/某书/正文/第013章_工程词.md" 工程词
# 紧邻整行复读（≥8 可见字符）
{ printf '# 第14章\n\n'; PAD; printf '\n他握紧拳头一步步走过去缓缓逼近。\n他握紧拳头一步步走过去缓缓逼近。\n他停下了。\n'; } > "$TMP/某书/正文/第014章_复读.md"
expect_fire_kw "$TMP/某书/正文/第014章_复读.md" 复读

# 书级 .deslop-whitelist：作者登记的原文字面片段不再被毒句式推回（与 OpenCode/ZCode/Antigravity/
# Codex 同口径，按正文所在书目录找白名单，不跨书继承）。走真实 bash hook → story_hook_cli.js。
expect_no_kw() {
  local out; out="$(run "$1")"
  if printf '%s' "$out" | grep -q "$2"; then
    echo "FAIL: 不该出现「$2」: $1" >&2; printf '%s\n' "$out" | head -4 >&2; fails=$((fails+1))
  fi
}
mkdir -p "$TMP/白名单书/正文" "$TMP/白名单书/大纲" "$TMP/对照书/正文" "$TMP/对照书/大纲"
printf '# 白名单\n声音不大，却带着一股狠劲\n' > "$TMP/白名单书/.deslop-whitelist"
for book in 白名单书 对照书; do
  { printf '# 第1章 开场\n\n'; PAD; printf '\n声音不大，却带着一股狠劲。\n他把门关上了。\n'; } > "$TMP/$book/正文/第001章_开场.md"
done
expect_fire_kw "$TMP/对照书/正文/第001章_开场.md" 'voice-contrast'
expect_no_kw "$TMP/白名单书/正文/第001章_开场.md" '毒句式'
# 白名单只遮登记的片段：同章另一处毒句式照报。
{ printf '# 第2章 回声\n\n'; PAD; printf '\n声音不大，却带着一股狠劲。\n没有伴奏，没有和声，没有提词器。\n他把门关上了。\n'; } > "$TMP/白名单书/正文/第002章_回声.md"
expect_fire_kw "$TMP/白名单书/正文/第002章_回声.md" 'negation-parade'
expect_no_kw "$TMP/白名单书/正文/第002章_回声.md" 'voice-contrast'
# 复扫指引：长篇分章正文指向 storyctl chapter check（长篇流程只认这个入口），短篇 正文.md
# 仍指向 check-ai-patterns.js。
expect_fire_kw "$TMP/对照书/正文/第001章_开场.md" 'storyctl.py chapter check --project <书目录> --chapter 1$'
expect_no_kw "$TMP/对照书/正文/第001章_开场.md" 'check-ai-patterns.js'
mkdir -p "$TMP/短篇书"
printf '# 设定\n' > "$TMP/短篇书/设定.md"
{ printf '# 正文\n\n'; PAD; printf '\n声音不大，却带着一股狠劲。\n他把门关上了。\n'; } > "$TMP/短篇书/正文.md"
expect_fire_kw "$TMP/短篇书/正文.md" 'check-ai-patterns.js --check <正文文件>$'
expect_no_kw "$TMP/短篇书/正文.md" 'storyctl'
# 硬信号分流文案：退化类重写该段，毒句式就地改写。
expect_fire_kw "$TMP/对照书/正文/第001章_开场.md" '截断/拒绝语/工程词→重写该段；毒句式→就地改写'

if [ "$fails" -ne 0 ]; then
  echo "Prose backstop hook tests FAILED ($fails)." >&2
  exit 1
fi
echo "Prose backstop hook regression tests passed."
