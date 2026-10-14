#!/usr/bin/env python3
"""build_writer_prompt.py — 确定性组装 narrative-writer 的 spawn prompt 骨架。

用法:
    python build_writer_prompt.py --project <书目录> --chapter N [--out [<文件>]]

`--out` 不带路径时留档到本章工作目录 `<书目录>/.story/work/第NNN章/writer_prompt.md`。
分组 segment、prompt 留档和逐章事务 JSON 都只放这个书内工作目录——不写系统 /tmp
（多本书/多会话同章号会互相覆盖，Windows 也没有 /tmp），也不写进 正文/（会被当成章节）。
`storyctl.py chapter commit` 成功后自动删除该章工作目录。

跑在「写前准备」第一步。stdout 分两区，`===` 分隔线以上是 prompt 正文
（主会话照抄，空槽以外一字不改），以下是核对报告（不进 prompt）。

职责边界:
- 脚本做确定性部分：固定首行、定位、标题行字面量、细纲指针、文风全文路径与裁决、
  上一章结尾、降档判定与情绪/节奏槽、固定块指针。
- 脚本代查作者记忆（prose_style + story_design）并填好 author_preferences；装不下的条目在核对报告里
  点名，并拼好章末对作者说的那句原话。
- 脚本注入 `设定/题材定位.md`「作者已定」（本书的偏好、红线与否掉的方案），超过 AUTHOR_DECIDED_CHARS
  可见字截断并注明去原文看；它是书级设定，优先于作者记忆。
- 主会话填九个固定槽：执行安排 / 本章意图 / 作者本轮要求 / 本章技法 / 本节速记 / 涉及角色 /
  genre_prose_card / 必读设定 / style_resolution。另有两个条件槽，出现时同样标［主会话填］：
  author_preferences 块内的限定范围（--genre／--workflow）作者记忆未代查时，由主会话判断是否适用后补查
  （脚本查询失败时则整块手查）；降档不成立时「情绪与节奏召回」也归主会话。
  核对报告末尾的「待填槽位」给出本次实际个数（9-11）。
  材料槽对应原流程步骤 3「写前准备」的四项输出（本节速记 / 目标情绪 / 涉及角色 /
  本章技法）加上作者本轮要求、题材卡、设定补漏与作者偏好——都是判断，脚本做不了。
- 续写状态卡校验后由主会话筛选，在「本节速记」槽内写入本章需要的状态。
- 可选块缺失留标题并写明原因（「没有」与「漏了」在产物上必须长得不一样）。
  必在块缺失退出码 2 —— 那是数据问题，要修数据后重跑，不是回落手拼的理由。

Exit: 0 = 骨架已输出；2 = 输入缺失或无效。
"""

import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from outline_view import parse as parse_volume

TAIL_CHARS = 400          # 上一章结尾注入的目标字符数（按整行回退，不切半句）
STATE_SECTIONS = ("当前位置", "长期约束", "核心角色状态", "活跃伏笔", "近三章速记", "下一章承诺", "连贯性风险")
SLOT_MARK = "［主会话填］"
AUTHOR_DECIDED_CHARS = 600  # 「作者已定」注入上限（去空白字数）；超了截断，写手按提示回原文看
WORK_ROOT = (".story", "work")


def chapter_work_dir(project: Path, chapter: int) -> Path:
    """本章临时文件的唯一落点；与 storyctl.py 提交后清理的目录同一口径。"""
    width = max(3, len(str(chapter)))
    return project.joinpath(*WORK_ROOT, f"第{chapter:0{width}d}章")


def read_text(path: Path):
    try:
        return io.open(path, encoding="utf-8").read().lstrip("﻿")
    except (OSError, UnicodeError):
        return None


def substantive(text):
    if not text:
        return False
    body = re.sub(r"^#{1,6}[^\n]*", "", text, flags=re.M)
    body = re.sub(r"待补充|待办|待定|暂无|TODO|TBD", "", body, flags=re.I)
    return bool(re.sub(r"[\s_#*\[\]【】{}。，；:：-]", "", body))


