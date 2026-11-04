#!/usr/bin/env python3
"""卷纲取段器 —— 让「不整读卷纲」成立。

按声明作用域选取卷级、单元级和批次材料；未声明的旧段保守纳入并告警。

两种写法都认（新卷纲只写第一种）：

1. 标题尾部注释（0.10 起）：
       ## 本卷故事线 <!-- 全卷 -->
       ### 第一段剧情：退婚风波 <!-- L1-01 -->
       #### 老底稿 <!-- 批次底稿 L1-01｜已退役 -->
   新写法里没写注释的子标题跟随上级剧情段（上级是全卷段的不跟随，仍算未声明）。
2. 旧写法：标题**下一行非空行**写
       > 作用域：卷级常任
       > 作用域：单元级 D1-03
       > 作用域：批次底稿 D1-03｜状态：在用

退役行（行内覆盖）：以 `⊘` 起头的列表行 / 表格行，默认过滤。

卷纲、细纲按名读取的字段在这里集中给出新旧名（UNIT_FIELD_NAMES、CHAPTER_UNIT_FIELDS），
其他脚本从这里取，不各自写死一种叫法。

细纲属于哪段剧情：新细纲只写段名（「第一段剧情：退婚风波」），按本章章号落在卷纲哪张剧情段卡的
「章节范围」里定位（unit_for_chapter / --chapter）；旧细纲行末的编号注释、旧「单元ID/位置」字段照样认。

用法：
    outline_view.py --toc   卷纲.md
    outline_view.py --unit D1-03 卷纲.md
    outline_view.py --chapter 12 卷纲.md      # 第 12 章落在哪段剧情，就取哪段（同 --unit）
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
# 标题尾部注释：## 本卷故事线 <!-- 全卷 -->
TRAILING = re.compile(r"^(.*?)\s*<!--\s*(.*?)\s*-->\s*$")
RETIRED_LINE = re.compile(r"^\s*(?:[-*]\s*)?⊘|^\s*\|\s*⊘")
# 单元块内不该出现的全卷字样——出现即说明这条常任规则放错了地方
LEAK = re.compile(r"全卷常任|全程生效|全卷生效|本单元起常任|自 ?[LD]\d+-\d+ ?起生效")
# 指向卷级的指针行不算泄漏：单元块可以引用常任规则，不可以复述它
POINTER = re.compile(r"全卷常任裁定|全卷规矩|已提为卷级|不复读|规则本身见|见「全卷")
UNIT_IN_TITLE = re.compile(r"(?<![\w-])([LD]\d+-\d+|U\d+)(?![\w-])")
# 批次底稿里出现跨章祈使＝这条约束在写作期还有效，而写作档不给底稿 → 必须下沉
IMPERATIVE = re.compile(r"全程不许|一律不许|往后任何章|此后不再|往后每|从此不|终局前不")
CH_RANGE = re.compile(r"章节范围[：:]\s*第\s*(\d+)\s*[-–—~至]\s*(\d+)\s*章")
# 情绪弧线逐章行：首列写「12」或模板里的「第12章」都认
ARC_ROW = re.compile(r"^\|\s*第?\s*(\d+)\s*章?\s*\|")
UNIT_ID = re.compile(r"(?<![\w-])([A-Za-z]\d+-\d+|U\d+)(?![\w-])")

# 按名读取的字段：新名在前，旧名照认。改名时只改这里，读的脚本跟着走。
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
    elif re.fullmatch(r"批次底稿(?:\s+[A-Za-z][\w-]*)?", head):
        section.kind = "批次底稿"
    elif section.inline and re.fullmatch(r"[A-Za-z][\w-]*", head) and UNIT_ID.fullmatch(head):
        section.kind = "单元级"
        section.unit = head
    found = re.search(r"^(?:单元级|批次底稿)\s+([A-Za-z][\w-]*)$", head)
    if found:
        section.unit = found.group(1)
    if any("已退役" in part for part in parts):
        section.status = "已退役"


def is_unit_card(section):
    """剧情段的卡头：旧写法标题含「剧情单元」，新写法标题是「第N段剧情」，或这一段自己写着章节范围。"""
    if section.kind != "单元级" or section.inherited:
        return False
    return ("剧情单元" in section.title or "段剧情" in section.title
            or any(CH_RANGE.search(line) for line in section.lines))


def field_value(text, names):
    """按名取列表字段的值（第一种叫法有就用它，否则试旧名）；没有返回 None。"""
    for name in names:
        pattern = re.compile(rf"^[ \t>]*[-*+][ \t]*\*{{0,2}}{re.escape(name)}\*{{0,2}}[ \t]*[：:][ \t]*(.*)$", re.M)
        match = pattern.search(text or "")
        if match:
            return match.group(1).strip()
    return None


def unit_id_of(value):
    """从「属于哪段剧情：第一段剧情，第二步 <!-- L1-01 -->」或旧「单元ID/位置：L1-01；第2拍」取单元编号。"""
    if not value:
        return None
    found = UNIT_ID.search(value)
    return found.group(1) if found else None


def chapter_unit(outline_text):
    """细纲里写明的剧情段编号（旧写法：行末注释或「单元ID/位置」）；新细纲不写编号，返回 None，
    由调用方按章号走 unit_for_chapter。"""
    return unit_id_of(field_value(outline_text, CHAPTER_UNIT_FIELDS))


def unit_for_chapter(sections, chapter):
    """本章章号落在哪张剧情段卡的「章节范围」里（跳过已退役的卡）；没有返回 None。"""
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
    """卷纲全文 + 章号 → 剧情段编号；卷纲读不出或没有覆盖本章的段返回 None。"""
    try:
        _, sections = parse(volume_text or "")
    except Exception:  # noqa: BLE001 —— 卷纲写坏时按「找不到」处理，由调用方报告
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
        self.start = start          # 标题行号（0 基）
        self.end = None
        self.scope = None           # 原始作用域串，None ＝ 未声明
        self.kind = None            # 卷级常任 / 单元级 / 批次底稿
        self.unit = None
        self.status = "在用"
        self.lines = []
        self.inline = False         # 作用域写在标题尾部注释里（新写法）
        self.inherited = False      # 新写法里没写注释、跟随上级剧情段


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
    # 新写法：没写注释的子标题跟随最近的上级剧情段（单元级或批次底稿），上级是全卷段的不跟随。
    stack = []
    for section in sections:
        while stack and stack[-1].level >= section.level:
            stack.pop()
        parent = stack[-1] if stack else None
        if (section.scope is None and parent is not None and parent.inline
                and parent.kind in ("单元级", "批次底稿") and parent.unit):
            section.scope = parent.scope
            section.kind = parent.kind
            section.unit = parent.unit
            section.status = parent.status
            section.inline = True
            section.inherited = True
        stack.append(section)
    # 新写法里全卷小节可以不写注释：文件里只要有剧情段用了标题尾注释，其余没标的段一律算全卷。
    if any(section.inline for section in sections):
        for section in sections:
            if section.scope is None and section.unit is None:
                section.scope = "全卷"
                section.inline = True
                classify(section)
    return lines, sections


def strip_retired(block_lines, keep_history):
    if keep_history:
        return block_lines
    return [line for line in block_lines if not RETIRED_LINE.match(line)]


def unit_chapter_range(sections, unit):
    for section in sections:
        if section.unit == unit and is_unit_card(section):
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
            (problems if strict else warnings).append(
                ("E1" if strict else "W2", where,
                 "标题没标是全卷还是哪段剧情：标题末尾加 <!-- 全卷 --> 或 <!-- 单元编号 -->；旧段保守纳入"))
            continue
        if section.kind is None:
            problems.append(("E2", where, "标题注释不认识：%s（只认 全卷 / 单元编号 / 批次底稿 单元编号）" % section.scope))
        if section.kind in ("单元级", "批次底稿") and section.unit is None:
            problems.append(("E3", where, "剧情段/批次底稿段没写单元编号"))
        if section.kind in ("单元级", "批次底稿"):
            for offset, line in enumerate(section.lines):
                if LEAK.search(line) and not POINTER.search(line):
                    problems.append(
                        ("E4", "第%d行" % (section.start + offset + 1),
                         "剧情段里写了全卷都要守的规矩，挪到「全卷规矩」：%s"
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
    parser.add_argument("--chapter", type=int, help="按章号找本章落在哪段剧情的章节范围里，取那一段（同 --unit）")
    parser.add_argument("--contract", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--strict", action="store_true", help="新建卷纲校验：标题没标全卷或单元编号也视为错误")
    # 排纲笔记放在卷纲外的 .story/排纲笔记/{单元ID}.md（老书在 大纲/排纲笔记_ 或 排纲底稿_），默认输出就是写作要的闭包。
    # --stage outline 只为老卷纲保留：它们的供给自查等底稿还写在卷纲里（作用域：批次底稿）。
    parser.add_argument("--stage", choices=["outline", "write"], default="write",
                        help="write（默认）＝卷级常任＋单元级；"
                             "outline＝另带老卷纲里仍在用的批次底稿段")
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
        unit = args.unit
        owned = [s for s in active if s.unit == unit]
        if not owned:
            sys.stderr.write(
                "找不到单元 %s —— 不静默降级。核对单元编号，或先补卷纲。\n" % unit)
            return 1
        if args.stage == "write":
            # 写作档不给批次底稿：它是排纲期的工作底稿，其中有写作期约束力的条目
            # 必须已经下沉到单元级段或细纲（见 artifact-protocols.md「排纲笔记不进卷纲」）
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
