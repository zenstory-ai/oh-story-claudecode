#!/usr/bin/env python3
"""Runtime E2E for check, commit, and accept-current-length."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORYCTL = ROOT / "skills/story-long-write/scripts/storyctl.py"
TRACKING = ROOT / "skills/story-long-write/scripts/tracking_commit.py"


def position() -> dict[str, object]:
    return {"volume": "第一卷", "volume_start_chapter": 1, "story_time": "当日", "scene": "剪辑室"}


def initial_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "book_title": "最终闭环测试",
        "last_chapter": 0,
        "context": {
            "position": position(),
            "long_term_constraints": ["只写批准内容。"],
            "active_character_names": [],
            "continuity_risks": [],
            "recent_chapters": [],
            "next_chapter_commitments": [],
        },
        "character_snapshots": {},
        "foreshadow": [],
        "timeline_events": [],
    }


def transaction(chapter: int, revision: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "append",
        "chapter": chapter,
        "chapter_title": f"闭环测试·{chapter}",
        "expected_state_revision": revision,
        "delta": {
            "result": f"第{chapter}章完成。",
            "character_changes": [],
            "foreshadow_changes": [],
            "timeline_events": [],
            "constraints": [],
            "next_chapter_commitments": ["继续批准剧情。"],
        },
        "context": {
            "position": position(),
            "long_term_constraints": ["只写批准内容。"],
            "active_character_names": [],
            "continuity_risks": [],
        },
        "character_snapshots": {},
    }


class FinalChapterFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="final-wordcount-flow-")
        self.root = Path(self.temporary.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.run_tracking("init", initial_document())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_input(self, label: str, document: dict[str, object]) -> Path:
        path = self.root / f"{label}-{os.urandom(4).hex()}.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def run_process(self, args: list[str], *, expect: int = 0) -> dict[str, object]:
        completed = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False)
        self.assertEqual(completed.returncode, expect, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
        lines = completed.stdout.strip().splitlines()
        self.assertTrue(lines, completed.stderr)
        return json.loads(lines[-1])

    def run_tracking(self, command: str, document: dict[str, object]) -> dict[str, object]:
        path = self.write_input(command, document)
        return self.run_process(
            [sys.executable, str(TRACKING), command, "--project", str(self.project), "--input", str(path)]
        )

    def run_chapter(
        self, command: str, chapter: int, *, document: dict[str, object] | None = None, expect: int = 0
    ) -> dict[str, object]:
        args = [
            sys.executable, str(STORYCTL), "chapter", command,
            "--project", str(self.project), "--chapter", str(chapter),
        ]
        if document is not None:
            args.extend(["--input", str(self.write_input(f"chapter-{chapter}", document))])
        return self.run_process(args, expect=expect)

    def state(self) -> dict[str, object]:
        return json.loads((self.project / "追踪/_tracking-state.json").read_text(encoding="utf-8"))

    def write_contract(self, chapter: int, actual: int, *, target: int = 1000, blocking: bool = False) -> None:
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "正文").mkdir(exist_ok=True)
        (self.project / "大纲" / f"细纲_第{chapter:03d}章.md").write_text(
            f"- 字数目标：{target} 字\n- 字数口径：visible_chars_v1\n\n"
            "| # | 情节点（谁做了什么） | 功能标签 | 执行边界 |\n|---|---|---|---|\n"
            "| 1 | 江晨完成一次审核 | 推进 | 不新增支线 |\n",
            encoding="utf-8",
        )
        prefix = "这不是夸奖，而是命令。" if blocking else ""
        fill = max(0, actual - len(prefix) - 1)
        (self.project / "正文" / f"第{chapter:03d}章_测试.md").write_text(
            f"# 第{chapter}章\n{prefix}" + "字" * fill + "。",
            encoding="utf-8",
        )

    def test_complete_user_flow_without_persisted_approval_state(self) -> None:
        # Checkpoint is pure: one call changes neither tracking state nor prose.
        segment = self.root / "segment.md"
        segment.write_text("# 前半段\n" + "字" * 500, encoding="utf-8")
        before = self.state()
        checkpoint = self.run_process(
            [sys.executable, str(STORYCTL), "wordcount", "checkpoint", "--file", str(segment), "--target", "1000"]
        )
        self.assertEqual(checkpoint["remaining_user_range"], {"min": 350, "max": 650})
        self.assertEqual(self.state(), before)

        # 1: length and blocking quality pass -> normal commit.
        self.write_contract(1, 1000)
        checked = self.run_chapter("check", 1)
        self.assertEqual(checked["quality"]["status"], "pass")
        self.assertEqual(checked["available_actions"], ["commit"])
        committed = self.run_chapter("commit", 1, document=transaction(1, self.state()["state_revision"]))
        self.assertTrue(committed["tracking_committed"])

        # 2: under never auto-commits; accept re-reads changed body and target, then commits once.
        self.write_contract(2, 800)
        checked = self.run_chapter("check", 2)
        self.assertEqual(
            checked["available_actions"],
            ["accept-current-length", "revise-outline-or-target", "discard"],
        )
        self.assertIsNone(checked["compression"])
        self.assertEqual(checked["state_revision"], self.state()["state_revision"])
        rejected = self.run_chapter(
            "commit", 2, document=transaction(2, self.state()["state_revision"]), expect=2
        )
        self.assertIn("outside the user band", rejected["message"])
        self.assertEqual(self.state()["last_committed_chapter"], 1)
        self.write_contract(2, 801, target=1100)
        accepted = self.run_chapter(
            "accept-current-length", 2, document=transaction(2, self.state()["state_revision"])
        )
        self.assertTrue(accepted["tracking_committed"])
        record = self.state()["wordcount_records"]["2"]
        self.assertEqual((record["target"], record["actual"], record["status"]), (1100, 801, "under"))
        self.assertEqual(record["resolution"], "accepted_current_length")

        # 3: over offers exactly one net-delete pass with deterministic removal ranges.
        self.write_contract(3, 1200)
        checked = self.run_chapter("check", 3)
        self.assertEqual(checked["length"]["status"], "over")
        self.assertEqual(
            checked["available_actions"],
            ["compress-once", "accept-current-length", "revise-outline-or-target", "discard"],
        )
        self.assertEqual(
            checked["compression"],
            {
                "mode": "single_pass_remove_only",
                "remove_to_internal_band": {"min": 80, "max": 320},
                "remove_to_user_band": {"min": 50, "max": 350},
            },
        )
        rejected = self.run_chapter(
            "commit", 3, document=transaction(3, self.state()["state_revision"]), expect=2
        )
        self.assertIn("outside the user band", rejected["message"])
        self.assertEqual(self.state()["last_committed_chapter"], 2)

        # Simulate the one allowed compression pass; a fresh check now enters the band and commits.
        self.write_contract(3, 1100)
        checked = self.run_chapter("check", 3)
        self.assertEqual(checked["length"]["status"], "internal_pass")
        self.assertEqual(checked["available_actions"], ["commit"])
        self.assertIsNone(checked["compression"])
        self.run_chapter("commit", 3, document=transaction(3, self.state()["state_revision"]))

        # 4: blocking quality failure cannot commit; after an explicit quality fix, next chapter proceeds.
        self.write_contract(4, 1200, blocking=True)
        failed = self.run_chapter("check", 4, expect=2)
        self.assertEqual(failed["quality"]["status"], "fail")
        self.assertEqual(failed["available_actions"], [])
        self.assertIsNone(failed["compression"])
        blocked = self.run_chapter(
            "commit", 4, document=transaction(4, self.state()["state_revision"]), expect=2
        )
        self.assertIn("blocking quality", blocked["message"])
        self.assertEqual(self.state()["last_committed_chapter"], 3)
        self.write_contract(4, 1000)
        self.run_chapter("commit", 4, document=transaction(4, self.state()["state_revision"]))

        state = self.state()
        self.assertEqual(state["last_committed_chapter"], 4)
        self.assertEqual(set(state["wordcount_records"]), {"1", "2", "3", "4"})
        self.assertNotIn("wordcount_events", state)
        self.assertNotIn("wordcount_policy", state)

    def test_chapter_work_dir_survives_failure_and_is_removed_after_commit(self) -> None:
        work = self.project / ".story/work/第001章"
        work.mkdir(parents=True)
        memory = self.project / ".story/作者记忆"
        memory.mkdir(parents=True)
        (work / "前组.md").write_text("# 前组\n" + "字" * 400, encoding="utf-8")
        (work / "writer_prompt.md").write_text("prompt", encoding="utf-8")
        tracking_input = work / "tracking.json"

        def commit(expect: int) -> dict[str, object]:
            tracking_input.write_text(
                json.dumps(transaction(1, self.state()["state_revision"]), ensure_ascii=False), encoding="utf-8"
            )
            return self.run_process([
                sys.executable, str(STORYCTL), "chapter", "commit", "--project", str(self.project),
                "--chapter", "1", "--input", str(tracking_input),
            ], expect=expect)

        # A rejected commit keeps every scratch file so the same transaction can be rerun.
        self.write_contract(1, 800)
        rejected = commit(2)
        self.assertIn("outside the user band", rejected["message"])
        self.assertTrue(tracking_input.is_file())
        self.assertTrue((work / "前组.md").is_file())

        self.write_contract(1, 1000)
        committed = commit(0)
        self.assertTrue(committed["tracking_committed"])
        self.assertEqual(committed["work_dir_removed"], ".story/work/第001章")
        self.assertFalse(work.exists())
        self.assertFalse((self.project / ".story/work").exists())
        # Book-level author memory shares .story/ and must never be touched.
        self.assertTrue(memory.is_dir())
        self.assertEqual(sorted(path.name for path in (self.project / "正文").iterdir()), ["第001章_测试.md"])

        # No work dir for the next chapter is simply reported as nothing to remove.
        self.write_contract(2, 1000)
        second = self.run_chapter("commit", 2, document=transaction(2, self.state()["state_revision"]))
        self.assertIsNone(second["work_dir_removed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