def has_custom_style(text):
    # A single substantive sentence can express the author's choice.
    return substantive(re.sub(r"<!--[\s\S]*?-->", "", text or ""))


def find_chapter_file(directory: Path, chapter: int, prefix: str):
    if not directory.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(prefix) if prefix else ''}第0*{chapter}章.*\.md$")
    # 正文按卷归档在子目录（正文/第N卷_卷名/第N章：章题.md），顶层找不到时递归查找
    for entry in sorted(
        (child for child in directory.rglob("*.md") if child.is_file()),
        key=lambda p: str(p),
    ):
        if pattern.match(entry.name) and "_原稿_" not in entry.name:
            return entry
    return None


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


def extract_title(outline_text: str, chapter: int):
    match = re.search(rf"^#{{1,4}}\s*第\s*0*{chapter}\s*章\s*[：:]\s*(.+?)\s*$",
                      outline_text, re.M)
    return match.group(1).strip() if match else None


def extract_unit_block(volume_text: str, unit_id: str):
    lines, sections = parse_volume(volume_text)
    for section in sections:
        if section.unit != unit_id or "剧情单元" not in section.title or section.status == "已退役":
            continue
        end = next((other.start for other in sections
                    if other.start > section.start and other.level <= section.level), len(lines))
        return "\n".join(lines[section.start:end]).strip()
    return None


def extract_state_sections(state_text: str):
    found = {}
    for section in STATE_SECTIONS:
        match = re.search(rf"^##\s*{section}\s*$(.*?)(?=^##\s|\Z)",
                          state_text, re.M | re.S)
        if match and match.group(1).strip():
            found[section] = match.group(1).strip()
    return found


def previous_chapter_tail(project: Path, chapter: int):
    """按整行从尾部回退，凑够 TAIL_CHARS 即停 —— 不切半句。"""
    prev = find_chapter_file(project / "正文", chapter - 1, "")
    if prev is None:
        return None, None
    text = read_text(prev)
    if not text:
        return prev, None
    lines = [line for line in text.rstrip().splitlines() if line.strip()]
    picked, total = [], 0
    for line in reversed(lines):
        picked.append(line)
        total += len(line)
        if total >= TAIL_CHARS:
            break
    return prev, "\n".join(reversed(picked))


MEMORY_KINDS = ("prose_style", "story_design")
IMPORTANCE_RANK = {"low": 1, "medium": 2, "high": 3}
MISSED_SHOWN = 8  # 给作者的那句话最多点名几条，其余用「等」带过；完整清单走「整理作者记忆」
# 限定「流程」的作者记忆里，这些取值指的就是长篇写正文。
LONG_WRITE_WORKFLOWS = {"长篇", "长篇写作", "写长篇", "长篇连载", "长篇网文", "长篇正文", "story-long-write"}


def scoped_memory_values(workspace: Path):
    """项目级 store 里限定题材／流程的 active 条目取值：{"genre": {...}, "workflow": {...}}。"""
    values = {"genre": set(), "workflow": set()}
    state = read_text(workspace / ".story" / "作者记忆" / "_author-memory-state.json")
    try:
        items = (json.loads(state) if state else {}).get("items") or {}
        items = list(items.values())
    except (ValueError, AttributeError, TypeError):
        return values
    for item in items:
        if not isinstance(item, dict):
            continue
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        if (item.get("status") == "active" and item.get("kind") in MEMORY_KINDS
                and scope.get("level") in values and scope.get("value")):
            values[scope["level"]].add(scope["value"])
    return values


WORKSPACE_MARKERS = (".active-book", "长篇", "短篇", "拆文库")


