#!/usr/bin/env python3
"""convert_outline_format.py — 把老写法的卷纲、细纲、排纲笔记换成 0.10 的写法（可选，只换格式不改内容）。

老写法照样能用：取段器、细纲检查、写正文的脚本新旧都认，不转也行。作者想要干净的文件时跑一次：

    python convert_outline_format.py <书目录>            # 转 大纲/ 下全部卷纲、细纲，挪走排纲笔记
    python convert_outline_format.py <书目录> --dry-run  # 只列出会改哪些文件，不写

转了什么：
- 卷纲：标题下一行的「> 作用域：卷级常任／单元级 L1-01／批次底稿 L1-01｜状态：…」挪成标题末尾注释
  （<!-- 全卷 --> / <!-- L1-01 --> / <!-- 批次底稿 L1-01｜状态：… -->）；「### 剧情单元 L1-03」改成
  「### 第三段剧情」（编号进注释）；卡里字段名、几个小节名换成白话（对照表见 VOLUME_LABELS / VOLUME_HEADINGS），
  「契约安全／需补强／契约破坏」换成「没问题／要补／有硬伤」；「- 单元ID：L1-01」这一行删掉（编号已在标题注释里）；
  情绪弧线的松紧标签换成白话（高压→爆发、修炼试错→修炼、关系回收→感情或关系戏、低压生活→日常、信息整理→过渡）；
  「无对标，按八节点自排」→「没有对标书，按常见的八步结构排」。
- 大纲.md 分卷表末列、设定/题材定位.md「留到后面的大牌」一节换成「后面才揭开或用上的东西」。
- 细纲：删「字数口径：visible_chars_v1」行；「单元ID/位置」→「属于哪段剧情」，只留段名（「第三段剧情，…」），
  不写编号——脚本按章号落在卷纲哪段剧情的章节范围里定位；卷纲里找不到覆盖本章的剧情段时编号留在行末注释里。
  0.10 早期行末带编号注释的同样处理。「本章禁止提前释放」→「这章不能说破」；「内容概括（五段式）」→「这章怎么走」；
  「写手自由区」→「可以放开写的地方」；情节点表头「功能标签」→「作用」、「执行边界（禁＋放）」→「分寸」；
  「复沓锚句」→「原样出现的原话」；「契约风险」「风险等级」→「有没有硬伤」；松紧标签同卷纲。
- 排纲笔记挪出作者目录：大纲/排纲笔记_{编号}.md、大纲/排纲底稿_{编号}.md → .story/排纲笔记/{编号}.md，
  小节「供给自查」→「写纲前查缺」、「建纲追加」→「写纲时补的」，「场景与底图」→「场景与布局」。

不删内容：新模板不再要的刻度台阶、打脸债、压力线轮转三张表原样留着，转完列出来，作者自己决定删不删。
细纲、卷纲里提到伏笔的编号（F057）不自动换成伏笔内容，按需自己改。
代码围栏里的内容不动。转完对每份卷纲跑一次 `outline_view.py --check`，结果打印出来。
重复运行不会再改（已是新写法的行原样跳过）。
Exit: 0 = 完成（含无事可做）；1 = 转完的卷纲 --check 有问题；2 = 参数错误。
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from outline_view import chapter_unit_in_volume  # noqa: E402
HEADING = re.compile(r"^(#{2,4})(\s+)(.*?\S)\s*$")
SCOPE = re.compile(r"^>\s*作用域[：:]\s*(.+?)\s*$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
DIGITS = "零一二三四五六七八九"

# 卷纲小节名（标题以它开头即换，后面的括注照留）
VOLUME_HEADINGS = [
    ("卷契约与终局储备", "这卷读者等着看什么"),
    ("剧情单元卡", "本卷剧情"),
    ("全卷常任裁定", "全卷规矩"),
    ("对标结构坐标", "照对标排的关键位置"),
    ("本卷伏笔（F 编号唯一分配处；表按编号排）", "本卷伏笔"),
    ("本卷故事线（L 编号唯一分配处；主线之外至少 2 条）", "本卷故事线"),
]
# 卷纲列表字段名
VOLUME_LABELS = [
    ("卷契约", "读者期待"),
    ("本卷战果", "本卷顺带的收获"),
    ("本卷解锁的终局里程碑", "这卷揭开或用上的"),
    ("本卷亮出的大牌", "这卷揭开或用上的"),
    ("本卷禁碰的终局底牌", "这卷先不能揭开、不能用上的"),
    ("本卷不能碰的大牌", "这卷先不能揭开、不能用上的"),
    ("本卷主推线", "这卷主打哪条线"),
    ("单元节拍/章功能分配", "这段怎么排"),
    ("单元节拍／章功能分配", "这段怎么排"),
    ("单元承诺", "这段答应读者什么"),
    ("单元情绪引擎", "这段让读者图什么"),
    ("卷级贡献", "对这卷的用处"),
    ("主角局部目标与核心利益", "主角这段要什么"),
    ("主角局部目标", "主角这段要什么"),
    ("因果入口", "怎么接上前面"),
    ("关键选择与决定性行动", "主角的关键选择和出手"),
    ("兑现方式与归属", "怎么兑现、好处归谁"),
    ("本单元主推线/战果", "这段主打哪条线、顺带收获什么"),
    ("这段主推哪条线、顺带收获什么", "这段主打哪条线、顺带收获什么"),
    ("本单元在跑的线", "这段在动的其他线"),
    ("终局底牌边界", "这段先不能揭开、不能用上的"),
    ("这段不能碰的大牌", "这段先不能揭开、不能用上的"),
    ("禁止提前释放", "这段不能说破"),
    ("下一单元因果钩子", "怎么引出下一段"),
    ("契约风险", "有没有硬伤"),
    ("风险等级", "有没有硬伤"),
]
# 细纲列表字段名（「单元ID/位置」另行处理）
CHAPTER_LABELS = [
    ("本章禁止提前释放", "这章不能说破"),
    ("复沓锚句", "原样出现的原话"),
    ("契约风险", "有没有硬伤"),
    ("风险等级", "有没有硬伤"),
    ("章节定位", "松紧"),
    ("写手自由区", "可以放开写的地方"),
]
# 细纲小节名（标题以它开头即整个换掉，括注「（五段式）」一并去掉）
CHAPTER_HEADINGS = [("内容概括", "这章怎么走")]
RISK_VALUES = [("契约安全", "没问题"), ("需补强", "要补"), ("契约破坏", "有硬伤")]
NOTE_HEADINGS = [("供给自查", "写纲前查缺"), ("建纲追加", "写纲时补的")]
NOTE_LABELS = [("场景与底图", "场景与布局")]
# 每章松紧标签（情绪弧线表的松紧列、细纲「松紧」行）；「推进」不变
SLACK_VALUES = [("普通推进", "推进"), ("高压", "爆发"), ("修炼试错", "修炼"), ("关系回收", "感情或关系戏"),
                ("低压生活", "日常"), ("信息整理", "过渡")]
NO_BENCHMARK = ("无对标，按八节点自排", "没有对标书，按常见的八步结构排")
# 大纲.md 分卷表末列表头、题材定位里那一节
OVERVIEW_CELLS = [("这卷读者等着看什么、亮哪张大牌", "这卷读者等着看什么、揭开或用上什么")]
GENRE_HEADING = re.compile(r"^(##\s+)留到后面的大牌.*$")
GENRE_LABELS = [("大牌（用一次就没了，标最早第几卷亮出）", "用一次就没了的（标最早第几卷揭开或用上）")]
UNIT_COMMENT = re.compile(r"\s*<!--\s*([A-Za-z]\d+-\d+)\s*-->\s*$")
DROPPED_TABLES = ("刻度台阶", "打脸债", "压力线轮转")


def ordinal(number: int) -> str:
    """3 → 三，12 → 十二，20 → 二十；超过 99 用阿拉伯数字。"""
    if number < 10:
        return DIGITS[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return ("" if tens == 1 else DIGITS[tens]) + "十" + (DIGITS[ones] if ones else "")
    return str(number)


def unit_title(title: str, unit: str | None) -> str:
    """「剧情单元 L1-03：码头」→「第三段剧情：码头」；编号不是 L/D 卷号-序号式就只去掉编号。"""
    match = re.match(r"^剧情单元\s+([A-Za-z][\w-]*)\s*(.*)$", title)
    if not match:
        return title
    found = re.fullmatch(r"[A-Za-z]\d+-(\d+)", match.group(1))
    rest = match.group(2).strip()
    head = f"第{ordinal(int(found.group(1)))}段剧情" if found else "剧情段"
    return head + (rest if rest.startswith(("：", ":")) or not rest else "：" + rest)


def scope_comment(scope: str) -> str:
    parts = re.split(r"[｜|]", scope, maxsplit=1)
    head = parts[0].strip()
    if head == "卷级常任":
        head = "全卷"
    elif head.startswith("单元级"):
        head = head[len("单元级"):].strip() or head
    return head + ("｜" + parts[1].strip() if len(parts) > 1 else "")


def slack(value: str) -> str:
    for old, new in SLACK_VALUES:
        value = value.replace(old, new)
    return value


def relabel(line: str, pairs, risk: bool = True) -> str:
    for old, new in pairs:
        pattern = re.compile(rf"^([ \t>]*[-*+][ \t]*\**){re.escape(old)}(\**[ \t]*[：:])")
        if pattern.match(line):
            line = pattern.sub(lambda m: m.group(1) + new + m.group(2), line, count=1)
            if risk and new == "有没有硬伤":
                for old_value, new_value in RISK_VALUES:
                    line = re.sub(rf"([：:][ \t]*`?){re.escape(old_value)}", rf"\g<1>{new_value}", line, count=1)
            break
    return line


def walk(lines, handle):
    """逐行处理，代码围栏里的行原样留。handle(index, line) 返回新行或 None（删掉这一行）。"""
    out, fence = [], None
    for index, line in enumerate(lines):
        marker = FENCE.match(line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            out.append(line)
            continue
        if fence:
            out.append(line)
            continue
        result = handle(index, line)
        if result is not None:
            out.append(result)
    return out


def convert_volume(text: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    drop: set[int] = set()
    comments: dict[int, str] = {}
    # 先找「标题 + 下一行非空的作用域行」
    fence = None
    for index, line in enumerate(lines):
        marker = FENCE.match(line)
        if marker:
            value = marker.group(1)
            fence = value if fence is None else (None if value[0] == fence[0] and len(value) >= len(fence) else fence)
            continue
        if fence or not HEADING.match(line) or "<!--" in line:
            continue
        nxt = next((j for j in range(index + 1, len(lines)) if lines[j].strip()), None)
        if nxt is not None and SCOPE.match(lines[nxt]):
            comments[index] = scope_comment(SCOPE.match(lines[nxt]).group(1))
            drop.add(nxt)
            # 作用域行后面紧跟的空行与标题后的空行重复时去掉一行
            if nxt + 1 < len(lines) and not lines[nxt + 1].strip() and nxt - 1 > index and not lines[nxt - 1].strip():
                drop.add(nxt + 1)
    leftovers: list[str] = []
    state = {"arc": False}

    def handle(index, line):
        if index in drop:
            return None
        heading = HEADING.match(line)
        if heading:
            state["arc"] = any(name in heading.group(3) for name in ("情绪弧线", "松还是紧", "排班"))
            level, gap, title = heading.groups()
            comment = None
            trailing = re.match(r"^(.*?)\s*<!--\s*(.*?)\s*-->$", title)
            if trailing:
                title, comment = trailing.group(1), trailing.group(2)
            if comments.get(index):
                comment = comments[index]
            unit = re.match(r"^剧情单元\s+([A-Za-z][\w-]*)", title)
            if unit and not comment:
                comment = unit.group(1)
            title = unit_title(title, unit.group(1) if unit else None)
            for old, new in VOLUME_HEADINGS + NOTE_HEADINGS:
                if title.startswith(old):
                    title = new + title[len(old):]
                    break
            if any(name in title for name in DROPPED_TABLES):
                leftovers.append(title)
            return f"{level}{gap}{title}" + (f" <!-- {comment} -->" if comment else "")
        if re.match(r"^[ \t]*[-*+][ \t]*\**单元ID\**[ \t]*[：:][ \t]*[A-Za-z][\w-]*[ \t]*$", line):
            return None
        if state["arc"] and line.lstrip().startswith("|"):
            cells = line.split("|")
            if len(cells) > 3:
                cells[2] = slack(cells[2])
                return "|".join(cells)
        line = line.replace(*NO_BENCHMARK)
        return relabel(line, VOLUME_LABELS)

    return "\n".join(walk(lines, handle)), leftovers


def convert_chapter(text: str, located: str | None = None) -> str:
    """located：卷纲按章号查到的本章剧情段编号。和细纲里写的编号一致时不再在行末留编号注释。"""
    def keep_comment(unit: str) -> str:
        return "" if located == unit else f" <!-- {unit} -->"

    def handle(_index, line):
        if re.match(r"^[ \t>]*[-*+]?[ \t]*\**字数口径\**[ \t]*[：:][ \t]*visible_chars_v1\b.*$", line):
            return None
        heading = HEADING.match(line)
        if heading:
            level, gap, title = heading.groups()
            for old, new in CHAPTER_HEADINGS:
                if title.startswith(old):
                    return f"{level}{gap}{new}"
            return line
        field = re.match(r"^([ \t>]*[-*+][ \t]*\**)单元ID/位置(\**[ \t]*[：:][ \t]*)(.*?)\s*$", line)
        if field:
            value = field.group(3)
            found = re.search(r"(?<![\w-])([A-Za-z])\d+-(\d+)(?![\w-])", value)
            if found:
                unit = found.group(0)
                rest = re.sub(r"^[\s；;，,、/|｜]+", "", value.replace(unit, "", 1)).strip()
                visible = f"第{ordinal(int(found.group(2)))}段剧情" + ("，" + rest if rest else "")
                return f"{field.group(1)}属于哪段剧情{field.group(2)}{visible}{keep_comment(unit)}"
            return f"{field.group(1)}属于哪段剧情{field.group(2)}{value}"
        current = re.match(r"^([ \t>]*[-*+][ \t]*\**属于哪段剧情\**[ \t]*[：:].*?)" + UNIT_COMMENT.pattern, line)
        if current:
            return current.group(1).rstrip() + keep_comment(current.group(2))
        if line.lstrip().startswith("|") and ("功能标签" in line or "执行边界" in line):
            line = line.replace("功能标签", "作用")
            line = re.sub(r"执行边界(?:[（(][^）)]*[）)])?", "分寸", line)
            return line
        line = relabel(line, CHAPTER_LABELS)
        if re.match(r"^[ \t>]*[-*+][ \t]*\**松紧\**[ \t]*[：:]", line):
            line = slack(line)
        return line

    return "\n".join(walk(text.split("\n"), handle))


def convert_overview(text: str) -> str:
    def handle(_index, line):
        for old, new in OVERVIEW_CELLS:
            if line.lstrip().startswith("|"):
                line = line.replace(old, new)
        return line

    return "\n".join(walk(text.split("\n"), handle))


def convert_genre(text: str) -> str:
    def handle(_index, line):
        if GENRE_HEADING.match(line):
            return GENRE_HEADING.match(line).group(1) + "后面才揭开或用上的东西"
        return relabel(line, GENRE_LABELS, risk=False)

    return "\n".join(walk(text.split("\n"), handle))


def convert_notes(text: str) -> str:
    def handle(_index, line):
        heading = HEADING.match(line) or re.match(r"^(#)(\s+)(.*?\S)\s*$", line)
        if heading:
            level, gap, title = heading.groups()
            title = title.replace("排纲底稿", "排纲笔记")
            for old, new in NOTE_HEADINGS:
                if title.startswith(old):
                    title = new + title[len(old):]
            return f"{level}{gap}{title}"
        return relabel(line, NOTE_LABELS, risk=False)

    return "\n".join(walk(text.split("\n"), handle))


def read(path: Path) -> str:
    with io.open(path, encoding="utf-8-sig") as handle:
        return handle.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把老卷纲、细纲、排纲笔记换成 0.10 写法（只换格式不改内容）")
    parser.add_argument("book", type=Path, help="书目录（含 大纲/）")
    parser.add_argument("--dry-run", action="store_true", help="只列出会改哪些文件")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    outline_dir = args.book / "大纲"
    if not outline_dir.is_dir():
        print(f"找不到 {outline_dir}", file=sys.stderr)
        return 2

    changed: list[str] = []
    leftovers: list[str] = []
    volumes = sorted(outline_dir.glob("卷纲_*.md"))
    converted: list[str] = []
    for path in volumes:
        old = read(path)
        new, left = convert_volume(old)
        converted.append(new)
        leftovers += [f"{path.name}「{title}」" for title in left]
        if new != old:
            changed.append(path.name)
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    # 按章号定位剧情段用转换后的卷纲（dry-run 时也用内存里的转换结果）
    for path in sorted(outline_dir.glob("细纲_*.md")):
        number = re.match(r"^细纲_第0*(\d+)章", path.name)
        located = None
        if number:
            located = next(filter(None, (chapter_unit_in_volume(text, int(number.group(1))) for text in converted)), None)
        old = read(path)
        new = convert_chapter(old, located)
        if new != old:
            changed.append(path.name)
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    for path, convert in ((outline_dir / "大纲.md", convert_overview),
                          (args.book / "设定" / "题材定位.md", convert_genre)):
        if not path.is_file():
            continue
        old = read(path)
        new = convert(old)
        if new != old:
            changed.append(str(path.relative_to(args.book)))
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    notes_dir = args.book / ".story" / "排纲笔记"
    # 新名优先：同一段既有排纲笔记_ 又有排纲底稿_ 时先挪笔记，底稿留给作者合并
    sources = sorted(outline_dir.glob("排纲笔记_*.md")) + sorted(outline_dir.glob("排纲底稿_*.md"))
    for path in sources:
        unit = path.stem.split("_", 1)[1]
        target = notes_dir / f"{unit}.md"
        if target.exists():
            print(f"跳过 {path.name}：{target.relative_to(args.book)} 已存在，两份请作者自己合并")
            continue
        changed.append(f"{path.name} → {target.relative_to(args.book)}")
        if not args.dry_run:
            notes_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(convert_notes(read(path)), encoding="utf-8")
            path.unlink()
    if notes_dir.is_dir() and not args.dry_run:
        for path in sorted(notes_dir.glob("*.md")):
            old = read(path)
            new = convert_notes(old)
            if new != old:
                path.write_text(new, encoding="utf-8")

    verb = "会改" if args.dry_run else "改了"
    print(f"{verb} {len(changed)} 个文件" + ("：" + "、".join(changed) if changed else "（已经是新写法）"))
    if leftovers:
        print("新模板不再要这几张表，内容原样留着，要不要删你定：" + "、".join(leftovers))
    status = 0
    if not args.dry_run:
        for path in volumes:
            result = subprocess.run([sys.executable, str(HERE / "outline_view.py"), "--check", str(path)],
                                    capture_output=True, text=True, encoding="utf-8")
            summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()
            print(f"{path.name} 检查：{summary}")
            if result.returncode:
                status = 1
                print(result.stdout)
    return status


if __name__ == "__main__":
    sys.exit(main())
