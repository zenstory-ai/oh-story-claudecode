#!/usr/bin/env python3
"""build_outline_brief.py — 拼出导入长篇「逐批反推细纲」的任务包。

用法:
    python build_outline_brief.py --project <书目录> --chapters A-B [--analysis <拆文库/导入书名>]

导入按作者时间线分时刻（见 SKILL.md「时刻表与交接」）。细纲按批反推，负载按批计、不随全书章数增长。
有 story-architect 时主会话只跑本脚本、把任务包路径交给它（它没有执行命令的权限），没有时主会话
自己读包写本批。任务包写在书内 `.story/work/排纲/`，是这次任务的输入数据，不是 reference。

包里只有本批需要的东西，执行者不再整读每章约 4K 字的摘要：
- 反推规则与细纲模板：references/outline-reverse-rules.md 全文；
- 本批每章：正文路径、按 visible_chars_v1 测好的历史长度（与写作时章节检查同一口径，
  story-architect 不能自己跑测量），以及从拆文库摘要里抽出的、写细纲真正要用的字段
  （关键事件、因果、局面结果、涉及、信息变化、状态变化、章尾钩子，情节点只取「标题｜类型｜基调」）；
- 本批第一章另带上一章摘要里的章尾钩子（写章首钩子用）；
- 卷纲里章节范围与本批重叠的剧情单元卡。单元卡用 outline_view.py 的解析识别（写正文时
  `outline_view.py --unit` 也用它），任务包取得到的单元，写正文时也取得到。
本书设定与作者已定的事不进包，执行者按规则定点读项目文件与 `.story/work/导入记录.md`。

批大小按总量定：请求 10–20 章（全书最后一批可以更少）；读取量包括任务包，
以及摘要缺失/证据不全时按全章计的正文补读上限。超过约 25K 字时从末尾少排几章（可少于 10 章，至少 1 章）。

stdout 输出一行 JSON：任务包路径、本批实际章节范围与下一批起点、执行者要读的总量 chars（去空白）、
本批每章长度、没找到摘要的章。
Exit: 0 = 已写出；2 = 参数错误、正文或卷纲缺失、长度测不出。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outline_view import parse as parse_volume, unit_chapter_range  # noqa: E402
from wordcount_core import METRIC, WordcountError, find_chapter_file, measure_wordcount  # noqa: E402

RULES = Path(__file__).resolve().parent.parent / "references" / "outline-reverse-rules.md"
WORK_DIR = (".story", "work", "排纲")
MIN_BATCH, MAX_BATCH = 10, 20
LOAD_LIMIT = 25000  # 执行者一次要读的量（去空白字数）；再加上 agent 模板或 SKILL 入口仍在 35K 内
# 摘要里写细纲要用的字段（与 story-long-analyze 摘要投影同名）；旧版摘要的同义标签放在别名里。
SUMMARY_FIELDS = (
    ("关键事件", ()),
    ("因果", ()),
    ("局面结果", ()),
    ("涉及", ("涉及人物", "出场人物")),
    ("信息变化", ()),
    ("状态变化", ()),
    ("章尾钩子", ("卡点与伏笔",)),
)
FIELD_NAMES = "|".join(name for field in SUMMARY_FIELDS for name in (field[0], *field[1]))
# `**标签**：`（当前投影与旧版加粗写法）或不加粗的 `- 关键事件：`（只认上面这些字段名）。
LABEL_RE = re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*([^*]+?)\*\*|(%s))\s*[：:（(]" % FIELD_NAMES)
POINT_HEADER_RE = re.compile(r"^P(\d+)\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$")
POINT_TAG_RE = re.compile(r"^主题标签\s*[：:]?\s*[^|｜]*?\s*[|｜]\s*基调\s*[：:]?\s*(.*?)\s*$")


def emit(text: str, stream) -> None:
    """统一按 UTF-8 写出：Windows 控制台默认 GBK/ASCII 时直接 print 中文会崩。"""
    stream.buffer.write((text + "\n").encode("utf-8"))
    stream.flush()


def weight(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def parse_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", value or "")
    if not match:
        raise SystemExit("ERROR: --chapters 写成 A-B，如 1-20")
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if first < 1 or last < first:
        raise SystemExit("ERROR: --chapters 范围无效")
    return first, last


def last_body_chapter(project: Path) -> int:
    numbers = [int(m.group(1)) for p in (project / "正文").glob("第*章*.md")
               if "_原稿_" not in p.name and (m := re.match(r"^第0*(\d+)章", p.name))]
    return max(numbers, default=0)


def check_batch_size(first: int, last: int, final: int) -> None:
    size = last - first + 1
    if size > MAX_BATCH:
        raise SystemExit(f"ERROR: 一批细纲最多 {MAX_BATCH} 章，拆成两批")
    # 只有全书最后一批可以不足 10 章（包太大时脚本自己少排几章不受此限）。
    if size < MIN_BATCH and last < final:
        raise SystemExit(f"ERROR: 一批细纲至少 {MIN_BATCH} 章（全书最后一批除外），把范围扩到第{first}-{min(final, first + MIN_BATCH - 1)}章")


def shown_path(path: Path, base: Path) -> str:
    """项目根下的路径写相对路径（story-architect 从项目根解析），在外面的写绝对路径。"""
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path)


def measure(project: Path, chapter: int) -> tuple[Path, str, int]:
    try:
        body = find_chapter_file(project / "正文", chapter, outline=False)
        text = body.read_bytes().decode("utf-8")
    except (WordcountError, OSError, UnicodeError) as exc:
        raise SystemExit(f"ERROR: 第{chapter}章正文读不到（{exc}），先完成正文迁移")
    result = measure_wordcount(text, chapter=chapter)
    if result["status"] != "measured":
        raise SystemExit(f"ERROR: 第{chapter}章长度测不出（{result['invalid_reason']}）")
    return body, text, result["actual"]


# ---------- 摘要字段抽取 ----------

def label_blocks(text: str) -> dict[str, str]:
    """把摘要按 `**标签**：` 切块；情节点之后的内容另行解析，不进字段块。"""
    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if POINT_HEADER_RE.match(stripped) or stripped.startswith("#"):
            current = None
            continue
        match = LABEL_RE.match(line)
        if match:
            current = (match.group(1) or match.group(2)).strip()
            rest = re.split(r"[：:]", line, maxsplit=1)
            blocks.setdefault(current, []).append(rest[1] if len(rest) > 1 else "")
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in blocks.items()}


def flatten(value: str) -> str:
    """列表/表格压成一行：表格只取第一列（人物名），跳过表头与分隔行。"""
    rows = [line.strip() for line in value.split("\n") if line.strip()]
    if rows and all(row.startswith("|") for row in rows):
        names = [row.strip("|").split("|")[0].strip() for row in rows[2:]]
        return "、".join(name for name in names if name)
    return " ".join(re.sub(r"^(?:\d+[.、]|[-*+])\s*", "", row) for row in rows)


def summary_points(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").split("\n")
    points = []
    for index, line in enumerate(lines):
        header = POINT_HEADER_RE.match(line.strip())
        if not header:
            continue
        kind = re.split(r"[|｜]", header.group(3))[0].strip()
        kind = kind[2:].lstrip(" ：:") if kind.startswith("类型") else kind
        tone = "—"
        for follow in lines[index + 1:index + 12]:
            if POINT_HEADER_RE.match(follow.strip()):
                break
            tag = POINT_TAG_RE.match(follow.strip())
            if tag:
                tone = tag.group(1) or "—"
                break
        points.append(f"P{header.group(1)} {header.group(2).strip()}｜{kind}｜{tone}")
    return points


def summary_lines(text: str) -> tuple[list[str], bool]:
    blocks = label_blocks(text)
    out = []
    complete = True
    for name, aliases in SUMMARY_FIELDS:
        raw = next((blocks[key] for key in (name, *aliases) if blocks.get(key)), "")
        value = flatten(raw)
        complete = complete and bool(value) and value != "[待补充]"
        out.append(f"- {name}：{value or '（摘要未写）'}")
    points = summary_points(text)
    out.append("- 情节点（标题｜类型｜基调）：" + ("；".join(points) if points else "（摘要里没有可读的情节点）"))
    return out, complete and bool(points)


def previous_hook(analysis: Path, chapter: int) -> str | None:
    """上一章摘要里的章尾钩子：本批第一章写「章首钩子」用，上一章不在本包里。"""
    summary = analysis / "章节" / f"第{chapter - 1}章_摘要.md"
    if chapter <= 1 or not summary.is_file():
        return None
    blocks = label_blocks(summary.read_text(encoding="utf-8-sig"))
    keys = ("章尾钩子", *dict(SUMMARY_FIELDS)["章尾钩子"])
    return next((flatten(blocks[key]) for key in keys if blocks.get(key)), None)


def chapter_block(project: Path, analysis: Path, chapter: int, first: int) -> tuple[str, int, int, bool]:
    """返回（本章块、历史长度、执行者还需另读的正文量、是否缺摘要）。"""
    body, body_text, actual = measure(project, chapter)
    head = [f"### 第{chapter}章", "",
            f"- 正文：`{shown_path(body, project.parent)}`；字数目标 {actual}（{METRIC}）"]
    hook = previous_hook(analysis, chapter) if chapter == first else None
    if hook:
        head.append(f"- 上一章（第{chapter - 1}章）章尾钩子：{hook}")
    summary = analysis / "章节" / f"第{chapter}章_摘要.md"
    if summary.is_file():
        evidence, complete = summary_lines(summary.read_text(encoding="utf-8-sig"))
        lines = [f"- 摘要要点（抽自 `{shown_path(summary, project.parent)}`）："] + [
            "  " + line for line in evidence]
        if not complete:
            lines.append("- 摘要要点不全；可能补读的正文已按全章计入本批读取量，优先用现有证据。")
        return "\n".join(head + lines), actual, 0 if complete else weight(body_text), False
    note = "- 摘要：未找到，读该章正文反推，证据不足处写 [待补充]"
    return "\n".join(head + [note]), actual, weight(body_text), True


# ---------- 卷纲剧情单元 ----------

def unit_cards(project: Path, first: int, last: int) -> list[str]:
    """从各卷纲取章节范围与本批重叠的剧情单元卡（连同卡下的子段）。"""
    volumes = sorted((project / "大纲").glob("卷纲_第*卷.md"))
    if not volumes:
        raise SystemExit("ERROR: 大纲/ 下没有卷纲，先在结构迁移时刻写定卷纲")
    out: list[str] = []
    coverage = {chapter: 0 for chapter in range(first, last + 1)}
    for volume in volumes:
        lines, sections = parse_volume(volume.read_text(encoding="utf-8-sig"))
        for section in sections:
            if section.kind != "单元级" or "剧情单元" not in section.title or section.status == "已退役":
                continue
            span = unit_chapter_range([section], section.unit)
            if span is None or span[0] > last or span[1] < first:
                continue
            for chapter in range(max(first, span[0]), min(last, span[1]) + 1):
                coverage[chapter] += 1
            end = next((other.start for other in sections
                        if other.start > section.start and other.level <= section.level), len(lines))
            out += [f"来源：`{project.name}/大纲/{volume.name}`", "", *lines[section.start:end], ""]
    if not out:
        raise SystemExit(f"ERROR: 卷纲里找不到章节范围覆盖第{first}-{last}章的剧情单元卡（卡标题下一行写"
                         "「> 作用域：单元级 {单元ID}」，卡里写「- 章节范围：第A-B章」），先补卷纲，"
                         "再用 outline_view.py --check --strict 核对")
    missing = [str(chapter) for chapter, count in coverage.items() if count == 0]
    duplicate = [str(chapter) for chapter, count in coverage.items() if count > 1]
    if missing or duplicate:
        raise SystemExit(f"ERROR: 卷纲剧情单元缺覆盖：{','.join(missing) or '无'}；"
                         f"重复覆盖：{','.join(duplicate) or '无'}；每章必须只属一张卡，先修卷纲")
    return out


# ---------- 拼包 ----------

def render(project: Path, first: int, last: int, blocks: list[str]) -> str:
    head = (f"# 任务包：反推第{first}-{last}章细纲（导入）\n\n"
            f"只交付 `{project.name}/大纲/细纲_第{first:03d}章.md` 到 `细纲_第{last:03d}章.md`，每章一个文件（已有的同名文件按本包重写覆盖）；"
            f"不改正文、卷纲和 `设定/`，不建 `追踪/`。证据用下方每章的摘要要点，不整读拆文库摘要；某个字段要点里没有、"
            f"又必须写实际内容时，只回看该章正文的相关段落。作者已定的事在 `{project.name}/.story/work/导入记录.md`；"
            "不要另读本包以外的写作技法文件。交付后只回：写了哪些文件、每章一句核心事件、"
            "证据不足标了 [待补充] 的要点（没有写「无」）。\n\n"
            "包里提到的检查由主会话在你交付后跑，你不执行命令；需要的测量结果已放进包里。")
    parts = [head, f"\n## 本批章节\n\n路径相对项目根（`{project.parent}`）。\n\n" + "\n\n".join(blocks),
             "\n## 卷纲剧情单元（覆盖本批）\n\n" + "\n".join(unit_cards(project, first, last)).rstrip(),
             "\n---\n\n<!-- 资料：outline-reverse-rules.md -->\n\n" + RULES.read_text(encoding="utf-8").lstrip("﻿").strip()]
    return "\n".join(parts) + "\n"


def build(project: Path, analysis: Path, first: int, last: int) -> dict:
    if not RULES.is_file():
        raise SystemExit(f"ERROR: 缺少 reference：{RULES}")
    fixed = weight(render(project, first, last, []))  # 包头、剧情单元卡与规则：章数减少只会更少
    blocks: list[str] = []
    lengths: dict[int, int] = {}
    missing: list[int] = []
    load, extra_reading = fixed, 0
    for chapter in range(first, last + 1):
        block, actual, extra, absent = chapter_block(project, analysis, chapter, first)
        cost = weight(block) + extra
        if blocks and load + cost > LOAD_LIMIT:
            break  # 包已够大：本章留给下一批
        blocks.append(block)
        lengths[chapter] = actual
        load += cost
        extra_reading += extra
        if absent:
            missing.append(chapter)
    end = first + len(blocks) - 1
    text = render(project, first, end, blocks)
    return {"text": text, "end": end, "lengths": lengths, "missing": missing,
            "chars": weight(text) + extra_reading}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="拼出导入长篇逐批反推细纲的任务包")
    parser.add_argument("--project", required=True, type=Path, help="书目录（{导入书名}/）")
    parser.add_argument("--chapters", required=True, help="章节范围 A-B，请求 10–20 章；包过大时自动少排")
    parser.add_argument("--analysis", type=Path, help="拆文库目录，默认 书目录的上一级/拆文库/{书目录名}")
    args = parser.parse_args(argv)
    try:
        project = args.project.resolve()
        if not project.is_dir():
            raise SystemExit(f"ERROR: 书目录不存在：{args.project}")
        first, last = parse_range(args.chapters)
        final = last_body_chapter(project)
        if last > final:
            raise SystemExit(f"ERROR: 正文只迁到第{final}章，范围超出")
        check_batch_size(first, last, final)
        analysis = (args.analysis or project.parent / "拆文库" / project.name).resolve()
        result = build(project, analysis, first, last)
    except SystemExit as exc:
        emit(str(exc), sys.stderr)
        return 2
    end = result["end"]
    out_dir = project.joinpath(*WORK_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"导入细纲_第{first:03d}-{end:03d}章.md"
    out.write_text(result["text"], encoding="utf-8")
    emit(json.dumps({"brief": str(out), "chapters": f"{first}-{end}",
                     "next": end + 1 if end < final else None, "chars": result["chars"], "limit": LOAD_LIMIT,
                     "metric": METRIC, "lengths": {str(k): v for k, v in result["lengths"].items()},
                     "missing_summaries": result["missing"]},
                    ensure_ascii=False), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
