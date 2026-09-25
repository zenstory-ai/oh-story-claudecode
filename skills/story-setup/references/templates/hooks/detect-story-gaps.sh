#!/bin/bash
# detect-story-gaps.sh — 检测写作项目中的 5 项缺口
# 设计原则：无缺口时完全静默，不输出任何内容，避免污染 context
set -euo pipefail

# 加载公共函数库（project_root + discover_all_books）
source "$(dirname "$0")/lib/common.sh"

# 后续 awk 解析中文伏笔表 + find/grep 中文路径。Windows 中文系统若导出 GBK 区域设置，
# gawk 会把 UTF-8 状态值按 GBK 多字节解码失败，trim 和 == 比较全乱、每行误报。强制 C
# 区域走字节匹配（UTF-8 字面量 vs UTF-8 内容字节相等）才稳定（issue #164 同类）。文末的
# 连续性扫描走 node 共享核（story_hook_cli.js），node 按 UTF-8 读文件、写 stdout，
# 不受 LC_ALL=C 影响，故仍可在顶部 export。
export LC_ALL=C

ROOT=$(project_root)
# 报告用真实换行拼接（NL），不用字面 `\n` 占位：输出端必须 printf '%s'，见文末注释。
NL=$'\n'
OUTPUT=""
HAS_WARNINGS=false

# 1. 新项目检测：没有书名目录（同时支持长篇和短篇项目）
# bash 3.2 兼容：不用关联数组，由 discover_all_books 内部按顺序去重。
declare -a BOOK_DIRS=()
while IFS= read -r dir; do
  [ -n "$dir" ] && BOOK_DIRS+=("$dir")
done < <(discover_all_books)

if [ "${#BOOK_DIRS[@]}" -eq 0 ]; then
  # 完全新项目，没有任何目录结构 — 静默退出
  exit 0
fi

