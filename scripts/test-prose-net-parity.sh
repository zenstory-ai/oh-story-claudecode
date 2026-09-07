#!/bin/bash
# test-prose-net-parity.sh — 正文兜底「轻量确定性网」四端 parity 守卫
# 网有两份运行实现：Codex `story_codex_hook.py` 与共享 JS core；Claude、OpenCode、ZCode
# 消费各自的同字节 core 副本。本测试四层保证：
#   A. 功能 parity：codex python 网、opencode TS 网、
#      zcode JS 网在同一组 fixture 上逐字相等。
#   B. 命令函数 parity（CI 硬保证）：正文目标抽取、apply-patch 目标、git commit 侦测三个纯函数
#      在 codex python 与 zcode JS 间逐字相等——锁住此前无守卫、已漂移的手抄逻辑。
#   C. 未归核面 parity（CI 硬保证）：staged markdown warnings 与大纲阻断判定未归核——codex
#      python 与 JS core 各有一份实现，在 fixture 上逐字比对（大小写变体命中、警告/阻断文案），
#      语义/文案以 JS core 为准。Claude 端这两面另有纯 bash 实现（validate-story-commit.sh 的
#      grep 段、guard-outline-before-prose.sh 的判定段），无跨端逐字锁，行为由
#      check-story-setup-deployment.sh / test-hook-encoding-portable.sh 的运行回归覆盖。
#   D. Claude bash 写正文守卫 ↔ JS core 行为 parity（CI 硬保证）：按「同一工程同一次写入，
#      bash 拦不拦 == JS 核拦不拦」逐场景比对，并锚死每个场景的期望方向（否则两端一起漏拦
#      也能 diff 干净）。补上 D 说的那条空档——#283 给另三端加追踪门时 Claude 侧静默漏了
#      一整版（issue #305），正是因为 bash 那一面没有任何跨端断言。
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$ROOT" ] && { echo "Error: not in a git repository" >&2; exit 1; }

CODEX="$ROOT/skills/story-setup/references/codex/hooks/story_codex_hook.py"
OPENCODE="$ROOT/skills/story-setup/references/opencode/plugin.ts"
ZCODE="$ROOT/skills/story-setup/references/zcode/hooks/story_zcode_hook.js"
ZCODE_CORE="$ROOT/skills/story-setup/references/zcode/hooks/story_hook_core.js"
OPENCODE_CORE="$ROOT/skills/story-setup/references/opencode/story_hook_core.js"
CLAUDE_CORE="$ROOT/skills/story-setup/references/templates/hooks/story_hook_core.js"
CLAUDE_COMMIT="$ROOT/skills/story-setup/references/templates/hooks/validate-story-commit.sh"
CLAUDE_GAPS="$ROOT/skills/story-setup/references/templates/hooks/detect-story-gaps.sh"
CLAUDE_GUARD="$ROOT/skills/story-setup/references/templates/hooks/guard-outline-before-prose.sh"
CLAUDE_HOOK_CLI="$ROOT/skills/story-setup/references/templates/hooks/story_hook_cli.js"
STORYCTL="$ROOT/skills/story-long-write/scripts/storyctl.py"
for f in "$CODEX" "$OPENCODE" "$ZCODE" "$ZCODE_CORE" "$OPENCODE_CORE" "$CLAUDE_CORE" "$CLAUDE_COMMIT" "$CLAUDE_GAPS" "$CLAUDE_GUARD" "$CLAUDE_HOOK_CLI" "$STORYCTL"; do
  [ -f "$f" ] || { echo "FAIL: missing impl: $f" >&2; exit 1; }
done

fails=0

