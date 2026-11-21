#!/usr/bin/env python3
"""build_writer_prompt.py — 确定性组装 narrative-writer 的 spawn prompt 骨架。

用法:
    python build_writer_prompt.py --project <书目录> --chapter N [--out [<文件>]]
`--out` 不带路径时留档到 `<书目录>/.story/work/第NNN章/writer_prompt.md`。
stdout 分两区：`===` 分隔线以上为 prompt 正文，以下为核对报告（不进 prompt）。
Exit: 0 = 骨架已输出；2 = 必在输入缺失或无效。
"""

import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from outline_view import CHAPTER_UNIT_FIELDS, UNIT_FIELD_NAMES as UNIT_CARD_FIELDS, chapter_unit_in_volume, is_unit_card, parse as parse_volume
from wordcount_core import WordcountError, resolve_book_dir

OUTLINE_MUST = {
    "目标情绪": ("目标情绪", "这一章要让读者感到什么"),
    "主角目标/关键选择": ("主角目标/关键选择", "主角目标／关键选择", "主角这一章想要什么，做了什么选择"),
}
PLACEHOLDER_RE = re.compile(r"^[{｛].*[}｝]$|^\[?待补充\]?$|^(?:无|待定|todo|TODO|…+|\.{3,})$")
UNIT_FIELD_NAMES = CHAPTER_UNIT_FIELDS + ("单元ID／位置", "所属剧情段", "单元ID")
ENGINE_FIELD_NAMES = UNIT_CARD_FIELDS["单元情绪引擎"]
TEMPO_FIELD_NAMES = UNIT_CARD_FIELDS["单元节拍/章功能分配"] + ("单元节拍",)
TAIL_CHARS = 400
STATE_SECTIONS = ("当前位置", "长期约束", "核心角色状态", "活跃伏笔", "近三章速记", "下一章承诺", "连贯性风险")
SLOT_MARK = "［主会话填］"
AUTHOR_DECIDED_CHARS = 600
WORK_ROOT = (".story", "work")
MEMORY_KINDS = ("prose_style", "story_design")
IMPORTANCE_RANK = {"low": 1, "medium": 2, "high": 3}
MISSED_SHOWN = 8
LONG_WRITE_WORKFLOWS = {"长篇", "长篇写作", "写长篇", "长篇连载", "长篇网文", "长篇正文", "story-long-write"}
WORKSPACE_MARKERS = (".active-book", "长篇", "短篇", "拆文库")
GENRE_CARD_DIR = Path(__file__).resolve().parent.parent / "references" / "genre-prose-cards"
FALLBACK_CARD = GENRE_CARD_DIR / "流派兜底.md"


def chapter_work_dir(project: Path, chapter: int) -> Path:
    width = max(3, len(str(chapter)))
    return project.joinpath(*WORK_ROOT, f"第{chapter:0{width}d}章")


def read_text(path: Path):
    try:
        return io.open(path, encoding="utf-8").read().lstrip("\ufeff")
    except (OSError, UnicodeError):
        return None


def substantive(text):
    if not text:
        return False
    body = re.sub(r"^#{1,6}[^\n]*", "", text, flags=re.M)
    body = re.sub(r"待补充|待办|待定|暂无|TODO|TBD", "", body, flags=re.I)
    return bool(re.sub(r"[\s_#*\[\]【】{}。，；:：-]", "", body))


def has_custom_style(text):
    return substantive(re.sub(r"<!--[\s\S]*?-->", "", text or ""))


def find_chapter_file(directory: Path, chapter: int, prefix: str):
    if not directory.is_dir():
        return None
    pattern = re.compile(rf"^{prefix}第0*{chapter}章.*\.md$")
    return next((e for e in sorted(directory.iterdir())
                 if e.is_file() and pattern.match(e.name) and "_原稿_" not in e.name), None)


