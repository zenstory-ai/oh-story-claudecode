#!/bin/bash
# check-hook-regex-sync.sh — 行为级校验 detect-story-gaps.sh 的伏笔状态检测
#
# 设计意图：SessionStart hook 只提示过期或异常伏笔，避免把长篇中正常
# 当前合法状态（已埋/已回收/放弃）误判为问题，诱发 daily 流程中的全量伏笔审计。
# 本脚本运行真实 hook fixture，验证正常状态不报警、已过期/异常状态报警。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOOK_FILE="$REPO_ROOT/skills/story-setup/references/templates/hooks/detect-story-gaps.sh"
COMMON_FILE="$REPO_ROOT/skills/story-setup/references/templates/hooks/lib/common.sh"
PROTOCOL_FILE="$REPO_ROOT/skills/story-long-write/scripts/tracking_commit.py"

for file in "$HOOK_FILE" "$COMMON_FILE" "$PROTOCOL_FILE"; do
  if [ ! -f "$file" ]; then
    echo "FAIL: required file not found: $file"
    exit 1
  fi
done

STATUS_ENUM=$(sed -n 's/^FORESHADOW_STATUSES = (\(.*\))$/\1/p' "$PROTOCOL_FILE" 2>/dev/null | head -1 | tr -d '" ' | tr ',' '/' || true)
if [ -z "$STATUS_ENUM" ]; then
  echo "FAIL: No foreshadow status enum found in protocol file"
  exit 1
fi

echo "Protocol defines status values: $STATUS_ENUM"

TMP_DIR=$(mktemp -d)
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

setup_fixture() {
  local name="$1"
  local foreshadow_body="$2"
  local root="$TMP_DIR/$name"
  mkdir -p "$root/.claude/hooks/lib" "$root/book/追踪" "$root/book/正文" "$root/book/设定" "$root/book/大纲"
  cp "$HOOK_FILE" "$root/.claude/hooks/detect-story-gaps.sh"
  cp "$COMMON_FILE" "$root/.claude/hooks/lib/common.sh"
  chmod +x "$root/.claude/hooks/detect-story-gaps.sh"
  touch "$root/.story-deployed"
  cat > "$root/book/追踪/上下文.md" <<'CTX'
# 写作进度
## 当前位置
- 章: 第1章
CTX
  # 表头状态枚举从 $STATUS_ENUM 展开，不再另抄一份：协议加状态时 fixture 也跟着变，
  # 否则新状态永远不会被行为级 fixture 走到（表头行本身由 hook 的 ^状态\{ 分支跳过）。
  cat > "$root/book/追踪/伏笔.md" <<EOF_FORESHADOW
# 伏笔追踪

## 伏笔状态表

| ID | 伏笔内容 | 埋设章节 | 预计回收章节 | 状态{$STATUS_ENUM} | 重要度{高/中/低} |
|----|---------|---------|-------------|-----------------------------|----------------|
$foreshadow_body
EOF_FORESHADOW
  printf '%s' "$root"
}

run_hook() {
  local root="$1"
  (cd "$root" && bash .claude/hooks/detect-story-gaps.sh)
}

assert_no_foreshadow_warn() {
  local case_name="$1"
  local body="$2"
  local root output
  root=$(setup_fixture "$case_name" "$body")
  output=$(run_hook "$root" || true)
  if echo "$output" | grep -q '伏笔'; then
    echo "FAIL: $case_name should not emit foreshadow warning"
    echo "Output:"
    echo "$output"
    exit 1
  fi
  echo "  OK no warn: $case_name"
}

assert_foreshadow_warn() {
  local case_name="$1"
  local body="$2"
  local root output
  root=$(setup_fixture "$case_name" "$body")
  output=$(run_hook "$root" || true)
  if ! echo "$output" | grep -q '检测到过期或异常的伏笔条目'; then
    echo "FAIL: $case_name should emit overdue/abnormal foreshadow warning"
    echo "Output:"
    echo "$output"
    exit 1
  fi
  echo "  OK warn: $case_name"
}

assert_no_foreshadow_warn "header-only" ""

plain_header_root="$TMP_DIR/plain-header"
mkdir -p "$plain_header_root/.claude/hooks/lib" "$plain_header_root/book/追踪" "$plain_header_root/book/正文" "$plain_header_root/book/设定" "$plain_header_root/book/大纲"
cp "$HOOK_FILE" "$plain_header_root/.claude/hooks/detect-story-gaps.sh"
cp "$COMMON_FILE" "$plain_header_root/.claude/hooks/lib/common.sh"
chmod +x "$plain_header_root/.claude/hooks/detect-story-gaps.sh"
cat > "$plain_header_root/book/追踪/伏笔.md" <<'EOF_PLAIN_HEADER'
# 伏笔追踪

