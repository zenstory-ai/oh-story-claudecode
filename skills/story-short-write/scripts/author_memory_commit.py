#!/usr/bin/env python3
"""Maintain evidence-backed author preferences and deterministic Markdown views.

The language model supplies compact semantic transactions. This tool validates
and applies them in memory, renders every derived view, and writes the JSON state
last as the commit point. Author memory lives in two kinds of store: the
project-level store under the workspace holds global / genre / workflow items
(`AP` ids); each book keeps its own book-level store under the book directory
(`BP` ids) so memory travels with the book. Both stay separate from each book's
story-continuity tracking. When the book root is the workspace itself, the
book-level store moves into a `书级/` subdirectory so the two never share a file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUT_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
STATE_MAX_BYTES = 2 * 1024 * 1024
PROFILE_MAX_BYTES = 12288
PENDING_MAX_BYTES = 12288
JOURNAL_MAX_BYTES = 24576
QUERY_MAX_BYTES = 2048
ASSERTION_MAX_BYTES = 120  # 新建条目的断言限一句话；解释进 reason（不进 query 载荷）。
OMITTED_IDS_MAX = 20  # omitted_ids 封顶，omitted 保留真实总数——漏项列表不许把载荷本身挤炸。
LEGACY_ASSERTION_MAX_BYTES = 768  # 存量条目的读取上限；强化老条目不受新上限约束。

# query 的输出是要原样贴进执行 agent prompt 的注入载荷，QUERY_MAX_BYTES
# 是它在 prompt 里的注意力预算，不该放大。防「作者以为载入了、实际被静默
# 截断挤掉」靠三层：①新建条目的断言限 ASSERTION_MAX_BYTES，从源头短（强化
# 已有条目不受限，否则存量长断言再也无法被确认，只会派生重复条目）；②写入
# 端按下列任务组合（与 references/author-memory.md 的映射表同包跟版）估算
# 最坏查询情形——全局条目＋各 scope 维度上最重的单一切片（一次查询只带一
# 个 book/genre/workflow，不同书的条目不会同现；切片按 casefold 归并，与
# same_scope_value 同一口径，轻重按 compact 字节＋列表分隔符算，与真实载荷
# 同一把尺），装不下时在返回的 warnings 里点名将被略过的条目、指向「整理作
# 者记忆」，写入本身永不因注入预算失败；③查询按 重要度→本书例外→最近更新
# 排序装填，被略过的恒是重要度较低的条目，漏下的 ID 按同一优先级顺序报进
# omitted_ids。
QUERY_COMBOS: dict[str, tuple[str, ...]] = {
    "正文初稿/续写": ("prose_style", "story_design"),
    "去AI味/改写": ("prose_style",),
    "设定/大纲": ("story_design", "workflow", "interaction"),
    "审稿": ("delivery", "interaction", "prose_style"),
}

KINDS = ("prose_style", "story_design", "workflow", "delivery", "interaction")
KIND_TITLES = {
    "prose_style": "文风与表达",
    "story_design": "故事设计",
    "workflow": "创作流程",
    "delivery": "交付格式",
    "interaction": "协作方式",
}
SCOPE_LEVELS = ("global", "genre", "book", "workflow")
STATUSES = ("active", "pending", "conflict", "rejected", "superseded")
CONFIDENCE_LEVELS = ("low", "medium", "high")
IMPORTANCE_LEVELS = ("low", "medium", "high")
# 作者记忆只记作者明确表达的偏好。repeated_correction / inferred_pattern 两条
# 由 agent 主动推断写入的管道已经移除（#436）：它们只在攒待确认清单的审阅负
# 担，不是记忆质量；文档也明说不装全量消息 hook，隐式捕获本就承诺不了完整
# 性。SOURCES 里保留这两个值只为存量 state 仍能通过校验、仍能 decide/forget，
# 新写入一律按 WRITE_SOURCES 校验。
SOURCES = (
    "explicit_user",
    "accepted_suggestion",
    "repeated_correction",
    "inferred_pattern",
    "manual",
)
WRITE_SOURCES = ("explicit_user", "accepted_suggestion", "manual")
RANK = {"low": 0, "medium": 1, "high": 2}

# 两级 store（#435）：项目级存 global/genre/workflow，ID 前缀 AP，位于
# {工作区}/.story/作者记忆/；书级只存该书的 book 条目，ID 前缀 BP，位于
# {书}/.story/作者记忆/，书归档、迁移时记忆随书走。ID 前缀就是路由键——
# decide/forget 看 item_id 前缀，remember/replace 看 scope.level，一份事务
# 只写一个 store。项目级 store 里升级前写入的存量 book 条目不再参与查询与估算，
# 用 migrate 搬进书目录后才回来——不做双读，双读会让迁移永远没人做。
STORE_PREFIX = {"project": "AP", "book": "BP"}
ID_PREFIXES = tuple(STORE_PREFIX.values())
# 单书布局（书根就是工作区）下书级 store 的子目录：两级 store 的默认落点在这种
# 布局里是同一个 state 文件，书级改住 {工作区}/.story/作者记忆/书级/。
SINGLE_ROOT_BOOK_DIR = "书级"


class AuthorMemoryError(ValueError):
    """Expected validation or state error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorMemoryError(message)


def as_mapping(value: object, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def as_list(value: object, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be a JSON array")
    return value


def as_int(value: object, label: str, *, minimum: int = 0) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def require_known_keys(mapping: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(mapping) - allowed
    require(not unknown, f"{label} contains unsupported fields: {', '.join(sorted(unknown))}")


def clean_text(value: object, label: str, *, max_bytes: int = 768) -> str:
    require(isinstance(value, str), f"{label} must be a string")
    cleaned = " ".join(value.replace("|", "｜").split())
    require(bool(cleaned), f"{label} must not be empty")
    require(len(cleaned.encode("utf-8")) <= max_bytes, f"{label} exceeds {max_bytes} bytes")
    return cleaned


def optional_text(value: object, label: str, *, max_bytes: int = 768) -> str | None:
    if value is None:
        return None
    return clean_text(value, label, max_bytes=max_bytes)


def choice(value: object, allowed: tuple[str, ...], label: str) -> str:
    require(isinstance(value, str) and value in allowed, f"{label} must be one of: {', '.join(allowed)}")
    return value


def is_item_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) >= 3
        and value[:2] in ID_PREFIXES
        and value[2:].isdigit()
        and int(value[2:]) >= 1
    )


def id_number(item_id: str) -> int:
    return int(item_id[2:])


def id_store(item_id: str) -> str:
    return "book" if item_id.startswith(STORE_PREFIX["book"]) else "project"


def clean_id_list(value: object, label: str, *, maximum: int = 32) -> list[str]:
    raw = as_list(value, label)
    require(len(raw) <= maximum, f"{label} may contain at most {maximum} items")
    result: list[str] = []
    for index, item in enumerate(raw):
        item_id = clean_text(item, f"{label}[{index}]", max_bytes=32)
        require(is_item_id(item_id), f"{label}[{index}] is not an author-memory id")
        if item_id not in result:
            result.append(item_id)
    return result


def emit(document: object, *, error: bool = False) -> None:
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True)
    stream = sys.stderr if error else sys.stdout
    stream.flush()
    stream.buffer.write((payload + "\n").encode("utf-8"))
    stream.buffer.flush()


