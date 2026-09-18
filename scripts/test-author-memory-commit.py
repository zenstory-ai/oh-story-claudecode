#!/usr/bin/env python3
"""Behavior regression for the two-level author-memory transaction tool."""

from __future__ import annotations

import importlib.util
import itertools
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "skills" / "story" / "scripts" / "author_memory_commit.py"


def run(*args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(TOOL), *args],
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
    assert len(result.stdout.encode("utf-8")) <= 2048, "query 载荷恒 ≤2048 字节"
    return json.loads(result.stdout)


def load_tool_module() -> Any:
    """就地加载被测脚本。下面几项不变式要在函数级别穷举，走子进程太慢。"""
    spec = importlib.util.spec_from_file_location("author_memory_commit", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_state(generator: random.Random, module: Any, *, book: str | None, books: list[str], genres: list[str], workflows: list[str]) -> dict[str, Any]:
    """合成一份 store：book=None 是项目级（含存量 book 条目），否则是该书的书级 store。"""
    values = {"book": books, "genre": genres, "workflow": workflows}
    prefix = "BP" if book is not None else "AP"
    items = {}
    for number in range(1, generator.randint(1, 30) + 1):
        if book is None:
            level = generator.choice(["global", "global", "book", "genre", "workflow"])
            value = None if level == "global" else generator.choice(values[level])
        else:
            level, value = "book", book
        items[f"{prefix}{number:03d}"] = {
            "id": f"{prefix}{number:03d}",
            "kind": generator.choice(module.KINDS),
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
    """核心不变式：写入回执没给提醒 ⟹ 任何真实 query 都不会漏条。

    这是整套「写入即预警」机制成立的前提。估算与真实查询是两段代码，任何一处
    口径漂移（scope 切片不按 casefold 归并、切片轻重不算 JSON 分隔符、状态过滤
    不一致、项目级存量 book 条目被误算或误返回）都会让作者拿到回执却丢条目——
    正是本机制要消灭的失败模式。固定种子的随机库穷举比任何手工 fixture 都难绕过。
    两级 store 下分别穷举「带书目录」与「不带书目录」两种真实查询。
    """
    module = load_tool_module()
    books = ["甲", "Lucky", "lucky", "LUCKY", "乙"]
    genres = ["悬疑", "Urban", "urban"]
    workflows = ["长篇", "short", "SHORT"]
    generator = random.Random(4290918)

    def real_query_omitted(project_state, book_state, kinds, requested):
        # oracle 就是 command_query 走的那条纯函数路径（merged_query），不是在测试里
        # 再实现一遍查询——否则估算与「真实查询」同源，信封少算一个字段也测不出。
        return module.merged_query(project_state, book_state, set(kinds), requested)[1]

    warned_libraries = 0
    for _ in range(300):
        project_state = synthetic_state(generator, module, book=None, books=books, genres=genres, workflows=workflows)
        visible_book = generator.choice(books + [None])
        book_state = None if visible_book is None else synthetic_state(generator, module, book=visible_book, books=books, genres=genres, workflows=workflows)
        warnings = module.query_budget_warnings(project_state, book_state)
        warned_libraries += any("最坏查询" in warning for warning in warnings)
        for task, kinds in module.QUERY_COMBOS.items():
            if any(f"「{task}」" in warning for warning in warnings):
                continue
            for genre, workflow in itertools.product(genres + [None], workflows + [None]):
                requested = {"genre": genre, "workflow": workflow}
                for visible in ([book_state] if book_state is not None else []) + [None]:
                    omitted = real_query_omitted(project_state, visible, set(kinds), requested)
                    assert not omitted, (
                        f"写入端没提醒「{task}」，但 query(book_root={'有' if visible else '无'}, genre={genre}, workflow={workflow}) "
                        f"漏了 {omitted}——估算与真实查询不是同一把尺"
                    )
    assert warned_libraries > 20, "随机库里触发提醒的太少，这个属性测试没覆盖到超编区间"


def assert_slice_weight_counts_separators() -> None:
    """挑「最重切片」必须按真实载荷占位算，即 compact 字节＋每条的 JSON 分隔符。

    只比字节和会挑错：条目多、单条短的切片字节和更小，实际占位却更大，于是
    估算判「装得下」而真实查询溢出——warnings 假阴性。下面的老库 fixture
    （题材甲 4 条各 381 字节的存量长断言 vs 题材乙 10 条各 92 字节）两把尺子挑的
    切片不同，且只有乙会溢出。
    """
    module = load_tool_module()

    def sized(number: str, value: str, byte_length: int) -> dict[str, Any]:
        full, remainder = divmod(byte_length, 3)
        return {
            "id": number, "kind": "prose_style",
            "scope": {"level": "genre", "value": value},
            "assertion": "文" * full + "x" * remainder, "status": "active",
            "importance": "medium", "updated_revision": 400, "confirmation_count": 1,
        }

    items = {}
    for index in range(4):
        items[f"AP{index + 1:03d}"] = sized(f"AP{index + 1:03d}", "甲", 381)
    for index in range(10):
        items[f"AP{index + 100:03d}"] = sized(f"AP{index + 100:03d}", "乙", 92)
    heavy = [item for item in items.values() if item["scope"]["value"] == "甲"]
    many = [item for item in items.values() if item["scope"]["value"] == "乙"]
    assert sum(map(module.compact_bytes, heavy)) > sum(map(module.compact_bytes, many)), \
        "fixture 前提：甲的字节和更大（旧尺子会挑甲）"
    assert module.slice_weight(heavy) < module.slice_weight(many), \
        "fixture 前提：乙的真实占位更大（新尺子必须挑乙）"
    assert not module.fit_items(sorted(heavy, key=module.query_sort_key), 700)[1], "甲自己装得下"
    assert module.fit_items(sorted(many, key=module.query_sort_key), 700)[1], "乙自己会溢出"
    warnings = module.query_budget_warnings({"items": items, "state_revision": 700, "journal": []}, None)
    assert any("最坏查询" in warning for warning in warnings), "挑错切片会让超编的乙被漏报——切片轻重必须算上列表分隔符"


def assert_omitted_ids_follow_priority() -> None:
    """omitted_ids 恒按候选优先级排序，不按被丢弃的先后。

    收尾回吐的条目优先级高于循环里跳过的那些；按丢弃先后排会把它追加到末尾，
    正好被 OMITTED_IDS_MAX 的封顶切掉——作者看到的漏项清单里，最该整理的那条
    反而不见了。下面的 fixture 恰好让回吐触发且漏项超过 20 条。
    """
    module = load_tool_module()
    items = [{
        "id": f"AP{number:03d}",
        "kind": "prose_style",
        "scope": {"level": "global", "value": None},
        "assertion": "文" * 25,
        "importance": "medium",
        "updated_revision": 100 - number,
        "confirmation_count": 1,
    } for number in range(1, 31)]
    items.sort(key=module.query_sort_key)
    result, omitted = module.fit_items([dict(item) for item in items], 500)
    order = {item["id"]: index for index, item in enumerate(items)}
    assert len(omitted) > module.OMITTED_IDS_MAX, "fixture 必须漏到封顶以上，否则测不到截断"
    assert len(result["items"]) + result["omitted"] == len(items), "条目守恒"
    assert omitted == sorted(omitted, key=order.__getitem__), "漏项必须按候选优先级排序"
    assert result["omitted_ids"] == sorted(omitted, key=order.__getitem__)[:module.OMITTED_IDS_MAX], \
        "omitted_ids 报的必须是优先级最高的那批——回吐的条目不得被封顶切掉"
    assert result["omitted"] == len(omitted), "omitted 保留真实总数"


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
            "待确认.md",
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

        # ---- #436：pending 只剩一种来源——作者原话范围含糊；推断管道不再写入 ----
        pending = transaction(
            "tx-pending",
            1,
            [{"action": "remember", "preference": preference(
                "倾向用物件细节替代直接心理说明",
                "心理活动……大概还是落到东西上比较好吧。",
                status="pending",
            )}],
        )
        commit(workspace, input_path, pending)
        assert state(workspace)["items"]["AP002"]["status"] == "pending"
        assert "AP002" in (memory / "待确认.md").read_text(encoding="utf-8")

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

        decide = transaction(
            "tx-decide",
            2,
            [{
                "action": "decide",
                "item_id": "AP002",
                "decision": "activate",
                "quote": "对，这也是我的长期习惯。",
                "reason": "author confirmed the candidate",
            }],
        )
        commit(workspace, input_path, decide)
        assert state(workspace)["items"]["AP002"]["status"] == "active"

        # 同 store 内的冲突候选：全局新说法与 AP001 矛盾，先记 conflict
        conflict = transaction(
            "tx-conflict",
            3,
            [{"action": "remember", "preference": preference(
                "允许更长的试探性对话",
                "以后对话慢一点，多试探几轮。",
                status="conflict",
                conflicts_with=["AP001"],
            )}],
        )
        commit(workspace, input_path, conflict)
        assert state(workspace)["items"]["AP003"]["status"] == "conflict"

        illegal_activation = transaction(
            "tx-illegal-conflict-activation",
            4,
            [{
                "action": "decide",
                "item_id": "AP003",
                "decision": "activate",
                "quote": "启用它。",
                "reason": "must still use replace",
            }],
        )
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, illegal_activation, expect=2)
        assert "must be activated with replace" in error.stderr
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
        check_error = run("check", "--workspace", str(workspace), expect=2)
        assert "stale or edited" in check_error.stderr
        replay = commit(workspace, input_path, reinforce)
        assert json.loads(replay.stdout)["replayed"] is True
        run("check", "--workspace", str(workspace))
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
            "tx-active", "tx-pending", "tx-decide", "tx-conflict", "tx-replace", "tx-forget", "tx-reinforce",
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
        assert {path.name for path in book_memory.iterdir()} == {"_author-memory-state.json", "作者画像.md", "待确认.md", "变更记录.md"}
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
        assert "同一 store" in error.stderr and "本书例外" in error.stderr
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

        # check 同时核对两级；书级画像被手改能查出
        checked = json.loads(run("check", "--workspace", str(workspace), "--book-root", str(book_root)).stdout)
        assert checked["project"]["revision"] == 14 and checked["book"]["revision"] == 2 and checked["book"]["name"] == "雾港来信"
        book_profile = book_memory / "作者画像.md"
        book_profile.write_text(book_profile.read_text(encoding="utf-8") + "手工污染\n", encoding="utf-8")
        assert "stale or edited" in run("check", "--workspace", str(workspace), "--book-root", str(book_root), expect=2).stderr
        assert json.loads(commit(workspace, input_path, transaction("tx-book-replace", 1, [{
            "action": "replace", "old_ids": ["BP001"],
            "preference": replacement("本书对话可以慢，但不拿台词讲设定", "改一下说法。", scope_level="book", scope_value="雾港来信"),
        }]), "--book-root", str(book_root)).stdout)["replayed"] is True, "幂等重放也要重写快照"
        assert len(state(book_root)["items"]) == 2, "重放不得派生条目"
        run("check", "--workspace", str(workspace), "--book-root", str(book_root))

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
        record(legacy_workspace, input_path, remember("seed-pending", preference("甲书候选：章末留钩子", "这本书章末……留个钩子吧。", status="pending")))
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
        record(legacy_workspace, input_path, event("window-decide", {"action": "decide", "item_id": "AP007", "decision": "activate", "quote": "对。", "reason": "窗口内确认"}))
        resumed = json.loads(run("migrate", "--workspace", str(legacy_workspace), "--book-root", str(b_root)).stdout)
        assert resumed["migrated"] == [{"from": "AP005", "to": "BP001"}, {"from": "AP007", "to": "BP002"}, {"from": "AP008", "to": "BP003"}], "重跑复用已建编号，不重复建条，也不因源条目状态变化锁死"
        b_state = state(b_root)
        assert len(b_state["items"]) == 3 and b_state["state_revision"] == 3, "书级零新写入"
        assert b_state["items"]["BP002"]["status"] == "pending", "复用编号的副本保持迁移时的状态，窗口内的确认由作者对副本重做"
        assert all(state(legacy_workspace)["items"][item_id]["status"] == "superseded" for item_id in ("AP005", "AP007", "AP008"))
        run("check", "--workspace", str(legacy_workspace), "--book-root", str(b_root))
        assert [item["id"] for item in query(legacy_workspace, "--kind", "prose_style", "--book-root", str(b_root))["items"]][:2] == ["BP003", "BP001"]

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

        # 断言限一句话：新建条目超 120 字节直接拒（存量条目的强化不受此限，见下方用例）
        long_assertion = transaction(
            "tx-assertion-too-long",
            state(auto_workspace)["state_revision"],
            [{"action": "remember", "preference": preference("长" * 45, "太长的断言应当拆条。")}],
        )
        error = commit(auto_workspace, input_path, long_assertion, expect=2)
        assert "超出 120 字节上限" in error.stderr
        assert "强化" in error.stderr, "报错要告诉 agent 重申老条目该怎么走"

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
                for index in range(12)
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
        for index in range(7):
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

        # omitted_ids 封顶：极端超编（直改 state 模拟老库长断言）保留真实总数、
        # 列表最多 20 条，载荷恒 ≤2048、绝不整包报错；768B 存量断言仍可校验通过
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
        assert len(flooded_document["omitted_ids"]) == 20

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
        for index in range(14):
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

        # ---- 注入载荷字段集是契约：多一个字段就多占 prompt 预算 ----
        assert all(set(item) == {"id", "kind", "scope", "assertion"} for item in priority_query["items"]), \
            "query 载荷只带 id/kind/scope/assertion；reason、evidence 等一律不进 prompt"

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
        new_long = record(legacy_long_workspace, input_path, remember("legacy-new-long", preference(legacy_assertion + "再补一句。", "新的长断言。")), expect=2)
        assert "超出 120 字节上限" in new_long.stderr, "新建条目仍受一句话上限约束"

        assert_no_false_negatives()
        assert_omitted_ids_follow_priority()
        assert_slice_weight_counts_separators()

    injection_contracts = {
        REPO / "skills/story-long-write/references/workflow-chapter.md": (
            "`author_preferences`",
            "作者偏好：{本章 query 命中的 prose_style/story_design 项}",
            "不逐条展示或最大化命中",
        ),
        REPO / "skills/story-short-write/references/workflow-draft.md": (
            "作者偏好 query 中的文风/故事设计项",
        ),
        REPO / "skills/story-short-write/references/workflow-revision.md": (
            "作者偏好：{query 命中的 prose_style/story_design 项}",
        ),
        REPO / "skills/story-deslop/SKILL.md": (
            "query --kind prose_style --book-root",
            "作者偏好：{query 命中的 prose_style 项}",
        ),
        REPO / "skills/story-review/SKILL.md": (
            "query --kind delivery --kind interaction --kind prose_style --book-root",
        ),
        REPO / "skills/story-short-write/SKILL.md": (
            "query --kind prose_style --kind story_design --book-root",
        ),
    }
    for path, required_fragments in injection_contracts.items():
        content = path.read_text(encoding="utf-8")
        for fragment in required_fragments:
            assert fragment in content, f"missing author-memory injection contract in {path}: {fragment}"
    # #436：文档不再引导推断写入
    for path in sorted((REPO / "skills").glob("*/references/author-memory.md")) + [REPO / "skills/story/SKILL.md", REPO / "skills/story-review/SKILL.md", REPO / "skills/story-deslop/SKILL.md"]:
        content = path.read_text(encoding="utf-8")
        assert "repeated_correction" not in content and "inferred_pattern" not in content, f"{path} 仍在引导推断写入"
        assert "推断先待确认" not in content and "推断和重复修正先进入待确认" not in content and "重复修正/推断先待确认" not in content, f"{path} 仍在引导推断写入"

    print("OK: author-memory transaction behavior")


if __name__ == "__main__":
    main()
