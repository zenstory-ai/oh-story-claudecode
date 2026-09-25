#!/bin/bash
# test-story-continuity.sh — detect-story-gaps.sh 的跨批连续性兜底回归测试
# 保证：① 追踪 staleness（正文更新到第N章但 上下文.md 更早）→ 提示续写状态卡滞后；
#       ② 章节标题去重（两章撞名）→ 提示改名；③ missing/mismatched/malformed state → 明确警告；
#       ④ 干净项目（state/上下文 revision 一致、上下文新于正文、标题唯一）静默。
# 与 codex story_codex_hook.py 的 continuity_findings 同触发条件（codex 侧由 test-codex-hooks.sh 覆盖）。
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO_ROOT" ] && { echo "Error: not in a git repository" >&2; exit 1; }
HOOK="$REPO_ROOT/skills/story-setup/references/templates/hooks/detect-story-gaps.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found: $HOOK" >&2; exit 1; }
bash -n "$HOOK" || { echo "FAIL: hook has syntax errors" >&2; exit 1; }

# 无 node 则跳过（连续性扫描走 story_hook_cli.js 调共享核，hook 探测不到 node 即静默；CI 三平台都装了 node）。
node -e "" >/dev/null 2>&1 || { echo "test-story-continuity: no node runtime, skipped."; exit 0; }

fails=0
run() { CLAUDE_PROJECT_DIR="$1" bash "$HOOK"; }

# 真书结构（设定 3 个，避开「正文多但设定少」缺口告警，专测连续性）。
make_book() {
  local root="$1"
  mkdir -p "$root/某书/正文" "$root/某书/大纲" "$root/某书/追踪" "$root/某书/设定"
  printf 'a\n' > "$root/某书/设定/角色.md"
  printf 'b\n' > "$root/某书/设定/世界.md"
  printf 'c\n' > "$root/某书/设定/力量.md"
  printf '卷纲\n' > "$root/某书/大纲/卷纲.md"
  printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":0}' > "$root/某书/追踪/_tracking-state.json"
  printf '%s\n' '> 状态修订：0' > "$root/某书/追踪/上下文.md"
}

# ① 追踪 staleness + ② 标题去重
T1="$(mktemp -d)"; make_book "$T1"
printf '旧上下文\n' > "$T1/某书/追踪/上下文.md"
sleep 1
printf '# 第1章 决战\n正文。\n' > "$T1/某书/正文/第001章_决战.md"
printf '# 第2章 决战\n正文。\n' > "$T1/某书/正文/第002章_决战.md"
out="$(run "$T1")"
printf '%s' "$out" | grep -q '续写状态卡更早' || { echo "FAIL: 追踪 staleness 未触发"; echo "$out" >&2; fails=$((fails+1)); }
printf '%s' "$out" | grep -q '标题重复' || { echo "FAIL: 标题去重 未触发"; echo "$out" >&2; fails=$((fails+1)); }
rm -rf "$T1"

# ③ mismatched/malformed/missing state 都必须告警
for kind in mismatch malformed missing; do
  T_META="$(mktemp -d)"; make_book "$T_META"
  printf '# 第1章 开端\n正文。\n' > "$T_META/某书/正文/第001章_开端.md"
  case "$kind" in
    mismatch) printf '%s\n' '{"schema_version":4,"state_revision":1,"last_committed_chapter":0}' > "$T_META/某书/追踪/_tracking-state.json" ;;
    malformed) printf '%s\n' '{not-json' > "$T_META/某书/追踪/_tracking-state.json" ;;
    missing) rm -f "$T_META/某书/追踪/_tracking-state.json" ;;
  esac
  out="$(run "$T_META")"
  case "$kind" in
    mismatch) printf '%s' "$out" | grep -q '状态修订' || { echo "FAIL: mismatched state 未触发"; echo "$out" >&2; fails=$((fails+1)); } ;;
    malformed) printf '%s' "$out" | grep -q '无法解析' || { echo "FAIL: malformed state 未触发"; echo "$out" >&2; fails=$((fails+1)); } ;;
    missing) printf '%s' "$out" | grep -q '_tracking-state.json 缺失' || { echo "FAIL: missing state 未触发"; echo "$out" >&2; fails=$((fails+1)); } ;;
  esac
  rm -rf "$T_META"
done

# ④ 干净项目：上下文新于正文、标题唯一 → 静默
T2="$(mktemp -d)"; make_book "$T2"
printf '# 第1章 开端\n正文。\n' > "$T2/某书/正文/第001章_开端.md"
printf '# 第2章 转折\n正文。\n' > "$T2/某书/正文/第002章_转折.md"
sleep 1
printf '%s\n' '> 状态修订：0' '新上下文，已更新到第2章' > "$T2/某书/追踪/上下文.md"
out="$(run "$T2")"
[ -z "$out" ] || { echo "FAIL: 干净项目应静默，却输出："; echo "$out" >&2; fails=$((fails+1)); }
rm -rf "$T2"

# ⑤ 短篇项目（无 追踪/）：不做 staleness（无 上下文.md），也不误报
T3="$(mktemp -d)"
mkdir -p "$T3/短篇/正文" "$T3/短篇/设定"
printf 'a\n' > "$T3/短篇/设定/角色.md"; printf 'b\n' > "$T3/短篇/设定/世界.md"; printf 'c\n' > "$T3/短篇/设定/力量.md"
printf '# 第1章 起\n正文。\n' > "$T3/短篇/正文/第001章_起.md"
mkdir -p "$T3/短篇/大纲"; printf '大纲\n' > "$T3/短篇/大纲/卷纲.md"
out="$(run "$T3")"
printf '%s' "$out" | grep -q '续写状态卡更早' && { echo "FAIL: 短篇无追踪不应报 staleness"; echo "$out" >&2; fails=$((fails+1)); } || true
rm -rf "$T3"

if [ "$fails" -ne 0 ]; then
  echo "Story continuity tests FAILED ($fails)." >&2
  exit 1
fi
echo "Story continuity regression tests passed."