# ── A. 功能 parity（codex python 网 vs opencode TS 网） ──
# TS 运行：优先 node 原生类型擦除（node ≥ 22.6 的 --experimental-strip-types），否则用本机 esbuild；
# 都没有时只跳过 OpenCode plugin 直跑，Codex ↔ ZCode 行为 parity 仍执行。
run_functional() {
  command -v node >/dev/null 2>&1 || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  cat > "$tmp/fixtures.json" <<'EOF'
{
  "clean": "江晨睁开眼天还没亮。\n他要快要狠要赢这是唯一的活路。\n「作为AI管家，我劝你别白费力气。」\n他握紧拳头走向门口。",
  "truncate": "江晨握紧拳头慢慢走向门口。\n江晨冲过去一拳砸在",
  "truncate_astral": "他继续往前走。\n开头😀😀😀😀😀😀😀😀😀😀😀😀😀X",
  "refuse": "夜色压下来。\n作为AI我无法继续创作这部分内容。",
  "refuse_after_quote": "“任务完成。”作为AI，我无法继续创作。",
  "refuse_before_quote": "作为AI，我无法继续创作。“你别怕。”",
  "refuse_after_multiple_quotes": "“甲说完了。”“乙也点头。”我无法继续创作。",
  "refuse_quoted_ok": "“作为AI，我无法继续创作。”",
  "refuse_quoted_with_prefix_ok": "他说：“作为AI，我无法继续创作。”",
  "refuse_english_quoted_ok": "“I cannot continue writing this scene.”",
  "refuse_unclosed_quote": "“任务完成。作为AI，我无法继续创作。",
  "refuse_apostrophe_contractions": "don't 作为AI，我无法继续创作。 John's!",
  "refuse_curly_apostrophe_contractions": "don’t 作为AI，我无法继续创作。 John’s!",
  "refuse_mixed_curly_apostrophe_contractions": "don‘t 作为AI，我无法继续创作。 John’s!",
  "refuse_single_quoted_ok": "他说：'作为AI，我无法继续创作。'然后关了门。",
  "refuse_curly_single_quoted_ok": "他说：‘作为AI，我无法继续创作。’然后关了门。",
  "ai_selfref_model": "夜色压下来。\n作为一个AI语言模型，我需要提醒您接下来的情节包含暴力描写。",
  "ai_selfref_assistant": "他推门进来。\n作为一个AI助手，这段内容涉及敏感话题。",
  "ai_selfref_era_ok": "作为一个人工智能时代的产物，他对孤独习以为常。\n他把灯关了。",
  "terminal_banner_ok": "他抬起手按在光屏上。\n【叮！任务完成，奖励已发放】",
  "terminal_ascii_quote_ok": "他站起来推开门。\n他说：\"我回来了。\"",
  "toxic_quote_codename_ok": "他把烟头按进烟灰缸。\n这一战注定是「血屠」的开端，没人料到后来会那样。",
  "engword": "街灯一盏盏亮起。\n按照本章细纲的情节点他该出场了。",
  "repeat": "他握紧拳头一步步走过去缓缓逼近。\n他握紧拳头一步步走过去缓缓逼近。\n他终于停下了。",
  "repeat_seven_ok": "一二三四五六七\n一二三四五六七\n他停下了。",
  "repeat_eight": "一二三四五六七八\n一二三四五六七八\n他停下了。",
  "repeat_astral_seven_ok": "😀😀😀😀😀😀😀\n😀😀😀😀😀😀😀\n他停下了。",
  "repeat_astral_eight": "😀😀😀😀😀😀😀😀\n😀😀😀😀😀😀😀😀\n他停下了。",
  "placeholder": "他打开门。\n（此处省略三百字打斗描写）他赢了。",
  "english_ai": "他说。\nI cannot continue writing this scene for you.",
  "parallel": "要么生，要么死。\n要么战，要么逃。\n要么赢，要么输。\n他做出了选择。",
  "danmaku": "前方高能！\n前方高能！预警。\n这一段我哭了。\n作者加更！",
  "toxic_voice": "他开口了。\n声音不高，第一句却稳稳压住了整个大厅。",
  "toxic_negation": "没有伴奏，没有和声，没有提词器。\n台下静了三秒。",
  "toxic_cross_negation": "不是嚎啕大哭。\n\n也不是扯着嗓子喊不舍。\n\n只是一个人走远了，留在原地的人还站着。",
  "toxic_cross_negation_dialogue_ok": "“不是嚎啕大哭。”\n\n“也不是扯着嗓子喊不舍。”\n\n“只是舍不得。”",
  "toxic_reverse_notis": "是真嗓子，不是修音修出来的。\n他清了清嗓子接着唱。",
  "toxic_forward_notis": "不是没有想过退路，而是根本没有退路。\n他把门关上了。",
  "toxic_trailer": "他放下麦克风朝台下鞠了一躬。\n没人知道，这才刚刚开头。",
  "toxic_trailer_summary": "他放下麦克风朝台下鞠了一躬。\n这一切都结束了。",
  "toxic_trailer_summary_fate": "她把账单折好塞回包里。\n这一夜注定无人入眠。",
  "toxic_bare_realize_ok": "那一刻我终于明白，母亲当年为什么总在夜里哭。\n我抓起外套就往门口走。",
  "toxic_summary_subclause_ok": "等这一切结束了，我们就能过上平静幸福的生活了。\n他把门带上了。",
  "toxic_summary_idiom_ok": "世间的这一刻，所有人都接受了命中注定的结局！\n他转身走了。",
  "toxic_dialogue_ok": "「没人知道。」\n他笑了笑接着往前走。",
  "toxic_eitheror_ok": "不是生就是死，他认了。\n他推门走了进去。",
  "toxic_affirm_ok": "是啊，不是他的错。\n他把灯关了。",
  "toxic_shibushi_ok": "他问自己是不是听错了，是不是灯光太晃。\n他揉了揉眼睛。",
  "toxic_question_ok": "是不是他干的，不是我干的。\n他说不清。",
  "toxic_rhetorical_ok": "是挺好的一件事，不是吗。\n他点了点头。",
  "toxic_curtain_ok": "钟声再度响起，比赛正式拉开序幕。\n他站上了台。",
  "toxic_quote_mid_ok": "她的声音不大好听，被人截成“名场面”，但她不在乎。\n台下没有掌声，没有“安可”声，只有此起彼伏的咳嗽。",
  "toxic_multi_tail_ok": "是他的错，不是我的错，不是吗。\n他点了点头。",
  "toxic_exempt_marker_ok": "# 第1章\n<!-- 去味:跳过 -->\n没有伴奏，没有和声，没有提词器。",
  "toxic_exempt_fullwidth_ok": "# 第1章\n<!-- 去味：跳过 -->\n没有伴奏，没有和声，没有提词器。",
  "toxic_exempt_other_nets": "# 第1章\n<!-- 去味:跳过 -->\n没有伴奏，没有和声，没有提词器。\n按照本章细纲的情节点他该出场了。",
  "toxic_astral_window_ok": "没人知道他练了多少年。\n“第1排😀😀😀😀😀😀😀😀😀😀”\n“第2排😀😀😀😀😀😀😀😀😀😀”\n“第3排😀😀😀😀😀😀😀😀😀😀”\n“第4排😀😀😀😀😀😀😀😀😀😀”\n“第5排😀😀😀😀😀😀😀😀😀😀”\n“第6排😀😀😀😀😀😀😀😀😀😀”\n“第7排😀😀😀😀😀😀😀😀😀😀”\n“第8排😀😀😀😀😀😀😀😀😀😀”\n“第9排😀😀😀😀😀😀😀😀😀😀”\n“第10排😀😀😀😀😀😀😀😀😀😀”\n“第11排😀😀😀😀😀😀😀😀😀😀”\n“第12排😀😀😀😀😀😀😀😀😀😀”\n“第13排😀😀😀😀😀😀😀😀😀😀”\n“第14排😀😀😀😀😀😀😀😀😀😀”\n“第15排😀😀😀😀😀😀😀😀😀😀”\n“第16排😀😀😀😀😀😀😀😀😀😀”\n“第17排😀😀😀😀😀😀😀😀😀😀”\n“第18排😀😀😀😀😀😀😀😀😀😀”\n“第19排😀😀😀😀😀😀😀😀😀😀”\n“第20排😀😀😀😀😀😀😀😀😀😀”\n“第21排😀😀😀😀😀😀😀😀😀😀”\n“第22排😀😀😀😀😀😀😀😀😀😀”\n“第23排😀😀😀😀😀😀😀😀😀😀”\n“第24排😀😀😀😀😀😀😀😀😀😀”\n“第25排😀😀😀😀😀😀😀😀😀😀”\n“第26排😀😀😀😀😀😀😀😀😀😀”\n“第27排😀😀😀😀😀😀😀😀😀😀”\n“第28排😀😀😀😀😀😀😀😀😀😀”\n“第29排😀😀😀😀😀😀😀😀😀😀”\n“第30排😀😀😀😀😀😀😀😀😀😀”",
  "toxic_trailer_window_ok": "没人知道他练了多少年。\n江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。江晨把这段视频剪了又剪从凌晨剪到天亮每一帧都抠得死死的。\n他把琴盖合上，起了身。"
}
EOF

  python3 - "$CODEX" "$tmp/fixtures.json" > "$tmp/py.txt" <<'PY'
import importlib.util, sys, json
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fx = json.load(open(sys.argv[2], encoding='utf-8'))
# 用 stdout.buffer 直写 UTF-8 字节：Windows runner 上 python<3.15 的文本 stdout 是 cp1252，
# 含中文 findings 的 print 会 UnicodeEncodeError（与 node 侧 console.log 的 UTF-8 输出对齐）。
for k in sorted(fx):
    line = k + " | " + " ;; ".join(m.prose_net_findings(fx[k]))
    sys.stdout.buffer.write((line + "\n").encode("utf-8"))
PY

  node - "$ZCODE" "$tmp/fixtures.json" > "$tmp/zcode.txt" <<'JS'
const hook = require(process.argv[2])
const fx = require(process.argv[3])
for (const k of Object.keys(fx).sort()) {
  console.log(k, "|", hook.proseNetFindings(fx[k]).join(" ;; "))
}
JS
  if ! diff "$tmp/py.txt" "$tmp/zcode.txt" >/dev/null; then
    echo "FAIL: 功能 parity 不一致（codex python 网 vs zcode JS 网）：" >&2
    diff "$tmp/py.txt" "$tmp/zcode.txt" >&2 || true
    return 3
  fi

  # 基础规则必须对真实输入产生预期结果；不能只证明三端一起输出了同样的空数组。
  grep -q '^clean | $' "$tmp/py.txt" || { echo "FAIL: 干净正文被误报" >&2; return 3; }
  grep -q '^refuse | 第2行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: 中文 AI 自指未命中" >&2; return 3; }
  grep -q '^refuse_after_quote | 第1行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: 对话后的 AI 自指被整行豁免" >&2; return 3; }
  grep -q '^refuse_before_quote | 第1行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: 对话前的 AI 自指被整行豁免" >&2; return 3; }
  grep -q '^refuse_after_multiple_quotes | 第1行 元信息泄漏（生成拒绝语）' "$tmp/py.txt" || { echo "FAIL: 多段对话后的生成拒绝语被整行豁免" >&2; return 3; }
  grep -q '^refuse_quoted_ok | $' "$tmp/py.txt" || { echo "FAIL: 成对引号内的合法角色台词被误报" >&2; return 3; }
  grep -q '^refuse_quoted_with_prefix_ok | $' "$tmp/py.txt" || { echo "FAIL: 带叙述前缀的成对引号台词被误报" >&2; return 3; }
  grep -q '^refuse_english_quoted_ok | $' "$tmp/py.txt" || { echo "FAIL: 成对引号内的英文角色台词被误报" >&2; return 3; }
  grep -q '^refuse_unclosed_quote | 第1行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: 未闭合引号不应跨行/整行豁免" >&2; return 3; }
  grep -q '^refuse_apostrophe_contractions | 第1行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: ASCII 缩写撇号被误配成引号跨度，吞掉 AI 自指" >&2; return 3; }
  grep -q '^refuse_curly_apostrophe_contractions | 第1行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: 弯撇号缩写吞掉 AI 自指" >&2; return 3; }
  grep -q '^refuse_mixed_curly_apostrophe_contractions | 第1行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: 左/右弯撇号被误配成引号跨度，吞掉 AI 自指" >&2; return 3; }
  grep -q '^refuse_single_quoted_ok | $' "$tmp/py.txt" || { echo "FAIL: ASCII 单引号内合法角色台词被误报" >&2; return 3; }
  grep -q '^refuse_curly_single_quoted_ok | $' "$tmp/py.txt" || { echo "FAIL: 弯单引号内合法角色台词被误报" >&2; return 3; }
  grep -q '^english_ai | 第2行 元信息泄漏（英文 AI 腔）' "$tmp/py.txt" || { echo "FAIL: 英文 AI 腔未命中" >&2; return 3; }
  grep -q '^engword | 第2行 工程词泄漏' "$tmp/py.txt" || { echo "FAIL: 工程词泄漏未命中" >&2; return 3; }
  grep -q '^placeholder | 第2行 占位符' "$tmp/py.txt" || { echo "FAIL: 占位符未命中" >&2; return 3; }
  grep -q '^repeat | 第2行 紧邻复读' "$tmp/py.txt" || { echo "FAIL: 紧邻复读未命中" >&2; return 3; }
  grep -q '^repeat_seven_ok | $' "$tmp/py.txt" || { echo "FAIL: 7 字短行不应触发复读" >&2; return 3; }
  grep -q '^repeat_eight | 第2行 紧邻复读' "$tmp/py.txt" || { echo "FAIL: 8 字复读边界未命中" >&2; return 3; }
  grep -q '^repeat_astral_seven_ok | $' "$tmp/py.txt" || { echo "FAIL: 7 个增补面字符不应触发复读" >&2; return 3; }
  grep -q '^repeat_astral_eight | 第2行 紧邻复读' "$tmp/py.txt" || { echo "FAIL: 8 个增补面字符的复读边界未命中" >&2; return 3; }

  # Adapter 的正文网不再测量字数；同一份欠长正文只应由 storyctl 的公开命令判定。
  # 这锁住职责分离：旧 90% 算法若重新混入任一 Hook，外部输出会立刻回归失败。
  mkdir -p "$tmp/book/大纲" "$tmp/book/正文"
  printf '字数目标：1000\n字数口径：visible_chars_v1\n' > "$tmp/book/大纲/细纲_第001章.md"
  python3 - "$tmp/book/正文/第001章_欠账.md" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_text("# 第1章\n" + "字" * 800 + "。\n", encoding="utf-8")
PY
  python3 "$STORYCTL" wordcount check \
    --file "$tmp/book/正文/第001章_欠账.md" --target 1000 --chapter 1 \
    > "$tmp/storyctl-wordcount.json"
  python3 - "$tmp/storyctl-wordcount.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
assert result["schema"] == "story-wordcount-result/v1", result
assert result["metric"] == "visible_chars_v1", result
assert result["actual"] == 801, result
assert result["status"] == "under", result
PY
  [ -z "$(node "$CLAUDE_HOOK_CLI" prose-net "$tmp/book/正文/第001章_欠账.md")" ] || {
    echo "FAIL: Claude Adapter 重新把字数测量混入正文内容网" >&2
    return 3
  }

  git -C "$tmp/book" init -q
  printf '{}\n' | (cd "$tmp/book" && python3 "$CODEX" stop) > "$tmp/codex-stop.json"
  python3 - "$tmp/codex-stop.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
assert result == {"continue": True}, result
PY

  # 毒句式 fixture 防空转断言（两端同错也能 diff 通过，故对期望输出显式断言）：
  # 正例（用户实抓的真实毒句）须命中对应规则；反例（对话内/either-or/确认语/是不是/
  # 窗口外 trailer）须完全静默。
  grep -q '^toxic_voice | 第2行 毒句式\[voice-contrast\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 voice-contrast 未命中「声音不高…却」" >&2; return 3; }
  grep -q '^toxic_negation | 第1行 毒句式\[negation-parade\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 negation-parade 未命中「没有…没有…」" >&2; return 3; }
  grep -q '^toxic_cross_negation | $' "$tmp/py.txt" || { echo "FAIL: 跨段「不是/也不是/只是」应由深扫语义复核，不应进轻量 blocking 网" >&2; return 3; }
  grep -q '^toxic_reverse_notis | 第1行 毒句式\[reverse-not-is\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 reverse-not-is 未命中「是真嗓子，不是修音」" >&2; return 3; }
  grep -q '^toxic_forward_notis | 第1行 毒句式\[not-is-comparison\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 not-is-comparison 未命中「不是…，而是…」" >&2; return 3; }
  grep -q '^toxic_trailer | 第2行 毒句式\[trailer-ending\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 trailer-ending 未命中「没人知道，这才刚刚开头」" >&2; return 3; }
  grep -q '^toxic_trailer_summary | 第2行 毒句式\[trailer-summary\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 trailer-summary 未命中「这一切都结束了」" >&2; return 3; }
  grep -q '^toxic_trailer_summary_fate | 第2行 毒句式\[trailer-summary\]' "$tmp/py.txt" || { echo "FAIL: 毒句式正例 trailer-summary 未命中「这一夜注定无人入眠」" >&2; return 3; }
  grep -q '^toxic_bare_realize_ok | $' "$tmp/py.txt" || { echo "FAIL: 「那一刻…终于明白」审判金句被误报（短篇卖点，本规则不收认知节拍）" >&2; return 3; }
  grep -q '^toxic_summary_subclause_ok | $' "$tmp/py.txt" || { echo "FAIL: 条件从句「等这一切结束了，…」被误报（未落句末断言位）" >&2; return 3; }
  grep -q '^toxic_summary_idiom_ok | $' "$tmp/py.txt" || { echo "FAIL: 成语「命中注定」被跨匹配成 trailer-summary" >&2; return 3; }
  grep -q '^toxic_dialogue_ok | $' "$tmp/py.txt" || { echo "FAIL: 对话内「没人知道」被误报（成对引号应剥除）" >&2; return 3; }
  grep -q '^toxic_cross_negation_dialogue_ok | $' "$tmp/py.txt" || { echo "FAIL: 三段对话内否定被写后 hook 误报（语义审查负责台词 advisory）" >&2; return 3; }
  grep -q '^toxic_eitheror_ok | $' "$tmp/py.txt" || { echo "FAIL: either-or「不是A就是B」被误报" >&2; return 3; }
  grep -q '^toxic_affirm_ok | $' "$tmp/py.txt" || { echo "FAIL: 确认语「是啊，不是…」被误报" >&2; return 3; }
  grep -q '^toxic_shibushi_ok | $' "$tmp/py.txt" || { echo "FAIL: 疑问「是不是」被误报" >&2; return 3; }
  grep -q '^toxic_question_ok | $' "$tmp/py.txt" || { echo "FAIL: 「是不是…」问句起头被误报" >&2; return 3; }
  grep -q '^toxic_rhetorical_ok | $' "$tmp/py.txt" || { echo "FAIL: 反问尾巴「…，不是吗」被误报" >&2; return 3; }
  grep -q '^toxic_curtain_ok | $' "$tmp/py.txt" || { echo "FAIL: 报幕式「正式拉开序幕」被误报" >&2; return 3; }
  grep -q '^toxic_trailer_window_ok | $' "$tmp/py.txt" || { echo "FAIL: 文末 600 字窗口外的「没人知道」被误报" >&2; return 3; }
  grep -q '^toxic_quote_mid_ok | $' "$tmp/py.txt" || { echo "FAIL: 句中引号段未按等长占位截断，规则跨引号拼出假命中" >&2; return 3; }
  grep -q '^toxic_multi_tail_ok | $' "$tmp/py.txt" || { echo "FAIL: 带中间对比项的反问尾巴「…，不是吗」被误报" >&2; return 3; }
  grep -q '^toxic_exempt_marker_ok | $' "$tmp/py.txt" || { echo "FAIL: 标「去味:跳过」的正文毒句式未被写后网豁免" >&2; return 3; }
  grep -q '^toxic_exempt_fullwidth_ok | $' "$tmp/py.txt" || { echo "FAIL: 全角冒号豁免标记「去味：跳过」未生效" >&2; return 3; }
  grep -q '^toxic_exempt_other_nets | 第4行 工程词泄漏' "$tmp/py.txt" || { echo "FAIL: 豁免标记不应连带关掉毒句式以外的网（工程词漏检）" >&2; return 3; }
  grep '^toxic_exempt_other_nets' "$tmp/py.txt" | grep -q '毒句式' && { echo "FAIL: 豁免标记在场时毒句式仍被推回" >&2; return 3; }
  grep -q '^toxic_astral_window_ok | $' "$tmp/py.txt" || { echo "FAIL: 引号内 emoji 的占位长度未按 UTF-16 码元对齐，trailer 窗口切点漂移" >&2; return 3; }
  grep -q '^toxic_quote_codename_ok | $' "$tmp/py.txt" || { echo "FAIL: 引号占位替 trailer-summary 的句末 [。！] 伪造终止符（占位字符落进了规则接受位）" >&2; return 3; }

  # AI 自指（软信号）防空转：带型号后缀的最典型退化开场必须命中，且不带拒绝语也要命中
  # （此前 refuse fixture 是被「生成拒绝语」规则接住的，AI 自指规则零覆盖）；复合名词不误报。
  grep -q '^ai_selfref_model | 第2行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: AI 自指未命中「作为一个AI语言模型」（无拒绝语）" >&2; return 3; }
  grep -q '^ai_selfref_assistant | 第2行 元信息泄漏（AI 自指）' "$tmp/py.txt" || { echo "FAIL: AI 自指未命中「作为一个AI助手」" >&2; return 3; }
  grep -q '^ai_selfref_era_ok | $' "$tmp/py.txt" || { echo "FAIL: 复合名词「人工智能时代的产物」被 AI 自指误报" >&2; return 3; }

  # 截断收尾标点：】（章尾系统播报模板的收束符）与 ASCII " （ascii 引号模式的收引号）都算收束，
  # 与深扫 oracle check-degeneration.js 的 findTruncation 一致；真截断另由 truncate fixture 锁。
  grep -q '^terminal_banner_ok | $' "$tmp/py.txt" || { echo "FAIL: 以【…】收尾的章末系统播报被误判疑似截断" >&2; return 3; }
  grep -q '^terminal_ascii_quote_ok | $' "$tmp/py.txt" || { echo "FAIL: 以 ASCII 收引号收尾的对话被误判疑似截断" >&2; return 3; }
  grep -q '^truncate | 第2行 疑似截断' "$tmp/py.txt" || { echo "FAIL: 真截断（结尾无标点）未被检出" >&2; return 3; }
  grep -q '^truncate_astral | 第2行 疑似截断' "$tmp/py.txt" || { echo "FAIL: 增补面字符结尾的真截断未被检出" >&2; return 3; }
  ! grep '^truncate_astral |' "$tmp/py.txt" | grep -q '�' || { echo "FAIL: 增补面字符摘要被 UTF-16 切坏" >&2; return 3; }

  # 转译 TS：擦除类型即可（net 函数只用 RegExp/String/Set/Array）。优先 node 原生类型擦除
  # （node ≥ 22.6 的 --experimental-strip-types），否则用本机已装的 esbuild 二进制。
  # 不走 `npx --yes esbuild`：CI 的 node 20 job 逐次联网下载既慢又脆；
  # 无 TS 运行时只跳过 OpenCode plugin 直跑；上面的 Codex ↔ ZCode 行为 parity 仍是硬门。
  cp "$OPENCODE" "$tmp/p.ts"
  # plugin.ts imports the core from ./lib/story_hook_core.js (the deploy target — a lib/
  # subdir escapes OpenCode's single-level .opencode/plugins/*.js plugin auto-discovery);
  # mirror that layout here so the copied plugin's import resolves.
  mkdir -p "$tmp/lib"
  cp "$OPENCODE_CORE" "$tmp/lib/story_hook_core.js"
  # plugin.ts imports the net from ./lib/story_hook_core.js; re-export it from that companion
  # so the type-stripped module exposes the exact function OpenCode runs at deploy time.
  printf "\nexport { proseNetFindings as _net } from './lib/story_hook_core.js'\n" >> "$tmp/p.ts"
  local ran=0
  if node --experimental-strip-types -e '' >/dev/null 2>&1; then
    node --experimental-strip-types --input-type=module -e "
      import { _net } from '$tmp/p.ts';
      import fs from 'node:fs';
      const fx = JSON.parse(fs.readFileSync('$tmp/fixtures.json','utf-8'));
      for (const k of Object.keys(fx).sort()) console.log(k, '|', _net(fx[k]).join(' ;; '));
    " > "$tmp/ts.txt" 2>/dev/null && ran=1
  fi
  if [ "$ran" -eq 0 ] && command -v esbuild >/dev/null 2>&1; then
    if esbuild "$tmp/p.ts" --format=esm --platform=node --log-level=silent --outfile="$tmp/p.mjs" >/dev/null 2>&1; then
      node --input-type=module -e "
        import { _net } from '$tmp/p.mjs';
        import fs from 'node:fs';
        const fx = JSON.parse(fs.readFileSync('$tmp/fixtures.json','utf-8'));
        for (const k of Object.keys(fx).sort()) console.log(k, '|', _net(fx[k]).join(' ;; '));
      " > "$tmp/ts.txt" 2>/dev/null && ran=1
    fi
  fi
  [ "$ran" -eq 0 ] && return 2

  if ! diff "$tmp/py.txt" "$tmp/ts.txt" >/dev/null; then
    echo "FAIL: 功能 parity 不一致（codex python 网 vs opencode TS 网）：" >&2
    diff "$tmp/py.txt" "$tmp/ts.txt" >&2 || true
    return 3
  fi
  return 0
}

