#!/usr/bin/env python3
"""Behavior regressions for the hot-path document budget CLI."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check-doc-budget.mjs"


class DocBudgetCliTests(unittest.TestCase):
    def run_checker(self, files: dict[str, str], manifest: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            manifest_path = root / "budget.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            return subprocess.run(
                ["node", str(CHECKER), "--root", str(root), "--manifest", str(manifest_path)],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

    def test_computes_non_whitespace_sum_for_group_only_files(self) -> None:
        result = self.run_checker(
            {"a.md": "甲 乙\n丙", "nested/b.md": "1\t2 3 4"},
            {
                "files": [{"path": "a.md", "budget": 3, "why": "fixture"}],
                "paths": [{"label": "fixture route", "budget": 7, "files": ["a.md", "nested/b.md"]}],
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, re.compile(r"\b7\s*/\s*7\s+0\s+fixture route\s+\[ok\]"))

    def test_path_ceiling_blocks_branch_over_limit_unless_exempt(self) -> None:
        files = {"base.md": "甲" * 6, "big.md": "乙" * 5}
        paths = [
            {"label": "writing", "files": ["base.md"],
             "branches": [{"label": "plain", "files": [], "budget": 10},
                          {"label": "heavy", "files": ["big.md"], "budget": 10}]},
            {"label": "planning", "budget": 20, "files": ["base.md", "big.md"]},
        ]
        over = self.run_checker(files, {"files": [], "paths": paths,
                                        "path_ceiling": {"limit": 10, "exempt": ["planning"], "why": "fixture"}})
        self.assertEqual(over.returncode, 1, over.stdout)
        self.assertIn("路径「writing（heavy）」超过硬上限 10 字（实际 11，预算 10）", over.stdout)
        self.assertNotIn("writing（plain）」超过硬上限", over.stdout)
        self.assertNotIn("路径「planning」超过硬上限", over.stdout)
        self.assertIn("planning  [ok，上限豁免]", over.stdout)

        # 预算值本身也不许调过上限：实际没超、budget 写大了同样拦。
        loose = self.run_checker(files, {"files": [], "paths": [{"label": "w", "budget": 11, "files": ["base.md"]}],
                                         "path_ceiling": {"limit": 10, "exempt": [], "why": "fixture"}})
        self.assertEqual(loose.returncode, 1, loose.stdout)
        self.assertIn("路径「w」超过硬上限 10 字（实际 6，预算 11）", loose.stdout)

    def test_path_ceiling_rejects_unknown_exempt_label(self) -> None:
        result = self.run_checker({"a.md": "甲"}, {"files": [], "paths": [{"label": "w", "budget": 5, "files": ["a.md"]}],
                                                   "path_ceiling": {"limit": 10, "exempt": ["不存在"], "why": "fixture"}})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("path_ceiling.exempt 列了不存在的路径：不存在", result.stdout)

    def test_agent_path_counts_preloaded_skill(self) -> None:
        agent = "skills/story-setup/references/templates/agents/w.md"
        result = self.run_checker(
            {agent: "---\nname: w\nskills: [pre]\n---\n正文", "skills/pre/SKILL.md": "预加载", "r.md": "参考"},
            {"files": [], "paths": [{"label": "writer call", "agent": agent, "budget": 100, "files": ["r.md"]}]},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        # 模板全文去空白 + 参考 2 字 + 预加载 SKILL 3 字
        weight = len("---name:wskills:[pre]---正文") + 2 + 3
        self.assertRegex(result.stdout, re.compile(rf"\b{weight}\s*/\s*100\b.*writer call"))

    def test_preloading_agent_without_agent_path_fails(self) -> None:
        agent = "skills/story-setup/references/templates/agents/w.md"
        result = self.run_checker(
            {agent: "---\nname: w\nskills: [pre]\n---\n正文", "skills/pre/SKILL.md": "预加载"},
            {"files": [], "paths": []},
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("预加载了 pre，但没有登记 agent 路径", result.stdout)

    def test_block_list_preload_is_counted_too(self) -> None:
        agent = "skills/story-setup/references/templates/agents/w.md"
        result = self.run_checker(
            {agent: "---\nname: w\nskills:\n  - pre\n---\n正文", "skills/pre/SKILL.md": "预加载"},
            {"files": [], "paths": []},
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("预加载了 pre，但没有登记 agent 路径", result.stdout)

    def test_unreadable_preload_form_fails(self) -> None:
        agent = "skills/story-setup/references/templates/agents/w.md"
        result = self.run_checker({agent: "---\nname: w\nskills: pre\n---\n正文"}, {"files": [], "paths": []})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("skills 预加载写法认不出", result.stdout)

    def test_fails_when_path_sum_exceeds_budget(self) -> None:
        result = self.run_checker(
            {"a.md": "abc", "b.md": "1234"},
            {
                "files": [],
                "paths": [{"label": "overflow route", "budget": 6, "files": ["a.md", "b.md"]}],
            },
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("路径「overflow route」超预算 1 字（7 > 6）", result.stdout)

    def test_computes_each_branch_with_shared_files(self) -> None:
        result = self.run_checker(
            {"common.md": "abc", "left.md": "1234", "right.md": "甲 乙"},
            {
                "files": [],
                "paths": [
                    {
                        "label": "branched route",
                        "files": ["common.md"],
                        "branches": [
                            {"label": "left", "budget": 7, "files": ["left.md"]},
                            {"label": "right", "budget": 5, "files": ["right.md"]},
                        ],
                    }
                ],
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, re.compile(r"\b7\s*/\s*7\s+0\s+branched route（left）\s+\[ok\]"))
        self.assertRegex(result.stdout, re.compile(r"\b5\s*/\s*5\s+0\s+branched route（right）\s+\[ok\]"))

    def stacking_manifest(self, slots: list[list[str]], budget: int = 12) -> dict:
        return {
            "files": [],
            "path_ceiling": {"limit": 12, "exempt": [], "why": "fixture"},
            "paths": [{
                "label": "solo",
                "files": ["base.md"],
                "branches": [
                    {"label": "技法甲", "budget": 12, "files": ["tech-a.md"]},
                    {"label": "技法乙", "budget": 12, "files": ["tech-b.md"]},
                    {"label": "兜底", "budget": 12, "files": ["fallback.md"]},
                ],
                "stacking": {"budget": budget, "slots": slots},
            }],
        }

    STACK_FILES = {"base.md": "基" * 5, "tech-a.md": "甲" * 4, "tech-b.md": "乙" * 3, "fallback.md": "兜" * 4}

    def test_stacking_checks_the_worst_combination_of_co_occurring_branches(self) -> None:
        # 每条分支单独看都在 12 以内（9/8/9），但技法和兜底会在同一次调用里叠加：5+4+4=13。
        over = self.run_checker(self.STACK_FILES, self.stacking_manifest([["技法甲", "技法乙"], ["兜底"]]))
        self.assertEqual(over.returncode, 1, over.stdout)
        self.assertIn("路径「solo（最坏叠加：技法甲＋兜底）」超过硬上限 12 字（实际 13，预算 12）", over.stdout)
        # 变异：同样的分支当成互斥（不登记叠加）就放过去了——这正是叠加语义要堵的洞。
        exclusive = self.stacking_manifest([])
        del exclusive["paths"][0]["stacking"]
        self.assertEqual(self.run_checker(self.STACK_FILES, exclusive).returncode, 0)
        # 变异：两个技法放进同一个槽是互斥的，不会三份一起算；拆成两个槽才会。
        same_slot = self.run_checker(self.STACK_FILES, self.stacking_manifest([["技法甲", "技法乙"]]))
        self.assertEqual(same_slot.returncode, 0, same_slot.stdout)
        self.assertRegex(same_slot.stdout, re.compile(r"\b9\s*/\s*12\s+3\s+solo（最坏叠加：技法甲）"))
        split = self.run_checker(self.STACK_FILES, self.stacking_manifest([["技法甲"], ["技法乙"]], budget=11))
        self.assertEqual(split.returncode, 1, split.stdout)
        self.assertIn("路径「solo（最坏叠加：技法甲＋技法乙）」超预算 1 字（12 > 11）", split.stdout)

    def test_stacking_counts_a_shared_file_once(self) -> None:
        files = {**self.STACK_FILES, "fallback.md": "甲" * 1}
        manifest = self.stacking_manifest([["技法甲"], ["兜底"]])
        manifest["paths"][0]["branches"][2]["files"] = ["tech-a.md", "fallback.md"]
        result = self.run_checker(files, manifest)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, re.compile(r"\b10\s*/\s*12\s+2\s+solo（最坏叠加：技法甲＋兜底）"))

    def test_stacking_rejects_unknown_or_repeated_branch(self) -> None:
        unknown = self.run_checker(self.STACK_FILES, self.stacking_manifest([["技法丙"]]))
        self.assertEqual(unknown.returncode, 1, unknown.stdout)
        self.assertIn("stacking 列了不存在的分支：技法丙", unknown.stdout)
        repeated = self.run_checker(self.STACK_FILES, self.stacking_manifest([["技法甲"], ["技法甲"]]))
        self.assertEqual(repeated.returncode, 1, repeated.stdout)
        self.assertIn("出现在两个槽里", repeated.stdout)

    def test_section_anchor_counts_only_that_section(self) -> None:
        doc = "# 手册\n前言\n## 决策路由\n路由\n### 细分\n细\n```\n## 围栏里不算标题\n```\n## 第二节\n很长很长很长\n"
        result = self.run_checker(
            {"m.md": doc},
            {"files": [], "paths": [{"label": "按节读", "budget": 100,
                                     "files": ["m.md#决策路由", "m.md#第二节"]}]},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        routed = len(re.sub(r"\s", "", "## 决策路由\n路由\n### 细分\n细\n```\n## 围栏里不算标题\n```"))
        second = len(re.sub(r"\s", "", "## 第二节\n很长很长很长"))
        self.assertRegex(result.stdout, re.compile(rf"\b{routed + second}\s*/\s*100\b.*按节读"))
        # 整份与它的小节同在一次调用里时，小节不重复计。
        whole = self.run_checker(
            {"m.md": doc},
            {"files": [], "paths": [{"label": "整读", "budget": 100, "files": ["m.md", "m.md#第二节"]}]},
        )
        whole_weight = len(re.sub(r"\s", "", doc))
        self.assertRegex(whole.stdout, re.compile(rf"\b{whole_weight}\s*/\s*100\b.*整读"))
        missing = self.run_checker(
            {"m.md": doc},
            {"files": [], "paths": [{"label": "拼错", "budget": 100, "files": ["m.md#不存在的节"]}]},
        )
        self.assertEqual(missing.returncode, 1, missing.stdout)
        self.assertIn("路径「拼错」登记的小节找不到：m.md#不存在的节", missing.stdout)

    def test_generated_brief_is_measured_by_running_its_script(self) -> None:
        script = "import json, sys\nassert sys.argv[1] == '--project'\nprint(json.dumps({'chars': int(sys.argv[3])}))\n"
        ok = self.run_checker(
            {"gen.py": script, "a.md": "甲乙"},
            {"files": [], "paths": [{"label": "任务包", "budget": 50, "files": ["a.md"],
                                     "generated": [{"script": "gen.py", "args": ["40"]}]}]},
        )
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertRegex(ok.stdout, re.compile(r"\b42\s*/\s*50\s+8\s+任务包"))
        broken = self.run_checker(
            {"gen.py": "import sys\nsys.exit(2)\n"},
            {"files": [], "paths": [{"label": "任务包", "budget": 50, "files": [],
                                     "generated": [{"script": "gen.py", "args": []}]}]},
        )
        self.assertEqual(broken.returncode, 1, broken.stdout)
        self.assertIn("没给出 chars（退出码 2）", broken.stdout)

    def test_path_ceiling_limit_must_be_a_positive_number(self) -> None:
        for limit in (None, 0, -5, "35000"):
            ceiling = {"exempt": [], "why": "fixture"}
            if limit is not None:
                ceiling["limit"] = limit
            result = self.run_checker({"a.md": "甲"}, {"files": [], "path_ceiling": ceiling,
                                                       "paths": [{"label": "w", "budget": 5, "files": ["a.md"]}]})
            self.assertEqual(result.returncode, 1, f"{limit}: {result.stdout}")
            self.assertIn("path_ceiling.limit 缺失或不是正数", result.stdout)
        self.assertIn("硬上限", result.stdout)

    def test_fails_when_registered_file_is_missing(self) -> None:
        result = self.run_checker(
            {},
            {"files": [{"path": "missing.md", "budget": 10, "why": "fixture"}], "paths": []},
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("预算登记的文件不存在：missing.md", result.stdout)

    def test_fails_when_group_only_file_is_missing(self) -> None:
        result = self.run_checker(
            {"present.md": "abc"},
            {
                "files": [],
                "paths": [{"label": "incomplete route", "budget": 10, "files": ["present.md", "missing.md"]}],
            },
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("路径「incomplete route」登记的文件不存在：missing.md", result.stdout)


if __name__ == "__main__":
    unittest.main()
