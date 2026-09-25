#!/bin/bash
# test-hook-encoding-portable.sh — 部署型 hook 在 Windows 中文系统下的编码健壮性回归。
#
# Windows 中文环境有两层独立的编码坑（都让 hook 静默失效，见 issue #164）：
#   1) python stdout 默认 cp936（与区域设置无关）：print(中文) 编成 GBK，和脚本 UTF-8
#      字面量字节不符 → 比较恒假。修法：sys.stdout.buffer.write(...encode("utf-8"))。
#   2) 用户导出 GBK 区域设置（LANG=zh_CN.GBK）时，gawk/GNU sed/GNU grep/bash 通配
#      按 GBK 多字节解码 UTF-8 内容/路径会乱。修法：hook 内 export LC_ALL=C 走字节匹配。
#
# 坑 1 随 #243 hook 去掉内嵌 python 已不存在（node 按 UTF-8 写 stdout）。本测试覆盖：
#   Part 1b/1c：Windows 盘符绝对路径分类（issue #184；1b 任何平台可跑，1c 仅 Windows/MSYS）。
#   Part 2：在真实 GBK 区域下跑全部 hook，复现坑 2（需系统装有 zh_CN.GBK 类 locale；
#           macOS 自带，CI ubuntu 由 workflow localedef 生成，Windows Git Bash 若无则跳过）。
# 常规区域下细纲门的长/短篇拦放由 check-story-setup-deployment.sh TS11 覆盖。
#
# 用法：bash scripts/test-hook-encoding-portable.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository"
  exit 1
fi
HOOKS_DIR="$REPO_ROOT/skills/story-setup/references/templates/hooks"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail=0
pass() { echo "  PASS $1"; }
bad()  { echo "  FAIL $1"; fail=1; }