| ID | 名称 | 埋下 | 回收 | 状态 | 备注 |
|----|------|------|------|------|------|
| F001 | 玉佩 | 第1章 | 第20章 | 已埋 | ok |
EOF_PLAIN_HEADER
plain_header_output=$(run_hook "$plain_header_root" || true)
if echo "$plain_header_output" | grep -q '伏笔'; then
  echo "FAIL: plain-header should not emit foreshadow warning"
  echo "Output:"
  echo "$plain_header_output"
  exit 1
fi
echo "  OK no warn: plain-header"

assert_no_foreshadow_warn "normal-open-planted" "| F002 | 正常开放伏笔 | 第1章 | 第20章 | 已埋 | 高 |"
assert_no_foreshadow_warn "closed-recovered" "| F003 | 已回收伏笔 | 第1章 | 第3章 | 已回收 | 低 |"
assert_no_foreshadow_warn "closed-abandoned" "| F006 | 已放弃伏笔 | 第1章 | 第3章 | 放弃 | 低 |"
assert_foreshadow_warn "overdue" "| F004 | 过期伏笔 | 第1章 | 第2章 | 已过期 | 高 |"
assert_foreshadow_warn "retired-unplanted-status" "| F001 | 尚未真正埋设 | 第5章 | 第10章 | 未埋 | 中 |"
assert_foreshadow_warn "unknown-status" "| F005 | 异常状态 | 第1章 | 第2章 | 状态损坏 | 高 |"

# Ensure every protocol status is explicitly classified by the hook's awk classifier:
# either an explicit warn state (status == "X") or an explicit normal state (status != "X").
# The old second clause grepped PROTOCOL_FILE — the very file STATUS_ENUM was extracted
# from — so it always matched and the whole loop could never fail. A status added to the
# protocol without teaching the hook falls into the classifier's else branch and gets
# reported as 异常 on every SessionStart; that drift must turn this check red.
for state in $(echo "$STATUS_ENUM" | tr '/' ' '); do
  if ! grep -qF "status == \"$state\"" "$HOOK_FILE" \
    && ! grep -qF "status != \"$state\"" "$HOOK_FILE"; then
    echo "FAIL: protocol status not classified by hook: $state"
    echo "  add status == \"$state\" (warn) or status != \"$state\" (normal) to the 伏笔 awk in $HOOK_FILE"
    exit 1
  fi
done

echo ""
echo "OK: hook foreshadow detection warns only on overdue/abnormal states"

# ── 毒句式 / 兜底网 js↔py 正则与常量同步锁 ──────────────────────────────────────
# 写后正文网的确定性规则在 JS 共享核 story_hook_core.js 与 codex story_codex_hook.py 各有一份
# 同构实现。文案由 test-prose-net-parity.sh A 段 fixture 逐字 diff 锁；fixture 只覆盖部分字符类
# 备选与可选组，单端删一个备选字、加一个 `|X` 分支、改一个 flag，fixture 照样全绿。
# 这里把两端的常量表真的解析出来（JS 正则/字符串/数组字面量 vs py ast）逐项全等比对：
#   - 每条正则的正文逐字相等（加减任何分支/字符都红），标签与修法文案、顺序也在比对内；
#   - flags 全锁：JS 字面量 flags 逐字等于对照表登记值，py 的 re flags 等于「JS flags 去 g」；
#   - 两端 TOXIC_*/SOFT_PATTERNS/HARD_PATTERNS 与 _TOXIC_*/_NET_* 常量必须全部登记，单端新增即红。
# 之后用变异测试证明这把锁真能抓到单端漂移（旧版只 grep 规范串「是否出现」，末尾追加分支照样过）。
JS_CORE="$REPO_ROOT/skills/story-setup/references/templates/hooks/story_hook_core.js"
PY_HOOK="$REPO_ROOT/skills/story-setup/references/codex/hooks/story_codex_hook.py"
for file in "$JS_CORE" "$PY_HOOK"; do
  if [ ! -f "$file" ]; then
    echo "FAIL: required file not found: $file"
    exit 1
  fi
done
PYBIN=""
for cand in python3 python py; do
  if "$cand" -c "" >/dev/null 2>&1; then PYBIN="$cand"; break; fi
done
[ -n "$PYBIN" ] || { echo "FAIL: 需要 Python 解析 js↔py 常量表"; exit 1; }

REGEX_SYNC="$TMP_DIR/regex_sync.py"
cat > "$REGEX_SYNC" <<'PY'
import ast
import json
import re
import sys

