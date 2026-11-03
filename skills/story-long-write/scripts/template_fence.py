#!/usr/bin/env python3
"""template_fence.py — 按围栏标签取参考文件里的模板。

参考文件里给作者落盘用的模板写在带标签的代码围栏里：

    ```markdown template=细纲
    ...
    ```

脚本按标签取整块，不按小节标题或「从 A 切到 B」的区间取：模板挪了位置、前后加了说明，
取到的仍是同一块；标签不在或出现了不止一次直接报错，不静默给空。
标签名的唯一清单在仓库 `scripts/current-contract.json` 的 `template_fences`，由仓库守卫核对每个标签
在全部参考文件里恰好出现一次；运行时脚本只按名取，不另存清单。
"""

from __future__ import annotations

import re

# 开围栏：三个以上反引号或波浪号，信息串里带 template=名字（名字到空白为止）。
OPEN_RE = re.compile(r"^[ ]{0,3}(?P<marker>`{3,}|~{3,})(?P<info>[^\n]*)$")
TAG_RE = re.compile(r"(?:^|\s)template=(?P<tag>\S+)")


class TemplateNotFound(LookupError):
    """标签没找到，或同一份文本里出现了不止一次。"""


def template_blocks(text: str) -> list[tuple[str, int, str]]:
    """文本里所有带标签的围栏：[(标签, 开围栏所在行号（从 1 起）, 围栏内文本)]。

    围栏内的围栏标记不算新围栏；没闭合的围栏一直取到文末。"""
    found: list[tuple[str, int, str]] = []
    lines = text.lstrip("﻿").split("\n")
    index = 0
    while index < len(lines):
        opened = OPEN_RE.match(lines[index])
        if not opened or (opened.group("marker")[0] == "`" and "`" in opened.group("info")):
            index += 1
            continue
        marker = opened.group("marker")
        tag = TAG_RE.search(opened.group("info"))
        close = re.compile(r"^[ ]{0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
        end = next((row for row in range(index + 1, len(lines)) if close.match(lines[row])), len(lines))
        if tag:
            found.append((tag.group("tag"), index + 1, "\n".join(lines[index + 1:end])))
        index = end + 1
    return found


def template_block(text: str, tag: str, *, source: str = "参考文件") -> str:
    """取标签为 tag 的那一块模板（不含围栏行）。找不到或不止一块就抛 TemplateNotFound。"""
    hits = [body for name, _, body in template_blocks(text) if name == tag]
    if not hits:
        raise TemplateNotFound(f"{source} 里找不到模板「{tag}」（围栏信息串应写 template={tag}）")
    if len(hits) > 1:
        raise TemplateNotFound(f"{source} 里模板「{tag}」出现了 {len(hits)} 次，只能有一处")
    return hits[0]
