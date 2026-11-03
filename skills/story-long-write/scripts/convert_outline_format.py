#!/usr/bin/env python3
"""convert_outline_format.py — 把 0.9.2 及以前的卷纲、细纲、排纲底稿换成 0.10 的写法（可选，只换格式不改内容）。

老写法照样能用：取段器、细纲检查、写正文的脚本新旧都认，不转也行。作者想要干净的文件时跑一次：

    python convert_outline_format.py <书目录>            # 转 大纲/ 下全部卷纲、细纲、排纲底稿
    python convert_outline_format.py <书目录> --dry-run  # 只列出会改哪些文件，不写

转了什么：
- 卷纲：标题下一行的「> 作用域：卷级常任／单元级 L1-01／批次底稿 L1-01｜状态：…」挪成标题末尾注释
  （<!-- 全卷 --> / <!-- L1-01 --> / <!-- 批次底稿 L1-01｜状态：… -->）；「### 剧情单元 L1-03」改成
  「### 第三段剧情」（编号进注释）；卡里字段名、几个小节名换成白话（对照表见 VOLUME_LABELS / VOLUME_HEADINGS），
  「契约安全／需补强／契约破坏」换成「没问题／要补／有硬伤」；「- 单元ID：L1-01」这一行删掉（编号已在标题注释里）。
- 细纲：删「字数口径：visible_chars_v1」行；「单元ID/位置」→「属于哪段剧情」（编号进行末注释）；
  「本章禁止提前释放」→「这章不能说破」；情节点表头「功能标签」→「作用」、「执行边界（禁＋放）」→「分寸」；
  「复沓锚句」→「原样出现的原话」；「契约风险」「风险等级」→「有没有硬伤」。
- 排纲底稿_{编号}.md → 排纲笔记_{编号}.md，小节「供给自查」→「写纲前查缺」、「建纲追加」→「写纲时补的」。

不删内容：新模板不再要的刻度台阶、打脸债、压力线轮转三张表原样留着，转完列出来，作者自己决定删不删。
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
    ("本卷解锁的终局里程碑", "本卷亮出的大牌"),
    ("本卷禁碰的终局底牌", "本卷不能碰的大牌"),
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
    ("本单元主推线/战果", "这段主推哪条线、顺带收获什么"),
    ("本单元在跑的线", "这段在动的其他线"),
    ("终局底牌边界", "这段不能碰的大牌"),
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
]
RISK_VALUES = [("契约安全", "没问题"), ("需补强", "要补"), ("契约破坏", "有硬伤")]
NOTE_HEADINGS = [("供给自查", "写纲前查缺"), ("建纲追加", "写纲时补的")]
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

    def handle(index, line):
        if index in drop:
            return None
        heading = HEADING.match(line)
        if heading:
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
        return relabel(line, VOLUME_LABELS)

    return "\n".join(walk(lines, handle)), leftovers


def convert_chapter(text: str) -> str:
    def handle(_index, line):
        if re.match(r"^[ \t>]*[-*+]?[ \t]*\**字数口径\**[ \t]*[：:][ \t]*visible_chars_v1\b.*$", line):
            return None
        field = re.match(r"^([ \t>]*[-*+][ \t]*\**)单元ID/位置(\**[ \t]*[：:][ \t]*)(.*?)\s*$", line)
        if field:
            value = field.group(3)
            found = re.search(r"(?<![\w-])([LD])\d+-(\d+)(?![\w-])", value)
            if found:
                unit = found.group(0)
                rest = re.sub(r"^[\s；;，,、/|｜]+", "", value.replace(unit, "", 1)).strip()
                visible = f"第{ordinal(int(found.group(2)))}段剧情" + ("，" + rest if rest else "")
                return f"{field.group(1)}属于哪段剧情{field.group(2)}{visible} <!-- {unit} -->"
            return f"{field.group(1)}属于哪段剧情{field.group(2)}{value}"
        if line.lstrip().startswith("|") and ("功能标签" in line or "执行边界" in line):
            line = line.replace("功能标签", "作用")
            line = re.sub(r"执行边界(?:[（(][^）)]*[）)])?", "分寸", line)
            return line
        return relabel(line, CHAPTER_LABELS)

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
        return line

    return "\n".join(walk(text.split("\n"), handle))


def read(path: Path) -> str:
    with io.open(path, encoding="utf-8-sig") as handle:
        return handle.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把老卷纲、细纲、排纲底稿换成 0.10 写法（只换格式不改内容）")
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
    for path in volumes:
        old = read(path)
        new, left = convert_volume(old)
        leftovers += [f"{path.name}「{title}」" for title in left]
        if new != old:
            changed.append(path.name)
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    for path in sorted(outline_dir.glob("细纲_*.md")):
        old = read(path)
        new = convert_chapter(old)
        if new != old:
            changed.append(path.name)
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    for path in sorted(outline_dir.glob("排纲底稿_*.md")):
        target = path.with_name(path.name.replace("排纲底稿_", "排纲笔记_", 1))
        if target.exists():
            print(f"跳过 {path.name}：{target.name} 已存在，两份请作者自己合并")
            continue
        changed.append(f"{path.name} → {target.name}")
        if not args.dry_run:
            target.write_text(convert_notes(read(path)), encoding="utf-8")
            path.unlink()
    for path in sorted(outline_dir.glob("排纲笔记_*.md")):
        if args.dry_run:
            continue
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