def memory_state_kind(directory: Path):
    """目录下 `.story/作者记忆/` 那份 state 是哪一级：不带 book 字段为 "project"，带书名为 "book"，
    没有或读不出为 None（与 author_memory_commit.py 的 peek_book_name 同一判据）。"""
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
    """写章代查作者记忆用的创作工作区，按 author-memory.md「存放与路由」认，返回 (目录, 是否认出)。

    依次认：书目录或祖先里的 `.story-deployed`（已部署的宿主）；书目录上一层叫 长篇／短篇 时取再上一层；
    书目录自己就有项目级作者记忆或 `书级/`（单书布局）；最近一个带 `.active-book`、`长篇/`、`短篇/`、`拆文库/`
    或项目级作者记忆的祖先（到用户主目录为止，主目录本身不算）。都没有时把书目录当工作区，但这是猜的：
    DSH 等宿主不写 `.story-deployed`，多书工作区里的书若被当成工作区，查询会报错或把书级记忆挪位。
    """
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
    except (RuntimeError, KeyError):  # 拿不到主目录时一路找到根
        home = None
    for ancestor in project.parents:
        if ancestor == home:
            break
        if any((ancestor / marker).exists() for marker in WORKSPACE_MARKERS) or memory_state_kind(ancestor) == "project":
            return ancestor, True
    return project, False


def genre_line(project: Path):
    """「题材类型」行的原文；未填的模板占位（{…}）当没有。"""
    text = read_text(project / "设定" / "题材定位.md") or ""
    match = re.search(r"^[ \t]*[-*+]?[ \t]*\**题材(?:类型)?\**[ \t]*[：:](.*)$", text, re.M)
    if not match or "{" in match.group(1):
        return ""
    return match.group(1).strip()


def book_genres(project: Path):
    """「题材类型」行按分隔符切成词。"""
    return {word.casefold() for word in re.split(r"[\W_丨×]+", genre_line(project)) if word}


GENRE_CARD_DIR = Path(__file__).resolve().parent.parent / "references" / "genre-prose-cards"


def match_genre_cards(project: Path):
    """题材正文提示卡缺失时，按「题材类型」原文匹配题材卡（卡头的 genre 与 aliases），替主会话省掉整读索引。

    按在题材类型里出现得越靠前越优先（主题材在前），同位置按置信度高→低；最多返回主、辅两张：[(路径, 置信度)]。"""
    raw = genre_line(project).casefold()
    if not raw or not GENRE_CARD_DIR.is_dir():
        return []
    rank = {"high": 0, "medium": 1, "low": 2}
    hits = []
    for card in sorted(GENRE_CARD_DIR.glob("*.md")):
        head = (read_text(card) or "").split("---")
        meta = head[1] if len(head) > 2 else ""
        genre = re.search(r"^genre:\s*(.+)$", meta, re.M)
        aliases = re.search(r"^aliases:\s*\[(.*)\]", meta, re.M)
        confidence = re.search(r"^confidence:\s*(\w+)", meta, re.M)
        names = [genre.group(1).strip()] if genre else [card.stem]
        names += [a.strip() for a in aliases.group(1).split(",")] if aliases else []
        where = [raw.find(name.casefold()) for name in names if name and name.casefold() in raw]
        if where:
            level = confidence.group(1) if confidence else "low"
            hits.append((min(where), rank.get(level, 2), card, level))
    hits.sort(key=lambda row: (row[0], row[1], row[2].name))
    return [(card, level) for _, _, card, level in hits[:2]]


