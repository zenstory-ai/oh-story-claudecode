#!/usr/bin/env python3
"""Render the character-relationship charts from 角色/角色关系.md.

The Markdown file ``人物关系图/人物关系图.md`` (Mermaid graphs plus a plain
list) is always written: it shows Chinese names in any Markdown viewer. PNG
pictures are optional (``--png``) and are drawn only when matplotlib and a font
that really contains Chinese glyphs are available. Without such a font no PNG is
written, so names are never replaced by pinyin, initials or empty boxes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


RELATION_FILE = Path("角色") / "角色关系.md"
CHART_DIR = Path("人物关系图")
CHART_MD = CHART_DIR / "人物关系图.md"
CORE_PNG = CHART_DIR / "核心人物关系.png"
EVOLUTION_PNG = CHART_DIR / "关键关系演变.png"
ARROW_RE = re.compile(r"\s*(?:→|->|⇒|=>|—>|－>)\s*")
# Common Simplified-Chinese capable fonts on macOS, Windows and Linux.
CJK_FONT_NAMES = (
    "PingFang SC", "Hiragino Sans GB", "Heiti SC", "STHeiti", "Songti SC", "STSong",
    "Microsoft YaHei", "SimHei", "SimSun", "DengXian",
    "Noto Sans CJK SC", "Noto Sans SC", "Noto Serif CJK SC", "Source Han Sans SC",
    "Source Han Sans CN", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Sarasa Gothic SC",
    "Arial Unicode MS",
)
NO_FONT_MESSAGE = (
    "这台电脑上没有找到能显示中文的字体，所以没有生成关系图图片（硬画会把人名变成拼音或方块）。"
    "关系图已经写在 人物关系图/人物关系图.md 里，用能预览 Markdown 的编辑器打开就能看到中文；"
    "装上任意一款中文字体（如思源黑体、文泉驿）后再生成一次，就能得到图片版。"
)
NO_MATPLOTLIB_MESSAGE = (
    "当前环境不能画图片，关系图已经写在 人物关系图/人物关系图.md 里，"
    "用能预览 Markdown 的编辑器打开就能看到中文。"
)


class ChartError(ValueError):
    def __init__(self, code: str, author_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.author_message = author_message


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".%s." % path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, str(path))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def pick(row: Dict[str, str], *names: str) -> str:
    for name in names:
        for key, value in row.items():
            if name in key and value and value not in {"-", "—", "无"}:
                return value
    return ""


SOURCE_KEYS = ("主体", "角色A", "人物A", "A", "甲")
TARGET_KEYS = ("客体", "角色B", "人物B", "B", "乙")


def exact(row: Dict[str, str], keys: Tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key, "")
        if value and value not in {"-", "—"}:
            return value
    return ""


def parse_relations(text: str) -> List[Dict[str, str]]:
    """Rows of a relationship table.

    Current files use one 「主体 → 客体」 column; older ones use separate
    主体/客体 or A/B columns. Any table with such a pair of columns counts.
    """
    relations = []  # type: List[Dict[str, str]]
    header = None  # type: Optional[List[str]]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None
            continue
        row_cells = cells(stripped)
        if header is None:
            names = set(row_cells)
            if (any("主体" in cell and "客体" in cell for cell in row_cells) or "关系方向" in names
                    or (names & set(SOURCE_KEYS) and names & set(TARGET_KEYS))):
                header = row_cells
            continue
        if not "".join(row_cells).strip("-: "):
            continue
        row = dict(zip(header, row_cells))
        pair = next((value for key, value in row.items() if ("主体" in key and "客体" in key) or key == "关系方向"), "")
        parts = [part.strip() for part in ARROW_RE.split(pair) if part.strip()] if pair else []
        if not parts:
            parts = [value for value in (exact(row, SOURCE_KEYS), exact(row, TARGET_KEYS)) if value]
        if len(parts) != 2:
            continue
        relations.append({
            "id": pick(row, "关系ID", "ID"),
            "source": parts[0], "target": parts[1],
            "label": pick(row, "关系动作", "类型", "表面关系"),
            "state": pick(row, "变化后状态", "真实关系", "表面关系"),
            "trigger": pick(row, "触发事件", "触发"),
        })
    return relations


def mermaid_text(value: str) -> str:
    value = re.sub(r"[`*]", "", value)
    return value.replace('"', "'").replace("|", "/").replace("\n", " ").strip()


def latest_by_pair(relations: List[Dict[str, str]]) -> List[Dict[str, str]]:
    latest = {}  # type: Dict[Tuple[str, str], Dict[str, str]]
    for relation in relations:
        latest[(relation["source"], relation["target"])] = relation
    return list(latest.values())


def evolutions(relations: List[Dict[str, str]]) -> List[Tuple[Tuple[str, str], List[Dict[str, str]]]]:
    history = {}  # type: Dict[Tuple[str, str], List[Dict[str, str]]]
    for relation in relations:
        history.setdefault((relation["source"], relation["target"]), []).append(relation)
    return [(pair, rows) for pair, rows in history.items() if len(rows) > 1]


def render_markdown(book: str, relations: List[Dict[str, str]], png_note: str) -> str:
    names = []  # type: List[str]
    for relation in relations:
        for name in (relation["source"], relation["target"]):
            if name not in names:
                names.append(name)
    node = {name: "p%s" % index for index, name in enumerate(names, start=1)}
    lines = ["# 人物关系图：%s" % book, "",
             "> 由 角色/角色关系.md 生成；关系事实以该文件为准。%s" % png_note, "",
             "## 核心人物关系", "", "```mermaid", "graph LR"]
    lines.extend('    %s["%s"]' % (node[name], mermaid_text(name)) for name in names)
    for relation in latest_by_pair(relations):
        label = relation["state"] or relation["label"] or "关系"
        lines.append('    %s -->|"%s"| %s' % (node[relation["source"]], mermaid_text(label), node[relation["target"]]))
    lines.extend(["```", ""])
    for relation in latest_by_pair(relations):
        label = relation["state"] or relation["label"] or "关系"
        lines.append("- %s → %s：%s" % (relation["source"], relation["target"], label))
    lines.extend(["", "## 关键关系演变", ""])
    changes = evolutions(relations)
    if not changes:
        lines.append("本书没有记录到同一对人物前后变化的关系。")
    for (source, target), rows in changes:
        steps = []
        for row in rows:
            state = row["state"] or row["label"] or "关系"
            steps.append("%s（%s）" % (state, row["trigger"]) if row["trigger"] else state)
        lines.append("- %s → %s：%s" % (source, target, " → ".join(steps)))
    return "\n".join(lines) + "\n"


def glyph_ok(path: str, text: str) -> bool:
    """True when the face matplotlib will use (face 0) has every character of text."""
    try:
        from matplotlib.ft2font import FT2Font
        font = FT2Font(path)
        return all(font.get_char_index(ord(char)) for char in set(text) if not char.isspace())
    except Exception:  # noqa: BLE001 - any font loading failure means "not usable"
        return False


def find_cjk_font(text: str) -> Optional[str]:
    """Path of an installed font that draws every character of text, or None."""
    text = text + "中文人物关系→"
    override = os.environ.get("STORY_ANALYZE_CHART_FONT")
    if override == "none":
        return None
    if override:
        return override if glyph_ok(override, text) else None
    try:
        from matplotlib import font_manager
    except ImportError:
        return None
    by_name = {}  # type: Dict[str, List[str]]
    for entry in font_manager.fontManager.ttflist:
        paths = by_name.setdefault(entry.name, [])
        if entry.fname not in paths:
            paths.append(entry.fname)
    candidates = [path for name in CJK_FONT_NAMES for path in by_name.get(name, [])]
    if shutil.which("fc-list"):
        try:
            listed = subprocess.run(["fc-list", ":lang=zh", "file"], capture_output=True, text=True,
                                    timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            listed = ""
        candidates.extend(line.split(":", 1)[0].strip() for line in listed.splitlines())
    seen = set()
    for path in candidates:
        if path and path not in seen:
            seen.add(path)
            if glyph_ok(path, text):
                return path
    return None


def short_label(value: str, limit: int = 10) -> str:
    value = re.sub(r"[`*]|\[[^\]]*\]", "", value).strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


def draw_png(relations: List[Dict[str, str]], font_path: str, root: Path) -> List[str]:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    import matplotlib.pyplot as plt

    font = font_manager.FontProperties(fname=font_path)
    (root / CHART_DIR).mkdir(parents=True, exist_ok=True)
    written = []
    core = latest_by_pair(relations)
    degree = {}  # type: Dict[str, int]
    for relation in core:
        for name in (relation["source"], relation["target"]):
            degree[name] = degree.get(name, 0) + 1
    # The most connected character (usually the protagonist) sits in the middle.
    names = sorted(degree, key=lambda name: -degree[name])
    ring = names[1:] if len(names) > 2 else names
    positions = {name: (math.cos(2 * math.pi * index / len(ring)), math.sin(2 * math.pi * index / len(ring)))
                 for index, name in enumerate(ring)}
    if len(names) > 2:
        positions[names[0]] = (0.0, 0.0)
    size = min(14, 8 + 0.3 * len(names))
    figure, axis = plt.subplots(figsize=(size, size))
    axis.set_axis_off()
    bend = 0.18  # curve both directions of a pair apart so their labels do not overlap
    for relation in core:
        (x1, y1), (x2, y2) = positions[relation["source"]], positions[relation["target"]]
        axis.annotate("", xy=(x2, y2), xytext=(x1, y1),
                      arrowprops={"arrowstyle": "->", "color": "#666666", "shrinkA": 22, "shrinkB": 22,
                                  "connectionstyle": "arc3,rad=%s" % bend})
        label_x = (x1 + x2) / 2 + bend * (y2 - y1) / 2
        label_y = (y1 + y2) / 2 - bend * (x2 - x1) / 2
        axis.text(label_x, label_y, short_label(relation["state"] or relation["label"] or "关系"),
                  fontproperties=font, fontsize=9, ha="center", va="center", color="#333333",
                  bbox={"boxstyle": "round", "fc": "white", "ec": "none", "alpha": 0.8})
    for name, (x, y) in positions.items():
        axis.text(x, y, name, fontproperties=font, fontsize=13, ha="center", va="center",
                  bbox={"boxstyle": "round,pad=0.5", "fc": "#e8eef7", "ec": "#4a6fa5"})
    axis.set_aspect("equal")
    axis.set_xlim(-1.4, 1.4)
    axis.set_ylim(-1.4, 1.4)
    figure.savefig(str(root / CORE_PNG), dpi=150, bbox_inches="tight")
    plt.close(figure)
    written.append(CORE_PNG.as_posix())

    changes = evolutions(relations)
    if changes:
        figure, axis = plt.subplots(figsize=(10, 1.2 + 0.8 * len(changes)))
        axis.set_axis_off()
        for row_index, ((source, target), rows) in enumerate(changes):
            y = len(changes) - row_index
            axis.text(0, y, "%s → %s" % (source, target), fontproperties=font, fontsize=11, ha="left", va="center")
            for step, row in enumerate(rows):
                x = 3 + step * 2.2
                if step:
                    axis.annotate("", xy=(x - 0.6, y), xytext=(x - 1.6, y),
                                  arrowprops={"arrowstyle": "->", "color": "#a58a4a"})
                axis.text(x, y, row["state"] or row["label"] or "关系", fontproperties=font,
                          fontsize=10, ha="center", va="center",
                          bbox={"boxstyle": "round", "fc": "#f3efe6", "ec": "#a58a4a"})
                if row["trigger"]:
                    axis.text(x, y - 0.32, row["trigger"], fontproperties=font, fontsize=8,
                              ha="center", va="center", color="#666666")
        axis.set_xlim(-0.2, 3 + 2.2 * max(len(rows) for _, rows in changes))
        axis.set_ylim(0.3, len(changes) + 0.7)
        figure.savefig(str(root / EVOLUTION_PNG), dpi=150, bbox_inches="tight")
        plt.close(figure)
        written.append(EVOLUTION_PNG.as_posix())
    return written


def render(root: Path, want_png: bool) -> Dict[str, object]:
    source = root / RELATION_FILE
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError:
        raise ChartError("relation_file_missing", "还没有 角色/角色关系.md，先整理人物关系，再生成关系图。")
    relations = parse_relations(text)
    if not relations:
        raise ChartError("relation_table_empty", "角色/角色关系.md 里没有认得出的关系表（需要「主体 → 客体」一列），关系图没有生成。")
    png_written = []  # type: List[str]
    author_message = ""
    png_note = ""
    if want_png:
        font_path = find_cjk_font("".join("".join(relation.values()) for relation in relations))
        try:
            import matplotlib  # noqa: F401
            has_matplotlib = True
        except ImportError:
            has_matplotlib = False
        if not has_matplotlib:
            author_message = NO_MATPLOTLIB_MESSAGE
        elif not font_path:
            author_message = NO_FONT_MESSAGE
        else:
            png_written = draw_png(relations, font_path, root)
            png_note = "图片版见同目录的 PNG。"
    markdown = render_markdown(root.name, relations, png_note)
    atomic_write(root / CHART_MD, markdown.encode("utf-8"))
    return {
        "ok": True, "markdown": CHART_MD.as_posix(), "png": png_written,
        "relations": len(relations), "author_message": author_message or None,
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="拆文库/{书名} 目录")
    parser.add_argument("--png", action="store_true", help="also draw PNG pictures when a Chinese font exists")
    args = parser.parse_args()
    try:
        if not args.root.is_dir():
            raise ChartError("root_not_found", "没找到这本书的拆文目录，确认书名或路径。")
        payload = render(args.root.resolve(), args.png)
    except ChartError as exc:
        payload = {"ok": False, "error": exc.code, "author_message": exc.author_message}
    except (OSError, UnicodeError) as exc:
        payload = {"ok": False, "error": "io_error", "detail": str(exc),
                   "author_message": "关系图文件写入失败，检查拆文目录是否可写。"}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
