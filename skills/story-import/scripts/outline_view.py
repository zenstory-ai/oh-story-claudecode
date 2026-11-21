#!/usr/bin/env python3
"""卷纲取段器 —— 让「不整读卷纲」成立（同步到 story-import）。

按声明作用域选取全卷段与剧情段；未声明的旧段保守纳入并告警。支持两种写法：
1. 标题尾部注释（0.10 起）：`## 本卷故事线 <!-- 全卷 -->`、`### 第一段剧情：退婚风波 <!-- L1-01 -->`
   未写注释的子标题跟随上级剧情段；文件里只要有标题尾注释，其余未标段视为全卷。
2. 旧写法（标题下首行非空行）：`> 作用域：卷级常任` / `> 作用域：单元级 D1-03`

以 `⊘` 起头的列表行 / 表格行默认过滤，加 `--history` 连退役段/行一并输出。

用法：
    outline_view.py --toc   卷纲.md
    outline_view.py --unit D1-03 卷纲.md
    outline_view.py --chapter 12 卷纲.md
    outline_view.py --contract 卷纲.md
    outline_view.py --check [--strict] 卷纲.md
"""
import argparse
import io
import re
import sys

HEADING = re.compile(r"^(#{2,4})\s+(.*\S)\s*$")
SCOPE = re.compile(r"^>\s*作用域[：:]\s*(.+?)\s*$")
TRAILING = re.compile(r"^(.*?)\s*<!--\s*(.*?)\s*-->\s*$")
RETIRED_LINE = re.compile(r"^\s*(?:[-*]\s*)?⊘|^\s*\|\s*⊘")
UNIT_IN_TITLE = re.compile(r"(?<![\w-])([LD]\d+-\d+|U\d+)(?![\w-])")
CH_RANGE = re.compile(r"章节范围[：:]\s*第\s*(\d+)\s*[-–—~至]\s*(\d+)\s*章")
ARC_ROW = re.compile(r"^\|\s*第?\s*(\d+)\s*章?\s*\|")
UNIT_ID = re.compile(r"(?<![\w-])([A-Za-z]\d+-\d+|U\d+)(?![\w-])")

# 卷纲、细纲按名读取字段的新旧叫法（新名在前，旧名照认）。
UNIT_FIELD_NAMES = {
    "单元情绪引擎": ("这段让读者图什么", "单元情绪引擎"),
    "单元节拍/章功能分配": ("这段怎么排", "这段怎么走", "单元节拍/章功能分配", "单元节拍／章功能分配"),
}
CHAPTER_UNIT_FIELDS = ("属于哪段剧情", "单元ID/位置")


def classify(section):
    """作用域串 → kind / unit / status。新旧叫法都认：全卷＝卷级常任，单写编号＝单元级。"""
    parts = [part.strip() for part in re.split(r"[｜|]", section.scope)]
    head = parts[0]
    if head in ("卷级常任", "全卷"):
        section.kind = "卷级常任"
    elif re.fullmatch(r"单元级(?:\s+[A-Za-z][\w-]*)?", head):
        section.kind = "单元级"
        found = re.search(r"^单元级\s+([A-Za-z][\w-]*)$", head)
        if found:
            section.unit = found.group(1)
    elif section.inline and re.fullmatch(r"[A-Za-z][\w-]*", head) and UNIT_ID.fullmatch(head):
        section.kind = "单元级"
        section.unit = head
    if any("已退役" in part for part in parts):
        section.status = "已退役"


def is_unit_card(section):
    """剧情段的卡头：标题含「剧情单元」「段剧情」，或本段自己写着章节范围。"""
    if section.kind != "单元级" or section.inherited:
        return False
    return ("剧情单元" in section.title or "段剧情" in section.title
            or any(CH_RANGE.search(line) for line in section.lines))


def field_value(text, names):
    for name in names:
        pattern = re.compile(rf"^[ \t>]*[-*+][ \t]*\*{{0,2}}{re.escape(name)}\*{{0,2}}[ \t]*[：:][ \t]*(.*)$", re.M)
        match = pattern.search(text or "")
        if match:
            return match.group(1).strip()
    return None


def unit_id_of(value):
    if not value:
        return None
    found = UNIT_ID.search(value)
    return found.group(1) if found else None


def chapter_unit(outline_text):
    return unit_id_of(field_value(outline_text, CHAPTER_UNIT_FIELDS))


def unit_for_chapter(sections, chapter):
    for section in sections:
        if section.status == "已退役" or not section.unit or not is_unit_card(section):
            continue
        for line in section.lines:
            found = CH_RANGE.search(line)
            if found:
                if int(found.group(1)) <= chapter <= int(found.group(2)):
                    return section.unit
                break
    return None


def chapter_unit_in_volume(volume_text, chapter):
    try:
        _, sections = parse(volume_text or "")
    except Exception:  # noqa: BLE001
        return None
    return unit_for_chapter(sections, chapter)


def read(path):
    with io.open(path, encoding="utf-8-sig") as handle:
        return handle.read()


