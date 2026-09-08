#!/usr/bin/env python3
"""卷纲取段器 —— 让「不整读卷纲」成立。

按声明作用域选取卷级、单元级和批次材料；未声明的旧段保守纳入并告警。

段头约定（每个 ## / ### / #### 标题的**下一行非空行**）：

    > 作用域：卷级常任
    > 作用域：单元级 D1-03
    > 作用域：批次底稿 D1-03｜状态：在用
    > 作用域：批次底稿 D1-02｜状态：已退役

退役行（行内覆盖）：以 `⊘` 起头的列表行 / 表格行，默认过滤。

用法：
    outline_view.py --toc   卷纲.md
    outline_view.py --unit D1-03 卷纲.md
    outline_view.py --contract 卷纲.md
    outline_view.py --check 卷纲.md
    任意子命令加 --history 连退役行一起输出
"""
import argparse
import io
import re
import sys

HEADING = re.compile(r"^(#{2,4})\s+(.*\S)\s*$")
SCOPE = re.compile(r"^>\s*作用域[：:]\s*(.+?)\s*$")
RETIRED_LINE = re.compile(r"^\s*(?:[-*]\s*)?⊘|^\s*\|\s*⊘")
# 单元块内不该出现的全卷字样——出现即说明这条常任规则放错了地方
LEAK = re.compile(r"全卷常任|全程生效|全卷生效|本单元起常任|自 ?[LD]\d+-\d+ ?起生效")
# 指向卷级的指针行不算泄漏：单元块可以引用常任规则，不可以复述它
POINTER = re.compile(r"全卷常任裁定|已提为卷级|不复读|规则本身见|见「全卷")
UNIT_IN_TITLE = re.compile(r"(?<![\w-])([LD]\d+-\d+|U\d+)(?![\w-])")
# 批次底稿里出现跨章祈使＝这条约束在写作期还有效，而写作档不给底稿 → 必须下沉
IMPERATIVE = re.compile(r"全程不许|一律不许|往后任何章|此后不再|往后每|从此不|终局前不")
CH_RANGE = re.compile(r"章节范围[：:]\s*第\s*(\d+)\s*[-–—~至]\s*(\d+)\s*章")
ARC_ROW = re.compile(r"^\|\s*(\d+)\s*\|")


