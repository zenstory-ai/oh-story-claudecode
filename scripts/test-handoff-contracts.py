#!/usr/bin/env python3
"""拆文、扫榜产物与下游读取方之间的交接契约。

产出方以模板或脚本为准，读取方以它在文档里点名的小节、字段、列名和取值为准，
逐条断言：读取方点名的东西在产出方模板里真实存在。覆盖：

- 长篇拆文报告：各读取方用 `拆文报告.md`「小节」点名的小节；文风生成引用的小节；
  快速预览与拆文报告同名的两节；story-explorer 从黄金三章深度拆解读的字段。
- 情绪模块卡：门禁字段以 inspiration_index.py 的 EM_REQUIRED_FIELDS 为准，
  Stage 3 模板卡要能被同一个解析器读出全部门禁字段；长篇写前召回、作者报告、
  story-explorer 点名的字段要对得上。
- 节奏索引：长篇写前召回的 rhythm_reference 和 story-explorer 点名的列/表要在 节奏.md 模板里。
- 短篇拆文：情节节点模板要有写作端点名的节点字段；genre_detected 的每个取值在写作端题材映射表里；
  导入短篇读的拆文报告小节存在；写作端和导入读的 `_meta.json` 键在 output-contract 的 schema 里。
- 短篇扫榜：选题匹配推荐的目标平台要被写作端的设计模板和 check-phase2-contract.js 接受，
  扫榜支持的每个平台都在对照表里；写作端 Phase 1 读结论文件点名的小节和「复扫日期」在模板里，
  扫榜情绪对照表与选题匹配的目标情绪只用写作端情绪表的六种，难度与写作端一致。
- 长篇扫榜：拆文回填和写作开书点名的选题决策小节、字段在模板里；「待拆文验证」和「能爆的原因」同一行；
  文件落在拆文端会去找的 `扫榜/{YYYYMMDD}/`。
- 派助手：路由派 story-explorer / story-researcher 的 prompt 字段和查询类型在助手模板里；
  审稿给短篇写「无追踪」时 consistency-checker 有短篇分支。
- 导入短篇 → 短篇写作构思检查：导入的 `设定.md` 模板有写作端模板的全部小节和基本信息、设计校验字段；
  照导入模板填好的设定和小节大纲跑 check-phase2-contract.js，只剩导入约定留给构思时定的两项。
- 导入长篇 → 长篇写作：导入卷纲模板原样落盘过写作端 outline_view.py 的严格检查，按单元取得到卡，
  卡里有写正文组装脚本要读的单元字段；细纲检查脚本回报的模板出处在各副本所在 skill 里真实存在。
- 写作端「目标平台」→ 审稿平台表：长篇题材定位、短篇设定模板、导入 Phase 1 能写的每个平台，
  都按篇幅出现在审稿的平台映射表里，映射到的平台表文件存在；审稿派 consistency-checker 时给出模板要的字段。
- 去味 → 写手：检测器的每个类别都在 expression 的提示索引里、blocking 加粗与检测器一致；
  各调用方派写手去味时的任务标签写手认得，点名的 deslop-gates 小节存在。

最后用几组改坏的输入确认断言真的会报错。
"""

from __future__ import annotations

import json
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LONG_ANALYZE = "skills/story-long-analyze"
AUTHOR_FACING = f"{LONG_ANALYZE}/references/author-facing.md"
STAGE1 = f"{LONG_ANALYZE}/references/stage1-golden-chapters.md"
STAGE3 = f"{LONG_ANALYZE}/references/stage3-plot-rhythm.md"
STAGE5 = f"{LONG_ANALYZE}/references/stage5-report.md"
STYLE_GENERATOR = f"{LONG_ANALYZE}/references/style-profile-generator.md"
INSPIRATION_INDEX = f"{LONG_ANALYZE}/scripts/inspiration_index.py"
LONG_RECALL = "skills/story-long-write/references/benchmark-recall.md"
EXPLORER_LOAD = "skills/story-setup/references/agent-references/benchmark-style-load.md"
IMPORT_LONG = "skills/story-import/references/structure-mapping-long.md"
IMPORT_SHORT = "skills/story-import/references/structure-mapping-short.md"

SHORT_ANALYZE_SKILL = "skills/story-short-analyze/SKILL.md"
SHORT_GENRES = "skills/story-short-analyze/references/analysis-short-genres.md"
SHORT_STAGE23 = "skills/story-short-analyze/references/stage2-3-structure-emotion.md"
SHORT_STAGE46 = "skills/story-short-analyze/references/stage4-6-reversal-summary.md"
SHORT_CONTRACT = "skills/story-short-analyze/references/output-contract.md"
IMPORT_DEEP = "skills/story-import/references/deep-analysis.md"
SHORT_RECALL = "skills/story-short-write/references/benchmark-recall.md"
SHORT_DESIGN = "skills/story-short-write/references/workflow-design.md"
SHORT_DRAFT = "skills/story-short-write/references/workflow-draft.md"
PHASE2_CHECK = "skills/story-short-write/scripts/check-phase2-contract.js"
SHORT_SCAN_SKILL = "skills/story-short-scan/SKILL.md"
TOPIC_MATCH = "skills/story-short-scan/references/topic-match.md"

# 读长篇拆文报告的文件：长篇写作、长篇扫榜、导入长篇、story-setup 部署给 agent 的资料。
LONG_REPORT_CONSUMER_GLOBS = (
    "skills/story-long-write/**/*.md",
    "skills/story-long-scan/**/*.md",
    "skills/story-setup/references/agent-references/*.md",
    "skills/story-setup/references/templates/agents/*.md",
    "skills/story-review/**/*.md",
    "skills/story-import/SKILL.md",
    IMPORT_LONG,
    STYLE_GENERATOR,
    STAGE5,
)
# 读短篇拆文报告的文件。
SHORT_REPORT_CONSUMER_GLOBS = (
    "skills/story-short-write/**/*.md",
    IMPORT_SHORT,
)

# `拆文报告.md`「小节」「小节」，可带「小节」的「字段」。
REPORT_REF_RE = re.compile(
    r"拆文报告(?:\.md)?`?((?:「[^」]+」[、与和及]?)+)(?:的「([^」]+)」)?"
)
QUOTED_RE = re.compile(r"「([^」]+)」")
# 「拆文报告·核心发现第 N 条」这类回填依据写法。
REPORT_CITE_RE = re.compile(r"拆文报告·([\u4e00-\u9fff]+?)第")
# Stage 3 模板标题：「### Stage 3 节奏.md」或「## 5. 节奏.md」都认。
EM_TEMPLATE_HEADING = r"^#{2,3}\s+(?:Stage 3\s+|\d+\.\s*)?情绪模块\.md"
RHYTHM_TEMPLATE_HEADING = r"^#{2,3}\s+(?:Stage 3\s+|\d+\.\s*)?节奏\.md"


class Repo:
    """读仓库文件；负例测试用 overrides 换掉个别文件的内容。"""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.overrides = overrides or {}

    def text(self, rel: str) -> str:
        if rel in self.overrides:
            return self.overrides[rel]
        path = ROOT / rel
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def glob(self, patterns: tuple[str, ...]) -> list[str]:
        found: set[str] = set()
        for pattern in patterns:
            for path in ROOT.glob(pattern):
                if path.is_file():
                    found.add(path.relative_to(ROOT).as_posix())
        found.update(rel for rel in self.overrides if any(Path(rel).match(p) for p in patterns))
        return sorted(found)


# ---------- 通用解析 ----------


def fenced_block_after(text: str, heading_re: str) -> str:
    """返回 heading_re 所在行之后第一个代码围栏里的内容；找不到返回空串。"""
    match = re.search(heading_re, text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    opening = re.search(r"^```[^\n]*\n", rest, re.M)
    if not opening:
        return ""
    body = rest[opening.end():]
    closing = re.search(r"^```\s*$", body, re.M)
    return body[: closing.start()] if closing else body


def headings(text: str) -> list[str]:
    return [m.group(2).strip() for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.M)]