# ── B. 命令函数 parity（codex python vs zcode JS），CI 硬保证 ─────────────────
# 正文目标抽取（重定向/tee/touch/cp·mv）、apply-patch 目标、git commit 侦测三个纯函数
# （命令串 → 值）在下列 fixture 上逐字相等。此前只在 py/js 手抄、无守卫，已漂移（cp·mv
# 元数、git 控制词 then/do/else/elif、子 shell 括号）。node+python3 在 CI 全平台都在，故为硬门。
# 注：fixture 取两端已收敛的子集；引号内分隔符（echo "a; git commit"）与命令替换（$(git commit)）
# 两端本就不等（py 用 shlex 尊重引号，js 裸拆），非本网职责，且只影响 advisory 不影响拦截。
run_cmd_parity() {
  command -v node >/dev/null 2>&1 || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  cat > "$tmp/cmd.json" <<'EOF'
{
  "redirect": "echo x > book/正文/第1章.md",
  "redirect_clobber": "echo x >| book/正文/第1章.md",
  "redirect_both": "echo x >& book/正文/第1章.md",
  "redirect_fd_dup": "echo book/正文/第1章.md >&2",
  "append": "cat a >> 正文.md",
  "tee": "echo x | tee book/正文/第2章.md",
  "tee_a": "printf y | tee -a 正文.md",
  "tee_double_dash": "printf y | tee -- book/正文/第2章.md",
  "tee_multi": "printf y | tee notes.md book/正文/第2章.md",
  "touch": "touch book/正文/第3章.md",
  "touch_multi": "touch notes.md book/正文/第3章.md",
  "touch_reference": "touch -r book/正文/第1章.md notes.md",
  "cp": "cp src.md book/正文/第4章.md",
  "cp_command_wrapper": "command cp src.md book/正文/第4章.md",
  "cp_command_p_wrapper": "command -p cp src.md book/正文/第4章.md",
  "cp_command_double_dash_wrapper": "command -- cp src.md book/正文/第4章.md",
  "cp_env_unset_short": "env -u FOO cp src.md book/正文/第4章.md",
  "cp_env_unset_long": "env --unset FOO cp src.md book/正文/第4章.md",
  "cp_absolute_binary": "/bin/cp src.md book/正文/第4章.md",
  "cp_destination_directory": "cp draft/第4章.md book/正文/",
  "cp_target_directory": "cp --target-directory=book/正文 draft/第4章.md",
  "install": "install draft.md book/正文/第4章.md",
  "mv2": "mv 正文.md",
  "cp_flag": "cp -f a.md 正文.md",
  "mention": "grep -n book/正文/第1章.md notes.md",
  "redirect_quoted_space": "cat draft.md > \"my book/正文/第1章_x.md\"",
  "redirect_fullwidth_space": "cat draft.md > book/正文/第003章　开局.md",
  "tee_quoted_space": "printf x | tee 'my book/正文/第1章_x.md'",
  "cp_quoted_space": "cp draft.md \"my book/正文/第1章_x.md\"",
  "cp_quoted_operator": "cp draft.md \"book|archive/正文/第11章.md\"",
  "literal_quoted_redirect": "echo '> book/正文/第7章.md'",
  "heredoc_mention": "cat <<EOF\n> book/正文/第7章.md\nEOF",
  "multiple_heredoc_mention": "cat <<A <<B\nfirst\nA\n> book/正文/第7章.md\nB",
  "escaped_heredoc_mention": "cat <<\\EOF\n> book/正文/第7章.md\nEOF",
  "escaped_heredoc_then_redirect": "cat <<\\EOF\nliteral\nEOF\necho x > book/正文/第7章.md",
  "escaped_quote_tee_mention": "printf '%s\\n' \"literal \\\" | tee book/正文/第7章.md\"",
  "nested_shell_redirect": "sh -c 'echo x > book/正文/第7章.md'",
  "nested_shell_combined_flags": "bash -lc 'echo x > book/正文/第7章.md'",
  "quoted_command_substitution_redirect": "echo \"$(echo x > book/正文/第7章.md)\"",
  "quoted_backtick_substitution_redirect": "echo \"`echo x > book/正文/第7章.md`\"",
  "patch_add": "*** Begin Patch\n*** Add File: book/正文/第5章.md\n+正文\n*** End Patch",
  "patch_move": "*** Begin Patch\n*** Update File: draft.md\n*** Move to: book/正文/第6章.md\n+正文\n*** End Patch",
  "patch_move_delete": "*** Begin Patch\n*** Delete File: draft.md\n*** Move to: book/正文/第7章.md\n*** End Patch",
  "patch_move_out": "*** Begin Patch\n*** Update File: book/正文/第8章.md\n*** Move to: draft.md\n+x\n*** End Patch",
  "patch_delete_only": "*** Begin Patch\n*** Delete File: book/正文/第9章.md\n*** End Patch",
  "patch_multi_move": "*** Begin Patch\n*** Add File: notes.md\n+x\n*** Update File: draft.md\n*** Move to: book/正文/第10章.md\n+正文\n*** End Patch",
  "patch_context_move": "*** Begin Patch\n*** Update File: book/正文/第12章.md\n@@\n *** Move to: notes.md\n+正文\n*** End Patch",
  "commit_plain": "git commit -m x",
  "commit_chain": "git add . && git commit -m x",
  "commit_if": "if true; then git commit -m x; fi",
  "commit_for": "for f in *; do git commit -am x; done",
  "commit_subshell": "(cd sub && git commit)",
  "commit_env": "FOO=1 git commit",
  "commit_config": "git -c user.name=x commit",
  "commit_C": "git -C sub commit -m y",
  "noncommit_echo": "echo git commit docs",
  "noncommit_status": "git status && echo done"
}
EOF
  python3 - "$CODEX" "$tmp/cmd.json" > "$tmp/cpy.txt" <<'PY'
import importlib.util, sys, json
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fx = json.load(open(sys.argv[2], encoding='utf-8'))
for k in sorted(fx):
    c = fx[k]
    line = f"{k} :: pros=[{'|'.join(m.extract_prose_targets_from_command(c))}] patch=[{'|'.join(m.extract_apply_patch_targets(c))}] commit={'1' if m.is_git_commit_command(c) else '0'}"
    sys.stdout.buffer.write((line + "\n").encode("utf-8"))
PY
  node - "$ZCODE" "$tmp/cmd.json" > "$tmp/cjs.txt" <<'JS'
const h = require(process.argv[2])
const fx = require(process.argv[3])
for (const k of Object.keys(fx).sort()) {
  const c = fx[k]
  console.log(`${k} :: pros=[${h.extractProseTargets(c).join("|")}] patch=[${h.extractPatchTargets(c).join("|")}] commit=${h.isGitCommitCommand(c) ? "1" : "0"}`)
}
JS
  if ! diff "$tmp/cpy.txt" "$tmp/cjs.txt" >/dev/null; then
    echo "FAIL: 命令函数 parity 不一致（codex python vs zcode JS）：" >&2
    diff "$tmp/cpy.txt" "$tmp/cjs.txt" >&2 || true
    return 3
  fi
  # 防空转：带空格/全角空格的目标必须整段取出（两端同错也能 diff 通过）。字符类排 \s 会把
  # 「第003章　开局.md」截成「第003章」、把引号排除在类外会让引号路径整条抽不到目标 → 静默放行。
  grep -q 'redirect_quoted_space :: pros=\[my book/正文/第1章_x.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 带空格的引号重定向目标未被整段取出（引号未被尊重）" >&2; return 3; }
  grep -q 'redirect_fullwidth_space :: pros=\[book/正文/第003章　开局.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 全角空格章名被 \\s 截断（U+3000 不是 shell 分词符）" >&2; return 3; }
  grep -q 'tee_quoted_space :: pros=\[my book/正文/第1章_x.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 带空格的引号 tee 目标未被整段取出" >&2; return 3; }
  grep -q 'cp_quoted_space :: pros=\[my book/正文/第1章_x.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: cp 的引号目标被按空白切碎，末位取到了另一本书的路径" >&2; return 3; }
  grep -q 'cp_quoted_operator :: pros=\[book|archive/正文/第11章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: cp 引号目标里的 | 被误当 shell 管道切段，正文守卫会静默放行" >&2; return 3; }
  grep -q 'tee_double_dash :: pros=\[book/正文/第2章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: tee -- 的正文目标未被提取" >&2; return 3; }
  grep -q 'tee_multi :: pros=\[book/正文/第2章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: tee 的第二个正文输出目标未被提取" >&2; return 3; }
  grep -q 'touch_multi :: pros=\[book/正文/第3章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: touch 的第二个正文目标未被提取" >&2; return 3; }
  grep -q 'touch_reference :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: touch -r 的参考源被误判成写入目标" >&2; return 3; }
  grep -q 'literal_quoted_redirect :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 引号内的重定向示例被误判成真实写入" >&2; return 3; }
  grep -q 'heredoc_mention :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: heredoc 正文中的路径提及被误判成真实写入" >&2; return 3; }
  grep -q 'multiple_heredoc_mention :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 多 heredoc 的后续正文被误判成真实写入" >&2; return 3; }
  grep -q 'escaped_heredoc_mention :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 反斜杠引用 heredoc 正文中的路径提及被误判成真实写入" >&2; return 3; }
  grep -q 'escaped_heredoc_then_redirect :: pros=\[book/正文/第7章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 反斜杠引用 heredoc 吞掉了其后的真实正文写入" >&2; return 3; }
  grep -q 'escaped_quote_tee_mention :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 转义引号内的 tee 示例被误判成真实写入" >&2; return 3; }
  grep -q 'nested_shell_redirect :: pros=\[book/正文/第7章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: sh -c 内的真实正文重定向绕过了守卫" >&2; return 3; }
  grep -q 'nested_shell_combined_flags :: pros=\[book/正文/第7章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: bash -lc 内的真实正文重定向绕过了守卫" >&2; return 3; }
  grep -q 'quoted_command_substitution_redirect :: pros=\[book/正文/第7章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 双引号内的 \$(...) 正文写入绕过了守卫" >&2; return 3; }
  grep -q 'quoted_backtick_substitution_redirect :: pros=\[book/正文/第7章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 双引号内的反引号正文写入绕过了守卫" >&2; return 3; }
  grep -q 'cp_command_wrapper :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: command cp 的正文目标未被提取" >&2; return 3; }
  grep -q 'cp_command_p_wrapper :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: command -p cp 的正文目标未被提取" >&2; return 3; }
  grep -q 'cp_command_double_dash_wrapper :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: command -- cp 的正文目标未被提取" >&2; return 3; }
  grep -q 'cp_env_unset_short :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: env -u 包装的 cp 正文目标未被提取" >&2; return 3; }
  grep -q 'cp_env_unset_long :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: env --unset 包装的 cp 正文目标未被提取" >&2; return 3; }
  grep -q 'cp_absolute_binary :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 绝对路径 cp 的正文目标未被提取" >&2; return 3; }
  grep -q 'cp_destination_directory :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: cp 到正文目录时未按源文件名还原落盘目标" >&2; return 3; }
  grep -q 'cp_target_directory :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: cp --target-directory 的正文目标未被提取" >&2; return 3; }
  grep -q 'install :: pros=\[book/正文/第4章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: install 的正文目标未被提取" >&2; return 3; }
  grep -q 'redirect_clobber :: pros=\[book/正文/第1章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: >| 正文重定向绕过了守卫" >&2; return 3; }
  grep -q 'redirect_both :: pros=\[book/正文/第1章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: >& 文件 正文重定向绕过了守卫" >&2; return 3; }
  grep -q 'redirect_fd_dup :: pros=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: >&2 文件描述符复制被误判成正文写入" >&2; return 3; }
  # 防空转（apply_patch 搬家形态）：`*** Move to:` 是 Update/Delete File 段的子指令，落盘路径是
  # 目的地。只认 Add/Update File 时「Update draft.md + Move to 书/正文/第N章.md」抽到的是源
  # draft.md → 细纲门整条空过、写后兜底网扫的是已不存在的源（两端同错，diff 也看不出来）。
  grep -q 'patch_move :: pros=\[\] patch=\[book/正文/第6章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: apply_patch 的 *** Move to: 目的地未进目标表（源被搬走，只有目的地落盘）" >&2; return 3; }
  grep -q 'patch_move_delete :: pros=\[\] patch=\[book/正文/第7章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: *** Delete File: + *** Move to: 的目的地未进目标表" >&2; return 3; }
  grep -q 'patch_move_out :: pros=\[\] patch=\[draft.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 搬出 正文/ 时源仍被当写入目标（源已不存在，只有目的地该被判）" >&2; return 3; }
  grep -q 'patch_delete_only :: pros=\[\] patch=\[\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 纯 *** Delete File: 不该进目标表（删除不是写入，认它只会给删稿误报）" >&2; return 3; }
  grep -q 'patch_multi_move :: pros=\[\] patch=\[notes.md|book/正文/第10章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: 一份补丁里 Add 段与 Move 段的目标未同时取全（Move 只该顶替同段的源）" >&2; return 3; }
  grep -q 'patch_context_move :: pros=\[\] patch=\[book/正文/第12章.md\]' "$tmp/cpy.txt" \
    || { echo "FAIL: patch 上下文行里的字面 *** Move to 被误当控制指令，实际正文目标被顶掉" >&2; return 3; }

  # ReDoS 回归（shellWords）：调用方先按 [;&|\n] 拆段会拆开引号内的 |，留下一个不闭合的 "。
  # 旧的 /"(?:\\.|[^"])*"|'[^']*'|[^\s]+/ 里 \\. 与 [^"] 都能吃反斜杠，每个反斜杠让搜索空间翻倍，
  # 这条百余字的提交命令实测烧掉数十秒 CPU（超过 zcode hooks.json 的 timeoutMs 15000 被杀）。
  # 线性手写分词必须毫秒级判完，故给 2 秒预算（Python 侧 shlex 本就线性，一并计时防漂移）。
  node - "$ZCODE" > "$tmp/redos.txt" <<'JS' || return 3
const h = require(process.argv[2])
const cmd = 'git commit -m "fix: 正则转义覆盖 ' + Array.from({ length: 18 }, () => "\\\\x").join(" ") + ' covered | see README"'
const t0 = Date.now()
const hit = h.isGitCommitCommand(cmd)
const ms = Date.now() - t0
if (!hit) { console.error("FAIL: git commit 侦测漏判带转义/管道的提交命令"); process.exit(3) }
if (ms > 2000) { console.error(`FAIL: shellWords 回溯爆炸（${ms}ms > 2000ms），宿主 hook 会超时被杀`); process.exit(3) }
console.log(`redos_budget :: ${ms}ms`)
JS
  python3 - "$CODEX" >> "$tmp/redos.txt" <<'PY' || return 3
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cmd = 'git commit -m "fix: 正则转义覆盖 ' + " ".join([r"\\x"] * 18) + ' covered | see README"'
t0 = time.time()
hit = m.is_git_commit_command(cmd)
ms = int((time.time() - t0) * 1000)
# 失败文案走 stderr.buffer 直写 UTF-8：Windows python 的文本 stderr 是 cp1252，中文会 UnicodeEncodeError
if not hit:
    sys.stderr.buffer.write("FAIL: py 侧 git commit 侦测漏判带转义/管道的提交命令\n".encode("utf-8")); sys.exit(3)
if ms > 2000:
    sys.stderr.buffer.write(f"FAIL: py 侧 git commit 侦测退化成非线性（{ms}ms > 2000ms）\n".encode("utf-8")); sys.exit(3)
PY
  return 0
}

