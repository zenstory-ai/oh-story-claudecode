#!/usr/bin/env python3
"""Behavioral regression tests for the single-authority tracking state tool."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/story-long-write/scripts/tracking_commit.py"
STORYCTL = ROOT / "skills/story-long-write/scripts/storyctl.py"
STORYCTL_SPEC = importlib.util.spec_from_file_location("storyctl_tracking_tests", STORYCTL)
assert STORYCTL_SPEC and STORYCTL_SPEC.loader
storyctl = importlib.util.module_from_spec(STORYCTL_SPEC)
STORYCTL_SPEC.loader.exec_module(storyctl)


def position(*, volume: str = "第一卷·军宣整顿", start: int = 1) -> dict[str, object]:
    return {
        "volume": volume,
        "volume_start_chapter": start,
        "story_time": "实弹训练两天后",
        "scene": "火箭军文工团高层看片会",
    }


def initial_document(
    *,
    last_chapter: int = 0,
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "book_title": "让你管账号，你高燃混剪炸全网",
        "last_chapter": last_chapter,
        "context": {
            "position": position(),
            "long_term_constraints": ["军方培养江晨的后续安排尚未向读者揭示。"],
            "active_character_names": [],
            "continuity_risks": [],
            "recent_chapters": [
                {"chapter": chapter, "summary": f"第{chapter}章军宣账号继续扩大影响。"}
                for chapter in range(max(1, last_chapter - 2), last_chapter + 1)
            ],
            "next_chapter_commitments": ["推进五天百万粉任务。"] if last_chapter else [],
        },
        "character_snapshots": {},
        "foreshadow": [],
        "timeline_events": [],
    }
    return document


def snapshot(*, state: str = "军内认可继续抬升", items: int = 1, repeat: int = 1) -> dict[str, object]:
    phrases = {
        "abilities_resources": "老兵采访授权与军宣制作资源仍需继续使用",
        "relationships": "与钟嘉嘉及文工团的协作关系影响下一阶段决策",
        "knowledge": "已经确认军宣流程和作品传播结果",
        "open_threads": "尚未回收的培养安排与作品计划仍需推进",
    }
    return {
        "identity": "火箭军文工团宣传兵",
        "location": "火箭军文工团高层看片会",
        "goal": "完成五天百万粉任务",
        "state": state,
        **{
            field: [f"第{index + 1}项：{phrase * repeat}" for index in range(items)]
            for field, phrase in phrases.items()
        },
    }


def transaction(
    chapter: int,
    *,
    mode: str = "append",
    character: bool = False,
    foreshadow: bool = False,
    timeline: bool = False,
    next_commitment: str = "结算百万粉任务并承接老兵主题。",
) -> dict[str, object]:
    character_changes = [{"name": "江晨", "change": "作品价值获军内高层确认"}] if character else []
    foreshadow_changes = (
        [
            {
                "action": "upsert",
                "id": "F027",
                "summary": "专业团队仍拍不出江晨原版的灵魂。",
                "planted_chapter": chapter,
                "planned_resolution_chapter": chapter + 8,
                "status": "已埋",
                "importance": "高",
            }
        ]
        if foreshadow
        else []
    )
    timeline_events = (
        [
            {
                "action": "upsert",
                "id": "E010",
                "story_time": "实弹训练两天后",
                "objective_fact": "军方培养江晨另有尚未公开的后续安排。",
                "reader_knowledge": "读者只知道专业重拍版被否决，不知道后续培养安排。",
                "reveal_status": "未揭示",
                "reveal_chapter": None,
                "characters": ["江晨", "钟嘉嘉"],
            }
        ]
        if timeline
        else []
    )
    return {
        "schema_version": 1,
        "mode": mode,
        "chapter": chapter,
        "chapter_title": f"军宣爆款·{chapter}",
        "delta": {
            "result": f"江晨在第{chapter}章继续扩大军宣作品影响力。",
            "character_changes": character_changes,
            "foreshadow_changes": foreshadow_changes,
            "timeline_events": timeline_events,
            "constraints": [],
            "next_chapter_commitments": [next_commitment],
        },
        "context": {
            "position": position(),
            "long_term_constraints": ["军方培养江晨的后续安排尚未向读者揭示。"],
            "active_character_names": ["江晨"] if character else [],
            "continuity_risks": [],
        },
        "character_snapshots": {"江晨": snapshot()} if character else {},
    }


def load_tool_module():
    spec = importlib.util.spec_from_file_location("tracking_commit_under_test", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TrackingCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "让你管账号，你高燃混剪炸全网"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_tool(
        self,
        command: str,
        document: dict[str, object] | None = None,
        *,
        expect: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        args = [sys.executable, str(TOOL), command, "--project", str(self.project)]
        if document is not None:
            document = json.loads(json.dumps(document, ensure_ascii=False))
            if command == "commit" and "expected_state_revision" not in document:
                document["expected_state_revision"] = self.read_state()["state_revision"]
            input_path = Path(self.temporary.name) / f"{command}-{os.urandom(4).hex()}.json"
            input_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            args.extend(["--input", str(input_path)])
        # 工具按 UTF-8 直写字节；text=True 默认按 locale 解码，Windows 的 cp1252
        # 会在读中文提示时 UnicodeDecodeError，必须显式指定 UTF-8。
        completed = subprocess.run(
            args, text=True, capture_output=True, check=False, encoding="utf-8"
        )
        self.assertEqual(
            completed.returncode,
            expect,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        return completed

    def init(self, *, last_chapter: int = 0) -> None:
        self.run_tool(
            "init",
            initial_document(last_chapter=last_chapter),
        )

    def write_chapter_contract(self, chapter: int, *, actual: int = 800, target: int = 1000) -> bytes:
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "正文").mkdir(exist_ok=True)
        width = max(3, len(str(chapter)))
        (self.project / "大纲" / f"细纲_第{chapter:0{width}d}章.md").write_text(
            f"- 字数目标：{target} 字\n- 字数口径：visible_chars_v1\n",
            encoding="utf-8",
        )
        body = ("# 标题\n" + "字" * actual + "。\n").encode("utf-8")
        (self.project / "正文" / f"第{chapter:0{width}d}章_测试.md").write_bytes(body)
        return body

    def bind_wordcount(
        self,
        document: dict[str, object],
        *,
        resolution: str = "accepted_current_length",
    ) -> dict[str, object]:
        chapter = int(document["chapter"])
        if "expected_state_revision" not in document:
            document["expected_state_revision"] = self.read_state()["state_revision"]
        document["wordcount"] = storyctl.build_project_wordcount_record(
            self.project,
            chapter,
            resolution=resolution,
        )
        return document

    def read_state(self) -> dict[str, object]:
        return json.loads((self.project / "追踪/_tracking-state.json").read_text(encoding="utf-8"))

    def test_init_creates_one_structured_authority_and_only_derived_views(self) -> None:
        self.init()
        tracking = self.project / "追踪"
        state = self.read_state()

        self.assertEqual(state["schema_version"], 4)
        self.assertEqual(state["state_revision"], 0)
        self.assertEqual(state["characters"], {})
        self.assertEqual(state["foreshadow"], {})
        self.assertEqual(state["timeline"], {})
        self.assertEqual(state["wordcount_records"], {})
        self.assertNotIn("wordcount_policy", state)
        self.assertNotIn("wordcount_events", state)
        self.assertFalse((tracking / "_tracking-meta.json").exists())
        self.assertFalse((tracking / "时间线/事件库.json").exists())
        self.assertIn("状态修订：0", (tracking / "上下文.md").read_text(encoding="utf-8"))
        self.run_tool("check")

    def test_commit_updates_state_and_all_demo_derived_views(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, character=True, foreshadow=True, timeline=True))
        tracking = self.project / "追踪"
        state = self.read_state()

        self.assertEqual(state["last_committed_chapter"], 1)
        self.assertEqual(state["state_revision"], 1)
        self.assertIn("江晨", state["characters"])
        self.assertIn("F027", state["foreshadow"])
        self.assertIn("E010", state["timeline"])
        self.assertIn("状态修订：1", (tracking / "上下文.md").read_text(encoding="utf-8"))
        self.assertIn("F027｜专业团队仍拍不出江晨原版的灵魂", (tracking / "上下文.md").read_text(encoding="utf-8"))
        self.assertIn("军方培养江晨另有尚未公开的后续安排", (tracking / "时间线/作者真相.md").read_text(encoding="utf-8"))
        self.assertNotIn("军方培养江晨另有尚未公开的后续安排", (tracking / "时间线/读者已知.md").read_text(encoding="utf-8"))
        self.assertTrue((tracking / "逐章记录/第001章.md").exists())
        self.run_tool("check")

    def test_simple_wordcount_record_commits_the_exact_current_body(self) -> None:
        self.init()
        original = self.write_chapter_contract(1, actual=800, target=1000)
        document = self.bind_wordcount(transaction(1))

        self.run_tool("commit", document)

        state = self.read_state()
        self.assertEqual(state["last_committed_chapter"], 1)
        self.assertEqual(state["state_revision"], 1)
        record = state["wordcount_records"]["1"]
        self.assertEqual(
            set(record),
            {"metric", "target", "actual", "status", "resolution", "body_sha256"},
        )
        self.assertEqual(record["status"], "under")
        self.assertEqual(record["resolution"], "accepted_current_length")
        self.assertEqual((self.project / "正文/第001章_测试.md").read_bytes(), original)
        self.run_tool("check")

    def test_body_or_target_change_rejects_a_prepared_record_without_writes(self) -> None:
        self.init()
        original_body = self.write_chapter_contract(1, actual=800, target=1000)
        document = self.bind_wordcount(transaction(1))
        before = self.read_state()

        body_path = self.project / "正文/第001章_测试.md"
        body_path.write_bytes(original_body + "变".encode("utf-8"))
        changed_body = self.run_tool("commit", document, expect=2)
        self.assertIn("wordcount record is stale", changed_body.stderr)
        self.assertEqual(self.read_state(), before)

        body_path.write_bytes(original_body)
        (self.project / "大纲/细纲_第001章.md").write_text(
            "- 字数目标：1100 字\n- 字数口径：visible_chars_v1\n", encoding="utf-8"
        )
        changed_target = self.run_tool("commit", document, expect=2)
        self.assertIn("wordcount record is stale", changed_target.stderr)
        self.assertEqual(self.read_state(), before)

    def test_two_concurrent_different_commits_advance_only_one_revision(self) -> None:
        self.init()
        self.write_chapter_contract(1, actual=800, target=1000)
        first = self.bind_wordcount(transaction(1, next_commitment="A"))
        second = self.bind_wordcount(transaction(1, next_commitment="B"))

        paths = []
        for index, document in enumerate((first, second), start=1):
            path = Path(self.temporary.name) / f"concurrent-{index}.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            paths.append(path)
        processes = [
            subprocess.Popen(
                [sys.executable, str(TOOL), "commit", "--project", str(self.project), "--input", str(path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
            )
            for path in paths
        ]
        results = [process.communicate(timeout=20) + (process.returncode,) for process in processes]

        self.assertEqual(sorted(result[2] for result in results), [0, 2], results)
        state = self.read_state()
        self.assertEqual(state["state_revision"], 1)
        self.assertEqual(set(state["wordcount_records"]), {"1"})
        self.assertEqual(len(list((self.project / "追踪/逐章记录").glob("第001章.md"))), 1)

    def test_character_snapshot_lists_are_not_limited_to_eight_items(self) -> None:
        self.init()
        document = transaction(1, character=True)
        document["character_snapshots"]["江晨"] = snapshot(items=12)

        completed = self.run_tool("commit", document)

        self.assertNotIn("at most 8 items", completed.stderr)
        self.assertEqual(len(self.read_state()["characters"]["江晨"]["relationships"]), 12)
        self.run_tool("check")

    def test_snapshot_target_warns_and_hard_cap_rejects_before_any_write(self) -> None:
        self.init()
        warning = transaction(1, character=True)
        warning["character_snapshots"]["江晨"] = snapshot(items=12, repeat=2)
        completed = self.run_tool("commit", warning)
        self.assertIn("WARNING: character snapshot 江晨", completed.stderr)
        self.assertEqual(self.read_state()["state_revision"], 1)

        rejected = transaction(2, character=True)
        rejected["character_snapshots"]["江晨"] = snapshot(items=24, repeat=4)
        before = json.loads(json.dumps(self.read_state(), ensure_ascii=False))
        completed = self.run_tool("commit", rejected, expect=2)
        self.assertIn("hard cap of 8192 bytes", completed.stderr)
        self.assertEqual(self.read_state(), before)
        self.assertFalse((self.project / "追踪/逐章记录/第002章.md").exists())

    def test_missing_active_snapshot_is_rejected_before_any_write(self) -> None:
        self.init()
        document = transaction(1)
        document["context"]["active_character_names"] = ["不存在的核心角色"]
        before = self.read_state()

        result = self.run_tool("commit", document, expect=2)

        self.assertIn("has no current snapshot", result.stderr)
        self.assertEqual(self.read_state(), before)
        self.assertFalse((self.project / "追踪/逐章记录/第001章.md").exists())

    def test_partial_view_write_keeps_old_authority_and_same_transaction_can_retry(self) -> None:
        self.init()
        module = load_tool_module()
        document = transaction(1, character=True, foreshadow=True, timeline=True)
        document["expected_state_revision"] = 0
        original = module.atomic_write_text

        def fail_on_foreshadow(path: Path, payload: str) -> None:
            if path.name == "伏笔.md":
                raise OSError("injected derived-view failure")
            original(path, payload)

        module.atomic_write_text = fail_on_foreshadow
        with self.assertRaises(OSError):
            module.apply_transaction(self.project, document)

        self.assertEqual(self.read_state()["state_revision"], 0)
        self.assertIn("状态修订：1", (self.project / "追踪/上下文.md").read_text(encoding="utf-8"))
        self.run_tool("check", expect=2)

        module.atomic_write_text = original
        module.apply_transaction(self.project, document)
        self.assertEqual(self.read_state()["state_revision"], 1)
        self.run_tool("check")

    def test_stale_revision_cannot_overwrite_newer_state(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, foreshadow=True, timeline=True))
        stale = transaction(1, mode="revision", foreshadow=True, timeline=True)
        stale["expected_state_revision"] = 1
        self.run_tool("commit", transaction(2))

        result = self.run_tool("commit", stale, expect=2)

        self.assertIn("tracking state changed", result.stderr)
        self.assertEqual(self.read_state()["last_committed_chapter"], 2)
        self.assertEqual(self.read_state()["state_revision"], 2)

    def test_old_revision_preserves_current_next_chapter_commitment(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, next_commitment="让专业团队进场重拍。"))
        self.run_tool("commit", transaction(2, next_commitment="等待高层看片结论。"))
        self.run_tool("commit", transaction(3, next_commitment="结算五天百万粉任务。"))
        self.run_tool("commit", transaction(1, mode="revision", next_commitment="修订章当时的旧承诺。"))

        context = (self.project / "追踪/上下文.md").read_text(encoding="utf-8")
        self.assertIn("结算五天百万粉任务", context)
        self.assertNotIn("修订章当时的旧承诺", context)

    def test_old_revision_applies_current_rows_without_moving_update_chapter_back(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, foreshadow=True, timeline=True))
        chapter_two = transaction(2, foreshadow=True, timeline=True)
        chapter_two["delta"]["foreshadow_changes"][0].update(
            planted_chapter=1,
            planned_resolution_chapter=2,
            status="已回收",
            summary="专业版缺少灵魂的判断已经由高层拍板兑现。",
        )
        chapter_two["delta"]["timeline_events"][0]["reader_knowledge"] = "读者已经看到张耀祖采用江晨原版。"
        self.run_tool("commit", chapter_two)

        revision = transaction(1, mode="revision", foreshadow=True, timeline=True)
        revision["delta"]["foreshadow_changes"][0].update(
            planted_chapter=1,
            planned_resolution_chapter=2,
            status="已回收",
            summary="专业版缺少灵魂的判断已经由高层拍板兑现。",
        )
        revision["delta"]["timeline_events"][0]["reader_knowledge"] = "读者已经看到张耀祖采用江晨原版。"
        self.run_tool("commit", revision)

        state = self.read_state()
        self.assertEqual(state["foreshadow"]["F027"]["updated_chapter"], 2)
        self.assertEqual(state["timeline"]["E010"]["updated_chapter"], 2)
        self.run_tool("check")

    def test_imported_cutoff_requires_only_new_daily_records(self) -> None:
        self.init(last_chapter=27)
        self.run_tool("commit", transaction(28, character=True))
        tracking = self.project / "追踪"

        self.assertFalse((tracking / "逐章记录/第027章.md").exists())
        self.assertTrue((tracking / "逐章记录/第028章.md").exists())
        self.assertEqual(self.read_state()["imported_through_chapter"], 27)
        self.run_tool("check")

    def test_imported_chapter_revision_creates_an_overlay_record(self) -> None:
        self.init(last_chapter=20)
        self.run_tool("commit", transaction(10, mode="revision"))
        self.assertTrue((self.project / "追踪/逐章记录/第010章.md").exists())
        self.assertEqual(self.read_state()["imported_through_chapter"], 20)
        self.run_tool("check")

    def test_check_compares_derived_views_to_state_without_parsing_markdown(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, character=True, foreshadow=True, timeline=True))
        tracking = self.project / "追踪"

        path = tracking / "角色状态/江晨.md"
        path.write_text("# 任意手改格式\n", encoding="utf-8")
        result = self.run_tool("check", expect=2)
        self.assertIn("derived view differs from _tracking-state.json", result.stderr)

        self.run_tool("commit", transaction(2))
        self.run_tool("check")

    def test_check_rejects_orphan_character_file(self) -> None:
        self.init()
        orphan = self.project / "追踪/角色状态/CONFLICT.md"
        orphan.write_text("# orphan\n", encoding="utf-8")
        result = self.run_tool("check", expect=2)
        self.assertIn("character snapshot files differ", result.stderr)

    def test_draft_prefills_current_context_so_only_the_delta_is_written(self) -> None:
        self.init()
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "大纲" / "细纲_第001章.md").write_text("### 第 1 章：看片会\n", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"],
            text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        guide = json.loads(completed.stdout)
        draft_path = Path(guide["draft"])
        self.assertEqual(draft_path, self.project / ".story/work/第001章/tracking.json")
        self.assertEqual(guide["mode"], "append")
        self.assertEqual(guide["limits_chars"]["delta.result"], 160)
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(draft["chapter_title"], "看片会")
        self.assertEqual(draft["expected_state_revision"], self.read_state()["state_revision"])
        self.assertEqual(draft["context"]["long_term_constraints"],
                         self.read_state()["context"]["long_term_constraints"])
        # 新章的故事时间与场景不沿用上一章：留空，逼着按本章结尾填；上一章的值另给参考。
        previous = self.read_state()["context"]["position"]
        self.assertEqual((draft["context"]["position"]["story_time"], draft["context"]["position"]["scene"]), ("", ""))
        self.assertEqual(guide["previous_position"], {"story_time": previous["story_time"], "scene": previous["scene"]})
        self.assertEqual(draft["context"]["position"]["volume"], previous["volume"])
        draft["delta"]["result"] = "江晨在看片会上保住了原版。"
        self.run_tool("commit", draft, expect=2)
        self.assertEqual(self.read_state()["last_committed_chapter"], 0)
        draft["context"]["position"].update({"story_time": "看片会当晚", "scene": "剪辑室"})
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        # 重跑 draft 只刷新修订号，不冲掉已填内容。
        again = subprocess.run(
            [sys.executable, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"],
            text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("原样保留", json.loads(again.stdout)["fill"])
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(draft["delta"]["result"], "江晨在看片会上保住了原版。")
        self.run_tool("commit", draft)
        self.assertEqual(self.read_state()["last_committed_chapter"], 1)
        self.assertEqual(self.read_state()["context"]["position"]["scene"], "剪辑室")

    def test_redraft_with_stale_revision_rebuilds_context_and_keeps_filled_parts(self) -> None:
        self.init()
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "大纲" / "细纲_第001章.md").write_text("### 第 1 章：看片会\n", encoding="utf-8")
        draft_cmd = [sys.executable, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"]
        first = subprocess.run(draft_cmd, text=True, capture_output=True, check=False, encoding="utf-8")
        draft_path = Path(json.loads(first.stdout)["draft"])
        state = self.read_state()
        # 过期草稿：中间别的事务改过 state 后，旧草稿的修订号与 context 都是旧的。
        stale = json.loads(draft_path.read_text(encoding="utf-8"))
        stale["expected_state_revision"] = state["state_revision"] + 7
        stale["context"]["position"]["volume"] = "旧卷名"
        stale["delta"]["result"] = "江晨保住了原版。"
        stale["context"]["position"].update({"story_time": "当晚", "scene": "剪辑室"})
        draft_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        again = subprocess.run(draft_cmd, text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("context 按当前状态重建", json.loads(again.stdout)["fill"])
        rebuilt = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["expected_state_revision"], state["state_revision"])
        self.assertEqual(rebuilt["context"]["position"]["volume"], state["context"]["position"]["volume"])
        self.assertEqual(rebuilt["delta"]["result"], "江晨保住了原版。")
        self.assertEqual((rebuilt["context"]["position"]["story_time"], rebuilt["context"]["position"]["scene"]),
                         ("当晚", "剪辑室"))
        self.run_tool("commit", rebuilt)
        self.assertEqual(self.read_state()["last_committed_chapter"], 1)

    def test_all_over_length_fields_are_reported_at_once_in_characters(self) -> None:
        self.init()
        document = transaction(1, foreshadow=True)
        document["delta"]["result"] = "江晨" * 100
        document["delta"]["foreshadow_changes"][0]["summary"] = "老兵" * 70
        result = self.run_tool("commit", document, expect=2)
        self.assertIn("2 个字段超长", result.stderr)
        self.assertIn("delta.result exceeds 480 bytes（现 200 字，上限约 160 字，至少删 40 字）", result.stderr)
        self.assertIn("summary exceeds 360 bytes（现 140 字，上限约 120 字，至少删 20 字）", result.stderr)
        self.assertEqual(self.read_state()["last_committed_chapter"], 0)

    def test_unknown_fields_are_rejected(self) -> None:
        invalid_init = initial_document()
        invalid_init["baseline"] = {}
        self.run_tool("init", invalid_init, expect=2)

        self.init()
        state = self.read_state()
        state["status"] = "clean"
        (self.project / "追踪/_tracking-state.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )
        result = self.run_tool("check", expect=2)
        self.assertIn("unsupported fields", result.stderr)

    def test_init_archives_a_pre_transaction_tracking_directory(self) -> None:
        tracking = self.project / "追踪"
        tracking.mkdir()
        (tracking / "角色状态.md").write_text("# 旧角色状态\n", encoding="utf-8")
        (tracking / "时间线.md").write_text("# 旧时间线\n", encoding="utf-8")
        (tracking / "_tracking-meta.json").write_text("{}\n", encoding="utf-8")

        result = self.run_tool("init", initial_document())
        self.assertIn("_旧追踪存档", result.stderr)
        archive = tracking / "_旧追踪存档"
        self.assertEqual((archive / "角色状态.md").read_text(encoding="utf-8"), "# 旧角色状态\n")
        self.assertEqual((archive / "时间线.md").read_text(encoding="utf-8"), "# 旧时间线\n")
        self.assertFalse((tracking / "角色状态.md").exists())
        self.assertTrue((tracking / "角色状态").is_dir())
        self.run_tool("check")

    def test_failed_init_leaves_the_old_tracking_directory_untouched(self) -> None:
        tracking = self.project / "追踪"
        tracking.mkdir()
        (tracking / "角色状态.md").write_text("# 旧角色状态\n", encoding="utf-8")
        invalid = initial_document()
        invalid["baseline"] = {}

        self.run_tool("init", invalid, expect=2)
        self.assertTrue((tracking / "角色状态.md").exists())
        self.assertFalse((tracking / "_旧追踪存档").exists())

    def test_commit_and_check_still_refuse_a_retired_layout(self) -> None:
        self.init()
        (self.project / "追踪/时间线.md").write_text("# 旧时间线\n", encoding="utf-8")
        result = self.run_tool("check", expect=2)
        self.assertIn("retired tracking files", result.stderr)
        result = self.run_tool("commit", transaction(1), expect=2)
        self.assertIn("retired tracking files", result.stderr)

    def test_dropping_a_context_item_without_declaring_it_is_rejected(self) -> None:
        self.init()
        silent = transaction(1)
        silent["context"]["long_term_constraints"] = []
        result = self.run_tool("commit", silent, expect=2)
        self.assertIn("retired_context_items", result.stderr)
        self.assertEqual(self.read_state()["state_revision"], 0)
        self.assertFalse((self.project / "追踪/逐章记录/第001章.md").exists())

    def test_declared_context_retirement_is_recorded_in_the_chapter_delta(self) -> None:
        self.init()
        declared = transaction(1)
        constraint = "军方培养江晨的后续安排尚未向读者揭示。"
        declared["context"]["long_term_constraints"] = []
        declared["delta"]["retired_context_items"] = [constraint]
        self.run_tool("commit", declared)

        self.assertEqual(self.read_state()["context"]["long_term_constraints"], [])
        delta_text = (self.project / "追踪/逐章记录/第001章.md").read_text(encoding="utf-8")
        self.assertIn("## 本章退役登记", delta_text)
        self.assertIn(constraint, delta_text)
        self.run_tool("check")

    def test_retiring_a_core_character_removes_its_derived_view(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, character=True))
        self.assertTrue((self.project / "追踪/角色状态/江晨.md").exists())

        retire = transaction(2)
        retire["delta"]["retired_characters"] = ["江晨"]
        self.run_tool("commit", retire)

        self.assertNotIn("江晨", self.read_state()["characters"])
        self.assertFalse((self.project / "追踪/角色状态/江晨.md").exists())
        self.assertIn("角色状态：江晨", (self.project / "追踪/逐章记录/第002章.md").read_text(encoding="utf-8"))
        self.run_tool("check")

    def test_an_interrupted_archive_can_be_resumed(self) -> None:
        tracking = self.project / "追踪"
        (tracking / "_旧追踪存档").mkdir(parents=True)
        (tracking / "角色状态.md").write_text("# 未搬完\n", encoding="utf-8")
        (tracking / "_旧追踪存档/时间线.md").write_text("# 上次已搬\n", encoding="utf-8")

        self.run_tool("init", initial_document())
        archive = tracking / "_旧追踪存档"
        self.assertEqual((archive / "角色状态.md").read_text(encoding="utf-8"), "# 未搬完\n")
        self.assertEqual((archive / "时间线.md").read_text(encoding="utf-8"), "# 上次已搬\n")
        self.run_tool("check")

    def test_archive_never_clobbers_an_already_archived_file(self) -> None:
        tracking = self.project / "追踪"
        (tracking / "_旧追踪存档").mkdir(parents=True)
        (tracking / "角色状态.md").write_text("现役\n", encoding="utf-8")
        (tracking / "_旧追踪存档/角色状态.md").write_text("存档\n", encoding="utf-8")

        result = self.run_tool("init", initial_document(), expect=2)
        self.assertIn("already exists", result.stderr)
        self.assertEqual((tracking / "角色状态.md").read_text(encoding="utf-8"), "现役\n")
        self.assertEqual((tracking / "_旧追踪存档/角色状态.md").read_text(encoding="utf-8"), "存档\n")

    def test_a_character_can_die_and_retire_in_one_transaction(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, character=True))
        farewell = transaction(2)
        farewell["delta"]["character_changes"] = [{"name": "江晨", "change": "在最终一战中阵亡，彻底退场"}]
        farewell["delta"]["retired_characters"] = ["江晨"]
        self.run_tool("commit", farewell)

        record = (self.project / "追踪/逐章记录/第002章.md").read_text(encoding="utf-8")
        self.assertIn("江晨｜核心｜在最终一战中阵亡，彻底退场", record)
        self.assertIn("角色状态：江晨", record)
        self.assertNotIn("江晨", self.read_state()["characters"])
        self.run_tool("check")

    def test_retirement_is_rejected_in_a_revision(self) -> None:
        self.init(last_chapter=20)
        retire = transaction(10, mode="revision")
        retire["delta"]["retired_characters"] = ["江晨"]
        result = self.run_tool("commit", retire, expect=2)
        self.assertIn("append transaction", result.stderr)

        drop = transaction(10, mode="revision")
        drop["context"]["long_term_constraints"] = []
        drop["delta"]["retired_context_items"] = ["军方培养江晨的后续安排尚未向读者揭示。"]
        result = self.run_tool("commit", drop, expect=2)
        self.assertIn("append transaction", result.stderr)
        self.assertEqual(self.read_state()["state_revision"], 0)

    def test_retiring_a_still_active_character_is_rejected(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, character=True))
        still_listed = transaction(2)
        still_listed["delta"]["retired_characters"] = ["江晨"]
        still_listed["context"]["active_character_names"] = ["江晨"]
        result = self.run_tool("commit", still_listed, expect=2)
        self.assertIn("retired character 江晨 is still listed in context.active_character_names", result.stderr)
        self.assertEqual(self.read_state()["state_revision"], 1)

    def test_retiring_and_updating_a_character_in_one_transaction_is_rejected(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1, character=True))
        updated = transaction(2, character=True)
        updated["delta"]["retired_characters"] = ["江晨"]
        updated["context"]["active_character_names"] = []
        result = self.run_tool("commit", updated, expect=2)
        self.assertIn("character 江晨 cannot be retired and updated in the same transaction", result.stderr)
        self.assertEqual(self.read_state()["state_revision"], 1)

    def test_windows_reserved_character_name_is_rejected(self) -> None:
        self.init()
        invalid = transaction(1, character=True)
        invalid["delta"]["character_changes"][0]["name"] = "CON"
        invalid["context"]["active_character_names"] = ["CON"]
        invalid["character_snapshots"] = {"CON": invalid["character_snapshots"]["江晨"]}
        result = self.run_tool("commit", invalid, expect=2)
        self.assertIn("is reserved on Windows", result.stderr)
        self.assertEqual(self.read_state()["state_revision"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