def table_header_cells(text: str) -> list[str]:
    """Markdown 表头行（下一行是分隔行）里的所有单元格。"""
    lines = text.splitlines()
    cells: list[str] = []
    for i, line in enumerate(lines[:-1]):
        if line.strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            cells.extend(c.strip() for c in line.strip().strip("|").split("|") if c.strip())
    return cells


def tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """返回 [(表头, 行列表)]。"""
    lines = text.splitlines()
    result: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i].strip()
        if line.startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            header = [c.strip() for c in line.strip("|").split("|")]
            rows: list[list[str]] = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            result.append((header, rows))
            i = j
        else:
            i += 1
    return result


def section_body(text: str, title: str) -> str:
    """标题为 title 的小节正文，到下一个同级或更高级标题为止。"""
    match = re.search(rf"^(#{{1,6}})\s+{re.escape(title)}\s*$", text, re.M)
    if not match:
        return ""
    level = len(match.group(1))
    rest = text[match.end():]
    nxt = re.search(rf"^#{{1,{level}}}\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def split_terms(raw: str, seps: str) -> list[str]:
    return [t.strip() for t in re.split(f"[{seps}]", raw) if t.strip()]


def line_no(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# ---------- 长篇拆文报告 ----------


def long_report_template(repo: Repo) -> tuple[str, str]:
    text = repo.text(AUTHOR_FACING)
    return (
        fenced_block_after(text, r"^## 拆文报告\.md\s*$"),
        fenced_block_after(text, r"^## 快速预览\.md\s*$"),
    )


def check_long_report(repo: Repo) -> list[str]:
    failures: list[str] = []
    report, preview = long_report_template(repo)
    if not report:
        return [f"{AUTHOR_FACING}: 找不到「## 拆文报告.md」下的报告模板代码块"]
    report_headings = set(headings(report))
    read_sections: dict[str, str] = {}

    for rel in repo.glob(LONG_REPORT_CONSUMER_GLOBS):
        text = repo.text(rel)
        for match in REPORT_REF_RE.finditer(text):
            where = f"{rel}:{line_no(text, match.start())}"
            sections = QUOTED_RE.findall(match.group(1))
            for section in sections:
                read_sections.setdefault(section, where)
            field = match.group(2)
            if field and sections:
                owner = sections[-1]
                body = section_body(report, owner)
                if owner in report_headings and not re.search(rf"(^|[|\s]){re.escape(field)}\s*[：:|]", body, re.M):
                    failures.append(f"{where}: 读拆文报告「{owner}」里的「{field}」，模板该节没写这一项")
        for match in REPORT_CITE_RE.finditer(text):
            read_sections.setdefault(match.group(1), f"{rel}:{line_no(text, match.start())}")
    if not read_sections:
        failures.append("长篇读取方里一处 `拆文报告.md`「小节」引用都没找到，检查正则或读取方清单")

    # 文风生成：报告「文风一句话」回填；「写法技巧 Top 5」「可借鉴套路 Top 3」摘入文风。
    style = repo.text(STYLE_GENERATOR)
    style_refs = re.findall(r"报告「([^」]+)」", style) + re.findall(r"([\u4e00-\u9fff]+) Top \d+", style)
    if not style_refs:
        failures.append(f"{STYLE_GENERATOR}: 没找到它引用的拆文报告小节，确认读取写法后更新本测试")
    for section in style_refs:
        read_sections.setdefault(section, STYLE_GENERATOR)

    for section, where in sorted(read_sections.items(), key=lambda kv: kv[1]):
        if section not in report_headings:
            failures.append(f"{where}: 读拆文报告「{section}」，报告模板没有这一节")

    # 报告模板写明「有下游在读、保留原名」的小节，要覆盖所有被读的小节。
    note = re.search(r"有下游在读[^：\n]*：([^\n]+)", repo.text(AUTHOR_FACING))
    if not note:
        failures.append(f"{AUTHOR_FACING}: 拆文报告模板前缺「有下游在读、保留原名」的小节清单")
    else:
        protected = set(QUOTED_RE.findall(note.group(1)))
        for section in protected - report_headings:
            failures.append(f"{AUTHOR_FACING}: 保留清单里的「{section}」在报告模板里不存在")
        for section, where in sorted(read_sections.items(), key=lambda kv: kv[1]):
            if section in report_headings and section not in protected:
                failures.append(f"{AUTHOR_FACING}: 「{section}」被 {where} 读取，没写进「有下游在读、保留原名」清单")

    # 快速预览说明里约定与拆文报告同名的小节，两边模板都要有。
    shared = re.search(r"沿用((?:「[^」]+」)+)两节的同名同结构", repo.text(AUTHOR_FACING))
    if not shared:
        failures.append(f"{AUTHOR_FACING}: 「快速预览.md」说明里没找到与拆文报告同名的小节约定，确认写法后更新本测试")
    else:
        preview_headings = set(headings(preview))
        for section in QUOTED_RE.findall(shared.group(1)):
            if section not in report_headings or section not in preview_headings:
                failures.append(f"{AUTHOR_FACING}: 约定与拆文报告同名的「{section}」，快速预览和报告模板没有都写")

    # story-explorer 从黄金三章深度拆解读的字段要在 Stage 1 模板里。
    explorer = repo.text(EXPLORER_LOAD)
    match = re.search(r"深度拆解\.md` 存在，再读取并提取((?:「[^」]+」)+)", explorer)
    if not match:
        failures.append(f"{EXPLORER_LOAD}: 没找到从深度拆解读取的字段，确认读取写法后更新本测试")
    else:
        stage1 = repo.text(STAGE1)
        for field in QUOTED_RE.findall(match.group(1)):
            if not re.search(rf"\*\*{re.escape(field)}\*\*", stage1):
                failures.append(f"{EXPLORER_LOAD}: 从深度拆解读「{field}」，Stage 1 深度拆解模板没有这一项")
    return failures


# ---------- 情绪模块卡 ----------


def check_em_cards(repo: Repo) -> list[str]:
    failures: list[str] = []
    module = runpy.run_path(str(ROOT / INSPIRATION_INDEX), run_name="handoff_contracts")
    required = tuple(module["EM_REQUIRED_FIELDS"])
    template = fenced_block_after(repo.text(STAGE3), EM_TEMPLATE_HEADING)
    if not template:
        return [f"{STAGE3}: 找不到「情绪模块.md」模板标题下的模板代码块"]

    cards, _index, problems = module["parse_em_module"](template)
    if not cards:
        failures.append(f"{STAGE3}: inspiration_index 从情绪模块模板里解析不出 EM 卡")
    for card in cards:
        missing = [f for f in required if not card.get(f, "").strip()]
        if missing:
            failures.append(f"{STAGE3}: 模板卡 {card.get('em_id')} 缺门禁字段 {'、'.join(missing)}")
    for problem in problems:
        failures.append(f"{STAGE3}: inspiration_index 解析模板报问题 {problem}")

    vocabulary = set(required) | set(headings(template)) | set(table_header_cells(template))
    for card in cards:
        vocabulary.update(k for k in card if k not in ("em_id", "title"))

    def exact(rel: str, pattern: str, label: str) -> None:
        text = repo.text(rel)
        match = re.search(pattern, text)
        if not match:
            failures.append(f"{rel}: 没找到{label}的字段清单，确认读取写法后更新本测试")
            return
        named = split_terms(match.group(1), "、，,")
        where = f"{rel}:{line_no(text, match.start())}"
        extra = [n for n in named if n not in required]
        absent = [f for f in required if f not in named]
        if extra or absent:
            failures.append(
                f"{where}: {label}字段应与 EM_REQUIRED_FIELDS（{'、'.join(required)}）一致；"
                f"多出 {'、'.join(extra) or '无'}，缺 {'、'.join(absent) or '无'}"
            )

    exact(LONG_RECALL, r"`selected_emotion_module`（([^）]+)）", "写前召回 selected_emotion_module ")

    def known(rel: str, pattern: str, label: str, seps: str) -> None:
        text = repo.text(rel)
        match = re.search(pattern, text)
        if not match:
            failures.append(f"{rel}: 没找到{label}，确认读取写法后更新本测试")
            return
        where = f"{rel}:{line_no(text, match.start())}"
        for term in split_terms(match.group(1), seps):
            if not any(term in v for v in vocabulary):
                failures.append(f"{where}: {label}点名「{term}」，情绪模块.md 模板里没有这个字段或小节")

    known(EXPLORER_LOAD, r"从([^。\n]+?)中选择 1 条 `selected_emotion_module`", "情绪模块取材范围", "、或")
    known(EXPLORER_LOAD, r'"selected_emotion_module": "<从 剧情/情绪模块\.md 选出的([^；>"]+)', "selected_emotion_module 字段说明", "/、")
    return failures


# ---------- 节奏索引 ----------


def check_rhythm(repo: Repo) -> list[str]:
    failures: list[str] = []
    template = fenced_block_after(repo.text(STAGE3), RHYTHM_TEMPLATE_HEADING)
    if not template:
        return [f"{STAGE3}: 找不到「节奏.md」模板标题下的模板代码块"]
    columns = set(table_header_cells(template))
    titles = set(headings(template))

    text = repo.text(LONG_RECALL)
    match = re.search(r"`rhythm_reference`（([^）]+)）", text)
    if not match:
        failures.append(f"{LONG_RECALL}: 没找到 rhythm_reference 的组成说明，确认读取写法后更新本测试")
    else:
        where = f"{LONG_RECALL}:{line_no(text, match.start())}"
        for step in split_terms(match.group(1), "→"):
            if step not in columns and not any(step in t for t in titles):
                failures.append(f"{where}: rhythm_reference 点名「{step}」，节奏.md 模板里没有这一列或这张表")

    explorer = repo.text(EXPLORER_LOAD)
    match = re.search(r"从([^。\n]+?)中选择 1 条 `rhythm_reference`", explorer)
    if not match:
        failures.append(f"{EXPLORER_LOAD}: 没找到节奏取材范围，确认读取写法后更新本测试")
    else:
        where = f"{EXPLORER_LOAD}:{line_no(explorer, match.start())}"
        vocabulary = columns | titles
        for term in split_terms(match.group(1), "、/"):
            if not any(term in v for v in vocabulary):
                failures.append(f"{where}: 节奏取材点名「{term}」，节奏.md 模板里没有对应的列或表")

    # 导入写题材定位时按编号引用节奏与情绪模块的条目。
    importer = repo.text(IMPORT_LONG)
    em_template = fenced_block_after(repo.text(STAGE3), EM_TEMPLATE_HEADING)
    for prefix_group, source, label in (
        (r"\{(RH/TR) 编号\}", template, "节奏.md"),
        (r"\{(EM)-001 等\}", em_template, "情绪模块.md"),
    ):
        match = re.search(prefix_group, importer)
        if not match:
            failures.append(f"{IMPORT_LONG}: 没找到按编号引用{label}的列，确认读取写法后更新本测试")
            continue
        for prefix in match.group(1).split("/"):
            if not re.search(rf"\b{prefix}-\d{{3}}", source):
                failures.append(f"{IMPORT_LONG}: 引用 {prefix} 编号，{label} 模板里没有 {prefix}-xxx 条目")
    return failures


# ---------- 短篇拆文 ----------


def check_short_analyze(repo: Repo) -> list[str]:
    failures: list[str] = []

    # 情节节点：写作端点名的节点字段要在节点模板里。
    node_template = fenced_block_after(repo.text(SHORT_STAGE23), r"^### 节点模板")
    if not node_template:
        failures.append(f"{SHORT_STAGE23}: 找不到「### 节点模板」下的模板代码块")
    else:
        labels = set(re.findall(r"([一-鿿]{2,4})\{", node_template))
        text = repo.text(SHORT_RECALL)
        match = re.search(r"`情节节点\.md` 看每个节点的([^，。\n]+)", text)
        if not match:
            failures.append(f"{SHORT_RECALL}: 没找到读情节节点的字段说明，确认读取写法后更新本测试")
        else:
            where = f"{SHORT_RECALL}:{line_no(text, match.start())}"
            for term in split_terms(match.group(1), "、和"):
                if term in node_template or any(label in term for label in labels):
                    continue
                failures.append(
                    f"{where}: 读情节节点的「{term}」，节点模板里没有这一项（模板字段：{'、'.join(sorted(labels))}）"
                )

    # genre_detected：拆文能写出的每个题材值，写作端映射表都要认得。
    # 取值来源：analysis-short-genres.md「题材路由」表第一列，加 SKILL.md 规定的兜底值。
    skill = repo.text(SHORT_ANALYZE_SKILL)
    produced: list[str] = []
    routing = section_body(repo.text(SHORT_GENRES), "题材路由")
    for header, rows in tables(routing):
        if header and header[0] == "类型":
            produced += [row[0] for row in rows if row and row[0]]
    produced += re.findall(r'扫不到(?:则 genre_detected = |写)[「"]([^」"]+)[」"]', skill)
    if not produced:
        failures.append(f"{SHORT_GENRES}: 没从「题材路由」表解析出 genre_detected 的取值，确认写法后更新本测试")
    recall = repo.text(SHORT_RECALL)
    mapping = next((rows for header, rows in tables(recall) if header and "genre_detected" in header[0]), None)
    if mapping is None:
        failures.append(f"{SHORT_RECALL}: 没找到 genre_detected → 题材包 映射表")
    else:
        accepted: set[str] = set()
        for row in mapping:
            accepted.update(split_terms(re.sub(r"[`]", "", row[0]), "/、（）() "))
        for genre in produced:
            if genre not in accepted:
                failures.append(f"{SHORT_RECALL}: genre_detected 可能取「{genre}」，题材包映射表里没有")

    # 导入短篇读的拆文报告小节。
    short_titles: set[str] = set()
    for rel in (SHORT_STAGE23, SHORT_STAGE46):
        source = repo.text(rel)
        marker = source.find("## 输出模板")
        short_titles.update(headings(source[marker:] if marker >= 0 else source))
    for rel in repo.glob(SHORT_REPORT_CONSUMER_GLOBS):
        text = repo.text(rel)
        for match in REPORT_REF_RE.finditer(text):
            where = f"{rel}:{line_no(text, match.start())}"
            for section in QUOTED_RE.findall(match.group(1)):
                for part in split_terms(section, "/"):
                    if not any(part in title for title in short_titles):
                        failures.append(f"{where}: 读短篇拆文报告「{section}」，Stage 2-6 输出模板里没有「{part}」这一节")

    # 写作端与导入读的 `_meta.json` 键要在 output-contract 的 schema 模板里。
    schema = fenced_block_after(repo.text(SHORT_CONTRACT), r"^## `_meta\.json` schema")
    keys = set(re.findall(r'"([A-Za-z_]+)"\s*:', schema))
    if not keys:
        failures.append(f"{SHORT_CONTRACT}: 没解析出 `_meta.json` schema 模板的键，确认写法后更新本测试")
    else:
        named = 0
        for rel in (SHORT_RECALL, IMPORT_DEEP):
            text = repo.text(rel)
            for line_match in re.finditer(r"^.*_meta\.json.*$", text, re.M):
                for token in re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", line_match.group(0)):
                    token = (token[len("_meta.json"):] if token.startswith("_meta.json") else token).lstrip(".")
                    if not token or token.endswith(".json"):
                        continue
                    named += 1
                    for part in token.split("."):
                        if part not in keys:
                            where = f"{rel}:{line_no(text, line_match.start())}"
                            failures.append(f"{where}: 读 `_meta.json` 的「{part}」，output-contract 的 schema 里没有这个键")
        if not named:
            failures.append(f"{SHORT_RECALL}: 没找到读取 `_meta.json` 键的写法，确认读取写法后更新本测试")
    return failures


# ---------- 短篇扫榜 → 写作平台 ----------


def check_short_platforms(repo: Repo) -> list[str]:
    failures: list[str] = []

    design = repo.text(SHORT_DESIGN)
    match = re.search(r"- 目标平台：\{([^}]+)\}", design)
    if not match:
        return failures + [f"{SHORT_DESIGN}: 没找到设定模板的「目标平台」取值，确认写法后更新本测试"]
    choices = split_terms(match.group(1), "/")
    node = shutil.which("node")
    if node is None:
        return failures + [f"{PHASE2_CHECK}: 需要 node 执行目标平台交接检查"]
    runner = """
const fs = require('fs')
const path = require('path')
const { verify } = require(process.argv[1])
const project = process.argv[2]
const platforms = JSON.parse(process.argv[3])
const accepted = platforms.filter(platform => {
  fs.writeFileSync(path.join(project, '设定.md'), `- 目标平台：${platform}\\n`)
  return verify(project).checks.some(check => check.id === 'phase2.platform-declared' && check.ok)
})
process.stdout.write(JSON.stringify(accepted))
"""
    with tempfile.TemporaryDirectory(prefix="short-platforms-") as tmp:
        verifier = Path(tmp) / "check-phase2-contract.js"
        verifier.write_text(repo.text(PHASE2_CHECK), encoding="utf-8")
        (Path(tmp) / "小节大纲.md").write_text("# 小节大纲\n", encoding="utf-8")
        run = subprocess.run([node, "-e", runner, str(verifier), tmp, json.dumps(choices)],
                             capture_output=True, encoding="utf-8")
    try:
        accepted = set(json.loads(run.stdout))
    except (ValueError, TypeError):
        return failures + [f"{PHASE2_CHECK}: 平台检查输出读不出来：{run.stderr.strip()[:200]}"]
    for choice in choices:
        if choice not in accepted:
            failures.append(f"{SHORT_DESIGN}: 目标平台可选「{choice}」，check-phase2-contract.js 不认")

    topic = repo.text(TOPIC_MATCH)
    mapping = None
    for header, rows in tables(topic):
        target_cols = [i for i, cell in enumerate(header) if "目标平台" in cell and i > 0]
        if target_cols:
            mapping = (header, rows, target_cols[0])
            break
    if mapping is None:
        failures.append(f"{TOPIC_MATCH}: 缺少「扫榜平台 → 写作目标平台」对照表（表头含「目标平台」的一列）")
        return failures
    header, rows, col = mapping
    covered: set[str] = set()
    for row in rows:
        if len(row) <= col:
            continue
        covered.update(split_terms(row[0], "/、 "))
        for target in split_terms(row[col], "/、"):
            target = re.sub(r"[（(].*$", "", target).strip()
            if target not in choices:
                failures.append(
                    f"{TOPIC_MATCH}: 对照表把「{row[0]}」推荐到「{target}」，写作端设定模板只认 {' / '.join(choices)}"
                )
            elif target not in accepted:
                failures.append(f"{TOPIC_MATCH}: 对照表目标平台「{target}」过不了 check-phase2-contract.js")

    described = re.search(r"分析(.+?)等平台", repo.text(SHORT_SCAN_SKILL))
    if not described:
        failures.append(f"{SHORT_SCAN_SKILL}: 没从 description 解析出扫榜平台，确认写法后更新本测试")
    else:
        for platform in split_terms(described.group(1), "、"):
            if not any(platform in name or name in platform for name in covered):
                failures.append(f"{TOPIC_MATCH}: 扫榜支持「{platform}」，对照表里没有这一行")
    return failures


# ---------- 短篇扫榜结论 → 写作端 Phase 1 ----------

SHORT_WRITE_SKILL = "skills/story-short-write/SKILL.md"


def short_write_emotions(repo: Repo) -> dict[str, str]:
    """写作端 Phase 1 情绪表：情绪 → 难度。"""
    for header, rows in tables(repo.text(SHORT_WRITE_SKILL)):
        if header and header[0] == "情绪类型" and "难度" in header:
            col = header.index("难度")
            return {row[0]: row[col] for row in rows if len(row) > col}
    return {}


def check_short_scan_handoff(repo: Repo) -> list[str]:
    failures: list[str] = []
    topic = repo.text(TOPIC_MATCH)
    template = fenced_block_after(topic, r"^## 短篇扫榜结论\.md 模板")
    if not template:
        return [f"{TOPIC_MATCH}: 没找到「短篇扫榜结论.md 模板」的代码块，确认写法后更新本测试"]

    # 写作端按文件名找结论，读点名的小节和「复扫日期」。
    write = repo.text(SHORT_WRITE_SKILL)
    read_line = re.search(r"^.*`短篇扫榜结论\.md`.*$", write, re.M)
    if not read_line:
        failures.append(f"{SHORT_WRITE_SKILL}: 没找到读取 `短篇扫榜结论.md` 的写法，确认读取写法后更新本测试")
    else:
        where = f"{SHORT_WRITE_SKILL}:{line_no(write, read_line.start())}"
        for name in QUOTED_RE.findall(read_line.group(0)):
            if not re.search(rf"^##\s+{re.escape(name)}\s*$", template, re.M):
                failures.append(f"{where}: 读结论文件的「{name}」，topic-match 模板里没有这一节")
        if "复扫日期" in read_line.group(0) and not re.search(r"^- 复扫日期：", template, re.M):
            failures.append(f"{where}: 读结论文件的「复扫日期」，topic-match 模板文件头里没有这个字段")
    if "`短篇扫榜结论.md`" not in repo.text(SHORT_SCAN_SKILL):
        failures.append(f"{SHORT_SCAN_SKILL}: 没写结论落到 `短篇扫榜结论.md`，写作端按这个文件名找")

    # 选题时读 `征稿要求.md`：存这份文件的写法要在 SKILL 里。平台参考只读所选的那份，
    # 写在某个平台参考里，选了别的平台的作者发来的征稿要求就不会落盘。
    skill = repo.text(SHORT_SCAN_SKILL)
    if "`征稿要求.md`" in skill and not re.search(r"^.*存进.*`征稿要求\.md`.*$", skill, re.M):
        failures.append(f"{SHORT_SCAN_SKILL}: 选题时读 `征稿要求.md`，SKILL 里没写把征稿要求存进这个文件")

    # 目标情绪与难度以写作端 Phase 1 情绪表为准。
    emotions = short_write_emotions(repo)
    if not emotions:
        return failures + [f"{SHORT_WRITE_SKILL}: 没解析出 Phase 1 情绪表（表头「情绪类型 … 难度」），确认写法后更新本测试"]
    scan_table = None
    for header, rows in tables(repo.text(SHORT_SCAN_SKILL)):
        if header and header[0] == "情绪" and "难度" in header:
            scan_table = (rows, header.index("难度"))
            break
    if scan_table is None:
        failures.append(f"{SHORT_SCAN_SKILL}: 缺少情绪对照表（表头「情绪 … 难度」）")
    else:
        rows, col = scan_table
        seen = set()
        for row in rows:
            name = row[0]
            seen.add(name)
            if name not in emotions:
                failures.append(f"{SHORT_SCAN_SKILL}: 情绪对照表的「{name}」不在写作端情绪表里（{' / '.join(emotions)}）")
            elif len(row) > col and row[col] != emotions[name]:
                failures.append(f"{SHORT_SCAN_SKILL}: 「{name}」难度写成「{row[col]}」，写作端是「{emotions[name]}」")
        for name in emotions:
            if name not in seen:
                failures.append(f"{SHORT_SCAN_SKILL}: 情绪对照表缺写作端的「{name}」")
    match = re.search(r"^- 目标情绪：\{([^}]+)\}", template, re.M)
    if not match:
        failures.append(f"{TOPIC_MATCH}: 模板缺「- 目标情绪：{{…}}」，写作端拿它当候选情绪")
    else:
        for choice in split_terms(re.sub(r"[，,].*$", "", match.group(1)), "/"):
            if choice not in emotions:
                failures.append(f"{TOPIC_MATCH}: 目标情绪可选「{choice}」，写作端情绪表里没有")
    return failures



# ---------- 长篇扫榜选题决策 → 拆文回填、写作开书 ----------

LONG_SCAN_SKILL = "skills/story-long-scan/SKILL.md"
TOPIC_DECISION = "skills/story-long-scan/references/topic-decision.md"
LONG_ANALYZE_SKILL = f"{LONG_ANALYZE}/SKILL.md"
LONG_WRITE_SETUP = "skills/story-long-write/references/workflow-setup.md"

# 读取方点名的选题决策小节或字段：(读取方, 原文里的写法, 模板里的名字)。
# 写法找不到说明读取方改了读法，提醒更新本表；名字找不到说明模板改名，下游会静默断开。
TOPIC_READS = (
    (LONG_WRITE_SETUP, "「推荐选题」", "推荐选题"),
    (LONG_WRITE_SETUP, "`扫榜日期`", "扫榜日期"),
    (LONG_WRITE_SETUP, "能爆的原因 Y", "能爆的原因"),
    (LONG_WRITE_SETUP, "差异化 Z", "差异化定位"),
    (STAGE5, "「推荐选题」", "推荐选题"),
    (STAGE5, "「能爆的原因」", "能爆的原因"),
    (STAGE5, "「题材组合」", "题材组合"),
    (LONG_ANALYZE_SKILL, "「推荐选题」", "推荐选题"),
)


def check_long_scan_handoff(repo: Repo) -> list[str]:
    failures: list[str] = []
    topic = repo.text(TOPIC_DECISION)
    template = fenced_block_after(topic, r"^## 选题决策\.md 模板")
    if not template:
        return [f"{TOPIC_DECISION}: 没找到「选题决策.md 模板」的代码块，确认写法后更新本测试"]
    names = {re.sub(r"[：:].*$", "", h).strip() for h in headings(template)}
    names |= set(re.findall(r"^- ([^：\n]+)：", template, re.M))

    for rel, said, name in TOPIC_READS:
        if said not in repo.text(rel):
            failures.append(f"{rel}: 没找到读选题决策「{name}」的写法 {said}，确认读取写法后更新本测试")
        if name not in names:
            failures.append(f"{TOPIC_DECISION}: {rel} 读选题决策的「{name}」，模板里没有这一节或这个字段")

    # 拆文端只改「能爆的原因」那一行回填，标记必须和它在同一行。
    line = re.search(r"^- 能爆的原因：.*$", template, re.M)
    if not line or "`待拆文验证`" not in line.group(0):
        failures.append(f"{TOPIC_DECISION}: 模板「能爆的原因」那一行要带 `待拆文验证`，拆文端按这一行回填")
    for rel in (STAGE5, LONG_ANALYZE_SKILL):
        if "待拆文验证" not in repo.text(rel):
            failures.append(f"{rel}: 没找到按「待拆文验证」回填的写法，确认读取写法后更新本测试")

    # 拆文端去 `扫榜/*/选题决策.md` 找，扫榜端要把文件落在 `扫榜/{YYYYMMDD}/`。
    if "扫榜/*/选题决策.md" not in repo.text(STAGE5):
        failures.append(f"{STAGE5}: 没找到去 `扫榜/*/选题决策.md` 找文件的写法，确认读取写法后更新本测试")
    elif "扫榜/{YYYYMMDD}/" not in section_body(topic, "交付"):
        failures.append(f"{TOPIC_DECISION}: 拆文端去 `扫榜/*/选题决策.md` 找文件，交付一节没写落在 `扫榜/{{YYYYMMDD}}/`")

    # 写作端取「排在最前（可行性最高）」的推荐选题，模板要写明按可行性排序。
    if "可行性最高" in repo.text(LONG_WRITE_SETUP) and "按可行性排序" not in topic:
        failures.append(f"{TOPIC_DECISION}: 写作端取排在最前的选题当可行性最高，模板没写按可行性排序")
    return failures


# ---------- 导入短篇 → 短篇写作构思检查 ----------

# 导入把题材包的选择留给续写构思；补完这两项后，完整门禁必须通过。
IMPORT_SHORT_LEFT_FOR_DESIGN = {"phase2.genre-reference-declared", "phase2.genre-moves-declared"}
IMPORT_FIXTURE_VALUES = {
    "- 目标字数：": "- 目标字数：6000 字",
    "- 目标平台：": "- 目标平台：知乎盐言",
    "- 反转类型：": "- 反转类型：身份反转",
    "- 反转位置：": "- 反转位置：第 3 节 ÷ 共 4 节 = 75%",
    "- 付费点：": "- 付费点：第 2 节末",
    "- 反派设计：": "- 反派设计：不适用（家庭矛盾，没有单一反派）",
}


def import_short_fixture(template: str, outline_header: str) -> tuple[str, str]:
    """把导入的设定模板填成一份完本短篇（4 节、付费点在第 2 节末），再配一份小节大纲。"""
    lines = []
    for line in template.splitlines():
        prefix = next((key for key in IMPORT_FIXTURE_VALUES if line.startswith(key)), None)
        lines.append(IMPORT_FIXTURE_VALUES[prefix] if prefix else re.sub(r"\{[^}]*\}", "原文证据", line))
    cells = len(split_terms(outline_header, "|"))
    rows = []
    for section in range(1, 5):
        row = ["开头", "主事件", "她发现账单{发现}", "平静→怀疑"] + ["原文证据"] * (cells - 5) + ["1500"]
        row[7] = "付费点" if section == 2 else "下一节接上"
        rows.append("| " + " | ".join(row) + " |")
    outline = "\n".join([outline_header, "|" + "---|" * cells, *rows]) + "\n"
    return "\n".join(lines) + "\n", outline


def check_import_short(repo: Repo) -> list[str]:
    failures: list[str] = []
    design = fenced_block_after(repo.text(SHORT_DESIGN), r"^#### 设定\.md 模板")
    ours = fenced_block_after(repo.text(IMPORT_SHORT), r"^## 设定\.md 模板")
    if not design or not ours:
        return [f"{IMPORT_SHORT}: 没找到导入或写作端的 设定.md 模板代码块，确认写法后更新本测试"]
    have = set(headings(ours))
    for title in headings(design):
        if "（" not in title and title not in have:  # 带括号的是选用小节（贯穿道具、对标摘要）
            failures.append(f"{IMPORT_SHORT}: 设定模板缺写作端的「{title}」小节，续写构思会当成没写")
    for title in ("基本信息", "Phase 2 设计校验"):
        for label in re.findall(r"^- ([^：{\n]+)：", section_body(design, title), re.M):
            if not re.search(rf"^- {re.escape(label)}：", ours, re.M):
                failures.append(f"{IMPORT_SHORT}: 设定模板缺写作端「{title}」的「{label}」字段")

    node = shutil.which("node")
    header = re.search(r"^\| 结构段/五段功能 .*\|$", repo.text(IMPORT_SHORT), re.M)
    if node is None:
        print("跳过导入短篇构思检查夹具：没有 node")
        return failures
    if not header:
        return failures + [f"{IMPORT_SHORT}: 没找到小节大纲 12 列表头，确认写法后更新本测试"]
    settings, outline = import_short_fixture(ours, header.group(0))
    with tempfile.TemporaryDirectory(prefix="import-short-") as tmp:
        (Path(tmp) / "设定.md").write_text(settings, encoding="utf-8")
        (Path(tmp) / "小节大纲.md").write_text(outline, encoding="utf-8")
        run = subprocess.run([node, str(ROOT / PHASE2_CHECK), "--json", tmp],
                             capture_output=True, encoding="utf-8")
        completed = settings.replace("- 题材参考：[待补充]", "- 题材参考：references/genre-writing-formulas.md")
        completed = completed.replace("- 核心招式：[待补充]", "- 核心招式：证据递进；关系反转")
        (Path(tmp) / "设定.md").write_text(completed, encoding="utf-8")
        completed_run = subprocess.run([node, str(ROOT / PHASE2_CHECK), "--json", tmp],
                                       capture_output=True, encoding="utf-8")
    try:
        failed = {item["id"] for item in json.loads(run.stdout)["failures"]}
        completed_report = json.loads(completed_run.stdout)
    except (ValueError, KeyError):
        return failures + [f"{PHASE2_CHECK}: 输出读不出来：{run.stderr.strip()[:200]}"]
    if not IMPORT_SHORT_LEFT_FOR_DESIGN <= failed:
        failures.append(f"{IMPORT_SHORT}: 导入预留的题材参考与核心招式没有阻断构思门禁")
    for check_id in sorted(failed - IMPORT_SHORT_LEFT_FOR_DESIGN - {"phase2.no-template-placeholders"}):
        failures.append(f"{IMPORT_SHORT}: 照导入模板填好的设定过不了构思检查 {check_id}")
    if completed_run.returncode != 0 or not completed_report["ok"]:
        remaining = "、".join(item["id"] for item in completed_report["failures"])
        failures.append(f"{IMPORT_SHORT}: 只补题材参考与核心招式后仍过不了构思检查：{remaining}")
    # 导入承诺续写构思只补缺项：写作端构思要认「本书续写基线」并只补 [待补充]，写正文从下一节接着写。
    design_text = repo.text(SHORT_DESIGN)
    if "只补缺项" in repo.text(IMPORT_SHORT) and not ("本书续写基线" in design_text and "[待补充]" in design_text):
        failures.append(f"{SHORT_DESIGN}: 导入说续写构思只补缺项，构思步骤没写有「本书续写基线」时只补 [待补充]")
    draft_line = next((line for line in repo.text(SHORT_DRAFT).splitlines() if "**导入项目续写基线**" in line), "")
    if "第 N+1 节" not in draft_line:
        failures.append(f"{SHORT_DRAFT}: 导入的半成品要从下一节接着写，「导入项目续写基线」没写第 N+1 节")
    return failures


# ---------- 派助手：调用方 prompt → 助手模板 ----------

ROUTER = "skills/story/SKILL.md"
REVIEW_PROMPTS = "skills/story-review/references/agent-prompts.md"
AGENT_TEMPLATES = "skills/story-setup/references/templates/agents"
EXPLORER = f"{AGENT_TEMPLATES}/story-explorer.md"
RESEARCHER = f"{AGENT_TEMPLATES}/story-researcher.md"
CHECKER = f"{AGENT_TEMPLATES}/consistency-checker.md"


def prompt_keys(block: str) -> list[str]:
    """`键：{值}` 形式的 prompt 行里的键。"""
    return [m.group(1).strip() for m in re.finditer(r"^([^：:\n{]+)[：:]", block, re.M)]


def check_agent_dispatch(repo: Repo) -> list[str]:
    """路由派 explorer / researcher、审稿派 consistency-checker 时，prompt 字段要是模板认的字段。"""
    failures: list[str] = []
    router = repo.text(ROUTER)
    explorer = repo.text(EXPLORER)
    researcher = repo.text(RESEARCHER)
    for label, heading, template, rel in (
        ("story-explorer", r"「查故事资料」交 `story-explorer`", explorer, EXPLORER),
        ("story-researcher", r"「查资料」交 `story-researcher`", researcher, RESEARCHER),
    ):
        block = fenced_block_after(router, heading)
        keys = prompt_keys(block)
        if not keys:
            failures.append(f"{ROUTER}: 找不到派 {label} 的 prompt 模板")
            continue
        protocol = section_body(template, "被调用协议")
        for key in keys:
            if f"`{key}`" not in protocol:
                failures.append(f"{ROUTER}: 派 {label} 的 prompt 字段「{key}」不在 {rel} 的被调用协议里")
    explorer_types = {
        row[0].strip("`") for header, rows in tables(explorer) if header and header[0] == "query_type" for row in rows
    }
    for header, rows in tables(router):
        if len(header) >= 2 and header[1] == "查询类型":
            for row in rows:
                # 单元格第一个反引号值是查询类型，括号里的是参数取值。
                for query_type in re.findall(r"^`([a-z_]+)`", row[1]):
                    if query_type not in explorer_types:
                        failures.append(f"{ROUTER}: 查询类型 {query_type} 不在 {EXPLORER} 的 query_type 表里")
    # 审稿给短篇填「无追踪」，检查员要认得这个写法，否则会把缺追踪判成证据不足。
    if "「无追踪」" in repo.text(REVIEW_PROMPTS) and "「无追踪」" not in repo.text(CHECKER):
        failures.append(f"{CHECKER}: 审稿给短篇写「无追踪」，检查员模板没有对应的短篇分支")
    return failures


# ---------- 导入长篇 → 长篇写作 ----------

LONG_OUTLINE_VIEW = "skills/story-long-write/scripts/outline_view.py"
LONG_WRITER_PROMPT = "skills/story-long-write/scripts/build_writer_prompt.py"
OUTLINE_CONTRACT_COPIES = (
    "skills/story-long-write/scripts/check-outline-contract.js",
    "skills/story-import/scripts/check-outline-contract.js",
)


def check_import_long(repo: Repo) -> list[str]:
    """导入卷纲模板原样落盘，写作端取段器要能严格通过并按单元取到卡。"""
    failures: list[str] = []
    doc = repo.text(IMPORT_LONG)
    marker = "#### 目标格式模板（大纲/卷纲_第X卷.md）"
    if marker not in doc:
        return [f"{IMPORT_LONG}: 没找到卷纲目标格式模板，确认写法后更新本测试"]
    after = doc.split(marker, 1)[1]
    if "```markdown\n" not in after:
        return [f"{IMPORT_LONG}: 卷纲模板不在 markdown 代码块里，确认写法后更新本测试"]
    template = after.split("```markdown\n", 1)[1].split("\n```\n", 1)[0]
    # 写正文组装脚本从单元卡读这两个字段，缺了就只能全量召回。
    for field in re.findall(r'extract_field\(unit_block or "", "([^"]+)"\)', repo.text(LONG_WRITER_PROMPT)):
        if "／" not in field and f"- {field}：" not in template:
            failures.append(f"{IMPORT_LONG}: 卷纲单元卡缺写正文要读的「{field}」")
    with tempfile.TemporaryDirectory(prefix="import-volume-") as tmp:
        volume = Path(tmp) / "卷纲_第1卷.md"
        volume.write_text(template + "\n", encoding="utf-8")
        run = lambda *args: subprocess.run(
            [sys.executable, str(ROOT / LONG_OUTLINE_VIEW), *args, str(volume)],
            capture_output=True, encoding="utf-8")
        check = run("--check", "--strict")
        if check.returncode != 0:
            failures.append(f"{IMPORT_LONG}: 导入卷纲模板过不了写作端 outline_view --check --strict："
                            f"{(check.stdout + check.stderr).strip()[-200:]}")
        unit = run("--unit", "L1-01")
        if unit.returncode != 0 or "单元情绪引擎" not in unit.stdout:
            failures.append(f"{IMPORT_LONG}: 写作端按单元取不到导入卷纲的单元卡 L1-01")
    node = shutil.which("node")
    if node is None:
        print("跳过细纲检查回报出处的核对：没有 node")
        return failures
    with tempfile.TemporaryDirectory(prefix="outline-refs-") as tmp:
        stub = Path(tmp) / "细纲_第001章.md"
        stub.write_text("### 第 1 章：空\n", encoding="utf-8")
        for rel in OUTLINE_CONTRACT_COPIES:
            run = subprocess.run([node, str(ROOT / rel), "--json", str(stub)], capture_output=True, encoding="utf-8")
            try:
                refs = {ref for item in json.loads(run.stdout)["repair_scope"] for ref in item["references"]}
            except (ValueError, KeyError):
                failures.append(f"{rel}: 输出读不出来：{run.stderr.strip()[:200]}")
                continue
            skill = Path(rel).parent.parent
            if not refs:
                failures.append(f"{rel}: 回报里没有可读的模板出处")
            for ref in sorted(refs):
                if not (ROOT / skill / ref).is_file():
                    failures.append(f"{rel}: 回报让读 {ref}，{skill.as_posix()} 里没有这个文件")
    return failures


# ---------- 写作端目标平台 → 审稿平台表；审稿 → consistency-checker ----------

REVIEW_SKILL = "skills/story-review/SKILL.md"
LONG_SETUP = "skills/story-long-write/references/workflow-setup.md"
IMPORT_SKILL = "skills/story-import/SKILL.md"


def review_platform_rows(repo: Repo) -> list[tuple[str, set[str], str]]:
    """审稿端「篇幅 | 目标平台 | 叠加的平台表」映射表：[(篇幅, 平台取值, 平台表单元格)]。"""
    for header, rows in tables(repo.text(REVIEW_SKILL)):
        if header[:2] == ["篇幅", "目标平台"]:
            parsed = []
            for row in rows:
                if len(row) < 3:
                    continue
                values = {re.sub(r"[（(].*?[）)]", "", v).strip() for v in split_terms(row[1], "、")}
                parsed.append((row[0], values, row[2]))
            return parsed
    return []


def check_review_platforms(repo: Repo) -> list[str]:
    """写作端、导入端能写进「目标平台」的每个取值，审稿端都要按篇幅映射到一张平台表或明确不叠加。"""
    failures: list[str] = []
    rows = review_platform_rows(repo)
    if not rows:
        return [f"{REVIEW_SKILL}: 找不到「篇幅 | 目标平台 | 叠加的平台表」映射表"]
    covered: dict[str, set[str]] = {"长篇": set(), "短篇": set()}
    for length, values, target in rows:
        if length not in covered:
            failures.append(f"{REVIEW_SKILL}: 平台映射表的篇幅「{length}」不是长篇/短篇")
            continue
        covered[length] |= values
        for path in re.findall(r"`(story-review/references/rubrics/[^`]+\.md)`", target):
            if not repo.text(f"skills/{path}"):
                failures.append(f"{REVIEW_SKILL}: 平台映射表指向 {path}，文件不存在")

    producers: list[tuple[str, str, list[str]]] = []
    setup = re.search(r"- 目标平台：\{([^}；]+)", repo.text(LONG_SETUP))
    if setup:
        producers.append((LONG_SETUP, "长篇", split_terms(setup.group(1), "/")))
    else:
        failures.append(f"{LONG_SETUP}: 没找到题材定位模板的「目标平台」取值，确认写法后更新本测试")
    design = re.search(r"- 目标平台：\{([^}]+)\}", repo.text(SHORT_DESIGN))
    if design:
        producers.append((SHORT_DESIGN, "短篇", split_terms(design.group(1), "/")))
    else:
        failures.append(f"{SHORT_DESIGN}: 没找到设定模板的「目标平台」取值，确认写法后更新本测试")
    imported = re.search(r"目标平台（长篇：([^；]+)；短篇：([^）]+)）", repo.text(IMPORT_SKILL))
    if imported:
        producers.append((IMPORT_SKILL, "长篇", split_terms(imported.group(1), "/")))
        producers.append((IMPORT_SKILL, "短篇", split_terms(imported.group(2), "/")))
    else:
        failures.append(f"{IMPORT_SKILL}: 没找到 Phase 1 的目标平台选项，确认写法后更新本测试")

    for where, length, values in producers:
        for value in values:
            if value not in covered[length]:
                failures.append(f"{where}: {length}目标平台可写「{value}」，{REVIEW_SKILL} 的平台映射表没有这一项")
    return failures


def check_review_checker_fields(repo: Repo) -> list[str]:
    """consistency-checker 模板要调用方随 prompt 传的字段，审稿端的 prompt 要逐个给出。"""
    template = repo.text(CHECKER)
    match = re.search(r"用调用方随 prompt 传入的((?:\s*/?\s*`[a-z_]+`)+)", template)
    if not match:
        return [f"{CHECKER}: 没找到「调用方随 prompt 传入的」字段，确认写法后更新本测试"]
    fields = re.findall(r"`([a-z_]+)`", match.group(1))
    prompts = repo.text(REVIEW_PROMPTS)
    start = re.search(r"^\*\*Agent 4: consistency-checker\*\*", prompts, re.M)
    end = re.search(r"^## ", prompts[start.end():], re.M) if start else None
    block = prompts[start.end(): start.end() + end.start()] if start and end else ""
    if not block:
        return [f"{REVIEW_PROMPTS}: 找不到 consistency-checker 的 prompt 代码块"]
    return [
        f"{REVIEW_PROMPTS}: consistency-checker 模板要求 prompt 带「{field}」，审稿端的 prompt 没写"
        for field in fields
        if not re.search(rf"^\s*{field}：", block, re.M)
    ]


# ---------- 去味 → 写手 ----------

DESLOP_DETECTOR = "skills/story-deslop/scripts/check-ai-patterns.js"
DESLOP_EXPRESSION = "skills/story-deslop/references/expression.md"
DESLOP_GATES = "skills/story-deslop/references/deslop-gates.md"
WRITER_TEMPLATE = f"{AGENT_TEMPLATES}/narrative-writer.md"
# 派 narrative-writer 去味的调用方；任务标签必须是写手「被调用协议」认得的那个。
DESLOP_WRITER_CALLERS = (
    "skills/story-deslop/references/agent-calls.md",
    "skills/story-long-write/references/agent-calls.md",
    "skills/story-short-write/references/agent-calls.md",
)


def check_deslop_handoff(repo: Repo) -> list[str]:
    failures: list[str] = []
    detector = repo.text(DESLOP_DETECTOR)
    m = re.search(r"blocking by default[^(]*\(([^)]*)\)", detector)
    blocking = {c.strip() for c in m.group(1).split("/")} if m else set()
    if not blocking:
        failures.append(f"{DESLOP_DETECTOR}：读不出 blocking 类别清单")
    node = shutil.which("node")
    if node is None:
        print("跳过检测类别索引核对：没有 node")
    else:
        listed = subprocess.run([node, str(ROOT / DESLOP_DETECTOR), "--list-review-classes"],
                                capture_output=True, encoding="utf-8")
        try:
            classes = json.loads(listed.stdout)
        except ValueError:
            classes = {}
            failures.append(f"{DESLOP_DETECTOR}：--list-review-classes 输出读不出来")
        expression = repo.text(DESLOP_EXPRESSION)
        index = expression[expression.find("## 脚本提示怎样进入语义判断"):]
        for cls in classes:
            bold = f"**`{cls}`**" in index
            if f"`{cls}`" not in index:
                failures.append(f"{DESLOP_EXPRESSION}：检测类别 {cls} 不在提示索引里")
            elif bold != (cls in blocking):
                failures.append(f"{DESLOP_EXPRESSION}：{cls} 的 blocking 加粗与检测器不一致")
    template = repo.text(WRITER_TEMPLATE)
    protocol = template[template.find("## 被调用协议"):]
    known_labels = set(re.findall(r"prompt 标「([^」]+)」", protocol))
    gate_headings = set(re.findall(r"^## (.+)$", repo.text(DESLOP_GATES), re.M))
    for rel in DESLOP_WRITER_CALLERS:
        text = repo.text(rel).replace("\\n", "\n")
        for label in re.findall(r"任务描述：([^\n`{]*去AI味[^\n`{]*)", text):
            if label.strip() not in known_labels:
                failures.append(f"{rel}：任务标签「{label.strip()}」写手不认得（认得：{sorted(known_labels)}）")
        for cited in re.findall(r"deslop-gates(?:\.md)?「([^」]+)」", text):
            if cited not in gate_headings:
                failures.append(f"{rel}：点名的 deslop-gates.md「{cited}」不存在")
    return failures


CHECKS = (
    check_long_report, check_em_cards, check_rhythm, check_short_analyze, check_short_platforms,
    check_short_scan_handoff, check_long_scan_handoff, check_import_short, check_agent_dispatch,
    check_import_long, check_review_platforms, check_review_checker_fields, check_deslop_handoff,
)


def run_all(repo: Repo) -> list[str]:
    failures: list[str] = []
    for check in CHECKS:
        failures.extend(check(repo))
    return failures


# ---------- 负例：改坏输入后断言必须报错 ----------


def mutated(rel: str, old: str, new: str) -> Repo | None:
    """把 rel 里最后一处 old 换成 new（报告模板在快速预览之后，取最后一处才改到报告）。"""
    text = Repo().text(rel)
    if old not in text:
        return None
    head, _, tail = text.rpartition(old)
    return Repo({rel: head + new + tail})


NEGATIVE_CASES = (
    ("报告删掉「读者在追什么」", AUTHOR_FACING, "## 读者在追什么", "## 读者追读点", "读者在追什么"),
    ("报告「基本信息」不再写题材", AUTHOR_FACING, "题材：{题材}\n", "", "「题材」"),
    ("报告「基本信息」不再写目标平台", AUTHOR_FACING, "目标平台：{原书所在平台，看不出来就留空}\n", "", "「目标平台」"),
    ("快速预览改了「黄金三章评分」标题", AUTHOR_FACING, "## 黄金三章评分\n\n| 维度", "## 开篇评分\n\n| 维度", "黄金三章评分"),
    ("深度拆解模板改了「可借鉴要素」", STAGE1, "**可借鉴要素**", "**可学的**", "可借鉴要素"),
    ("短篇报告改了「人物分析」标题", SHORT_STAGE46, "### A. 人物分析", "### A. 人物", "人物分析"),
    ("短篇 schema 改了 reversal_type", SHORT_CONTRACT, '"reversal_type"', '"reversal_kind"', "reversal_type"),
    ("短篇 schema 改了 genre_detected", SHORT_CONTRACT, '"genre_detected"', '"genre"', "genre_detected"),
    ("情节节点模板丢掉位置", SHORT_STAGE23, "位置{第N节，约X字} | ", "", "位置"),
    ("写前召回把「可替换项」写成别名", LONG_RECALL, "可替换项、不可照搬）", "可替换要素、不可照搬）", "可替换要素"),
    ("rhythm_reference 点名不存在的列", LONG_RECALL, "扩写方式 →", "扩写技法 →", "扩写技法"),
    ("情绪模块模板丢掉门禁字段", STAGE3, "| 情绪链 | {缺口", "| 情绪曲线 | {缺口", "情绪链"),
    ("写作端校验不再认黑岩", PHASE2_CHECK, "|黑岩|", "|", "黑岩"),
    ("扫榜结论改了「选题匹配」标题", TOPIC_MATCH, "## 选题匹配", "## 选题方向", "选题匹配"),
    ("扫榜结论文件头丢了复扫日期", TOPIC_MATCH, "- 复扫日期：{YYYYMMDD}\n", "", "复扫日期"),
    ("征稿要求只在平台参考里落盘", SHORT_SCAN_SKILL,
     "5. 作者发来征稿要求：原文存进输出目录的 `征稿要求.md`，题材、字数、截止日期当硬条件。\n", "", "征稿要求.md"),
    ("选题匹配目标情绪写成题材名", TOPIC_MATCH, "{意难平 / 反转震撼", "{虐恋 / 反转震撼", "虐恋"),
    ("扫榜情绪表难度和写作端相反", SHORT_SCAN_SKILL, "| 反转震撼 | 悬疑、身份错位、反转 | 高 |",
     "| 反转震撼 | 悬疑、身份错位、反转 | 低 |", "反转震撼"),
    ("选题决策模板丢了题材组合", TOPIC_DECISION, "- 题材组合：", "- 题材：", "题材组合"),
    ("待拆文验证挪出能爆的原因那一行", TOPIC_DECISION,
     "（假设，`待拆文验证`）\n", "\n- 拆文状态：`待拆文验证`\n", "待拆文验证"),
    ("选题决策不再落在扫榜日期目录", TOPIC_DECISION,
     "`扫榜/{YYYYMMDD}/`", "`选题/{YYYYMMDD}/`", "扫榜/*/选题决策.md"),
    ("导入短篇设定还用旧的核心反转小节", IMPORT_SHORT, "### 核心支点", "### 核心反转", "核心支点"),
    ("导入短篇设定丢了付费点字段", IMPORT_SHORT, "- 付费点：第 {N} 节末\n", "", "付费点"),
    ("导入短篇设定没写反派设计", IMPORT_SHORT, "- 反派设计：不适用（{原因}）\n", "", "villain-contract"),
    ("短篇构思不认导入的续写基线", SHORT_DESIGN, "有「本书续写基线」时只补标", "有续写基线时只补标", "只补缺项"),
    ("短篇写正文不从导入的下一节接着写", SHORT_DRAFT, "正文从第 N+1 节接着写", "正文接着写", "第 N+1 节"),
    ("路由派查资料助手用了模板不认的字段", ROUTER, "查询参数：{", "查询内容：{", "查询内容"),
    ("资料研究助手模板丢了 cdp_port", RESEARCHER, "- `cdp_port`：CDP 端口号（可选，默认 9222）\n", "", "cdp_port"),
    ("检查员模板丢了短篇分支", CHECKER, "或 prompt 写「无追踪」", "", "无追踪"),
    ("导入卷纲单元卡丢了作用域行", IMPORT_LONG, "> 作用域：单元级 L1-01\n", "", "outline_view"),
    ("导入卷纲单元卡丢了单元情绪引擎", IMPORT_LONG, "- 单元情绪引擎：", "- 情绪引擎：", "单元情绪引擎"),
    ("审稿平台映射漏了晋江", REVIEW_SKILL, "晋江、其他", "其他", "晋江"),
    ("审稿平台映射漏了黑岩", REVIEW_SKILL, "七猫、黑岩、红果", "七猫、红果", "黑岩"),
    ("审稿端不给 consistency-checker 传修订号", REVIEW_PROMPTS, "  state_revision：", "  修订号：", "state_revision"),
    ("去味索引漏了一类 blocking", DESLOP_EXPRESSION, "**`em-dash`**", "**`em_dash`**", "em-dash"),
    ("短篇派写手用了写手不认的去味标签", "skills/story-short-write/references/agent-calls.md",
     "任务描述：审查+去AI味", "任务描述：去AI味+格式检查", "写手不认得"),
    ("调用方点名的 deslop-gates 小节改了名", DESLOP_GATES,
     "## 按检测类别或问题限定范围", "## 定点 Gate 映射", "按检测类别或问题限定范围"),
)


def run_negative_cases() -> list[str]:
    failures: list[str] = []
    for label, rel, old, new, expect in NEGATIVE_CASES:
        repo = mutated(rel, old, new)
        if repo is None:
            failures.append(f"负例「{label}」：{rel} 里找不到要改的原文「{old}」，更新负例")
            continue
        if not any(expect in f for f in run_all(repo)):
            failures.append(f"负例「{label}」：改坏后没有报出含「{expect}」的问题")
    return failures


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failures = run_all(Repo())
    failures += run_negative_cases()
    if failures:
        print("交接契约检查失败：")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("交接契约检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