def read(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return handle.read()


class Section:
    __slots__ = ("level", "title", "start", "end", "scope", "kind",
                 "unit", "status", "lines")

    def __init__(self, level, title, start):
        self.level = level
        self.title = title
        self.start = start          # 标题行号（0 基）
        self.end = None
        self.scope = None           # 原始作用域串，None ＝ 未声明
        self.kind = None            # 卷级常任 / 单元级 / 批次底稿
        self.unit = None
        self.status = "在用"
        self.lines = []


def parse(text):
    lines = text.split("\n")
    sections = []
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        match = HEADING.match(line)
        if match:
            if sections:
                sections[-1].end = index
            sections.append(Section(len(match.group(1)), match.group(2), index))
    if sections:
        sections[-1].end = len(lines)
    for section in sections:
        section.lines = lines[section.start:section.end]
        for candidate in section.lines[1:]:
            if not candidate.strip():
                continue
            scope_match = SCOPE.match(candidate)
            if scope_match:
                section.scope = scope_match.group(1)
            break
        if section.scope:
            head = section.scope.split("｜")[0].strip()
            if head == "卷级常任":
                section.kind = "卷级常任"
            elif re.fullmatch(r"单元级(?:\s+[A-Za-z][\w-]*)?", head):
                section.kind = "单元级"
            elif re.fullmatch(r"批次底稿(?:\s+[A-Za-z][\w-]*)?", head):
                section.kind = "批次底稿"
            found = re.search(r"^(?:单元级|批次底稿)\s+([A-Za-z][\w-]*)$", head)
            if found:
                section.unit = found.group(1)
            if "已退役" in section.scope:
                section.status = "已退役"
        if section.unit is None:
            found = re.search(r"剧情单元\s+([A-Za-z][\w-]*)", section.title) or UNIT_IN_TITLE.search(section.title)
            if found:
                section.unit = found.group(1)
        if section.unit is None and section.scope is None:
            for line in section.lines[1:]:
                field = re.match(r"^\s*[-*+]\s*单元ID\s*[：:]\s*([A-Za-z][\w-]*)\s*$", line.replace("**", ""))
                if field:
                    section.unit = field.group(1)
                    break
    return lines, sections


def strip_retired(block_lines, keep_history):
    if keep_history:
        return block_lines
    return [line for line in block_lines if not RETIRED_LINE.match(line)]


def unit_chapter_range(sections, unit):
    for section in sections:
        if section.unit == unit and section.kind == "单元级" and "剧情单元" in section.title:
            for line in section.lines:
                found = CH_RANGE.search(line)
                if found:
                    return int(found.group(1)), int(found.group(2))
    return None


def slice_arc(section, span):
    """情绪弧线这类逐章表：只留本单元章区间的行，表头与说明照留。"""
    if span is None:
        return section.lines
    low, high = span
    kept = []
    for line in section.lines:
        row = ARC_ROW.match(line)
        if row and not (low <= int(row.group(1)) <= high):
            continue
        kept.append(line)
    return kept


def emit(sections, chosen, span, keep_history, note, preamble):
    out = ["\n".join(strip_retired(preamble, keep_history)).rstrip()] if preamble else []
    for section in sections:
        if section not in chosen:
            continue
        body = section.lines
        if "情绪弧线" in section.title or "排班" in section.title:
            body = slice_arc(section, span)
        body = strip_retired(body, keep_history)
        out.append("\n".join(body).rstrip())
    text = "\n\n".join(out)
    sys.stdout.write(text + "\n")
    if note:
        sys.stderr.write(note + "\n")


def cmd_toc(sections):
    print("%-3s %-6s %-9s %-8s %-46s %s" %
          ("#", "行", "作用域", "单元", "段", "字符"))
    for number, section in enumerate(sections, 1):
        size = sum(len(line) + 1 for line in section.lines)
        print("%-3d %-6d %-9s %-8s %-46s %d" %
              (number, section.start + 1, section.kind or "**未声明**",
               (section.unit or "-") + ("(退)" if section.status == "已退役" else ""),
               section.title[:44], size))


def cmd_check(sections, strict=False):
    problems = []
    warnings = []
    for section in sections:
        if section.kind == "批次底稿":
            for offset, line in enumerate(section.lines):
                if IMPERATIVE.search(line):
                    warnings.append(
                        ("W1", "第%d行" % (section.start + offset + 1),
                         "批次底稿里有跨章祈使，写作档不给底稿——确认已下沉到单元级段或细纲：%s"
                         % line.strip()[:52]))
    for section in sections:
        where = "第%d行「%s」" % (section.start + 1, section.title[:36])
        if section.scope is None:
            (problems if strict else warnings).append(("E1" if strict else "W2", where, "缺「> 作用域：」声明行；旧段保守纳入"))
            continue
        if section.kind is None:
            problems.append(("E2", where, "作用域值不认识：%s" % section.scope))
        if section.kind in ("单元级", "批次底稿") and section.unit is None:
            problems.append(("E3", where, "单元级/批次底稿段未标单元ID"))
        if section.kind in ("单元级", "批次底稿"):
            for offset, line in enumerate(section.lines):
                if LEAK.search(line) and not POINTER.search(line):
                    problems.append(
                        ("E4", "第%d行" % (section.start + offset + 1),
                         "单元块内出现全卷字样，常任规则放错了位置：%s"
                         % line.strip()[:56]))
    for code, where, message in problems + warnings:
        print("%s %s %s" % (code, where, message))
    print("---")
    print("段 %d ／ 问题 %d ／ 告警 %d（告警不阻断，逐条人工判断）"
          % (len(sections), len(problems), len(warnings)))
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("path")
    parser.add_argument("--toc", action="store_true")
    parser.add_argument("--unit")
    parser.add_argument("--contract", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--strict", action="store_true", help="新建卷纲校验：缺作用域也视为错误")
    parser.add_argument("--stage", choices=["outline", "write"], default="outline",
                        help="outline＝排纲档（带在用批次底稿）；"
                             "write＝写作档（只要卷级常任＋单元级，底稿一概不给）")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    try:
        lines, sections = parse(read(args.path))
    except (OSError, UnicodeError) as error:
        sys.stderr.write(f"无法读取卷纲：{error}\n")
        return 2
    if not sections:
        sys.stderr.write("卷纲里没有 ## 段，路径对不对？\n")
        return 2

    if args.toc:
        cmd_toc(sections)
        return 0
    if args.check:
        return cmd_check(sections, args.strict)

    invalid = [s for s in sections if s.scope and
               (s.kind is None or (s.kind != "卷级常任" and s.unit is None))]
    if invalid:
        sys.stderr.write("作用域声明无效，先运行 --check 修正\n")
        return 1
    active = [s for s in sections if args.history or s.status != "已退役"]
    permanent = [s for s in active if s.kind == "卷级常任"]
    undeclared = [s for s in active if s.scope is None]
    note = ("%d 段未声明作用域，已保守纳入；用 --check 查看" % len(undeclared)) if undeclared else None
    preamble = lines[:sections[0].start]
    if args.contract:
        emit(sections, set(permanent + undeclared), None, args.history, note, preamble)
        return 0

    if args.unit:
        unit = args.unit
        owned = [s for s in active if s.unit == unit]
        if not owned:
            sys.stderr.write(
                "找不到单元 %s —— 不静默降级。核对单元ID，或先补卷纲。\n" % unit)
            return 1
        if args.stage == "write":
            # 写作档不给批次底稿：它是排纲期的工作底稿，其中有写作期约束力的条目
            # 必须已经下沉到单元级段或细纲（见 artifact-protocols.md 段位契约纪律④）
            live = [s for s in owned if s.kind == "单元级"]
        else:
            live = [s for s in owned
                    if s.kind == "单元级"
                    or s.kind == "批次底稿"]
        chosen = set(permanent + live + undeclared)
        span = unit_chapter_range(active, unit)
        emit(sections, chosen, span, args.history, note, preamble)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
