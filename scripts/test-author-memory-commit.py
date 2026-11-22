#!/usr/bin/env python3
"""Behavior regression for the two-level author-memory transaction tool."""

from __future__ import annotations

import importlib.util
import itertools
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "skills" / "story-long-write" / "scripts" / "author_memory_commit.js"
NODE = shutil.which("node") or "node"


def run(*args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [NODE, str(TOOL), *args],
        cwd=REPO,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"expected exit {expect}, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transaction(transaction_id: str, revision: int, operations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "expected_state_revision": revision,
        "operations": operations,
    }


def preference(
    assertion: str,
    quote: str,
    *,
    status: str = "active",
    source: str = "explicit_user",
    scope_level: str = "global",
    scope_value: str | None = None,
    conflicts_with: list[str] | None = None,
    kind: str = "prose_style",
    importance: str = "high",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "scope": {"level": scope_level, "value": scope_value},
        "assertion": assertion,
        "quote": quote,
        "source_ref": "test:conversation",
        "source": source,
        "confidence": "high" if source == "explicit_user" else "medium",
        "importance": importance,
        "status": status,
        "reason": "behavior regression evidence",
        "conflicts_with": conflicts_with or [],
    }


def replacement(assertion: str, quote: str, **scope: Any) -> dict[str, Any]:
    document = preference(assertion, quote, **scope)
    document.pop("status")
    document.pop("conflicts_with")
    return document


def event(event_id: str, operation: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "event_id": event_id, "operation": operation}


def remember(event_id: str, pref: dict[str, Any]) -> dict[str, Any]:
    return event(event_id, {"action": "remember", "preference": pref})


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def memory_dir(root: Path) -> Path:
    return root / ".story" / "作者记忆"


def state(root: Path) -> dict[str, Any]:
    return json.loads((memory_dir(root) / "_author-memory-state.json").read_text(encoding="utf-8"))