for BOOK_DIR in "${BOOK_DIRS[@]}"; do
  BOOK_NAME=$(basename "$BOOK_DIR")
  BOOK_OUTPUT=""

  # 2. 正文多但设定少
  CHAPTER_COUNT=0
  SETTING_COUNT=0
  # `|| true` + 数字兜底不能省：子目录不可读时 find 会退 1，pipefail 把它变成整条管道的
  # 退出码，set -e 就在这里终止脚本——OUTPUT 到文末才 flush，所有警告连 stderr 一起丢光。
  if [ -d "$BOOK_DIR/正文" ]; then
    CHAPTER_COUNT=$(find "$BOOK_DIR/正文" -name "*.md" 2>/dev/null | wc -l | tr -d ' ' || true)
    case "$CHAPTER_COUNT" in ''|*[!0-9]*) CHAPTER_COUNT=0 ;; esac
  elif [ -f "$BOOK_DIR/正文.md" ]; then
    CHAPTER_COUNT=1
  fi
  if [ -d "$BOOK_DIR/设定" ]; then
    SETTING_COUNT=$(find "$BOOK_DIR/设定" -name "*.md" 2>/dev/null | wc -l | tr -d ' ' || true)
    case "$SETTING_COUNT" in ''|*[!0-9]*) SETTING_COUNT=0 ;; esac
  fi
  if [ "$CHAPTER_COUNT" -gt 10 ] && [ "$SETTING_COUNT" -lt 3 ]; then
    BOOK_OUTPUT+="[WARN] ${BOOK_NAME}：正文 ${CHAPTER_COUNT} 章，但设定文件只有 ${SETTING_COUNT} 个，建议补充设定。${NL}"
  fi

  # 4. 过期或异常伏笔线索
  if [ -f "$BOOK_DIR/追踪/伏笔.md" ]; then
    # 仅检查表格数据行中的状态列。当前协议正常状态（已埋/已回收/放弃）不报警，
    # 避免长篇项目每次 SessionStart 都触发全量伏笔审计。
    # 行为回归脚本：scripts/check-hook-regex-sync.sh（区域设置健壮性由 export LC_ALL=C 保证）
    ABNORMAL_FORESHADOW=$(awk -F'|' '
      # 含全角空格 U+3000：LC_ALL=C 下 [[:space:]] 只认 ASCII 空白，单元格用全角空格补白时
      # 会留在 status 里被误判为异常；用交替补上全角空格（不能进字符组，否则触发跨区域 bug）。
      function trim(s) { gsub(/^([[:space:]]|　)+|([[:space:]]|　)+$/, "", s); return s }
      # 分隔行字符组必须含 `:`：markdown 对齐写法 |:---|:---:|---:| 也是分隔行，漏掉它会把
      # 分隔行当数据行、拿 ":---" 当状态值，于是每次 SessionStart 都误报一条伏笔异常。
      # `:` 是 ASCII，可以直接进字符组（全角字符才不行，见上条注释）。
      /^\|/ && $0 !~ /^\|[-:[:space:]|]+$/ {
        status=trim($6)
        if (status == "" || status == "状态" || status ~ /^状态\{/) next
        if (status == "已过期" || (status != "已埋" && status != "已回收" && status != "放弃")) print
      }
    ' "$BOOK_DIR/追踪/伏笔.md" 2>/dev/null || true)
    if [ -n "$ABNORMAL_FORESHADOW" ]; then
      BOOK_OUTPUT+="[WARN] ${BOOK_NAME}：伏笔.md 中检测到过期或异常的伏笔条目，建议跑 /story-review lean 或做一次伏笔审计。${NL}"
    fi
  fi

  # 5. 大纲缺失（按项目类型区分判定）
  if [ -d "$BOOK_DIR/正文" ] || [ -f "$BOOK_DIR/正文.md" ]; then
    # 长篇判定：有 追踪/ 视为长篇，要求 大纲/ 目录
    if [ -d "$BOOK_DIR/追踪" ] && [ ! -d "$BOOK_DIR/大纲" ]; then
      BOOK_OUTPUT+="[WARN] ${BOOK_NAME}：已有 正文/ 但缺少 大纲/，建议先搭大纲。${NL}"
    # 短篇判定：无 追踪/ 视为短篇，要求 小节大纲.md 单文件
    elif [ ! -d "$BOOK_DIR/追踪" ] && [ ! -f "$BOOK_DIR/小节大纲.md" ]; then
      BOOK_OUTPUT+="[WARN] ${BOOK_NAME}：已有正文但缺少 小节大纲.md，建议先搭大纲。${NL}"
    fi
  fi

  # 仅在有问题时输出该书目的信息
  if [ -n "$BOOK_OUTPUT" ]; then
    OUTPUT+="检查：$BOOK_NAME${NL}$BOOK_OUTPUT"
    HAS_WARNINGS=true
  fi
done

# 3. 全局拆文未完成检测（项目级，非书目级）
GLOBAL_PROGRESS_OUTPUT=""
if [ -d "$ROOT/拆文库" ]; then
  # 同 session-start：按「最终状态」过滤，拆完的书不再报（裸数文件会永久误报）。
  while IFS= read -r progress_file; do
    [ -n "$progress_file" ] || continue
    GLOBAL_PROGRESS_OUTPUT+="[WARN] 拆文未完成：${progress_file#$ROOT/}，运行 /story-long-analyze 继续。${NL}"
  done < <(discover_incomplete_analyses "$ROOT")
fi
if [ -n "$GLOBAL_PROGRESS_OUTPUT" ]; then
  OUTPUT+="$GLOBAL_PROGRESS_OUTPUT"
  HAS_WARNINGS=true
fi

# 6. 跨批连续性兜底（追踪 staleness + 章节标题去重）——走 node 共享核 continuityFindings，
# 与 Codex/OpenCode/ZCode 同一份实现。会话起点提醒：续写前发现「写了章但 上下文.md 没跟上」
# 或「两章撞名」。消息串与共享连续性核心保持一致；多书/并列去重的排序按 js 语义（已文档化，仅影响
# advisory 顺序，不影响是否报）。扫描范围 repo-wide（与上方缺口检测一致），多书项目里非活跃书
# 也会提醒——有意为之（切书前也想知道断线），不按 .active-book 收窄。staleness 用 mtime 比较
# （+1 秒容差防同秒误报），是启发式 advisory：git checkout / 带 -p 的拷贝改 mtime 时可能偏差，
# 只提醒不阻塞。node 探测不到静默跳过（native 安装可能无 node，session-start.sh 会在会话起点
# 提示一次；core.js 由 bash hook 目录内 story_hook_cli.js 加载）。
if node -e "" >/dev/null 2>&1; then
  CONT_CLI="$(dirname "$0")/story_hook_cli.js"
  if [ -f "$CONT_CLI" ]; then
    CONTINUITY_OUTPUT="$(node "$CONT_CLI" continuity "$ROOT" 2>/dev/null || true)"
    if [ -n "$CONTINUITY_OUTPUT" ]; then
      OUTPUT+="$CONTINUITY_OUTPUT"
      HAS_WARNINGS=true
    fi
  fi
fi

# 仅在有警告时输出
# 必须 %s 不能 %b：$OUTPUT 里嵌着书名目录名和 node 连续性输出（含从文件里读出的章标题）。
# %b 会把其中的 `\n`、`\b` 当转义展开，`\c` 更会直接终止 printf，把后面的 [WARN] 全吞掉。
# 分隔换行由上面拼接时的 ${NL} 真实换行承担。
if [ "$HAS_WARNINGS" = true ]; then
  printf '%s\n' "=== 写作缺口检测 ===" "$OUTPUT"
fi
