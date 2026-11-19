#!/usr/bin/env python3
"""Merge one host's oh-story block into a project instruction file.

CLAUDE.md and the shared root AGENTS.md carry one managed block per host:

    <!-- oh-story:codex 开始：重新部署时整块替换，自己的内容写在块外 -->
    ...rendered template...
    <!-- oh-story:codex 结束 -->

Redeploying replaces only this host's block; text outside every block and
other hosts' blocks stay byte-identical.  Files written before blocks existed
are migrated once: the oh-story title line, its intro and the sections whose
headings the current template owns are removed and the block takes their place.
A file counts as an old deployment only when an oh-story title line sits
outside every block; once another host's block exists, only the headings unique
to this host are still treated as leftovers.  Anything else is the author's own
file and the block is appended.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


HOSTS = ("claude-code", "opencode", "codex", "zcode", "openclaw", "reasonix", "generic", "dsh")
# 旧模板里有、现模板已删的受管节；迁移旧文件时一并清掉。
RETIRED_HEADINGS = frozenset({"协作规则"})
# 名字太常见的节，旧文件里只有带 oh-story 痕迹才算受管，避免误删作者自己的同名节。
GENERIC_HEADINGS = frozenset({"Skill 路由表", "文件结构", "写作约束"})
LEGACY_SIGNALS = ("story-", "拆文库", "追踪/", "细纲", "作者记忆", "oh-story")
# 各宿主模板共有的节；文件里已有别的宿主的块、块外又没有旧标题时，这些节归作者。
SHARED_HEADINGS = frozenset({"Skill 路由表", "文件结构", "写作约束", "与作者协作", "Compact 后恢复上下文"})
TITLE_SIGNAL = "网文写作工具集"
LEGACY_MARKER = "<!-- managed-by: story-setup -->"
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


class MergeError(ValueError):
    pass


def begin_marker(host: str) -> str:
    return f"<!-- oh-story:{host} 开始：重新部署时整块替换，自己的内容写在块外 -->"


def end_marker(host: str) -> str:
    return f"<!-- oh-story:{host} 结束 -->"


def block_re(host: str) -> re.Pattern[str]:
    return re.compile(
        r"^<!-- oh-story:" + re.escape(host) + r" 开始[^\n]*-->\n.*?^<!-- oh-story:"
        + re.escape(host) + r" 结束 -->[ \t]*$",
        re.S | re.M,
    )


ANY_BEGIN_RE = re.compile(r"^<!-- oh-story:([a-z-]+) 开始[^\n]*-->$", re.M)


def render_block(template: str, host: str, project_name: str) -> str:
    body = template.replace("\r\n", "\n").replace("{项目名}", project_name).strip("\n")
    if "<!-- oh-story:" in body:
        raise MergeError("template must not carry its own oh-story markers")
    return f"{begin_marker(host)}\n{body}\n{end_marker(host)}"


def managed_headings(template: str) -> set[str]:
    headings = {m.group(1) for m in map(HEADING_RE.match, template.splitlines()) if m}
    return headings | set(RETIRED_HEADINGS)


def protected_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of every existing oh-story block (any host)."""
    spans = []
    for match in ANY_BEGIN_RE.finditer(text):
        host = match.group(1)
        end = re.compile(r"^<!-- oh-story:" + re.escape(host) + r" 结束 -->[ \t]*$", re.M).search(text, match.end())
        if end is None:
            raise MergeError(f"unterminated oh-story:{host} block")
        spans.append((match.start(), end.end()))
    return spans


def title_re(template: str) -> re.Pattern[str] | None:
    """The template's own H1, with the project name as a wildcard."""
    first = next((line for line in template.splitlines() if line.startswith("# ")), "")
    if TITLE_SIGNAL not in first:
        return None
    parts = [re.escape(part) for part in first.strip().split("{项目名}")]
    return re.compile("^" + ".*".join(parts) + r"\s*$")


