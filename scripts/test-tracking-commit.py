#!/usr/bin/env python3
"""Behavioral regression tests for the single-authority tracking state tool."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/story-long-write/scripts/tracking_commit.js"
STORYCTL = ROOT / "skills/story-long-write/scripts/storyctl.js"
WORDCOUNT = ROOT / "skills/story-long-write/scripts/wordcount_core.js"
NODE = shutil.which("node") or "node"


def build_project_wordcount_record(project: Path, chapter: int, *, resolution: str) -> dict[str, object]:
    script = (
        'const wc = require(process.argv[1]);'
        'const res = wc.buildProjectWordcountRecord(process.argv[2], Number(process.argv[3]), { resolution: process.argv[4] });'
        'process.stdout.write(JSON.stringify(res));'
    )
    completed = subprocess.run(
        [NODE, "-e", script, str(WORDCOUNT), str(project), str(chapter), resolution],
        text=True, encoding="utf-8", capture_output=True, check=True,
    )
    return json.loads(completed.stdout)


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
        extra: list[str] | None = None,
        expect: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        args = [NODE, str(TOOL), command, "--project", str(self.project), *(extra or [])]
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
        document["wordcount"] = build_project_wordcount_record(
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
                [NODE, str(TOOL), "commit", "--project", str(self.project), "--input", str(path)],
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
        over_old_cap = transaction(1, character=True)
        over_old_cap["character_snapshots"]["江晨"] = snapshot(items=14, repeat=4)
        completed = self.run_tool("commit", over_old_cap)
        self.assertNotIn("WARNING: character snapshot 江晨", completed.stderr)
        rendered_ch1 = (self.project / "追踪/角色状态/江晨.md").read_bytes()
        self.assertGreater(len(rendered_ch1), 8192)
        self.assertLessEqual(len(rendered_ch1), 16384)
        self.assertEqual(len(self.read_state()["characters"]["江晨"]["knowledge"]), 14)
        self.assertLessEqual(len((self.project / "追踪/上下文.md").read_bytes()), 12288)
        self.run_tool("check")

        warning = transaction(2, character=True)
        warning["character_snapshots"]["江晨"] = snapshot(items=24, repeat=4)
        completed = self.run_tool("commit", warning)
        self.assertIn("WARNING: character snapshot 江晨", completed.stderr)
        self.assertIn("不影响本次提交", completed.stderr)
        self.assertEqual(self.read_state()["state_revision"], 2)
        self.run_tool("check")

        rejected = transaction(3, character=True)
        rejected["character_snapshots"]["江晨"] = snapshot(items=80, repeat=4)
        before = json.loads(json.dumps(self.read_state(), ensure_ascii=False))
        snapshot_before = (self.project / "追踪/角色状态/江晨.md").read_bytes()
        completed = self.run_tool("commit", rejected, expect=2)
        self.assertIn("exceeds hard cap of 65536 bytes", completed.stderr)
        self.assertIn("能力与资源 80 项", completed.stderr)
        self.assertEqual(self.read_state(), before)
        self.assertEqual((self.project / "追踪/角色状态/江晨.md").read_bytes(), snapshot_before)
        self.assertFalse((self.project / "追踪/逐章记录/第003章.md").exists())

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
        document = transaction(1, character=True, foreshadow=True, timeline=True)
        document["expected_state_revision"] = 0
        fail_script = (
            'const path = require("path");'
            'const mod = require(process.argv[1]);'
            'const doc = JSON.parse(process.argv[3]);'
            'const orig = mod._hooks.atomicWriteText;'
            'mod._hooks.atomicWriteText = (p, payload) => {'
            '  if (path.basename(p) === "伏笔.md") { const e = new Error("injected derived-view failure"); e.code = "EIO"; throw e; }'
            '  return orig(p, payload);'
            '};'
            'try { mod.applyTransaction(process.argv[2], doc); process.exit(1); }'
            'catch (err) { if (err.message !== "injected derived-view failure") throw err; }'
        )
        completed = subprocess.run(
            [NODE, "-e", fail_script, str(TOOL), str(self.project), json.dumps(document, ensure_ascii=False)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        self.assertEqual(self.read_state()["state_revision"], 0)
        self.assertIn("状态修订：1", (self.project / "追踪/上下文.md").read_text(encoding="utf-8"))
        # An orphaned future chapter delta from a crashed transaction is a hard integrity error (exit 2).
        self.run_tool("check", expect=2)

        self.run_tool("commit", document)
        self.assertEqual(self.read_state()["state_revision"], 1)
        self.run_tool("check", extra=["--strict"])

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
        # Default check softens manual edit to structured drift_warnings (exit 0) with author prompt.
        soft = self.run_tool("check", expect=0)
        payload = json.loads(soft.stdout)
        self.assertEqual(len(payload["drift_warnings"]), 1)
        self.assertEqual(payload["drift_warnings"][0]["type"], "view_drift")
        self.assertIn("derived view differs from _tracking-state.json", payload["drift_warnings"][0]["message"])
        self.assertIn("询问作者", payload["drift_warnings"][0]["prompt"])
        # --strict explicitly enforces exit 2 on derived view drift.
        strict_res = self.run_tool("check", extra=["--strict"], expect=2)
        self.assertIn("derived view differs from _tracking-state.json", strict_res.stderr)

        self.run_tool("commit", transaction(2))
        self.run_tool("check", extra=["--strict"])

    def test_check_rejects_orphan_character_file(self) -> None:
        self.init()
        orphan = self.project / "追踪/角色状态/CONFLICT.md"
        orphan.write_text("# orphan\n", encoding="utf-8")
        soft = self.run_tool("check", expect=0)
        payload = json.loads(soft.stdout)
        self.assertTrue(any(w["type"] == "character_files_drift" for w in payload["drift_warnings"]))
        result = self.run_tool("check", extra=["--strict"], expect=2)
        self.assertIn("character snapshot files differ", result.stderr)

    def test_draft_prefills_current_context_so_only_the_delta_is_written(self) -> None:
        self.init()
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "大纲" / "细纲_第001章.md").write_text("### 第 1 章：看片会\n", encoding="utf-8")
        completed = subprocess.run(
            [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"],
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
            [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"],
            text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("原样保留", json.loads(again.stdout)["fill"])
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(draft["delta"]["result"], "江晨在看片会上保住了原版。")
        self.run_tool("commit", draft)
        self.assertEqual(self.read_state()["last_committed_chapter"], 1)
        self.assertEqual(self.read_state()["context"]["position"]["scene"], "剪辑室")

    def test_common_model_spellings_commit_on_first_try(self) -> None:
        # 实测（v0.8.1 solo A/B，10 章）首次提交全被退回：章号写成字符串、自造 planned_chapter、
        # action 写 add、新书快照的 identity 写成列表。这些写法含义明确，照收并规范成正式形状。
        self.init()
        document = transaction(1, character=True, foreshadow=True, timeline=True)
        row = document["delta"]["foreshadow_changes"][0]
        row["action"] = "add"
        row["planted_chapter"] = "1"
        row["planned_chapter"] = row.pop("planned_resolution_chapter")
        event = document["delta"]["timeline_events"][0]
        event["action"] = "新增"
        document["character_snapshots"]["江晨"]["identity"] = ["火箭军文工团宣传兵", "军宣爆款创作者"]
        document["character_snapshots"]["江晨"]["relationships"] = "与钟嘉嘉协作"
        self.run_tool("commit", document)
        state = self.read_state()
        self.assertEqual(state["foreshadow"]["F027"]["planted_chapter"], 1)
        self.assertEqual(state["foreshadow"]["F027"]["planned_resolution_chapter"], 9)
        self.assertEqual(state["characters"]["江晨"]["identity"], "火箭军文工团宣传兵；军宣爆款创作者")
        self.assertEqual(state["characters"]["江晨"]["relationships"], ["与钟嘉嘉协作"])

    def test_status_verbs_fill_a_missing_status_and_reject_a_contradicting_one(self) -> None:
        # resolve/回收 映射成 upsert 时，动作词本身就是「已回收」的意图：缺 status 按它补，矛盾就退回并说清怎么写。
        self.init()
        document = transaction(1, foreshadow=True)
        row = document["delta"]["foreshadow_changes"][0]
        row["action"] = "回收"
        row.pop("status")
        self.run_tool("commit", document)
        self.assertEqual(self.read_state()["foreshadow"]["F027"]["status"], "已回收")

        for verb, status, hint in (("resolve", "已埋", "status=已回收"), ("回收", "已埋", "status=已回收"),
                                   ("advance", "已回收", "status=已埋"), ("推进", "放弃", "status=已埋")):
            document = transaction(2, foreshadow=True)
            document["delta"]["foreshadow_changes"][0].update({"action": verb, "status": status})
            stderr = self.run_tool("commit", document, expect=2).stderr
            self.assertIn(f"action={verb} 与 status={status} 矛盾", stderr)
            self.assertIn(hint, stderr)
        self.assertEqual(self.read_state()["last_committed_chapter"], 1)

        document = transaction(2, foreshadow=True)
        document["delta"]["foreshadow_changes"][0].update({"action": "推进", "status": "已埋",
                                                           "planted_chapter": "１"})
        self.run_tool("commit", document)
        self.assertEqual(self.read_state()["foreshadow"]["F027"]["status"], "已埋")

    def test_superscript_chapter_is_a_clean_rejection_not_a_traceback(self) -> None:
        self.init()
        document = transaction(1, foreshadow=True)
        document["delta"]["foreshadow_changes"][0]["planted_chapter"] = "²"
        completed = self.run_tool("commit", document, expect=2)
        self.assertIn("planted_chapter must be an integer", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_rejections_name_the_fix(self) -> None:
        self.init()
        document = transaction(1, foreshadow=True)
        document["delta"]["foreshadow_changes"][0]["payoff_note"] = "看片会后"
        completed = self.run_tool("commit", document, expect=2)
        self.assertIn("contains unsupported fields: payoff_note", completed.stderr)
        self.assertIn("只收 action, id, importance, planned_resolution_chapter, planted_chapter, status, summary",
                      completed.stderr)
        document = transaction(1, foreshadow=True)
        document["delta"]["foreshadow_changes"][0]["action"] = "merge"
        self.assertIn("action is invalid: use upsert or delete", self.run_tool("commit", document, expect=2).stderr)
        self.run_tool("commit", transaction(1, character=True))
        document = transaction(2, character=True)
        document["character_snapshots"] = {}
        self.assertIn("current_snapshots", self.run_tool("commit", document, expect=2).stderr)

    def test_draft_shows_entry_shapes_from_the_validator_constants(self) -> None:
        self.init()
        completed = subprocess.run(
            [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"],
            text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        shapes = json.loads(completed.stdout)["shapes"]
        foreshadow = shapes["delta.foreshadow_changes[]"]
        self.assertEqual(foreshadow["planted_chapter"], 1)
        self.assertEqual(foreshadow["status"], "已埋|已回收|已过期|放弃")
        self.assertEqual(set(foreshadow), {"action", "id", "summary", "planted_chapter",
                                           "planned_resolution_chapter", "status", "importance"})
        self.assertEqual(shapes["delta.timeline_events[]"]["reveal_status"], "未揭示|部分揭示|已揭示")
        snapshot_shape = shapes["character_snapshots.{角色名}"]
        self.assertEqual(snapshot_shape["identity"], "一句话")
        self.assertEqual(snapshot_shape["open_threads"], ["一条一句"])

    def test_redraft_with_stale_revision_rebuilds_context_and_keeps_filled_parts(self) -> None:
        self.init()
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "大纲" / "细纲_第001章.md").write_text("### 第 1 章：看片会\n", encoding="utf-8")
        draft_cmd = [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"]
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

    def test_redraft_merge_keeps_the_drafts_own_additions_and_retirements(self) -> None:
        self.init()
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "大纲" / "细纲_第001章.md").write_text("### 第 1 章：看片会\n", encoding="utf-8")
        draft_cmd = [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"]
        first = subprocess.run(draft_cmd, text=True, capture_output=True, check=False, encoding="utf-8")
        draft_path = Path(json.loads(first.stdout)["draft"])
        state = self.read_state()
        old = state["context"]["long_term_constraints"][0]
        stale = json.loads(draft_path.read_text(encoding="utf-8"))
        stale["expected_state_revision"] = state["state_revision"] + 7
        stale["context"]["long_term_constraints"] = ["本章新立的约束。"]  # 删旧条目、加新条目
        stale["delta"]["retired_context_items"] = [old]
        stale["delta"]["result"] = "江晨保住了原版。"
        stale["context"]["position"].update({"story_time": "当晚", "scene": "剪辑室", "volume": "旧卷名"})
        draft_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        again = subprocess.run(draft_cmd, text=True, capture_output=True, check=False, encoding="utf-8")
        guide = json.loads(again.stdout)
        self.assertIn("卷信息与当前状态不同", guide["fill"])
        rebuilt = json.loads(draft_path.read_text(encoding="utf-8"))
        # 本章的新增留下、退役的不回来。
        self.assertEqual(rebuilt["context"]["long_term_constraints"], ["本章新立的约束。"])
        self.run_tool("commit", rebuilt)
        self.assertEqual(self.read_state()["context"]["long_term_constraints"], ["本章新立的约束。"])

    def test_redraft_revision_and_names_are_not_merged_back_silently(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1))
        # 修订草稿：中间可能插进新章并退役条目，旧草稿多出的条目不能自动带回。
        draft_cmd = [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"]
        first = subprocess.run(draft_cmd, text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(json.loads(first.stdout)["mode"], "revision")
        draft_path = Path(json.loads(first.stdout)["draft"])
        state = self.read_state()
        stale = json.loads(draft_path.read_text(encoding="utf-8"))
        stale["expected_state_revision"] = state["state_revision"] + 7
        stale["context"]["long_term_constraints"].append("已被后续章节退役的条目。")
        stale["context"]["active_character_names"].append("路人乙")
        stale["character_snapshots"] = {"路人乙": {"name": "路人乙"}}  # 后续章节已退役的角色的旧快照
        draft_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        again = subprocess.run(draft_cmd, text=True, capture_output=True, check=False, encoding="utf-8")
        fill = json.loads(again.stdout)["fill"]
        rebuilt = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["context"]["long_term_constraints"], state["context"]["long_term_constraints"])
        self.assertNotIn("路人乙", rebuilt["context"]["active_character_names"])
        self.assertIn("没有自动带回", fill)
        self.assertIn("已被后续章节退役的条目。", fill)
        self.assertIn("在场角色 路人乙", fill)
        self.assertIn("角色快照 路人乙", fill)
        self.assertEqual(rebuilt["character_snapshots"], {})

    def draft(self, chapter: int) -> tuple[dict[str, object], Path]:
        completed = subprocess.run(
            [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", str(chapter)],
            text=True, capture_output=True, check=False, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        guide = json.loads(completed.stdout)
        return guide, Path(guide["draft"])

    def test_revision_draft_keeps_commitments_that_contain_the_separator(self) -> None:
        # 承诺原文带「；」：非最新章的修订草稿从逐章记录读回承诺，不能把一条拆成两条。
        self.init()
        commitment = "江晨答应交片；但只交原版，不交删改版。"
        self.run_tool("commit", transaction(1, next_commitment=commitment))
        self.run_tool("commit", transaction(2))
        _, draft_path = self.draft(1)
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(draft["delta"]["next_chapter_commitments"], [commitment])
        # 照预填提交后再读回，仍是同一条（渲染与读回互逆）。
        self.run_tool("commit", draft)
        (self.project / ".story/work/第001章/tracking.json").unlink()
        _, draft_path = self.draft(1)
        again = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(again["delta"]["next_chapter_commitments"], [commitment])

    def test_revision_draft_without_a_record_does_not_claim_it_prefilled(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1))
        self.run_tool("commit", transaction(2))
        (self.project / "追踪/逐章记录/第001章.md").unlink()
        guide, _ = self.draft(1)
        self.assertEqual(guide["mode"], "revision")
        self.assertNotIn("已按本章现有逐章记录预填", guide["fill"])
        self.assertIn("逐章记录缺失", guide["fill"])

    def test_revision_draft_prefills_the_committed_record_so_nothing_is_wiped(self) -> None:
        self.init()
        first = transaction(1, character=True, foreshadow=True, timeline=True)
        first["delta"]["constraints"] = ["原版视频不能再被替换。"]
        self.run_tool("commit", first)
        self.run_tool("commit", transaction(2, character=True))
        record_path = self.project / "追踪/逐章记录/第001章.md"
        before = record_path.read_text(encoding="utf-8")

        guide, draft_path = self.draft(1)
        self.assertEqual(guide["mode"], "revision")
        # 修订的 delta 是本章修订后的完整记录，不是「只填变化」。
        self.assertNotIn("只填 delta 里本章的变化", guide["fill"])
        self.assertIn("完整记录", guide["fill"])
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        delta = draft["delta"]
        self.assertEqual(delta["result"], first["delta"]["result"])
        self.assertEqual(delta["character_changes"], first["delta"]["character_changes"])
        self.assertEqual([item["id"] for item in delta["foreshadow_changes"]], ["F027"])
        self.assertEqual([item["id"] for item in delta["timeline_events"]], ["E010"])
        self.assertEqual(delta["constraints"], ["原版视频不能再被替换。"])
        self.assertEqual(delta["next_chapter_commitments"], first["delta"]["next_chapter_commitments"])
        self.assertIn("江晨", draft["character_snapshots"])

        # 只改修订真正改变的一项，其余照预填提交：逐章记录除结果外逐字不变，check 通过。
        delta["result"] = "江晨在看片会上保住原版，并当场剪出新预告。"
        self.run_tool("commit", draft)
        after = record_path.read_text(encoding="utf-8")
        self.assertEqual(after, before.replace(first["delta"]["result"], delta["result"]))
        self.run_tool("check")

    def test_revision_keeps_the_chapter_retirement_log(self) -> None:
        self.init()
        constraint = "军方培养江晨的后续安排尚未向读者揭示。"
        declared = transaction(1)
        declared["context"]["long_term_constraints"] = []
        declared["delta"]["retired_context_items"] = [constraint]
        self.run_tool("commit", declared)
        _, draft_path = self.draft(1)
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        self.run_tool("commit", draft)
        record = (self.project / "追踪/逐章记录/第001章.md").read_text(encoding="utf-8")
        self.assertIn("## 本章退役登记", record)
        self.assertIn(constraint, record)
        self.run_tool("check")

    def test_revision_recounts_a_body_edited_after_commit(self) -> None:
        # 提交后去味或审稿改了正文：修订照常提交，字数记录按现正文重算，不让作者换工具。
        self.init()
        body = self.write_chapter_contract(1, actual=1000, target=1000)
        self.run_tool("commit", self.bind_wordcount(transaction(1), resolution="within_user_band"))
        committed_actual = self.read_state()["wordcount_records"]["1"]["actual"]
        body_path = self.project / "正文/第001章_测试.md"
        body_path.write_bytes(body.replace("字".encode("utf-8"), "".encode("utf-8"), 50))
        self.run_tool("commit", transaction(1, mode="revision"))
        record = self.read_state()["wordcount_records"]["1"]
        self.assertEqual(record["actual"], committed_actual - 50)
        self.assertEqual(record["body_sha256"], hashlib.sha256(body_path.read_bytes()).hexdigest())
        self.run_tool("check")
        # 改到出了作者范围才停下要作者定；报的是改了哪一项，记录不动。
        outline = self.project / "大纲/细纲_第001章.md"
        outline.write_text(outline.read_text(encoding="utf-8").replace("1000 字", "1200 字"), encoding="utf-8")
        before = self.read_state()
        result = self.run_tool("commit", transaction(1, mode="revision"), expect=2)
        self.assertIn("第1章字数目标已改", result.stderr)
        self.assertNotIn("正文", result.stderr.split("；")[0])
        self.assertIn("accept-current-length", result.stderr)
        self.assertEqual(self.read_state(), before)

    def test_tracking_only_revision_survives_a_later_author_range_line(self) -> None:
        # 提交时细纲没写「字数范围」（记录无 author_range）；作者事后给细纲补一行范围。正文与目标都没动，
        # 纯追踪修订不该被当成「正文或字数目标已改」拒掉。
        self.init()
        self.write_chapter_contract(1, actual=1000, target=1000)
        self.run_tool("commit", self.bind_wordcount(transaction(1), resolution="within_user_band"))
        outline = self.project / "大纲/细纲_第001章.md"
        outline.write_text(outline.read_text(encoding="utf-8") + "- 字数范围：1500-2000 字\n", encoding="utf-8")
        self.run_tool("commit", transaction(1, mode="revision"))
        self.run_tool("check")

    def test_tracking_only_revision_survives_a_non_numeric_target_note(self) -> None:
        # 旧细纲在数字目标旁留了一行「字数目标：按卷规划」式说明：不含数字的行是说明文字，
        # 已提交章的纯追踪修订照常核对并通过；两个数字值冲突仍拒。
        self.init()
        self.write_chapter_contract(1, actual=1000, target=1000)
        self.run_tool("commit", self.bind_wordcount(transaction(1), resolution="within_user_band"))
        outline = self.project / "大纲/细纲_第001章.md"
        original = outline.read_text(encoding="utf-8")
        outline.write_text(original + "- 字数目标：按卷规划\n", encoding="utf-8")
        self.run_tool("commit", transaction(1, mode="revision"))
        outline.write_text(original + "- 字数目标：1200 字\n", encoding="utf-8")
        result = self.run_tool("commit", transaction(1, mode="revision"), expect=2)
        self.assertIn("字数记录无法核对", result.stderr)

    def test_retired_item_still_in_context_is_rejected(self) -> None:
        self.init()
        document = transaction(1)
        document["delta"]["retired_context_items"] = list(document["context"]["long_term_constraints"])
        result = self.run_tool("commit", document, expect=2)
        self.assertIn("lists items that are still in context", result.stderr)

    def test_all_over_length_fields_are_reported_at_once_in_characters(self) -> None:
        self.init()
        document = transaction(1, foreshadow=True)
        document["delta"]["result"] = "江晨" * 100
        document["delta"]["foreshadow_changes"][0]["summary"] = "老兵" * 70
        result = self.run_tool("commit", document, expect=0)
        payload = json.loads(result.stdout)
        self.assertEqual(self.read_state()["last_committed_chapter"], 1)
        self.assertIn("delta.result exceeds 480 bytes（现 200 字，建议上限约 160 字", result.stderr)
        self.assertIn("summary exceeds 360 bytes（现 140 字，建议上限约 120 字", result.stderr)
        self.assertTrue(any("delta.result exceeds 480 bytes" in w for w in payload["warnings"]))
        self.assertTrue(any("summary exceeds 360 bytes" in w for w in payload["warnings"]))
        self.run_tool("check", extra=["--strict"])

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

    def cast_document(self, count: int, *, long_fields: bool = False) -> dict[str, object]:
        document = initial_document()
        names = [f"女主{index:02d}" for index in range(1, count + 1)]
        document["context"]["active_character_names"] = names
        for name in names:
            entry = snapshot()
            if long_fields:
                entry.update(identity="身" * 80, state="状" * 100, goal="目" * 100)
            document["character_snapshots"][name] = entry
        return document

    def test_twenty_active_characters_pass_and_above_twenty_warns_without_blocking(self) -> None:
        # >20 active characters and >6 constraints / >5 risks now emit structured warnings instead of hard exit 2.
        over_init = self.cast_document(21)
        over_init["context"]["long_term_constraints"] = [f"约束{i}" for i in range(7)]
        over_init["context"]["continuity_risks"] = [f"风险{i}" for i in range(6)]
        result = self.run_tool("init", over_init, expect=0)
        payload = json.loads(result.stdout)
        self.assertTrue(any("active_character_names has 21 names" in w for w in payload["warnings"]))
        self.assertTrue(any("long_term_constraints has 7 items" in w for w in payload["warnings"]))
        self.assertTrue(any("continuity_risks has 6 items" in w for w in payload["warnings"]))
        self.run_tool("check", extra=["--strict"])

        overflow = transaction(1, character=True)
        overflow["context"]["active_character_names"] = self.read_state()["context"]["active_character_names"] + ["江晨"]
        overflow["context"]["long_term_constraints"] = self.read_state()["context"]["long_term_constraints"]
        overflow["context"]["continuity_risks"] = self.read_state()["context"]["continuity_risks"]
        commit_res = self.run_tool("commit", overflow, expect=0)
        self.assertTrue(any("active_character_names has 22 names" in w for w in json.loads(commit_res.stdout)["warnings"]))
        self.run_tool("check", extra=["--strict"])

    def test_existing_state_with_six_to_twenty_active_characters_still_checks_drafts_and_commits(self) -> None:
        # 旧版只收 6 人；作者改过脚本写下的 7–20 人 state，升级后必须照常 check / draft / commit。
        for count in (6, 7, 20):
            with self.subTest(count=count):
                self.project = Path(self.temporary.name) / f"群像{count}"
                self.project.mkdir()
                self.run_tool("init", self.cast_document(count))
                self.run_tool("check")
                (self.project / "大纲").mkdir()
                (self.project / "大纲" / "细纲_第001章.md").write_text("### 第 1 章：家宴\n", encoding="utf-8")
                drafted = subprocess.run(
                    [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "1"],
                    text=True, capture_output=True, check=False, encoding="utf-8")
                self.assertEqual(drafted.returncode, 0, drafted.stderr)
                draft_path = Path(json.loads(drafted.stdout)["draft"])
                draft = json.loads(draft_path.read_text(encoding="utf-8"))
                self.assertEqual(len(draft["context"]["active_character_names"]), count)
                draft["delta"]["result"] = "众人在家宴上各怀心思。"
                draft["context"]["position"].update({"story_time": "家宴当晚", "scene": "正厅"})
                self.run_tool("commit", draft)
                state = self.read_state()
                self.assertEqual(state["last_committed_chapter"], 1)
                self.assertEqual(len(state["context"]["active_character_names"]), count)
                self.run_tool("check")

    def test_hot_context_soft_warns_above_12kb_and_hard_rejects_above_64kb(self) -> None:
        # >12288B hot context now succeeds with structured warning; >65536B safety cap hard-rejects before any write.
        soft_res = self.run_tool("init", self.cast_document(20, long_fields=True), expect=0)
        self.assertIn("hot context is", soft_res.stderr)
        self.assertIn("12288 bytes", soft_res.stderr)
        self.assertTrue(any("12288 bytes" in w for w in json.loads(soft_res.stdout)["warnings"]))
        self.run_tool("check", extra=["--strict"])

        # >65536B hot context still hard-rejects before writing anything.
        huge = transaction(1)
        names = self.read_state()["context"]["active_character_names"]
        huge["context"]["active_character_names"] = names
        huge["context"]["long_term_constraints"] = self.read_state()["context"]["long_term_constraints"] + [
            "超长约束" * 2000 for _ in range(3)
        ]
        before = self.read_state()
        context_before = (self.project / "追踪/上下文.md").read_bytes()
        result = self.run_tool("commit", huge, expect=2)
        self.assertIn("exceeds hard cap of 65536 bytes", result.stderr)
        self.assertEqual(self.read_state(), before)
        self.assertEqual((self.project / "追踪/上下文.md").read_bytes(), context_before)
        self.assertFalse((self.project / "追踪/逐章记录/第001章.md").exists())

    def test_snapshot_utf8_multibyte_boundary_and_list_item_limit(self) -> None:
        self.init()
        # 列表单项 >600 字节降为 warning，不再阻断提交。
        long_item = transaction(1, character=True)
        long_item["character_snapshots"]["江晨"]["abilities_resources"] = ["剑" * 201]
        warned_item = self.run_tool("commit", long_item, expect=0)
        self.assertIn("exceeds 600 bytes（现 201 字，建议上限约 200 字", warned_item.stderr)
        self.assertEqual(self.read_state()["state_revision"], 1)

        # 构造渲染后恰好 65536 UTF-8 字节（中文 3 字节 + ASCII 精确补齐）的快照：通过；再多 1 个汉字（+3 字节）即拒。
        base_snap = {
            "identity": "太虚宗执剑弟子",
            "location": "寒鸦关石室",
            "goal": "护送残卷回宗",
            "state": "灵力存六成",
            "abilities_resources": ["剑" * 200 for _ in range(100)],
            "relationships": ["盟" * 10],
            "knowledge": ["秘" * 10],
            "open_threads": ["债" * 10],
        }
        probe = transaction(2, character=True)
        probe["character_snapshots"]["江晨"] = json.loads(json.dumps(base_snap, ensure_ascii=False))
        self.run_tool("commit", probe)
        current_bytes = len((self.project / "追踪/角色状态/江晨.md").read_bytes())
        # 第 3 章提交时 revision 从 2 变成 3（位数相同，字节差仅来自新增列表项）。
        remaining = 65536 - current_bytes
        exact_snap = json.loads(json.dumps(base_snap, ensure_ascii=False))
        while remaining > 603:
            exact_snap["knowledge"].append("剑" * 200)
            remaining -= 603
        self.assertGreater(remaining, 10)
        payload_budget = remaining - 3
        cjk_count, ascii_rem = divmod(payload_budget, 3)
        exact_item = ("阵" * cjk_count) if ascii_rem == 0 else ("阵" * cjk_count + "A" * ascii_rem)
        exact_snap["knowledge"].append(exact_item)
        exact_tx = transaction(3, character=True)
        exact_tx["character_snapshots"]["江晨"] = exact_snap
        self.run_tool("commit", exact_tx)
        snapshot_file = self.project / "追踪/角色状态/江晨.md"
        self.assertEqual(len(snapshot_file.read_bytes()), 65536)
        self.assertLess(len(snapshot_file.read_text(encoding="utf-8")), 25000)
        self.run_tool("check", extra=["--strict"])

        over_by_one_hanzi = json.loads(json.dumps(exact_snap, ensure_ascii=False))
        over_by_one_hanzi["open_threads"][0] = over_by_one_hanzi["open_threads"][0] + "多"
        over_tx = transaction(4, character=True)
        over_tx["character_snapshots"]["江晨"] = over_by_one_hanzi
        before = self.read_state()
        rejected = self.run_tool("commit", over_tx, expect=2)
        self.assertIn("65539 bytes", rejected.stderr)
        self.assertIn("exceeds hard cap of 65536 bytes", rejected.stderr)
        self.assertEqual(self.read_state(), before)
        self.assertEqual(len(snapshot_file.read_bytes()), 65536)
        self.assertFalse((self.project / "追踪/逐章记录/第004章.md").exists())

    def test_multi_character_accumulation_draft_files_revision_and_reactivation_across_copies(self) -> None:
        # 1. init 一次性汇总多字段超长，修正后导入含大快照与非在场核心角色的 60 章存量项目。
        def rich_snapshot(tag: str, count: int) -> dict[str, object]:
            return {
                "identity": f"{tag}·北境镇魔司执令使",
                "location": "寒鸦关地下古阵石室",
                "goal": f"{tag}查清阵眼被蚀真相并稳住根基",
                "state": f"{tag}寒毒压于奇经但战力尚存七成",
                "abilities_resources": [f"{tag}功法器物{i:02d}：玄铁剑诀第{i}式与灵矿密牒（第{i}章所得，剩余三次）" for i in range(1, count + 1)],
                "relationships": [f"{tag}关键关系{i:02d}：与守关将领及暗桩第{i}号结盟互保但留底牌" for i in range(1, count + 1)],
                "knowledge": [f"{tag}已知情报{i:02d}：确认军粮账册第{i}页篡改牵涉兵部侍郎走私链" for i in range(1, count + 1)],
                "open_threads": [f"{tag}未结事项{i:02d}：月底前核查第{i}批失踪斥候并归还古阵盘" for i in range(1, max(4, count // 2) + 1)],
            }

        bad_init = initial_document(last_chapter=60)
        bad_init["schema_version"] = 99
        bad_res = self.run_tool("init", bad_init, expect=2)
        self.assertIn("schema_version is unsupported", bad_res.stderr)
        self.assertFalse((self.project / "追踪/_tracking-state.json").exists())

        init_doc = initial_document(last_chapter=60)
        init_doc["context"]["active_character_names"] = ["沈砚", "钟离"]
        init_doc["character_snapshots"] = {
            "沈砚": rich_snapshot("沈砚", 40),
            "钟离": rich_snapshot("钟离", 28),
            "顾长渊": rich_snapshot("顾长渊", 28),  # 久别非在场核心角色
        }
        self.run_tool("init", init_doc)
        self.assertGreater(len((self.project / "追踪/角色状态/沈砚.md").read_bytes()), 12000)
        self.assertGreater(len((self.project / "追踪/角色状态/顾长渊.md").read_bytes()), 8192)
        self.run_tool("check")

        # 2. 第 61 章继续累积使沈砚突破 16 KiB 内联阈值；第 62 章 draft 验证 stdout 受控且久别角色顾长渊可从 snapshot_files 取回。
        ch61 = transaction(61)
        grown_shen = rich_snapshot("沈砚", 70)
        ch61["delta"]["character_changes"] = [{"name": "沈砚", "change": "破入石室深层并掌握新阵纹线索"}]
        ch61["context"]["active_character_names"] = ["沈砚", "钟离"]
        ch61["character_snapshots"] = {"沈砚": grown_shen}
        self.run_tool("commit", ch61)
        self.assertGreater(len((self.project / "追踪/角色状态/沈砚.md").read_bytes()), 20000)

        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "正文").mkdir(exist_ok=True)
        (self.project / "大纲/细纲_第062章.md").write_text(
            "### 第 62 章：驰援西营\n- 字数目标：1000 字\n- 字数口径：visible_chars_v1\n",
            encoding="utf-8",
        )
        guide62, draft62_path = self.draft(62)
        self.assertIn("沈砚", guide62.get("omitted_active_snapshots", []))
        self.assertNotIn("沈砚", guide62["current_snapshots"])
        self.assertIn("钟离", guide62["current_snapshots"])
        snapshot_files = guide62["snapshot_files"]
        self.assertEqual(set(snapshot_files), {"沈砚", "钟离", "顾长渊"})
        gu_from_disk = json.loads(Path(snapshot_files["顾长渊"]).read_text(encoding="utf-8"))
        self.assertEqual(gu_from_disk, init_doc["character_snapshots"]["顾长渊"])

        # 久别核心角色顾长渊本章变化但漏交快照时，报错明确指路 current_snapshots / snapshot_files 且不写盘。
        draft62 = json.loads(draft62_path.read_text(encoding="utf-8"))
        draft62["delta"]["result"] = "顾长渊驰援寒鸦关，与沈砚合破妖族暗桩。"
        draft62["delta"]["character_changes"] = [{"name": "顾长渊", "change": "驰援寒鸦关并交出南境密信"}]
        draft62["context"]["position"].update({"story_time": "风雪第四夜", "scene": "寒鸦关西营"})
        draft62["context"]["active_character_names"] = ["沈砚", "钟离", "顾长渊"]
        missing_gu = self.run_tool("commit", draft62, expect=2)
        self.assertIn("snapshot_files", missing_gu.stderr)
        self.assertEqual(self.read_state()["last_committed_chapter"], 61)

        # 通过 storyctl.py chapter commit 正式提交第 62 章，验证工作目录连同 snapshots/ 自动清理。
        (self.project / "正文/第062章_驰援西营.md").write_text(
            "# 第062章 驰援西营\n"
            + "\n".join(f"顾长渊在西营核对第{i}册军械账目，沈砚旁证北境第{i}道暗桩口供。" for i in range(1, 36))
            + "\n",
            encoding="utf-8",
        )
        gu_from_disk["knowledge"].append("顾长渊新知：西营军械库暗门已被妖族识破")
        draft62["character_snapshots"] = {"顾长渊": gu_from_disk}
        draft62_path.write_text(json.dumps(draft62, ensure_ascii=False), encoding="utf-8")
        storyctl_commit = subprocess.run(
            [
                NODE, str(STORYCTL), "chapter", "commit",
                "--project", str(self.project), "--chapter", "62", "--input", str(draft62_path),
            ],
            text=True, capture_output=True, check=False, encoding="utf-8",
        )
        self.assertEqual(storyctl_commit.returncode, 0, storyctl_commit.stdout + storyctl_commit.stderr)
        self.assertFalse((self.project / ".story/work/第062章").exists())
        self.assertEqual(len(self.read_state()["characters"]["顾长渊"]["knowledge"]), 29)

        # 3. 修订第 61 章：预填完整 >20KB 快照，不丢任何条目；意外清空列表时给出非阻断提醒，完结 open_threads 不误报。
        _, rev61_path = self.draft(61)
        rev61 = json.loads(rev61_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rev61["character_snapshots"]["沈砚"]["abilities_resources"]), 70)
        rev61["character_snapshots"]["沈砚"]["open_threads"] = []
        ok_clear_threads = self.run_tool("commit", rev61)
        self.assertNotIn("清空成了空列表", ok_clear_threads.stderr)

        rev61_wipe = json.loads(json.dumps(rev61, ensure_ascii=False))
        rev61_wipe["expected_state_revision"] = self.read_state()["state_revision"]
        rev61_wipe["character_snapshots"]["沈砚"]["knowledge"] = []
        warned_wipe = self.run_tool("commit", rev61_wipe)
        self.assertIn("WARNING: 角色快照「沈砚」把 已知信息（原有 70 项） 清空成了空列表", warned_wipe.stderr)
        # 恢复完整快照确保后续全量保真
        rev61["expected_state_revision"] = self.read_state()["state_revision"]
        rev61["character_snapshots"]["沈砚"]["open_threads"] = grown_shen["open_threads"]
        self.run_tool("commit", rev61)
        self.assertEqual(self.read_state()["characters"]["沈砚"], grown_shen)

        # 4. 退役钟离后再重新激活并写入 >10KB 快照，且长篇/导入/审查三份部署脚本 check 一致通过。
        retire63 = transaction(63)
        retire63["delta"]["character_changes"] = [{"name": "钟离", "change": "奉命秘密赴京述职，暂离北境线"}]
        retire63["delta"]["retired_characters"] = ["钟离"]
        retire63["context"]["active_character_names"] = ["沈砚", "顾长渊"]
        self.run_tool("commit", retire63)
        self.assertFalse((self.project / "追踪/角色状态/钟离.md").exists())
        guide64, _ = self.draft(64)
        self.assertNotIn("钟离", guide64["snapshot_files"])
        self.assertFalse((self.project / ".story/work/第064章/snapshots/钟离.json").exists())

        reactivate64 = transaction(64)
        returned_zhongli = rich_snapshot("钟离京城归来", 36)
        reactivate64["delta"]["character_changes"] = [{"name": "钟离", "change": "携兵部尚书密旨重返寒鸦关"}]
        reactivate64["context"]["active_character_names"] = ["沈砚", "顾长渊", "钟离"]
        reactivate64["character_snapshots"] = {"钟离": returned_zhongli}
        self.run_tool("commit", reactivate64)
        self.assertGreater(len((self.project / "追踪/角色状态/钟离.md").read_bytes()), 11000)

        for copy_rel in (
            "skills/story-long-write/scripts/tracking_commit.js",
            "skills/story-import/scripts/tracking_commit.js",
            "skills/story-review/scripts/tracking_commit.js",
        ):
            checked = subprocess.run(
                [NODE, str(ROOT / copy_rel), "check", "--project", str(self.project)],
                text=True, capture_output=True, check=False, encoding="utf-8",
            )
            self.assertEqual(checked.returncode, 0, f"{copy_rel}: {checked.stderr}")

    def test_crlf_derived_views_and_idempotent_append_retry(self) -> None:
        self.init()
        tx = transaction(1, character=True)
        self.run_tool("commit", tx)
        # Simulate Windows CRLF line endings in derived views and delta file
        ctx_path = self.project / "追踪/上下文.md"
        ctx_crlf = ctx_path.read_text(encoding="utf-8").replace("\n", "\r\n")
        ctx_path.write_bytes(ctx_crlf.encode("utf-8"))
        self.run_tool("check")

        # Also simulate CRLF on an already-written chapter delta during append retry
        state_before_ch2 = (self.project / "追踪/_tracking-state.json").read_bytes()
        delta_path = self.project / "追踪/逐章记录/第002章.md"
        tx2 = transaction(2, character=True)
        self.run_tool("commit", tx2)
        delta_crlf = delta_path.read_text(encoding="utf-8").replace("\n", "\r\n")
        # Restore state to before chapter 2 while leaving CRLF delta for chapter 2 on disk
        (self.project / "追踪/_tracking-state.json").write_bytes(state_before_ch2)
        delta_path.write_bytes(delta_crlf.encode("utf-8"))
        tx2_retry = transaction(2, character=True)
        self.run_tool("commit", tx2_retry)
        self.run_tool("check")

    def test_draft_matches_unpadded_outline_and_writes_atomically(self) -> None:
        self.init()
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "大纲/细纲_第1章.md").write_text(
            "### 第 1 章：夜雨来客\n- 字数目标：2000 字\n",
            encoding="utf-8",
        )
        _, draft_path = self.draft(1)
        doc = json.loads(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["chapter_title"], "夜雨来客")
        leftovers = list(draft_path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [], f"atomic draft write left temp files: {leftovers}")

    def test_delta_soft_warns_above_3kb_and_hard_rejects_above_64kb(self) -> None:
        self.init()
        over_3k = transaction(1)
        over_3k["delta"]["result"] = "江" * 1200  # ~3600 bytes > 3072B
        res = self.run_tool("commit", over_3k, expect=0)
        payload = json.loads(res.stdout)
        self.assertTrue(any("3072 bytes" in w for w in payload["warnings"]))
        self.assertIn("WARNING: chapter delta is", res.stderr)
        self.run_tool("check", extra=["--strict"])

        over_64k = transaction(2)
        over_64k["delta"]["result"] = "江" * 23000  # ~69000 bytes > 65536B
        before = self.read_state()
        rejected = self.run_tool("commit", over_64k, expect=2)
        self.assertIn("exceeds hard cap of 65536 bytes", rejected.stderr)
        self.assertEqual(self.read_state(), before)

    def test_allow_gap_permits_intentional_out_of_order_append_while_default_guards_typos(self) -> None:
        self.init()
        self.run_tool("commit", transaction(1))
        # Default append rejects chapter 3 after chapter 1 (typo protection).
        blocked = self.run_tool("commit", transaction(3), expect=2)
        self.assertIn("append chapter must be 2, got 3", blocked.stderr)
        self.assertIn("--allow-gap", blocked.stderr)

        # With --allow-gap, draft & commit for chapter 3 succeed with a clear gap warning.
        draft3 = subprocess.run(
            [NODE, str(TOOL), "draft", "--project", str(self.project), "--chapter", "3", "--allow-gap"],
            text=True, capture_output=True, check=False, encoding="utf-8",
        )
        self.assertEqual(draft3.returncode, 0, draft3.stderr)
        self.assertEqual(json.loads(draft3.stdout)["mode"], "append")

        gap_commit = self.run_tool("commit", transaction(3), extra=["--allow-gap"], expect=0)
        gap_payload = json.loads(gap_commit.stdout)
        self.assertEqual(gap_payload["last_committed_chapter"], 3)
        self.assertTrue(any("跳章提交" in w for w in gap_payload["warnings"]))

        # Default check exits 0 with missing_delta drift warning; --strict fails exit 2.
        soft_check = json.loads(self.run_tool("check", expect=0).stdout)
        self.assertTrue(any(w["type"] == "missing_delta" and w["chapter"] == 2 for w in soft_check["drift_warnings"]))
        self.run_tool("check", extra=["--strict"], expect=2)

        # Backfilling skipped chapter 2 via --allow-gap restores strict check cleanliness.
        backfill = self.run_tool("commit", transaction(2), extra=["--allow-gap"], expect=0)
        self.assertEqual(json.loads(backfill.stdout)["last_committed_chapter"], 3)
        self.run_tool("check", extra=["--strict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
