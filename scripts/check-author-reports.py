#!/usr/bin/env python3
"""守卫：给作者看的报告模板里不许出现工程黑话。

只检查紧跟在 <!-- author-report --> 标记行后面的围栏块（其余 skill 指令不管，避免误报）。
围栏本身用普通的 ```md：信息串写成 author-report 时模型会把围栏原样回给作者，所以旧写法直接报错。
检查内容：
- 已知内部字段/状态名、reviewer 名、严重度代号、Gate 字母、PASS/FAIL；
- 脚本/配置文件名（.py/.js/.sh/.json/...）、命令行 flag、snake_case 与 kebab-case 标识符
  （/story-xxx、$story-xxx 这类作者要敲的命令除外）；
- 裸编号（F003、BP001、REL-001、L1-3）——编号必须挂故事标签：「描述（ID）」或「ID（描述）」。
static-check.py 的 author-report 检查调用本文件的 check_block，两处只有这一份规则。
块内最后一个非空行若以「技术备注：」开头，可承载执行路径等工程细节，不受上述检查；
技术备注只能有一行且必须在块尾。

REQUIRED 里的文件必须至少有一个 author-report 块，防止模板标记被悄悄删掉。

用法：python3 scripts/check-author-reports.py [--self-test]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 作者记忆回执不在此列：整条回复就是模板两行，写成围栏块时模型会把围栏原样回给作者（实测 2/2），
# 所以 author-memory.md 用行内示例描述回执。
REQUIRED = (
    "skills/story-import/SKILL.md",
    "skills/story-review/SKILL.md",
    "skills/story-deslop/SKILL.md",
    "skills/story-short-analyze/SKILL.md",
    "skills/story-long-scan/SKILL.md",
    "skills/story-short-scan/SKILL.md",
    "skills/story-cover/SKILL.md",
)

TAIL_PREFIX = "技术备注："

KNOWN_TOKENS = (
    "Requested Mode", "Effective Mode", "Rubric Source", "Severity Counts", "Fallback:",
    "NOT_RUN", "APPROVE", "CONCERNS", "REJECT", "PASS", "FAIL", "SKIP",
    "Author Memory Receipt",
)

CHECKS = (
    ("已知内部名", re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(t) for t in KNOWN_TOKENS) + r")(?![A-Za-z])")),
    ("脚本/配置文件名", re.compile(r"[\w.-]+\.(?:py|js|mjs|cjs|sh|ts|json|jsonl|toml|ya?ml)\b")),
    ("命令行 flag", re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")),
    ("snake_case 字段名", re.compile(r"(?<![\w])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")),
    ("kebab-case 标识符", re.compile(r"(?<![\w/$-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")),
    ("英文工程词", re.compile(
        r"(?i)(?<![A-Za-z])(?:state|schema|agents?|reviewers?|rubric|prompt|hooks?|fallback|pipeline|stage|tier|token"
        r"|commit|verdict|severity|discard|borderline|invalid|internal|pass|fail|under|over|tracking|revision"
        r"|checkpoint|segment|delta|Constraint Lock|Notice)(?![A-Za-z])"
    )),
    ("内部清单名", re.compile(r"安全七检|七检|供给自查|供给单|内带|用户带|二档|三档|收编|契约检查器|状态码|追踪事务")),
    ("严重度代号", re.compile(r"(?<![A-Za-z0-9])S[1-4](?![0-9])")),
    ("Gate 名", re.compile(r"\bGate\b|\d\s*Gate")),
)

_ID = r"(?:[A-Z]{1,3}\d?-?\d{2,}|[EFL]\d+(?:-\d+)?)"
RAW_ID = re.compile(r"(?<![A-Za-z0-9])" + _ID + r"(?![A-Za-z0-9])")
# 编号必须挂故事标签，两种写法都算：「描述（ID）」与「ID（描述）」。
LABELED_ID = re.compile(
    r"\S（" + _ID + r"(?:[、，,]\s*" + _ID + r")*）"
    r"|(?<![A-Za-z0-9])" + _ID + r"(?:[、，,]\s*" + _ID + r")*\s*[（(][^）)]*[^\sA-Za-z0-9（(）)][^）)]*[）)]"
)

FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\s`]*)")
MARKER = "<!-- author-report -->"
LEGACY_INFO = "author-report"


def author_blocks(text: str):
    """产出 (起始行号, 块内行列表)。"""
    lines = text.splitlines()
    i = 0
    previous = ""
    while i < len(lines):
        m = FENCE_OPEN.match(lines[i])
        if not m:
            if lines[i].strip():
                previous = lines[i].strip()
            i += 1
            continue
        fence = m.group(2)
        marked = previous == MARKER
        start = i
        i += 1
        body = []
        while i < len(lines) and not lines[i].strip().startswith(fence):
            body.append(lines[i])
            i += 1
        i += 1
        previous = ""
        if marked:
            yield start + 2, body


def legacy_fences(text: str) -> list[int]:
    """信息串写成 author-report 的旧围栏（行号从 1 起）。"""
    return [
        k + 1 for k, line in enumerate(text.splitlines())
        if (m := FENCE_OPEN.match(line)) and m.group(3) == LEGACY_INFO
    ]


def check_block(body: list[str]) -> list[tuple[int, str]]:
    errors: list[tuple[int, str]] = []
    nonempty = [k for k, line in enumerate(body) if line.strip()]
    last = nonempty[-1] if nonempty else -1
    for k, line in enumerate(body):
        stripped = line.strip()
        if stripped.startswith(TAIL_PREFIX):
            if k != last:
                errors.append((k, "技术备注只能是块内最后一行"))
            continue
        for label, pattern in CHECKS:
            hit = pattern.search(line)
            if hit:
                errors.append((k, f"{label}「{hit.group(0)}」"))
        masked = LABELED_ID.sub("", line)
        hit = RAW_ID.search(masked)
        if hit:
            errors.append((k, f"裸编号「{hit.group(0)}」（写成「故事描述（ID）」或「ID（故事描述）」）"))
    return errors


def check_text(text: str) -> list[tuple[int, str]]:
    out = []
    for start, body in author_blocks(text):
        for k, msg in check_block(body):
            out.append((start + k, msg))
    return out


def run() -> int:
    failures = []
    files = sorted((ROOT / "skills").rglob("*.md"))
    marked = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        if any(True for _ in author_blocks(text)):
            marked.add(rel)
        for lineno, msg in check_text(text):
            failures.append(f"{rel}:{lineno}: {msg}")
        for lineno in legacy_fences(text):
            failures.append(f"{rel}:{lineno}: 围栏信息串不能写 author-report（模型会原样回给作者），改成上一行 {MARKER}、围栏用 ```md")
    for rel in REQUIRED:
        if rel not in marked:
            failures.append(f"{rel}: 缺少 {MARKER} 标记的报告模板块")
    if failures:
        print("作者报告模板含工程黑话：")
        for f in failures:
            print("  " + f)
        return 1
    print(f"OK: {len(marked)} 个文件的作者报告模板不含工程黑话")
    return 0


def self_test() -> int:
    bad = [
        "字数口径：visible_chars_v1",
        "运行 tracking_commit.py check 通过",
        "要接受当前长度吗？回复 accept-current-length",
        "severity: S2",
        "7 Gate 中 4 个有问题",
        "伏笔 F007 未回收",
        "Fallback: none",
        "加 --book-root",
        "追踪：唯一结构化 state + 派生快照",
        "伏笔 L1-3 待定",
        "按安全七检过了一遍",
        "字数 borderline，要不要 discard",
        "Constraint Lock 已生效",
    ]
    good = [
        "下一步：说「日更」就从第 7 章接着写；也可运行 `/story-long-write`。",
        "还没收的线：玉佩的来历（F003）",
        "伏笔 F057（那封信的去处）已经收回",
        "第一卷第三个单元（L1-3）写完了",
        "## 必须改（2 处）",
        "",
    ]
    ok = True
    for line in bad:
        text = f"{MARKER}\n```md\n{line}\n结尾\n```\n"
        if not check_text(text):
            print(f"self-test: 未拦截 {line!r}")
            ok = False
    for line in good:
        text = f"{MARKER}\n```md\n{line}\n```\n"
        if check_text(text):
            print(f"self-test: 误报 {line!r}: {check_text(text)}")
            ok = False
    tail_ok = MARKER + "\n```md\n正文\n技术备注：Mode full→solo · Fallback missing agents -> solo\n```\n"
    if check_text(tail_ok):
        print(f"self-test: 块尾技术备注被误报 {check_text(tail_ok)}")
        ok = False
    tail_bad = MARKER + "\n```md\n技术备注：S1\n正文\n```\n"
    if not check_text(tail_bad):
        print("self-test: 未拦截非块尾技术备注")
        ok = False
    plain = "```text\ntracking_commit.py check\n```\n"
    if check_text(plain):
        print("self-test: 误检了非 author-report 块")
        ok = False
    unmarked_after_marked = MARKER + "\n```md\n正文\n```\n\n```text\ntracking_commit.py\n```\n"
    if check_text(unmarked_after_marked):
        print("self-test: 标记只该管紧随其后的一个围栏")
        ok = False
    if legacy_fences("```author-report\n正文\n```\n") != [1]:
        print("self-test: 未拦截旧的 author-report 信息串")
        ok = False
    print("self-test OK" if ok else "self-test FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    sys.exit(run())