def author_decided(project: Path):
    """`设定/题材定位.md`「## 作者已定」一节：去掉模板占位行；返回 (正文, 是否截断)。没有这一节返回 (None, False)。"""
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
    """代主会话做写正文那一次作者记忆查询（prose_style + story_design）。

    注入块原样用 query 给的 lines 拼——每次查询的 lines ≤2KB，预算量的就是写手读到的这几行，
    这里不另行排版。工作区按 find_workspace 认；认不出、而书目录里又是一份带书名的记忆时不代查——
    那既可能是单书布局的旧版记忆，也可能是没有任何迹象的多书工作区里的一本书，拿书目录当工作区去查，
    后一种会被当成前一种「归位」，此后正确的查询全部报错。
    限定题材的条目只在取值出现在本书「题材类型」里时代查，限定流程的只认长篇写作的取值；
    其余限定条目不猜，报给主会话自己判断。
    返回 (注入行, 没带上的 [(ID, 断言首句)], 未代查的限定取值, 错误)；错误时由主会话按 author-memory.md 手动查询。
    """
    workspace, recognised = find_workspace(project)
    script = Path(__file__).with_name("author_memory_commit.py")
    if not script.is_file():
        return None, [], {}, "author_memory_commit.py 缺失"
    if not recognised and memory_state_kind(project) == "book":
        return None, [], {}, ("认不出创作工作区（书目录及祖先都没有 .active-book、长篇/、短篇/、拆文库/ 或项目级作者记忆），"
                              "书目录里却是本书的记忆；先按 author-memory.md「存放与路由」定好 --workspace")
    scoped = scoped_memory_values(workspace)
    book = book_genres(project)
    genres = sorted(v for v in scoped["genre"] if v.casefold() in book) or [None]
    workflows = sorted(v for v in scoped["workflow"] if v.casefold() in {w.casefold() for w in LONG_WRITE_WORKFLOWS})
    skipped = {"genre": sorted(v for v in scoped["genre"] if v not in genres),
               "workflow": sorted(v for v in scoped["workflow"] if v not in workflows)}
    lines, omitted, summaries, importance, seen = [], [], {}, {}, set()
    for genre in genres:
        for workflow in workflows or [None]:
            command = [sys.executable, str(script), "query", "--workspace", str(workspace), "--book-root", str(project)]
            for kind in MEMORY_KINDS:
                command += ["--kind", kind]
            if genre:
                command += ["--genre", genre]
            if workflow:
                command += ["--workflow", workflow]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
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
    # 每次查询的漏项各自按优先级排好，合并后按重要度重排（同重要度保持先后），
    # 给作者点名的前几条才是最该知道的；某次漏、另一次带上了的不算没带上。
    ranked = sorted((i for i in omitted if i not in seen),
                    key=lambda i: (-IMPORTANCE_RANK.get(importance.get(i), 0), omitted.index(i)))
    missed = [(i, summaries.get(i, "")) for i in ranked]
    return lines, missed, {k: v for k, v in skipped.items() if v}, None


def learn_heading_form(project: Path, chapter: int, title: str):
    """从已有正文学标题行形态（层级／章号填充位数／分隔符），不按通用规则推导。

    通用规则写的是 `## 第N章 章名`，而各书实际形态不一（本仓库某书用 `# 第015章 …`），
    两处都对不上时写手只能自己去翻既有章——每章翻一次。这里替它翻。
    """
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
        if not head:
            continue
        hit = pattern.match(head[0].strip())
        if hit:
            number = int(num.group(1))
            if number < chapter and (best is None or number > best[0]):
                best = (number, hit)
    if best is None:
        return None, "正文/ 下没有可解析标题行的既有章，写手按自身规则处理"
    _, hit = best
    level, gap1, digits, gap2 = hit.group(1), hit.group(2), hit.group(3), hit.group(4)
    # 有前导零才算补零形态，且按它的位数补；`第15章` 这种不补——
    # 否则会从两位数章学出「补到 2 位」，把第 9 章写成 `第09章`。
    if digits.startswith("0"):
        number, how = f"{chapter:0{len(digits)}d}", f"{len(digits)} 位补零"
    else:
        number, how = str(chapter), "不补零"
    return (f"{level}{gap1}第{number}章{gap2 or ' '}{title}",
            f"照既有章形态（{level} ＋ 章号{how}）")


