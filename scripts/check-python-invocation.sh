#!/bin/bash
# check-python-invocation.sh — 守卫：技能文档里禁止裸调 `python3`
#
# Windows 上 python.org 安装后 `python3` 会落到 Microsoft Store 占位程序、以 exit 49
# 静默失败（见 issue #121）。所有调用必须先按 python3 -> python -> py 探测可用解释器：
#   for PYBIN in python3 python py; do "$PYBIN" -c "" 2>/dev/null && break; done
#   "$PYBIN" -c "..."
#
# 本守卫拦截一切「裸调用」形态：python3 紧跟空白再接任意参数（-c / -m / <<  /
# 脚本路径 / 引号等），以及不带空白的重定向形态（python3<<'PY' / python3<脚本）——
# 后者是合法 shell、同样会落到 Store 占位程序上。探测列表 `python3 python py` 与
# 说明文字（python3 后紧跟反斜杠引号、破折号、箭头等，无空白）不受影响。
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository"
  exit 1
fi

# 裸调用形态：python3 + 空白 + 任意非空白参数（覆盖 -c / -m / << / 脚本路径 / 引号），
# 或 python3 紧跟 `<`（heredoc `python3<<'PY'` 与输入重定向 `python3<脚本`，无空白也照跑）。
# `<` 之外的紧跟形态（反斜杠引号 / 破折号 / 箭头 / 斜杠）仍是说明文字，继续豁免。
PATTERN='python3([[:space:]]+[^[:space:]]|<)'
# 探测列表 `... in python3 python py ...` 是允许写法，从命中里剔除（兼容 PYBIN/c 等变量名）
ALLOW='python3 python py'

echo "Python Invocation Guard"
echo "======================="

# skills/ 文档 + 部署模板 hook（CI scripts 自身允许用任意写法，不扫）
hits="$(grep -rnE "$PATTERN" "$REPO_ROOT/skills" 2>/dev/null | grep -vF "$ALLOW" || true)"

if [ -n "$hits" ]; then
  echo "FAIL: 发现裸调 python3（Windows 上会 exit 49）："
  echo "$hits"
  echo
  echo "改用解释器探测形态："
  echo '  for PYBIN in python3 python py; do "$PYBIN" -c "" 2>/dev/null && break; done'
  echo '  "$PYBIN" -c "..."'
  exit 1
fi

echo "OK: 未发现裸调 python3"
