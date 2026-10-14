"""章节正文解码与 HTML 归一化。"""

from html.parser import HTMLParser
import gzip
import re
import zlib


class _TextExtractor(HTMLParser):
    """把章节 HTML 片段转换为适合 TXT 导出的段落文本。"""

    _BLOCK_TAGS = {"p", "div", "section", "article", "li", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str):
        self.parts.append(data)


def normalize_chapter_text(value: str) -> str:
    """清理章节 HTML/换行，返回纯文本。"""
    text = str(value or "")
    if "<" in text and ">" in text:
        parser = _TextExtractor()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def decode_cdn_payload(payload: bytes) -> str:
    """解码新版 App 的正文 CDN 数据。

    抓包确认的传输链为 HTTP gzip（requests 通常自动解压）后再包一层
    zlib，最终内容是 UTF-8 HTML 片段。函数同时兼容仍保留 gzip 外层
    或直接返回 UTF-8 的节点。
    """
    data = bytes(payload)
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    try:
        data = zlib.decompress(data)
    except zlib.error:
        pass
    return normalize_chapter_text(data.decode("utf-8", errors="replace"))