# ── C. 未归核面 parity（codex python vs JS core），CI 硬保证 ─────────────────────
# staged markdown warnings 与大纲阻断判定未归核：codex python（staged_markdown_warnings /
# prose_block_reason）与 JS core（stagedMarkdownWarnings / proseBlockReason）各有一份实现，
# 语义/文案以 JS core 为准，这里在 fixture 上逐字比对防漂移。Claude 端的纯 bash 实现不在此锁，
# 由 check-story-setup-deployment.sh / test-hook-encoding-portable.sh 的运行回归覆盖。
# fixture 至少覆盖：① name 字段大小写变体（NAME/全角空格补白）命中一致——有字段不告警；
# ② 缺字段/硬编码属性的中文警告文案（含头尾框线）逐字一致；③ 长篇缺细纲/有细纲、
# 短篇缺小节大纲/无设定信号 4 组阻断判定与阻断文案逐字一致；④ 毒句式欠账门 4 组：
# 有欠账拦、标「去味:跳过」/全角冒号「去味：跳过」豁免放、上一章含坏字节替换解码继续扫。
run_uncored_parity() {
  command -v node >/dev/null 2>&1 || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  command -v git >/dev/null 2>&1 || return 1
  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  # E1: staged markdown warnings —— 建独立 git 仓库并 stage 固定文件集
  local repo="$tmp/repo"
  mkdir -p "$repo/book/正文" "$repo/设定"
  git -C "$repo" init -q
  printf '身高: 180\n他推门而入。\n年龄　：18\n' > "$repo/book/正文/第1章.md"
  printf 'NAME：林远\n' > "$repo/设定/主角.md"            # 大小写变体：字段在，不告警
  printf '　名字 ：苏离\n' > "$repo/设定/配角.md"          # 全角空格补白：字段在，不告警
  printf '简介：没有名字字段\n' > "$repo/设定/反派.md"     # 缺字段：告警
  # 角色卡收窄：只有 设定/角色|人物 子目录内的文件 + 设定/ 直属扁平角色卡才查 name 字段；
  # 项目级设定件（关系/文风/题材定位…）与非角色子目录不查。四端（bash/OpenCode/JS/py）
  # 同口径，这里锁 py↔js 两端，防任一端被改回「整棵 设定/ 一刀切」的假警告版本。
  mkdir -p "$repo/设定/角色" "$repo/设定/世界观"
  printf '简介：没有名字字段的角色卡\n' > "$repo/设定/角色/新人.md"  # 角色卡子目录：缺字段，告警
  printf '# 角色关系图\n' > "$repo/设定/关系.md"                     # 项目级设定件：不告警
  printf '# 文风\n' > "$repo/设定/文风.md"                           # 项目级设定件：不告警
  printf '# 地理\n' > "$repo/设定/世界观/地理.md"                    # 非角色子目录：整目录跳过
  git -C "$repo" add -A

  python3 - "$CODEX" "$repo" > "$tmp/spy.txt" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
out = m.staged_markdown_warnings(Path(sys.argv[2]))
sys.stdout.buffer.write((out + "\n").encode("utf-8"))
PY
  node - "$CLAUDE_CORE" "$repo" > "$tmp/sjs.txt" <<'JS'
const core = require(process.argv[2])
console.log(core.stagedMarkdownWarnings(process.argv[3]))
JS
  if ! diff "$tmp/spy.txt" "$tmp/sjs.txt" >/dev/null; then
    echo "FAIL: staged warnings parity 不一致（codex python vs JS core）：" >&2
    diff "$tmp/spy.txt" "$tmp/sjs.txt" >&2 || true
    return 3
  fi
  # 防空转（两边都输出空串也会 diff 通过）：断言命中/未命中与统一后的中文文案确实在场
  grep -q '正文硬编码角色属性，应引用设定文件' "$tmp/spy.txt" || { echo "FAIL: staged warnings 未按统一文案报硬编码属性" >&2; return 3; }
  grep -q '反派.md: 设定文件缺少 name/名字 必填字段。' "$tmp/spy.txt" || { echo "FAIL: staged warnings 未按统一文案报缺 name 字段" >&2; return 3; }
  grep -q '主角.md' "$tmp/spy.txt" && { echo "FAIL: 大写 NAME： 应视为字段已存在（大小写不敏感）" >&2; return 3; }
  grep -q '配角.md' "$tmp/spy.txt" && { echo "FAIL: 全角空格补白的 名字 ： 应视为字段已存在" >&2; return 3; }
  grep -q '设定/角色/新人.md: 设定文件缺少 name/名字 必填字段。' "$tmp/spy.txt" || { echo "FAIL: 设定/角色 子目录下的角色卡应仍查 name 字段" >&2; return 3; }
  grep -q '关系.md' "$tmp/spy.txt" && { echo "FAIL: 项目级设定件 关系.md 不该被当角色卡查 name" >&2; return 3; }
  grep -q '文风.md' "$tmp/spy.txt" && { echo "FAIL: 项目级设定件 文风.md 不该被当角色卡查 name" >&2; return 3; }
  grep -q '地理.md' "$tmp/spy.txt" && { echo "FAIL: 设定/ 下非角色子目录应整目录跳过" >&2; return 3; }

  # E2: 大纲/追踪阻断判定 —— 长篇缺细纲(拦)/有细纲(放)、短篇缺小节大纲(拦)/无设定信号(放)、
  #     毒句式欠账门（上一章有欠账拦 / 标「去味:跳过」豁免放 / 全角冒号「去味：跳过」豁免放 /
  #     上一章含坏字节替换解码继续扫仍拦）、新书无脚手架时仍须先建细纲（拦）
  local blk="$tmp/blk"
  mkdir -p "$blk/long/正文" "$blk/long/大纲" "$blk/short" "$blk/short2" \
    "$blk/long2/正文" "$blk/long2/大纲" "$blk/long3/正文" "$blk/long3/大纲"
  : > "$blk/long/大纲/细纲_第2章.md"
  : > "$blk/short/设定.md"
  : > "$blk/short2/其他.md"
  : > "$blk/long2/大纲/细纲_第2章.md"
  printf '%s\n' '# 第1章 旧' '' '声音不大，却带着一股狠劲。' > "$blk/long2/正文/第1章_旧.md"
  : > "$blk/long3/大纲/细纲_第2章.md"
  printf '%s\n' '# 第1章 旧' '<!-- 去味:跳过 -->' '声音不大，却带着一股狠劲。' > "$blk/long3/正文/第1章_旧.md"
  mkdir -p "$blk/long4/正文" "$blk/long4/大纲" "$blk/long5/正文" "$blk/long5/大纲"
  : > "$blk/long4/大纲/细纲_第2章.md"
  printf '%s\n' '# 第1章 旧' '<!-- 去味：跳过 -->' '声音不大，却带着一股狠劲。' > "$blk/long4/正文/第1章_旧.md"
  : > "$blk/long5/大纲/细纲_第2章.md"
  { printf '%s\n' '# 第1章 旧' '声音不大，却带着一股狠劲。'; printf '\xff\n'; } > "$blk/long5/正文/第1章_旧.md"
  for book in long long2 long3 long4 long5; do
    mkdir -p "$blk/$book/追踪"
    printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":1}' > "$blk/$book/追踪/_tracking-state.json"
    printf '%s\n' '> 状态修订：0' > "$blk/$book/追踪/上下文.md"
  done
  # 上一章正文已存在、state 提交进度落后：必须拦住下一章首建。
  mkdir -p "$blk/long6/正文" "$blk/long6/大纲" "$blk/long6/追踪"
  : > "$blk/long6/大纲/细纲_第2章.md"
  printf '%s\n' '# 第1章 旧' '他把门关上了。' > "$blk/long6/正文/第1章_旧.md"
  printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":0}' > "$blk/long6/追踪/_tracking-state.json"
  printf '%s\n' '> 状态修订：0' > "$blk/long6/追踪/上下文.md"
  # canonical case：agent 直接首建 {书}/正文/第N章.md，即使书目录还没有大纲/追踪/设定脚手架，
  # 也必须 fail closed；相对目标的 cwd 语义由各宿主 adapter 单独负责，不能靠削弱核心守卫来掩盖。
  mkdir -p "$blk/bare/正文"

  python3 - "$CODEX" "$blk" > "$tmp/bpy.txt" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = Path(sys.argv[2])
for rel in ["long/正文/第1章_起.md", "long/正文/第2章_承.md", "short/正文.md", "short2/正文.md", "long2/正文/第2章_新.md", "long3/正文/第2章_新.md", "long4/正文/第2章_新.md", "long5/正文/第2章_新.md", "long6/正文/第2章_新.md", "bare/正文/第1章_起.md"]:
    reason = m.prose_block_reason(root, root / rel)
    sys.stdout.buffer.write((f"{rel} :: {reason if reason else '-'}\n").encode("utf-8"))
PY
  node - "$CLAUDE_CORE" "$blk" > "$tmp/bjs.txt" <<'JS'
const path = require("node:path")
const core = require(process.argv[2])
const root = process.argv[3]
for (const rel of ["long/正文/第1章_起.md", "long/正文/第2章_承.md", "short/正文.md", "short2/正文.md", "long2/正文/第2章_新.md", "long3/正文/第2章_新.md", "long4/正文/第2章_新.md", "long5/正文/第2章_新.md", "long6/正文/第2章_新.md", "bare/正文/第1章_起.md"]) {
  const reason = core.proseBlockReason(root, path.join(root, rel))
  console.log(`${rel} :: ${reason || "-"}`)
}
JS
  if ! diff "$tmp/bpy.txt" "$tmp/bjs.txt" >/dev/null; then
    echo "FAIL: 大纲阻断 parity 不一致（codex python vs JS core）：" >&2
    diff "$tmp/bpy.txt" "$tmp/bjs.txt" >&2 || true
    return 3
  fi
  grep -q '第1章_起.md :: ⛔' "$tmp/bpy.txt" || { echo "FAIL: 长篇缺细纲未被拦截" >&2; return 3; }
  grep -q '第2章_承.md :: -' "$tmp/bpy.txt" || { echo "FAIL: 长篇有细纲被误拦" >&2; return 3; }
  grep -q 'short/正文.md :: ⛔' "$tmp/bpy.txt" || { echo "FAIL: 短篇缺小节大纲未被拦截" >&2; return 3; }
  grep -q 'short2/正文.md :: -' "$tmp/bpy.txt" || { echo "FAIL: 无设定信号的正文.md 被误拦" >&2; return 3; }
  grep -q '毒句式欠账' "$tmp/bpy.txt" || { echo "FAIL: 上一章毒句式欠账未被欠账门拦截" >&2; return 3; }
  grep -q 'long3/正文/第2章_新.md :: -' "$tmp/bpy.txt" || { echo "FAIL: 标「去味:跳过」豁免的上一章仍被欠账门误拦" >&2; return 3; }
  grep -q 'long4/正文/第2章_新.md :: -' "$tmp/bpy.txt" || { echo "FAIL: 全角冒号豁免标记「去味：跳过」未被欠账门认可" >&2; return 3; }
  grep -q 'long5/正文/第2章_新.md :: ⛔' "$tmp/bpy.txt" || { echo "FAIL: 上一章含坏字节时两端应替换解码继续扫（不得整体放行）" >&2; return 3; }
  grep -q 'long6/正文/第2章_新.md :: ⛔.*必须先提交第1章追踪事务' "$tmp/bpy.txt" || { echo "FAIL: state 的 last_committed_chapter 落后正文时未拦住下一章" >&2; return 3; }
  grep -q 'bare/正文/第1章_起.md :: ⛔' "$tmp/bpy.txt" || { echo "FAIL: 新书无 大纲/追踪/设定 脚手架时首章守卫 fail open" >&2; return 3; }

  # E3: 追踪状态判定 parity。覆盖缺失、坏 JSON、旧 schema、派生 revision 不一致、
  #     缺修订号、缺章号、提交落后和有效 state 放行，避免 Codex Python 与三端 JS core 漂移。
  local cp="$tmp/checkpoints"
  mkdir -p "$cp"/{missing,malformed,old,mismatch,norevision,nolast,behind,valid,revised}/追踪
  for name in malformed old mismatch norevision nolast behind valid revised; do
    printf '%s\n' '> 状态修订：0' > "$cp/$name/追踪/上下文.md"
  done
  printf '%s\n' '{not-json' > "$cp/malformed/追踪/_tracking-state.json"
  printf '%s\n' '{"schema_version":3,"state_revision":0,"last_committed_chapter":7}' > "$cp/old/追踪/_tracking-state.json"
  printf '%s\n' '{"schema_version":4,"state_revision":1,"last_committed_chapter":7}' > "$cp/mismatch/追踪/_tracking-state.json"
  printf '%s\n' '{"schema_version":4,"last_committed_chapter":7}' > "$cp/norevision/追踪/_tracking-state.json"
  printf '%s\n' '{"schema_version":4,"state_revision":0}' > "$cp/nolast/追踪/_tracking-state.json"
  printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":6}' > "$cp/behind/追踪/_tracking-state.json"
  printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":7}' > "$cp/valid/追踪/_tracking-state.json"
  # 回炉/改名/留原稿备份：章号已在追踪范围内（expected 7 < last 9），文件名是新的但该章早已提交，
  # 顺序校验对它恒为假，必须放行——否则 workflow-revision 的「备份原稿」步骤在三端被硬拦。
  printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":9}' > "$cp/revised/追踪/_tracking-state.json"
  python3 - "$CODEX" "$cp" > "$tmp/cpy.txt" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = Path(sys.argv[2])
# 同 B/C 段：Windows runner 上 python<3.15 的文本 stdout 是 cp1252，
# 含中文的 issue 直接 print 会 UnicodeEncodeError，必须走 stdout.buffer 直写 UTF-8。
for name, expected in [("missing", None), ("malformed", None), ("old", None), ("mismatch", None), ("norevision", None), ("nolast", 7), ("behind", 7), ("valid", 7), ("revised", 7)]:
    issue = m.tracking_checkpoint_issue(root / name, require_state=True, expected_last_committed=expected)
    sys.stdout.buffer.write((f"{name} :: {issue or '-'}" + "\n").encode("utf-8"))
PY
  node - "$CLAUDE_CORE" "$cp" > "$tmp/cjs.txt" <<'JS'
const path = require("node:path")
const core = require(process.argv[2])
const root = process.argv[3]
for (const [name, expected] of [["missing", null], ["malformed", null], ["old", null], ["mismatch", null], ["norevision", null], ["nolast", 7], ["behind", 7], ["valid", 7], ["revised", 7]]) {
  const issue = core.trackingCheckpointIssue(path.join(root, name), true, expected)
  console.log(`${name} :: ${issue || "-"}`)
}
JS
  if ! diff "$tmp/cpy.txt" "$tmp/cjs.txt" >/dev/null; then
    echo "FAIL: 追踪检查点 parity 不一致（codex python vs JS core）：" >&2
    diff "$tmp/cpy.txt" "$tmp/cjs.txt" >&2 || true
    return 3
  fi
  grep -q 'missing :: .*_tracking-state.json 缺失' "$tmp/cpy.txt" || { echo "FAIL: 缺失 state 未 fail closed" >&2; return 3; }
  grep -q 'malformed :: .*无法解析' "$tmp/cpy.txt" || { echo "FAIL: 坏 JSON 未 fail closed" >&2; return 3; }
  grep -q 'old :: .*schema_version=4' "$tmp/cpy.txt" || { echo "FAIL: 旧 schema 未 fail closed" >&2; return 3; }
  grep -q 'mismatch :: .*状态修订.*mode=revision 事务重建派生视图' "$tmp/cpy.txt" || { echo "FAIL: 派生 revision 不一致未给 mode=revision 重建动作" >&2; return 3; }
  grep -q 'norevision :: .*缺少整数 state_revision' "$tmp/cpy.txt" || { echo "FAIL: 缺 state_revision 未 fail closed" >&2; return 3; }
  grep -q 'nolast :: .*缺少整数 last_committed_chapter' "$tmp/cpy.txt" || { echo "FAIL: 缺 last_committed 未 fail closed" >&2; return 3; }
  grep -q 'behind :: .*必须先提交第7章追踪事务' "$tmp/cpy.txt" || { echo "FAIL: 落后章号未 fail closed" >&2; return 3; }
  grep -q 'valid :: -' "$tmp/cpy.txt" || { echo "FAIL: 有效 state 被误拦" >&2; return 3; }
  grep -q 'revised :: -' "$tmp/cpy.txt" || { echo "FAIL: 回炉/备份已提交章号被误拦（workflow-revision 备份原稿会卡死）" >&2; return 3; }

  # E4: 续写状态卡超预算在 Python/JS 两端都告警，且不得依赖 mtime 偶然触发。
  local hot="$tmp/hot-context"
  mkdir -p "$hot/book/正文" "$hot/book/追踪"
  printf '%s\n' '# 第1章 开端' '正文。' > "$hot/book/正文/第001章_开端.md"
  printf '%s\n' '{"schema_version":4,"state_revision":0,"last_committed_chapter":1}' > "$hot/book/追踪/_tracking-state.json"
  python3 - "$hot/book/追踪/上下文.md" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(("> 状态修订：0\n" + "状态" * 7000).encode("utf-8"))
PY
  python3 - "$CODEX" "$hot" > "$tmp/hpy.txt" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("ch", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# findings 运行期含中文；Windows 文本 stdout 是 cp1252，必须走 buffer 直写 UTF-8。
for finding in m.continuity_findings(Path(sys.argv[2])):
    sys.stdout.buffer.write((finding + "\n").encode("utf-8"))
PY
  node - "$CLAUDE_CORE" "$hot" > "$tmp/hjs.txt" <<'JS'
const core = require(process.argv[2])
for (const finding of core.continuityFindings(process.argv[3])) console.log(finding)
JS
  if ! diff "$tmp/hpy.txt" "$tmp/hjs.txt" >/dev/null; then
    echo "FAIL: 热上下文超预算 parity 不一致（codex python vs JS core）：" >&2
    diff "$tmp/hpy.txt" "$tmp/hjs.txt" >&2 || true
    return 3
  fi
  grep -q '超出续写状态卡预算 12288 字节' "$tmp/hpy.txt" || { echo "FAIL: 热上下文超预算未告警" >&2; return 3; }
  return 0
}

set +e
run_functional
rc=$?
set -e
case "$rc" in
  0) echo "功能 parity：codex python 网 == opencode TS 网 == zcode JS 网（扩展 fixtures，含毒句式正反例/AI 自指/截断收尾、豁免标记与 storyctl 字数职责分离）。" ;;
  2) echo "功能 parity：codex python 网 == zcode JS 网；OpenCode plugin 直跑跳过（无 TS 运行时）。" ;;
  *) fails=$((fails + 1)) ;;
