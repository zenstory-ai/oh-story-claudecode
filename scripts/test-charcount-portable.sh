#!/bin/bash
# test-charcount-portable.sh — 验证「跨平台字符统计」命令在三大平台 + 无可用
# Python（模拟 Windows Microsoft Store exit-49 占位程序）场景下都能正确数出中文字符数。
#
# 背景：技能文档已统一采用零依赖 Node.js 18+ 的 `node -e` 逐节计字命令，不再依赖
# Python 解释器。`--stub` 模式人为在 PATH 前塞入 exit-49 的假 python3/python/py，
# 确认命令在 Windows Store Python 占位环境下完全不受影响。
#
# 用法：
#   bash scripts/test-charcount-portable.sh           # 常规跨平台验证
#   bash scripts/test-charcount-portable.sh --stub    # 模拟 Store 占位程序(exit 49)
#
# 命令直接从 story-short-write/references/short-format.md「字数统计」节的第一个 bash 块
# 抽取执行，不手抄：文档改了命令，本测试跑的就是新命令。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC="$REPO_ROOT/skills/story-short-write/references/short-format.md"
COUNT_BLOCK="$(awk '/^## 字数统计/{s=1;next} s&&/^```bash$/{b=1;next} b&&/^```$/{exit} b' "$DOC")"
case "$COUNT_BLOCK" in
  *"node -e"*) ;;
  *) echo "FAIL: 未能从 $DOC 的「字数统计」节抽到 node -e 统计命令" >&2; exit 1 ;;
esac

STUB=0
[ "${1:-}" = "--stub" ] && STUB=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 中文目录 + 中文文件名，复现 issue #121 的路径场景
BOOK_DIR="$WORK/小说项目/第一卷"
mkdir -p "$BOOK_DIR"
# 两节：「中文字数测试」6 个码位，「ABC 123」去掉空白后 6 个码位；无结尾换行
printf '%s' $'###1.\n中文字数测试\n###2.\nABC 123' > "$BOOK_DIR/正文.md"
EXPECT=$'###1. 6\n###2. 6'

if [ "$STUB" -eq 1 ]; then
  # 塞入永远 exit 49 的假 python3/python/py，确认计字命令不依赖 Python
  FAKEBIN="$WORK/fakebin"
  mkdir -p "$FAKEBIN"
  for pyname in python3 python py; do
    printf '#!/bin/sh\nexit 49\n' > "$FAKEBIN/$pyname"
    chmod +x "$FAKEBIN/$pyname"
  done
  PATH="$FAKEBIN:$PATH"
  export PATH
  echo "[stub] python3/python/py 现在固定 exit 49（模拟 Microsoft Store 占位程序）"
fi

# 在书目录里原样执行文档命令（相对路径 正文.md）——这正是技能里模型的用法：
# 先 cd 到项目/正文目录再用相对路径，三平台一致。
run_count() {
  OUT="$(cd "$BOOK_DIR" && eval "$COUNT_BLOCK")"
  GOT="$(printf '%s\n' "$OUT" | tr -d '\r' | sed '/^$/d')"
}
run_count

echo "char count: $GOT (expect $EXPECT)"

fail=0
if [ "$GOT" != "$EXPECT" ]; then
  echo "FAIL: 字符数不符（中文路径或 Node 统计命令问题）"
  fail=1
fi

# 第一个小节标记前的导语也要单独报一行
printf '%s' $'开头导语\n###1.\n中文字数测试\n###2.\nABC 123' > "$BOOK_DIR/正文.md"
EXPECT=$'导语 4\n###1. 6\n###2. 6'
run_count
echo "lead count: $GOT (expect $EXPECT)"
if [ "$GOT" != "$EXPECT" ]; then
  echo "FAIL: 导语字数没有报出"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "PASS"
fi
exit "$fail"
