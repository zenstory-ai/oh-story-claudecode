from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceSpec:
    site_id: str
    site_name: str
    source_id: str
    semantic_key: str
    category: str
    category_name: str
    url: str
    required_adapters: list[str] = field(default_factory=list)
    known_risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParseResult:
    ok: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    category_name: str = ""
    failure_code: str = ""
    failure_detail: str = ""
    parser_version: str = ""
    source_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RankItem:
    rank_position: int
    book_id: str
    book_name: str
    author_name: str = ""
    book_url: str = ""
    cover_url: str = ""
    description: str = ""
    category_text: str = ""
    score_text: str = ""
    word_count_text: str = ""
    status: str = ""
    tags: list[str] = field(default_factory=list)
    latest_chapter: str = ""
    latest_update_time: str = ""
    rank_delta: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    field_confidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RankSnapshot:
    site: str
    site_name: str
    category: str
    category_name: str
    semantic_key: str
    source_url: str
    snapshot_at: str
    items: list[RankItem]
    raw_ref: str
    parse_status: str
    source_notes: list[str] = field(default_factory=list)
    parser_version: str = ""
    adapter_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload


class RankFetchError(RuntimeError):
    """A rank request or parse failed. Callers must not invent rows."""
