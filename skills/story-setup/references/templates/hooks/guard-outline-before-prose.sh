#!/bin/bash
# guard-outline-before-prose.sh — PreToolUse(Bash|Write|Edit|MultiEdit) 流程守卫
# 写「正文」前必须先有对应大纲/细纲，否则阻止（exit 2，BLOCKING）。
#
# 拦截三类：
#   - 长篇 正文/第N章_*.md 首建且缺细纲：要求同书 大纲/细纲_第N章.md 存在
#   - 短篇 正文.md 首建且缺大纲：要求同目录 小节大纲.md 存在
#   - 长篇追踪检查点不成立：state 缺失/schema 不符/续写状态卡修订不一致/首建新章时
#     上一章事务未提交（判定走共享核，与 opencode/zcode/codex 同一份；见下方该段注释）
# 细纲/大纲门只在首建时判，追踪门对首建与续写都判（与 JS 核 proseBlockReason 同序）。
# 非正文目标、解析不到路径一律静默放行。
# 设计原则：宁可漏拦不可误伤——任何不确定都 exit 0。
set -euo pipefail

source "$(dirname "$0")/lib/common.sh"

# 全程走字节稳定区域：本 hook 在中文路径上做 bash 通配（中间目录是中文书名时
# 细纲_第*章*.md 在 GBK 区域会 NOMATCH）、sed 提章号、case 匹配。Windows 中文系统若导出
# GBK/GB2312 区域设置，这些都会按多字节错误解码 UTF-8 而失效。强制 C 区域走字节匹配（UTF-8
# 字面量 vs UTF-8 字节相等）才稳定（issue #164）。路径抽取走 node 共享核，node 自身按 UTF-8
# 处理、与 bash 区域无关；拦截判定全在下方 bash，不受影响。
export LC_ALL=C

HOOK_INPUT="${CLAUDE_TOOL_INPUT:-}"
if [ -z "$HOOK_INPUT" ] && [ ! -t 0 ]; then
  HOOK_INPUT="$(cat)"
fi
# 故意不 export：Write/Edit/MultiEdit 负载里带整章正文（MultiEdit 还带 old_string+new_string），
# export 会把它塞进本脚本每个子进程的 envp，负载一大 execve 就 E2BIG（Linux 单个环境变量上限
# 128 KiB，macOS 整体 1 MiB），dirname/sed/node 全报「Argument list too long」——本守卫会在
# 走到 exit 2 之前死掉，退成「非阻塞错误」放过这次写入，与 BLOCKING 契约相反。改为只在需要负载
# 的 node 调用处用管道喂 stdin（story_hook_cli.js extract-target 在 HOOK_INPUT 缺省时读 stdin）；
# 下方 extract_target_bash 用的是 printf 内建，不需要 export。

# 提取直接写工具的目标文件路径：优先 node 共享核（与其它端同一份实现）；node 缺席、或 node 在但抽取失败时
# 都回落纯 bash 抽取。这是阻断守卫，不能因 node 问题而 fail-open——官方现在推荐原生二进制装
# Claude Code，只有 npm 装法才带 Node，native 运行时可能无 node；旧 node 不识 node: 前缀、或
# 部署的核损坏时 node 探测通过但抽取会抛错。只要能解析出目标路径就照常判定拦截，两条路径都抽不到
# 才放行（宁可漏拦不可误伤）。
CLI="$(dirname "$0")/story_hook_cli.js"

# 纯 bash JSON 抽取兜底：按 dig 优先级取第一处 file_path/path/filePath 字符串值。Claude(node
# 应用)的 hook 负载走 JSON.stringify——非 ASCII 路径是原始 UTF-8（不转 \uXXXX），Windows 盘符
# 路径是 \\ 转义；两者都可在 bash 里还原（下方盘符分支再把 \ 归一成 /）。node 缺席、或 node 在
# 但抽取失败时启用。
extract_target_bash() {
  local key val
  for key in file_path path filePath; do
    val="$(printf '%s' "$HOOK_INPUT" \
      | grep -oE "\"$key\"[[:space:]]*:[[:space:]]*\"([^\"\\\\]|\\\\.)*\"" \
      | head -n1 \
      | sed -E "s/^\"$key\"[[:space:]]*:[[:space:]]*\"//; s/\"\$//")"
    if [ -n "$val" ]; then
      val="${val//\\\"/\"}"   # \" -> "
      val="${val//\\\\/\\}"   # \\ -> \
      printf '%s' "$val"
      return 0
    fi
  done
  return 1
}

TARGET=""
if node -e "" >/dev/null 2>&1 && [ -f "$CLI" ]; then
  TARGET="$(printf '%s' "$HOOK_INPUT" | node "$CLI" extract-target 2>/dev/null || true)"