# JS 常量名 -> (py 常量名, JS 正则字面量必须带的 flags)。flags 是完整锁：JS 端 flags 串必须逐字等于
# 这里的值；py 端 flags 必须等于「JS flags 去掉 g」（g 只是 JS 的迭代方式，py 用 finditer/search 等价）。
PAIRS = {
    "TOXIC_QUOTE_SPANS": ("_TOXIC_QUOTE_SPANS", "g"),
    "TOXIC_QUOTE_CHARS": ("_TOXIC_QUOTE_CHARS", None),
    "TOXIC_CLAUSE_BOUNDARY": ("_TOXIC_CLAUSE_BOUNDARY", None),
    "TOXIC_TAG_PARTICLES": ("_TOXIC_TAG_PARTICLES", None),
    "TOXIC_AFFIRM_PARTICLES": ("_TOXIC_AFFIRM_PARTICLES", None),
    "TOXIC_TRAILER_WINDOW": ("_TOXIC_TRAILER_WINDOW", None),
    "TOXIC_SENTENCE_PATTERNS": ("_TOXIC_SENTENCE_PATTERNS", "g"),
    "TOXIC_TRAILER_PATTERN": ("_TOXIC_TRAILER", ""),
    "TOXIC_TRAILER_SUMMARY_PATTERN": ("_TOXIC_TRAILER_SUMMARY", ""),
    "TOXIC_REVERSE_TAIL": ("_TOXIC_REVERSE_TAIL", ""),
    "TERMINAL": ("_NET_TERMINAL", None),
    "SOFT_PATTERNS": ("_NET_SOFT_PATTERNS", ""),
    "HARD_PATTERNS": ("_NET_HARD_PATTERNS", ""),
    "UNEXPANDED_SHELL_VAR": ("UNEXPANDED_SHELL_VAR", ""),
    "OUTLINE_MIN_CHARS": ("_OUTLINE_MIN_CHARS", None),
}
# 这两组前缀下的常量一律要登记进 PAIRS：单端新增一条毒句式/兜底网规则也算漂移。
JS_FAMILY = re.compile(r"^(TOXIC_[A-Z_]+|SOFT_PATTERNS|HARD_PATTERNS)$")
PY_FAMILY = re.compile(r"^(_TOXIC_[A-Z_]+|_NET_[A-Z_]+)$")
PY_FLAG = {"IGNORECASE": "i", "I": "i", "MULTILINE": "m", "M": "m", "DOTALL": "s", "S": "s",
           "UNICODE": "u", "U": "u", "ASCII": "a", "A": "a", "VERBOSE": "x", "X": "x"}


class JsParser:
    def __init__(self, text: str, pos: int):
        self.s = text
        self.i = pos

    def skip(self) -> None:
        s = self.s
        while self.i < len(s):
            if s[self.i] in " \t\r\n":
                self.i += 1
            elif s.startswith("//", self.i):
                self.i = s.index("\n", self.i)
            elif s.startswith("/*", self.i):
                self.i = s.index("*/", self.i) + 2
            else:
                return

    def value(self):
        self.skip()
        s, c = self.s, self.s[self.i]
        if c == "/":
            return self.regex()
        if c in "\"'":
            return self.string()
        if c == "[":
            self.i += 1
            items = []
            while True:
                self.skip()
                if s[self.i] == "]":
                    self.i += 1
                    return items
                items.append(self.value())
                self.skip()
                if s[self.i] == ",":
                    self.i += 1
        if s.startswith("new Set(", self.i):
            self.i += len("new Set(")
            inner = self.value()
            self.expect(")")
            return inner
        if s.startswith("Array.from(", self.i):
            self.i += len("Array.from(")
            inner = self.value()
            self.expect(")")
            return inner
        m = re.compile(r"\d+").match(s, self.i)
        if m:
            self.i = m.end()
            return int(m.group(0))
        raise SystemExit(f"regex-sync: 无法解析的 JS 常量值: {s[self.i:self.i + 40]!r}")

    def expect(self, ch: str) -> None:
        self.skip()
        if self.s[self.i] != ch:
            raise SystemExit(f"regex-sync: JS 常量期望 {ch!r}: {self.s[self.i:self.i + 40]!r}")
        self.i += 1

    def regex(self):
        s, i = self.s, self.i + 1
        in_class = False
        while True:
            c = s[i]
            if c == "\\":
                i += 2
                continue
            if c == "\n":
                raise SystemExit("regex-sync: JS 正则字面量未闭合")
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
            i += 1
        body = s[self.i + 1:i]
        m = re.compile(r"[a-z]*").match(s, i + 1)
        self.i = m.end()
        return ("re", body, m.group(0))

    def string(self):
        s, q, i = self.s, self.s[self.i], self.i + 1
        while s[i] != q:
            i += 2 if s[i] == "\\" else 1
        raw = s[self.i + 1:i]
        self.i = i + 1
        if q == "'":
            raw = raw.replace("\\'", "'").replace('"', '\\"')
        return json.loads('"' + raw + '"')


