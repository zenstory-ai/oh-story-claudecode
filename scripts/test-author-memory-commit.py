#!/usr/bin/env python3
"""Behavior regression for the workspace-level author-memory transaction tool."""

from __future__ import annotations

import json
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
) -> dict[str, Any]:
    return {
        "kind": kind,
        "scope": {"level": scope_level, "value": scope_value},
        "assertion": assertion,
        "quote": quote,
        "source_ref": "test:conversation",
        "source": source,
        "confidence": "high" if source == "explicit_user" else "medium",
        "importance": "high",
        "status": status,
        "reason": "behavior regression evidence",
        "conflicts_with": conflicts_with or [],
    }


def replacement(assertion: str, quote: str) -> dict[str, Any]:
    document = preference(assertion, quote, scope_level="book", scope_value="雾港来信")
    document.pop("status")
    document.pop("conflicts_with")
    return document


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def state(workspace: Path) -> dict[str, Any]:
    path = workspace / ".story" / "作者记忆" / "_author-memory-state.json"
    return json.loads(path.read_text(encoding="utf-8"))


def commit(workspace: Path, input_path: Path, document: dict[str, Any], *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    write_json(input_path, document)
    return run("commit", "--workspace", str(workspace), "--input", str(input_path), expect=expect)


def record(workspace: Path, input_path: Path, document: dict[str, Any], *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    write_json(input_path, document)
    return run("record", "--workspace", str(workspace), "--input", str(input_path), expect=expect)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="author-memory-test-") as temporary:
        workspace = Path(temporary) / "创作工作区"
        workspace.mkdir()
        input_path = Path(temporary) / "transaction.json"
        memory = workspace / ".story" / "作者记忆"

        empty_query = run("query", "--workspace", str(workspace), "--kind", "prose_style")
        assert json.loads(empty_query.stdout)["items"] == []
        assert not memory.exists(), "a read-only query must not initialize author memory"

        init_result = run("init", "--workspace", str(workspace))
        assert json.loads(init_result.stdout)["revision"] == 0
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

        pending = transaction(
            "tx-pending",
            1,
            [{"action": "remember", "preference": preference(
                "倾向用物件细节替代直接心理说明",
                "三次修改都把心理说明换成了桌上的旧物。",
                status="pending",
                source="repeated_correction",
            )}],
        )
        commit(workspace, input_path, pending)
        assert state(workspace)["items"]["AP002"]["status"] == "pending"
        assert "AP002" in (memory / "待确认.md").read_text(encoding="utf-8")

        invalid_inference = transaction(
            "tx-invalid-inference",
            2,
            [{"action": "remember", "preference": preference(
                "推断出的习惯不能直接生效",
                "从成稿里看起来如此。",
                source="inferred_pattern",
            )}],
        )
        before_failure = snapshot(memory)
        error = commit(workspace, input_path, invalid_inference, expect=2)
        assert "must remain pending" in error.stderr
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

        conflict = transaction(
            "tx-conflict",
            3,
            [{"action": "remember", "preference": preference(
                "本书允许更长的试探性对话",
                "这本书对话慢一点，多试探几轮。",
                status="conflict",
                scope_level="book",
                scope_value="雾港来信",
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
                    "本书对话允许更长的试探，但避免解释设定",
                    "这本书可以让对话慢一点，多试探，但还是别拿台词讲设定。",
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
            "本书对话允许更长的试探，但避免解释设定",
            "这本书就按慢对话和少解释继续。",
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

        recorded_preference = preference(
            "全局偏好用具体物件承载情绪",
            "记住：以后尽量让情绪落到具体物件上。",
        )
        record_event = {
            "schema_version": 1,
            "event_id": "conversation-message-42",
            "operation": {"action": "remember", "preference": recorded_preference},
        }
        recorded = json.loads(record(workspace, input_path, record_event).stdout)
        assert recorded["receipt"] == "Author Memory Receipt: r8 · AP005"
        assert recorded["replayed"] is False

        queried = run(
            "query",
            "--workspace", str(workspace),
            "--kind", "prose_style",
            "--book", "雾港来信",
        )
        assert len(queried.stdout.encode("utf-8")) <= 2048
        query_document = json.loads(queried.stdout)
        assert [item["id"] for item in query_document["items"]] == ["AP004", "AP005"]
        assert all(item["id"] not in {"AP001", "AP002", "AP003"} for item in query_document["items"])

        forget_event = {
            "schema_version": 1,
            "event_id": "conversation-message-43",
            "operation": {
                "action": "forget",
                "item_id": "AP005",
                "quote": "这个全局偏好先忘掉。",
                "reason": "author withdrew the newly recorded preference",
            },
        }
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

        auto_workspace = Path(temporary) / "自动初始化工作区"
        auto_workspace.mkdir()
        auto_event = {
            "schema_version": 1,
            "event_id": "first-explicit-memory",
            "operation": {"action": "remember", "preference": preference("偏好短标题", "记住：标题短一点。")},
        }
        auto_result = json.loads(record(auto_workspace, input_path, auto_event).stdout)
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
        fit_query = json.loads(run("query", "--workspace", str(auto_workspace), "--kind", "prose_style").stdout)
        assert fit_query["omitted_ids"] == []
        matching_design = json.loads(run(
            "query", "--workspace", str(auto_workspace),
            "--kind", "story_design", "--genre", "悬疑",
        ).stdout)
        assert [item["id"] for item in matching_design["items"]] == ["AP004"]
        assert json.loads(run(
            "query", "--workspace", str(auto_workspace),
            "--kind", "story_design", "--genre", "甜宠",
        ).stdout)["items"] == []
        run("check", "--workspace", str(auto_workspace))

        # 断言限一句话：写入端超 120 字节直接拒；存量校验仍按 768 兼容（见下方直改 state 的用例）
        long_assertion = transaction(
            "tx-assertion-too-long",
            state(auto_workspace)["state_revision"],
            [{"action": "remember", "preference": preference("长" * 45, "太长的断言应当拆条。")}],
        )
        error = commit(auto_workspace, input_path, long_assertion, expect=2)
        assert "exceeds 120 bytes" in error.stderr

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
        cleanup_event = {
            "schema_version": 1,
            "event_id": "cleanup-step-1",
            "operation": {
                "action": "forget",
                "item_id": crowded["item_ids"][0],
                "quote": "这条先退役。",
                "reason": "整理：逐条退役",
            },
        }
        cleaned = json.loads(record(auto_workspace, input_path, cleanup_event).stdout)
        assert cleaned["replayed"] is False
        assert cleaned["warnings"], "仍超编时提醒应继续存在，但写入不失败"

        # kind-less 查询直接报错，不再默认返回全部类型
        kindless = run("query", "--workspace", str(auto_workspace), expect=2)
        assert "--kind" in kindless.stderr

        # 查询排序含 recency：同重要度下最近写入的条目排最前，被略过的是旧条目
        recency_query = json.loads(run(
            "query", "--workspace", str(auto_workspace), "--kind", "prose_style",
        ).stdout)
        assert len(recency_query["items"]) > 0
        assert recency_query["items"][0]["id"] == crowded["item_ids"][1], "最近写入应排最前（首条已退役）"
        assert recency_query["omitted_ids"], "超编查询必须报漏项"
        assert recency_query["omitted"] == len(recency_query["omitted_ids"])

        # 同一把尺＋跨书不合算：书甲引文重（写作时不读）、书乙断言多而重；
        # 预算提醒必须按写作时真正读到的字段挑最重切片——旧尺子（按完整条目
        # 字节）会挑中甲、漏掉乙的超编；两本书的条目也绝不加在一起算
        ruler_workspace = Path(temporary) / "两书工作区"
        ruler_workspace.mkdir()
        heavy_quote = "甲书原话交代来龙去脉，" * 22
        for index in range(3):
            record(ruler_workspace, input_path, {
                "schema_version": 1,
                "event_id": f"book-a-{index}",
                "operation": {"action": "remember", "preference": preference(
                    f"甲书短偏好{index}", heavy_quote, scope_level="book", scope_value="甲",
                )},
            })
        for index in range(4):
            record(ruler_workspace, input_path, {
                "schema_version": 1,
                "event_id": f"global-{index}",
                "operation": {"action": "remember", "preference": preference(
                    f"全局偏好{index}：动词承重不用被动式，段尾不落抒情句，比喻每场只留一个。",
                    f"第 {index} 条全局偏好。",
                )},
            })
        last_b = None
        for index in range(7):
            last_b = json.loads(record(ruler_workspace, input_path, {
                "schema_version": 1,
                "event_id": f"book-b-{index}",
                "operation": {"action": "remember", "preference": preference(
                    f"乙书偏好{index}：情绪落在具体物件上，对话短句推进，收尾用动作不用感叹。",
                    f"第 {index} 条乙书偏好。",
                    scope_level="book",
                    scope_value="乙",
                )},
            }).stdout)
        assert any("正文初稿" in warning for warning in last_b["warnings"]), "书乙切片超编必须被点名"
        book_a = json.loads(run(
            "query", "--workspace", str(ruler_workspace),
            "--kind", "prose_style", "--kind", "story_design", "--book", "甲",
        ).stdout)
        assert book_a["omitted_ids"] == [], "不同书的记忆不得加在一起算"
        book_b = json.loads(run(
            "query", "--workspace", str(ruler_workspace),
            "--kind", "prose_style", "--kind", "story_design", "--book", "乙",
        ).stdout)
        assert book_b["omitted_ids"], "书乙自身切片超编必须体现在查询漏项"

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
        state_file = ruler_workspace / ".story" / "作者记忆" / "_author-memory-state.json"
        state_file.write_text(json.dumps(flood, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        flooded = run("query", "--workspace", str(ruler_workspace), "--kind", "prose_style")
        assert len(flooded.stdout.encode("utf-8")) <= 2048
        flooded_document = json.loads(flooded.stdout)
        assert flooded_document["items"], "跳过不中断——装得下的条目仍应返回"
        assert flooded_document["omitted"] > 20
        assert len(flooded_document["omitted_ids"]) == 20

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
            "query --kind prose_style",
            "作者偏好：{query 命中的 prose_style 项}",
        ),
        REPO / "skills/story-review/SKILL.md": (
            "query --kind delivery --kind interaction --kind prose_style",
        ),
    }
    for path, required_fragments in injection_contracts.items():
        content = path.read_text(encoding="utf-8")
        for fragment in required_fragments:
            assert fragment in content, f"missing author-memory injection contract in {path}: {fragment}"

    print("OK: author-memory transaction behavior")


if __name__ == "__main__":
    main()
