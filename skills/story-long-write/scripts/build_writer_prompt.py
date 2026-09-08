#!/usr/bin/env python3
"""build_writer_prompt.py — 确定性组装 narrative-writer 的 spawn prompt 骨架。

用法:
    python build_writer_prompt.py --project <书目录> --chapter N [--out <文件>]

跑在「写前准备」第一步。stdout 分两区，`===` 分隔线以上是 prompt 正文
（主会话照抄，空槽以外一字不改），以下是核对报告（不进 prompt）。

职责边界:
- 脚本做确定性部分：固定首行、定位、标题行字面量、细纲指针、文风三行与判读的通用参考、
  上一章结尾、降档判定与情绪/节奏槽、固定块指针。
- 主会话填八槽：执行安排 / 本章意图 / 参考技法 / 本节速记 / 涉及角色 / genre_prose_card /
  必读设定 / author_preferences。降档不成立时情绪与节奏槽也归主会话。
  材料槽对应原流程步骤 3「写前准备」的四项输出（本节速记 / 情绪目标 / 涉及角色 /
  参考技法）加上题材卡、设定补漏与作者偏好——都是判断，脚本做不了。
- 续写状态卡校验后由主会话筛选，在「本节速记」槽内写入本章需要的状态。
- 可选块缺失留标题并写明原因（「没有」与「漏了」在产物上必须长得不一样）。
  必在块缺失退出码 2 —— 那是数据问题，要修数据后重跑，不是回落手拼的理由。

Exit: 0 = 骨架已输出；2 = 输入缺失或无效。
"""

import argparse
import io
import re
import sys
from pathlib import Path
from outline_view import parse as parse_volume

TAIL_CHARS = 400          # 上一章结尾注入的目标字符数（按整行回退，不切半句）
STATE_SECTIONS = ("当前位置", "长期约束", "核心角色状态", "活跃伏笔", "近三章速记", "下一章承诺", "连贯性风险")
SLOT_MARK = "［主会话填］"


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
    pattern = re.compile(rf"^{prefix}第0*{chapter}章.*\.md$")
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and pattern.match(entry.name):
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


def parse_reference_ruling(style_text: str):
    """扫 设定/文风.md「通用参考裁决」表，返回 (停读清单, 判读的行)。"""
    skips, reads = [], []
    for line in style_text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = re.sub(r"[`*]", "", cells[0]).strip()
        if not name.endswith(".md") and not name.endswith("/*"):
            continue
        if re.match(r"^停读(?:$|[（(\s])", cells[1]):
            skips.append(name)
        elif "读" in cells[1]:
            caveat = re.sub(r"[`*]", "", cells[1]).strip()
            caveat = re.sub(r"^读\s*[（(]?", "", caveat).rstrip("）)").strip()
            reads.append(f"{name}（{caveat}）" if caveat else name)
    return skips, reads


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
        skips, reads = parse_reference_ruling(style_text)
        if skips:
            parts.append("本书停读清单（整行跳过、不判定不读取）：" + "、".join(skips))
        if reads:
            parts.append("本书判读的通用参考：" + "；".join(reads))
        report.append(
            f"文风：custom_style=true，停读 {len(skips)} 项、判读 {len(reads)} 项")
    else:
        parts.append(
            "——— 文风 ———\n"
            "（本书无可用的 设定/文风.md，未进入自定义文风模式；"
            "按 workflow-chapter 3(d) 走对标文风召回，由主会话补路径与召回指令）")
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
    if not custom_style:
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
        report.append(f"召回降档：成立，文风、题材卡、目标情绪和单元 {unit_id} 情绪/节拍均可用")
    else:
        slot_recall = ("——— 情绪与节奏召回 ———\n"
                       f"{SLOT_MARK} 降档不成立（" + "、".join(why) +
                       "），按 workflow-chapter 3(a)(b)(e)(f) 走全量召回后填此槽")
        report.append("召回降档：不成立（" + "、".join(why) + "）—— 全量召回归主会话")

    # ---- 需要主会话判断的槽位 ----
    parts.append(
        "——— 执行安排 ———\n"
        f"{SLOT_MARK} 全章细纲用于整体编排。默认按自然转场或因果停顿分前后两组，"
        "填写当前组的情节点/片段及临时输出路径；先只写前组，父流程测一次 checkpoint 后"
        "再给后组和机器剩余区间。只有用户明确要求一次成文时才填「全章，直接写最终路径」。")
    parts.append(f"——— 本章意图（一句话）———\n{SLOT_MARK}")
    parts.append(slot_recall)
    # 伏笔与卷级禁忌走「主会话筛选后写进速记」这条原设计路线（步骤 3 状态筛选），
    # 不由脚本整栏注入——筛选是判断，而整栏注入还会把伏笔栏里的作者侧真相一并下放。
    # 代价是它依赖主会话逐章想起来，所以这里把提示语写成写死的三问清单。
    parts.append(
        "——— 参考技法 ———\n"
        f"{SLOT_MARK} 步骤 3 三问的第 ②③ 问：借鉴哪个参考文件的哪个技法、用在哪些段落。"
        "上面「判读的通用参考」是书级可读范围，不是本章取用；本书自定义文风优先，"
        "通用参考只作技法示例、不给验收线。")
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
    parts.append("——— 题材正文提示卡（genre_prose_card，只含本章相关条目）———\n"
                 f"{SLOT_MARK} 主题材抽 3-5 条、辅题材 1-2 条；只作内部校准，不进正文")
    parts.append(slot_setting)
    parts.append("——— style_resolution / author_preferences ———\n"
                 f"{SLOT_MARK} author_memory query 命中本章的 prose_style/story_design 项；"
                 "query 显式传本书/题材/流程；偏好是低优先级倾向，无则写「无」。附 style_resolution：生效要求及来源、被覆盖的默认条款和事实边界；同一裁决传去味与审稿，不逐条追求命中。")

    # ---- 固定块：压成指针，不重述 agent 定义 ----
    parts.append(
        "本次照你的铁律 1-8 与被调用协议执行（细纲优先边界、正文形状、新增物三档、"
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
    parser.add_argument("--out", default=None)
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

    if args.out:
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(prompt)
        report.append(f"留档：{args.out}")

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