def extract_field(outline_text: str, field: str):
    lines = outline_text.splitlines()
    pattern = re.compile(rf"^([ \t]*)[-*+]\s+\*{{0,2}}{re.escape(field)}\*{{0,2}}[ \t]*[：:][ \t]*(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        values = [match.group(2)]
        for following in lines[index + 1:]:
            bullet = re.match(r"^([ \t]*)[-*+]\s", following)
            if re.match(r"^#{1,6}\s", following) or (bullet and len(bullet.group(1)) <= len(match.group(1))):
                break
            values.append(following)
        return "\n".join(values).strip()
    return None


def extract_any(text: str, names):
    for name in names:
        value = extract_field(text, name)
        if value is not None:
            return value
    return None


def outline_gaps(outline_text: str):
    missing = []
    for name, labels in OUTLINE_MUST.items():
        cleaned = re.sub(r"\s+", " ", (extract_any(outline_text, labels) or "").replace("**", "")).strip()
        if not cleaned or PLACEHOLDER_RE.match(cleaned):
            missing.append(name)
    return missing


def unit_id_from(field: str):
    match = re.search(r"[A-Za-z]+\d+(?:-\d+)+", field) or re.match(r"([A-Za-z0-9\-]+)", field)
    return match.group(0) if match else None


def own_names(project: Path):
    names = {project.name}
    text = read_text(project / "设定" / "题材定位.md") or ""
    match = re.search(r"^[ \t]*[-*+]?[ \t]*\**书名\**[ \t]*[：:][ \t]*(.+)$", text, re.M)
    if match and "{" not in match.group(1):
        names.add(re.sub(r"[（(][^）)]*[）)]", "", match.group(1)).strip().strip("《》"))
    return {name for name in names if name}


def benchmark_registry(project: Path):
    text = re.sub(r"<!--[\s\S]*?-->", "", read_text(project / "设定" / "题材定位.md") or "")
    values = [v.strip() for label in ("主对标书", "对标")
              for v in re.findall(rf"^[ \t>]*(?:[-*+][ \t]*)?\**{label}\**[ \t]*[：:][ \t]*(.*)$", text, re.M)]
    values = [v for v in values if v and not v.startswith(("{", "｛"))]
    if any(re.match(r"^(无|不对标|都不用|没有)", v) for v in values):
        return "none"
    section = re.search(r"^##[ \t]*对标登记[^\n]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
    rows = []
    if section:
        for line in section.group(1).splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if cells and cells[0] and cells[0] != "书名" and not set(cells[0]) <= set("-: ") and not cells[0].startswith("{"):
                rows.append(cells[0])
    return "registered" if values or rows else "missing"


def extract_title(outline_text: str, chapter: int):
    match = re.search(rf"^#{{1,4}}\s*第\s*0*{chapter}\s*章\s*[：:]\s*(.+?)\s*$", outline_text, re.M)
    return match.group(1).strip() if match else None


def extract_unit_block(volume_text: str, unit_id: str):
    lines, sections = parse_volume(volume_text)
    for sec in sections:
        if sec.unit != unit_id or not is_unit_card(sec) or sec.status == "已退役":
            continue
        end = next((o.start for o in sections if o.start > sec.start and o.level <= sec.level), len(lines))
        return "\n".join(lines[sec.start:end]).strip()
    return None


def extract_state_sections(state_text: str):
    found = {}
    for sec in STATE_SECTIONS:
        match = re.search(rf"^##\s*{sec}\s*$(.*?)(?=^##\s|\Z)", state_text, re.M | re.S)
        if match and match.group(1).strip():
            found[sec] = match.group(1).strip()
    return found


def previous_chapter_tail(project: Path, chapter: int):
    prev = find_chapter_file(project / "正文", chapter - 1, "")
    text = read_text(prev) if prev else None
    if not text:
        return prev, None
    picked, total = [], 0
    for line in reversed([ln for ln in text.rstrip().splitlines() if ln.strip()]):
        picked.append(line)
        total += len(line)
        if total >= TAIL_CHARS:
            break
    return prev, "\n".join(reversed(picked))


def scoped_memory_values(workspace: Path):
    values = {"genre": set(), "workflow": set()}
    state = read_text(workspace / ".story" / "作者记忆" / "_author-memory-state.json")
    try:
        items = list(((json.loads(state) if state else {}).get("items") or {}).values())
    except (ValueError, AttributeError, TypeError):
        return values
    for item in items:
        if not isinstance(item, dict):
            continue
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        if item.get("status") == "active" and item.get("kind") in MEMORY_KINDS and scope.get("level") in values and scope.get("value"):
            values[scope["level"]].add(scope["value"])
    return values


def memory_state_kind(directory: Path):
    text = read_text(directory / ".story" / "作者记忆" / "_author-memory-state.json")
    try:
        document = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    book = document.get("book")
    return "book" if isinstance(book, str) and book.strip() else "project"


def find_workspace(project: Path):
    project = project.resolve()
    deployed = next((d for d in (project, *project.parents) if (d / ".story-deployed").is_file()), None)
    if deployed is not None:
        return deployed, True
    if project.parent.name in {"长篇", "短篇"}:
        return project.parent.parent, True
    if memory_state_kind(project) == "project" or (project / ".story" / "作者记忆" / "书级").is_dir():
        return project, True
    try:
        home = Path.home().resolve()
    except (RuntimeError, KeyError):
        home = None
    for ancestor in project.parents:
        if ancestor == home:
            break
        if any((ancestor / marker).exists() for marker in WORKSPACE_MARKERS) or memory_state_kind(ancestor) == "project":
            return ancestor, True
    return project, False


def genre_line(project: Path):
    text = read_text(project / "设定" / "题材定位.md") or ""
    match = re.search(r"^[ \t]*[-*+]?[ \t]*\**题材(?:类型)?\**[ \t]*[：:](.*)$", text, re.M)
    return "" if (not match or "{" in match.group(1)) else match.group(1).strip()


def book_genres(project: Path):
    return {word.casefold() for word in re.split(r"[\W_丨×]+", genre_line(project)) if word}


def match_genre_cards(project: Path):
    raw = genre_line(project).casefold()
    fallback = [(FALLBACK_CARD, "low")] if FALLBACK_CARD.is_file() else []
    if not raw or not GENRE_CARD_DIR.is_dir():
        return fallback
    rank, spans = {"high": 0, "medium": 1, "low": 2}, []
    for card in sorted(GENRE_CARD_DIR.glob("*.md")):
        head = (read_text(card) or "").split("---")
        meta = head[1] if len(head) > 2 else ""
        if re.search(r"^fallback:\s*true\s*$", meta, re.M):
            continue
        genre = re.search(r"^genre:\s*(.+)$", meta, re.M)
        aliases = re.search(r"^aliases:\s*\[(.*)\]", meta, re.M)
        confidence = re.search(r"^confidence:\s*(\w+)", meta, re.M)
        level = confidence.group(1) if confidence else "low"
        names = ([genre.group(1).strip()] if genre else [card.stem]) + ([a.strip() for a in aliases.group(1).split(",")] if aliases else [])
        for name in {n.casefold() for n in names if n}:
            spans += [(m.start(), m.end(), card, level) for m in re.finditer(re.escape(name), raw)]
    best = {}
    for start, end, card, level in spans:
        if any(c != card and s <= start and end <= e and e - s > end - start for s, e, c, _ in spans):
            continue
        key = (start, -(end - start), rank.get(level, 2), card.name)
        if card not in best or key < best[card][0]:
            best[card] = (key, level)
    hits = sorted((key, card, level) for card, (key, level) in best.items())
    return [(card, level) for _, card, level in hits[:2]] or fallback


def author_decided(project: Path):
    text = read_text(project / "设定" / "题材定位.md") or ""
    match = re.search(r"^##[ \t]*作者已定[^\n]*\n(.*?)(?=^#{1,2}[ \t]|\Z)", text, re.M | re.S)
    if not match:
        return None, False
    lines = [line.rstrip() for line in match.group(1).splitlines()
             if line.strip() and not re.fullmatch(r"\s*[-*+]?\s*\{.*\}\s*", line)]
    kept, used, cut = [], 0, False
    for line in lines:
        size = len(re.sub(r"\s", "", line))
        if used + size > AUTHOR_DECIDED_CHARS:
            cut = True
            break
        kept.append(line)
        used += size
    return "\n".join(kept), cut


def query_author_memory(project: Path):
    workspace, recognised = find_workspace(project)
    script = Path(__file__).with_name("author_memory_commit.py")
    if not script.is_file():
        return None, [], {}, "author_memory_commit.py 缺失"
    if not recognised and memory_state_kind(project) == "book":
        return None, [], {}, ("认不出创作工作区（书目录及祖先都没有 .active-book、长篇/、短篇/、拆文库/ 或项目级作者记忆），"
                              "书目录里却是本书的记忆；先按 author-memory.md「存放与路由」定好 --workspace")
    scoped, book = scoped_memory_values(workspace), book_genres(project)
    genres = sorted(v for v in scoped["genre"] if v.casefold() in book) or [None]
    workflows = sorted(v for v in scoped["workflow"] if v.casefold() in {w.casefold() for w in LONG_WRITE_WORKFLOWS})
    skipped = {"genre": sorted(v for v in scoped["genre"] if v not in genres),
               "workflow": sorted(v for v in scoped["workflow"] if v not in workflows)}
    lines, omitted, summaries, importance, seen = [], [], {}, {}, set()
    for genre in genres:
        for workflow in workflows or [None]:
            cmd = [sys.executable, str(script), "query", "--workspace", str(workspace), "--book-root", str(project)]
            for kind in MEMORY_KINDS:
                cmd += ["--kind", kind]
            if genre:
                cmd += ["--genre", genre]
            if workflow:
                cmd += ["--workflow", workflow]
            completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
            try:
                result = json.loads(completed.stdout or "{}")
            except ValueError:
                result = {}
            if not result.get("ok"):
                return None, [], {}, result.get("error") or completed.stderr.strip() or "query 失败"
            items, rendered = result.get("items") or [], result.get("lines") or []
            if len(items) != len(rendered):
                return None, [], {}, "query 输出缺 lines（作者记忆脚本与组装脚本版本不一致）"
            for item, line in zip(items, rendered):
                if item.get("id") not in seen:
                    seen.add(item.get("id"))
                    lines.append(line)
            omitted += [i for i in result.get("omitted_ids") or [] if i not in omitted]
            summaries.update(result.get("omitted_summaries") or {})
            importance.update(result.get("omitted_importance") or {})
    ranked = sorted((i for i in omitted if i not in seen),
                    key=lambda i: (-IMPORTANCE_RANK.get(importance.get(i), 0), omitted.index(i)))
    return lines, [(i, summaries.get(i, "")) for i in ranked], {k: v for k, v in skipped.items() if v}, None


def learn_heading_form(project: Path, chapter: int, title: str):
    body = project / "正文"
    if not body.is_dir():
        return None, "正文/ 目录不存在"
    pattern = re.compile(r"^(#+)([ \t　]*)第(0*\d+)章([ \t　]*)(.*)$")
    best = None
    for entry in sorted(body.glob("*.md")):
        num = re.match(r"^第(\d+)章", entry.name)
        if not num or int(num.group(1)) == chapter:
            continue
        head = (read_text(entry) or "").lstrip().splitlines()
        hit = pattern.match(head[0].strip()) if head else None
        if hit and int(num.group(1)) < chapter and (best is None or int(num.group(1)) > best[0]):
            best = (int(num.group(1)), hit)
    if best is None:
        return None, "正文/ 下没有可解析标题行的既有章，写手按自身规则处理"
    _, hit = best
    level, gap1, digits, gap2 = hit.group(1), hit.group(2), hit.group(3), hit.group(4)
    number, how = (f"{chapter:0{len(digits)}d}", f"{len(digits)} 位补零") if digits.startswith("0") else (str(chapter), "不补零")
    return f"{level}{gap1}第{number}章{gap2 or ' '}{title}", f"照既有章形态（{level} ＋ 章号{how}）"


def build(project: Path, chapter: int, report: list):
    errors = []
    outline_file = find_chapter_file(project / "大纲", chapter, "细纲_")
    if outline_file is None:
        return None, [f"必在块缺失：{project / '大纲'} 下没有第 {chapter} 章细纲"]
    outline_text = read_text(outline_file)
    if not outline_text or not outline_text.strip():
        return None, [f"必在块缺失：{outline_file} 为空"]

    title = extract_title(outline_text, chapter)
    if not title:
        return None, [f"细纲缺章名：{outline_file}，需要 ### 第 N 章：章名"]
    if any(ch in title for ch in "/\\"):
        return None, ["章名不能包含路径分隔符"]

    parts = [
        f"本次任务：写第 {chapter} 章，全章一次写完。开始前先按「参考文件体系」逐行独立判定命中并读取，命中即必读，未命中不预加载；交付摘要里报出读了哪几个。",
        f"项目目录：{project}",
        f"章节：第 {chapter} 章",
        f"最终输出路径：{project / '正文' / f'第{chapter:03d}章_{title}.md'}",
    ]
    heading_line, how = learn_heading_form(project, chapter, title)
    if heading_line:
        parts.append(f"标题行（逐字照抄，勿按通用规则推导）：{heading_line}")
        report.append(f"标题行：{heading_line}　{how}")
    else:
        report.append(f"标题行：未注入——{how}")
    parts.append(f"细纲文件（动笔前完整读到 EOF）：{outline_file}")

    state_file = project / "追踪" / "上下文.md"
    state_text = read_text(state_file)
    if not state_text:
        errors.append(f"必在块缺失：读不到 {state_file}")
    else:
        missing = [s for s in STATE_SECTIONS if s not in extract_state_sections(state_text)]
        if missing:
            errors.append(f"必在块缺失：{state_file} 缺栏目 {'、'.join(missing)}（先用 tracking_commit.py 修派生视图）")
        else:
            report.append("续写状态：七栏已校验，主会话按本章需要筛选到「本节速记」")

    style_file = project / "设定" / "文风.md"
    custom_style = has_custom_style(read_text(style_file))
    registry = benchmark_registry(project)
    mine = own_names(project)
    has_books = any(d.is_dir() and d.name not in mine
                    for base in (project / "对标", project / "拆文库", project.parent / "拆文库")
                    if base.is_dir() for d in base.iterdir())
    no_benchmark = registry == "none" or (registry == "missing" and not has_books)
    if custom_style:
        parts.append(f"文风：读 {style_file} 全文（本书文风；表达与通用写法冲突时按它写，不覆盖细纲事实与信息边界）")
        report.append("文风：本书有 设定/文风.md，已给路径")
    elif no_benchmark:
        parts.append("文风：本书没有 设定/文风.md，也不对标——按作者这次的要求和通用写法写")
        report.append("文风：无文风文件、无对标" + ("（作者登记了不对标）" if registry == "none" else ""))
    else:
        parts.append(f"——— 文风 ———\n{SLOT_MARK} 本书没有 设定/文风.md：按 benchmark-recall.md 取主对标文风，填路径与要点")
        report.append("文风：无文风文件、有对标——主对标文风归主会话填")

    if chapter > 1:
        prev_file, tail = previous_chapter_tail(project, chapter)
        if prev_file is None or not tail:
            errors.append(f"必在块缺失：找不到或读不到第 {chapter - 1} 章正文")
        else:
            parts.append("——— 上一章结尾（承接用，不重写；不给全章路径）———\n" + tail)
            report.append(f"上一章结尾：{prev_file.name} 末 {len(tail)} 字（按整行回退）")

    unit_field = extract_any(outline_text, UNIT_FIELD_NAMES)
    volumes = [read_text(v) or "" for v in sorted((project / "大纲").glob("卷纲_*.md"))]
    candidates = [unit_id_from(unit_field) if unit_field else None] + [chapter_unit_in_volume(t, chapter) for t in volumes]
    unit_id, unit_block = None, None
    for candidate in filter(None, candidates):
        block = next(filter(None, (extract_unit_block(t, candidate) for t in volumes)), None)
        if block:
            unit_id, unit_block = candidate, block
            break

    gaps = outline_gaps(outline_text)
    if gaps:
        report.append("细纲两行：缺 " + "、".join(gaps) + "——不拒写：按卷纲本段剧情补出这两行写回细纲、汇报里说「补了这两行」，再重跑本脚本；卷纲里也没有本章内容就停下问作者")
    else:
        report.append("细纲两行：目标情绪、主角目标/关键选择都有")

    target_emotion = extract_any(outline_text, OUTLINE_MUST["目标情绪"])
    card_text = read_text(project / "设定" / "题材正文提示卡.md")
    engine = extract_any(unit_block or "", ENGINE_FIELD_NAMES)
    tempo = extract_any(unit_block or "", TEMPO_FIELD_NAMES)
    needs = {"题材正文提示卡": card_text, "目标情绪": target_emotion, "单元情绪引擎": engine, "单元节拍/章功能分配": tempo}
    why = [name + "缺有效内容" for name, value in needs.items() if not substantive(value)]
    if not custom_style and not no_benchmark:
        why.append("custom_style=false")

    if not why:
        lines = [
            "selected_emotion_module：降档（来源：细纲「目标情绪」＋单元卡「单元情绪引擎」）",
            f"  细纲目标情绪：{target_emotion}",
            *([f"  单元情绪引擎：{engine}"] if engine else []),
            "rhythm_reference：降档（来源：单元卡「单元节拍/章功能分配」）",
            *([f"  {tempo}"] if tempo else []),
        ]
        slot_recall = "——— 情绪与节奏召回 ———\n" + "\n".join(lines)
        report.append(f"召回降档：成立，{'无对标，' if no_benchmark and not custom_style else '文风、'}题材卡、目标情绪和单元 {unit_id} 情绪/节拍均可用")
    else:
        slot_recall = f"——— 情绪与节奏召回 ———\n{SLOT_MARK} 降档不成立（{'、'.join(why)}），按 benchmark-recall.md 走全量召回后填此槽"
        report.append(f"召回降档：不成立（{'、'.join(why)}）—— 全量召回归主会话")

    parts += [
        f"——— 本章意图（一句话）———\n{SLOT_MARK}",
        f"——— 作者本轮要求 ———\n{SLOT_MARK} 本轮字数范围、必发生、禁发生、停笔点与章尾要求；无写「无」。",
        slot_recall,
        f"——— 本章技法 ———\n{SLOT_MARK} 填 SKILL.md「本章技法」类别之一（无写「无」）及用在何处；不摘技法。",
        f"——— 本节速记 ———\n{SLOT_MARK} 筛自 `追踪/上下文.md`：在场角色状态、下章承诺、连贯性风险、活跃伏笔（只给禁令，不下放作者侧真相）、本章相关卷级禁忌、久别角色是否补读快照。",
        f"——— 涉及角色 ———\n{SLOT_MARK} 列出本章要读的角色卡（本节速记已给全状态者不列）。",
    ]
    if not substantive(card_text):
        cards = match_genre_cards(project)
        if cards:
            named = "；".join(f"{'主' if i == 0 else '辅'}题材 {card}（置信度 {level}）" for i, (card, level) in enumerate(cards))
            how = "（题材卡无匹配，用流派兜底卡：只抽最接近的流派一节）" if cards[0][0] == FALLBACK_CARD else ""
            report.append(f"题材卡：本书还没有题材正文提示卡，按「题材类型」匹配到 {named}{how}；按 genre-prose-cards.md「全书题材正文提示卡」一节生成后落盘，后续章直接读")
        else:
            report.append("题材卡：本书还没有题材正文提示卡，题材卡目录缺失——重跑 /story-setup 或重装本 skill")
    parts += [
        f"——— 题材正文提示卡（genre_prose_card，只含本章相关条目）———\n{SLOT_MARK} 主题材 3-5 条、辅题材 1-2 条；只作内部校准，不进正文。",
        f"——— 必读设定 ———\n{SLOT_MARK} 直接写出本章用到的设定原句（细纲显式引用 + 隐含术语/程序/数字锚）；无写「无」。",
    ]

    decided, cut = author_decided(project)
    if decided:
        note = f"\n（超过 {AUTHOR_DECIDED_CHARS} 字已截断，其余见 {project / '设定' / '题材定位.md'}「作者已定」，动笔前读完）" if cut else ""
        parts.append("——— 作者已定（本书的决定，高于作者记忆，与细纲冲突以细纲为准并在交付摘要里说明）———\n" + decided + note)
        report.append("作者已定：已注入" + ("（超长截断，写手需回原文读完）" if cut else ""))
    else:
        report.append("作者已定：题材定位里没有或为空，未注入")

    lines, missed, skipped, memory_error = query_author_memory(project)
    if memory_error:
        memory_block = f"{SLOT_MARK} 组装脚本查询作者记忆失败（{memory_error}），按 author-memory.md 手动 query prose_style + story_design 后填入；无写「无」"
        report.append(f"作者记忆：脚本查询失败——{memory_error}，归主会话手动查询；手查有没带上的，章末照模板用原话说")
    else:
        memory_block = "\n".join(lines) if lines else "无"
        report.append(f"作者记忆：已注入 {len(lines)} 条" if lines or missed else "作者记忆：无相关 active 条目")
    if missed:
        shown = "".join(f"「{summary or item_id}」" for item_id, summary in missed[:MISSED_SHOWN])
        more = "等" if len(missed) > MISSED_SHOWN else ""
        report.append(
            f"作者记忆：装不下、这章没带上 {len(missed)} 条（{'、'.join(i for i, _ in missed)}），章末汇报原样说这句——"
            f"你记下的写作习惯这章有 {len(missed)} 条没带上：{shown}{more}；说「整理作者记忆」可以合并相近的、调低不常用的。")
    if skipped and not memory_error:
        named = "；".join(f"{'题材' if k == 'genre' else '流程'}：{'、'.join(v)}" for k, v in skipped.items())
        memory_block += f"\n{SLOT_MARK} 另有限定范围的作者记忆未代查（{named}）：适用则带 --genre／--workflow 补查后填入"
        report.append(f"作者记忆：限定范围未代查（{named}），归主会话判断是否适用")
    parts += [
        "——— 作者偏好（作者记下的写作习惯，低优先级倾向，不逐条追求命中）———\n" + memory_block,
        "检查分工：写手负责编排、内容覆盖和格式自检；主会话质量阶段负责语义去味及最终文件扫描，写手不重复整轮去味。",
        "本次照你的铁律 1-8 与被调用协议执行（细纲边界、正文形状、新增物三级、交付三附件均以你的定义为准）。",
        f"字数目标按细纲执行；整章一次写完，直接写到最终输出路径（临时文件只放 {chapter_work_dir(project, chapter)}，不写 /tmp）；不拆逐点配额、不自测字数。",
    ]

    if errors:
        return None, errors
    return "\n\n".join(parts) + "\n", []


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--chapter", required=True, type=int)
    parser.add_argument("--out", nargs="?", const="", default=None,
                        help="prompt 留档路径；不带值时留档到本章工作目录 writer_prompt.md")
    args = parser.parse_args(argv)

    project = Path(args.project).resolve()
    if args.chapter < 1:
        parser.error("--chapter 必须大于 0")
    if not project.is_dir():
        sys.stderr.write(f"项目目录不存在：{project}\n")
        return 2
    try:
        project = resolve_book_dir(project)
    except WordcountError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    report = []
    prompt, errors = build(project, args.chapter, report)
    if prompt is None:
        sys.stderr.write("组装中止，先修数据再重跑（这不是回落手拼的理由）：\n")
        for item in errors:
            sys.stderr.write(f"  - {item}\n")
        return 2

    outline_file = find_chapter_file(project / "大纲", args.chapter, "细纲_")
    title = extract_title(read_text(outline_file) or "", args.chapter) if outline_file else None
    if title:
        clashes = [p.name for p in sorted((project / "正文").glob("*.md"))
                   if p.name.endswith(f"_{title}.md") and not p.name.startswith(f"第{args.chapter:03d}章")]
        report.append(f"标题预检：《{title}》" + ("与既有章重名 → " + "、".join(clashes) if clashes else "无重名"))

    if args.out is not None:
        out = Path(args.out) if args.out else chapter_work_dir(project, args.chapter) / "writer_prompt.md"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with io.open(out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(prompt)
        except OSError as exc:
            sys.stderr.write(f"留档写入失败：{out}（{exc}）\n")
            return 2
        report.append(f"留档：{out}")

    sys.stdout.write(prompt)
    sys.stdout.write("\n" + "=" * 60 + "\n")
    sys.stdout.write("以上是 prompt 正文（空槽以外一字不改，照抄）。以下不进 prompt：\n\n")
    for item in report:
        sys.stdout.write(f"- {item}\n")
    sys.stdout.write(f"- 待填槽位：{prompt.count(SLOT_MARK)} 个（搜 {SLOT_MARK}）\n")
    sys.stdout.write(f"- 骨架长度：{len(prompt)} 字符\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