esac

set +e
run_cmd_parity
rc_cmd=$?
set -e
case "$rc_cmd" in
  0) echo "命令函数 parity：codex python == zcode JS（扩展 fixtures：正文抽取/apply-patch/git commit 侦测逐字相等，含包装器/命令替换/多 heredoc/转义引号、apply_patch 搬家与 ReDoS 预算）。" ;;
  1) echo "命令函数 parity：跳过（无 node/python3 运行时）。" ;;
  *) fails=$((fails + 1)) ;;
esac

# D. Claude bash 写正文守卫 ↔ JS core proseBlockReason 行为 parity（CI 硬保证）。
# 大纲/细纲阻断必须在无 node 的运行时也拦得住，所以 guard-outline-before-prose.sh 用纯 bash
# 判定；追踪检查点要解析 JSON，只能经 story_hook_cli.js 调共享核。两条路径混在一个 BLOCKING
# 守卫里，此前无任何跨端断言覆盖 bash 那一面——#283 给另三端加了追踪门，Claude 侧静默漏了
# 一整版（issue #305）。这里按「同一工程同一次写入，bash 拦不拦 == JS 核拦不拦」逐场景比对，
# 任一端单边改动都会红。
run_bash_guard_parity() {
  command -v node >/dev/null 2>&1 || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN

  # scenario|last_committed|ctx_revision|schema|outline_ch|target_ch|target_exists|拆文库|state
  # state=none 时 last/ctx/schema 无意义。target_exists=1 走续写路径（不判细纲，仍判追踪）。
  local scenarios="
nostate|-|-|-|1|1|0|0|none
nooutline|-|-|-|-|1|0|0|none
importwindow|-|-|-|-|1|0|1|none
importstate|0|0|4|1|3|0|1|yes
valid|0|0|4|1|1|0|0|yes
skipahead|0|0|4|3|3|0|0|yes
existing|1|0|4|1|1|1|0|yes
existing_mismatch|1|9|4|1|1|1|0|yes
badschema|0|0|3|1|1|0|0|yes
revisionbackup|5|0|4|3|3|0|0|yes
"
  local out_bash="$tmp/bash.txt" out_js="$tmp/js.txt"
  : > "$out_bash"; : > "$out_js"

  local line
  while IFS='|' read -r name last ctx schema outline target exists lib state; do
    [ -n "${name:-}" ] || continue
    local proj="$tmp/$name" book="$tmp/$name/书"
    mkdir -p "$book/大纲" "$book/正文" "$book/追踪"
    [ "$lib" = "1" ] && mkdir -p "$proj/拆文库/书"
    [ "$outline" != "-" ] && printf '# 细纲\n' > "$book/大纲/细纲_第00${outline}章.md"
    if [ "$state" = "yes" ]; then
      printf '{"schema_version":%s,"state_revision":0,"last_committed_chapter":%s}\n' "$schema" "$last" \
        > "$book/追踪/_tracking-state.json"
      printf '> 状态修订：%s。\n' "$ctx" > "$book/追踪/上下文.md"
    fi
    local abs="$book/正文/第00${target}章_测试.md"
    [ "$exists" = "1" ] && printf '# 第%s章 测试\n正文。\n' "$target" > "$abs"

    # bash 侧：exit 2 = 拦，0 = 放行
    local payload code
    payload=$(python3 -c 'import json,sys;print(json.dumps({"tool_input":{"file_path":sys.argv[1]}}))' "$abs")
    ( cd "$proj" && CLAUDE_PROJECT_DIR="$proj" CLAUDE_TOOL_INPUT="$payload" bash "$CLAUDE_GUARD" ) >/dev/null 2>&1
    code=$?
    if [ "$code" = 2 ]; then printf '%s :: block\n' "$name" >> "$out_bash"
    else printf '%s :: pass\n' "$name" >> "$out_bash"; fi

    # JS 核侧
    node - "$CLAUDE_CORE" "$proj" "$abs" "$name" >> "$out_js" <<'JS'
const core = require(process.argv[2])
const reason = core.proseBlockReason(process.argv[3], process.argv[4])
console.log(`${process.argv[5]} :: ${reason ? "block" : "pass"}`)
JS
  done <<< "$scenarios"

  if ! diff "$out_bash" "$out_js" >/dev/null; then
    echo "FAIL: 写正文守卫 parity 不一致（Claude bash guard vs JS core）：" >&2
    diff "$out_bash" "$out_js" >&2 || true
    return 3
  fi
  # 光对齐还不够：两端一起漏拦也会 diff 干净。锚死每个场景的期望方向。
  local expect="nostate block
nooutline block
importwindow pass
importstate block
valid pass
skipahead block
existing pass
existing_mismatch block
badschema block
revisionbackup pass"
  while read -r want_name want_verdict; do
    [ -n "$want_name" ] || continue
    grep -qx "$want_name :: $want_verdict" "$out_bash" || {
      echo "FAIL: 场景 $want_name 期望 $want_verdict，实得：$(grep "^$want_name ::" "$out_bash")" >&2
      return 3
    }
  done <<< "$expect"

  # node 缺席时追踪门必须 fail-open（大纲门仍靠纯 bash 拦住）。
  local nonode="$tmp/nonode"; mkdir -p "$nonode"
  local proj="$tmp/nostate" abs="$tmp/nostate/书/正文/第001章_测试.md"
  local payload; payload=$(python3 -c 'import json,sys;print(json.dumps({"tool_input":{"file_path":sys.argv[1]}}))' "$abs")
  ( cd "$proj" && PATH="$nonode:/usr/bin:/bin" CLAUDE_PROJECT_DIR="$proj" CLAUDE_TOOL_INPUT="$payload" \
      bash "$CLAUDE_GUARD" ) >/dev/null 2>&1
  [ $? -eq 0 ] || { echo "FAIL: node 缺席时追踪门未 fail-open（BLOCKING 路径不得依赖 node 在场）" >&2; return 3; }
  return 0
}

set +e
run_uncored_parity
rc_uncored=$?
set -e
case "$rc_uncored" in
  0) echo "未归核面 parity：codex python == JS core（staged warnings 大小写变体/文案 + 大纲阻断 9 组判定含毒句式欠账门/无脚手架 fail-closed/文案逐字相等）。" ;;
  1) echo "未归核面 parity：跳过（无 node/python3/git 运行时）。" ;;
  *) fails=$((fails + 1)) ;;
esac

set +e
run_bash_guard_parity
rc_guard=$?
set -e
case "$rc_guard" in
  0) echo "写正文守卫 parity：Claude bash guard == JS core（10 组工程场景：无 state/缺细纲/导入窗口/跳章/续写/派生修订不一致/坏 schema/回炉备份，含 node 缺席 fail-open）。" ;;
  1) echo "写正文守卫 parity：跳过（无 node/python3 运行时）。" ;;
  *) fails=$((fails + 1)) ;;
esac

if [ "$fails" -ne 0 ]; then
  echo "Prose net parity tests FAILED ($fails)." >&2
  exit 1
fi
echo "Prose net parity tests passed."