class Section:
    __slots__ = ("level", "title", "start", "end", "scope", "kind",
                 "unit", "status", "lines", "inline", "inherited")

    def __init__(self, level, title, start):
        self.level = level
        self.title = title
        self.start = start
        self.end = None
        self.scope = None
        self.kind = None  # 卷级常任 / 单元级
        self.unit = None
        self.status = "在用"
        self.lines = []
        self.inline = False
        self.inherited = False


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
        trailing = TRAILING.match(section.title)
        if trailing and trailing.group(2):
            section.title = trailing.group(1).strip() or section.title
            section.scope = trailing.group(2)
            section.inline = True
        else:
            for candidate in section.lines[1:]:
                if not candidate.strip():
                    continue
                scope_match = SCOPE.match(candidate)
                if scope_match:
                    section.scope = scope_match.group(1)
                break
        if section.scope:
            classify(section)
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
    stack = []
    for section in sections:
        while stack and stack[-1].level >= section.level:
            stack.pop()
        parent = stack[-1] if stack else None
        if section.scope is None and parent is not None and parent.inline and parent.kind == "单元级" and parent.unit:
            section.scope, section.kind, section.unit, section.status = parent.scope, parent.kind, parent.unit, parent.status
            section.inline = section.inherited = True
        stack.append(section)
    if any(section.inline for section in sections):
        for section in sections:
            if section.scope is None and section.unit is None:
                section.scope = "全卷"
                section.inline = True
                classify(section)
    return lines, sections


def strip_retired(block_lines, keep_history):
    return block_lines if keep_history else [line for line in block_lines if not RETIRED_LINE.match(line)]


def unit_chapter_range(sections, unit):
    for section in sections:
        if section.unit == unit and is_unit_card(section):
            for line in section.lines:
                found = CH_RANGE.search(line)
                if found:
                    return int(found.group(1)), int(found.group(2))
    return None


def slice_arc(section, span):
    if span is None:
        return section.lines
    low, high = span
    return [line for line in section.lines
            if not ((row := ARC_ROW.match(line)) and not (low <= int(row.group(1)) <= high))]


def emit(sections, chosen, span, keep_history, note, preamble):
    out = ["\n".join(strip_retired(preamble, keep_history)).rstrip()] if preamble else []
    for section in sections:
        if section not in chosen:
            continue
        body = slice_arc(section, span) if ("情绪弧线" in section.title or "排班" in section.title) else section.lines
        out.append("\n".join(strip_retired(body, keep_history)).rstrip())
    sys.stdout.write("\n\n".join(out) + "\n")
    if note:
        sys.stderr.write(note + "\n")


def cmd_toc(sections):
    print("%-3s %-6s %-9s %-8s %-46s %s" % ("#", "行", "作用域", "单元", "段", "字符"))
    for number, section in enumerate(sections, 1):
        size = sum(len(line) + 1 for line in section.lines)
        print("%-3d %-6d %-9s %-8s %-46s %d" % (
            number, section.start + 1, section.kind or "**未声明**",
            (section.unit or "-") + ("(退)" if section.status == "已退役" else ""),
            section.title[:44], size))


def cmd_check(sections, strict=False):
    problems, warnings = [], []
    for section in sections:
        where = "第%d行「%s」" % (section.start + 1, section.title[:36])
        if section.scope is None:
            (problems if strict else warnings).append(
                ("E1" if strict else "W2", where,
                 "标题没标是全卷还是哪段剧情：标题末尾加 <!-- 全卷 --> 或 <!-- 单元编号 -->；旧段保守纳入"))
            continue
        if section.kind is None:
            problems.append(("E2", where, "标题注释不认识：%s（只认 全卷 / 单元编号）" % section.scope))
        if section.kind == "单元级" and section.unit is None:
            problems.append(("E3", where, "剧情段没写单元编号"))
    for code, where, message in problems + warnings:
        print("%s %s %s" % (code, where, message))
    print("---")
    print("段 %d ／ 问题 %d ／ 告警 %d（告警不阻断，逐条人工判断）" % (len(sections), len(problems), len(warnings)))
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("path")
    parser.add_argument("--toc", action="store_true")
    parser.add_argument("--unit")
    parser.add_argument("--chapter", type=int, help="按章号找本章落在哪段剧情的章节范围里，取那一段（同 --unit）")
    parser.add_argument("--contract", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--strict", action="store_true", help="新建卷纲校验：标题没标全卷或单元编号也视为错误")
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

    invalid = [s for s in sections if s.scope and (s.kind is None or (s.kind != "卷级常任" and s.unit is None))]
    if invalid:
        sys.stderr.write("标题注释（或旧的作用域行）写得不对，先运行 --check 修正\n")
        return 1
    active = [s for s in sections if args.history or s.status != "已退役"]
    permanent = [s for s in active if s.kind == "卷级常任"]
    undeclared = [s for s in active if s.scope is None]
    note = ("%d 段没标全卷或单元编号，已保守纳入；用 --check 查看" % len(undeclared)) if undeclared else None
    preamble = lines[:sections[0].start]
    if args.contract:
        emit(sections, set(permanent + undeclared), None, args.history, note, preamble)
        return 0

    if args.chapter is not None and not args.unit:
        args.unit = unit_for_chapter(active, args.chapter)
        if not args.unit:
            sys.stderr.write(
                "卷纲里没有哪段剧情的章节范围覆盖第 %d 章 —— 不静默降级。核对剧情段的「章节范围」，或先补卷纲。\n"
                % args.chapter)
            return 1
        sys.stderr.write("第 %d 章属于剧情段 %s\n" % (args.chapter, args.unit))

    if args.unit:
        owned = [s for s in active if s.unit == args.unit]
        if not owned:
            sys.stderr.write("找不到单元 %s —— 不静默降级。核对单元编号，或先补卷纲。\n" % args.unit)
            return 1
        live = [s for s in owned if s.kind == "单元级"]
        emit(sections, set(permanent + live + undeclared), unit_chapter_range(active, args.unit), args.history, note, preamble)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
