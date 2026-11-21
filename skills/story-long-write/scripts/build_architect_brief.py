#!/usr/bin/env python3
"""build_architect_brief.py — 把定设定、出卷纲、出一批细纲要用的流程、模板与卷纲段拼成 story-architect 任务包。

用法:
    python build_architect_brief.py --project <书目录> --task world|volume|outline [--volume N] [--chapters A-B] [--rules-only]
Exit: 0 = 已写出；2 = 参数或资料缺失。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outline_view import parse as parse_volume, slice_arc, strip_retired, unit_chapter_range  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
REFERENCES = SKILL_ROOT / "references"
WORK_DIR = (".story", "work", "排纲")
FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(?P<marker>`{3,}|~{3,})(?P<info>[^\n]*)$")
FENCE_TAG_RE = re.compile(r"(?:^|\s)template=(?P<tag>\S+)")

CROSS_BOOK = ("cross-book-recall.md", None, "`设定/题材定位.md`「对标登记」里有 2 本及以上对标书")
ROMANCE = ("character-relations.md", "感情线阶段", "本书有感情线")
CONDITIONAL = {
    "world": [("female-audience-writing.md", None, "本书是女频"), ROMANCE, CROSS_BOOK],
    "volume": [CROSS_BOOK, ("outline-methods.md", "常见的八步结构", "没有主对标"),
               ("outline-methods.md", "情绪模块公式", "卷纲里有自创的剧情段"),
               ("outline-methods.md", "换地图", "本卷换大地图或开新地图"),
               ("long-reversal.md", "反转类型", "本卷规划了反转"), ROMANCE],
    "outline": [ROMANCE, CROSS_BOOK],
}
TEMPLATE_TARGETS = {
    "题材定位": "设定/题材定位.md", "全书梗概": "设定/全书梗概.md", "关系": "设定/关系.md",
    "主角卡": "设定/角色/{名}.md（主角）", "配角卡": "设定/角色/{名}.md（配角）",
}
PLOT_CORE_AFTER_OPENING = ("目标情绪与主角选择", "爽点：六类与倒推", "高潮构建公式",
                           "情节细化：情节点怎么排", "留悬念与章尾", "过渡章与衔接")
NEW_ADDITION_TIERS = (
    "**新增物三级**（缺东西时三种处理；只看下一章需不需要知道它存在过）：\n"
    "- **直接写**：微连接、路人、器物、地名细部、一次性对话、现场细节；不申报。\n"
    "- **补上并记下**：具名配角、势力、复用地点属性、能力形态、规矩、刻度、新伏笔、新关系或承诺；"
    "排纲先落设定档再引用，写正文照写并进申报表。\n"
    "- **先问作者**：新主线事件或反转、金手指规则与力量档位、真相或伏笔结算、经济锚点、读者期待、"
    "提前写后续章、改变细纲已定结果或人物决定、卷纲新增主线或故事线、碰这卷主打的线或后面才揭开的东西、"
    "与既有规矩或承诺冲突；写正文时不写，排纲时挂起列候选，由主会话问作者。\n"
    "拿不准：写时按补上并记下，处置时按先问作者。"
)


def read_reference(name: str) -> str:
    path = REFERENCES / name
    if not path.is_file():
        raise SystemExit(f"ERROR: 缺少 reference：{path}")
    return path.read_text(encoding="utf-8").lstrip("\ufeff")


def headings(text: str) -> list[tuple[int, int, str]]:
    found, fence = [], None
    for index, line in enumerate(text.split("\n")):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if not fence and (match := re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)):
            found.append((index, len(match.group(1)), match.group(2)))
    return found


def section(text: str, *names: str) -> str:
    lines, marks, parts = text.split("\n"), headings(text), []
    for name in names:
        hit = next((i for i, (_, _, title) in enumerate(marks) if title.startswith(name)), None)
        if hit is None:
            raise SystemExit(f"ERROR: reference 里找不到小节「{name}」")
        start, level, _ = marks[hit]
        end = next((row for row, lv, _ in marks[hit + 1:] if lv <= level), len(lines))
        parts.append("\n".join(lines[start:end]).rstrip())
    return "\n\n".join(parts)


def template_block(text: str, tag: str, *, source: str = "参考文件") -> str:
    """按围栏标签 `template=<tag>` 取整块模板（不含围栏行）；缺失或重复直接报错。"""
    lines, hits, index = text.lstrip("\ufeff").split("\n"), [], 0
    while index < len(lines):
        opened = FENCE_OPEN_RE.match(lines[index])
        if not opened or (opened.group("marker")[0] == "`" and "`" in opened.group("info")):
            index += 1
            continue
        marker = opened.group("marker")
        found = FENCE_TAG_RE.search(opened.group("info"))
        close = re.compile(r"^[ ]{0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
        end = next((row for row in range(index + 1, len(lines)) if close.match(lines[row])), len(lines))
        if found and found.group("tag") == tag:
            hits.append("\n".join(lines[index + 1:end]))
        index = end + 1
    if len(hits) != 1:
        reason = f"找不到模板「{tag}」" if not hits else f"模板「{tag}」出现了 {len(hits)} 次"
        raise SystemExit(f"ERROR: {source} 里{reason}")
    return hits[0]


def templates(name: str, *tags: str) -> str:
    text = read_reference(name)
    blocks = ["模板里的小节名、字段名照抄，不改名：写正文的脚本和别的 skill 按名读取。"]
    for tag in tags:
        body = template_block(text, tag, source=name)
        blocks.append(f"### {TEMPLATE_TARGETS.get(tag, tag)}\n\n```markdown\n{body.strip()}\n```")
    return "\n\n".join(blocks)


def drop_last_column(text: str) -> str:
    return "\n".join("|".join(line.split("|")[:-2]) + "|" if line.startswith("|") else line
                     for line in text.splitlines())


def conditional_reads(task: str) -> str:
    lines = ["下面几份在包外，只在条件满足时读，只读点名的那一节（没点名读整份）；条件不满足不读。"
             "路径按你的参考文件路径规则解析；流程提到而这里没列的参考文件不用找，对标资料缺了就停下，说清缺哪份："]
    for name, part, when in CONDITIONAL[task]:
        text = read_reference(name)
        if part:
            section(text, part)
        lines.append(f"- {when}：读 `agent-references/{name}` {'「' + part + '」一节' if part else '整份'}")
    if CROSS_BOOK in CONDITIONAL[task]:
        lines.append(f"读了 {CROSS_BOOK[0]} 时：`gaps.*` 写进「要作者定的事」，「副对标召回摘要」不单独回。")
    return "\n".join(lines)


def emit(text: str, stream) -> None:
    stream.buffer.write((text + "\n").encode("utf-8"))
    stream.flush()


def render(sections, chosen, span, preamble) -> str:
    out = ["\n".join(strip_retired(preamble, False)).rstrip()] if preamble else []
    for sec in sections:
        if sec not in chosen:
            continue
        body = slice_arc(sec, span) if ("情绪弧线" in sec.title or "排班" in sec.title) else sec.lines
        out.append("\n".join(strip_retired(body, False)).rstrip())
    return "\n\n".join(out) + "\n"


def compress(numbers: list[int]) -> str:
    spans, start = [], numbers[0]
    for prev, cur in zip(numbers, numbers[1:] + [None]):
        if cur != prev + 1:
            spans.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = cur
    return "、".join(spans)


def unit_closures(project: Path, first: int, last: int) -> list[tuple[str, str]]:
    """按 `outline_view.py --unit U` 口径取出覆盖本批章节的剧情段闭包；同卷全卷段只给一次。"""
    found: list[tuple[str, str]] = []
    covered: set[int] = set()
    undeclared: list[str] = []
    for volume in sorted((project / "大纲").glob("卷纲_第*卷.md")):
        lines, sections = parse_volume(volume.read_text(encoding="utf-8"))
        undeclared += [f"{volume.name}「{s.title.strip()}」" for s in sections
                       if s.scope is None and s.unit and ("剧情单元" in s.title or "段剧情" in s.title)]
        if any(s.scope and (s.kind is None or (s.kind != "卷级常任" and s.unit is None)) for s in sections):
            raise SystemExit(f"ERROR: {volume.name} 标题注释（或旧的作用域行）写得不对，先跑 outline_view.py --check 修正")
        active = [s for s in sections if s.status != "已退役"]
        shared = [s for s in active if s.kind == "卷级常任" or s.scope is None]
        units = sorted({s.unit for s in active if s.unit and s.kind == "单元级"})
        given = False
        for unit in units:
            span = unit_chapter_range(active, unit)
            if not (span and span[0] <= last and span[1] >= first):
                continue
            covered.update(range(span[0], span[1] + 1))
            live = [s for s in active if s.unit == unit and s.kind == "单元级"]
            if given:
                text = "（全卷段同上一段，不重复。）\n\n" + render(sections, set(live), span, None)
            else:
                text = render(sections, set(shared + live), span, lines[:sections[0].start] if sections else None)
            given = True
            found.append((f"{volume.name} · 剧情段 {unit}（第{span[0]}-{span[1]}章；排纲笔记写 .story/排纲笔记/{unit}.md）", text))
    missing = [n for n in range(first, last + 1) if n not in covered]
    if missing:
        hint = (f"；这些剧情段的标题末尾缺单元编号注释（如 <!-- L1-01 -->）：{'、'.join(undeclared)}"
                if undeclared else "（每段剧情的标题末尾写单元编号注释，如「### 第一段剧情：退婚风波 <!-- L1-01 -->」，卡里写「章节范围：第A-B章」）")
        where = "找不到覆盖" if not found else "剧情段只覆盖了一部分，缺覆盖"
        raise SystemExit(f"ERROR: 卷纲里{where}第{compress(missing)}章的剧情段{hint}，先补卷纲"
                         "（`outline_view.py --check --strict` 列出全部问题）")
    return found


def build(task: str, volume: int | None, chapters: tuple[int, int] | None,
          project: Path | None = None, rules_only: bool = False) -> tuple[str, list[str]]:
    outside = "写作技法只读本包，外加包末「按条件可读」里条件满足的那几节。"
    if task == "world":
        head = ("# 任务包：出核心设定提案\n\n"
                "按下面 Phase 2 的流程，把核心设定写成文件：`设定/题材定位.md`（在定方向时已写的部分上补全，「题材框架」留到出卷纲补，不删作者已定的内容）、"
                "`设定/全书梗概.md`（故事话写主角最终要什么、最大阻碍、前几次大转折；结局一节没想好可空）、"
                "`设定/关系.md`、主角与关键角色的 `设定/角色/{名}.md`、影响全书的 `设定/世界观/{主题}.md`。"
                "作者在定方向时说过的话都在 `设定/题材定位.md`，先读它；拿不准的写成二选一的候选留给作者定，不替作者拍板，"
                "物价、收入、力量档位这类全书刻度按下附「新增物三级」属问作者，只给候选。"
                f"不出卷纲、不写正文。{outside}交付后只回：写了哪些文件、主角与核心冲突各一句、要作者定的事（没有写「无」）。")
        setup = read_reference("workflow-setup.md")
        parts = [("workflow-setup.md（Phase 2）", section(setup, "Phase 2：核心设定")),
                 ("workflow-setup.md（题材定位、全书梗概、关系模板）", templates("workflow-setup.md", "题材定位", "全书梗概", "关系")),
                 ("character-basics.md", read_reference("character-basics.md")),
                 ("long-genre-mechanics.md（核心梗三层递进设计、金手指）",
                  section(read_reference("long-genre-mechanics.md"), "核心梗三层递进设计", "金手指")),
                 ("character-relations.md（人物关系类型）", section(read_reference("character-relations.md"), "人物关系类型")),
                 ("reader-contract-and-progression.md", read_reference("reader-contract-and-progression.md"))]
    elif task == "volume":
        label = f"第{volume}卷" if volume else "本卷"
        head = (f"# 任务包：出{label}卷纲\n\n"
                f"只交付 `大纲/大纲.md` 的分卷表（已有就只补本卷那一行）、`大纲/卷纲_第{volume or 'X'}卷.md`，"
                "并补齐 `设定/题材定位.md`「题材框架」的「关键转折节点」（标题写 `## 题材框架`，去掉「（出卷纲时补）」，其余小节不动）；"
                "不出细纲、不写正文、不建 `追踪/`。本书方向、设定、对标登记与作者已定的事读 `设定/`（先读 `设定/题材定位.md`）。"
                f"{outside}交付后只回：写了哪些文件、排纲自查四项的结论各一句、要作者定的事（没有写「无」）。")
        parts = [("workflow-volume.md（排纲方法）", section(read_reference("workflow-volume.md"), "排纲方法")),
                 ("artifact-protocols.md", read_reference("artifact-protocols.md")),
                 ("outline-methods.md（卷纲排法）", section(read_reference("outline-methods.md"), "卷纲排法")),
                 ("reader-contract-and-progression.md", read_reference("reader-contract-and-progression.md"))]
    else:
        first, last = chapters
        head = (f"# 任务包：出第{first}-{last}章细纲\n\n"
                f"只交付 `大纲/细纲_第{first:03d}章` 到第{last:03d}章，以及排纲笔记（`.story/排纲笔记/{{剧情段编号}}.md`）与必要的设定补全，"
                "不写正文、不建 `追踪/`。本批涉及的卷纲剧情段附在包末（已按段取好），卷纲本身不整读；设定从 `设定/` 定点读；"
                f"{outside}交付后只回：写了哪些文件、每章一句核心事件、要作者定的事（没有写「无」）。")
        plot = read_reference("plot-core-methods.md")
        parts = [("workflow-outline.md（排纲方法）", section(read_reference("workflow-outline.md"), "排纲方法")),
                 ("outline-template.md", read_reference("outline-template.md")),
                 ("long-chapter-hooks.md（章尾钩子 13 式、章首钩子 7 式）",
                  drop_last_column(section(read_reference("long-chapter-hooks.md"), "章尾钩子 13 式", "章首钩子 7 式"))),
                 ("character-basics.md（主角卡、配角卡模板）", templates("character-basics.md", "主角卡", "配角卡"))]
        if first <= 3:
            parts += [("plot-core-methods.md", plot),
                      ("opening-design.md（开篇规划）", section(read_reference("opening-design.md"), "开篇规划"))]
        else:
            parts.append(("plot-core-methods.md（不含开篇噱头）", section(plot, *PLOT_CORE_AFTER_OPENING)))
        if not rules_only:
            parts += [(f"卷纲取段：{name}", text) for name, text in unit_closures(project, first, last)]
    parts.append(("SKILL.md（新增物三级）", NEW_ADDITION_TIERS))
    parts.append(("按条件可读（包外）", conditional_reads(task)))
    body = [head + "\n\n包里流程写到的脚本命令（取段、`--check`、`check-outline-contract.js`）由主会话在你交付后跑，你不执行命令；需要的取段结果已放进包里。"]
    body += [f"\n---\n\n<!-- 资料：{name} -->\n\n{text.strip()}\n" for name, text in parts]
    return "\n".join(body), [name for name, _ in parts]


def parse_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", value or "")
    if not match:
        raise SystemExit("ERROR: --chapters 写成 A-B，如 1-10")
    first, last = int(match.group(1)), int(match.group(2) or match.group(1))
    if first < 1 or last < first:
        raise SystemExit("ERROR: --chapters 范围无效")
    return first, last


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="拼出 story-architect 出卷纲/细纲的任务包")
    parser.add_argument("--project", required=True, type=Path, help="书目录")
    parser.add_argument("--task", required=True, choices=("world", "volume", "outline"))
    parser.add_argument("--volume", type=int, help="卷号（volume 任务）")
    parser.add_argument("--chapters", help="章节范围 A-B（outline 任务）")
    parser.add_argument("--rules-only", action="store_true", help="只拼规则部分、不取本书卷纲（预算守卫计量用）")
    args = parser.parse_args(argv)
    try:
        if not args.project.is_dir():
            raise SystemExit(f"ERROR: 书目录不存在：{args.project}")
        chapters = parse_range(args.chapters) if args.task == "outline" else None
        if args.task == "outline" and chapters[1] - chapters[0] >= 10:
            raise SystemExit("ERROR: 一批细纲最多 10 章，拆成两批")
        text, included = build(args.task, args.volume, chapters, args.project, args.rules_only)
    except SystemExit as exc:
        emit(str(exc), sys.stderr)
        return 2
    out_dir = args.project.joinpath(*WORK_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = ("核心设定.md" if args.task == "world"
            else (f"卷纲_第{args.volume}卷.md" if args.volume else "卷纲.md") if args.task == "volume"
            else f"细纲_第{chapters[0]:03d}-{chapters[1]:03d}章.md")
    out = out_dir / name
    out.write_text(text, encoding="utf-8")
    emit(json.dumps({"brief": str(out), "chars": len(re.sub(r"\s", "", text)), "includes": included}, ensure_ascii=False), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
