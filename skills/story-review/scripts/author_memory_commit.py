#!/usr/bin/env python3
"""Maintain evidence-backed author preferences and deterministic Markdown views.

The language model supplies compact semantic transactions. This tool validates
and applies them in memory, renders every derived view, and writes the JSON state
last as the commit point. Author memory is workspace-level and deliberately
separate from each book's story-continuity tracking.
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

# 写入即限载：query 的输出是要原样贴进执行 agent prompt 的注入载荷，
# QUERY_MAX_BYTES 是低优先级偏好在 prompt 里的注意力预算，不该放大。
# 防「作者以为载入了、实际被静默截断挤掉」的唯一可靠位置在写入端——
# 下列任务组合（与 references/author-memory.md 的映射表同包跟版）在
# 最坏查询情形下都必须装进 QUERY_MAX_BYTES，超限拒绝写入，先精简/
# 合并/退役旧条目。最坏情形＝全局条目＋各 scope 维度上最重的单一切片
# （一次查询只带一个 book/genre/workflow，不同书的条目不会同现）。
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
SOURCES = (
    "explicit_user",
    "accepted_suggestion",
    "repeated_correction",
    "inferred_pattern",
    "manual",
)
RANK = {"low": 0, "medium": 1, "high": 2}


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


def clean_id_list(value: object, label: str, *, maximum: int = 32) -> list[str]:
    raw = as_list(value, label)
    require(len(raw) <= maximum, f"{label} may contain at most {maximum} items")
    result: list[str] = []
    for index, item in enumerate(raw):
        item_id = clean_text(item, f"{label}[{index}]", max_bytes=32)
        require(item_id.startswith("AP") and item_id[2:].isdigit() and int(item_id[2:]) >= 1, f"{label}[{index}] is not an author-memory id")
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


def memory_root(workspace: Path) -> Path:
    return workspace.resolve() / ".story" / "作者记忆"


def state_path(workspace: Path) -> Path:
    return memory_root(workspace) / "_author-memory-state.json"


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_revision": 0,
        "next_item_number": 1,
        "items": {},
        "journal": [],
        "applied_transactions": {},
    }


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
    require(item_id.startswith("AP") and item_id[2:].isdigit() and int(item_id[2:]) >= 1, f"{label}.id is invalid")
    evidence = [normalize_evidence(entry, f"{label}.evidence[{index}]") for index, entry in enumerate(as_list(item.get("evidence"), f"{label}.evidence"))]
    require(bool(evidence), f"{label}.evidence must not be empty")
    status = choice(item.get("status"), STATUSES, f"{label}.status")
    conflicts = clean_id_list(item.get("conflicts_with"), f"{label}.conflicts_with")
    superseded_by = optional_text(item.get("superseded_by"), f"{label}.superseded_by", max_bytes=32)
    if superseded_by is not None:
        require(superseded_by.startswith("AP") and superseded_by[2:].isdigit(), f"{label}.superseded_by is invalid")
    return {
        "id": item_id,
        "kind": choice(item.get("kind"), KINDS, f"{label}.kind"),
        "scope": normalize_scope(item.get("scope"), f"{label}.scope"),
        "assertion": clean_text(item.get("assertion"), f"{label}.assertion", max_bytes=768),
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


def validate_state(value: object) -> dict[str, Any]:
    state = as_mapping(value, "state")
    allowed = {"schema_version", "state_revision", "next_item_number", "items", "journal", "applied_transactions"}
    require_known_keys(state, allowed, "state")
    require(state.get("schema_version") == STATE_SCHEMA_VERSION, f"state.schema_version must be {STATE_SCHEMA_VERSION}")
    revision = as_int(state.get("state_revision"), "state.state_revision")
    next_number = as_int(state.get("next_item_number"), "state.next_item_number", minimum=1)
    raw_items = as_mapping(state.get("items"), "state.items")
    items: dict[str, Any] = {}
    max_number = 0
    for raw_id, raw_item in raw_items.items():
        normalized = normalize_item(raw_item, f"state.items.{raw_id}")
        require(raw_id == normalized["id"], f"state.items key {raw_id} does not match item id")
        max_number = max(max_number, int(raw_id[2:]))
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
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "state_revision": revision,
        "next_item_number": next_number,
        "items": items,
        "journal": copy.deepcopy(journal),
        "applied_transactions": copy.deepcopy(transactions),
    }


def normalize_preference(value: object, label: str, *, allow_status: bool) -> dict[str, Any]:
    preference = as_mapping(value, label)
    allowed = {"kind", "scope", "assertion", "quote", "source_ref", "source", "confidence", "importance", "reason"}
    if allow_status:
        allowed |= {"status", "conflicts_with"}
    require_known_keys(preference, allowed, label)
    source = choice(preference.get("source"), SOURCES, f"{label}.source")
    status = choice(preference.get("status"), ("active", "pending", "conflict"), f"{label}.status") if allow_status else "active"
    conflicts = clean_id_list(preference.get("conflicts_with", []), f"{label}.conflicts_with") if allow_status else []
    if status == "active":
        require(not conflicts, f"{label}.conflicts_with must be empty for active status")
        require(source not in {"repeated_correction", "inferred_pattern"}, f"{label} inferred evidence must remain pending")
    elif status == "conflict":
        require(bool(conflicts), f"{label}.conflicts_with is required for conflict status")
    else:
        require(not conflicts, f"{label}.conflicts_with is only valid for conflict status")
    return {
        "kind": choice(preference.get("kind"), KINDS, f"{label}.kind"),
        "scope": normalize_scope(preference.get("scope"), f"{label}.scope"),
        "assertion": clean_text(preference.get("assertion"), f"{label}.assertion", max_bytes=768),
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


def transaction_digest(transaction: dict[str, Any]) -> str:
    canonical = json.dumps(transaction, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(preference: dict[str, Any]) -> str:
    value = {
        "kind": preference["kind"],
        "scope": preference["scope"],
        "assertion": preference["assertion"].casefold(),
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def allocate_item(state: dict[str, Any], preference: dict[str, Any], revision: int) -> dict[str, Any]:
    item_id = f"AP{state['next_item_number']:03d}"
    state["next_item_number"] += 1
    return {
        "id": item_id,
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
    old_ids = {item["id"] for item in old_items}
    released = 0
    for candidate in state["items"].values():
        if candidate["status"] != "conflict":
            continue
        retained = [item_id for item_id in candidate["conflicts_with"] if item_id not in old_ids]
        if retained == candidate["conflicts_with"]:
            continue
        candidate["conflicts_with"] = retained
        candidate["updated_revision"] = revision
        if not retained:
            candidate["status"] = "pending"
            released += 1
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
    released = 0
    for candidate in state["items"].values():
        if candidate["status"] != "conflict" or item["id"] not in candidate["conflicts_with"]:
            continue
        candidate["conflicts_with"] = [conflict_id for conflict_id in candidate["conflicts_with"] if conflict_id != item["id"]]
        candidate["updated_revision"] = revision
        if not candidate["conflicts_with"]:
            candidate["status"] = "pending"
            released += 1
    suffix = f"；{released} 个冲突候选退回待确认" if released else ""
    return f"忘记 {item['id']}：{item['assertion']}{suffix}"


def apply_transaction(state: dict[str, Any], transaction: dict[str, Any], digest: str) -> tuple[dict[str, Any], list[str]]:
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
    committed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    updated["state_revision"] = revision
    updated["journal"].append({
        "revision": revision,
        "transaction_id": transaction["transaction_id"],
        "committed_at": committed_at,
        "summaries": summaries,
    })
    item_ids = sorted(
        (item_id for item_id, item in updated["items"].items() if item["updated_revision"] == revision),
        key=lambda item_id: int(item_id[2:]),
    )
    require(bool(item_ids), "transaction did not update any author-memory item")
    updated["applied_transactions"][transaction["transaction_id"]] = {
        "revision": revision,
        "digest": digest,
        "item_ids": item_ids,
    }
    return validate_state(updated), summaries


def scope_label(scope: dict[str, str | None]) -> str:
    if scope["level"] == "global":
        return "全局"
    labels = {"genre": "题材", "book": "本书", "workflow": "流程"}
    return f"{labels[scope['level']]}：{scope['value']}"


def render_profile(state: dict[str, Any]) -> str:
    lines = [
        "# 作者画像",
        "",
        "<!-- 由 author_memory_commit.py 生成，请勿手改；修改请提交事务。 -->",
        "",
        f"> 状态修订：{state['state_revision']}。仅列出已确认偏好；当前明确要求、本书设定与硬性门禁优先。",
        "",
    ]
    active = [item for item in state["items"].values() if item["status"] == "active"]
    for kind in KINDS:
        lines.extend([f"## {KIND_TITLES[kind]}", ""])
        items = sorted((item for item in active if item["kind"] == kind), key=lambda item: int(item["id"][2:]))
        if not items:
            lines.extend(["- 暂无", ""])
            continue
        for item in items:
            lines.append(f"- **{item['id']}**〔{scope_label(item['scope'])}｜{item['confidence']}｜确认 {item['confirmation_count']} 次〕{item['assertion']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_pending(state: dict[str, Any]) -> str:
    lines = [
        "# 待确认的作者习惯",
        "",
        "<!-- 由 author_memory_commit.py 生成，请勿手改；修改请提交事务。 -->",
        "",
        f"> 状态修订：{state['state_revision']}。待确认项不参与创作约束，也不应打断当前任务。",
        "",
    ]
    items = sorted((item for item in state["items"].values() if item["status"] in {"pending", "conflict"}), key=lambda item: int(item["id"][2:]))
    if not items:
        lines.extend(["暂无待确认项。", ""])
    for item in items:
        lines.extend([
            f"## {item['id']} · {'冲突' if item['status'] == 'conflict' else '待确认'}",
            "",
            f"- 候选习惯：{item['assertion']}",
            f"- 范围：{scope_label(item['scope'])}",
            f"- 原话：\u201c{item['evidence'][-1]['quote']}\u201d",
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


def write_snapshot(workspace: Path, state: dict[str, Any]) -> None:
    root = memory_root(workspace)
    views = render_views(state)
    state_payload = json_payload(state)
    require(len(state_payload.encode("utf-8")) <= STATE_MAX_BYTES, f"_author-memory-state.json exceeds {STATE_MAX_BYTES} bytes")
    for name, payload in views.items():
        write_if_changed(root / name, payload)
    # State is the authority and therefore the last commit point.
    write_if_changed(state_path(workspace), state_payload)


def command_init(workspace: Path) -> dict[str, Any]:
    require(workspace.exists() and workspace.is_dir(), f"workspace does not exist: {workspace}")
    path = state_path(workspace)
    if path.exists():
        state = validate_state(read_json(path))
    else:
        state = empty_state()
    write_snapshot(workspace, state)
    return {"ok": True, "command": "init", "revision": state["state_revision"], "root": str(memory_root(workspace))}


def query_envelope_bytes(items: list[dict[str, Any]], revision: int) -> int:
    """按 command_query 同款 JSON 信封计算字节——校验与真实输出必须同一把尺。"""
    result = {
        "ok": True,
        "command": "query",
        "initialized": True,
        "revision": revision,
        "items": [
            {"id": i["id"], "kind": i["kind"], "scope": i["scope"], "assertion": i["assertion"]}
            for i in items
        ],
        "omitted": 0,
        "omitted_ids": [],
    }
    return len((json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


def enforce_query_budgets(state: dict[str, Any]) -> None:
    """每个任务组合在最坏查询情形下必须装进 QUERY_MAX_BYTES，否则拒绝写入。

    query 侧的截断只是最后的保险丝；真到那一步，作者以为载入的记忆已经静默
    失效。所以闸门设在这里：写不进去就先盘点——精简判据句、合并同义条、退役
    过时条。init/幂等重放不查（老库越限时仍可修复视图、可做减量盘点）。
    """
    for task, kinds in QUERY_COMBOS.items():
        pool = [i for i in state["items"].values() if i["status"] == "active" and i["kind"] in kinds]
        worst = [i for i in pool if i["scope"]["level"] == "global"]
        for level in ("book", "genre", "workflow"):
            slices: dict[str, list[dict[str, Any]]] = {}
            for i in pool:
                if i["scope"]["level"] == level:
                    slices.setdefault(i["scope"]["value"] or "", []).append(i)
            if slices:
                worst.extend(max(
                    slices.values(),
                    key=lambda items: sum(len(json.dumps(i, ensure_ascii=False).encode("utf-8")) for i in items),
                ))
        size = query_envelope_bytes(worst, state["state_revision"])
        if size <= QUERY_MAX_BYTES:
            continue
        heaviest = sorted(worst, key=lambda i: -len(i["assertion"].encode("utf-8")))[:6]
        detail = "；".join(f"{i['id']}({len(i['assertion'].encode('utf-8'))}B)" for i in heaviest)
        require(
            False,
            f"「{task}」组合最坏查询 {size} 字节，超出注入预算 {QUERY_MAX_BYTES}——"
            f"query 将静默截断，记忆看似载入实则失效。先精简/合并/退役旧条目再写入。"
            f"该组合最重条目：{detail}",
        )


def command_commit(workspace: Path, input_path: Path) -> dict[str, Any]:
    require(state_path(workspace).exists(), "author memory is not initialized; run init first")
    state = validate_state(read_json(state_path(workspace)))
    transaction = normalize_transaction(read_json(input_path))
    digest = transaction_digest(transaction)
    updated, summaries = apply_transaction(state, transaction, digest)
    replayed = updated is state
    if not replayed:
        enforce_query_budgets(updated)
        write_snapshot(workspace, updated)
    else:
        # Repair missing or stale views during an idempotent retry.
        write_snapshot(workspace, state)
    return {
        "ok": True,
        "command": "commit",
        "revision": updated["state_revision"],
        "transaction_id": transaction["transaction_id"],
        "replayed": replayed,
        "item_ids": updated["applied_transactions"][transaction["transaction_id"]]["item_ids"],
        "summaries": summaries,
    }


def command_record(workspace: Path, input_path: Path) -> dict[str, Any]:
    require(workspace.exists() and workspace.is_dir(), f"workspace does not exist: {workspace}")
    event = normalize_record_event(read_json(input_path))
    path = state_path(workspace)
    state = validate_state(read_json(path)) if path.exists() else empty_state()
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
    updated, summaries = apply_transaction(state, transaction, digest)
    replayed = updated is state
    if not replayed:
        enforce_query_budgets(updated)
    write_snapshot(workspace, updated)
    record = updated["applied_transactions"][transaction_id]
    item_ids = record["item_ids"]
    receipt = f"Author Memory Receipt: r{record['revision']} · {', '.join(item_ids)}"
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
    }


def same_scope_value(item_value: str | None, requested: str | None) -> bool:
    return requested is not None and item_value is not None and item_value.casefold() == requested.casefold()


def command_query(
    workspace: Path,
    kinds: list[str] | None,
    book: str | None,
    genre: str | None,
    workflow: str | None,
) -> dict[str, Any]:
    require(workspace.exists() and workspace.is_dir(), f"workspace does not exist: {workspace}")
    path = state_path(workspace)
    if not path.exists():
        return {"ok": True, "command": "query", "initialized": False, "revision": 0, "items": [], "omitted": 0, "omitted_ids": []}
    state = validate_state(read_json(path))
    requested_kinds = set(kinds or KINDS)
    requested_scopes = {
        "book": optional_text(book, "query.book", max_bytes=180),
        "genre": optional_text(genre, "query.genre", max_bytes=180),
        "workflow": optional_text(workflow, "query.workflow", max_bytes=180),
    }

    def relevant(item: dict[str, Any]) -> bool:
        if item["status"] != "active" or item["kind"] not in requested_kinds:
            return False
        level = item["scope"]["level"]
        return level == "global" or same_scope_value(item["scope"]["value"], requested_scopes[level])

    scope_rank = {"book": 0, "genre": 1, "workflow": 2, "global": 3}
    candidates = sorted(
        (item for item in state["items"].values() if relevant(item)),
        key=lambda item: (
            scope_rank[item["scope"]["level"]],
            -RANK[item["importance"]],
            -item["confirmation_count"],
            int(item["id"][2:]),
        ),
    )
    result: dict[str, Any] = {
        "ok": True,
        "command": "query",
        "initialized": True,
        "revision": state["state_revision"],
        "items": [],
        "omitted": 0,
        "omitted_ids": [],
    }
    # 写入即限载（enforce_query_budgets）保证这里恒装得下；截断分支只是老库
    # 未盘点时的过渡保险丝——装不下的**跳过而不中断**（一条长的不挡后面的短
    # 条），漏下的 ID 逐个报进 omitted_ids：非空＝记忆超编该盘点了，不是
    # 「没有更多了」。
    for item in candidates:
        compact = {
            "id": item["id"],
            "kind": item["kind"],
            "scope": item["scope"],
            "assertion": item["assertion"],
        }
        result["items"].append(compact)
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n"
        if len(payload.encode("utf-8")) > QUERY_MAX_BYTES:
            result["items"].pop()
            result["omitted_ids"].append(item["id"])
    # omitted 计数落定后包可能恰好贴边超出一两个字节，回吐条目直到装下。
    result["omitted"] = len(result["omitted_ids"])
    while result["items"] and len((json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")) > QUERY_MAX_BYTES:
        result["omitted_ids"].append(result["items"].pop()["id"])
        result["omitted"] = len(result["omitted_ids"])
    require(len((json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")) <= QUERY_MAX_BYTES, "query result exceeds its fixed byte budget")
    return result


def command_check(workspace: Path) -> dict[str, Any]:
    path = state_path(workspace)
    require(path.exists(), "author memory is not initialized")
    state = validate_state(read_json(path))
    views = render_views(state)
    root = memory_root(workspace)
    for name, expected in views.items():
        view_path = root / name
        require(view_path.exists(), f"missing derived view: {view_path}")
        require(view_path.read_text(encoding="utf-8") == expected, f"derived view is stale or edited: {view_path}")
    counts = {status: sum(1 for item in state["items"].values() if item["status"] == status) for status in STATUSES}
    return {"ok": True, "command": "check", "revision": state["state_revision"], "counts": counts}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "check"):
        child = subparsers.add_parser(command)
        child.add_argument("--workspace", required=True, type=Path)
    commit = subparsers.add_parser("commit")
    commit.add_argument("--workspace", required=True, type=Path)
    commit.add_argument("--input", required=True, type=Path)
    record = subparsers.add_parser("record")
    record.add_argument("--workspace", required=True, type=Path)
    record.add_argument("--input", required=True, type=Path)
    query = subparsers.add_parser("query")
    query.add_argument("--workspace", required=True, type=Path)
    query.add_argument("--kind", action="append", choices=KINDS)
    query.add_argument("--book")
    query.add_argument("--genre")
    query.add_argument("--workflow")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            result = command_init(args.workspace)
        elif args.command == "commit":
            result = command_commit(args.workspace, args.input)
        elif args.command == "record":
            result = command_record(args.workspace, args.input)
        elif args.command == "query":
            result = command_query(args.workspace, args.kind, args.book, args.genre, args.workflow)
        else:
            result = command_check(args.workspace)
        emit(result)
        return 0
    except AuthorMemoryError as exc:
        emit({"ok": False, "error": str(exc)}, error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
