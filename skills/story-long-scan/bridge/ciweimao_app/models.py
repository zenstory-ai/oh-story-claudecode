"""数据模型：Book, Division, Chapter。"""

from dataclasses import dataclass, field
import re


def safe_book_name(name: str) -> str:
    """返回可用于 Windows 文件名的书名。"""
    cleaned = re.sub(r'[\\/:*?"<>|]', '', str(name)).strip().rstrip(".")
    return cleaned or "未命名"


@dataclass
class Chapter:
    """单章信息。"""
    chapter_id: str = ""
    chapter_index: int = 0
    chapter_title: str = ""
    word_count: int = 0
    is_vip: bool = False
    auth_access: bool = False
    content: str = ""          # 解密后的正文


@dataclass
class Division:
    """分卷。"""
    division_id: str = ""
    division_name: str = ""
    chapters: list = field(default_factory=list)


@dataclass
class Book:
    """书籍信息。"""
    book_id: str = ""
    book_name: str = ""
    author_name: str = ""
    cover_url: str = ""
    total_word_count: int = 0
    category_name: str = ""
    description: str = ""
    divisions: list = field(default_factory=list)

    @property
    def safe_name(self) -> str:
        """返回安全的文件名。"""
        return safe_book_name(self.book_name)

    @property
    def safe_stem(self) -> str:
        """返回适合全站抓取、避免同名冲突的文件名主体。"""
        return f"{self.book_id} - {self.safe_name}" if self.book_id else self.safe_name
