#!/usr/bin/env python3
"""build_architect_brief.py — 把「出卷纲」「出一批细纲」这一时刻要用的流程与模板拼成任务包。

用法:
    python build_architect_brief.py --project <书目录> --task world
    python build_architect_brief.py --project <书目录> --task volume [--volume N]
    python build_architect_brief.py --project <书目录> --task outline --chapters A-B
    python build_architect_brief.py --project <临时目录> --task <任务> --rules-only   # 仓库预算守卫计量用

开书与规划按作者确认点分时刻（见 references/workflow-setup.md）。卷纲与每批细纲最重，
有子代理时交给 story-architect 在新上下文里做：主会话只跑本脚本、把任务包路径交给它，
自己不读包里的内容。任务包写在书内 `.story/work/排纲/`，是这次任务的输入数据，不是 reference。

包里只有该时刻需要的东西，三种任务都附 SKILL.md 的「新增物三级」判据（包外读不到 SKILL.md）：
- world：workflow-setup.md 的 Phase 2 与设定模板、character-basics.md、long-genre-mechanics.md 的
  「核心梗三层递进设计」与「金手指」、character-relations.md 的「人物关系类型」、reader-contract-and-progression.md。
- volume：workflow-volume.md 的「排纲方法」（刻度、交付、自查、关键点法、对标迁移、章节定位）、
  artifact-protocols.md 的大纲与卷纲两节、outline-methods.md 的「卷纲排法」、
  reader-contract-and-progression.md 的契约四问、核心概念、机构设计、风险与续接判据（不带示例）。
- outline：workflow-outline.md 的「排纲方法」（批次步骤、细纲模板与验收、设定补全、排纲底稿模板）、
  long-chapter-hooks.md 的「章尾钩子 13 式」与「章首钩子 7 式」（细纲模板要从中选；只带名称与公式，示例列不进包）、
  character-basics.md 的主角卡与配角卡模板、plot-core-methods.md（首批整份；之后不带开篇噱头一节）；
  首章在范围内时加 opening-design.md 的「开篇规划」。
流程文件的主会话一节（读取清单、分工、作者汇报）不进包。流程里点名、但只在某些书才用得上的参考
（多对标时的跨书召回、女频手册、八节点、情绪模块公式、换地图、感情线阶段、弧线与反转速查、灵感库）
不进包，列在包末「按条件可读」，给出绝对路径与小节，条件满足才读。
本书的方向、设定与作者口头定下的事都在 `设定/`，不进包，由执行者按包里的流程定点读。
`--rules-only` 只拼规则部分（不取本书卷纲），供仓库的预算守卫计量每次调用的加载量。

stdout 输出一行 JSON：任务包路径、字数（去空白）、包含的资料。
Exit: 0 = 已写出；2 = 参数或资料缺失（含卷纲单元只覆盖了请求章节的一部分）。
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
# 包外按条件可读：(文件, 小节或 None=整份, 条件)。条件由执行者读 `设定/` 判断。
CROSS_BOOK = ("cross-book-recall.md", None, "`设定/题材定位.md`「对标登记」里有 2 本及以上对标书")
INSPIRATION = ("cross-book-recall.md", "公共灵感标签召回", "工作区有 `灵感库/`（零命中不阻塞）")
ROMANCE = ("character-relations.md", "感情线阶段", "本书有感情线")
CONDITIONAL = {
    "world": [("female-audience-writing.md", None, "本书是女频"), ROMANCE, CROSS_BOOK, INSPIRATION],
    "volume": [CROSS_BOOK, ("outline-methods.md", "八节点故事结构", "没有主对标"),
               ("outline-methods.md", "情绪模块公式", "卷纲里有自创单元"),
               ("outline-methods.md", "换地图", "本卷换大地图或开新地图"),
               ("emotional-arc-design.md", "六种弧线速查", "情绪弧线选型拿不准"),
               ("long-reversal.md", "反转类型", "本卷规划了反转"), ROMANCE, INSPIRATION],
    "outline": [ROMANCE, CROSS_BOOK, INSPIRATION],
}


def read_reference(name: str) -> str:
    path = REFERENCES / name
    if not path.is_file():
        raise SystemExit(f"ERROR: 缺少 reference：{path}")
    return path.read_text(encoding="utf-8").lstrip("﻿")


def section(text: str, start: str, end: str | None = None) -> str:
    """取 start 标题行到 end 标题行之前（end 省略则到文末）；找不到 start 就报错，不静默给空。"""
    match = re.search(rf"^#+\s*{re.escape(start)}.*$", text, re.M)
    if match is None:
        raise SystemExit(f"ERROR: reference 里找不到小节「{start}」")
    stop = re.search(rf"^#+\s*{re.escape(end)}.*$", text[match.end():], re.M) if end else None
    return text[match.start(): match.end() + stop.start() if stop else len(text)].rstrip()


def drop_last_column(text: str) -> str:
    """表格去掉末列：钩子表的示例列不进包，免得细纲照抄示例的句子形状。"""
    return "\n".join("|".join(line.split("|")[:-2]) + "|" if line.startswith("|") else line
                     for line in text.splitlines())


def new_addition_tiers() -> str:
    """SKILL.md 的「新增物三级」判据：排纲、定设定都要按它分级，而任务包外的 SKILL.md 读不到。"""
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^> \*\*新增物三级\*\*.*?(?=^(?!>))", text, re.M | re.S)
    if match is None:
        raise SystemExit("ERROR: SKILL.md 里找不到「新增物三级」")
    return "\n".join(line[2:] if line.startswith("> ") else line.lstrip(">") for line in match.group(0).rstrip().splitlines())


def conditional_reads(task: str) -> str:
    lines = ["下面几份在包外，只在条件满足时读，只读点名的那一节（没点名读整份）；条件不满足不读："]
    for name, part, when in CONDITIONAL[task]:
        where = f"「{part}」一节" if part else "整份"
        lines.append(f"- {when}：读 `{REFERENCES / name}` {where}")
    return "\n".join(lines)


def emit(text: str, stream) -> None:
    """统一按 UTF-8 写出：Windows 控制台默认 GBK/ASCII 时直接 print 中文会崩。"""
    stream.buffer.write((text + "\n").encode("utf-8"))
    stream.flush()


def render(sections, chosen, span, preamble) -> str:
    """与 outline_view.emit 同一取法（剔除已退役条目、情绪弧线按单元截段），只是返回文本。"""
    out = ["\n".join(strip_retired(preamble, False)).rstrip()] if preamble else []
    for sec in sections:
        if sec not in chosen:
            continue
        body = slice_arc(sec, span) if ("情绪弧线" in sec.title or "排班" in sec.title) else sec.lines
        out.append("\n".join(strip_retired(body, False)).rstrip())
    return "\n\n".join(out) + "\n"


def unit_closures(project: Path, first: int, last: int) -> list[tuple[str, str]]:
    """story-architect 没有执行命令的权限：由脚本先把覆盖本批章节的剧情单元闭包取出来放进包里。

    取法同 `outline_view.py --unit U --stage outline`；一卷里有几个单元时，卷契约与卷级常任只随第一个单元给一次。"""
    found: list[tuple[str, str]] = []
    covered: set[int] = set()
    undeclared: list[str] = []
    for volume in sorted((project / "大纲").glob("卷纲_第*卷.md")):
        lines, sections = parse_volume(volume.read_text(encoding="utf-8"))
        # 单元卡有标题、没写作用域行时取段器认不出它——点名缺哪一行，而不是笼统说找不到单元。
        undeclared += [f"{volume.name}「{s.title.strip()}」" for s in sections
                       if s.scope is None and s.unit and "剧情单元" in s.title]
        if any(s.scope and (s.kind is None or (s.kind != "卷级常任" and s.unit is None)) for s in sections):
            raise SystemExit(f"ERROR: {volume.name} 作用域声明无效，先跑 outline_view.py --check 修正")
        active = [s for s in sections if s.status != "已退役"]
        shared = [s for s in active if s.kind == "卷级常任" or s.scope is None]
        units = sorted({s.unit for s in active if s.unit and s.kind == "单元级"})
        given = False
        for unit in units:
            span = unit_chapter_range(active, unit)
            if not (span and span[0] <= last and span[1] >= first):
                continue
            covered.update(range(span[0], span[1] + 1))
            live = [s for s in active if s.unit == unit and s.kind in ("单元级", "批次底稿")]
            if given:
                text = "（卷契约与卷级常任同上一段，不重复。）\n\n" + render(sections, set(live), span, None)
            else:
                text = render(sections, set(shared + live), span, lines[:sections[0].start] if sections else None)
            given = True
            found.append((f"{volume.name} · 单元 {unit}（第{span[0]}-{span[1]}章）", text))
    missing = [n for n in range(first, last + 1) if n not in covered]
    if missing:
        hint = (f"；这些单元卡缺「> 作用域：单元级 {{单元ID}}」声明行：{'、'.join(undeclared)}"
                if undeclared else "（单元卡要写「> 作用域：单元级 {单元ID}」和「章节范围：第A-B章」）")
        where = "找不到覆盖" if not found else "剧情单元只覆盖了一部分，缺覆盖"
        raise SystemExit(f"ERROR: 卷纲里{where}第{compress(missing)}章的剧情单元{hint}，先补卷纲"
                         "（`outline_view.py --check --strict` 列出全部问题）")
    return found


def compress(numbers: list[int]) -> str:
    """[4, 5, 6, 9] → 4-6、9"""
    spans, start = [], numbers[0]
    for prev, cur in zip(numbers, numbers[1:] + [None]):
        if cur != prev + 1:
            spans.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = cur
    return "、".join(spans)


def weight(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def build(task: str, volume: int | None, chapters: tuple[int, int] | None,
          project: Path | None = None, rules_only: bool = False) -> tuple[str, list[str]]:
    outside = "写作技法只读本包，外加包末「按条件可读」里条件满足的那几节。"
    if task == "world":
        head = ("# 任务包：出核心设定提案\n\n"
                "按下面 Phase 2 的流程，把核心设定写成文件：`设定/题材定位.md`（在定方向时已写的部分上补全，不删作者已定的内容）、"
                "`设定/关系.md`、主角与关键角色的 `设定/角色/{名}.md`、影响全书的 `设定/世界观/{主题}.md`。"
                "作者在定方向时说过的话都在 `设定/题材定位.md`，先读它；拿不准的写成二选一的候选留给作者定，不替作者拍板，"
                "物价、收入、力量档位这类全书刻度按下附「新增物三级」属先问作者，只给候选。"
                f"不出卷纲、不写正文。{outside}交付后只回：写了哪些文件、主角与核心冲突各一句、"
                "要作者定的事（没有写「无」）。")
        setup = read_reference("workflow-setup.md")
        parts = [("workflow-setup.md（Phase 2 与设定模板）",
                  section(setup, "Phase 2：核心设定", "Agent 调用：story-architect + character-designer") + "\n\n"
                  + section(setup, "定设定时建的文件模板")),
                 ("character-basics.md", read_reference("character-basics.md")),
                 ("long-genre-mechanics.md（核心梗三层递进设计、金手指）",
                  section(read_reference("long-genre-mechanics.md"), "核心梗三层递进设计", "微创新与差异化设计")),
                 ("character-relations.md（人物关系类型）",
                  section(read_reference("character-relations.md"), "人物关系类型", "感情流人设核心法")),
                 ("reader-contract-and-progression.md", read_reference("reader-contract-and-progression.md"))]
    elif task == "volume":
        label = f"第{volume}卷" if volume else "本卷"
        head = (f"# 任务包：出{label}卷纲\n\n"
                f"只交付 `大纲/大纲.md` 的分卷表（已有就只补本卷那一行）和 `大纲/卷纲_第{volume or 'X'}卷.md`，"
                "不出细纲、不写正文、不建 `追踪/`。本书方向、设定、对标登记与作者已定的事读 `设定/`（先读 "
                f"`设定/题材定位.md`）。{outside}交付后只回：写了哪些文件、排纲自查 1–4 "
                "的结论各一句、要作者定的事（没有写「无」）。")
        parts = [("workflow-volume.md（排纲方法）", section(read_reference("workflow-volume.md"), "排纲方法")),
                 ("artifact-protocols.md（大纲与卷纲模板）",
                  section(read_reference("artifact-protocols.md"), "大纲/大纲.md", "大纲/细纲_第XXX章.md")),
                 ("outline-methods.md（卷纲排法）", section(read_reference("outline-methods.md"), "卷纲排法", "换地图")),
                 ("reader-contract-and-progression.md（规划判据）",
                  section(read_reference("reader-contract-and-progression.md"), "0. 契约四问", "4. 好/坏例与例外")
                  + "\n\n" + section(read_reference("reader-contract-and-progression.md"), "5. 续接与换书债"))]
    else:
        first, last = chapters
        head = (f"# 任务包：出第{first}-{last}章细纲\n\n"
                f"只交付 `大纲/细纲_第{first:03d}章` 到第{last:03d}章，以及排纲底稿与必要的设定补全，不写正文、"
                "不建 `追踪/`。本批涉及的卷纲单元段附在包末（已按单元取好），卷纲本身不整读；设定从 `设定/` 定点读；"
                f"{outside}交付后只回：写了哪些文件、"
                "每章一句核心事件、要作者定的事（没有写「无」）。")
        basics = read_reference("character-basics.md")
        plot = read_reference("plot-core-methods.md")
        parts = [("workflow-outline.md（排纲方法）", section(read_reference("workflow-outline.md"), "排纲方法")),
                 ("long-chapter-hooks.md（章尾钩子 13 式、章首钩子 7 式）",
                  drop_last_column(section(read_reference("long-chapter-hooks.md"), "章尾钩子 13 式", "章尾实战模板"))),
                 ("character-basics.md（主角卡、配角卡）", section(basics, "第1节：主角卡", "第3节"))]
        if first <= 3:
            parts += [("plot-core-methods.md", plot),
                      ("opening-design.md（开篇规划）",
                       section(read_reference("opening-design.md"), "开篇规划", "开篇落笔"))]
        else:
            parts.append(("plot-core-methods.md（不含开篇噱头）",
                          section(plot, "目标情绪与主角选择", "噱头分类与开篇流程")))
        if not rules_only:
            parts += [(f"卷纲取段：{name}", text) for name, text in unit_closures(project, first, last)]
    parts.append(("SKILL.md（新增物三级）", new_addition_tiers()))
    parts.append(("按条件可读（包外）", conditional_reads(task)))
    body = [head + ("\n\n包里流程写到的脚本命令（取段、`--check`、`check-outline-contract.js`）由主会话在你交付后跑，"
                    "你不执行命令；需要的取段结果已放进包里。")]
    for name, text in parts:
        body.append(f"\n---\n\n<!-- 资料：{name} -->\n\n{text.strip()}\n")
    return "\n".join(body), [name for name, _ in parts]


def parse_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", value or "")
    if not match:
        raise SystemExit("ERROR: --chapters 写成 A-B，如 1-10")
    first = int(match.group(1))
    last = int(match.group(2) or first)
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
    if args.task == "world":
        name = "核心设定.md"
    elif args.task == "volume":
        name = f"卷纲_第{args.volume}卷.md" if args.volume else "卷纲.md"
    else:
        name = f"细纲_第{chapters[0]:03d}-{chapters[1]:03d}章.md"
    out = out_dir / name
    out.write_text(text, encoding="utf-8")
    emit(json.dumps({"brief": str(out), "chars": weight(text), "includes": included}, ensure_ascii=False), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
