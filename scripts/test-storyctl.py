#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORYCTL_PATH = ROOT / "skills/story-long-write/scripts/storyctl.py"
SPEC = importlib.util.spec_from_file_location("storyctl", STORYCTL_PATH)
assert SPEC and SPEC.loader
storyctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storyctl)


def run_cli(*arguments: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(STORYCTL_PATH), *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"CLI did not return JSON: exit={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
        ) from error
    return completed, payload


class VisibleCharsTests(unittest.TestCase):
    def test_frozen_unicode_counting_contract(self) -> None:
        self.assertEqual(storyctl.count_visible_chars("甲\n乙"), 2)
        self.assertEqual(storyctl.count_visible_chars("甲\r\n乙"), 2)
        self.assertEqual(storyctl.count_visible_chars("甲\r乙"), 2)
        self.assertEqual(storyctl.count_visible_chars("中文"), 2)
        self.assertEqual(storyctl.count_visible_chars("😀"), 1)
        self.assertEqual(storyctl.count_visible_chars("e\u0301"), 2)
        self.assertEqual(storyctl.count_visible_chars("\ufeff正文"), 2)
        self.assertEqual(storyctl.count_visible_chars("正文\ufeff"), 3)
        self.assertEqual(storyctl.count_visible_chars("中文，。！"), 5)

        whitespace = "".join(
            chr(codepoint)
            for codepoint in [
                *range(0x0009, 0x000E),
                0x0020,
                0x0085,
                0x00A0,
                0x1680,
                *range(0x2000, 0x200B),
                0x2028,
                0x2029,
                0x202F,
                0x205F,
                0x3000,
            ]
        )
        self.assertEqual(storyctl.count_visible_chars(f"甲{whitespace}乙"), 2)

    def test_frontmatter_and_first_heading_are_not_body(self) -> None:
        body = "\ufeff---\r\ntitle: 第一章\r\ntags:\r\n  - test\r\n---\r\n# 第一章 标题\r\n正文😀\r\n"
        self.assertEqual(storyctl.count_visible_chars(body), 3)
        self.assertEqual(storyctl.count_visible_chars("---\n场景转换\n---\n正文"), 12)
        self.assertEqual(storyctl.count_visible_chars("# 第一章\n正文\n## 中段标题"), 8)

    def test_bands_and_status_boundaries(self) -> None:
        self.assertEqual(
            storyctl.compute_wordcount_bands(1200),
            {"internal": {"min": 1056, "max": 1344}, "user": {"min": 1020, "max": 1380}},
        )
        self.assertEqual(
            storyctl.compute_wordcount_bands(1001),
            {"internal": {"min": 881, "max": 1121}, "user": {"min": 851, "max": 1151}},
        )

        def status(actual: int) -> str:
            return storyctl.evaluate_wordcount("字" * actual, 1200)["status"]

        self.assertEqual(status(1056), "internal_pass")
        self.assertEqual(status(1344), "internal_pass")
        self.assertEqual(status(1055), "borderline")
        self.assertEqual(status(1020), "borderline")
        self.assertEqual(status(1345), "borderline")
        self.assertEqual(status(1380), "borderline")
        self.assertEqual(status(1019), "under")
        self.assertEqual(status(1381), "over")
        self.assertEqual(storyctl.evaluate_wordcount("", 1200)["invalid_reason"], "EMPTY_BODY")
        self.assertEqual(storyctl.evaluate_wordcount("正文", "12.5")["invalid_reason"], "INVALID_TARGET")
        self.assertEqual(
            storyctl.evaluate_wordcount("正文", "9007199254740992")["invalid_reason"],
            "INVALID_TARGET",
        )


class OutlineTargetTests(unittest.TestCase):
    def test_outline_target_accepts_utf8_bom_and_crlf(self) -> None:
        plain = "- 字数目标：1000 字\n- 字数口径：visible_chars_v1\n"
        self.assertEqual(storyctl.target_from_outline(plain), 1000)
        self.assertEqual(storyctl.target_from_outline("\ufeff" + plain), 1000)
        self.assertEqual(
            storyctl.target_from_outline("\ufeff" + plain.replace("\n", "\r\n")),
            1000,
        )

    def test_outline_target_rejections_remain_unchanged(self) -> None:
        with self.assertRaisesRegex(storyctl.WordcountError, "字数口径"):
            storyctl.target_from_outline(
                "- 字数目标：1000 字\n- 字数口径：VISIBLE_CHARS_V1\n"
            )
        with self.assertRaisesRegex(storyctl.WordcountError, "字数目标"):
            storyctl.target_from_outline(
                "- 字数目标：1000 字\n"
                "- 字数目标：1200 字\n"
                "- 字数口径：visible_chars_v1\n"
            )


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_reports_only_current_count_and_remaining_user_range(self) -> None:
        result = storyctl.checkpoint_wordcount("字" * 558, 2200, chapter=28)
        self.assertEqual(result["schema"], "story-wordcount-checkpoint/v1")
        self.assertEqual(result["actual"], 558)
        self.assertEqual(result["user_band"], {"min": 1870, "max": 2530})
        self.assertEqual(result["remaining_user_range"], {"min": 1312, "max": 1972})
        self.assertNotIn("beats", result)
        self.assertNotIn("resolution", result)