fi
# node 在场却抽空（旧 node 不识 node: 前缀 / 核损坏时探测通过但抽取抛错）也回落纯 bash。
# Bash 负载没有 file_path；直接目标抽不到时，再让共享核只识别重定向/tee/touch/cp/mv 的写入目标，
# 避免把 grep/cat 等只读命令里提及的正文路径误判为写入。该面依赖 node；node 缺席时 Bash 命令
# 按“宁可漏拦不可误伤”放行，Write/Edit/MultiEdit 仍走上面的纯 bash 兜底。
[ -z "$TARGET" ] && TARGET="$(extract_target_bash 2>/dev/null || true)"

ROOT=$(project_root)
if [ -z "$TARGET" ]; then
  if node -e "" >/dev/null 2>&1 && [ -f "$CLI" ]; then
    set +e
    COMMAND_BLOCK="$(printf '%s' "$HOOK_INPUT" | node "$CLI" prose-command-guard "$ROOT" 2>&1)"
    COMMAND_STATUS=$?
    set -e
    if [ "$COMMAND_STATUS" -ne 0 ]; then
      printf '%s\n' "⚠ Bash 正文写入守卫解析失败，本次按 fail-open 放行；请改用 Write/Edit 或修复 hook：${COMMAND_BLOCK:-未知错误}" >&2
      exit 0
    fi
    if [ -n "$COMMAND_BLOCK" ]; then
      printf '%s\n' "$COMMAND_BLOCK" >&2
      exit 2
    fi
  elif printf '%s' "$HOOK_INPUT" | grep -q '正文'; then
    printf '%s\n' "⚠ 当前环境缺少可用 Node/story_hook_cli.js，无法判定 Bash 是否写正文；本次按 fail-open 放行，请改用 Write/Edit 以启用大纲守卫。" >&2
  fi
  exit 0
fi