def strip_legacy(text: str, template: str) -> tuple[str, int | None, list[str]]:
    """Remove unmarked oh-story content owned by this template.

    Returns the new text, the offset where the block should go (None when
    nothing legacy was found) and the removed section titles.
    """
    headings = managed_headings(template)
    own_title = title_re(template)
    spans = protected_spans(text)
    lines = text.split("\n")
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    def inside_block(index: int) -> bool:
        return any(start <= offsets[index] < end for start, end in spans)

    # 旧部署的凭据：块外有 oh-story 标题行（任一宿主）或旧版托管标记。
    outside = [line for i, line in enumerate(lines) if not inside_block(i)]
    legacy_deploy = any(
        (line.startswith("# ") and TITLE_SIGNAL in line) or line.strip() == LEGACY_MARKER for line in outside
    )
    if not legacy_deploy:
        if not spans:
            return text, None, []
        # 已有别的宿主的块：共有节在先迁移的宿主那里清过了，剩下的只可能是本宿主独有的节。
        headings = headings - SHARED_HEADINGS - RETIRED_HEADINGS

    # 把块外的行切成「本宿主标题行 + 引言」与「## 节」两类片段。
    pieces: list[tuple[str, int, int]] = []  # (title, start_line, end_line_exclusive)
    index = 0
    while index < len(lines):
        if inside_block(index):
            index += 1
            continue
        line = lines[index]
        if own_title is not None and own_title.match(line):
            end = index + 1
            while end < len(lines) and not lines[end].startswith("#") and not inside_block(end):
                end += 1
            pieces.append(("#title", index, end))
            index = end
            continue
        heading = HEADING_RE.match(line)
        if heading:
            end = index + 1
            while end < len(lines) and not lines[end].startswith("# ") and not HEADING_RE.match(lines[end]) and not inside_block(end):
                end += 1
            pieces.append((heading.group(1), index, end))
            index = end
            continue
        index += 1

    removed_ranges: list[tuple[int, int]] = []
    removed_titles: list[str] = []
    for title, start, end in pieces:
        body = "\n".join(lines[start:end])
        if title == "#title":
            removed_ranges.append((start, end))
            removed_titles.append(lines[start].lstrip("# ").strip())
        elif title in headings and (
            title not in GENERIC_HEADINGS or any(signal in body for signal in LEGACY_SIGNALS)
        ):
            removed_ranges.append((start, end))
            removed_titles.append(title)
    if not removed_ranges:
        return text, None, []
    drop = set()
    for start, end in removed_ranges:
        drop.update(range(start, end))
    first = min(start for start, _ in removed_ranges)
    kept_before = [line for i, line in enumerate(lines[:first]) if i not in drop]
    kept_after = [line for i, line in enumerate(lines) if i >= first and i not in drop]
    head = "\n".join(kept_before)
    insert_at = len(head) + (1 if kept_before else 0)
    new_text = head + ("\n" if kept_before else "") + "\n".join(kept_after)
    return new_text, insert_at, removed_titles


def tidy(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def merge(existing: str, template: str, host: str, project_name: str) -> tuple[str, dict]:
    block = render_block(template, host, project_name)
    crlf = existing.count("\r\n") > existing.count("\n") / 2 if existing else False
    text = existing.replace("\r\n", "\n")
    report: dict = {"host": host, "removed_legacy_sections": []}
    if not text.strip():
        report["status"] = "created"
        merged = block + "\n"
    else:
        protected_spans(text)  # 先校验已有块都闭合
        pattern = block_re(host)
        matches = list(pattern.finditer(text))
        if len(matches) > 1:
            raise MergeError(f"more than one oh-story:{host} block")
        if matches:
            report["status"] = "replaced"
            merged = tidy(text[: matches[0].start()] + block + text[matches[0].end():])
        else:
            stripped, insert_at, removed = strip_legacy(text, template)
            if insert_at is None:
                report["status"] = "appended"
                merged = tidy(text.rstrip("\n") + "\n\n" + block)
            else:
                report["status"] = "migrated"
                report["removed_legacy_sections"] = removed
                before, after = stripped[:insert_at], stripped[insert_at:]
                merged = tidy(
                    (before.rstrip("\n") + "\n\n" if before.strip() else "")
                    + block
                    + ("\n\n" + after.lstrip("\n") if after.strip() else "")
                )
    if crlf:
        merged = merged.replace("\n", "\r\n")
    return merged, report


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True, choices=HOSTS)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--existing", required=True, type=Path, help="project CLAUDE.md / AGENTS.md (may be absent)")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project-name", required=True)
    args = parser.parse_args(argv)
    try:
        template = args.template.read_text(encoding="utf-8")
        existing = args.existing.read_text(encoding="utf-8") if args.existing.is_file() else ""
        merged, report = merge(existing, template, args.host, args.project_name)
        unchanged = merged == existing and args.output.resolve() == args.existing.resolve()
        if not unchanged:
            atomic_write(args.output, merged)
    except (OSError, UnicodeDecodeError, MergeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 1
    # 只输出 ASCII（中文转义），避免 Windows 控制台编码把报告打成乱码。
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
