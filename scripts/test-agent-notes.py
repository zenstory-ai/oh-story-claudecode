#!/usr/bin/env python3
"""test-agent-notes.py — check-agent-notes.py 的行为回归：合法笔记通过，每类违规各自被拦。"""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / "check-agent-notes.py"

GOOD = """# Agent Note: 示例决定

Status: implemented

## Problem

问题。

## Decision

决定。

## Alternatives considered

- 方案 A——最强理由；否。

## Consequences

收益与代价。
"""


def run(root: pathlib.Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK), "--root", str(root)], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def write(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def case(name: str, rel: str, text: str, expect_fail: bool, needle: str = "") -> None:
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        write(root, rel, text)
        code, out = run(root)
        failed = code != 0
        assert failed == expect_fail, f"{name}: 期望{'失败' if expect_fail else '通过'}，实际 exit {code}\n{out}"
        if needle:
            assert needle in out, f"{name}: 输出里没有 `{needle}`\n{out}"
        print(f"  ok  {name}")


def main() -> None:
    case("合法笔记通过", "implemented/process/2026-09-15-example.md", GOOD, False)
    case("proposed 用 Proposal 通过", "proposed/feature/2026-09-15-example.md",
         GOOD.replace("Status: implemented", "Status: proposed").replace("## Decision", "## Proposal"), False)
    case("状态目录非法", "draft/process/2026-09-15-example.md", GOOD, True, "状态目录")
    case("分类目录非法", "implemented/misc/2026-09-15-example.md", GOOD, True, "分类目录")
    case("文件名无日期", "implemented/process/example.md", GOOD, True, "文件名")
    case("Status 与目录不一致", "rejected/process/2026-09-15-example.md", GOOD, True, "不一致")
    case("缺 Alternatives", "implemented/process/2026-09-15-example.md",
         GOOD.replace("## Alternatives considered", "## Options"), True, "Alternatives considered")
    case("implemented 缺 Decision", "implemented/process/2026-09-15-example.md",
         GOOD.replace("## Decision", "## Proposal"), True, "Decision")
    case("首行不是 Agent Note", "implemented/process/2026-09-15-example.md",
         GOOD.replace("# Agent Note: 示例决定", "# 示例决定"), True, "首行")
    case("禁止 INDEX.md", "INDEX.md", "# index\n", True, "索引")
    print("test-agent-notes: all passed")


if __name__ == "__main__":
    main()
