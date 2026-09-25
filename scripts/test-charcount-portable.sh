#!/bin/bash
# test-charcount-portable.sh — 验证「跨平台字符统计」命令在三大平台 + Windows
# Microsoft Store 占位程序场景下都能正确数出中文字符数。
#
# 背景：技能文档要求模型用下面这条探测命令统计字数。Windows 上 python.org 安装后
# `python3` 会落到 Microsoft Store 占位程序、以 exit 49 静默失败，必须按
# python3 -> python -> py 探测出真正可用的解释器。GitHub windows-latest 自带可用的
# python3，因此 `--stub` 模式人为塞入一个 exit-49 的假 python3 来复现真实故障。
#
# 用法：
#   bash scripts/test-charcount-portable.sh           # 用真实解释器
#   bash scripts/test-charcount-portable.sh --stub     # 模拟 Store 占位程序(exit 49)
#
# 命令直接从 story-short-write/references/short-format.md「字数统计」节的第一个 bash 块
# 抽取执行，不手抄：文档改了命令，本测试跑的就是新命令。check-python-invocation.sh
# 守卫文档不回退成裸 python3；本脚本守卫这条命令真的能跑出正确结果。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC="$REPO_ROOT/skills/story-short-write/references/short-format.md"
COUNT_BLOCK="$(awk '/^## 字数统计/{s=1;next} s&&/^```bash$/{b=1;next} b&&/^```$/{exit} b' "$DOC")"
case "$COUNT_BLOCK" in
  *PYBIN*) ;;
  *) echo "FAIL: 未能从 $DOC 的「字数统计」节抽到探测 + 统计命令" >&2; exit 1 ;;
esac

STUB=0
[ "${1:-}" = "--stub" ] && STUB=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 中文目录 + 中文文件名，复现 issue #121 的路径场景
BOOK_DIR="$WORK/小说项目/第一卷"
mkdir -p "$BOOK_DIR"
# 12 个码位：中文字数测试(6) + ABC(3) + 123(3)，无结尾换行
printf '%s' '中文字数测试ABC123' > "$BOOK_DIR/正文.md"
EXPECT=12

# 先记住一个真正可用的解释器。stub 必须自给自足，不假设当前机器
# 同时安装了 python3 和 python/py（某些 macOS 环境只有 python3）。
REAL_PYTHON=""
for candidate in python3 python py; do
  if "$candidate" -c "" >/dev/null 2>&1; then
    REAL_PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$REAL_PYTHON" ] || { echo "FAIL: no working Python interpreter" >&2; exit 1; }

if [ "$STUB" -eq 1 ]; then
  # 塞一个永远 exit 49 的假 python3 到 PATH 最前面，复现 Windows Store 占位程序
  FAKEBIN="$WORK/fakebin"
  mkdir -p "$FAKEBIN"
  printf '#!/bin/sh\nexit 49\n' > "$FAKEBIN/python3"
  printf '#!/bin/sh\nexec "%s" "$@"\n' "$REAL_PYTHON" > "$FAKEBIN/python"
  chmod +x "$FAKEBIN/python3"
  chmod +x "$FAKEBIN/python"
  PATH="$FAKEBIN:$PATH"
  export PATH
  echo "[stub] python3 现在固定 exit 49（模拟 Microsoft Store 占位程序）"
fi

# 在书目录里原样执行文档命令（相对路径 正文.md）——这正是技能里模型的用法：
# 先 cd 到项目/正文目录再用相对路径。Windows Git Bash 下若把绝对 POSIX 路径
# （/tmp/...、/c/...）直接喂给原生 Windows python，会被解析成 C:\tmp\... 而找不到文件；
# 相对路径按子进程真实 cwd 解析，三平台一致。末行回报命令选中的解释器，供 stub 断言。
OUT="$(cd "$BOOK_DIR" && eval "$COUNT_BLOCK"; printf '\n__PYBIN=%s\n' "${PYBIN:-}")"
PYBIN="$(printf '%s\n' "$OUT" | sed -n 's/^__PYBIN=//p')"
GOT="$(printf '%s\n' "$OUT" | sed '/^__PYBIN=/d;/^$/d')"

echo "selected interpreter: $PYBIN"
echo "char count: $GOT (expect $EXPECT)"

fail=0
if [ "$GOT" != "$EXPECT" ]; then
  echo "FAIL: 字符数不符（中文路径或解释器问题）"
  fail=1
fi
if [ "$STUB" -eq 1 ] && [ "$PYBIN" = "python3" ]; then
  echo "FAIL: stub 模式下仍选中了坏掉的 python3，回退链没生效"
  fail=1
fi
if [ "$fail" -eq 0 ]; then
  echo "PASS"
fi
exit "$fail"
