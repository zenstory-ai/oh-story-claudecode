#!/bin/bash
# check-hook-locale-safety.sh — 守卫部署 hook 在 Windows 中文 GBK 区域下的字节安全。
#
# 背景（issue #164 同类）：部署 hook 跑在用户 Windows Git Bash。若用户导出 GBK/GB2312
# 区域设置，gawk/GNU sed/GNU grep 和 bash 通配会把 UTF-8 中文内容/路径按多字节错误解码，
# 让守卫静默失效（误拦或漏检）。治法是在 hook 里 `export LC_ALL=C` 走字节匹配。
#
# 本守卫是 locale 无关的静态检查（任何 CI 环境都能跑），与行为级回归
# scripts/test-hook-encoding-portable.sh（在真实 GBK 区域下端到端跑 hook）互补。
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository"
  exit 1
fi
HOOKS_DIR="$REPO_ROOT/skills/story-setup/references/templates/hooks"

echo "Hook locale-safety Guard"
echo "========================"

fail=0

# Check 1：所有处理中文内容/路径的部署 hook 必须 export LC_ALL=C，在 GBK 区域下走字节匹配。
# 调 node 共享核的 hook（guard-outline/validate-story-commit）export 位置另有讲究（见各文件注释），
# 但都必须出现该 export。
# 清单不再手抄：直接枚举 hooks 顶层 *.sh（lib/ 由 Check 3 的 per-command LC_ALL=C 管），新增 hook
# 自动进检——原先手抄清单漏了 check-prose-after-write.sh，而它的 `case "$BASE" in 正文.md)`
# 全靠 export LC_ALL=C 走字节比较，漏登记等于这道守卫对它完全失明。
# 下限清单只保留「必须存在」语义：hook 被误删时不能因为枚举不到而假绿。
REQUIRED_LOCALE_HOOKS="check-prose-after-write detect-story-gaps guard-outline-before-prose validate-story-commit session-start session-end pre-compact post-compact"
for h in $REQUIRED_LOCALE_HOOKS; do
  if [ ! -f "$HOOKS_DIR/$h.sh" ]; then
    echo "FAIL: 预期的 locale 敏感 hook 不存在：$h.sh"
    fail=1
  fi
done
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if ! grep -qE '^[[:space:]]*export[[:space:]]+LC_(ALL|CTYPE)=C\b' "$f"; then
    echo "FAIL: $(basename "$f") 缺少 export LC_ALL=C（GBK 区域下中文匹配会乱，issue #164 同类）"
    fail=1
  fi
done < <(find "$HOOKS_DIR" -maxdepth 1 -name '*.sh' -type f | sort)
[ "$fail" -eq 0 ] && echo "OK: locale 敏感 hook 均已 export LC_ALL=C"

# Check 2：禁止在部署 hook 的正则里用含全角字符的方括号字符组（如 [：:]）。含全角字符的
# 字符组只有 UTF-8 区域才正确，在 C/GBK 区域会被拆成单字节、漏匹配；必须改用交替 (：|:)。
# 用字节匹配检测 `[` 紧跟全角冒号/分号/逗号/句号等常见全角标点；跳过整行注释。
# 必须把目录交给 -r（配 --include）而不是 "$HOOKS_DIR"/*.sh：后者只展开顶层文件，-r 形同虚设，
# lib/common.sh、lib/sentinel.sh 里的字符组一个都扫不到。
BRACKET_HITS="$(LC_ALL=C grep -rnE '\[[^]]*(：|；|，|。|！|？|、)' "$HOOKS_DIR" --include='*.sh' 2>/dev/null \
  | grep -vE ':[0-9]+:[[:space:]]*#' || true)"
if [ -n "$BRACKET_HITS" ]; then
  echo "FAIL: 部署 hook 正则里出现含全角字符的方括号字符组（C/GBK 区域会漏匹配，改用交替 (A|B)）："
  echo "$BRACKET_HITS"
  fail=1
else
  echo "OK: 未发现含全角字符的方括号字符组"
fi

# Check 3：hooks/lib/ 下的函数库自己不 export LC_ALL=C（由调用方决定区域），其处理中文书名/路径
# 的 sed/grep 必须 per-command 加 LC_ALL=C，否则 GBK 下 trim 会报 illegal byte sequence、
# .active-book 被吞空、误解析到 find 的第一本书。
# 扫整个 lib/ 而不是只写死 common.sh：sentinel.sh 同样被 session-start 复用，写死文件名等于
# 新增函数库自动免检。
if [ -d "$HOOKS_DIR/lib" ]; then
  # grep -n 带上文件名前缀（-H），注释行用 :[0-9]+:[[:space:]]*# 剔除。
  BARE_TEXT_TOOL="$(grep -HnE '(^|[^=[:alnum:]_])(sed|grep)[[:space:]]' "$HOOKS_DIR/lib"/*.sh 2>/dev/null \
    | grep -vE 'LC_ALL=C' | grep -vE ':[0-9]+:[[:space:]]*#' || true)"
  if [ -n "$BARE_TEXT_TOOL" ]; then
    echo "FAIL: hooks/lib 有未加 LC_ALL=C 的 sed/grep（GBK 下处理中文书名会乱）："
    echo "$BARE_TEXT_TOOL"
    fail=1
  else
    echo "OK: hooks/lib 的 sed/grep 均已 LC_ALL=C"
  fi
fi

exit "$fail"
