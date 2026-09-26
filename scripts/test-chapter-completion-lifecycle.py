#!/usr/bin/env python3
"""Runtime E2E for check, commit, and accept-current-length."""

from __future__ import annotations

import json
import os
import shutil
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

    def run_process(
        self, args: list[str], *, expect: int = 0, env: dict[str, str] | None = None
    ) -> dict[str, object]:
        completed = subprocess.run(
            args, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False, env=env
        )
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
        self, command: str, chapter: int, *, document: dict[str, object] | None = None, expect: int = 0,
        extra: list[str] | None = None, env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        args = [
            sys.executable, str(STORYCTL), "chapter", command,
            "--project", str(self.project), "--chapter", str(chapter), *(extra or []),
        ]
        if document is not None:
            args.extend(["--input", str(self.write_input(f"chapter-{chapter}", document))])
        return self.run_process(args, expect=expect, env=env)

    def state(self) -> dict[str, object]:
        return json.loads((self.project / "追踪/_tracking-state.json").read_text(encoding="utf-8"))

    def write_contract(
        self, chapter: int, actual: int, *, target: int = 1000, blocking: bool = False, extra: str = ""
    ) -> None:
        (self.project / "大纲").mkdir(exist_ok=True)
        (self.project / "正文").mkdir(exist_ok=True)
        (self.project / "大纲" / f"细纲_第{chapter:03d}章.md").write_text(
            f"- 字数目标：{target} 字\n- 字数口径：visible_chars_v1\n{extra}\n"
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

    def test_fix_punctuation_normalizes_body_before_the_single_check(self) -> None:
        self.write_contract(1, 1000)
        body = self.project / "正文" / "第001章_测试.md"
        body.write_text(body.read_text(encoding="utf-8").replace("字字字字", "字……字", 1), encoding="utf-8")
        plain = self.run_chapter("check", 1, expect=1)
        self.assertEqual(plain["status"], "blocked")
        self.assertEqual(plain["quality"]["status"], "fail")
        self.assertNotIn("punctuation_fixed", plain)
        args = [sys.executable, str(STORYCTL), "chapter", "check", "--project", str(self.project),
                "--chapter", "1", "--fix-punctuation"]
        fixed = self.run_process(args)
        self.assertTrue(fixed["punctuation_fixed"])
        self.assertEqual(fixed["quality"]["status"], "pass")
        self.assertNotIn("……", body.read_text(encoding="utf-8"))
        self.assertFalse(self.run_process(args)["punctuation_fixed"])

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
        self.assertEqual(rejected["error_code"], "LENGTH_OUT_OF_BAND")
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
        failed = self.run_chapter("check", 4, expect=1)
        self.assertEqual(failed["status"], "blocked")
        self.assertEqual(failed["quality"]["status"], "fail")
        self.assertEqual(failed["available_actions"], [])
        self.assertIsNone(failed["compression"])
        blocked = self.run_chapter(
            "commit", 4, document=transaction(4, self.state()["state_revision"]), expect=2
        )
        self.assertIn("blocking quality", blocked["message"])
        self.assertEqual((blocked["status"], blocked["error_code"]), ("error", "QUALITY_BLOCKED"))
        self.assertEqual(self.state()["last_committed_chapter"], 3)
        self.write_contract(4, 1000)
        self.run_chapter("commit", 4, document=transaction(4, self.state()["state_revision"]))

        state = self.state()
        self.assertEqual(state["last_committed_chapter"], 4)
        self.assertEqual(set(state["wordcount_records"]), {"1", "2", "3", "4"})
        self.assertNotIn("wordcount_events", state)
        self.assertNotIn("wordcount_policy", state)

    def test_author_range_from_outline_or_flags_replaces_the_default_band(self) -> None:
        # 1080 字对目标 1200：默认 ±12% 内部带（1056 起）会判 internal_pass；作者说 1100-1300 就是欠长。
        self.write_contract(1, 1080, target=1200, extra="- 字数范围：1100-1300\n")
        checked = self.run_chapter("check", 1)
        self.assertEqual(checked["length"]["status"], "under")
        self.assertEqual(checked["length"]["band_source"], "author")
        self.assertEqual(checked["status"], "needs_decision")
        # 命令行给的区间优先于细纲；作者区间内提交，记录带上 author_range，state 仍能通过校验。
        widened = ["--min-chars", "1000", "--max-chars", "1300"]
        self.assertEqual(self.run_chapter("check", 1, extra=widened)["status"], "ready")
        self.run_chapter("commit", 1, document=transaction(1, self.state()["state_revision"]), extra=widened)
        record = self.state()["wordcount_records"]["1"]
        self.assertEqual(record["author_range"], {"min": 1000, "max": 1300})
        self.assertEqual(record["status"], "internal_pass")
        self.run_process([sys.executable, str(TRACKING), "check", "--project", str(self.project)])
        # 超长时的删除字数也按作者区间算。
        self.write_contract(2, 1400, target=1200, extra="- 字数范围：1100-1300\n")
        over = self.run_chapter("check", 2)
        self.assertEqual(over["compression"]["remove_to_user_band"], {"min": 100, "max": 300})
        self.assertEqual(over["compression"]["remove_to_internal_band"], {"min": 100, "max": 300})

    def test_accept_current_length_has_a_floor_and_needs_one_compression_first(self) -> None:
        self.write_contract(1, 289, target=1000)
        refused = self.run_chapter(
            "accept-current-length", 1, document=transaction(1, self.state()["state_revision"]), expect=2
        )
        self.assertEqual((refused["status"], refused["error_code"]), ("error", "BELOW_ACCEPT_FLOOR"))
        self.assertEqual(self.state()["last_committed_chapter"], 0)
        self.run_chapter(
            "accept-current-length", 1, document=transaction(1, self.state()["state_revision"]), extra=["--force"]
        )
        self.assertEqual(self.state()["wordcount_records"]["1"]["actual"], 289)

        self.write_contract(2, 1400)
        refused = self.run_chapter(
            "accept-current-length", 2, document=transaction(2, self.state()["state_revision"]), expect=2
        )
        self.assertEqual(refused["error_code"], "COMPRESSION_REQUIRED")
        self.assertEqual(self.run_chapter("check", 2)["available_actions"][0], "compress-once")
        # 删一个字不算压缩：基线 1400、作者范围上限 1150，至少要删到差额（250）的一半，即 ≤1275。
        for token_cut in (1399, 1276):
            self.write_contract(2, token_cut)
            refused = self.run_chapter(
                "accept-current-length", 2, document=transaction(2, self.state()["state_revision"]), expect=2
            )
            self.assertEqual(refused["error_code"], "COMPRESSION_REQUIRED", token_cut)
            self.assertIn("1275", refused["message"])
        self.write_contract(2, 1270)  # 真压过一次仍超长：现在可以接受。
        accepted = self.run_chapter(
            "accept-current-length", 2, document=transaction(2, self.state()["state_revision"])
        )
        self.assertTrue(accepted["tracking_committed"])
        self.assertEqual(accepted["work_dir_removed"], ".story/work/第002章")

    def test_missing_node_is_a_tool_error_not_a_prose_finding(self) -> None:
        self.write_contract(1, 1000)
        empty_bin = self.root / "empty-bin"
        empty_bin.mkdir()
        env = {**os.environ, "PATH": str(empty_bin)}
        checked = self.run_chapter("check", 1, expect=3, env=env)
        self.assertEqual(checked["status"], "tool_unavailable")
        self.assertEqual(checked["quality"]["status"], "unavailable")
        self.assertEqual(checked["quality"]["blocking_findings"], [])
        self.assertIn("Node.js", checked["quality"]["tool_errors"][0]["message"])
        self.assertEqual(checked["length"]["status"], "internal_pass")
        refused = self.run_chapter(
            "commit", 1, document=transaction(1, self.state()["state_revision"]), expect=3, env=env
        )
        self.assertEqual((refused["schema"], refused["error_code"]), ("story-chapter-error/v1", "TOOL_UNAVAILABLE"))

    def test_findings_pass_through_and_semantic_advisories_are_counted(self) -> None:
        # 用桩检测器替身跑真实 storyctl：finding 原样透传，review 缺省按语义类计数。
        runtime = self.root / "runtime"
        runtime.mkdir()
        for name in ("storyctl.py", "wordcount_core.py", "tracking_commit.py"):
            shutil.copy2(STORYCTL.parent / name, runtime / name)
        findings = [
            {"type": "voice", "severity": "advisory", "review": "semantic", "line": 1},
            {"type": "space", "severity": "advisory", "review": "mechanical", "line": 2},
            {"type": "legacy", "severity": "advisory", "line": 3},
        ]
        (runtime / "check-ai-patterns.js").write_text(
            f"process.stdout.write(JSON.stringify({{findings: {json.dumps(findings)}}}))\n", encoding="utf-8"
        )
        # 退化检测器的 advisory（工程词疑似泄漏）不带 review：它不是 AI 味，不计入触发去 AI 味审查的语义条数。
        degeneration = [{"type": "meta-leak", "severity": "advisory", "line": 4}]
        (runtime / "check-degeneration.js").write_text(
            f"process.stdout.write(JSON.stringify({{findings: {json.dumps(degeneration)}}}))\n", encoding="utf-8"
        )
        for name in ("normalize-punctuation.js", "check-outline-copy.js"):
            (runtime / name).write_text("process.exit(0)\n", encoding="utf-8")
        self.write_contract(1, 1000)
        checked = self.run_process([
            sys.executable, str(runtime / "storyctl.py"), "chapter", "check",
            "--project", str(self.project), "--chapter", "1",
        ])
        self.assertEqual(
            checked["quality"]["advisories"],
            [{"source": "ai-pattern", **row} for row in findings]
            + [{"source": "degeneration", **row, "review": "mechanical"} for row in degeneration],
        )
        self.assertEqual(checked["quality"]["semantic_advisories"], 2)
        self.assertEqual(checked["status"], "ready")

    def test_revision_goes_through_storyctl_and_remeasures_the_body(self) -> None:
        self.write_contract(1, 1000)
        self.run_chapter("commit", 1, document=transaction(1, self.state()["state_revision"]))
        self.write_contract(1, 950)
        draft = self.run_process([
            sys.executable, str(TRACKING), "draft", "--project", str(self.project), "--chapter", "1",
        ])
        self.assertEqual(draft["mode"], "revision")
        committed = self.run_process([
            sys.executable, str(STORYCTL), "chapter", "commit", "--project", str(self.project),
            "--chapter", "1", "--input", draft["draft"],
        ])
        self.assertEqual(committed["mode"], "revision")
        self.assertEqual(committed["work_dir_removed"], ".story/work/第001章")
        self.assertEqual(self.state()["wordcount_records"]["1"]["actual"], 950)
        self.assertIn("第1章完成。", (self.project / "追踪/逐章记录/第001章.md").read_text(encoding="utf-8"))

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