deploy() { # $1 = project root
  mkdir -p "$1/.claude"
  cp -R "$HOOKS_DIR" "$1/.claude/hooks"
  chmod +x "$1/.claude/hooks"/*.sh "$1/.claude/hooks/lib"/*.sh 2>/dev/null || true
}

echo "Hook encoding portability test (issue #164)"
echo "==========================================="

# Part 1b/1c 共用的部署工程（1c 自建带追踪 state 的书目录）。
P1="$WORK/p1"; deploy "$P1"

# ===== Part 1b：Windows 盘符绝对路径分类（issue #184，任何平台可跑）=====
# Windows + Git Bash 下 Claude Code 传入盘符绝对路径（F:/... 或 F:\...）。旧 case 只认 /*，
# 把它当相对路径拼成 $ROOT/F:/...，找错 大纲/ 目录 → 误报细纲缺失。修复后盘符路径按绝对路径处理。
# POSIX runner 无真实盘符：用反证法——fixture 只放在「旧代码会拼出来的」$ROOT/C:/<book> 下。
#   修复后：guard 把 C:/<book> 当绝对路径（→ 文件系统根 /C:/<book>，不存在）→ 找不到 fixture → block(2)
#   旧代码：拼成 $ROOT/C:/<book> 命中 fixture → allow(0)
# 以 block(2) 证明盘符路径已按绝对路径处理。（真实 Windows 上同样的绝对处理会命中真盘符下的
# 真细纲而放行，方向相反，此处只验「是否按绝对路径分类」这一修复点。）
echo "--- Part 1b: Windows drive-letter absolute path classification (issue #184) ---"
if mkdir -p "$P1/C:/book184/大纲" 2>/dev/null && : > "$P1/C:/book184/大纲/细纲_第2章.md" 2>/dev/null; then
  run_guard_drive() { # $1 file_path(JSON-escaped) -> exit code
    local ec=0
    printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$1" \
      | CLAUDE_PROJECT_DIR="$P1" bash "$P1/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?
    printf '%s' "$ec"
  }
  [ "$(run_guard_drive 'C:/book184/正文/第2章_x.md')" = 2 ] \
    && pass "[win] forward-slash drive path treated as absolute (not root-joined)" \
    || bad  "[win] forward-slash drive path was root-joined — issue #184 regression"
  # 反斜杠路径在真实 JSON 里是转义的（\\）；json.loads 解出单反斜杠交给 bash，case 分支再归一。
  [ "$(run_guard_drive 'C:\\book184\\正文\\第2章_x.md')" = 2 ] \
    && pass "[win] backslash drive path treated as absolute (separators normalized)" \
    || bad  "[win] backslash drive path mishandled — issue #184 regression"
  rm -rf "$P1/C:"
else
  echo "  SKIP: 文件系统不支持含 ':' 的目录名（无法构造盘符 fixture）"
fi

# ===== Part 1c：真实 Windows 盘符路径（cygpath，仅 Windows/MSYS 跑）=====
# 1b 是 POSIX 反证；这里在真实 Windows/MSYS 上用 cygpath 把 $P1 映射成 C:/... 盘符路径，
# 直接验用户可见行为：细纲在则放行、细纲缺则拦截——而不是反向的分类反证。POSIX 无 cygpath → SKIP。
echo "--- Part 1c: real Windows drive-letter path via cygpath (issue #184) ---"
if command -v cygpath >/dev/null 2>&1; then
  WINROOT="$(cygpath -m "$P1" 2>/dev/null || true)"
  case "$WINROOT" in
    [A-Za-z]:/*)
      mkdir -p "$P1/winbook/正文" "$P1/winbook/大纲" "$P1/winbook/追踪"
      # 本节测的是盘符路径解析，不是追踪门：落一份有效 state，让细纲门成为唯一变量。
      # last_committed 取大于本节章号的值，章号落在追踪范围内即跳过顺序校验。
      printf '{"schema_version":4,"state_revision":0,"last_committed_chapter":50}\n' > "$P1/winbook/追踪/_tracking-state.json"
      printf '> 状态修订：0。\n' > "$P1/winbook/追踪/上下文.md"
      run_guard_win() { local ec=0; printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$1" \
        | CLAUDE_PROJECT_DIR="$P1" bash "$P1/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?; printf '%s' "$ec"; }
      : > "$P1/winbook/大纲/细纲_第3章.md"
      [ "$(run_guard_win "$WINROOT/winbook/正文/第3章_x.md")" = 0 ] \
        && pass "[win] real drive path allowed when 细纲 present" \
        || bad  "[win] real drive path should allow when 细纲 present"
      rm -f "$P1/winbook/大纲/细纲_第3章.md"
      [ "$(run_guard_win "$WINROOT/winbook/正文/第3章_x.md")" = 2 ] \
        && pass "[win] real drive path blocked when 细纲 missing" \
        || bad  "[win] real drive path should block when 细纲 missing"
      rm -rf "$P1/winbook"
      ;;
    *)
      echo "  SKIP: cygpath present but did not yield a drive-letter path ($WINROOT)"
      ;;
  esac
else
  echo "  SKIP: cygpath not available (not a Windows/MSYS runner)"
fi

# ===== Part 2：真实 GBK 区域下跑全部 hook =====
echo "--- Part 2: real GBK locale (LANG/LC_ALL=zh_CN.GBK) end-to-end ---"
# 探测「可用」的 GBK 类 locale：不看 `locale -a` 列表（Cygwin/MSYS2 会按需合成而不列出），
# 而是真试着设上去看 `locale charmap` 是否返回 GB 类编码。这样 Linux(localedef 生成)、
# macOS(自带)、Windows Git Bash(Cygwin 合成) 三处都能跑到真实 GBK。
detect_gbk_locale() {
  local cand cm
  for cand in zh_CN.GBK zh_CN.gbk zh_CN.GB18030 zh_CN.gb18030 zh_CN.GB2312 zh_CN.gb2312; do
    cm="$(LC_ALL="$cand" locale charmap 2>/dev/null | tr 'a-z' 'A-Z' | tr -d '-')"
    case "$cm" in GBK|GB18030|GB2312) printf '%s' "$cand"; return 0 ;; esac
  done
  return 1
}
GBK_LOCALE="$(detect_gbk_locale || true)"
if [ -z "$GBK_LOCALE" ]; then
  echo "  SKIP: 系统无可用 zh_CN.GBK 类 locale（Part 2 需真实 GBK 区域）"
else
  echo "  using locale: $GBK_LOCALE"
  GBK() { LANG="$GBK_LOCALE" LC_ALL="$GBK_LOCALE" env "$@"; }
  P2="$WORK/p2"; deploy "$P2"
  git -C "$P2" init -q; git -C "$P2" config user.email t@t.t; git -C "$P2" config user.name t
  # 中文书名作为中间目录——正是 GBK 下 bash 通配会 NOMATCH 的场景
  BOOK="$P2/让你管账号"; mkdir -p "$BOOK/正文" "$BOOK/大纲" "$BOOK/追踪" "$BOOK/设定"
  printf '让你管账号\n' > "$P2/.active-book"

  # 2a guard-outline：中文书名中间目录 + 中文通配 glob
  rg() { local ec=0; printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$1" \
    | GBK CLAUDE_PROJECT_DIR="$P2" bash "$P2/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?; printf '%s' "$ec"; }
  [ "$(rg '让你管账号/正文/第1章_开端.md')" = 2 ] && pass "[GBK] guard blocks missing 细纲" || bad "[GBK] guard should block missing 细纲"
  : > "$BOOK/大纲/细纲_第1章.md"
  # 细纲齐了还要追踪检查点成立才放行（issue #305 起 Claude 侧也有这道门）。先落一份有效
  # state，否则下面两条测的就不是中文 glob 而是追踪门。中文书名路径这里要经 node 传给共享核，
  # 顺带守住 GBK 区域下 node 侧按 UTF-8 收路径这条（bash 用 LC_ALL=C 走字节，node 与区域无关）。
  printf '{"schema_version":4,"state_revision":0,"last_committed_chapter":0}\n' > "$BOOK/追踪/_tracking-state.json"
  printf '> 状态修订：0。\n' > "$BOOK/追踪/上下文.md"
  [ "$(rg '让你管账号/正文/第1章_开端.md')" = 0 ] && pass "[GBK] guard allows present 细纲 (Chinese glob)" || bad "[GBK] guard should allow present 细纲 under GBK"
  [ "$(rg '让你管账号/正文/第001章_开端.md')" = 0 ] && pass "[GBK] guard tolerates zero-pad 第001章" || bad "[GBK] guard should tolerate 第001章 under GBK"
  # 追踪门本身在 GBK 区域下也要拦得住：中文书名经 node 解析 state，拦截文案含中文相对路径。
  mv "$BOOK/追踪/_tracking-state.json" "$BOOK/追踪/_state.bak"
  [ "$(rg '让你管账号/正文/第1章_开端.md')" = 2 ] && pass "[GBK] guard blocks missing tracking state (Chinese book path)" || bad "[GBK] guard should block missing tracking state under GBK"
  mv "$BOOK/追踪/_state.bak" "$BOOK/追踪/_tracking-state.json"

  # 2b detect-story-gaps：正常伏笔表不误报；同时证明中文书目能被发现。
  # F001 状态用全角空格 U+3000 补白（已埋 前后各一个），守住 LC_ALL=C 下 trim 仍认全角空格。
  cat > "$BOOK/追踪/伏笔.md" <<'EOF'
| ID | 伏笔内容 | 埋设章节 | 预计回收章节 | 状态{已埋/已回收/已过期/放弃} | 重要度{高/中/低} |
|----|---------|---------|-------------|-----------------------------|----------------|
| F001 | 玉佩身世 | 第1章 | 第20章 |　已埋　| 高 |
| F002 | 师门往事 | 第3章 | 第25章 | 已回收 | 中 |
EOF
  out="$(cd "$P2" && GBK CLAUDE_PROJECT_DIR="$P2" bash .claude/hooks/detect-story-gaps.sh 2>&1 || true)"
  echo "$out" | grep -q '伏笔' && bad "[GBK] detect-story-gaps spuriously warns on normal 伏笔" || pass "[GBK] detect-story-gaps silent on normal 伏笔"
  # 制造真实缺口（正文>10 设定<3），证明中文书目确实被遍历到（否则上面的"静默"是假阳性）
  i=1; while [ "$i" -le 11 ]; do : > "$BOOK/正文/第${i}章.md"; i=$((i+1)); done
  out2="$(cd "$P2" && GBK CLAUDE_PROJECT_DIR="$P2" bash .claude/hooks/detect-story-gaps.sh 2>&1 || true)"
  echo "$out2" | grep -q '让你管账号' && pass "[GBK] detect-story-gaps discovers Chinese book + warns on real gap" || bad "[GBK] detect-story-gaps failed to discover Chinese book under GBK"
  rm -f "$BOOK"/正文/第*章.md

  # 2c validate-story-commit：命中全角冒号 + 全角空格的硬编码属性（C/GBK 区域下方括号字符组
  # 会漏全角冒号、[[:space:]] 会漏全角空格，交替修好）
  printf '年龄　：18\n' > "$BOOK/正文/第1章_开端.md"
  git -C "$P2" add -A >/dev/null 2>&1
  cout="$(cd "$P2" && GBK CLAUDE_PROJECT_DIR="$P2" STORY_COMMIT_COMMAND='git commit -m x' bash .claude/hooks/validate-story-commit.sh 2>&1 || true)"
  echo "$cout" | grep -q '正文硬编码角色属性' && pass "[GBK] validate-commit catches fullwidth-colon attr" || bad "[GBK] validate-commit missed fullwidth-colon attr under GBK"

  # 2d lib/common.sh discover_active_book：.active-book 指向「短中文书名」时，GBK 下 trim sed
  # 会报 illegal byte sequence → active 被吞空 → 误回退到 find 的第一本书。覆盖被 session-*/
  # pre-compact/post-compact 复用的这条共享路径。确定性构造：活跃书无 追踪/正文（fallback 找
  # 不到它），诱饵书有 追踪/（fallback 只会命中诱饵）—— 修复前回 decoy、修复后回 .active-book。
  P2D="$WORK/p2d"; deploy "$P2D"
  mkdir -p "$P2D/让你管账号/设定" "$P2D/decoy小说/追踪"
  printf '让你管账号\n' > "$P2D/.active-book"
  active_path="$(cd "$P2D" && GBK CLAUDE_PROJECT_DIR="$P2D" bash -c 'source ".claude/hooks/lib/common.sh"; discover_active_book' 2>/dev/null)"
  # 字节安全断言：活跃书有 设定/、诱饵书有 追踪/；用 [ -d ] 直接 stat 字节路径，避免 basename
  # 在个别 runner 的 GBK 下改写多字节而假失败。修复前回诱饵（无 设定/），修复后回活跃书。
  if [ -d "$active_path/设定" ]; then
    pass "[GBK] common.sh discover_active_book honors short Chinese .active-book"
  else
    bad "[GBK] common.sh discover_active_book dropped short Chinese .active-book (resolved [$active_path])"
  fi
fi

echo ""
if [ "$fail" -eq 0 ]; then
  echo "PASS: hook 在盘符路径与真实 GBK 区域下都正确"
else
  echo "FAIL: hook 在某个编码/区域模式下行为不符（中文编码回归）"
fi
exit "$fail"