def js_constants(path: str) -> dict:
    text = open(path, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"^const ([A-Z_]+) = ", text, re.M):
        name = m.group(1)
        if name in PAIRS or JS_FAMILY.match(name):
            out[name] = JsParser(text, m.end()).value()
    return out


def py_value(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [py_value(x) for x in node.elts]
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "set" and len(node.args) == 1:
            return py_value(node.args[0])
        if isinstance(func, ast.Attribute) and func.attr == "compile" and isinstance(func.value, ast.Name) and func.value.id == "re":
            flags_node = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "flags"), None)
            return ("re", py_value(node.args[0]), "".join(sorted(py_flags(flags_node))))
    raise SystemExit(f"regex-sync: 无法解析的 py 常量值: {ast.dump(node)[:80]}")


def py_flags(node) -> set:
    if node is None:
        return set()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return py_flags(node.left) | py_flags(node.right)
    if isinstance(node, ast.Attribute) and node.attr in PY_FLAG:
        return {PY_FLAG[node.attr]}
    raise SystemExit(f"regex-sync: 无法解析的 py 正则 flags: {ast.dump(node)[:80]}")


def py_constants(path: str) -> dict:
    tree = ast.parse(open(path, encoding="utf-8").read())
    wanted = {py for py, _ in PAIRS.values()}
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            name, value = node.target.id, node.value
        else:
            continue
        if name in wanted or PY_FAMILY.match(name):
            out[name] = py_value(value)
    return out


def regexes(value):
    if isinstance(value, tuple) and value and value[0] == "re":
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from regexes(item)


def strip_g(value):
    if isinstance(value, tuple) and value and value[0] == "re":
        return ("re", value[1], "".join(sorted(set(value[2]) - {"g"})))
    if isinstance(value, list):
        return [strip_g(v) for v in value]
    return value