class StoryctlCliTests(unittest.TestCase):
    def test_chapter_check_cli_reads_bom_crlf_outline_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="storyctl-bom-outline-") as directory:
            project = Path(directory)
            (project / "大纲").mkdir()
            (project / "正文").mkdir()
            outline = project / "大纲/细纲_第001章.md"
            with outline.open("w", encoding="utf-8", newline="") as output:
                output.write("\ufeff- 字数目标：1000 字\r\n- 字数口径：visible_chars_v1\r\n")
            (project / "正文/第001章_测试.md").write_text(
                "# 第一章\n" + "字" * 999 + "。", encoding="utf-8"
            )
            tracking = storyctl._tracking_module()
            tracking.initialize(
                project,
                {
                    "schema_version": 1,
                    "book_title": "BOM 大纲测试",
                    "last_chapter": 0,
                    "context": {
                        "position": {
                            "volume": "第一卷",
                            "volume_start_chapter": 1,
                            "story_time": "当日",
                            "scene": "测试",
                        },
                        "long_term_constraints": ["只写批准内容。"],
                        "active_character_names": [],
                        "continuity_risks": [],
                        "recent_chapters": [],
                        "next_chapter_commitments": [],
                    },
                    "character_snapshots": {},
                    "foreshadow": [],
                    "timeline_events": [],
                },
            )
            # 改稿流程留在 正文/ 的原稿备份不算本章正文（否则「本章正文不唯一」直接失败）。
            (project / "正文/第001章_测试_原稿_20260925.md").write_text(
                "# 第一章\n" + "旧" * 500 + "。", encoding="utf-8"
            )
            completed, result = run_cli(
                "chapter", "check", "--project", str(project), "--chapter", "1"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["schema"], "story-chapter-check/v1")
        self.assertEqual(result["length"]["target"], 1000)
        self.assertEqual(result["length"]["status"], "internal_pass")

    def test_wordcount_measure_returns_actual_without_a_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="storyctl-measure-") as directory:
            body = Path(directory) / "chapter.md"
            body.write_text("# 第一章\n正文 😀", encoding="utf-8")
            completed, result = run_cli(
                "wordcount", "measure", "--file", str(body), "--chapter", "1"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["schema"], "story-wordcount-measurement/v1")
        self.assertEqual(result["metric"], "visible_chars_v1")
        self.assertEqual(result["actual"], 3)
        self.assertEqual(result["status"], "measured")

    def test_wordcount_check_returns_structured_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="storyctl-check-") as directory:
            body = Path(directory) / "chapter.md"
            body.write_text("# 第一章\n" + "字" * 1020, encoding="utf-8")
            completed, result = run_cli(
                "wordcount",
                "check",
                "--file",
                str(body),
                "--target",
                "1200",
                "--chapter",
                "1",
                "--case-id",
                "boundary",
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["schema"], "story-wordcount-result/v1")
        self.assertEqual(result["metric"], "visible_chars_v1")
        self.assertEqual(result["chapter"], "1")
        self.assertEqual(result["case_id"], "boundary")
        self.assertEqual(result["actual"], 1020)
        self.assertEqual(result["status"], "borderline")
        self.assertEqual(result["internal_band"], {"min": 1056, "max": 1344, "status": "fail"})
        self.assertEqual(result["user_band"], {"min": 1020, "max": 1380, "status": "pass"})

    def test_cli_errors_are_json_and_nonzero(self) -> None:
        completed, result = run_cli("wordcount", "check", "--file", "missing.md", "--target", "1200")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["invalid_reason"], "INVALID_FILE")

        completed, result = run_cli("unknown-command")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(result["invalid_reason"], "INVALID_ARGUMENT")

    def test_demo_outlines_and_bodies_use_the_same_metric(self) -> None:
        book = ROOT / "demo/长篇/让你管账号，你高燃混剪炸全网"
        outlines = sorted((book / "大纲").glob("细纲_第*.md"))
        self.assertGreaterEqual(len(outlines), 1)
        # 导入的章节其「字数目标」是从已发布正文反推的，因此逐字相等；
        # 导入之后由 skill 写出的章节只需落在内部带内（作者可接受偏短的成稿）。
        state = json.loads(
            (book / "追踪/_tracking-state.json").read_text(encoding="utf-8")
        )
        imported_through = state["imported_through_chapter"]
        for outline in outlines:
            target = storyctl.target_from_outline(outline.read_text(encoding="utf-8"))

            chapter = outline.stem.removeprefix("细纲_第").removesuffix("章")
            bodies = list((book / "正文").glob(f"第{chapter}章_*"))
            self.assertEqual(len(bodies), 1, outline.name)
            completed, result = run_cli(
                "wordcount",
                "check",
                "--file",
                str(bodies[0]),
                "--target",
                str(target),
                "--chapter",
                chapter,
            )
            self.assertEqual(completed.returncode, 0, f"{outline.name}: {completed.stderr}")
            self.assertEqual(result["status"], "internal_pass", outline.name)
            if int(chapter) <= imported_through:
                self.assertEqual(result["target"], result["actual"], outline.name)


if __name__ == "__main__":
    unittest.main()