def json_payload(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def read_json(path: Path) -> object:
    try:
        require(path.stat().st_size <= STATE_MAX_BYTES, f"{path} exceeds {STATE_MAX_BYTES} bytes")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorMemoryError(f"unable to read JSON {path}: {exc}") from exc


def atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_if_changed(path: Path, payload: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == payload:
            return
    except FileNotFoundError:
        pass
    atomic_write_text(path, payload)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


class Store:
    """一个 state 文件的落点：项目级（工作区）或书级（书目录）。"""

    __slots__ = ("kind", "root", "book")

    def __init__(self, kind: str, root: Path, book: str | None) -> None:
        self.kind = kind
        self.root = root
        self.book = book

    @property
    def prefix(self) -> str:
        return STORE_PREFIX[self.kind]

    @property
    def state_path(self) -> Path:
        return self.root / "_author-memory-state.json"

    @property
    def label(self) -> str:
        return "项目级" if self.kind == "project" else f"书级（{self.book}）"


def project_store(workspace: Path) -> Store:
    return Store("project", workspace.resolve() / ".story" / "作者记忆", None)


def peek_book_name(state_path: Path) -> str | None:
    """不校验整份 state，只取书名——书级 store 一旦建立，书名以 state 为准，
    书目录改名不影响。"""
    if not state_path.exists():
        return None
    document = read_json(state_path)
    name = document.get("book") if isinstance(document, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def enclosing_workspace(workspace: Path) -> Path | None:
    """--workspace 指到的其实是多书工作区里的一本书时，返回真正的创作工作区。

    认三种迹象，任一成立即是：①工作区的上一层目录叫 长篇 / 短篇（story-setup 的书
    目录约定，返回再上一层）；②某个祖先目录有 .active-book；③某个祖先目录有项目级
    store（不带 book 字段的 state）——但工作区自己已有项目级 store 时不认这一条，最
    近的项目级 store 就是它自己，免得主目录里一份误建的 store 挡住正常的单书工作区。
    读不出来的祖先 state 不算迹象。"""
    resolved = workspace.resolve()
    if resolved.parent.name in {"长篇", "短篇"}:
        return resolved.parent.parent
    own = project_store(resolved).state_path
    owns_project_store = own.exists() and peek_book_name(own) is None
    for ancestor in resolved.parents:
        if (ancestor / ".active-book").exists():
            return ancestor
        if owns_project_store:
            continue
        state_path = project_store(ancestor).state_path
        try:
            document = read_json(state_path) if state_path.is_file() else None
        except AuthorMemoryError:
            document = None
        if isinstance(document, dict) and "book" not in document:
            return ancestor
    return None


def same_directory(first: Path, second: Path) -> bool:
    # samefile 认得大小写不敏感文件系统（macOS APFS 默认）上只差大小写的同一目录。
    if first.exists() and second.exists():
        return os.path.samefile(first, second)
    return first.resolve() == second.resolve()


def is_single_root(workspace: Path, book_root: Path | None) -> bool:
    """单书布局：书根就是工作区（正文/、大纲/、追踪/ 直接在工作区根）。

    同一目录还可能是多书工作区里的一本书被误传成了 --workspace（书目录自己也含
    .story/作者记忆/）。那时按单书布局处理会把书级 state 挪进 书级/、在原处补一份
    空的项目级 state，此后正确的调用全部失败，所以一律报错、零写入。"""
    if book_root is None or not same_directory(book_root, workspace):
        return False
    outer = enclosing_workspace(workspace)
    require(
        outer is None,
        f"{workspace} 是创作工作区 {outer} 里的一本书，不是单书工作区：--workspace 应传 {outer}，"
        f"这个目录放 --book-root",
    )
    return True


def book_memory_root(workspace: Path, book_root: Path) -> Path:
    root = book_root.resolve() / ".story" / "作者记忆"
    # 单书布局下两级 store 的默认落点是同一个 state 文件；书级改住子目录，
    # 两份 state、两套派生视图、两条修订线仍各自独立。
    return root / SINGLE_ROOT_BOOK_DIR if is_single_root(workspace, book_root) else root


def sole_legacy_book_name(project: Store) -> str | None:
    """项目级 store 里存量 book 条目只指向一本书时返回该书名（单书布局的升级默认）。"""
    if not project.state_path.exists():
        return None
    document = read_json(project.state_path)
    items = document.get("items") if isinstance(document, dict) else None
    names: dict[str, str] = {}
    for item in (items.values() if isinstance(items, dict) else ()):
        scope = item.get("scope") if isinstance(item, dict) else None
        if (
            isinstance(scope, dict) and scope.get("level") == "book"
            and isinstance(scope.get("value"), str) and scope["value"].strip()
            and item.get("status") in {"active", "pending", "conflict"}
        ):
            names.setdefault(scope["value"].casefold(), scope["value"])
    return next(iter(names.values())) if len(names) == 1 else None


def book_store(workspace: Path, book_root: Path, book: str | None) -> Store:
    require(book_root.exists() and book_root.is_dir(), f"book root does not exist: {book_root}")
    resolved = book_root.resolve()
    root = book_memory_root(workspace, book_root)
    name = optional_text(book, "book", max_bytes=180)
    stored = peek_book_name(root / "_author-memory-state.json")
    if name is None:
        name = stored
    elif stored is not None:
        require(
            name.casefold() == stored.casefold(),
            f"--book「{name}」与 {root} 里记录的书「{stored}」不一致",
        )
    if name is None and is_single_root(workspace, book_root):
        # 单书工作区的目录名常常不是书名；升级前的本书条目只指向一本书时，以它为准，
        # 否则 migrate 会按目录名找不到存量、静默迁移零条。
        name = sole_legacy_book_name(project_store(workspace))
    if name is None:
        name = clean_text(resolved.name, "book root name", max_bytes=180)
    return Store("book", root, name)


def relocate_misplaced_book_state(workspace: Path, book_root: Path | None) -> None:
    """单书布局的自愈：旧版把书级 state（带 state.book）写在了项目级位置，此后项目级
    读写一律失败。带 --book-root {工作区} 运行任一命令时，把它原子移进书级子目录，
    再在项目级位置补一份空 state 重建视图。state 内容不变，不推进任何修订。"""
    if not is_single_root(workspace, book_root):
        return
    project = project_store(workspace)
    misplaced = peek_book_name(project.state_path)
    if misplaced is None:
        return
    target = Store("book", book_memory_root(workspace, book_root), misplaced)
    require(
        not target.state_path.exists(),
        f"{project.state_path} 与 {target.state_path} 都是书级 state，无法自动归位；"
        f"保留修订较新的一份移到 {target.state_path}，另一份备份后移走再重跑",
    )
    state = validate_state(read_json(project.state_path), store=target)
    target.root.mkdir(parents=True, exist_ok=True)
    os.replace(project.state_path, target.state_path)
    write_snapshot(target, state)
    write_snapshot(project, empty_state())


def resolve_target_store(kind: str, workspace: Path, book_root: Path | None, book: str | None) -> Store:
    if kind == "project":
        return project_store(workspace)
    require(
        book_root is not None,
        "book 级条目须传 --book-root {书目录}——记忆随书存放在 {书}/.story/作者记忆/，不再写进工作区的项目级 store",
    )
    return book_store(workspace, book_root, book)


def empty_state(book: str | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_revision": 0,
        "next_item_number": 1,
        "items": {},
        "journal": [],
        "applied_transactions": {},
    }
    if book is not None:
        state["book"] = book
    return state


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def normalize_scope(value: object, label: str) -> dict[str, str | None]:
    scope = as_mapping(value, label)
    require_known_keys(scope, {"level", "value"}, label)
    level = choice(scope.get("level"), SCOPE_LEVELS, f"{label}.level")
    raw_value = scope.get("value")
    if level == "global":
        require(raw_value is None, f"{label}.value must be null for global scope")
        normalized_value = None
    else:
        normalized_value = clean_text(raw_value, f"{label}.value", max_bytes=180)
    return {"level": level, "value": normalized_value}


def normalize_evidence(value: object, label: str) -> dict[str, str | None]:
    evidence = as_mapping(value, label)
    require_known_keys(evidence, {"quote", "source_ref"}, label)
    return {
        "quote": clean_text(evidence.get("quote"), f"{label}.quote", max_bytes=768),
        "source_ref": optional_text(evidence.get("source_ref"), f"{label}.source_ref", max_bytes=240),
    }


def normalize_item(value: object, label: str) -> dict[str, Any]:
    item = as_mapping(value, label)
    allowed = {
        "id", "kind", "scope", "assertion", "confidence", "importance", "status", "source",
        "reason", "conflicts_with", "confirmation_count", "evidence", "created_revision",
        "updated_revision", "superseded_by",
    }
    require_known_keys(item, allowed, label)
    item_id = clean_text(item.get("id"), f"{label}.id", max_bytes=32)
    require(is_item_id(item_id), f"{label}.id is invalid")
    evidence = [normalize_evidence(entry, f"{label}.evidence[{index}]") for index, entry in enumerate(as_list(item.get("evidence"), f"{label}.evidence"))]
    require(bool(evidence), f"{label}.evidence must not be empty")
    status = choice(item.get("status"), STATUSES, f"{label}.status")
    conflicts = clean_id_list(item.get("conflicts_with"), f"{label}.conflicts_with")
    superseded_by = optional_text(item.get("superseded_by"), f"{label}.superseded_by", max_bytes=32)
    if superseded_by is not None:
        require(is_item_id(superseded_by), f"{label}.superseded_by is invalid")
    return {
        "id": item_id,
        "kind": choice(item.get("kind"), KINDS, f"{label}.kind"),
        "scope": normalize_scope(item.get("scope"), f"{label}.scope"),
        "assertion": clean_text(item.get("assertion"), f"{label}.assertion", max_bytes=LEGACY_ASSERTION_MAX_BYTES),
        "confidence": choice(item.get("confidence"), CONFIDENCE_LEVELS, f"{label}.confidence"),
        "importance": choice(item.get("importance"), IMPORTANCE_LEVELS, f"{label}.importance"),
        "status": status,
        "source": choice(item.get("source"), SOURCES, f"{label}.source"),
        "reason": clean_text(item.get("reason"), f"{label}.reason", max_bytes=480),
        "conflicts_with": conflicts,
        "confirmation_count": as_int(item.get("confirmation_count"), f"{label}.confirmation_count", minimum=1),
        "evidence": evidence,
        "created_revision": as_int(item.get("created_revision"), f"{label}.created_revision", minimum=1),
        "updated_revision": as_int(item.get("updated_revision"), f"{label}.updated_revision", minimum=1),
        "superseded_by": superseded_by,
    }


def scope_fits_store(scope: dict[str, str | None], book: str | None) -> bool:
    if book is None:
        return True  # 项目级：存量 book 条目仍合法，只为老库能通过校验并被 migrate 搬走
    return scope["level"] == "book" and (scope["value"] or "").casefold() == book.casefold()


def validate_state(value: object, *, store: Store) -> dict[str, Any]:
    state = as_mapping(value, "state")
    allowed = {"schema_version", "state_revision", "next_item_number", "items", "journal", "applied_transactions", "book"}
    require_known_keys(state, allowed, "state")
    require(state.get("schema_version") == STATE_SCHEMA_VERSION, f"state.schema_version must be {STATE_SCHEMA_VERSION}")
    if store.kind == "book":
        book = clean_text(state.get("book"), "state.book", max_bytes=180)
        require(store.book is not None and book.casefold() == store.book.casefold(), f"state.book「{book}」与目标书「{store.book}」不一致")
    else:
        require(
            "book" not in state,
            "project-level state must not carry state.book：这份其实是书级 state。--workspace 指到了"
            "长篇/、短篇/ 下的书目录时，改传创作工作区根、书目录放 --book-root；只有书根就是工作区"
            "（单书布局）时，带 --book-root {工作区} 重跑任一命令即自动移进 .story/作者记忆/书级/",
        )
        book = None
    revision = as_int(state.get("state_revision"), "state.state_revision")
    next_number = as_int(state.get("next_item_number"), "state.next_item_number", minimum=1)
    raw_items = as_mapping(state.get("items"), "state.items")
    items: dict[str, Any] = {}
    max_number = 0
    for raw_id, raw_item in raw_items.items():
        normalized = normalize_item(raw_item, f"state.items.{raw_id}")
        require(raw_id == normalized["id"], f"state.items key {raw_id} does not match item id")
        require(raw_id.startswith(store.prefix), f"state.items.{raw_id} does not belong to the {store.label} store（前缀应为 {store.prefix}）")
        require(scope_fits_store(normalized["scope"], book), f"state.items.{raw_id} scope does not belong to book「{book}」")
        max_number = max(max_number, id_number(raw_id))
        require(normalized["created_revision"] <= normalized["updated_revision"] <= revision, f"state.items.{raw_id} revision is ahead of state")
        items[raw_id] = normalized
    require(next_number > max_number, "state.next_item_number must be greater than every allocated item id")
    for item_id, item in items.items():
        for conflict_id in item["conflicts_with"]:
            require(conflict_id in items and conflict_id != item_id, f"state.items.{item_id} has an invalid conflict id")
        if item["superseded_by"] is not None:
            require(item["superseded_by"] in items and item["superseded_by"] != item_id, f"state.items.{item_id} has an invalid superseded_by id")
        if item["status"] == "active":
            require(not item["conflicts_with"], f"active item {item_id} cannot retain conflicts")
        if item["status"] == "pending":
            require(not item["conflicts_with"], f"pending item {item_id} cannot retain conflicts")
        if item["status"] == "conflict":
            require(bool(item["conflicts_with"]), f"conflict item {item_id} must reference an active item")
            require(all(items[conflict_id]["status"] == "active" for conflict_id in item["conflicts_with"]), f"conflict item {item_id} must reference only active items")
        if item["status"] != "superseded":
            require(item["superseded_by"] is None, f"only superseded item {item_id} may set superseded_by")
    journal = as_list(state.get("journal"), "state.journal")
    require(len(journal) == revision, "state.journal length must equal state.state_revision")
    journal_revisions: dict[str, int] = {}
    for index, entry in enumerate(journal):
        mapping = as_mapping(entry, f"state.journal[{index}]")
        require_known_keys(mapping, {"revision", "transaction_id", "committed_at", "summaries"}, f"state.journal[{index}]")
        entry_revision = as_int(mapping.get("revision"), f"state.journal[{index}].revision", minimum=1)
        require(entry_revision == index + 1, f"state.journal[{index}].revision must be {index + 1}")
        transaction_id = clean_text(mapping.get("transaction_id"), f"state.journal[{index}].transaction_id", max_bytes=128)
        require(transaction_id not in journal_revisions, f"state.journal repeats transaction_id {transaction_id}")
        journal_revisions[transaction_id] = entry_revision
        clean_text(mapping.get("committed_at"), f"state.journal[{index}].committed_at", max_bytes=64)
        summaries = as_list(mapping.get("summaries"), f"state.journal[{index}].summaries")
        require(bool(summaries), f"state.journal[{index}].summaries must not be empty")
        for summary_index, summary in enumerate(summaries):
            clean_text(summary, f"state.journal[{index}].summaries[{summary_index}]", max_bytes=768)
    transactions = as_mapping(state.get("applied_transactions"), "state.applied_transactions")
    require(set(transactions) == set(journal_revisions), "state.applied_transactions must match state.journal transaction ids")
    for transaction_id, record in transactions.items():
        clean_text(transaction_id, "state.applied_transactions key", max_bytes=128)
        mapping = as_mapping(record, f"state.applied_transactions.{transaction_id}")
        require_known_keys(mapping, {"revision", "digest", "item_ids"}, f"state.applied_transactions.{transaction_id}")
        transaction_revision = as_int(mapping.get("revision"), f"state.applied_transactions.{transaction_id}.revision", minimum=1)
        require(transaction_revision == journal_revisions[transaction_id], f"state.applied_transactions.{transaction_id}.revision does not match journal")
        digest = clean_text(mapping.get("digest"), f"state.applied_transactions.{transaction_id}.digest", max_bytes=64)
        require(len(digest) == 64 and all(char in "0123456789abcdef" for char in digest), f"state.applied_transactions.{transaction_id}.digest is invalid")
        item_ids = clean_id_list(mapping.get("item_ids"), f"state.applied_transactions.{transaction_id}.item_ids")
        require(bool(item_ids), f"state.applied_transactions.{transaction_id}.item_ids must not be empty")
        require(all(item_id in items for item_id in item_ids), f"state.applied_transactions.{transaction_id}.item_ids references an unknown item")
    result = {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_revision": revision,
        "next_item_number": next_number,
        "items": items,
        "journal": copy.deepcopy(journal),
        "applied_transactions": copy.deepcopy(transactions),
    }
    if book is not None:
        result["book"] = book
    return result


def load_state(store: Store) -> dict[str, Any] | None:
    if not store.state_path.exists():
        return None
    return validate_state(read_json(store.state_path), store=store)


def normalize_preference(value: object, label: str, *, allow_status: bool) -> dict[str, Any]:
    preference = as_mapping(value, label)
    allowed = {"kind", "scope", "assertion", "quote", "source_ref", "source", "confidence", "importance", "reason"}
    if allow_status:
        allowed |= {"status", "conflicts_with"}
    require_known_keys(preference, allowed, label)
    raw_source = preference.get("source")
    require(
        raw_source not in {"repeated_correction", "inferred_pattern"},
        f"{label}.source「{raw_source}」已不再写入：作者记忆只记作者明确表达的偏好，"
        f"不从重复修改或成稿轨迹推断；范围含糊的原话用 explicit_user 并置 status=pending",
    )
    source = choice(raw_source, WRITE_SOURCES, f"{label}.source")
    status = choice(preference.get("status"), ("active", "pending", "conflict"), f"{label}.status") if allow_status else "active"
    conflicts = clean_id_list(preference.get("conflicts_with", []), f"{label}.conflicts_with") if allow_status else []
    if status == "active":
        require(not conflicts, f"{label}.conflicts_with must be empty for active status")
    elif status == "conflict":
        require(bool(conflicts), f"{label}.conflicts_with is required for conflict status")
    else:
        require(not conflicts, f"{label}.conflicts_with is only valid for conflict status")
    return {
        "kind": choice(preference.get("kind"), KINDS, f"{label}.kind"),
        "scope": normalize_scope(preference.get("scope"), f"{label}.scope"),
        # 这里按存量上限收；ASSERTION_MAX_BYTES 只在真正新建条目时校验
        # （require_new_item_assertion），好让存量长断言仍能被强化。
        "assertion": clean_text(preference.get("assertion"), f"{label}.assertion", max_bytes=LEGACY_ASSERTION_MAX_BYTES),
        "quote": clean_text(preference.get("quote"), f"{label}.quote", max_bytes=768),
        "source_ref": optional_text(preference.get("source_ref"), f"{label}.source_ref", max_bytes=240),
        "source": source,
        "confidence": choice(preference.get("confidence"), CONFIDENCE_LEVELS, f"{label}.confidence"),
        "importance": choice(preference.get("importance"), IMPORTANCE_LEVELS, f"{label}.importance"),
        "status": status,
        "reason": clean_text(preference.get("reason"), f"{label}.reason", max_bytes=480),
        "conflicts_with": conflicts,
    }


def normalize_transaction(value: object) -> dict[str, Any]:
    transaction = as_mapping(value, "transaction")
    require_known_keys(transaction, {"schema_version", "transaction_id", "expected_state_revision", "operations"}, "transaction")
    require(transaction.get("schema_version") == INPUT_SCHEMA_VERSION, f"transaction.schema_version must be {INPUT_SCHEMA_VERSION}")
    transaction_id = clean_text(transaction.get("transaction_id"), "transaction.transaction_id", max_bytes=128)
    operations = as_list(transaction.get("operations"), "transaction.operations")
    require(1 <= len(operations) <= 32, "transaction.operations must contain 1-32 operations")
    normalized_operations: list[dict[str, Any]] = []
    for index, raw_operation in enumerate(operations):
        label = f"transaction.operations[{index}]"
        operation = as_mapping(raw_operation, label)
        action = operation.get("action")
        if action == "remember":
            require_known_keys(operation, {"action", "preference"}, label)
            normalized_operations.append({"action": action, "preference": normalize_preference(operation.get("preference"), f"{label}.preference", allow_status=True)})
        elif action == "decide":
            require_known_keys(operation, {"action", "item_id", "decision", "quote", "reason"}, label)
            normalized_operations.append({
                "action": action,
                "item_id": clean_id_list([operation.get("item_id")], f"{label}.item_id", maximum=1)[0],
                "decision": choice(operation.get("decision"), ("activate", "reject"), f"{label}.decision"),
                "quote": clean_text(operation.get("quote"), f"{label}.quote", max_bytes=768),
                "reason": clean_text(operation.get("reason"), f"{label}.reason", max_bytes=480),
            })
        elif action == "replace":
            require_known_keys(operation, {"action", "old_ids", "preference"}, label)
            old_ids = clean_id_list(operation.get("old_ids"), f"{label}.old_ids")
            require(bool(old_ids), f"{label}.old_ids must not be empty")
            normalized_operations.append({"action": action, "old_ids": old_ids, "preference": normalize_preference(operation.get("preference"), f"{label}.preference", allow_status=False)})
        elif action == "forget":
            require_known_keys(operation, {"action", "item_id", "quote", "reason"}, label)
            normalized_operations.append({
                "action": action,
                "item_id": clean_id_list([operation.get("item_id")], f"{label}.item_id", maximum=1)[0],
                "quote": clean_text(operation.get("quote"), f"{label}.quote", max_bytes=768),
                "reason": clean_text(operation.get("reason"), f"{label}.reason", max_bytes=480),
            })
        else:
            raise AuthorMemoryError(f"{label}.action must be one of: remember, decide, replace, forget")
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "expected_state_revision": as_int(transaction.get("expected_state_revision"), "transaction.expected_state_revision"),
        "operations": normalized_operations,
    }


def normalize_record_event(value: object) -> dict[str, Any]:
    event = as_mapping(value, "event")
    require_known_keys(event, {"schema_version", "event_id", "operation"}, "event")
    require(event.get("schema_version") == INPUT_SCHEMA_VERSION, f"event.schema_version must be {INPUT_SCHEMA_VERSION}")
    event_id = clean_text(event.get("event_id"), "event.event_id", max_bytes=120)
    normalized = normalize_transaction({
        "schema_version": INPUT_SCHEMA_VERSION,
        "transaction_id": f"record:{event_id}",
        "expected_state_revision": 0,
        "operations": [event.get("operation")],
    })
    return {"event_id": event_id, "operation": normalized["operations"][0]}


# ---------------------------------------------------------------------------
# Routing: which store does an operation belong to?
# ---------------------------------------------------------------------------


def scope_store_kind(scope: dict[str, str | None]) -> str:
    return "book" if scope["level"] == "book" else "project"


def store_kind_label(kind: str) -> str:
    return "书级（BP）" if kind == "book" else "项目级（AP）"


def operation_store_kind(operation: dict[str, Any], label: str) -> str:
    action = operation["action"]
    if action in {"decide", "forget"}:
        return id_store(operation["item_id"])
    preference = operation["preference"]
    kind = scope_store_kind(preference["scope"])
    if action == "remember":
        for conflict_id in preference["conflicts_with"]:
            require(
                id_store(conflict_id) == kind,
                f"{label}.conflicts_with 只能引用同一 store 的条目（{conflict_id} 在{store_kind_label(id_store(conflict_id))}）："
                f"本书例外不算与全局规则冲突，直接 remember 为 book 条目即可",
            )
        return kind
    for old_id in operation["old_ids"]:
        require(
            id_store(old_id) == kind,
            f"{label} replace 不能跨 store：{old_id} 在{store_kind_label(id_store(old_id))}，新条目范围属于{store_kind_label(kind)}；"
            f"跨 store 改版拆成 forget＋remember，存量 book 条目先 migrate",
        )
    return kind


def transaction_store_kind(transaction: dict[str, Any]) -> str:
    kinds = {
        operation_store_kind(operation, f"transaction.operations[{index}]")
        for index, operation in enumerate(transaction["operations"])
    }
    require(
        len(kinds) == 1,
        "一份事务只能写一个 store：项目级（global/genre/workflow 范围或 AP 编号）与书级（book 范围或 BP 编号）的操作要分开提交",
    )
    return kinds.pop()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def transaction_digest(transaction: dict[str, Any]) -> str:
    canonical = json.dumps(transaction, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(preference: dict[str, Any]) -> str:
    """同一条偏好的身份：kind＋scope＋断言，scope.value 与 same_scope_value 同样按
    casefold 比——否则「Urban」「urban」会各建一条，两条同断言一起挤进 prompt。"""
    scope = preference["scope"]
    value = {
        "kind": preference["kind"],
        "scope": {"level": scope["level"], "value": None if scope["value"] is None else scope["value"].casefold()},
        "assertion": preference["assertion"].casefold(),
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def require_new_item_assertion(preference: dict[str, Any]) -> None:
    """新建条目的断言限一句话。强化已有条目走不到这里——存量长断言必须还能
    被确认，否则作者重申老偏好只会派生一条重复条目，库反而更挤。"""
    size = len(preference["assertion"].encode("utf-8"))
    require(
        size <= ASSERTION_MAX_BYTES,
        f"新条目的 assertion {size} 字节，超出 {ASSERTION_MAX_BYTES} 字节上限——"
        f"断言限一句话，需要解释的背景写进 reason。若这是对已有条目的重申，"
        f"原样使用该条目的 assertion 即可强化（不受本上限约束）；"
        f"若确实是几条互不依赖的偏好，才拆成几条分别记录。",
    )


def require_scope_fits_store(state: dict[str, Any], scope: dict[str, str | None]) -> None:
    book = state.get("book")
    if book is None:
        require(
            scope["level"] != "book",
            "book 级条目须传 --book-root {书目录}——记忆随书存放在 {书}/.story/作者记忆/，不再写进工作区的项目级 store",
        )
    else:
        require(
            scope_fits_store(scope, book),
            f"book 条目的范围「{scope['value']}」与本书 store「{book}」不一致——只有这本书的条目才住在这个书目录",
        )


def next_item_id(state: dict[str, Any]) -> str:
    prefix = STORE_PREFIX["book"] if state.get("book") is not None else STORE_PREFIX["project"]
    item_id = f"{prefix}{state['next_item_number']:03d}"
    state["next_item_number"] += 1
    return item_id


def allocate_item(state: dict[str, Any], preference: dict[str, Any], revision: int) -> dict[str, Any]:
    require_new_item_assertion(preference)
    require_scope_fits_store(state, preference["scope"])
    return {
        "id": next_item_id(state),
        "kind": preference["kind"],
        "scope": copy.deepcopy(preference["scope"]),
        "assertion": preference["assertion"],
        "confidence": preference["confidence"],
        "importance": preference["importance"],
        "status": preference["status"],
        "source": preference["source"],
        "reason": preference["reason"],
        "conflicts_with": list(preference["conflicts_with"]),
        "confirmation_count": 1,
        "evidence": [{"quote": preference["quote"], "source_ref": preference["source_ref"]}],
        "created_revision": revision,
        "updated_revision": revision,
        "superseded_by": None,
    }


def best_level(first: str, second: str) -> str:
    return first if RANK[first] >= RANK[second] else second


def add_evidence(item: dict[str, Any], quote: str, source_ref: str | None) -> None:
    evidence = {"quote": quote, "source_ref": source_ref}
    if evidence not in item["evidence"]:
        item["evidence"].append(evidence)


def require_item(state: dict[str, Any], item_id: str, label: str) -> dict[str, Any]:
    require(item_id in state["items"], f"{label} references unknown item {item_id}")
    return state["items"][item_id]


def apply_remember(state: dict[str, Any], preference: dict[str, Any], revision: int) -> str:
    require_scope_fits_store(state, preference["scope"])
    for conflict_id in preference["conflicts_with"]:
        conflict = require_item(state, conflict_id, "remember")
        require(conflict["status"] == "active", f"remember conflict {conflict_id} must be active")
    preference_fingerprint = fingerprint(preference)
    for item in state["items"].values():
        if item["status"] not in {"active", "pending", "conflict"} or fingerprint(item) != preference_fingerprint:
            continue
        require(not (item["status"] == "conflict" and preference["status"] == "active"), f"conflict item {item['id']} must be resolved with replace or rejected")
        require(not (item["status"] == "active" and preference["status"] == "conflict"), f"active item {item['id']} cannot be recategorized as its own conflict")
        add_evidence(item, preference["quote"], preference["source_ref"])
        item["confirmation_count"] += 1
        item["confidence"] = best_level(item["confidence"], preference["confidence"])
        item["importance"] = best_level(item["importance"], preference["importance"])
        item["updated_revision"] = revision
        item["reason"] = preference["reason"]
        if item["status"] == "pending" and preference["status"] == "active":
            item["status"] = "active"
        elif item["status"] == "pending" and preference["status"] == "conflict":
            item["status"] = "conflict"
            item["conflicts_with"] = list(preference["conflicts_with"])
        elif item["status"] == "conflict" and preference["status"] == "conflict":
            item["conflicts_with"] = sorted(set(item["conflicts_with"]) | set(preference["conflicts_with"]))
        return f"强化 {item['id']}：{item['assertion']}"
    item = allocate_item(state, preference, revision)
    state["items"][item["id"]] = item
    return f"新增 {item['id']}（{item['status']}）：{item['assertion']}"


def apply_decide(state: dict[str, Any], operation: dict[str, Any], revision: int) -> str:
    item = require_item(state, operation["item_id"], "decide")
    require(item["status"] in {"pending", "conflict"}, f"decide requires pending/conflict item, got {item['status']}")
    if operation["decision"] == "activate":
        require(item["status"] == "pending" and not item["conflicts_with"], "conflict candidates must be activated with replace")
        item["status"] = "active"
        verb = "确认"
    else:
        item["status"] = "rejected"
        verb = "拒绝"
    add_evidence(item, operation["quote"], None)
    item["reason"] = operation["reason"]
    item["updated_revision"] = revision
    return f"{verb} {item['id']}：{item['assertion']}"


def release_conflicts(state: dict[str, Any], removed_ids: set[str], revision: int) -> int:
    """被撤下的 active 条目不再是任何候选的冲突对象；冲突对象清空的候选退回 pending。"""
    released = 0
    for candidate in state["items"].values():
        if candidate["status"] != "conflict":
            continue
        retained = [item_id for item_id in candidate["conflicts_with"] if item_id not in removed_ids]
        if retained == candidate["conflicts_with"]:
            continue
        candidate["conflicts_with"] = retained
        candidate["updated_revision"] = revision
        if not retained:
            candidate["status"] = "pending"
            released += 1
    return released


def apply_replace(state: dict[str, Any], operation: dict[str, Any], revision: int) -> str:
    old_items = [require_item(state, item_id, "replace") for item_id in operation["old_ids"]]
    for item in old_items:
        require(item["status"] in {"active", "conflict", "pending"}, f"replace target {item['id']} is already {item['status']}")
    replacement = allocate_item(state, operation["preference"], revision)
    replacement["status"] = "active"
    replacement["conflicts_with"] = []
    state["items"][replacement["id"]] = replacement
    for item in old_items:
        item["status"] = "superseded"
        item["superseded_by"] = replacement["id"]
        item["updated_revision"] = revision
    released = release_conflicts(state, {item["id"] for item in old_items}, revision)
    replaced = ", ".join(item["id"] for item in old_items)
    suffix = f"；{released} 个其他冲突候选退回待确认" if released else ""
    return f"用 {replacement['id']} 替代 {replaced}：{replacement['assertion']}{suffix}"


def apply_forget(state: dict[str, Any], operation: dict[str, Any], revision: int) -> str:
    item = require_item(state, operation["item_id"], "forget")
    require(item["status"] in {"active", "pending", "conflict"}, f"forget target {item['id']} is already {item['status']}")
    item["status"] = "superseded"
    item["superseded_by"] = None
    item["reason"] = operation["reason"]
    item["updated_revision"] = revision
    add_evidence(item, operation["quote"], None)
    released = release_conflicts(state, {item["id"]}, revision)
    suffix = f"；{released} 个冲突候选退回待确认" if released else ""
    return f"忘记 {item['id']}：{item['assertion']}{suffix}"


def committed_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def seal_transaction(
    updated: dict[str, Any],
    transaction_id: str,
    digest: str,
    summaries: list[str],
    *,
    store: Store,
) -> dict[str, Any]:
    """把本次修订写进 journal / applied_transactions，并整份校验。"""
    revision = updated["state_revision"] + 1
    updated["state_revision"] = revision
    updated["journal"].append({
        "revision": revision,
        "transaction_id": transaction_id,
        "committed_at": committed_now(),
        "summaries": summaries,
    })
    item_ids = sorted(
        (item_id for item_id, item in updated["items"].items() if item["updated_revision"] == revision),
        key=id_number,
    )
    require(bool(item_ids), "transaction did not update any author-memory item")
    updated["applied_transactions"][transaction_id] = {
        "revision": revision,
        "digest": digest,
        "item_ids": item_ids,
    }
    return validate_state(updated, store=store)


def apply_transaction(state: dict[str, Any], transaction: dict[str, Any], digest: str, *, store: Store) -> tuple[dict[str, Any], list[str]]:
    applied = state["applied_transactions"].get(transaction["transaction_id"])
    if applied is not None:
        require(applied["digest"] == digest, "transaction_id was already used with different content")
        return state, [f"事务已应用于修订 {applied['revision']}，本次为幂等重放"]
    require(transaction["expected_state_revision"] == state["state_revision"], f"stale state revision: expected {transaction['expected_state_revision']}, current {state['state_revision']}")
    updated = copy.deepcopy(state)
    revision = updated["state_revision"] + 1
    summaries: list[str] = []
    for operation in transaction["operations"]:
        if operation["action"] == "remember":
            summaries.append(apply_remember(updated, operation["preference"], revision))
        elif operation["action"] == "decide":
            summaries.append(apply_decide(updated, operation, revision))
        elif operation["action"] == "replace":
            summaries.append(apply_replace(updated, operation, revision))
        else:
            summaries.append(apply_forget(updated, operation, revision))
    return seal_transaction(updated, transaction["transaction_id"], digest, summaries, store=store), summaries


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------


def scope_label(scope: dict[str, str | None]) -> str:
    if scope["level"] == "global":
        return "全局"
    labels = {"genre": "题材", "book": "本书", "workflow": "流程"}
    return f"{labels[scope['level']]}：{scope['value']}"


def store_caption(state: dict[str, Any]) -> str:
    book = state.get("book")
    if book is None:
        return "项目级记忆（全局、题材、流程）；各书的书级记忆住在各自书目录的 .story/作者记忆/。"
    return f"本书「{book}」的书级记忆；全局、题材、流程记忆住在工作区的 .story/作者记忆/。"


def render_profile(state: dict[str, Any]) -> str:
    lines = [
        "# 作者画像",
        "",
        "<!-- 由 author_memory_commit.py 生成，请勿手改；修改请提交事务。 -->",
        "",
        f"> 状态修订：{state['state_revision']}。{store_caption(state)}仅列出已确认偏好；当前明确要求、本书设定与硬性门禁优先。",
        "",
    ]
    active = [item for item in state["items"].values() if item["status"] == "active"]
    for kind in KINDS:
        lines.extend([f"## {KIND_TITLES[kind]}", ""])
        items = sorted((item for item in active if item["kind"] == kind), key=lambda item: id_number(item["id"]))
        if not items:
            lines.extend(["- 暂无", ""])
            continue
        for item in items:
            # 必须显示 importance：它决定超编时谁留在 prompt 里，而「整理作者
            # 记忆」只以本文件为输入——不显示就无从判断该退役哪条。
            lines.append(
                f"- **{item['id']}**〔{scope_label(item['scope'])}｜重要 {item['importance']}"
                f"｜把握 {item['confidence']}｜确认 {item['confirmation_count']} 次〕{item['assertion']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_pending(state: dict[str, Any]) -> str:
    lines = [
        "# 待确认的作者习惯",
        "",
        "<!-- 由 author_memory_commit.py 生成，请勿手改；修改请提交事务。 -->",
        "",
        f"> 状态修订：{state['state_revision']}。{store_caption(state)}待确认项不参与创作约束，也不应打断当前任务。",
        "",
    ]
    items = sorted((item for item in state["items"].values() if item["status"] in {"pending", "conflict"}), key=lambda item: id_number(item["id"]))
    if not items:
        lines.extend(["暂无待确认项。", ""])
    for item in items:
        lines.extend([
            f"## {item['id']} · {'冲突' if item['status'] == 'conflict' else '待确认'}",
            "",
            f"- 候选习惯：{item['assertion']}",
            f"- 范围：{scope_label(item['scope'])}",
            f"- 原话：“{item['evidence'][-1]['quote']}”",
            f"- 依据：{item['reason']}",
            f"- 置信度 / 重要度：{item['confidence']} / {item['importance']}",
        ])
        if item["conflicts_with"]:
            lines.append(f"- 冲突对象：{', '.join(item['conflicts_with'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_journal(state: dict[str, Any]) -> str:
    lines = [
        "# 作者记忆变更记录",
        "",
        "<!-- 由 author_memory_commit.py 生成，请勿手改；最近记录在前。 -->",
        "",
        f"> {store_caption(state)}",
        "",
    ]
    if not state["journal"]:
        lines.extend(["暂无变更。", ""])
    for entry in reversed(state["journal"][-100:]):
        lines.extend([f"## r{entry['revision']} · {entry['committed_at']}", "", f"- 事务：`{entry['transaction_id']}`"])
        lines.extend(f"- {summary}" for summary in entry["summaries"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_views(state: dict[str, Any]) -> dict[str, str]:
    views = {
        "作者画像.md": render_profile(state),
        "待确认.md": render_pending(state),
        "变更记录.md": render_journal(state),
    }
    limits = {"作者画像.md": PROFILE_MAX_BYTES, "待确认.md": PENDING_MAX_BYTES, "变更记录.md": JOURNAL_MAX_BYTES}
    for name, payload in views.items():
        require(len(payload.encode("utf-8")) <= limits[name], f"{name} exceeds {limits[name]} bytes; consolidate old memory first")
    return views


def write_snapshot(store: Store, state: dict[str, Any]) -> None:
    views = render_views(state)
    state_payload = json_payload(state)
    require(len(state_payload.encode("utf-8")) <= STATE_MAX_BYTES, f"_author-memory-state.json exceeds {STATE_MAX_BYTES} bytes")
    for name, payload in views.items():
        write_if_changed(store.root / name, payload)
    # State is the authority and therefore the last commit point.
    write_if_changed(store.state_path, state_payload)


# ---------------------------------------------------------------------------
# Query & budget
# ---------------------------------------------------------------------------


def same_scope_value(item_value: str | None, requested: str | None) -> bool:
    return requested is not None and item_value is not None and item_value.casefold() == requested.casefold()


def summarize_assertion(assertion: str, *, limit: int = 14) -> str:
    return assertion if len(assertion) <= limit else assertion[:limit] + "…"


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    """query 载荷只带这四个字段——估算与真实输出必须同一把尺。"""
    return {"id": item["id"], "kind": item["kind"], "scope": item["scope"], "assertion": item["assertion"]}


def compact_bytes(item: dict[str, Any]) -> int:
    return len(json.dumps(compact_item(item), ensure_ascii=False).encode("utf-8"))


SCOPE_RANK = {"book": 0, "genre": 1, "workflow": 2, "global": 3}


def query_sort_key(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """重要度→本书例外→最近更新→确认次数→编号。

    重要度必须排在 scope 之前：超编时先丢的应当是不重要的条目，而不是「凡
    全局一律先丢」。scope 在前会让任意数量的 low 本书琐事挤掉 high 的全局
    铁律——那恰恰是作者最不愿意丢的那一类。同重要度之内才按本书例外优先。
    两个 store 的修订号互不可比，但 book 条目只来自书级 store、其余只来自项目
    级，同 scope 必同 store，所以按修订号比「最近更新」在合并后仍成立。
    """
    return (
        -RANK[item["importance"]],
        SCOPE_RANK[item["scope"]["level"]],
        -item["updated_revision"],
        -item["confirmation_count"],
        id_number(item["id"]),
    )


def fit_items(
    sorted_items: list[dict[str, Any]],
    revision: int,
    *,
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """按 query 输出信封把条目装进 QUERY_MAX_BYTES：装不下的跳过而不中断
    （一条长的不挡后面的短条），漏下的 ID 报进 omitted_ids（封顶
    OMITTED_IDS_MAX 条，omitted 保留真实总数）。返回 (结果文档, 全部漏下 ID)。

    漏项恒按候选优先级排序，不按被丢弃的先后：收尾回吐的条目优先级高于循环
    里跳过的，若按追加顺序排，omitted_ids 的封顶正好会把最该报的那条切掉。
    `extra` 是同样计入信封的附加字段（book_revision 等）。
    """
    result: dict[str, Any] = {
        "ok": True,
        "command": "query",
        "initialized": True,
        "revision": revision,
        "items": [],
        "omitted": 0,
        "omitted_ids": [],
    }
    result.update(extra or {})
    order = {item["id"]: index for index, item in enumerate(sorted_items)}
    kept: list[dict[str, Any]] = []
    dropped: set[str] = set()

    def ordered_omitted() -> list[str]:
        return sorted(dropped, key=order.__getitem__)

    def envelope_bytes() -> int:
        omitted = ordered_omitted()
        result["items"] = [compact_item(item) for item in kept]
        result["omitted"] = len(omitted)
        result["omitted_ids"] = omitted[:OMITTED_IDS_MAX]
        return len((json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))

    for item in sorted_items:
        kept.append(item)
        if envelope_bytes() > QUERY_MAX_BYTES:
            kept.pop()
            dropped.add(item["id"])
    # omitted 计数落定后包可能恰好贴边超出一两个字节，回吐条目直到装下。
    while kept and envelope_bytes() > QUERY_MAX_BYTES:
        dropped.add(kept.pop()["id"])
    envelope_bytes()
    return result, ordered_omitted()


def build_query_result(
    candidates: list[dict[str, Any]],
    project_state: dict[str, Any] | None,
    book_state: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """真实查询与写入端估算共用的唯一信封构造：候选已按优先级排好，这里补上
    book_revision 等附加字段再装填。两处信封差一个字段就是一次假阴性——回执
    说没事、query 照样丢条。"""
    extra: dict[str, Any] = {}
    if book_state is not None:
        extra["book_revision"] = book_state["state_revision"]
    revision = project_state["state_revision"] if project_state is not None else 0
    return fit_items(candidates, revision, extra=extra)


def merged_query(
    project_state: dict[str, Any] | None,
    book_state: dict[str, Any] | None,
    kinds: set[str],
    requested_scopes: dict[str, str | None],
) -> tuple[dict[str, Any], list[str]]:
    """真实查询的纯函数部分：项目级按 kind／scope 过滤（存量 book 条目不参与，
    migrate 后才回来），书级整个 store 就是这本书的，只按 status／kind 过滤；
    合并后按 重要度→本书例外→最近更新 装填。"""

    def relevant(item: dict[str, Any]) -> bool:
        if item["status"] != "active" or item["kind"] not in kinds:
            return False
        level = item["scope"]["level"]
        if level == "global":
            return True
        return level != "book" and same_scope_value(item["scope"]["value"], requested_scopes[level])

    candidates: list[dict[str, Any]] = []
    if project_state is not None:
        candidates.extend(item for item in project_state["items"].values() if relevant(item))
    if book_state is not None:
        candidates.extend(active_of_kinds(book_state, tuple(kinds)))
    candidates.sort(key=query_sort_key)
    return build_query_result(candidates, project_state, book_state)


def slice_weight(items: list[dict[str, Any]]) -> int:
    """切片在真实载荷里的占位：compact 字节＋每条在 JSON 数组里的分隔符。

    只比 compact 字节会挑错切片——条目多、单条短的切片字节和更小，实际占位
    却更大，于是估算判「装得下」而真实查询溢出（warnings 假阴性）。
    """
    return sum(compact_bytes(item) + 2 for item in items)


def active_of_kinds(state: dict[str, Any] | None, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    if state is None:
        return []
    return [item for item in state["items"].values() if item["status"] == "active" and item["kind"] in kinds]


def worst_case_items(
    project_state: dict[str, Any] | None,
    book_state: dict[str, Any] | None,
    kinds: tuple[str, ...],
) -> list[dict[str, Any]]:
    """某个任务组合的最坏查询候选：全局条目＋各 scope 维度上最重的单一切片。

    一次查询只带一个 book/genre/workflow，不同书的条目不会同现，所以按切片
    取最重而不是全加起来，多书工作区才不会被粗算误伤。切片按 casefold 归并，
    与 same_scope_value 同一口径——否则只差大小写的同名书在这里算两个切片、
    在真实查询里却合成一个，估算就成了下界。

    book 维度就是当前可见的书级 store（整个 store 是这本书的一片），所以写书级
    条目时「本书＋全局」是精确的；写项目级条目而没传 --book-root 时看不到任何
    书级 store，估算只覆盖项目级。项目级里的存量 book 条目不参与查询，也不参与
    估算。
    """
    pool = [item for item in active_of_kinds(project_state, kinds) if item["scope"]["level"] != "book"]
    worst = [item for item in pool if item["scope"]["level"] == "global"]
    slices: dict[str, dict[str, list[dict[str, Any]]]] = {"genre": {}, "workflow": {}}
    for item in pool:
        level = item["scope"]["level"]
        if level != "global":
            slices[level].setdefault((item["scope"]["value"] or "").casefold(), []).append(item)
    for level in ("genre", "workflow"):
        if slices[level]:
            worst.extend(max(slices[level].values(), key=slice_weight))
    worst.extend(active_of_kinds(book_state, kinds))
    worst.sort(key=query_sort_key)
    return worst


def legacy_book_items(project_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """项目级 store 里升级前写入、还活着的 book 条目——只有 migrate 会碰它们。"""
    if project_state is None:
        return []
    return [
        item for item in project_state["items"].values()
        if item["scope"]["level"] == "book" and item["status"] in {"active", "pending", "conflict"}
    ]


def query_budget_warnings(project_state: dict[str, Any] | None, book_state: dict[str, Any] | None) -> list[str]:
    """写入回执的预算提醒：每个任务组合按最坏查询情形试装，装不下的点名。

    写入永不因注入预算失败；提醒指向「整理作者记忆」。点名带断言首句——只给
    编号的话，作者不打开 作者画像.md 就无从判断丢的是什么。
    """
    warnings: list[str] = []
    for task, kinds in QUERY_COMBOS.items():
        worst = worst_case_items(project_state, book_state, kinds)
        _, omitted = build_query_result(worst, project_state, book_state)
        if not omitted:
            continue
        assertions = {item["id"]: item["assertion"] for item in worst}
        shown = "；".join(f"{item_id}「{summarize_assertion(assertions[item_id])}」" for item_id in omitted[:3])
        more = f" 等 {len(omitted)} 条" if len(omitted) > 3 else ""
        warnings.append(
            f"「{task}」最坏查询装不下 {len(omitted)} 条，它们不会进入 prompt："
            f"{shown}{more}——超出 {QUERY_MAX_BYTES} 字节注入预算。"
            f"说「整理作者记忆」可合并同义条、退役过时条。"
        )
    return warnings


def visible_states(
    store: Store,
    updated: dict[str, Any],
    workspace: Path,
    book_root: Path | None,
    book: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """写入后可见的两级状态：刚写的那份用内存里的，另一份只读加载（没有就 None）。

    此时写入已经落盘，另一份读不出来（书目录不存在、--book 与书级记录不符、state
    损坏）只能降级为提醒：若在这里报错，调用方会告诉作者「没记住」，换个 event_id
    重试就派生重复条目。"""
    try:
        if store.kind == "project":
            other = load_state(book_store(workspace, book_root, book)) if book_root is not None else None
            return updated, other, []
        return load_state(project_store(workspace)), updated, []
    except AuthorMemoryError as exc:
        other_label = "书级" if store.kind == "project" else "项目级"
        notice = f"已写入{store.label} store；但{other_label} store 读取失败，本次预算提醒没算上它：{exc}"
        return (updated, None, [notice]) if store.kind == "project" else (None, updated, [notice])


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def prepare_workspace(workspace: Path, book_root: Path | None = None) -> None:
    """每个命令的入口：校验工作区，并在单书布局下先把误放的书级 state 归位——
    归位之前项目级 store 读不出来，放在任何读取之前才能让只读查询也自愈。"""
    require(workspace.exists() and workspace.is_dir(), f"workspace does not exist: {workspace}")
    relocate_misplaced_book_state(workspace, book_root)


def store_fields(store: Store) -> dict[str, Any]:
    fields: dict[str, Any] = {"store": store.kind, "root": str(store.root)}
    if store.book is not None:
        fields["book"] = store.book
    return fields


def command_init(workspace: Path, book_root: Path | None, book: str | None) -> dict[str, Any]:
    prepare_workspace(workspace, book_root)
    store = book_store(workspace, book_root, book) if book_root is not None else project_store(workspace)
    state = load_state(store)
    if state is None:
        state = empty_state(store.book)
    write_snapshot(store, state)
    return {"ok": True, "command": "init", "revision": state["state_revision"], **store_fields(store)}


def command_commit(workspace: Path, book_root: Path | None, book: str | None, input_path: Path) -> dict[str, Any]:
    prepare_workspace(workspace, book_root)
    transaction = normalize_transaction(read_json(input_path))
    store = resolve_target_store(transaction_store_kind(transaction), workspace, book_root, book)
    require(store.state_path.exists(), f"{store.label} author memory is not initialized; run init first")
    state = load_state(store)
    digest = transaction_digest(transaction)
    updated, summaries = apply_transaction(state, transaction, digest, store=store)
    replayed = updated is state
    # 幂等重放时也重写快照，修复缺失或过期的派生视图。
    write_snapshot(store, updated)
    project_state, book_state, load_warnings = visible_states(store, updated, workspace, book_root, book)
    return {
        "ok": True,
        "command": "commit",
        "revision": updated["state_revision"],
        "transaction_id": transaction["transaction_id"],
        "replayed": replayed,
        "item_ids": updated["applied_transactions"][transaction["transaction_id"]]["item_ids"],
        "summaries": summaries,
        "warnings": load_warnings + query_budget_warnings(project_state, book_state),
        **store_fields(store),
    }


def command_record(workspace: Path, book_root: Path | None, book: str | None, input_path: Path) -> dict[str, Any]:
    prepare_workspace(workspace, book_root)
    event = normalize_record_event(read_json(input_path))
    store = resolve_target_store(operation_store_kind(event["operation"], "event.operation"), workspace, book_root, book)
    state = load_state(store)
    if state is None:
        state = empty_state(store.book)
    transaction_id = f"record:{event['event_id']}"
    applied = state["applied_transactions"].get(transaction_id)
    expected_revision = applied["revision"] - 1 if applied is not None else state["state_revision"]
    transaction = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "expected_state_revision": expected_revision,
        "operations": [event["operation"]],
    }
    digest = transaction_digest(transaction)
    updated, summaries = apply_transaction(state, transaction, digest, store=store)
    replayed = updated is state
    write_snapshot(store, updated)
    record = updated["applied_transactions"][transaction_id]
    item_ids = record["item_ids"]
    receipt = f"Author Memory Receipt: r{record['revision']} · {', '.join(item_ids)}"
    project_state, book_state, load_warnings = visible_states(store, updated, workspace, book_root, book)
    return {
        "ok": True,
        "command": "record",
        "revision": updated["state_revision"],
        "applied_revision": record["revision"],
        "event_id": event["event_id"],
        "replayed": replayed,
        "item_ids": item_ids,
        "receipt": receipt,
        "summaries": summaries,
        "warnings": load_warnings + query_budget_warnings(project_state, book_state),
        **store_fields(store),
    }


def command_query(
    workspace: Path,
    book_root: Path | None,
    kinds: list[str] | None,
    book: str | None,
    genre: str | None,
    workflow: str | None,
) -> dict[str, Any]:
    prepare_workspace(workspace, book_root)
    require(
        bool(kinds),
        "query 必须显式传 --kind（按 references/author-memory.md 的任务映射表选类型），不再默认返回全部类型",
    )
    project_state = load_state(project_store(workspace))
    book_state = load_state(book_store(workspace, book_root, book)) if book_root is not None else None
    if project_state is None and book_state is None:
        return {"ok": True, "command": "query", "initialized": False, "revision": 0, "items": [], "omitted": 0, "omitted_ids": []}
    requested_scopes = {
        "genre": optional_text(genre, "query.genre", max_bytes=180),
        "workflow": optional_text(workflow, "query.workflow", max_bytes=180),
    }
    # 装不下的**跳过而不中断**（一条长的不挡后面的短条），漏下的 ID 报进
    # omitted_ids：非空＝记忆超编该整理了，不是「没有更多了」。写入端的
    # warnings 与这里共用 build_query_result 同一个信封，估算即实况。
    result, _ = merged_query(project_state, book_state, set(kinds), requested_scopes)
    require(len((json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")) <= QUERY_MAX_BYTES, "query result exceeds its fixed byte budget")
    return result


def check_store(store: Store) -> dict[str, Any]:
    state = load_state(store)
    require(state is not None, f"{store.label} author memory is not initialized")
    views = render_views(state)
    for name, expected in views.items():
        view_path = store.root / name
        require(view_path.exists(), f"missing derived view: {view_path}")
        require(view_path.read_text(encoding="utf-8") == expected, f"derived view is stale or edited: {view_path}")
    counts = {status: sum(1 for item in state["items"].values() if item["status"] == status) for status in STATUSES}
    return {"revision": state["state_revision"], "counts": counts}


def command_check(workspace: Path, book_root: Path | None, book: str | None) -> dict[str, Any]:
    prepare_workspace(workspace, book_root)
    project = project_store(workspace)
    result: dict[str, Any] = {"ok": True, "command": "check"}
    if book_root is not None:
        store = book_store(workspace, book_root, book)
        result["book"] = {"name": store.book, "root": str(store.root), **check_store(store)}
        if project.state_path.exists():
            result["project"] = {"root": str(project.root), **check_store(project)}
    else:
        result["project"] = {"root": str(project.root), **check_store(project)}
    # 兼容旧调用：顶层 revision / counts 指项目级 store。
    primary = result.get("project") or result["book"]
    result["revision"] = primary["revision"]
    result["counts"] = primary["counts"]
    return result


MIGRATE_PREFIX = "migrate:"


def migration_digest(item: dict[str, Any]) -> str:
    """迁移事务的摘要只看条目不可变的身份：编号、类型、范围、断言。证据会随强化
    增长、状态会随 decide/forget 变化，它们若进摘要，中途失败后作者动过条目就会
    永远「already used with different content」。"""
    return transaction_digest({"id": item["id"], "kind": item["kind"], "scope": item["scope"], "assertion": item["assertion"]})


def migrated_item(source: dict[str, Any], new_id: str, revision: int, id_map: dict[str, str]) -> dict[str, Any]:
    """把项目级的存量 book 条目原样搬进书级 store：断言、证据、确认次数、重要度
    全部保留，只换编号与修订。冲突对象只保留同书已迁移的（重映射为 BP），
    引用全局条目的冲突关系不再成立——本书例外按优先级覆盖全局，不算冲突——
    对象清空的候选退回 pending。"""
    item = copy.deepcopy(source)
    item["id"] = new_id
    item["created_revision"] = revision
    item["updated_revision"] = revision
    item["superseded_by"] = None
    item["conflicts_with"] = [id_map[old] for old in source["conflicts_with"] if old in id_map]
    if item["status"] == "conflict" and not item["conflicts_with"]:
        item["status"] = "pending"
    return item


def migration_records(state: dict[str, Any]) -> dict[str, str]:
    """书级 store 里「源 AP 编号 → 已建 BP 编号」；每个源条目一笔 migrate:APxxx 事务。"""
    records: dict[str, str] = {}
    for transaction_id, record in state["applied_transactions"].items():
        if transaction_id.startswith(MIGRATE_PREFIX) and is_item_id(transaction_id[len(MIGRATE_PREFIX):]):
            records[transaction_id[len(MIGRATE_PREFIX):]] = record["item_ids"][0]
    return records


def apply_single(state: dict[str, Any], transaction_id: str, digest: str, mutate, summaries: list[str], *, store: Store) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    mutate(updated, updated["state_revision"] + 1)
    return seal_transaction(updated, transaction_id, digest, summaries, store=store)


def command_migrate(workspace: Path, book_root: Path | None, book: str | None) -> dict[str, Any]:
    """把项目级 store 里某本书的存量 book 条目搬进该书目录的书级 store。

    书级每个源条目一笔事务（migrate:APxxx，摘要只看不可变字段），所以每个源条目
    至多迁一次，与本次批次里还有哪些条目无关、源条目状态怎么变都不会锁死；项目级
    随后一笔事务把这批源条目标 superseded 并注明去向。先写书级再写项目级，中途
    失败直接重跑：书级已有记录的直接复用编号，只补项目级。
    """
    prepare_workspace(workspace, book_root)
    require(book_root is not None, "migrate 须传 --book-root {书目录}：书名到书目录的映射由调用方给出")
    project = project_store(workspace)
    store = book_store(workspace, book_root, book)
    assert store.book is not None
    project_state = load_state(project)
    book_state = load_state(store)

    def result(migrated: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "ok": True,
            "command": "migrate",
            "migrated": migrated,
            "project_revision": project_state["state_revision"] if project_state is not None else 0,
            "revision": book_state["state_revision"] if book_state is not None else 0,
            "warnings": query_budget_warnings(project_state, book_state),
            **store_fields(store),
        }

    if project_state is None:
        return result([])
    legacy = sorted(
        (item for item in legacy_book_items(project_state) if same_scope_value(item["scope"]["value"], store.book)),
        key=lambda item: id_number(item["id"]),
    )
    if book_state is None:
        if not legacy:
            return result([])
        book_state = empty_state(store.book)
    id_map = migration_records(book_state)

    # 1) 书级：还没迁的源条目各建一条 BP；已迁的复用编号。
    for item in legacy:
        if item["id"] in id_map:
            continue
        transaction_id = f"{MIGRATE_PREFIX}{item['id']}"
        new_id = f"{STORE_PREFIX['book']}{book_state['next_item_number']:03d}"

        preview = migrated_item(item, new_id, 1, id_map)

        def create(updated: dict[str, Any], revision: int, source=item, new_id=new_id) -> None:
            updated["next_item_number"] += 1
            updated["items"][new_id] = migrated_item(source, new_id, revision, id_map)

        book_state = apply_single(
            book_state, transaction_id, migration_digest(item), create,
            [f"迁移 {item['id']} → {new_id}（{preview['status']}）：{item['assertion']}"],
            store=store,
        )
        id_map[item["id"]] = new_id
    # 幂等重跑也重写快照，修复缺失或过期的派生视图。
    write_snapshot(store, book_state)

    # 2) 项目级：这批源条目标 superseded 并注明去向。
    migrated = [{"from": item["id"], "to": id_map[item["id"]]} for item in legacy]
    if legacy:
        transaction_id = f"{MIGRATE_PREFIX}{store.book.casefold()}:r{project_state['state_revision'] + 1}"
        digest = transaction_digest({"transaction_id": transaction_id, "migrated": migrated})

        def move_out(updated: dict[str, Any], revision: int) -> None:
            for item in legacy:
                target = updated["items"][item["id"]]
                target["status"] = "superseded"
                target["superseded_by"] = None
                target["conflicts_with"] = []
                target["reason"] = f"已迁移到书级 store「{store.book}」：{id_map[item['id']]}"
                target["updated_revision"] = revision
            release_conflicts(updated, set(id_map), revision)

        summaries = [f"迁出 {pair['from']} → {pair['to']}：{project_state['items'][pair['from']]['assertion']}" for pair in migrated]
        project_state = apply_single(project_state, transaction_id, digest, move_out, summaries, store=project)
        write_snapshot(project, project_state)
    return result(migrated)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_location(child: argparse.ArgumentParser) -> None:
        child.add_argument("--workspace", required=True, type=Path)
        child.add_argument("--book-root", type=Path, help="书目录；书级条目（scope.level=book / BP 编号）的落点")
        child.add_argument("--book", help="书名；传了 --book-root 时默认取 store 记录的书名或目录名")

    for command in ("init", "check", "migrate"):
        add_location(subparsers.add_parser(command))
    for command in ("commit", "record"):
        child = subparsers.add_parser(command)
        add_location(child)
        child.add_argument("--input", required=True, type=Path)
    query = subparsers.add_parser("query")
    add_location(query)
    query.add_argument("--kind", action="append", choices=KINDS)
    query.add_argument("--genre")
    query.add_argument("--workflow")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            result = command_init(args.workspace, args.book_root, args.book)
        elif args.command == "commit":
            result = command_commit(args.workspace, args.book_root, args.book, args.input)
        elif args.command == "record":
            result = command_record(args.workspace, args.book_root, args.book, args.input)
        elif args.command == "query":
            result = command_query(args.workspace, args.book_root, args.kind, args.book, args.genre, args.workflow)
        elif args.command == "migrate":
            result = command_migrate(args.workspace, args.book_root, args.book)
        else:
            result = command_check(args.workspace, args.book_root, args.book)
        emit(result)
        return 0
    except AuthorMemoryError as exc:
        emit({"ok": False, "error": str(exc)}, error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