def main(js_path: str, py_path: str) -> int:
    js, py = js_constants(js_path), py_constants(py_path)
    errors = []
    for name in sorted(set(js) - set(PAIRS)):
        errors.append(f"JS 常量 {name} 未登记到 js↔py 对照表（单端新增规则）")
    known_py = {p for p, _ in PAIRS.values()}
    for name in sorted(set(py) - known_py):
        errors.append(f"py 常量 {name} 未登记到 js↔py 对照表（单端新增规则）")
    for js_name, (py_name, js_flags) in PAIRS.items():
        if js_name not in js:
            errors.append(f"JS 缺常量 {js_name}")
            continue
        if py_name not in py:
            errors.append(f"py 缺常量 {py_name}")
            continue
        jv, pv = js[js_name], py[py_name]
        if js_flags is not None:
            found = list(regexes(jv))
            if not found:
                errors.append(f"{js_name} 里没抽到正则字面量")
            for _, body, flags in found:
                if flags != js_flags:
                    errors.append(f"{js_name} 的 JS 正则 flags 应为 {js_flags!r}，实为 {flags!r}：/{body[:30]}…/")
        if strip_g(jv) != pv:
            errors.append(f"{js_name} ↔ {py_name} 不一致：\n    js={strip_g(jv)!r}\n    py={pv!r}")
    if errors:
        for e in errors:
            sys.stdout.buffer.write(f"FAIL: 毒句式/兜底网 js↔py 漂移 — {e}\n".encode("utf-8"))
        return 1
    n = sum(len(list(regexes(v))) for v in js.values())
    sys.stdout.buffer.write(f"regex-sync: {len(PAIRS)} 组常量、{n} 条正则 js↔py 逐字相等（含 flags）\n".encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
PY

toxic_fail=0
"$PYBIN" "$REGEX_SYNC" "$JS_CORE" "$PY_HOOK" || toxic_fail=1

# 变异测试：每种单端漂移都必须让上面的比对变红；无关改动（数组里加注释）不能误报。
mutate() { # $1 源文件 $2 输出 $3 旧串 $4 新串（旧串须恰好出现一次）
  "$PYBIN" - "$1" "$2" "$3" "$4" <<'PY'
import sys
src, dst, old, new = sys.argv[1:5]
text = open(src, encoding="utf-8").read()
if text.count(old) != 1:
    sys.stderr.buffer.write(f"mutation anchor not unique ({text.count(old)}): {old}\n".encode("utf-8"))
    sys.exit(2)
open(dst, "w", encoding="utf-8", newline="").write(text.replace(old, new))
PY
}
expect_mutation() { # $1 描述 $2 期望(fail|pass) $3 js|py $4 旧串 $5 新串
  local js="$JS_CORE" py="$PY_HOOK" out="$TMP_DIR/mutant" rc=0
  if [ "$3" = js ]; then mutate "$JS_CORE" "$out.js" "$4" "$5" || { echo "FAIL: 变异锚点失效：$1"; toxic_fail=1; return; }; js="$out.js"
  else mutate "$PY_HOOK" "$out.py" "$4" "$5" || { echo "FAIL: 变异锚点失效：$1"; toxic_fail=1; return; }; py="$out.py"; fi
  "$PYBIN" "$REGEX_SYNC" "$js" "$py" >/dev/null 2>&1 || rc=$?
  if [ "$2" = fail ] && [ "$rc" -eq 0 ]; then echo "FAIL: 同步锁没抓到单端漂移：$1"; toxic_fail=1; fi
  if [ "$2" = pass ] && [ "$rc" -ne 0 ]; then echo "FAIL: 同步锁误报无关改动：$1"; toxic_fail=1; fi
}
expect_mutation "JS 句式正则末尾追加分支" fail js '[却但偏]/g, "voice-contrast"' '[却但偏]|X/g, "voice-contrast"'
expect_mutation "py 预告收尾正则末尾追加分支" fail py '即将(?:开始|来临|降临)")' '即将(?:开始|来临|降临)|X")'
expect_mutation "JS 正则加 i flag" fail js '即将(?:开始|来临|降临)/
' '即将(?:开始|来临|降临)/i
'
expect_mutation "JS 句式正则去掉 g flag" fail js '[却但偏]/g, "voice-contrast"' '[却但偏]/, "voice-contrast"'
expect_mutation "py 正则加 IGNORECASE" fail py '[却但偏]"), "voice-contrast"' '[却但偏]", re.IGNORECASE), "voice-contrast"'
expect_mutation "JS 分句边界集多一个字符" fail js 'const TOXIC_CLAUSE_BOUNDARY = new Set(Array.from("' 'const TOXIC_CLAUSE_BOUNDARY = new Set(Array.from("X'
expect_mutation "JS 单端新增一条毒句式常量" fail js 'const TOXIC_REVERSE_TAIL = ' 'const TOXIC_EXTRA_PATTERN = /x/
const TOXIC_REVERSE_TAIL = '
expect_mutation "py 修法文案漂移" fail py '"negation-parade", "「没有…，没有…」排比删到只剩一个或全删' '"negation-parade", "「没有…，没有…」排比删到只剩一个'
expect_mutation "py 窗口 600→500" fail py '_TOXIC_TRAILER_WINDOW = 600' '_TOXIC_TRAILER_WINDOW = 500'
expect_mutation "JS 兜底网数组里加一行注释（无关改动）" pass js 'const HARD_PATTERNS = [
' 'const HARD_PATTERNS = [
  // 无关注释
'

# 欠账门的豁免标记与门文案 js↔py 同步。Claude bash 侧前置门（guard-outline-before-prose.sh）
# 的判定与文案由 test-prose-net-parity.sh D 段按真实写入逐场景锁。
GATE_SYNC=(
  '<!--[ \t]*去味[ \t]*(：|:)[ \t]*跳过[ \t]*-->'
  '未清毒句式欠账'
  '<!-- 去味:跳过 --> 后重试'
)
for needle in "${GATE_SYNC[@]}"; do
  for file in "$JS_CORE" "$PY_HOOK"; do
    if ! grep -Fq -- "$needle" "$file"; then
      echo "FAIL: 欠账门规范串缺失/漂移 — 「${needle}」未出现在 $(basename "$file")"
      toxic_fail=1
    fi
  done
done
# storyctl chapter check 的豁免判定与 hooks 同一个标记语法（作者照一种写法加标记，两边都认）。
STORYCTL="$REPO_ROOT/skills/story-long-write/scripts/storyctl.py"
if ! grep -Fq -- "${GATE_SYNC[0]}" "$STORYCTL"; then
  echo "FAIL: 豁免标记语法漂移 — 「${GATE_SYNC[0]}」未出现在 storyctl.py"
  toxic_fail=1
fi
if [ "$toxic_fail" -ne 0 ]; then
  exit 1
fi

echo "OK: 毒句式正则、常量表与欠账门标记/文案 js↔py↔storyctl 逐字同步"