def build(project: Path, chapter: int, report: list):
    errors = []

    outline_file = find_chapter_file(project / "大纲", chapter, "细纲_")
    if outline_file is None:
        errors.append(f"必在块缺失：{project / '大纲'} 下没有第 {chapter} 章细纲")
        return None, errors
    outline_text = read_text(outline_file)
    if not outline_text or not outline_text.strip():
        errors.append(f"必在块缺失：{outline_file} 为空")
        return None, errors

    parts = []
    title = extract_title(outline_text, chapter)

    # ---- 固定首行（指令，不是栏目；漏传即写手不读参考直接开写）----
    parts.append(
        f"本次任务：写第 {chapter} 章，执行范围见「执行安排」。开始前先按「参考文件体系」逐行独立判定命中并读取，"
        "命中即必读，未命中不预加载；交付摘要里报出读了哪几个。")

    parts.append(f"项目目录：{project}")
    parts.append(f"章节：第 {chapter} 章")
    if title:
        out_path = project / "正文" / f"第{chapter:03d}章_{title}.md"
    else:
        return None, [f"细纲缺章名：{outline_file}，需要 ### 第 N 章：章名"]
    if any(char in title for char in '/\\'):
        return None, ["章名不能包含路径分隔符"]
    parts.append(f"最终输出路径：{out_path}")
    if title:
        heading_line, how = learn_heading_form(project, chapter, title)
        if heading_line:
            parts.append(
                f"标题行（逐字照抄，勿按通用规则推导）：{heading_line}")
            report.append(f"标题行：{heading_line}　{how}")
        else:
            report.append(f"标题行：未注入——{how}")

    # ---- 细纲：只给路径，不注入全文 ----
    parts.append(f"细纲文件（动笔前完整读到 EOF）：{outline_file}")

    # ---- 续写状态卡：校验结构；主会话筛选相关状态 ----
    state_file = project / "追踪" / "上下文.md"
    state_text = read_text(state_file)
    if not state_text:
        errors.append(f"必在块缺失：读不到 {state_file}")
    else:
        found = extract_state_sections(state_text)
        missing = [s for s in STATE_SECTIONS if s not in found]
        if missing:
            errors.append(
                f"必在块缺失：{state_file} 缺栏目 " + "、".join(missing) +
                "（续写状态卡应为固定 7 栏，先用 tracking_commit.py 修派生视图）")
        else:
            report.append("续写状态：七栏已校验，主会话按本章需要筛选到「本节速记」")

    # ---- 文风（本书自定义文风时由脚本全包）----
    style_file = project / "设定" / "文风.md"
    style_text = read_text(style_file)
    custom_style = has_custom_style(style_text)
    if custom_style:
        parts.append(f"文风路径：{style_file}（书级权威文风，写作与去味均读全文；摘要只作索引）")
        parts.append(
            "文风优先裁决：`设定/文风.md` 对句段／句法／对话落法／标点形态与删改取向的规定"
            "按 style-resolution.md 裁决：当前请求 > 本书文风 > active 作者记忆 > 对标 > 通用参考；不覆盖细纲事实、信息边界、调用方所选 Gate 范围及文件结构。"
            "风格冲突按文风写，交付摘要列出「因文风优先而未执行的通用条款」。")
        report.append("文风：custom_style=true，表达冲突按维度裁决；reference 读取仍按任务条件")
    else:
        parts.append(
            "——— 文风 ———\n"
            "（本书无可用的 设定/文风.md，未进入自定义文风模式；"
            "按 benchmark-recall.md 走对标文风召回，由主会话补路径与召回指令）")
        report.append("文风：custom_style=false，文风召回归主会话（未跳过，留标题）")

    # ---- 上一章结尾（不给路径，避免写手回头读整章）----
    if chapter > 1:
        prev_file, tail = previous_chapter_tail(project, chapter)
        if prev_file is None or not tail:
            errors.append(f"必在块缺失：找不到或读不到第 {chapter - 1} 章正文")
        else:
            parts.append(
                "——— 上一章结尾（承接用，不重写；全章不需要，故不给路径）———\n" + tail)
            report.append(f"上一章结尾：{prev_file.name} 末 {len(tail)} 字（按整行回退）")

    # ---- 必读设定：整槽归主会话 ----
    slot_setting = (
        "——— 必读设定 ———\n"
        f"{SLOT_MARK} 本章要用到的设定，**直接写出那几句**，不要只给路径让写手去查"
        "（Grep 遇超长行会被截断，最关键那句往往正好被吞）。两处来源都要过："
        "① 细纲里显式引用的 `xxx.md`（连小节一起给）；② 细纲没点名、但本章会碰到的"
        "（术语口径、程序、数字锚）。无则写「无」。")

    # ---- 降档判定与情绪/节奏槽 ----
    unit_field = extract_field(outline_text, "单元ID/位置")
    unit_id = None
    if unit_field:
        match = re.match(r"([A-Za-z0-9\-]+)", unit_field)
        if match:
            unit_id = match.group(1)
    unit_block = None
    if unit_id:
        for volume in sorted((project / "大纲").glob("卷纲_*.md")):
            block = extract_unit_block(read_text(volume) or "", unit_id)
            if block:
                unit_block = block
                break

    target_emotion = extract_field(outline_text, "目标情绪")
    card_text = read_text(project / "设定" / "题材正文提示卡.md")
    engine = extract_field(unit_block or "", "单元情绪引擎")
    tempo = (extract_field(unit_block or "", "单元节拍/章功能分配")
             or extract_field(unit_block or "", "单元节拍／章功能分配"))
    needs = {"题材正文提示卡": card_text, "目标情绪": target_emotion,
             "单元情绪引擎": engine, "单元节拍/章功能分配": tempo}
    why = [name + "缺有效内容" for name, value in needs.items() if not substantive(value)]
    # 无对标（项目与工作区都没有对标书）时文风本就没有对标可召回：不因 custom_style 缺失拒绝降档
    no_benchmark = not any(d.is_dir() for base in (project / "对标", project / "拆文库", project.parent / "拆文库")
                           if base.is_dir() for d in base.iterdir())
    if not custom_style and not no_benchmark:
        why.append("custom_style=false")
    downgrade = not why

    if downgrade:
        lines = [
            "selected_emotion_module：降档（来源：细纲「目标情绪」＋单元卡「单元情绪引擎」）",
            f"  细纲目标情绪：{target_emotion}",
        ]
        if engine:
            lines.append(f"  单元情绪引擎：{engine}")
        lines.append("rhythm_reference：降档（来源：单元卡「单元节拍/章功能分配」）")
        if tempo:
            lines.append(f"  {tempo}")
        slot_recall = "——— 情绪与节奏召回 ———\n" + "\n".join(lines)
        report.append(f"召回降档：成立，{'无对标，' if no_benchmark and not custom_style else '文风、'}题材卡、目标情绪和单元 {unit_id} 情绪/节拍均可用")
    else:
        slot_recall = ("——— 情绪与节奏召回 ———\n"
                       f"{SLOT_MARK} 降档不成立（" + "、".join(why) +
                       "），按 benchmark-recall.md 走全量召回后填此槽")
        report.append("召回降档：不成立（" + "、".join(why) + "）—— 全量召回归主会话")

    # ---- 需要主会话判断的槽位 ----
    work_dir = chapter_work_dir(project, chapter)
    parts.append(
        "——— 执行安排 ———\n"
        f"{SLOT_MARK} 全章细纲用于整体编排。默认按自然转场或因果停顿分前后两组，"
        "填写当前组的情节点/片段；先只写前组，主会话测一次 checkpoint 后"
        "再给后组和机器剩余区间。只有用户明确要求一次成文时才填「全章，直接写最终路径」。\n"
        f"分组临时文件：前组 {work_dir / '前组.md'}，后组 {work_dir / '后组.md'}"
        "（只写这里，不写 /tmp 或 正文/）。")
    parts.append(f"——— 本章意图（一句话）———\n{SLOT_MARK}")
    parts.append("——— 作者本轮要求 ———\n"
                 f"{SLOT_MARK} 作者这次明确说的：字数范围、必须发生、不许发生、写到哪里停、章尾要留什么；没有写「无」。")
    parts.append(slot_recall)
    # 伏笔与卷级禁忌走「主会话筛选后写进速记」这条原设计路线（步骤 3 状态筛选），
    # 不由脚本整栏注入——筛选是判断，而整栏注入还会把伏笔栏里的作者侧真相一并下放。
    # 代价是它依赖主会话逐章想起来，所以这里把提示语写成写死的三问清单。
    parts.append(
        "——— 本章技法 ———\n"
        f"{SLOT_MARK} 按细纲主功能填 打脸／反转／感情／悬疑／日常／无 之一（对照 SKILL.md「本章技法」），"
        "再写一句用在哪几段；写手按自己的读取表读对应文件，这里不摘技法。本书文风只覆盖冲突表达条款，不停读整份文件。")
    parts.append(
        "——— 本节速记 ———\n"
        f"{SLOT_MARK} 按 workflow-chapter 步骤 3「状态筛选」产出（`追踪/上下文.md` 不注入"
        "本 prompt，这一槽是写手唯一的状态来源）：核心角色状态里本章在场的／下一章承诺里本章"
        "必须履行的／连贯性风险里本章相关的／活跃伏笔里**要碰**与**要避**的（只下放禁令，"
        "「作者侧：」之后的真相留在主会话）／长期约束里本章相关的卷级常任禁忌（细纲多半只写"
        "「见卷纲，不复读」，而卷纲不进本 prompt）／久别角色是否补读 `追踪/角色状态/{名}.md`。")
    parts.append(
        "——— 涉及角色 ———\n"
        f"{SLOT_MARK} 按细纲「人物出场顺序」与「镜头准入」的台词位／动作位分配，"
        "列出本章要读的角色卡；本节速记已给全状态的不必再列。")
    if not substantive(card_text):
        cards = match_genre_cards(project)
        if cards:
            named = "；".join(f"{'主' if i == 0 else '辅'}题材 {card}（置信度 {level}）" for i, (card, level) in enumerate(cards))
            report.append(f"题材卡：本书还没有题材正文提示卡，按「题材类型」匹配到 {named}；生成后落盘，后续章直接读")
        else:
            report.append("题材卡：本书还没有题材正文提示卡，题材卡无匹配——读 style-genre-modules.md"
                          "「题材正文提示卡」一节与最接近的流派一节生成后落盘")
    parts.append("——— 题材正文提示卡（genre_prose_card，只含本章相关条目）———\n"
                 f"{SLOT_MARK} 主题材抽 3-5 条、辅题材 1-2 条；只作内部校准，不进正文")
    parts.append(slot_setting)
    decided, cut = author_decided(project)
    if decided:
        note = (f"\n（超过 {AUTHOR_DECIDED_CHARS} 字已截断，其余见 {project / '设定' / '题材定位.md'}「作者已定」，动笔前读完）"
                if cut else "")
        parts.append("——— 作者已定（本书的决定，高于作者记忆，与细纲冲突以细纲为准并在交付摘要里说明）———\n"
                     + decided + note)
        report.append("作者已定：已注入" + ("（超长截断，写手需回原文读完）" if cut else ""))
    else:
        report.append("作者已定：题材定位里没有或为空，未注入")
    lines, missed, skipped, memory_error = query_author_memory(project)
    if memory_error:
        memory_block = (f"{SLOT_MARK} 组装脚本查询作者记忆失败（{memory_error}），"
                        "按 author-memory.md 手动 query prose_style + story_design 后填入；无则写「无」")
        report.append(f"作者记忆：脚本查询失败——{memory_error}，归主会话手动查询；手查有没带上的（任一次查询带上了的不算），章末照模板那一行用原话说")
    else:
        memory_block = "\n".join(lines) if lines else "无"
        report.append(f"作者记忆：已注入 {len(lines)} 条" if lines or missed else "作者记忆：无相关 active 条目")
    if missed:
        # 装不下的不能悄悄略过：拼好给作者的原话，章末汇报照模板那一行原样说。
        shown = "".join(f"「{summary or item_id}」" for item_id, summary in missed[:MISSED_SHOWN])
        more = "等" if len(missed) > MISSED_SHOWN else ""
        report.append(
            f"作者记忆：装不下、这章没带上 {len(missed)} 条（{'、'.join(i for i, _ in missed)}），章末汇报原样说这句——"
            f"你记下的写作习惯这章有 {len(missed)} 条没带上：{shown}{more}；"
            "说「整理作者记忆」可以合并相近的、调低不常用的。")
    if skipped and not memory_error:
        named = "；".join(f"{'题材' if k == 'genre' else '流程'}：{'、'.join(v)}" for k, v in skipped.items())
        memory_block += (f"\n{SLOT_MARK} 另有限定范围的作者记忆未代查（{named}）：本书适用的，"
                         "带 --genre／--workflow 跑 SKILL.md「核心方法」的 query 命令（--kind prose_style --kind story_design）后补进本块")
        report.append(f"作者记忆：限定范围未代查（{named}），归主会话判断是否适用；补查有没带上的（已在本块里的不算），章末照模板那一行用原话说")
    parts.append("——— author_preferences（作者记忆，低优先级倾向，不逐条追求命中）———\n" + memory_block)
    parts.append("——— style_resolution ———\n"
                 f"{SLOT_MARK} 本轮请求里作者对表达的明确要求及其覆盖的默认条款（没有写「无」）；"
                 "本书文风与作者记忆的裁决见上方各块，同一裁决传去味与审稿。")

    parts.append("检查分工：写手负责编排、内容覆盖和格式自检；主会话质量阶段负责语义去味及最终文件扫描。写手不提前重复整轮去味或相同检查链，保留情节点落点、新增申报与原定交付。")

    # ---- 固定块：压成指针，不重述 agent 定义 ----
    parts.append(
        "本次照你的铁律 1-8 与被调用协议执行（细纲优先边界、正文形状、新增物三级、"
        "阅读体验字段、交付三附件均以你的定义为准，此处不重述）。")
    parts.append(
        "字数目标按细纲执行，字数口径 visible_chars_v1；按执行安排交付，"
        "目标按整章分量刻度使用，疏密自行分配，不拆逐点配额；不自测字数。")

    if errors:
        return None, errors

    prompt = "\n\n".join(parts) + "\n"

    return prompt, []


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

    report = []
    prompt, errors = build(project, args.chapter, report)
    if prompt is None:
        sys.stderr.write("组装中止，先修数据再重跑（这不是回落手拼的理由）：\n")
        for item in errors:
            sys.stderr.write(f"  - {item}\n")
        return 2

    # 标题预检：正文目录里有没有同名章
    title = None
    outline_file = find_chapter_file(project / "大纲", args.chapter, "细纲_")
    if outline_file:
        title = extract_title(read_text(outline_file) or "", args.chapter)
    if title:
        clashes = [p.name for p in sorted((project / "正文").glob("*.md"))
                   if p.name.endswith(f"_{title}.md")
                   and not p.name.startswith(f"第{args.chapter:03d}章")]
        report.append(
            f"标题预检：《{title}》" + ("与既有章重名 → " + "、".join(clashes)
                                       if clashes else "无重名"))

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
    sys.stdout.write(
        f"- 待填槽位：{prompt.count(SLOT_MARK)} 个（搜 {SLOT_MARK}）\n")
    sys.stdout.write(f"- 骨架长度：{len(prompt)} 字符\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