# 绝对路径直接采用，相对路径才拼项目根。
# Windows + Git Bash 下 Claude Code 可能传入盘符绝对路径（F:/work/... 或 F:\work\...）；
# 只认 /* 会把它们当相对路径拼成 $ROOT/F:/work/...，找错 大纲/ 目录、误报细纲缺失（issue #184）。
# [A-Za-z]:[/\\]* 命中盘符绝对路径，并把反斜杠统一成正斜杠（对齐 plugin.ts 的 isAbsolute + 反斜杠归一）。
case "$TARGET" in
  /*) ABS="$TARGET" ;;
  [A-Za-z]:[/\\]*) ABS="${TARGET//\\//}" ;;
  *)  ABS="$ROOT/$TARGET" ;;
esac

BASE="$(basename "$ABS")"
PARENT="$(basename "$(dirname "$ABS")")"

case "$BASE" in
  正文.md)
    # 短篇单文件正文：已存在则放行（续写/改稿）
    [ -f "$ABS" ] && exit 0
    BOOK_DIR="$(dirname "$ABS")"
    # story-import 迁移：已有 拆文库/{书名}/ 分析源时，正文先于小节大纲迁移是正常流程（小节大纲由拆文反推），放行
    [ -d "$ROOT/拆文库/$(basename "$BOOK_DIR")" ] && exit 0
    # 仅在确为短篇工程时拦截（有 设定.md 信号——story-short-write/import 都先产 设定.md），
    # 避免误伤 docs/正文.md 等非作品文件
    [ -f "$BOOK_DIR/设定.md" ] || exit 0
    if [ ! -f "$BOOK_DIR/小节大纲.md" ]; then
      printf '%s\n' "⛔ 写正文被拦截：${TARGET} 缺少同目录 小节大纲.md。" >&2
      printf '%s\n' "   先按 story-short-write 完成「小节大纲.md」，再写正文（不允许跳过大纲直接写正文）。" >&2
      printf '%s\n' "   如确需先起草，请先补建 小节大纲.md。" >&2
      exit 2
    fi
    ;;
  *)
    # 长篇分章正文：父目录须为「正文」，文件名形如 第N章...
    [ "$PARENT" = "正文" ] || exit 0
    case "$BASE" in
      第*章*.md) ;;
      *) exit 0 ;;
    esac
    # 章号（去前导零）
    NUM="$(printf '%s' "$BASE" | sed -n 's/^第0*\([0-9][0-9]*\)章.*/\1/p')"
    [ -z "$NUM" ] && exit 0
    BOOK_DIR="$(dirname "$(dirname "$ABS")")"
    # story-import 迁移：已有 拆文库/{书名}/ 分析源时放行（细纲由章节摘要反推、晚于正文迁移）。
    # 一旦 追踪/_tracking-state.json 存在即进入当前追踪协议，不再因为保留了 拆文库/ 分析资产
    # 而永久绕过守卫（与 story_hook_core.js 的同一判定保持一致）。
    if [ -d "$ROOT/拆文库/$(basename "$BOOK_DIR")" ] && [ ! -f "$BOOK_DIR/追踪/_tracking-state.json" ]; then
      exit 0
    fi
    # 正文已存在（续写/改稿/回炉）跳过细纲门，但追踪检查点仍适用——与 JS 核
    # proseBlockReason 同序：细纲门只在首建时判，追踪门两种情况都判。
    EXISTS=""
    [ -f "$ABS" ] && EXISTS=1
    if [ -z "$EXISTS" ]; then
      OUTLINE_DIR="$BOOK_DIR/大纲"
      FOUND=""
      if [ -d "$OUTLINE_DIR" ]; then
        # 容忍补零差异与标题后缀：按整数章号匹配 大纲/细纲_第*章*.md
        for f in "$OUTLINE_DIR"/细纲_第*章*.md; do
          [ -e "$f" ] || continue
          fnum="$(basename "$f" | sed -n 's/^细纲_第0*\([0-9][0-9]*\)章.*/\1/p')"
          if [ "$fnum" = "$NUM" ]; then FOUND="$f"; break; fi
        done
      fi
      if [ -z "$FOUND" ]; then
        printf '%s\n' "⛔ 写正文被拦截：第 ${NUM} 章缺少细纲（${OUTLINE_DIR#$ROOT/}/细纲_第$(printf '%03d' "$NUM")章.md）。" >&2
        printf '%s\n' "   按 story-long-write 单章流程先补建细纲，再写正文（不允许跳过细纲直接写作）。" >&2
        printf '%s\n' "   如确需先起草，请先补建对应细纲文件。" >&2
        exit 2
      fi
    fi
    # 追踪检查点门：state 缺失 / schema 不是 4 / 续写状态卡修订与 state 不一致 / 首建新章
    # 时上一章事务未提交，都拦下。判定走共享核（story_hook_cli.js tracking-checkpoint），
    # 与 opencode/zcode/codex 同一份实现——issue #305 之前这道门只进了 JS 核与 codex py，
    # Claude 侧独缺，会静默写出若干章无追踪的正文。
    # 需要解析 JSON，只能靠 node；node 缺席/核缺失/子命令不识别一律放行（宁可漏拦不可误伤，
    # 与本文件其余降级一致）。SessionStart 连续性提醒与批末 check 仍兜底。
    if node -e "" >/dev/null 2>&1 && [ -f "$CLI" ]; then
      # 首建新章才做顺序校验（期望上一章已提交）；已存在的正文传 `-` 只校验 state 自身。
      EXPECT="-"
      [ -z "$EXISTS" ] && EXPECT=$((NUM - 1))
      CHECKPOINT="$(node "$CLI" tracking-checkpoint "$ROOT" "$BOOK_DIR" "$EXPECT" 2>/dev/null || true)"
      if [ -n "$CHECKPOINT" ]; then
        printf '%s\n' "$CHECKPOINT" >&2
        exit 2
      fi
    fi
    # 正文已存在的到此为止：欠账门只针对首建新章。
    [ -n "$EXISTS" ] && exit 0
    # 欠账门（无状态）：写第 N 章（首建）前，上一章有未清毒句式且未标「去味:跳过」豁免时先清再写。
    # 毒句式扫描走共享核 prose-toxic 子命令（与写后网同一份规则）；node/核缺失或扫描失败一律
    # 放行（宁可漏拦不可误伤）——写后网与 SKILL 同轮铁律仍兜底。判据现算自上一章文件，无状态。
    PREV=$((NUM - 1))
    if [ "$PREV" -ge 1 ] && node -e "" >/dev/null 2>&1 && [ -f "$CLI" ]; then
      PROSE_DIR="$(dirname "$ABS")"
      PREV_FILE=""
      # glob 已按字典序，但同章号的原稿备份（workflow-revision 的「备份原稿」产物）
      # 也会命中；显式跳过 _原稿_，与 JS 核 / codex py 取同一个「上一章」。
      for f in "$PROSE_DIR"/第*章*.md; do
        [ -e "$f" ] || continue
        case "$(basename "$f")" in *_原稿_*) continue ;; esac
        pnum="$(basename "$f" | sed -n 's/^第0*\([0-9][0-9]*\)章.*/\1/p')"
        if [ "$pnum" = "$PREV" ]; then PREV_FILE="$f"; break; fi
      done
      if [ -n "$PREV_FILE" ] && ! head -n 6 "$PREV_FILE" | grep -qE '去味(：|:)跳过'; then
        TOXIC="$(node "$CLI" prose-toxic "$PREV_FILE" 2>/dev/null || true)"
        if [ -n "$TOXIC" ]; then
          printf '%s\n' "⛔ 写正文被拦截：上一章（$(basename "$PREV_FILE")）有未清毒句式欠账，先清零再写第 ${NUM} 章；用户显式豁免时在上一章标题行下加 <!-- 去味:跳过 --> 后重试。" >&2
          # 只列前 8 条。不能写 `printf … | head -n 8`：欠账多时 head 先退出，printf 吃 SIGPIPE，
          # pipefail 下整条管道返回 141，set -e 立刻终止脚本——下面的 exit 2 永远走不到，拦截
          # 退成「非阻塞错误」放过这次写入。改用 here-string 直喂 head（无管道即无 SIGPIPE），
          # 再兜一层 || true，保证无论如何都能走到 exit 2。
          head -n 8 <<< "$TOXIC" >&2 || true
          exit 2
        fi
      fi
    fi
    ;;
esac

exit 0
