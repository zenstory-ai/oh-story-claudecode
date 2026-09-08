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
CHECKER = REPO_ROOT / "scripts" / "check-doc-budget.sh"


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
                ["bash", str(CHECKER), "--root", str(root), "--manifest", str(manifest_path)],
                text=True,
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