def save_state(root: Path, document: dict[str, Any]) -> None:
    (memory_dir(root) / "_author-memory-state.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def commit(workspace: Path, input_path: Path, document: dict[str, Any], *extra: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    write_json(input_path, document)
    return run("commit", "--workspace", str(workspace), "--input", str(input_path), *extra, expect=expect)


def record(workspace: Path, input_path: Path, document: dict[str, Any], *extra: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    write_json(input_path, document)
    return run("record", "--workspace", str(workspace), "--input", str(input_path), *extra, expect=expect)


def query(workspace: Path, *args: str, expect: int = 0) -> dict[str, Any]:
    result = run("query", "--workspace", str(workspace), *args, expect=expect)
    if expect:
        return {"stderr": result.stderr}
    document = json.loads(result.stdout)
    assert sum(len((line + "\n").encode("utf-8")) for line in document["lines"]) <= 2048, "交给执行者的 lines 恒 ≤2048 字节"
    return document


def run_node_check(js_code: str, payload: object = None) -> dict[str, Any]:
    completed = subprocess.run(
        [NODE, "-e", js_code, str(TOOL)],
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else "",
        cwd=REPO, text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"node check failed ({completed.returncode}):\nstdout={completed.stdout}\nstderr={completed.stderr}")
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


KINDS = ("prose_style", "story_design", "workflow", "delivery", "interaction")


def synthetic_state(generator: random.Random, *, book: str | None, books: list[str], genres: list[str], workflows: list[str]) -> dict[str, Any]:
    """合成一份 store：book=None 是项目级（含存量 book 条目），否则是该书的书级 store。"""
    values = {"book": books, "genre": genres, "workflow": workflows}
    prefix = "BP" if book is not None else "AP"
    items = {}
    for number in range(1, generator.randint(1, 60) + 1):
        if book is None:
            level = generator.choice(["global", "global", "book", "genre", "workflow"])
            value = None if level == "global" else generator.choice(values[level])
        else:
            level, value = "book", book
        items[f"{prefix}{number:03d}"] = {
            "id": f"{prefix}{number:03d}",
            "kind": generator.choice(KINDS),
            "scope": {"level": level, "value": value},
            "assertion": "文" * generator.randint(1, 40),
            "status": generator.choice(["active"] * 6 + ["pending", "superseded"]),
            "importance": generator.choice(["low", "medium", "high"]),
            "updated_revision": generator.randint(1, 500),
            "confirmation_count": generator.randint(0, 9),
        }
    document: dict[str, Any] = {"items": items, "state_revision": generator.randint(1, 9999), "journal": []}
    if book is not None:
        document["book"] = book
    return document


def assert_no_false_negatives() -> None:
    """核心不变式：写入回执没给提醒 ⟹ 任何真实 query 都不会漏条。"""
    books = ["甲", "Lucky", "lucky", "LUCKY", "乙"]
    genres = ["悬疑", "Urban", "urban"]
    workflows = ["长篇", "short", "SHORT"]
    generator = random.Random(4290918)
    cases = []
    for _ in range(300):
        project_state = synthetic_state(generator, book=None, books=books, genres=genres, workflows=workflows)
        visible_book = generator.choice(books + [None])
        book_state = None if visible_book is None else synthetic_state(generator, book=visible_book, books=books, genres=genres, workflows=workflows)
        cases.append({"project_state": project_state, "book_state": book_state})
    js = r"""
const fs = require('fs');
const assert = require('assert');
const mod = require(process.argv[1]);
const { cases, genres, workflows } = JSON.parse(fs.readFileSync(0, 'utf8'));
let warnedLibraries = 0;
for (const { project_state, book_state } of cases) {
  const warnings = mod.queryBudgetWarnings(project_state, book_state);
  if (warnings.some((w) => w.includes('最坏查询'))) warnedLibraries += 1;
  for (const [task, kinds] of Object.entries(mod.QUERY_COMBOS)) {
    if (warnings.some((w) => w.includes(`「${task}」`))) continue;
    for (const genre of [...genres, null]) {
      for (const workflow of [...workflows, null]) {
        const requested = { genre, workflow };
        const visList = book_state ? [book_state, null] : [null];
        for (const visible of visList) {
          const { omittedIds } = mod.mergedQuery(project_state, visible, new Set(kinds), requested);
          assert.equal(omittedIds.length, 0,
            `写入端没提醒「${task}」，但 query(book_root=${visible ? '有' : '无'}, genre=${genre}, workflow=${workflow}) 漏了 ${omittedIds}`);
        }
      }
    }
  }
}
assert(warnedLibraries > 20, `warnedLibraries=${warnedLibraries} <= 20`);
process.stdout.write(JSON.stringify({ warnedLibraries }));
"""
    run_node_check(js, {"cases": cases, "genres": genres, "workflows": workflows})


def assert_slice_weight_uses_rendered_lines() -> None:
    """挑「最重切片」必须按执行者读到的行算，与装填同一把尺。"""
    js = r"""
const assert = require('assert');
const mod = require(process.argv[1]);
const item = (number, value, assertion) => ({
  id: `AP${String(number).padStart(3, '0')}`, kind: 'prose_style',
  scope: { level: 'genre', value }, assertion, status: 'active',
  importance: 'medium', updated_revision: 400, confirmation_count: 1,
});
const items = {};
for (let i = 0; i < 12; i++) items[`AP${String(i + 1).padStart(3, '0')}`] = item(i + 1, '甲'.repeat(60), `甲短${i}`);
for (let i = 0; i < 12; i++) items[`AP${String(i + 100).padStart(3, '0')}`] = item(i + 100, '乙', `乙偏好${i}：` + '文'.repeat(52));
const heavyJson = Object.values(items).filter((e) => e.scope.value.startsWith('甲'));
const heavyLines = Object.values(items).filter((e) => e.scope.value === '乙');
const jsonWeight = (arr) => arr.reduce((a, e) => a + Buffer.byteLength(JSON.stringify(mod.compactItem(e)), 'utf8'), 0);
assert(jsonWeight(heavyJson) > jsonWeight(heavyLines));
assert(mod.sliceWeight(heavyJson) < mod.sliceWeight(heavyLines));
assert.equal(mod.fitItems([...heavyJson].sort(mod.compareQueryItems), 700).omittedIds.length, 0);
assert(mod.fitItems([...heavyLines].sort(mod.compareQueryItems), 700).omittedIds.length > 0);
const warnings = mod.queryBudgetWarnings({ items, state_revision: 700, journal: [] }, null);
assert(warnings.some((w) => w.includes('最坏查询')));

const entry = (number, level, value, chars) => ({ ...item(number, value || '', '文'.repeat(chars)), scope: { level, value } });
const mixed = {};
for (let i = 0; i < 12; i++) mixed[`AP${String(i + 1).padStart(3, '0')}`] = entry(i + 1, 'global', null, 40);
mixed['AP013'] = entry(13, 'global', null, 6);
for (let i = 0; i < 3; i++) mixed[`AP${String(i + 20).padStart(3, '0')}`] = entry(i + 20, 'genre', '甲', 40);
for (let i = 0; i < 5; i++) mixed[`AP${String(i + 30).padStart(3, '0')}`] = entry(i + 30, 'genre', '乙', 23);
const fewLong = Object.values(mixed).filter((e) => e.scope.value === '甲');
const manyShort = Object.values(mixed).filter((e) => e.scope.value === '乙');
assert(fewLong.reduce((a, e) => a + Buffer.byteLength(e.assertion, 'utf8'), 0) > manyShort.reduce((a, e) => a + Buffer.byteLength(e.assertion, 'utf8'), 0));
assert(mod.sliceWeight(fewLong) < mod.sliceWeight(manyShort));
const library = { items: mixed, state_revision: 700, journal: [] };
assert(mod.mergedQuery(library, null, new Set(['prose_style']), { genre: '乙', workflow: null }).omittedIds.length > 0);
assert(mod.queryBudgetWarnings(library, null).some((w) => w.includes('最坏查询')));
"""
    run_node_check(js)


def assert_omitted_follow_priority_and_lines_fit() -> None:
    """装填只量执行者读到的行；漏项全数列出、按候选优先级排序、附断言首句。"""
    js = r"""
const assert = require('assert');
const mod = require(process.argv[1]);
const items = Array.from({ length: 40 }, (_, idx) => {
  const number = idx + 1;
  return {
    id: `AP${String(number).padStart(3, '0')}`, kind: 'prose_style',
    scope: { level: 'global', value: null }, assertion: `第${number}条` + '文'.repeat(36),
    importance: 'medium', updated_revision: 100 - number, confirmation_count: 1,
  };
});
items.sort(mod.compareQueryItems);
const { result, omittedIds: omitted } = mod.fitItems(items.map((x) => ({ ...x })), 500);
const order = Object.fromEntries(items.map((item, idx) => [item.id, idx]));
assert(omitted.length > 20);
assert.equal(result.items.length + result.omitted, items.length);
assert.deepEqual(result.omitted_ids, omitted);
assert.deepEqual(omitted, [...omitted].sort((a, b) => order[a] - order[b]));
assert.deepEqual(new Set(Object.keys(result.omitted_summaries)), new Set(omitted));
assert(Object.values(result.omitted_summaries).every((s) => Array.from(s).length <= 15));
assert.deepEqual(result.lines, result.items.map((item) => `- ${item.assertion}（${item.id}）`));
const used = result.lines.reduce((a, line) => a + Buffer.byteLength(line + '\n', 'utf8'), 0);
assert(used <= mod.QUERY_MAX_BYTES);
const firstDropped = items.find((item) => item.id === omitted[0]);
assert(used + mod.lineBytes(firstDropped) > mod.QUERY_MAX_BYTES);
const full = items.slice(0, 15).map((item) => ({ ...item, assertion: '文'.repeat(40) }));
assert.equal(mod.fitItems(full, 500).omittedIds.length, 0);
assert.deepEqual(new Set(Object.keys(result.omitted_importance)), new Set(omitted));
const exact = [...full, { ...items[15], assertion: '文'.repeat(8) }];
assert.equal(exact.reduce((a, item) => a + mod.lineBytes(item), 0), mod.QUERY_MAX_BYTES);
assert.equal(mod.fitItems(exact, 500).omittedIds.length, 0);
const over = [...full, { ...items[15], assertion: '文'.repeat(8) + 'x' }];
assert.deepEqual(mod.fitItems(over, 500).omittedIds, [items[15].id]);
const queue = [...full.slice(0, 14), { ...items[20], assertion: '长'.repeat(250) }, { ...items[21], assertion: '短' }];
const { result: skippedResult, omittedIds: skipped } = mod.fitItems(queue, 500);
assert.deepEqual(skipped, [items[20].id]);
assert.equal(skippedResult.items[skippedResult.items.length - 1].id, items[21].id);
"""
    run_node_check(js)


def assert_single_root_layout(temporary: Path, input_path: Path) -> None:
    """单书布局（书根就是工作区）：两级 store 的默认落点重合，书级改住 书级/ 子目录。"""
    # ---- 全新工作区：项目级、书级各写一条，query 两条都在 ----
    fresh = temporary / "单书"
    fresh.mkdir()
    root_args = ("--book-root", str(fresh))
    book_pref = preference("本书对话短句推进", "这本书对话都短一点。", scope_level="book", scope_value="单书")
    first = json.loads(record(fresh, input_path, remember("sr-global", preference("全局：动词承重", "记住：动词承重。")), *root_args).stdout)
    assert first["store"] == "project" and first["receipt"] == "Author Memory Receipt: r1 · AP001"
    booked = json.loads(record(fresh, input_path, remember("sr-book", book_pref), *root_args).stdout)
    assert booked["store"] == "book" and booked["book"] == "单书" and booked["receipt"] == "Author Memory Receipt: r1 · BP001"
    book_dir = memory_dir(fresh) / "书级"
    assert Path(booked["root"]) == book_dir.resolve(), "书级 store 必须落在子目录，不与项目级共用 state"
    assert "book" not in state(fresh) and list(state(fresh)["items"]) == ["AP001"]
    assert json.loads((book_dir / "_author-memory-state.json").read_text(encoding="utf-8"))["book"] == "单书"
    # 书级写入之后，项目级写入与查询照常可用（修复前这里恒报 state.book）
    second = json.loads(record(fresh, input_path, remember("sr-global-2", preference("全局：段尾不抒情", "记住：段尾不抒情。")), *root_args).stdout)
    assert second["item_ids"] == ["AP002"] and second["warnings"] == []
    assert [item["id"] for item in query(fresh, "--kind", "prose_style", *root_args)["items"]] == ["BP001", "AP002", "AP001"]
    assert [item["id"] for item in query(fresh, "--kind", "prose_style")["items"]] == ["AP002", "AP001"], "不传书根拿不到书级条目"
    forgot = json.loads(record(fresh, input_path, event("sr-forget", {"action": "forget", "item_id": "BP001", "quote": "x", "reason": "x"}), *root_args).stdout)
    assert forgot["store"] == "book" and forgot["item_ids"] == ["BP001"]
    run("check", "--workspace", str(fresh), *root_args)

    # ---- v0.7.10 单根存量库：query / 书级 record / migrate 都可用，书名取存量条目 ----
    legacy = temporary / "novel-root"  # 目录名不是书名
    legacy.mkdir()
    legacy_args = ("--book-root", str(legacy))
    record(legacy, input_path, remember("v710-global", preference("全局：少用感叹号", "记住：少用感叹号。")))
    seeded = state(legacy)
    old_item = json.loads(json.dumps(seeded["items"]["AP001"], ensure_ascii=False))
    old_item.update({"id": "AP002", "scope": {"level": "book", "value": "雾港来信"}, "assertion": "雾港来信：章末留钩子", "confirmation_count": 2})
    seeded["items"]["AP002"] = old_item
    seeded["next_item_number"] = 3
    save_state(legacy, seeded)
    run("init", "--workspace", str(legacy))
    assert [item["id"] for item in query(legacy, "--kind", "prose_style", *legacy_args)["items"]] == ["AP001"], "存量 book 条目迁移前不参与查询"
    fresh_book = json.loads(record(legacy, input_path, remember("v710-book", preference(
        "雾港来信：对话短句", "这本书对话短一点。", scope_level="book", scope_value="雾港来信",
    )), *legacy_args).stdout)
    assert fresh_book["book"] == "雾港来信" and fresh_book["item_ids"] == ["BP001"], "单书布局下书名默认取唯一的存量书名，而不是目录名"
    moved = json.loads(run("migrate", "--workspace", str(legacy), *legacy_args).stdout)
    assert moved["migrated"] == [{"from": "AP002", "to": "BP002"}] and moved["book"] == "雾港来信"
    after = state(legacy)
    assert "book" not in after and after["items"]["AP002"]["status"] == "superseded"
    moved_book = json.loads((memory_dir(legacy) / "书级" / "_author-memory-state.json").read_text(encoding="utf-8"))
    assert moved_book["items"]["BP002"]["confirmation_count"] == 2
    assert [item["id"] for item in query(legacy, "--kind", "prose_style", *legacy_args)["items"]] == ["BP002", "BP001", "AP001"]
    assert json.loads(run("migrate", "--workspace", str(legacy), *legacy_args).stdout)["migrated"] == []
    run("check", "--workspace", str(legacy), *legacy_args)

    # ---- 已被旧版写坏的工作区：项目级位置上是一份书级 state，带书根运行即自愈 ----
    donor = temporary / "供体工作区"
    donor_root = donor / "长篇" / "雾港来信"
    donor_root.mkdir(parents=True)
    record(donor, input_path, remember("donor-book", preference(
        "雾港来信：对话短句", "这本书对话短一点。", scope_level="book", scope_value="雾港来信",
    )), "--book-root", str(donor_root))
    broken = temporary / "坏库"
    shutil.copytree(memory_dir(donor_root), memory_dir(broken))
    broken_args = ("--book-root", str(broken))
    assert "--book-root" in query(broken, "--kind", "prose_style", expect=2)["stderr"], "报错要指出怎么自愈"
    before_failure = snapshot(memory_dir(broken))
    record(broken, input_path, remember("broken-global", preference("全局：标题短", "记住：标题短。")), expect=2)
    assert snapshot(memory_dir(broken)) == before_failure
    healed = query(broken, "--kind", "prose_style", *broken_args)
    assert [item["id"] for item in healed["items"]] == ["BP001"] and healed["book_revision"] == 1
    assert "book" not in state(broken) and state(broken)["state_revision"] == 0, "项目级位置补一份空 state"
    relocated = json.loads((memory_dir(broken) / "书级" / "_author-memory-state.json").read_text(encoding="utf-8"))
    assert relocated["book"] == "雾港来信" and list(relocated["items"]) == ["BP001"], "归位不改 state 内容"
    run("check", "--workspace", str(broken), *broken_args)
    assert json.loads(record(broken, input_path, remember("healed-global", preference("全局：标题短", "记住：标题短。"))).stdout)["item_ids"] == ["AP001"]
    booked_again = json.loads(record(broken, input_path, remember("healed-book", preference(
        "雾港来信：少用比喻", "这本书少用比喻。", scope_level="book", scope_value="雾港来信",
    )), *broken_args).stdout)
    assert booked_again["item_ids"] == ["BP002"]
    # 两处都是书级 state 时不猜，报错点名两份文件
    shutil.copy(memory_dir(donor_root) / "_author-memory-state.json", memory_dir(broken) / "_author-memory-state.json")
    assert "无法自动归位" in query(broken, "--kind", "prose_style", *broken_args, expect=2)["stderr"]


def error_text(stderr: str) -> str:
    """报错走 JSON（ensure_ascii），Windows 路径的反斜杠会被转义；按字段取出原文再比。"""
    try:
        return str(json.loads(stderr)["error"])
    except (ValueError, KeyError, TypeError):
        return stderr


def assert_book_dir_is_not_single_root(temporary: Path, input_path: Path) -> None:
    """多书工作区里的书目录被误传成 --workspace（书目录自己也含 .story/作者记忆/）：
    不得当单书布局挪动书级 state，报错、零写入；正确调用照常可用。"""
    workspace = temporary / "多书工作区"
    book_root = workspace / "长篇" / "甲书"
    book_root.mkdir(parents=True)
    book_args = ("--book-root", str(book_root))
    record(workspace, input_path, remember("mb-global", preference("全局：动词承重", "记住：动词承重。")))
    record(workspace, input_path, remember("mb-book", preference(
        "甲书：对话短句", "这本书对话短一点。", scope_level="book", scope_value="甲书",
    )), *book_args)
    before = snapshot(workspace)
    mistaken = ("--workspace", str(book_root), *book_args)
    for command in (("query", "--kind", "prose_style"), ("init",), ("check",), ("migrate",)):
        failed = run(command[0], *mistaken, *command[1:], expect=2)
        assert f"--workspace 应传 {workspace.resolve()}" in error_text(failed.stderr), failed.stderr
    record(book_root, input_path, remember("mb-book-2", preference(
        "甲书：少用比喻", "这本书少用比喻。", scope_level="book", scope_value="甲书",
    )), *book_args, expect=2)
    assert snapshot(workspace) == before, "误传书目录为工作区时不得改动任何文件"
    assert not (memory_dir(book_root) / "书级").exists()
    # 误传不带 --book-root 时，报错提示不得只引导「带 --book-root {工作区} 重跑」
    hint = query(book_root, "--kind", "prose_style", expect=2)["stderr"]
    assert "改传创作工作区根" in hint and "单书布局" in hint, hint
    # 正确调用照常可用
    assert [item["id"] for item in query(workspace, "--kind", "prose_style", *book_args)["items"]] == ["BP001", "AP001"]
    run("check", "--workspace", str(workspace), *book_args)

    # 其余两种迹象：祖先有 .active-book，或祖先有项目级 store（书目录不在 长篇/ 短篇/ 下）
    marked = temporary / "标记工作区"
    (marked / "书稿" / "乙书").mkdir(parents=True)
    (marked / ".active-book").write_text("书稿/乙书\n", encoding="utf-8")
    nested = marked / "书稿" / "乙书"
    assert f"--workspace 应传 {marked.resolve()}" in error_text(run("init", "--workspace", str(nested), "--book-root", str(nested), expect=2).stderr)
    stored = temporary / "有项目级工作区"
    (stored / "丙书").mkdir(parents=True)
    run("init", "--workspace", str(stored))
    nested = stored / "丙书"
    assert f"--workspace 应传 {stored.resolve()}" in error_text(run("init", "--workspace", str(nested), "--book-root", str(nested), expect=2).stderr)
    assert not memory_dir(nested).exists()


def assert_write_lock_blocks_busy_and_serializes_writes(temporary: Path, input_path: Path) -> None:
    """写锁在锁文件被占用时超时报错，并在并发 record 下串行化写入不丢更新。"""
    lock_ws = temporary / "写锁工作区"
    lock_ws.mkdir()
    run("init", "--workspace", str(lock_ws))
    lock_file = memory_dir(lock_ws) / ".author-memory.lock"
    lock_file.write_text("pid=99999\n", encoding="utf-8")
    try:
        probe = subprocess.run(
            [
                NODE,
                "-e",
                (
                    "const mod = require(process.argv[1]);"
                    "const store = mod.projectStore(process.argv[2]);"
                    "try {"
                    "  mod.withStoreWriteLock(store, () => {}, { timeoutSeconds: 0.15 });"
                    "  process.exit(1);"
                    "} catch (err) {"
                    "  if (!(err instanceof mod.AuthorMemoryError) || !/lock is busy or stale/.test(err.message)) process.exit(3);"
                    "  process.stdout.write(err.message);"
                    "}"
                ),
                str(TOOL),
                str(lock_ws),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert probe.returncode == 0, f"busy lock must throw AuthorMemoryError: {probe.returncode} {probe.stdout} {probe.stderr}"
    finally:
        lock_file.unlink(missing_ok=True)

    # 并发 4 个 record 子进程写同一工作区，全部成功且修订号连续推进到 4，无锁文件残留。
    race_ws = temporary / "并发写锁工作区"
    race_ws.mkdir()
    procs = []
    for idx in range(4):
        ev_file = temporary / f"race-ev-{idx}.json"
        ev_file.write_text(
            json.dumps(
                remember(f"race-{idx}", preference(f"并发偏好{idx}：保持短句节奏", f"作者说第{idx}条。")),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        procs.append(
            subprocess.Popen(
                [NODE, str(TOOL), "record", "--workspace", str(race_ws), "--input", str(ev_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        )
    for proc in procs:
        out, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, f"concurrent record failed: {out} {err}"
    race_state = state(race_ws)
    assert race_state["state_revision"] == 4, f"expected revision 4, got {race_state['state_revision']}"
    assert len(race_state["items"]) == 4, f"expected 4 items, got {len(race_state['items'])}"
    assert not (memory_dir(race_ws) / ".author-memory.lock").exists(), "lockfile must be cleaned up"
    run("check", "--workspace", str(race_ws))


def assert_single_root_case_insensitive_path(temporary: Path, input_path: Path) -> None:
    """大小写不敏感的文件系统（macOS APFS 默认）上，只差大小写的书根仍是同一目录。"""
    probe = temporary / "CaseProbe"
    probe.mkdir()
    if not (temporary / "caseprobe").exists():
        return  # 大小写敏感的文件系统上没有这种别名
    workspace = temporary / "Book"
    workspace.mkdir()
    alias = ("--book-root", str(temporary / "book"))
    record(workspace, input_path, remember("ci-global", preference("全局：动词承重", "记住：动词承重。")), *alias)
    booked = json.loads(record(workspace, input_path, remember("ci-book", preference(
        "本书对话短句", "这本书对话短一点。", scope_level="book", scope_value="Book",
    )), *alias).stdout)
    assert booked["item_ids"] == ["BP001"] and Path(booked["root"]).name == "书级", "只差大小写的书根也按单书布局住子目录"
    assert "book" not in state(workspace), "项目级 state 不得被书级条目占用"
    assert [item["id"] for item in query(workspace, "--kind", "prose_style", *alias)["items"]] == ["BP001", "AP001"]


def assert_other_store_failure_is_nonfatal(temporary: Path, input_path: Path) -> None:
    """写入已落盘后，读另一级 store 失败只降级为提醒：报错会让 agent 告诉作者「没记住」，
    换个 event_id 重试就派生重复条目。"""
    workspace = temporary / "读取失败工作区"
    book_root = workspace / "长篇" / "甲"
    book_root.mkdir(parents=True)
    missing = ("--book-root", str(workspace / "长篇" / "不存在"))
    global_event = remember("nf-global", preference("全局：动词承重", "记住：动词承重。"))
    written = json.loads(record(workspace, input_path, global_event, *missing).stdout)
    assert written["ok"] and written["receipt"] == "Author Memory Receipt: r1 · AP001"
    assert any("读取失败" in warning and "book root does not exist" in warning for warning in written["warnings"])
    assert state(workspace)["state_revision"] == 1
    replayed = json.loads(record(workspace, input_path, global_event, *missing).stdout)
    assert replayed["replayed"] is True and len(state(workspace)["items"]) == 1, "重试不得派生重复条目"
    committed = json.loads(commit(workspace, input_path, transaction("nf-tx", 1, [
        {"action": "remember", "preference": preference("全局：段尾不抒情", "记住：段尾不抒情。")},
    ]), *missing).stdout)
    assert committed["item_ids"] == ["AP002"] and any("读取失败" in warning for warning in committed["warnings"])

    record(workspace, input_path, remember("nf-book", preference(
        "甲书：对话短句", "这本书对话短一点。", scope_level="book", scope_value="甲",
    )), "--book-root", str(book_root))
    mismatched = json.loads(record(workspace, input_path, remember("nf-global-2", preference("全局：标题短", "记住：标题短。")),
                                   "--book-root", str(book_root), "--book", "乙").stdout)
    assert mismatched["item_ids"] == ["AP003"] and any("不一致" in warning for warning in mismatched["warnings"])

    (memory_dir(workspace) / "_author-memory-state.json").write_text("{损坏", encoding="utf-8")
    book_written = json.loads(record(workspace, input_path, remember("nf-book-2", preference(
        "甲书：少用比喻", "这本书少用比喻。", scope_level="book", scope_value="甲",
    )), "--book-root", str(book_root)).stdout)
    assert book_written["item_ids"] == ["BP002"] and any("项目级 store 读取失败" in warning for warning in book_written["warnings"])
    assert state(book_root)["state_revision"] == 2


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="author-memory-test-") as temporary:
        workspace = Path(temporary) / "创作工作区"
        workspace.mkdir()
        input_path = Path(temporary) / "transaction.json"
        memory = memory_dir(workspace)

        empty_query = query(workspace, "--kind", "prose_style")
        assert empty_query["items"] == []
        assert not memory.exists(), "a read-only query must not initialize author memory"

        init_result = json.loads(run("init", "--workspace", str(workspace)).stdout)
        assert init_result["revision"] == 0 and init_result["store"] == "project"
        assert {path.name for path in memory.iterdir()} == {
            "_author-memory-state.json",
            "作者画像.md",
            "变更记录.md",
        }
        run("check", "--workspace", str(workspace))

        first = transaction(
            "tx-active",
            0,
            [{"action": "remember", "preference": preference(
                "对话尽量短，用动作承接情绪，不用大段解释",
                "以后对话都短一点，情绪放动作里，别让角色长篇解释。",
            )}],
        )
        commit(workspace, input_path, first)
        current = state(workspace)
        assert current["state_revision"] == 1
        assert current["items"]["AP001"]["status"] == "active"
        assert "AP001" in (memory / "作者画像.md").read_text(encoding="utf-8")

        replay = commit(workspace, input_path, first)
        assert json.loads(replay.stdout)["replayed"] is True
        assert state(workspace)["state_revision"] == 1

        reused = json.loads(json.dumps(first, ensure_ascii=False))
        reused["operations"][0]["preference"]["quote"] = "同一 ID 的不同内容"
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, reused, expect=2)
        assert "different content" in error.stderr
        assert snapshot(memory) == before_failure

        # ---- 0.10：不再记待确认、冲突候选，也没有 decide；推断管道不再写入（#436）----
        for status, extra in (("pending", {}), ("conflict", {"conflicts_with": ["AP001"]})):
            candidate = transaction(f"tx-{status}-rejected", 1, [{"action": "remember", "preference": preference(
                "候选不再写入", "大概这样吧。", status=status, **extra)}])
            before_failure = snapshot(memory)
            error = commit(workspace, input_path, candidate, expect=2)
            assert "不再记待确认或冲突候选" in error.stderr, "拒写要告诉 agent 先问作者"
            assert snapshot(memory) == before_failure
        second = transaction(
            "tx-second",
            1,
            [{"action": "remember", "preference": preference(
                "倾向用物件细节替代直接心理说明",
                "以后心理活动落到东西上。",
            )}],
        )
        commit(workspace, input_path, second)
        assert state(workspace)["items"]["AP002"]["status"] == "active"

        for inferred_source in ("inferred_pattern", "repeated_correction"):
            inferred = transaction(
                f"tx-{inferred_source}",
                2,
                [{"action": "remember", "preference": preference(
                    "推断出的习惯不再写入",
                    "从成稿里看起来如此。",
                    status="pending",
                    source=inferred_source,
                )}],
            )
            before_failure = snapshot(memory)
            error = commit(workspace, input_path, inferred, expect=2)
            assert "已不再写入" in error.stderr and "explicit_user" in error.stderr, "拒写要告诉 agent 该怎么改"
            assert snapshot(memory) == before_failure

        restate = transaction(
            "tx-restate",
            2,
            [{"action": "remember", "preference": preference(
                "倾向用物件细节替代直接心理说明",
                "对，这也是我的长期习惯。",
            )}],
        )
        commit(workspace, input_path, restate)
        assert state(workspace)["items"]["AP002"]["confirmation_count"] == 2

        third = transaction(
            "tx-third",
            3,
            [{"action": "remember", "preference": preference(
                "允许更长的试探性对话",
                "以后对话慢一点，多试探几轮。",
            )}],
        )
        commit(workspace, input_path, third)
        # 直改 state 模拟旧版留下的冲突候选（冲突对象 AP001）：不进查询，只能 replace / forget。
        legacy_conflict = state(workspace)
        legacy_conflict["items"]["AP003"]["status"] = "conflict"
        legacy_conflict["items"]["AP003"]["conflicts_with"] = ["AP001"]
        save_state(workspace, legacy_conflict)
        run("init", "--workspace", str(workspace))
        assert "AP003" not in [item["id"] for item in query(workspace, "--kind", "prose_style")["items"]]

        illegal_activation = transaction(
            "tx-illegal-conflict-activation",
            4,
            [{
                "action": "decide",
                "item_id": "AP003",
                "decision": "activate",
                "quote": "启用它。",
                "reason": "decide is gone",
            }],
        )
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, illegal_activation, expect=2)
        assert "decide 已移除" in error.stderr
        assert snapshot(memory) == before_failure

        replace = transaction(
            "tx-replace",
            4,
            [{
                "action": "replace",
                "old_ids": ["AP001", "AP003"],
                "preference": replacement(
                    "对话允许更长的试探，但避免解释设定",
                    "以后可以让对话慢一点，多试探，但还是别拿台词讲设定。",
                ),
            }],
        )
        commit(workspace, input_path, replace)
        current = state(workspace)
        assert current["items"]["AP001"]["status"] == "superseded"
        assert current["items"]["AP003"]["status"] == "superseded"
        assert current["items"]["AP004"]["status"] == "active"
        assert current["items"]["AP001"]["superseded_by"] == "AP004"

        forget = transaction(
            "tx-forget",
            5,
            [{
                "action": "forget",
                "item_id": "AP002",
                "quote": "忘掉这个偏好。",
                "reason": "author withdrew it",
            }],
        )
        commit(workspace, input_path, forget)
        assert state(workspace)["items"]["AP002"]["status"] == "superseded"

        reinforce_preference = replacement(
            "对话允许更长的试探，但避免解释设定",
            "就按慢对话和少解释继续。",
        )
        reinforce_preference["status"] = "active"
        reinforce_preference["conflicts_with"] = []
        reinforce = transaction(
            "tx-reinforce",
            6,
            [{"action": "remember", "preference": reinforce_preference}],
        )
        commit(workspace, input_path, reinforce)
        current = state(workspace)
        assert current["next_item_number"] == 5
        assert current["items"]["AP004"]["confirmation_count"] == 2
        assert len(current["items"]["AP004"]["evidence"]) == 2

        stale = transaction(
            "tx-stale",
            5,
            [{"action": "forget", "item_id": "AP004", "quote": "旧事务", "reason": "stale"}],
        )
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, stale, expect=2)
        assert "stale state revision" in error.stderr
        assert snapshot(memory) == before_failure

        partial_failure = transaction(
            "tx-partial-failure",
            7,
            [
                {"action": "remember", "preference": preference("不应落盘", "这条事务后面会失败。")},
                {"action": "forget", "item_id": "AP999", "quote": "不存在", "reason": "force rollback"},
            ],
        )
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, partial_failure, expect=2)
        assert "unknown item AP999" in error.stderr
        assert snapshot(memory) == before_failure

        unknown_field = transaction(
            "tx-unknown-field",
            7,
            [{"action": "forget", "item_id": "AP004", "quote": "x", "reason": "x", "extra": True}],
        )
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, unknown_field, expect=2)
        assert "unsupported fields" in error.stderr
        assert snapshot(memory) == before_failure

        profile = memory / "作者画像.md"
        profile.write_text(profile.read_text(encoding="utf-8") + "手工污染\n", encoding="utf-8")
        # Default check emits drift_warnings (exit 0); --strict exits 2.
        soft_check = json.loads(run("check", "--workspace", str(workspace)).stdout)
        assert soft_check["ok"] is True and len(soft_check["drift_warnings"]) == 1
        assert "stale or edited" in soft_check["drift_warnings"][0]["message"]
        assert "询问作者" in soft_check["drift_warnings"][0]["prompt"]
        check_error = run("check", "--workspace", str(workspace), "--strict", expect=2)
        assert "stale or edited" in check_error.stderr
        replay = commit(workspace, input_path, reinforce)
        assert json.loads(replay.stdout)["replayed"] is True
        run("check", "--workspace", str(workspace), "--strict")
        assert "手工污染" not in profile.read_text(encoding="utf-8")

        record_event = remember("conversation-message-42", preference(
            "全局偏好用具体物件承载情绪",
            "记住：以后尽量让情绪落到具体物件上。",
        ))
        recorded = json.loads(record(workspace, input_path, record_event).stdout)
        assert recorded["receipt"] == "Author Memory Receipt: r8 · AP005"
        assert recorded["replayed"] is False and recorded["store"] == "project"

        queried = query(workspace, "--kind", "prose_style", "--book", "雾港来信")
        assert [item["id"] for item in queried["items"]] == ["AP005", "AP004"], "同重要度、同 scope 下最近写入的排前"
        assert all(item["id"] not in {"AP001", "AP002", "AP003"} for item in queried["items"])
        assert "book_revision" not in queried

        forget_event = event("conversation-message-43", {
            "action": "forget",
            "item_id": "AP005",
            "quote": "这个全局偏好先忘掉。",
            "reason": "author withdrew the newly recorded preference",
        })
        forgotten = json.loads(record(workspace, input_path, forget_event).stdout)
        assert forgotten["receipt"] == "Author Memory Receipt: r9 · AP005"
        replayed_record = json.loads(record(workspace, input_path, record_event).stdout)
        assert replayed_record["replayed"] is True
        assert replayed_record["applied_revision"] == 8
        assert state(workspace)["items"]["AP005"]["status"] == "superseded"

        final = state(workspace)
        assert final["state_revision"] == 9
        assert set(final["applied_transactions"]) == {
            "tx-active", "tx-second", "tx-restate", "tx-third", "tx-replace", "tx-forget", "tx-reinforce",
            "record:conversation-message-42", "record:conversation-message-43",
        }
        assert all(record["item_ids"] for record in final["applied_transactions"].values())

        # ---- #436：存量 state 里的推断来源条目仍可读、可 decide/forget ----
        legacy_source = state(workspace)
        legacy_source["items"]["AP002"]["source"] = "repeated_correction"
        legacy_source["items"]["AP004"]["source"] = "inferred_pattern"
        save_state(workspace, legacy_source)
        run("check", "--workspace", str(workspace))
        assert [item["id"] for item in query(workspace, "--kind", "prose_style")["items"]] == ["AP004"]
        legacy_forget = json.loads(record(workspace, input_path, event("legacy-source-forget", {
            "action": "forget", "item_id": "AP004", "quote": "这条也忘掉。", "reason": "存量推断条目照常可退役",
        })).stdout)
        assert legacy_forget["item_ids"] == ["AP004"]

        # ================= #435：项目级 / 书级两级 store =================
        book_root = workspace / "长篇" / "雾港来信"
        book_root.mkdir(parents=True)
        book_memory = memory_dir(book_root)
        book_pref = preference(
            "本书对话允许更长的试探，但避免解释设定",
            "这本书可以让对话慢一点，多试探，但还是别拿台词讲设定。",
            scope_level="book", scope_value="雾港来信",
        )

        # book 条目没传 --book-root：拒写并指路，项目级 store 零写入
        before_failure = snapshot(memory)
        routed = record(workspace, input_path, remember("book-without-root", book_pref), expect=2)
        assert "--book-root" in routed.stderr and "随书" in routed.stderr
        assert snapshot(memory) == before_failure
        assert not book_memory.exists()

        # 传了 --book-root：落进书目录，BP 编号，书名默认取目录名
        book_recorded = json.loads(record(workspace, input_path, remember("book-with-root", book_pref), "--book-root", str(book_root)).stdout)
        assert book_recorded["receipt"] == "Author Memory Receipt: r1 · BP001"
        assert book_recorded["store"] == "book" and book_recorded["book"] == "雾港来信"
        assert {path.name for path in book_memory.iterdir()} == {"_author-memory-state.json", "作者画像.md", "变更记录.md"}
        book_state = state(book_root)
        assert book_state["book"] == "雾港来信" and book_state["items"]["BP001"]["scope"] == {"level": "book", "value": "雾港来信"}
        assert "BP001" in (book_memory / "作者画像.md").read_text(encoding="utf-8")
        assert "雾港来信" in (book_memory / "作者画像.md").read_text(encoding="utf-8"), "书级画像要标明是哪本书"
        assert "BP001" not in (memory / "作者画像.md").read_text(encoding="utf-8"), "书级条目不进项目级画像"
        assert state(workspace)["state_revision"] == 10, "写书级 store 不推进项目级修订"

        # 别的书的条目不能塞进这个书目录
        wrong_book = preference("乙书偏好", "乙书原话。", scope_level="book", scope_value="乙")
        error = record(workspace, input_path, remember("wrong-book", wrong_book), "--book-root", str(book_root), expect=2)
        assert "不一致" in error.stderr
        # --book 与 store 记录的书名不一致也拒
        error = record(workspace, input_path, remember("wrong-name", book_pref), "--book-root", str(book_root), "--book", "别的书", expect=2)
        assert "不一致" in error.stderr

        # 同断言、只差大小写的 scope.value 走强化，不派生第二条
        for value in ("Urban", "urban"):
            genre_result = json.loads(record(workspace, input_path, remember(f"genre-{value}", preference(
                "都市文多用短句", "都市文短句。", scope_level="genre", scope_value=value,
            ))).stdout)
        assert genre_result["item_ids"] == ["AP006"] and "强化" in genre_result["summaries"][0], "scope.value 按 casefold 归并"
        assert state(workspace)["items"]["AP006"]["confirmation_count"] == 2
        record(workspace, input_path, event("genre-forget", {"action": "forget", "item_id": "AP006", "quote": "x", "reason": "x"}))
        # 全局条目即使传了 --book-root 也路由到项目级
        global_via_book = json.loads(record(workspace, input_path, remember("global-with-book-root", preference(
            "段尾不落抒情句", "记住：段尾别落抒情句。",
        )), "--book-root", str(book_root)).stdout)
        assert global_via_book["store"] == "project" and global_via_book["item_ids"] == ["AP007"]

        # 合并查询：项目级 + 书级，本书例外在同重要度下排前
        merged = query(workspace, "--kind", "prose_style", "--book-root", str(book_root))
        assert [item["id"] for item in merged["items"]] == ["BP001", "AP007"]
        assert merged["book_revision"] == 1 and merged["revision"] == 14
        # 没传书目录拿不到书级条目——书级 store 只能从书目录读
        assert [item["id"] for item in query(workspace, "--kind", "prose_style")["items"]] == ["AP007"]
        # 书目录存在但还没有书级 store：照常只返回项目级
        other_root = workspace / "长篇" / "无记忆之书"
        other_root.mkdir()
        assert [item["id"] for item in query(workspace, "--kind", "prose_style", "--book-root", str(other_root))["items"]] == ["AP007"]
        assert not memory_dir(other_root).exists(), "只读查询不得初始化书级 store"

        # 一份事务只写一个 store；replace 不能跨 store；conflicts_with 不能跨 store
        run("init", "--workspace", str(workspace), "--book-root", str(book_root))
        mixed = transaction("tx-mixed-stores", 1, [
            {"action": "forget", "item_id": "BP001", "quote": "x", "reason": "x"},
            {"action": "forget", "item_id": "AP007", "quote": "x", "reason": "x"},
        ])
        error = commit(workspace, input_path, mixed, "--book-root", str(book_root), expect=2)
        assert "只能写一个 store" in error.stderr
        cross_replace = transaction("tx-cross-replace", 1, [{
            "action": "replace", "old_ids": ["AP007"],
            "preference": replacement("本书段尾可以落抒情句", "这本书段尾可以抒情。", scope_level="book", scope_value="雾港来信"),
        }])
        error = commit(workspace, input_path, cross_replace, "--book-root", str(book_root), expect=2)
        assert "不能跨 store" in error.stderr and "forget" in error.stderr
        cross_conflict = remember("cross-conflict", preference(
            "本书允许段尾抒情", "这本书例外。", status="conflict", scope_level="book", scope_value="雾港来信", conflicts_with=["AP007"],
        ))
        error = record(workspace, input_path, cross_conflict, "--book-root", str(book_root), expect=2)
        assert "不再记待确认或冲突候选" in error.stderr
        assert state(book_root)["state_revision"] == 1 and state(workspace)["state_revision"] == 14

        # decide / forget 按编号前缀路由：BP 没传 --book-root 拒，传了就进书级
        error = record(workspace, input_path, event("bp-forget-no-root", {
            "action": "forget", "item_id": "BP001", "quote": "x", "reason": "x",
        }), expect=2)
        assert "--book-root" in error.stderr
        book_commit = json.loads(commit(workspace, input_path, transaction("tx-book-replace", 1, [{
            "action": "replace", "old_ids": ["BP001"],
            "preference": replacement("本书对话可以慢，但不拿台词讲设定", "改一下说法。", scope_level="book", scope_value="雾港来信"),
        }]), "--book-root", str(book_root)).stdout)
        assert book_commit["store"] == "book" and book_commit["item_ids"] == ["BP001", "BP002"]
        assert state(book_root)["items"]["BP001"]["superseded_by"] == "BP002"

        # check 同时核对两级；书级画像被手改默认出 drift_warnings，--strict 才 exit 2
        checked = json.loads(run("check", "--workspace", str(workspace), "--book-root", str(book_root)).stdout)
        assert checked["project"]["revision"] == 14 and checked["book"]["revision"] == 2 and checked["book"]["name"] == "雾港来信"
        assert checked["drift_warnings"] == []
        book_profile = book_memory / "作者画像.md"
        book_profile.write_text(book_profile.read_text(encoding="utf-8") + "手工污染\n", encoding="utf-8")
        book_soft = json.loads(run("check", "--workspace", str(workspace), "--book-root", str(book_root)).stdout)
        assert len(book_soft["drift_warnings"]) == 1 and "stale or edited" in book_soft["drift_warnings"][0]["message"]
        assert "stale or edited" in run("check", "--workspace", str(workspace), "--book-root", str(book_root), "--strict", expect=2).stderr
        assert json.loads(commit(workspace, input_path, transaction("tx-book-replace", 1, [{
            "action": "replace", "old_ids": ["BP001"],
            "preference": replacement("本书对话可以慢，但不拿台词讲设定", "改一下说法。", scope_level="book", scope_value="雾港来信"),
        }]), "--book-root", str(book_root)).stdout)["replayed"] is True, "幂等重放也要重写快照"
        assert len(state(book_root)["items"]) == 2, "重放不得派生条目"
        run("check", "--workspace", str(workspace), "--book-root", str(book_root), "--strict")

        # 书目录改名后书名以 state 为准，不受目录名影响
        renamed_root = workspace / "长篇" / "雾港来信（改名）"
        book_root.rename(renamed_root)
        renamed = query(workspace, "--kind", "prose_style", "--book-root", str(renamed_root))
        assert [item["id"] for item in renamed["items"]] == ["BP002", "AP007"]
        renamed_root.rename(book_root)

        # ---- 存量迁移：升级前写进项目级的 book 条目不再参与查询与估算，migrate 搬进书目录后才回来 ----
        legacy_workspace = Path(temporary) / "存量工作区"
        legacy_workspace.mkdir()
        legacy_root = legacy_workspace / "长篇" / "甲"
        legacy_root.mkdir(parents=True)
        record(legacy_workspace, input_path, remember("seed-global", preference("全局：动词承重", "记住：动词承重。")))
        record(legacy_workspace, input_path, remember("seed-second", preference("甲书候选：章末留钩子", "记住：章末留个钩子。")))
        legacy_state = state(legacy_workspace)
        # 直改 state 模拟升级前的库：AP002 是甲书 active，AP003 是甲书 conflict（冲突对象是全局 AP001），
        # AP004 是甲书 pending，AP005 是乙书 active。
        template = legacy_state["items"]["AP001"]

        def legacy_item(number: int, value: str, status: str, assertion: str, **fields: Any) -> dict[str, Any]:
            item = json.loads(json.dumps(template, ensure_ascii=False))
            item.update({"id": f"AP{number:03d}", "scope": {"level": "book", "value": value}, "status": status, "assertion": assertion, "confirmation_count": 3, "evidence": [{"quote": f"原话 {number}", "source_ref": None}, {"quote": f"再说一次 {number}", "source_ref": None}]})
            item.update(fields)
            return item

        legacy_state["items"]["AP002"] = legacy_item(2, "甲", "active", "甲书：对话短句推进")
        legacy_state["items"]["AP003"] = legacy_item(3, "甲", "conflict", "甲书：名词承重不用动词", conflicts_with=["AP001"])
        legacy_state["items"]["AP004"] = legacy_item(4, "甲", "pending", "甲书：章末留钩子")
        legacy_state["items"]["AP005"] = legacy_item(5, "乙", "active", "乙书：多用长句")
        legacy_state["next_item_number"] = 6
        save_state(legacy_workspace, legacy_state)
        run("init", "--workspace", str(legacy_workspace))  # 直改 state 后重建派生视图
        run("check", "--workspace", str(legacy_workspace))

        assert [item["id"] for item in query(legacy_workspace, "--kind", "prose_style")["items"]] == ["AP001"], "存量 book 条目不参与查询"
        with_root = query(legacy_workspace, "--kind", "prose_style", "--book-root", str(legacy_root))
        assert [item["id"] for item in with_root["items"]] == ["AP001"] and "book_revision" not in with_root
        seeded_write = json.loads(record(legacy_workspace, input_path, remember("seed-global-2", preference("全局：段尾不抒情", "记住：段尾不抒情。"))).stdout)
        assert seeded_write["warnings"] == [], "存量 book 条目不参与估算"

        migrate_error = run("migrate", "--workspace", str(legacy_workspace), expect=2)
        assert "--book-root" in migrate_error.stderr
        migrated = json.loads(run("migrate", "--workspace", str(legacy_workspace), "--book-root", str(legacy_root)).stdout)
        assert migrated["migrated"] == [{"from": "AP002", "to": "BP001"}, {"from": "AP003", "to": "BP002"}, {"from": "AP004", "to": "BP003"}]
        assert migrated["book"] == "甲" and migrated["revision"] == 3
        moved = state(legacy_root)
        assert moved["book"] == "甲" and moved["state_revision"] == 3, "书级每个源条目一笔事务"
        assert set(moved["applied_transactions"]) == {"migrate:AP002", "migrate:AP003", "migrate:AP004"}
        assert moved["items"]["BP001"]["status"] == "active" and moved["items"]["BP001"]["confirmation_count"] == 3
        assert len(moved["items"]["BP001"]["evidence"]) == 2, "证据随条目搬家"
        assert moved["items"]["BP002"]["status"] == "pending" and moved["items"]["BP002"]["conflicts_with"] == [], "与全局条目的冲突关系不再成立，退回待确认"
        assert moved["items"]["BP003"]["status"] == "pending"
        after = state(legacy_workspace)
        assert all(after["items"][item_id]["status"] == "superseded" for item_id in ("AP002", "AP003", "AP004"))
        assert "BP001" in after["items"]["AP002"]["reason"] and after["items"]["AP002"]["superseded_by"] is None
        assert after["items"]["AP005"]["status"] == "active", "别的书的存量条目不动"
        assert any("迁出 AP002 → BP001" in summary for summary in after["journal"][-1]["summaries"])
        run("check", "--workspace", str(legacy_workspace), "--book-root", str(legacy_root))
        after_query = query(legacy_workspace, "--kind", "prose_style", "--book-root", str(legacy_root))
        assert [item["id"] for item in after_query["items"]] == ["BP001", "AP006", "AP001"], "迁移后书级条目回来；全局条目按最近更新排"
        again = json.loads(run("migrate", "--workspace", str(legacy_workspace), "--book-root", str(legacy_root)).stdout)
        assert again["migrated"] == [] and again["warnings"] == [] and again["revision"] == 3, "没有存量时输出形状不变"
        assert state(legacy_workspace)["state_revision"] == after["state_revision"], "重复 migrate 项目级零写入"
        book_profile_a = memory_dir(legacy_root) / "作者画像.md"
        book_profile_a.write_text(book_profile_a.read_text(encoding="utf-8") + "手工污染\n", encoding="utf-8")
        run("migrate", "--workspace", str(legacy_workspace), "--book-root", str(legacy_root))
        assert "手工污染" not in book_profile_a.read_text(encoding="utf-8"), "重跑 migrate 也要修复派生视图"
        # 没有项目级 store 的工作区：migrate 是空操作而不是报错
        fresh = Path(temporary) / "无项目级"
        (fresh / "长篇" / "书").mkdir(parents=True)
        assert json.loads(run("migrate", "--workspace", str(fresh), "--book-root", str(fresh / "长篇" / "书")).stdout)["migrated"] == []
        assert not memory_dir(fresh / "长篇" / "书").exists()

        # 中途失败重跑：书级已写、项目级没写 → 只补项目级，不重复建 BP。
        # 失败窗口里作者还可能 decide 存量条目，重跑不能因摘要变化锁死。
        b_root = legacy_workspace / "长篇" / "乙"
        b_root.mkdir()
        seeded = state(legacy_workspace)  # 直改 state 模拟升级前写入的乙书条目
        seeded["items"]["AP007"] = legacy_item(7, "乙", "pending", "乙书补充：章末留白")
        seeded["items"]["AP008"] = legacy_item(8, "乙", "active", "乙书补充：少用感叹号")
        seeded["next_item_number"] = 9
        save_state(legacy_workspace, seeded)
        run("init", "--workspace", str(legacy_workspace))
        before_project = state(legacy_workspace)
        run("migrate", "--workspace", str(legacy_workspace), "--book-root", str(b_root))
        assert [item["id"] for item in state(b_root)["items"].values()] == ["BP001", "BP002", "BP003"]
        # 回滚项目级到迁移前，模拟第二步写入失败；窗口里作者确认了 AP007、退役了 AP008
        save_state(legacy_workspace, before_project)
        run("init", "--workspace", str(legacy_workspace))
        window = state(legacy_workspace)  # 窗口里旧版工具确认了 AP007
        window["items"]["AP007"]["status"] = "active"
        save_state(legacy_workspace, window)
        run("init", "--workspace", str(legacy_workspace))
        resumed = json.loads(run("migrate", "--workspace", str(legacy_workspace), "--book-root", str(b_root)).stdout)
        assert resumed["migrated"] == [{"from": "AP005", "to": "BP001"}, {"from": "AP007", "to": "BP002"}, {"from": "AP008", "to": "BP003"}], "重跑复用已建编号，不重复建条，也不因源条目状态变化锁死"
        b_state = state(b_root)
        assert len(b_state["items"]) == 3 and b_state["state_revision"] == 3, "书级零新写入"
        assert b_state["items"]["BP002"]["status"] == "pending", "复用编号的副本保持迁移时的状态，窗口内的确认由作者对副本重做"
        assert all(state(legacy_workspace)["items"][item_id]["status"] == "superseded" for item_id in ("AP005", "AP007", "AP008"))
        run("check", "--workspace", str(legacy_workspace), "--book-root", str(b_root))
        assert [item["id"] for item in query(legacy_workspace, "--kind", "prose_style", "--book-root", str(b_root))["items"]][:2] == ["BP003", "BP001"]
        # 旧版待确认条目不进查询；作者把同一句话再说一次就生效。
        assert "BP002" not in [item["id"] for item in query(legacy_workspace, "--kind", "prose_style", "--book-root", str(b_root))["items"]]
        restated = json.loads(record(legacy_workspace, input_path, remember("restate-legacy-pending", preference(
            "乙书补充：章末留白", "对，章末留白。", scope_level="book", scope_value="乙")), "--book-root", str(b_root)).stdout)
        assert restated["item_ids"] == ["BP002"] and state(b_root)["items"]["BP002"]["status"] == "active"

        # ---- 预算提醒在两级 store 下的口径 ----
        auto_workspace = Path(temporary) / "自动初始化工作区"
        auto_workspace.mkdir()
        auto_result = json.loads(record(auto_workspace, input_path, remember("first-explicit-memory", preference("偏好短标题", "记住：标题短一点。"))).stdout)
        assert auto_result["receipt"] == "Author Memory Receipt: r1 · AP001"
        assert state(auto_workspace)["state_revision"] == 1
        # 预算内的一组照常入库，回执不带提醒
        fitting = transaction(
            "tx-query-budget-fit",
            1,
            [
                {
                    "action": "remember",
                    "preference": preference(
                        f"短偏好 {index}：动词承重，不用被动式。",
                        f"第 {index} 条短偏好。",
                    ),
                }
                for index in range(2)
            ] + [{
                "action": "remember",
                "preference": preference(
                    "悬疑故事优先让线索改变人物关系",
                    "悬疑里我更看重线索对关系的改变。",
                    scope_level="genre",
                    scope_value="悬疑",
                    kind="story_design",
                ),
            }],
        )
        assert json.loads(commit(auto_workspace, input_path, fitting).stdout)["warnings"] == []
        assert query(auto_workspace, "--kind", "prose_style")["omitted_ids"] == []
        matching_design = query(auto_workspace, "--kind", "story_design", "--genre", "悬疑")
        assert [item["id"] for item in matching_design["items"]] == ["AP004"]
        assert query(auto_workspace, "--kind", "story_design", "--genre", "甜宠")["items"] == []
        run("check", "--workspace", str(auto_workspace))

        # 断言超 120 字节降为软提醒（成功落盘并带 warning），不再阻断写入
        long_assertion = transaction(
            "tx-assertion-too-long",
            state(auto_workspace)["state_revision"],
            [{"action": "remember", "preference": preference("长" * 45, "较长断言应给提醒而非硬拦。")}],
        )
        long_res = json.loads(commit(auto_workspace, input_path, long_assertion).stdout)
        assert long_res["ok"] is True
        assert any("120 字节" in w for w in long_res["warnings"]), long_res["warnings"]
        # 清理这条测试偏好，不影响后续预算提醒精确用例
        commit(auto_workspace, input_path, transaction("tx-forget-long", state(auto_workspace)["state_revision"], [{
            "action": "forget", "item_id": long_res["item_ids"][0], "quote": "撤回测试条", "reason": "cleanup",
        }]))

        # 提醒制：把「正文初稿/续写」组合撑到超编的写入照常成功，回执带 warnings
        before_revision = state(auto_workspace)["state_revision"]
        crowding = transaction(
            "tx-query-budget-crowding",
            before_revision,
            [
                {
                    "action": "remember",
                    "preference": preference(
                        f"长偏好{index}：先给动作再给判断，段尾不落抒情句，比喻每场最多留一个。",
                        f"第 {index} 条用于撑满注入预算。",
                    ),
                }
                for index in range(24)
            ],
        )
        crowded = json.loads(commit(auto_workspace, input_path, crowding).stdout)
        assert crowded["warnings"], "超编写入必须携带预算提醒"
        assert any("整理作者记忆" in warning for warning in crowded["warnings"])
        assert state(auto_workspace)["state_revision"] == before_revision + 1

        # 减量清理：超编工作区逐条忘记必须照常成功（拒写制在这里会死锁）
        cleaned = json.loads(record(auto_workspace, input_path, event("cleanup-step-1", {
            "action": "forget",
            "item_id": crowded["item_ids"][0],
            "quote": "这条先退役。",
            "reason": "整理：逐条退役",
        })).stdout)
        assert cleaned["replayed"] is False
        assert cleaned["warnings"], "仍超编时提醒应继续存在，但写入不失败"

        # kind-less 查询直接报错，不再默认返回全部类型
        assert "--kind" in query(auto_workspace, expect=2)["stderr"]

        # 查询排序含 recency：同重要度下最近写入的条目排最前，被略过的是旧条目
        recency_query = query(auto_workspace, "--kind", "prose_style")
        assert len(recency_query["items"]) > 0
        assert recency_query["items"][0]["id"] == crowded["item_ids"][1], "最近写入应排最前（首条已退役）"
        assert recency_query["omitted_ids"], "超编查询必须报漏项"
        assert recency_query["omitted"] == len(recency_query["omitted_ids"])

        # 书级精确计算：写书级条目时提醒按「全局＋本书 store」算，别的书不掺进来；
        # 写项目级条目而传了 --book-root 时同样把这本书算进去。
        ruler_workspace = Path(temporary) / "两书工作区"
        ruler_workspace.mkdir()
        root_a = ruler_workspace / "长篇" / "甲"
        root_b = ruler_workspace / "长篇" / "乙"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        for index in range(3):
            record(ruler_workspace, input_path, remember(f"book-a-{index}", preference(
                f"甲书短偏好{index}", "甲书原话交代来龙去脉，" * 22, scope_level="book", scope_value="甲",
            )), "--book-root", str(root_a))
        for index in range(4):
            record(ruler_workspace, input_path, remember(f"global-{index}", preference(
                f"全局偏好{index}：动词承重不用被动式，段尾不落抒情句，比喻每场只留一个。",
                f"第 {index} 条全局偏好。",
            )))
        last_b = None
        for index in range(16):
            last_b = json.loads(record(ruler_workspace, input_path, remember(f"book-b-{index}", preference(
                f"乙书偏好{index}：情绪落在具体物件上，对话短句推进，收尾用动作不用感叹。",
                f"第 {index} 条乙书偏好。",
                scope_level="book", scope_value="乙",
            )), "--book-root", str(root_b)).stdout)
        assert any("正文初稿" in warning for warning in last_b["warnings"]), "书乙自身超编必须被点名"
        book_a = query(ruler_workspace, "--kind", "prose_style", "--kind", "story_design", "--book-root", str(root_a))
        assert book_a["omitted_ids"] == [] and {item["id"][:2] for item in book_a["items"]} == {"AP", "BP"}, "不同书的记忆不得加在一起算"
        book_b = query(ruler_workspace, "--kind", "prose_style", "--kind", "story_design", "--book-root", str(root_b))
        assert book_b["omitted_ids"], "书乙自身切片超编必须体现在查询漏项"
        # 写项目级条目：不传书目录看不到任何书级 store → 不报；传了乙就把乙算进来
        blind = json.loads(record(ruler_workspace, input_path, remember("global-blind", preference("全局：标题短", "记住：标题短。"))).stdout)
        assert blind["warnings"] == [], "看不到书级 store 时不该凭空报警"
        sighted = json.loads(record(ruler_workspace, input_path, remember("global-sighted", preference("全局：少用感叹号", "记住：少用感叹号。")), "--book-root", str(root_b)).stdout)
        assert sighted["store"] == "project" and any("正文初稿" in warning for warning in sighted["warnings"]), "传了 --book-root 的项目级写入要把这本书算进提醒"

        # 极端超编（直改 state 模拟老库长断言）：漏项全数列出并附首句，注入的行恒 ≤2048、
        # 绝不整包报错；768B 存量断言仍可校验通过
        flood = state(ruler_workspace)
        base_item = json.loads(json.dumps(flood["items"]["AP001"], ensure_ascii=False))
        for number in range(100, 140):
            clone = json.loads(json.dumps(base_item, ensure_ascii=False))
            clone["id"] = f"AP{number}"
            clone["assertion"] = f"直改状态的超长断言{number}：" + "长" * 200
            clone["scope"] = {"level": "global", "value": None}
            flood["items"][f"AP{number}"] = clone
        flood["next_item_number"] = 200
        save_state(ruler_workspace, flood)
        flooded_document = query(ruler_workspace, "--kind", "prose_style")
        assert flooded_document["items"], "跳过不中断——装得下的条目仍应返回"
        assert flooded_document["omitted"] > 20
        assert len(flooded_document["omitted_ids"]) == flooded_document["omitted"], "漏项清单不进 prompt，不再封顶"
        assert set(flooded_document["omitted_summaries"]) == set(flooded_document["omitted_ids"])
        assert sum(len((line + "\n").encode("utf-8")) for line in flooded_document["lines"]) <= 2048

        # ---- 重要度优先：high 全局铁律不得被 low 本书琐事挤出注入预算（本书条目在书级 store） ----
        priority_workspace = Path(temporary) / "重要度工作区"
        priority_root = priority_workspace / "长篇" / "雾港来信"
        priority_root.mkdir(parents=True)
        for index, rule in enumerate((
            "铁律一：绝不写第二人称叙述，任何情况都不破例。",
            "铁律二：未成年角色绝不出现性描写，平台红线。",
        )):
            record(priority_workspace, input_path, remember(f"rule-{index}", preference(rule, f"作者原话：{rule}", importance="high")))
        crowd_out = None
        for index in range(24):
            crowd_out = json.loads(record(priority_workspace, input_path, remember(f"trivia-{index}", preference(
                f"本书临时{index}：这一卷多用短句，场景切换不加过渡段落。",
                f"第 {index} 条本卷临时偏好。",
                scope_level="book", scope_value="雾港来信", importance="low",
            )), "--book-root", str(priority_root)).stdout)
        priority_query = query(priority_workspace, "--kind", "prose_style", "--kind", "story_design", "--book-root", str(priority_root))
        kept_ids = [item["id"] for item in priority_query["items"]]
        assert priority_query["omitted_ids"], "撑满预算后必须有漏项，否则这个用例没在测东西"
        assert "AP001" in kept_ids and "AP002" in kept_ids, "high 全局铁律不得被 low 本书条目挤掉"
        assert all(item_id.startswith("BP") for item_id in priority_query["omitted_ids"]), "先丢的必须是重要度低的条目"
        assert crowd_out["warnings"], "超编写入必须携带提醒"
        assert any("「" in warning for warning in crowd_out["warnings"]), "提醒要带断言首句，只给编号作者无从判断"

        # ---- 注入载荷是契约：执行者只读 lines（断言原文＋编号），items 只带四个字段给主会话判断 ----
        assert all(set(item) == {"id", "kind", "scope", "assertion"} for item in priority_query["items"]), \
            "query items 只带 id/kind/scope/assertion；reason、evidence 等一律不出 store"
        assert priority_query["lines"] == [f"- {item['assertion']}（{item['id']}）" for item in priority_query["items"]], \
            "lines 与 items 一一对应，就是交给执行者的原文"

        # ---- 作者画像.md 必须显示 importance：它是「整理作者记忆」的去留依据 ----
        priority_profile = (memory_dir(priority_workspace) / "作者画像.md").read_text(encoding="utf-8")
        assert "重要 high" in priority_profile, "画像要显示重要度，否则整理时无从判断该退役哪条"
        assert "重要 low" in (memory_dir(priority_root) / "作者画像.md").read_text(encoding="utf-8")

        # ---- 存量长断言：原样重申走强化，不因新上限被拒、也不派生重复条目 ----
        legacy_long_workspace = Path(temporary) / "存量长断言工作区"
        legacy_long_workspace.mkdir()
        legacy_assertion = "存量长断言：" + "以后写对话时别用破折号表示打断改用省略号但叙述里的插入语破折号保留" * 2
        assert len(legacy_assertion.encode("utf-8")) > 120
        record(legacy_long_workspace, input_path, remember("legacy-seed", preference("占位短断言。", "原话。")))
        legacy_long_state = state(legacy_long_workspace)
        legacy_long_state["items"]["AP001"]["assertion"] = legacy_assertion
        save_state(legacy_long_workspace, legacy_long_state)
        reinforced = json.loads(record(legacy_long_workspace, input_path, remember("legacy-restate", preference(legacy_assertion, "作者又说了一遍。"))).stdout)
        assert reinforced["item_ids"] == ["AP001"], "原样重申存量长断言必须强化原条目，不得新建"
        after_legacy = state(legacy_long_workspace)
        assert len(after_legacy["items"]) == 1, "强化路径不得派生重复条目"
        assert after_legacy["items"]["AP001"]["confirmation_count"] == 2
        run("check", "--workspace", str(legacy_long_workspace))
        # CRLF regression: derived views rewritten with \r\n (e.g. git autocrlf=true on Windows) must still pass check
        profile_path = memory_dir(legacy_long_workspace) / "作者画像.md"
        profile_path.write_bytes(profile_path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        run("check", "--workspace", str(legacy_long_workspace))
        new_long = json.loads(record(legacy_long_workspace, input_path, remember("legacy-new-long", preference(legacy_assertion + "再补一句。", "新的长断言。"))).stdout)
        assert new_long["ok"] is True
        assert any("120 字节" in w for w in new_long["warnings"]), "新建长断言应出软提醒而不阻断"

        # ---- 软视图上限（>12KB 作者画像提醒放行）vs 64 KiB 安全硬上限（拒写零落盘） ----
        soft_view_ws = Path(temporary) / "软视图工作区"
        soft_view_ws.mkdir()
        run("init", "--workspace", str(soft_view_ws))
        big_batch = [
            {"action": "remember", "preference": preference(
                f"偏好{i:03d}：" + "叙" * 180,
                f"原话{i}",
            )}
            for i in range(30)
        ]
        soft_view_res = json.loads(commit(soft_view_ws, input_path, transaction("tx-soft-profile", 0, big_batch)).stdout)
        assert soft_view_res["ok"] is True
        assert len((memory_dir(soft_view_ws) / "作者画像.md").read_bytes()) > 12288
        assert any("12288 字节" in w for w in soft_view_res["warnings"]), soft_view_res["warnings"]
        run("check", "--workspace", str(soft_view_ws), "--strict")

        # 超过 65536 字节硬帽必须拒写且零改动
        hit_hard_cap = False
        for batch_idx in range(1, 6):
            rev = state(soft_view_ws)["state_revision"]
            extra_batch = [
                {"action": "remember", "preference": preference(
                    f"超限{batch_idx}-{i:03d}：" + "叙" * 200,
                    f"原话{batch_idx}-{i}",
                )}
                for i in range(25)
            ]
            before_snap = snapshot(memory_dir(soft_view_ws))
            write_json(input_path, transaction(f"tx-hard-{batch_idx}", rev, extra_batch))
            res_proc = subprocess.run(
                [NODE, str(TOOL), "commit", "--workspace", str(soft_view_ws), "--input", str(input_path)],
                cwd=REPO, text=True, encoding="utf-8", capture_output=True, check=False,
            )
            if res_proc.returncode == 2:
                assert "exceeds hard cap of 65536 bytes" in res_proc.stderr, res_proc.stderr
                assert snapshot(memory_dir(soft_view_ws)) == before_snap
                hit_hard_cap = True
                break
            assert res_proc.returncode == 0, res_proc.stderr
        assert hit_hard_cap, "must eventually hit the 65536 bytes hard cap"

        assert_single_root_layout(Path(temporary), input_path)
        assert_book_dir_is_not_single_root(Path(temporary), input_path)
        assert_single_root_case_insensitive_path(Path(temporary), input_path)
        assert_write_lock_blocks_busy_and_serializes_writes(Path(temporary), input_path)
        assert_other_store_failure_is_nonfatal(Path(temporary), input_path)
        assert_no_false_negatives()
        assert_omitted_follow_priority_and_lines_fit()
        assert_slice_weight_uses_rendered_lines()

    # 只锚 prompt 与运行时 CLI / 槽位的对接片段，不钉措辞
    injection_contracts = {
        # 写一章的填槽说明随「只在交给写手时才用」迁到 agent-calls.md（v0.8.2）。
        REPO / "skills/story-long-write/scripts/build_writer_prompt.js": (
            "——— 作者偏好（",
        ),
        # 查到的偏好要进子代理 prompt 的槽位，否则 query 照跑、结果到不了写手。
        # 短篇派写手的 prompt 同样随「只在交给写手时才用」迁到 agent-calls.md（v0.8.2）。
        REPO / "skills/story-short-write/references/agent-calls.md": (
            "作者偏好 query",
            "\n作者偏好：{",
        ),
        # 去味交给写手的 prompt 随「只在交给写手时才用」迁到 agent-calls.md（v0.8.3）。
        REPO / "skills/story-deslop/references/agent-calls.md": (
            "\n作者偏好：{",
        ),
        REPO / "skills/story-short-write/SKILL.md": (
            "query --workspace {工作区} --book-root {项目目录} --kind prose_style --kind story_design",
            "没装下的",
        ),
        # 装不下的习惯要用原话告诉作者（dsh#61）：组装脚本拼好那句话，单章与日更批末汇报模板各有一行接住。
        REPO / "skills/story-long-write/references/workflow-chapter.md": ("习惯没带上",),
        REPO / "skills/story-long-write/references/workflow-daily.md": ("习惯没带上",),
    }
    for path, required_fragments in injection_contracts.items():
        # 单行转义 prompt 与 fenced 多行 prompt 都必须实际传递同一字段。
        content = path.read_text(encoding="utf-8").replace("\\n", "\n")
        for fragment in required_fragments:
            assert fragment in content, f"missing author-memory injection contract in {path}: {fragment}"
    # 只有写作 skill 拥有记忆协议和工具；其他 skill 通过调用方接收裁决。
    owners = ("story-long-write", "story-short-write")
    expected_protocols = {REPO / "skills" / owner / "references" / name
                          for owner in owners
                          for name in ("author-memory.md",)}
    assert set((REPO / "skills").glob("*/references/author-memory*.md")) == expected_protocols
    assert set((REPO / "skills").glob("*/scripts/author_memory_commit.js")) == {
        REPO / "skills" / owner / "scripts/author_memory_commit.js" for owner in owners}
    # #436：写作入口和协议不再引导推断写入。
    for path in sorted(expected_protocols) + [REPO / "skills" / owner / "SKILL.md" for owner in owners]:
        content = path.read_text(encoding="utf-8")
        assert "repeated_correction" not in content and "inferred_pattern" not in content, f"{path} 仍在引导推断写入"
    # 0.10：两份协议合成一份，只锚小节与命令，防止规则被悄悄删掉；待确认、冲突、decide 不再回流。
    for path in sorted(expected_protocols):
        content = path.read_text(encoding="utf-8")
        for fragment in ("## 回执怎么告诉作者", "## 记不记、记成什么", "## 改、忘与整理", "record  --workspace",
                         "query   --workspace", "migrate --workspace", "check   --workspace", "12288"):
            assert fragment in content, f"{path} 缺少作者记忆锚点：{fragment}"
        for gone in ('"status": "pending"', '"action":"decide"', "author-memory-maintenance.md", "技术备注"):
            assert gone not in content, f"{path} 仍引导已删的作者记忆机制：{gone}"

    print("OK: author-memory transaction behavior")


if __name__ == "__main__":
    main()
