#!/usr/bin/env python3
"""Regression gate for the single-state long-analysis runtime."""

from __future__ import annotations

import csv
import codecs
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "skills" / "story-long-analyze" / "scripts"
INDEX = RUNTIME / "build_chapter_index.py"
INSPECT = RUNTIME / "inspect_existing_assets.py"
MANAGE = RUNTIME / "manage_analysis_run.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(script: Path, *args: object, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(script), *map(str, args)],
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})},
        capture_output=True,
        check=False,
    )


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_index_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="long-index-refactor-") as temporary:
        root = Path(temporary)
        source = root / "原文.txt"
        output = root / "chapter_index.csv"
        source.write_text(
            "序章 雨夜\\User\n一行\u2028仍是同一物理行\n\n"
            "第0章 起点\n零章正文\n\n第五章 节选开始\n这是第五章正文\n\n番外 回家\n这是番外正文",
            encoding="utf-8",
        )
        first = run(INDEX, "--source", source, "--output", output, "--locator-path", "原文/原文.txt")
        require(first.returncode == 0, first.stdout or first.stderr)
        indexed = rows(output)
        require(len(indexed) == 4, "序章、第0章、任意编号正文和番外必须各自成章")
        require(indexed[0]["start_line"] == "1" and indexed[1]["start_line"] == "4", "行号必须只按 LF")
        require(all(item.get("chapter_sha256") for item in indexed), "索引必须包含逐章 hash")
        before = output.read_bytes()
        second = run(INDEX, "--source", source, "--output", output, "--locator-path", "原文/原文.txt")
        require(second.returncode == 0 and output.read_bytes() == before, "同源二次索引必须幂等")
        old_hashes = [item["chapter_sha256"] for item in indexed]
        source.write_text(source.read_text(encoding="utf-8") + "\n\n后记 再见\n后记正文", encoding="utf-8")
        refused = run(INDEX, "--source", source, "--output", output, "--locator-path", "原文/原文.txt")
        require(refused.returncode != 0, "原文改变时必须拒绝静默覆盖")
        rebuilt = run(
            INDEX,
            "--source",
            source,
            "--output",
            output,
            "--locator-path",
            "原文/原文.txt",
            "--rebuild",
        )
        require(rebuilt.returncode == 0, rebuilt.stdout or rebuilt.stderr)
        require([item["chapter_sha256"] for item in rows(output)[:4]] == old_hashes, "末尾追加不能使旧章 hash 失效")

        moved = root / "改名后的原文.txt"
        moved.write_bytes(source.read_bytes())
        moved_refused = run(INDEX, "--source", moved, "--output", output, "--locator-path", "原文/改名后的原文.txt")
        require(moved_refused.returncode != 0, "来源路径变化必须显式重建定位")
        moved_rebuilt = json.loads(run(INDEX, "--source", moved, "--output", output,
                                       "--locator-path", "原文/改名后的原文.txt", "--rebuild").stdout)
        require(moved_rebuilt["pending_chapters"] == [], "只移动来源路径不能把全书判为语义变化")

        large = root / "大数章.txt"
        large_index = root / "large.csv"
        large.write_text("第一百零一章 起\n正文。\n第一百零二章 续\n正文。\n", encoding="utf-8")
        large_result = run(INDEX, "--source", large, "--output", large_index, "--locator-path", "原文/大数章.txt")
        require(large_result.returncode == 0, large_result.stdout or large_result.stderr)
        require([item["source_chapter"] for item in rows(large_index)] == ["101", "102"], "第一百零一章必须正确解析")


def test_invalid_root_and_manage_entry() -> None:
    with tempfile.TemporaryDirectory(prefix="long-runtime-refactor-") as temporary:
        missing = Path(temporary) / "不存在"
        inspected = run(INSPECT, "--root", missing)
        require(inspected.returncode != 0, "错误 root 必须非零退出")
        require(MANAGE.is_file(), "统一运行脚本 manage_analysis_run.py 必须存在")
        help_result = run(MANAGE, "--help")
        require(help_result.returncode == 0, help_result.stdout or help_result.stderr)
        for command in ("plan", "commit", "split", "repair-progress", "mark-stage"):
            require(command in help_result.stdout, "统一运行脚本缺少命令：" + command)


def test_index_existing_supported_forms() -> None:
    with tempfile.TemporaryDirectory(prefix="long-index-forms-") as temporary:
        root = Path(temporary)
        cases = {
            "toc": "目录\n第一章 起\n第二章 承\n第三章 合\n\n说明。\n说明。\n第一章 起\n正文一。\n第二章 承\n正文二。\n第三章 合\n正文三。\n",
            "volumes": "第一卷 第一章 起\n正文。\n第一卷 第二章 承\n正文。\n第二卷 第一章 转\n正文。\n第二卷 第二章 合\n正文。\n",
            "empty": "第一章 起\n正文。\n第二章 空\n",
            "numbered_prose": "第一章 起\n1. 这是正文列表\n正文。\n第二章 合\n2. 仍是正文列表\n正文。\n",
        }
        indexed = {}
        for name, text in cases.items():
            source = root / f"{name}.txt"
            output = root / f"{name}.csv"
            source.write_text(text, encoding="utf-8")
            result = run(INDEX, "--source", source, "--output", output, "--locator-path", f"原文/{name}.txt")
            require(result.returncode == 0, result.stdout or result.stderr)
            indexed[name] = rows(output)
        require(len(indexed["toc"]) == 3, "重复的前置目录必须剔除")
        require([item["source_chapter"] for item in indexed["volumes"]] == ["1", "2", "1", "2"], "多卷本地章号必须保留")
        require(indexed["empty"][-1]["status"] == "empty", "空章必须显式保留")
        require(len(indexed["numbered_prose"]) == 2, "数字正文列表不能覆盖显式章标题")

        gb = root / "gb18030.txt"
        gb_index = root / "gb.csv"
        gb.write_bytes("第一章 起\r\n正文。\r\n第二章 合\r\n正文。".encode("gb18030"))
        gb_result = run(INDEX, "--source", gb, "--output", gb_index, "--locator-path", "原文/gb18030.txt")
        require(gb_result.returncode == 0 and len(rows(gb_index)) == 2, "GB18030 原文必须继续支持")

        long_source = root / "long.txt"
        long_index = root / "long.csv"
        long_source.write_text("第一章 长章\n" + "甲" * 26000 + "\n第二章 短章\n乙。\n", encoding="utf-8")
        require(run(INDEX, "--source", long_source, "--output", long_index, "--locator-path", "原文/long.txt").returncode == 0, "长章索引失败")
        project = root / "long-project"
        project.mkdir()
        shutil.copy2(long_index, project / "chapter_index.csv")
        long_plan = json.loads(run(MANAGE, "plan", "--root", project).stdout)
        require(long_plan["batches"][0]["chapter_range"] == [1, 1], "单章超过字符上限时必须独占一块")


def write_source_and_index(root: Path, count: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "原文" / "原文.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("\n".join(f"第{chapter}章 标题{chapter}\n正文{chapter}。" for chapter in range(1, count + 1)), encoding="utf-8")
    result = run(INDEX, "--source", source, "--output", root / "chapter_index.csv", "--locator-path", "原文/原文.txt")
    require(result.returncode == 0, result.stdout or result.stderr)
    return source


def plot_points(chapter: int, count: int, *, tone: str, theme: str) -> str:
    points = []
    for number in range(1, count + 1):
        points.append(
            f"P{number} **节拍{number}**：类型动作 | 人物甲在第{chapter}章完成第{number}步。 | 涉及人物甲,人物乙 | 地点旧城\n\n"
            f"主题标签{theme} | 基调：{tone}"
        )
    return "\n\n---\n\n".join(points)


def compact_output(start: int, end: int, *, tone: str = "期待", theme: str = "陌生主题", points: int = 10) -> str:
    blocks = []
    for chapter in range(start, end + 1):
        blocks.append(
            f"""<!-- CHAPTER_START:{chapter} -->
## 第{chapter}章 标题{chapter}

**概要**：人物在本章完成一次可核查推进。
**因果**：因为目标受阻，所以人物改换办法并得到结果。
**关键行动**：人物执行第{chapter}章的关键行动。
**局面结果**：局面从受阻变成获得下一步入口。
**涉及人物**：人物甲、人物乙
**信息变化**：读者确认入口存在，角色乙仍不知代价。
**状态变化**：人物甲获得入口，人物乙承担风险。
**三维节奏**：事件3/5｜情绪3/5｜篇幅2/3。
**章尾钩子**：代价将在下一章出现。
**证据**：原文定位词“正文{chapter}”。
**情节点**：

{plot_points(chapter, points, tone=tone, theme=theme)}
<!-- CHAPTER_END:{chapter} -->"""
        )
    return "\n\n".join(blocks) + """

<!-- BATCH_OBSERVATIONS_START -->
## 跨章观察
- 因果连续，下一批继续核查代价。
<!-- BATCH_OBSERVATIONS_END -->
"""


def reuse_output(start: int, end: int) -> str:
    return f"""<!-- REUSED_CHAPTERS:{start}-{end} -->

<!-- BATCH_OBSERVATIONS_START -->
## 跨章观察
- 仅从已有拆文成果归一，不读取原文。
<!-- BATCH_OBSERVATIONS_END -->
"""


def protected_snapshot(root: Path) -> dict[str, bytes]:
    result = {}
    for name in ("章节", "剧情", "角色", "设定"):
        directory = root / name
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_file():
                    result[path.relative_to(root).as_posix()] = path.read_bytes()
    for name in ("文风.md", "拆文报告.md"):
        path = root / name
        if path.is_file():
            result[name] = path.read_bytes()
    return result


def test_inspection_legacy_and_partial() -> None:
    with tempfile.TemporaryDirectory(prefix="long-inspect-refactor-") as temporary:
        root = Path(temporary)
        complete = root / "完整"
        complete.mkdir()
        (complete / "_progress.md").write_text("# 进度\n- schema_version: 2\n- 总章数：4\n- 最终状态：completed\n", encoding="utf-8")
        for chapter in range(1, 5):
            path = complete / "章节" / f"第{chapter}章_摘要.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("摘要", encoding="utf-8")
        for path in (complete / "拆文报告.md", complete / "剧情" / "故事线.md",
                     complete / "剧情" / "情绪模块.md", complete / "剧情" / "节奏.md", complete / "文风.md"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("有效", encoding="utf-8")
        before = (complete / "_progress.md").read_bytes()
        checked = run(INSPECT, "--root", complete)
        payload = json.loads(checked.stdout)
        require(checked.returncode == 0 and payload["recommended_path"] == "direct_use", "schema 2 完整旧项目必须直接使用")
        require((complete / "_progress.md").read_bytes() == before, "检查器必须只读且不能改 schema")

        schema1_text = (complete / "_progress.md").read_text(encoding="utf-8").replace("schema_version: 2", "schema_version: 1")
        (complete / "_progress.md").write_text(schema1_text, encoding="utf-8")
        schema1_plan = json.loads(run(MANAGE, "plan", "--root", complete, "--intent", "enhance").stdout)
        schema1_model = root / "schema1-reuse.md"
        for batch in schema1_plan["batches"]:
            start, end = batch["chapter_range"]
            schema1_model.write_text(reuse_output(start, end), encoding="utf-8")
            require(run(MANAGE, "commit", "--root", complete, "--input", schema1_model,
                        "--batch-id", batch["batch_id"]).returncode == 0, "schema 1 旧成果增强提交失败")
        require("schema_version: 1" in (complete / "_progress.md").read_text(encoding="utf-8"),
                "existing-results 提交不能升级旧 schema")
        require(json.loads(run(INSPECT, "--root", complete).stdout)["recommended_path"] == "direct_use",
                "schema 1 完整旧项目增强后仍必须 direct_use")
        require(json.loads(run(MANAGE, "plan", "--root", complete, "--intent", "enhance").stdout)["batches"] == [],
                "schema 1 完整旧项目增强不能重复调用模型")

        (complete / "_progress.md").write_text("# 进度\n- schema_version: 2\n- 总章数：4\n- 最终状态：completed_with_errors\n", encoding="utf-8")
        (complete / "章节" / "第2章_摘要.md").unlink()
        checked = run(INSPECT, "--root", complete)
        payload = json.loads(checked.stdout)
        require(payload["missing_semantic_chapters"] == [2], "缺失语义章必须精确报告")
        require(payload["recommended_path"] == "continue_partial", "部分旧项目必须只续缺失章")

        golden = root / "黄金"
        golden.mkdir()
        (golden / "_progress.md").write_text("# 进度\n- schema_version: 2\n- 总章数：6\n- 最终状态：paused_after_stage1\n", encoding="utf-8")
        for chapter in range(1, 4):
            path = golden / "章节" / f"第{chapter}章_深度拆解.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("黄金章事实", encoding="utf-8")
        payload = json.loads(run(INSPECT, "--root", golden).stdout)
        require(payload["missing_semantic_chapters"] == [4, 5, 6], "黄金三章必须算语义覆盖，缺失从第4章开始")


def test_plan_commit_repair_and_state_preservation() -> None:
    with tempfile.TemporaryDirectory(prefix="long-manage-refactor-") as temporary:
        root = Path(temporary) / "书"
        write_source_and_index(root, 2)
        progress = root / "_progress.md"
        prefix = codecs.BOM_UTF8 + "# 旧进度\r\n- schema_version: 7\r\n- 作者备注：\\User 保留\r\n".encode("utf-8")
        progress.write_bytes(prefix)
        planned = run(MANAGE, "plan", "--root", root)
        plan = json.loads(planned.stdout)
        require(planned.returncode == 0 and [b["batch_id"] for b in plan["batches"]] == ["RAW-1-2"], planned.stdout)
        require(plan["read_counts"]["raw_chapters"] == 2 and not plan["state_written"], "计划必须只读并准确报告原文读取")
        require(progress.read_bytes() == prefix, "plan 不能写进度")

        model = root / "model.md"
        model.write_text(compact_output(1, 2), encoding="utf-8")
        committed = run(MANAGE, "commit", "--root", root, "--input", model,
                        "--batch-id", "RAW-1-2", "--range-sha256", plan["batches"][0]["range_sha256"])
        require(committed.returncode == 0, committed.stdout or committed.stderr)
        require(progress.read_bytes().startswith(prefix), "受管状态外的 BOM、换行和 schema 必须逐字节保留")
        summary = (root / "章节" / "第1章_摘要.md").read_text(encoding="utf-8")
        require("主题标签其他 | 基调：其他" in summary, "未知主题和情绪必须投影到其他")
        require("P1 **节拍1**：类型行动 | " in summary and "P10 **节拍10**" in summary and "地点旧城" in summary,
                "多情节点必须逐条投影，类型映射到枚举并保留地点等字段")
        require("**涉及**：人物甲、人物乙" in summary, "章级涉及人物必须兼容旧消费者")
        after_commit = progress.read_bytes()
        require(json.loads(run(MANAGE, "plan", "--root", root).stdout)["batches"] == [], "成功批次不得重复规划")
        require(progress.read_bytes() == after_commit, "重跑计划仍必须只读")
        repeated = run(MANAGE, "commit", "--root", root, "--input", model,
                       "--batch-id", "RAW-1-2", "--range-sha256", plan["batches"][0]["range_sha256"])
        require(repeated.returncode == 0 and progress.read_bytes() == after_commit, "相同批次重复 commit 必须幂等")

        source = root / "原文" / "原文.txt"
        source.write_text(source.read_text(encoding="utf-8").replace("正文2。", "正文2已变化。"), encoding="utf-8")
        refused = run(INDEX, "--source", source, "--output", root / "chapter_index.csv", "--locator-path", "原文/原文.txt")
        require(refused.returncode != 0, "局部原文变化必须先拒绝")
        rebuilt = run(INDEX, "--source", source, "--output", root / "chapter_index.csv", "--locator-path", "原文/原文.txt", "--rebuild")
        require(json.loads(rebuilt.stdout)["pending_chapters"] == [2], "局部变化只能标记受影响章")
        stale_repair = run(MANAGE, "repair-progress", "--root", root, "--batch-id", "RAW-1-2")
        require(stale_repair.returncode != 0 and json.loads(stale_repair.stdout)["errors"][0]["error"] == "range_hash_mismatch", "旧输入缓存不能修复新原文进度")
        changed_plan = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require([batch["batch_id"] for batch in changed_plan["batches"]] == ["RAW-1-2"], "原文变化使整批缓存失效并重读该批")
        summary_before = (root / "章节" / "第2章_摘要.md").read_bytes()
        recommitted = json.loads(run(MANAGE, "commit", "--root", root, "--input", model, "--batch-id", "RAW-1-2",
                                     "--range-sha256", changed_plan["batches"][0]["range_sha256"]).stdout)
        require(recommitted["kept_existing_summary_chapters"] == [1, 2]
                and (root / "章节" / "第2章_摘要.md").read_bytes() == summary_before,
                "已有摘要一律不覆盖，并在提交结果中列出")
        (root / "章节" / "第2章_摘要.md").unlink()
        refresh_plan = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require(refresh_plan["batches"] == [] and refresh_plan["recoverable_caches"][0]["missing_summary_chapters"] == [2],
                "删掉摘要后应从本批新缓存补回，不再重读原文")
        require(run(MANAGE, "repair-progress", "--root", root).returncode == 0
                and (root / "章节" / "第2章_摘要.md").read_bytes() != summary_before,
                "补回的摘要必须来自变化后的原文")

        interrupted = Path(temporary) / "中断"
        write_source_and_index(interrupted, 2)
        (interrupted / "_progress.md").write_text("# 原进度\n- schema_version: 2\n", encoding="utf-8")
        failed_plan = json.loads(run(MANAGE, "plan", "--root", interrupted).stdout)
        failed_model = interrupted / "model.md"
        failed_model.write_text(compact_output(1, 2, tone="紧张", theme="友情"), encoding="utf-8")
        before_failure = (interrupted / "_progress.md").read_bytes()
        failed = run(MANAGE, "commit", "--root", interrupted, "--input", failed_model,
                     "--batch-id", "RAW-1-2", "--range-sha256", failed_plan["batches"][0]["range_sha256"],
                     extra_env={"STORY_ANALYZE_FAIL_AFTER_CACHE": "1"})
        require(failed.returncode != 0 and (interrupted / "_analysis_cache" / "批次-RAW-1-2.md").is_file(), "中断点必须留下完整缓存")
        require((interrupted / "_progress.md").read_bytes() == before_failure, "缓存阶段失败不能提前标成功")
        repaired = run(MANAGE, "repair-progress", "--root", interrupted)
        require(repaired.returncode == 0 and all((interrupted / "章节" / f"第{n}章_摘要.md").is_file() for n in (1, 2)), repaired.stdout)
        edited = interrupted / "章节" / "第1章_摘要.md"
        edited.write_text("用户修改", encoding="utf-8")
        repaired_again = run(MANAGE, "repair-progress", "--root", interrupted)
        require(repaired_again.returncode == 0 and edited.read_text(encoding="utf-8") == "用户修改", "恢复只能补缺，不能覆盖用户摘要")

        fresh = Path(temporary) / "新进度"
        write_source_and_index(fresh, 1)
        fresh_plan = json.loads(run(MANAGE, "plan", "--root", fresh).stdout)
        fresh_model = fresh / "model.md"
        fresh_model.write_text(compact_output(1, 1), encoding="utf-8")
        require(run(MANAGE, "commit", "--root", fresh, "--input", fresh_model,
                    "--batch-id", "RAW-1-1", "--range-sha256", fresh_plan["batches"][0]["range_sha256"]).returncode == 0,
                "新进度提交失败")
        require("schema_version: 2" in (fresh / "_progress.md").read_text(encoding="utf-8"), "新建进度必须写当前 schema")

        broken = Path(temporary) / "重复状态区"
        broken.mkdir()
        (broken / "_progress.md").write_text(
            "<!-- story-long-analyze:runtime-state:start -->\n"
            "<!-- story-long-analyze:runtime-state:end -->\n"
            "<!-- story-long-analyze:runtime-state:start -->\n"
            "<!-- story-long-analyze:runtime-state:end -->\n",
            encoding="utf-8",
        )
        rejected = run(MANAGE, "plan", "--root", broken, "--expected-chapters", "1")
        require(rejected.returncode != 0 and json.loads(rejected.stdout)["error"] == "progress_state_block_invalid",
                "重复受管状态区必须明确停止")

        partial = Path(temporary) / "部分落盘"
        write_source_and_index(partial, 3)
        partial_plan = json.loads(run(MANAGE, "plan", "--root", partial).stdout)
        partial_model = partial / "model.md"
        partial_model.write_text(compact_output(1, 3), encoding="utf-8")
        failed_partial = run(
            MANAGE, "commit", "--root", partial, "--input", partial_model,
            "--batch-id", "RAW-1-3", "--range-sha256", partial_plan["batches"][0]["range_sha256"],
            extra_env={"STORY_ANALYZE_FAIL_AFTER_SUMMARIES": "1"},
        )
        require(failed_partial.returncode != 0 and (partial / "章节" / "第1章_摘要.md").is_file()
                and not (partial / "章节" / "第2章_摘要.md").exists(), "必须能注入部分摘要落盘故障")
        recovery_plan = json.loads(run(MANAGE, "plan", "--root", partial).stdout)
        require(recovery_plan["batches"] == [] and recovery_plan["recoverable_caches"][0]["missing_summary_chapters"] == [2, 3], "完整缓存存在时计划必须先恢复，不能重复调模型")
        require(run(MANAGE, "repair-progress", "--root", partial).returncode == 0, "部分摘要恢复失败")


def test_split_survives_replanning() -> None:
    with tempfile.TemporaryDirectory(prefix="long-split-refactor-") as temporary:
        root = Path(temporary)
        write_source_and_index(root, 5)
        first = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require(first["batches"][0]["batch_id"] == "RAW-1-3", "恰好3章必须合法成块")
        split = run(MANAGE, "split", "--root", root, "--batch-id", "RAW-1-3", "--at", 1)
        require(split.returncode == 0 and json.loads(split.stdout)["children"] == ["RAW-1-1", "RAW-2-3"], split.stdout)
        second = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        ids = [batch["batch_id"] for batch in second["batches"]]
        require("RAW-1-1" in ids and "RAW-2-3" in ids and "RAW-1-3" not in ids, "拆分必须相邻且重规划不能合回父块")


def test_panlong_acceptance_samples() -> None:
    source_demo = ROOT / "demo" / "拆文库" / "盘龙"
    require(source_demo.is_dir(), "盘龙验收样本缺失")
    if not (source_demo / "原文" / "原文.txt").is_file():
        # 原文按 .gitignore 版权策略不入库；缺席时明确跳过，不让 CI 因夹具红。
        print("SKIP: test_panlong_acceptance_samples (panlong raw text absent by copyright policy)")
        return
    with tempfile.TemporaryDirectory(prefix="long-panlong-acceptance-") as temporary:
        area = Path(temporary)

        complete = area / "完整旧项目"
        shutil.copytree(source_demo, complete)
        before = protected_snapshot(complete)
        progress_before = (complete / "_progress.md").read_text(encoding="utf-8-sig")
        inspected = json.loads(run(INSPECT, "--root", complete).stdout)
        require(inspected["recommended_path"] == "direct_use", "盘龙旧项目必须 direct_use")
        require(not (complete / "chapter_index.csv").exists(), "直接使用不能新建索引")
        prepared = run(MANAGE, "mark-stage", "--root", complete, "--stage", "stage5", "--prepare")
        require(prepared.returncode == 0, prepared.stdout or prepared.stderr)
        require((complete / "_analysis_cache" / "legacy" / "拆文报告.md").read_bytes() == before["拆文报告.md"], "新报告生成前必须逐字节备份旧报告")
        (complete / "拆文报告.md").write_text("明确重建后的另一版报告", encoding="utf-8")
        second_prepared = json.loads(run(MANAGE, "mark-stage", "--root", complete, "--stage", "stage5", "--prepare").stdout)
        second_backup = complete / second_prepared["legacy_report_backup"]
        require(second_backup.name != "拆文报告.md" and second_backup.read_text(encoding="utf-8") == "明确重建后的另一版报告",
                "不同版本报告必须另存历史备份")
        (complete / "拆文报告.md").write_bytes(before["拆文报告.md"])
        enhanced = json.loads(run(MANAGE, "plan", "--root", complete, "--intent", "enhance").stdout)
        require(enhanced["read_counts"]["raw_chapters"] == 0, "旧项目增强原文读取必须为0")
        reuse_file = area / "reuse.md"
        for batch in enhanced["batches"]:
            start, end = batch["chapter_range"]
            reuse_file.write_text(reuse_output(start, end), encoding="utf-8")
            committed = run(MANAGE, "commit", "--root", complete, "--input", reuse_file, "--batch-id", batch["batch_id"])
            require(committed.returncode == 0, committed.stdout or committed.stderr)
        require(protected_snapshot(complete) == before, "旧项目增强只能新增缓存并修改进度状态区")
        progress_after = (complete / "_progress.md").read_text(encoding="utf-8-sig")
        require("schema_version: 2" in progress_before and "schema_version: 2" in progress_after, "旧 schema 值不能改变")
        require(progress_after.count("最终状态") == progress_before.count("最终状态"),
                "只做增强的旧项目不能多出第二个最终状态")
        require(json.loads(run(INSPECT, "--root", complete).stdout)["recommended_path"] == "direct_use", "增强后仍须 direct_use")
        require(json.loads(run(MANAGE, "plan", "--root", complete, "--intent", "enhance").stdout)["batches"] == [], "已提交增强批次不能重复执行")

        style_missing = area / "只缺文风"
        shutil.copytree(source_demo, style_missing)
        (style_missing / "文风.md").unlink()
        style_report = json.loads(run(INSPECT, "--root", style_missing).stdout)
        require(style_report["stage_repairs"] == ["stage6_style"], "只缺文风必须定点路由 Stage 6")

        aggregate_missing = area / "只缺聚合产物"
        shutil.copytree(source_demo, aggregate_missing)
        (aggregate_missing / "剧情" / "情绪模块.md").unlink()
        (aggregate_missing / "剧情" / "节奏.md").unlink()
        aggregate_report = json.loads(run(INSPECT, "--root", aggregate_missing).stdout)
        require(aggregate_report["stage_repairs"] == ["stage3_emotion", "stage3_rhythm"], "情绪/节奏缺失必须单独路由 Stage 3+")
        require(json.loads(run(MANAGE, "plan", "--root", aggregate_missing).stdout)["batches"] == [], "聚合产物修复不能生成 Stage 2 原文任务")

        golden = area / "黄金三章暂停"
        shutil.copytree(source_demo, golden)
        for path in (golden / "章节").glob("*_摘要.md"):
            path.unlink()
        progress_text = (golden / "_progress.md").read_text(encoding="utf-8-sig")
        progress_text = re.sub(r"(?m)^- 最终状态：.*$", "- 最终状态：paused_after_stage1", progress_text)
        (golden / "_progress.md").write_text(progress_text, encoding="utf-8")
        golden_report = json.loads(run(INSPECT, "--root", golden).stdout)
        require(golden_report["missing_semantic_chapters"] == list(range(4, 24)), "黄金三章暂停项目必须只缺4-23")
        build = run(INDEX, "--source", golden / "原文" / "原文.txt", "--output", golden / "chapter_index.csv", "--locator-path", "原文/原文.txt")
        require(build.returncode == 0, build.stdout or build.stderr)
        golden_plan = json.loads(run(MANAGE, "plan", "--root", golden).stdout)
        require(golden_plan["read_counts"]["raw_chapters"] == 20, "黄金三章不能重读，原文只读4-23")
        require(any(batch["batch_id"] == "REUSE-1-3" for batch in golden_plan["batches"]), "黄金三章须用于补投影")

        mixed = area / "缺7和15"
        shutil.copytree(source_demo, mixed)
        for chapter in (7, 15):
            (mixed / "章节" / f"第{chapter}章_摘要.md").unlink()
        progress_text = (mixed / "_progress.md").read_text(encoding="utf-8-sig")
        progress_text = re.sub(r"(?m)^- 最终状态：.*$", "- 最终状态：completed_with_errors", progress_text)
        (mixed / "_progress.md").write_text(progress_text, encoding="utf-8")
        missing_report = json.loads(run(INSPECT, "--root", mixed).stdout)
        require(missing_report["missing_semantic_chapters"] == [7, 15], "缺章必须精确为7、15")
        built = run(INDEX, "--source", mixed / "原文" / "原文.txt", "--output", mixed / "chapter_index.csv", "--locator-path", "原文/原文.txt")
        require(built.returncode == 0, built.stdout or built.stderr)
        missing_plan = json.loads(run(MANAGE, "plan", "--root", mixed).stdout)
        require(missing_plan["read_counts"]["raw_chapters"] == 2, "已完成章原文读取必须为0")
        require([batch["batch_id"] for batch in missing_plan["batches"]] == ["RAW-7-7", "RAW-15-15"], "只规划缺失章7、15")
        for batch in missing_plan["batches"]:
            start, end = batch["chapter_range"]
            model = area / f"raw-{start}.md"
            model.write_text(compact_output(start, end, tone="紧张", theme="成长"), encoding="utf-8")
            committed = run(MANAGE, "commit", "--root", mixed, "--input", model,
                            "--batch-id", batch["batch_id"], "--range-sha256", batch["range_sha256"])
            require(committed.returncode == 0, committed.stdout or committed.stderr)
        mixed_report = json.loads(run(INSPECT, "--root", mixed).stdout)
        require(mixed_report["mixed_sources"] and mixed_report["recommended_path"] == "direct_use", "新旧混存必须可用且来源可见：" + json.dumps(mixed_report, ensure_ascii=False))
        require(mixed_report["chapter_sources"]["preferred_by_chapter"]["7"] == "three_script_projection"
                and mixed_report["chapter_sources"]["preferred_by_chapter"]["15"] == "three_script_projection"
                and mixed_report["chapter_sources"]["preferred_by_chapter"]["8"] == "upstream_summary",
                "来源表必须区分新投影7、15与旧摘要")
        require(json.loads(run(MANAGE, "plan", "--root", mixed).stdout)["batches"] == [], "新投影不能被当旧成果再提取")

        old_hashes = [row["chapter_sha256"] for row in rows(mixed / "chapter_index.csv")]
        with (mixed / "原文" / "原文.txt").open("a", encoding="utf-8") as handle:
            handle.write("\n\n第24章 新章\n新增正文。\n")
        refused = run(INDEX, "--source", mixed / "原文" / "原文.txt", "--output", mixed / "chapter_index.csv", "--locator-path", "原文/原文.txt")
        require(refused.returncode != 0, "追加原文必须先拒绝静默覆盖")
        rebuilt = run(INDEX, "--source", mixed / "原文" / "原文.txt", "--output", mixed / "chapter_index.csv", "--locator-path", "原文/原文.txt", "--rebuild")
        rebuilt_payload = json.loads(rebuilt.stdout)
        require(rebuilt.returncode == 0 and rebuilt_payload["pending_chapters"] == [24], rebuilt.stdout)
        require([row["chapter_sha256"] for row in rows(mixed / "chapter_index.csv")[:23]] == old_hashes, "追加新章不能使前23章回退")
        append_plan = json.loads(run(MANAGE, "plan", "--root", mixed).stdout)
        require([batch["batch_id"] for batch in append_plan["batches"]] == ["RAW-24-24"], "追加后只处理新章")


def test_audit_recovery_regressions() -> None:
    with tempfile.TemporaryDirectory(prefix="long-audit-recovery-") as temporary:
        area = Path(temporary)
        root = area / "截断缓存"
        write_source_and_index(root, 2)
        first_plan = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        model = area / "model.md"
        model.write_text(compact_output(1, 2), encoding="utf-8")
        committed = run(MANAGE, "commit", "--root", root, "--input", model,
                        "--batch-id", "RAW-1-2", "--range-sha256", first_plan["batches"][0]["range_sha256"])
        require(committed.returncode == 0, committed.stdout or committed.stderr)
        cache = root / "_analysis_cache" / "批次-RAW-1-2.md"
        data = cache.read_bytes()
        cache.write_bytes(data[:len(data) // 2])
        retry = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require([batch["batch_id"] for batch in retry["batches"]] == ["RAW-1-2"],
                "截断缓存必须重做对应批次，摘要存在不能掩盖失败")

        repaired = run(MANAGE, "commit", "--root", root, "--input", model,
                       "--batch-id", "RAW-1-2", "--range-sha256", retry["batches"][0]["range_sha256"])
        require(repaired.returncode == 0, repaired.stdout or repaired.stderr)

        state_only = area / "状态表丢失但缓存完整"
        shutil.copytree(root, state_only)
        progress_text = (state_only / "_progress.md").read_text(encoding="utf-8-sig")
        progress_text = re.sub(
            r"(?s)<!-- story-long-analyze:runtime-state:start -->.*?"
            r"<!-- story-long-analyze:runtime-state:end -->\n?",
            "",
            progress_text,
        )
        (state_only / "_progress.md").write_text(progress_text, encoding="utf-8")
        state_plan = json.loads(run(MANAGE, "plan", "--root", state_only).stdout)
        require(state_plan["batches"] == []
                and state_plan["recoverable_caches"][0]["state_repair_required"],
                "缓存完整而状态行丢失时必须走状态恢复，不能重复调用模型")
        restored = run(MANAGE, "repair-progress", "--root", state_only)
        require(restored.returncode == 0
                and "| RAW-1-2 | 1-2 | raw-original |" in (state_only / "_progress.md").read_text(encoding="utf-8-sig"),
                "repair-progress 必须能从完整缓存恢复单一状态表")

        truncated_split = area / "截断后拆分"
        write_source_and_index(truncated_split, 5)
        split_plan = json.loads(run(MANAGE, "plan", "--root", truncated_split).stdout)
        model.write_text(compact_output(1, 3), encoding="utf-8")
        require(run(MANAGE, "commit", "--root", truncated_split, "--input", model, "--batch-id", "RAW-1-3",
                    "--range-sha256", split_plan["batches"][0]["range_sha256"]).returncode == 0, "拆分样本提交失败")
        split_cache = truncated_split / "_analysis_cache" / "批次-RAW-1-3.md"
        split_cache.write_bytes(split_cache.read_bytes()[:200])
        require(run(MANAGE, "split", "--root", truncated_split, "--batch-id", "RAW-1-3", "--at", "1").returncode == 0, "拆分失败")
        after_split = json.loads(run(MANAGE, "plan", "--root", truncated_split).stdout)
        require([b["batch_id"] for b in after_split["batches"]][:2] == ["RAW-1-1", "RAW-2-3"],
                "失效批次拆分后子块必须被规划，不能因摘要已在而丢掉：" + json.dumps(after_split["batches"], ensure_ascii=False))
        for batch in after_split["batches"]:
            start, end = batch["chapter_range"]
            model.write_text(compact_output(start, end), encoding="utf-8")
            require(run(MANAGE, "commit", "--root", truncated_split, "--input", model, "--batch-id", batch["batch_id"],
                        "--range-sha256", batch["range_sha256"]).returncode == 0, "子块提交失败")
        require(json.loads(run(MANAGE, "plan", "--root", truncated_split).stdout)["batches"] == []
                and run(MANAGE, "repair-progress", "--root", truncated_split).returncode == 0,
                "子块补完后不再规划，被取代的旧缓存也不能让 repair-progress 永久报错")

        oversized = area / "超限提交"
        write_source_and_index(oversized, 4)
        oversized_model = area / "oversized.md"
        oversized_model.write_text(compact_output(1, 4), encoding="utf-8")
        index_rows = rows(oversized / "chapter_index.csv")
        payload = "range-v1\n" + "".join(f"{row['chapter']}:{row['chapter_sha256']}\n" for row in index_rows)
        range_hash = hashlib.sha256(payload.encode("ascii")).hexdigest()
        refused = run(MANAGE, "commit", "--root", oversized, "--input", oversized_model,
                      "--batch-id", "RAW-1-4", "--range-sha256", range_hash)
        require(refused.returncode != 0 and json.loads(refused.stdout)["error"] == "batch_too_large",
                "提交入口必须拒绝超过3章的手工批次")

        sparse = area / "情节点不足"
        write_source_and_index(sparse, 1)
        sparse_plan = json.loads(run(MANAGE, "plan", "--root", sparse).stdout)
        sparse_model = area / "sparse.md"
        sparse_model.write_text(compact_output(1, 1, points=1), encoding="utf-8")
        sparse_commit = run(MANAGE, "commit", "--root", sparse, "--input", sparse_model, "--batch-id", "RAW-1-1",
                            "--range-sha256", sparse_plan["batches"][0]["range_sha256"])
        require(sparse_commit.returncode != 0 and json.loads(sparse_commit.stdout)["error"] == "plot_point_count"
                and not (sparse / "章节" / "第1章_摘要.md").exists(),
                "原文批次每章少于10个情节点必须整批拒收且不落盘")


def test_audit_stage_and_mapping_regressions() -> None:
    with tempfile.TemporaryDirectory(prefix="long-audit-stage-") as temporary:
        area = Path(temporary)
        root = area / "阶段缺口"
        write_source_and_index(root, 2)
        planned = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        model = area / "stage-model.md"
        model.write_text(compact_output(1, 2), encoding="utf-8")
        require(run(MANAGE, "commit", "--root", root, "--input", model,
                    "--batch-id", "RAW-1-2", "--range-sha256", planned["batches"][0]["range_sha256"]).returncode == 0,
                "阶段样本提交失败")
        for name in ("剧情/情绪模块.md", "剧情/节奏.md", "文风.md"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("有效产物", encoding="utf-8")
        stage_plan = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require({"stage4", "stage5"}.issubset(stage_plan["required_stages"]),
                "角色/设定和报告缺失必须进入阶段恢复计划")
        premature = run(MANAGE, "mark-stage", "--root", root, "--stage", "stage4")
        require(premature.returncode != 0 and json.loads(premature.stdout)["error"] == "stage_output_missing",
                "Stage 4 没有角色与设定产物时不能标 completed")

        for chapter in (1, 2):
            path = root / "章节" / f"第{chapter}章_深度拆解.md"
            path.write_text("有效深度拆解", encoding="utf-8")
        (root / "快速预览.md").write_text("有效快速预览", encoding="utf-8")
        (root / "角色").mkdir()
        (root / "角色" / "人物.md").write_text("有效人物档案", encoding="utf-8")
        (root / "设定" / "世界观").mkdir(parents=True)
        (root / "设定" / "世界观" / "背景.md").write_text("有效世界设定", encoding="utf-8")
        (root / "拆文报告.md").write_text("有效拆文报告", encoding="utf-8")
        for stage in ("stage3", "stage4", "stage5", "stage6"):
            marked = run(MANAGE, "mark-stage", "--root", root, "--stage", stage)
            require(marked.returncode == 0, marked.stdout or marked.stderr)
        require("- 最终状态：completed" in (root / "_progress.md").read_text(encoding="utf-8-sig"),
                "Stage 3-6 按文档各标一次即算完成，不依赖 Stage 1/2 行")
        for stage in ("stage1", "stage2"):
            marked = run(MANAGE, "mark-stage", "--root", root, "--stage", stage)
            require(marked.returncode == 0, marked.stdout or marked.stderr)
        complete = json.loads(run(INSPECT, "--root", root).stdout)
        require(complete["classification"] == "current_complete"
                and complete["recommended_path"] == "direct_use",
                "受管 Stage 1-6 全部完成时必须识别为 current_complete/direct_use")
        require("- 最终状态：completed" in (root / "_progress.md").read_text(encoding="utf-8-sig"),
                "六个阶段完成后必须写出 hooks 识别的最终状态")
        hook_lib = ROOT / "skills" / "story-setup" / "references" / "templates" / "hooks" / "lib" / "common.sh"
        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", 'source "$1" && analysis_incomplete "$2"', "_",
                                    hook_lib.as_posix(), (root / "_progress.md").as_posix()],
                                   capture_output=True, text=True, check=False)
            require(probe.returncode == 1, "hooks 必须把拆完的书判为已完成：" + probe.stderr)

        resumed = area / "旧项目续拆完成"
        shutil.copytree(root, resumed)
        progress_text = (resumed / "_progress.md").read_text(encoding="utf-8-sig")
        progress_text = re.sub(r"(?s)<!-- story-long-analyze:runtime-state:start -->.*?<!-- story-long-analyze:runtime-state:end -->\n?", "", progress_text)
        (resumed / "_progress.md").write_text("# 旧进度\n- 最终状态：paused_after_stage1\n" + progress_text, encoding="utf-8")
        require(run(MANAGE, "mark-stage", "--root", resumed, "--stage", "stage1").returncode == 0, "旧项目标记失败")
        require("最终状态：paused_after_stage1" in (resumed / "_progress.md").read_text(encoding="utf-8"),
                "未全部完成时不改旧项目的最终状态")
        for stage in ("stage2", "stage3", "stage4", "stage5", "stage6"):
            require(run(MANAGE, "mark-stage", "--root", resumed, "--stage", stage).returncode == 0, "旧项目标记失败")
        resumed_text = (resumed / "_progress.md").read_text(encoding="utf-8")
        require(resumed_text.count("最终状态") == 1 and "- 最终状态：completed" in resumed_text,
                "旧项目续拆完成后只改写原有的最终状态行，不另写第二行：" + resumed_text)

        prologue = area / "序章旧项目"
        (prologue / "原文").mkdir(parents=True)
        (prologue / "原文" / "原文.txt").write_text(
            "序章 引子\n序章事实。\n第1章 起\n正文1。\n第2章 合\n正文2。\n", encoding="utf-8")
        for chapter in (1, 2):
            path = prologue / "章节" / f"第{chapter}章_摘要.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"旧第{chapter}章事实", encoding="utf-8")
        blocked = run(INDEX, "--source", prologue / "原文" / "原文.txt",
                      "--output", prologue / "chapter_index.csv", "--locator-path", "原文/原文.txt")
        require(blocked.returncode != 0 and "chapter_mapping_ambiguous" in json.loads(blocked.stdout)["error"]
                and not (prologue / "chapter_index.csv").exists(),
                "序章导致旧摘要身份漂移时必须在写索引前明确停止")

        fresh_prologue = area / "序章新书"
        (fresh_prologue / "原文").mkdir(parents=True)
        (fresh_prologue / "原文" / "原文.txt").write_text(
            "序章 引子\n序章事实。\n第1章 起\n正文1。\n第2章 承\n正文2。\n第3章 合\n正文3。\n", encoding="utf-8")
        require(run(INDEX, "--source", fresh_prologue / "原文" / "原文.txt", "--output", fresh_prologue / "chapter_index.csv",
                    "--locator-path", "原文/原文.txt").returncode == 0, "序章新书索引失败")
        for chapter in (1, 2, 3):
            path = fresh_prologue / "章节" / f"第{chapter}章_深度拆解.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("本次 Stage 1 按索引写的黄金章", encoding="utf-8")
        fresh_plan = run(MANAGE, "plan", "--root", fresh_prologue)
        require(fresh_plan.returncode == 0 and [b["batch_id"] for b in json.loads(fresh_plan.stdout)["batches"]]
                == ["REUSE-1-3", "RAW-4-4"],
                "序章开头的新书写完黄金三章后不能被身份守卫卡死：" + fresh_plan.stdout)


PROLOGUE_BOOK = (
    "测试书\n\n楔子 雨夜\n楔子正文。\n\n第一章 起程\n正文一。\n\n第二章 遇敌\n正文二。\n\n"
    "第三章 破局\n正文三。\n\n第四章 回城\n正文四。\n\n第五章 夜谈\n正文五。\n\n第六章 远行\n正文六。\n"
)
# v0.7.10 did not recognize 楔子: its 第1章 is the body's 第一章 (line 6).
OLD_BOUNDARIES = [(1, "第一章 起程", 6), (2, "第二章 遇敌", 9), (3, "第三章 破局", 12),
                  (4, "第四章 回城", 15), (5, "第五章 夜谈", 18), (6, "第六章 远行", 21)]


def legacy_progress(boundary_rows: list[tuple[int, str, int]]) -> str:
    """A v0.7.10-shaped _progress.md: schema 2, paused after Stage 1, 「章节边界」 table."""
    table = "".join(f"| {number} | {title} | {line} | 3 |\n" for number, title, line in boundary_rows)
    return (
        "# 深度拆解进度：测试书\n- 小说：测试书 | 总章数：6 | 输出目录：拆文库/测试书 | 开始：2026-09-01\n"
        "- 最终状态：paused_after_stage1\n- schema_version: 2\n## 管道进度\n| 阶段 | 状态 | 进度 | 备注 |\n"
        "|------|------|------|------|\n| Stage 1 黄金三章 | 完成 | 3/3 章 | — |\n"
        "## 章节边界（Stage 0 章节边界子步骤产物，唯一权威）\n| 章号 | 标题 | 起始行 | 字数 |\n"
        "|------|------|--------|------|\n" + table + "## 分块进度\n| 块 | 章节 | 状态 |\n## 断点\n- 下一操作：Stage 2\n"
    )


def make_legacy_stage1_library(root: Path, boundary_rows: list[tuple[int, str, int]]) -> None:
    source = root / "原文" / "原文.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(PROLOGUE_BOOK, encoding="utf-8")
    (root / "_progress.md").write_text(legacy_progress(boundary_rows), encoding="utf-8")
    for chapter in (1, 2, 3):
        path = root / "章节" / f"第{chapter}章_深度拆解.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"字数约3字 | 核心事件：旧版第{chapter}章事件", encoding="utf-8")
    (root / "快速预览.md").write_text("# 快速预览：测试书\n", encoding="utf-8")


def build_index(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return run(INDEX, "--source", root / "原文" / "原文.txt", "--output", root / "chapter_index.csv",
               "--locator-path", "原文/原文.txt", *extra)


def author_text_is_plain(message: str) -> bool:
    return bool(message) and not re.search(r"[A-Za-z]+_[A-Za-z_]+|RAW-|REUSE-|\.py|\.csv|--", message)


def test_legacy_prologue_alignment() -> None:
    with tempfile.TemporaryDirectory(prefix="long-legacy-prologue-") as temporary:
        area = Path(temporary)
        root = area / "旧版只拆了黄金三章"
        make_legacy_stage1_library(root, OLD_BOUNDARIES)
        protected = protected_snapshot(root)

        blocked = build_index(root)
        payload = json.loads(blocked.stdout)
        require(blocked.returncode == 2 and payload["error"].startswith("chapter_mapping_ambiguous")
                and not (root / "chapter_index.csv").exists(),
                "旧版黄金三章与带楔子的新章号错位时必须在写索引前停下：" + blocked.stdout)
        message = payload.get("author_message", "")
        require("楔子" in message and "按旧章号继续" in message and "新目录" in message,
                "停下时必须给作者可选的出路：" + message)
        require(author_text_is_plain(message), "给作者的话不能夹带字段名、批次号或脚本名：" + message)

        # An index built before this guard existed must not let plan misalign either.
        prebuilt = area / "prebuilt"
        (prebuilt / "原文").mkdir(parents=True)
        (prebuilt / "原文" / "原文.txt").write_text(PROLOGUE_BOOK, encoding="utf-8")
        require(build_index(prebuilt).returncode == 0, "无旧成果的楔子新书必须能建索引")
        shutil.copy2(prebuilt / "chapter_index.csv", root / "chapter_index.csv")
        inspected = json.loads(run(INSPECT, "--root", root, "--compact").stdout)
        require(inspected["chapter_mapping_conflicts"] and inspected["chapter_mapping_author_message"],
                "检查器必须报告旧黄金三章的章号错位")
        plan = run(MANAGE, "plan", "--root", root)
        plan_payload = json.loads(plan.stdout)
        require(plan.returncode == 2 and plan_payload["error"] == "chapter_mapping_ambiguous"
                and "楔子" in plan_payload.get("author_message", ""),
                "计划不能排出 REUSE-1-3 + RAW-4-6 这类静默错位批次：" + plan.stdout)
        (root / "chapter_index.csv").unlink()

        folded = build_index(root, "--fold-prologue")
        folded_payload = json.loads(folded.stdout)
        require(folded.returncode == 0 and folded_payload["folded_into_first_chapter"] == ["楔子"],
                "作者选「按旧章号继续」时楔子必须并入第一章：" + folded.stdout)
        indexed = rows(root / "chapter_index.csv")
        require(indexed[0]["source_chapter"] == "1" and indexed[0]["start_line"] == "3"
                and indexed[0]["title"] == "起程" and indexed[3]["title"] == "回城",
                "并入后新章号必须与旧章节表逐章对齐：" + json.dumps(indexed[:4], ensure_ascii=False))
        aligned_plan = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require([batch["batch_id"] for batch in aligned_plan["batches"]] == ["REUSE-1-3", "RAW-4-6"],
                "对齐后应复用旧黄金三章、只读第四章起的原文：" + json.dumps(aligned_plan, ensure_ascii=False))
        raw_batch = aligned_plan["batches"][1]
        require(raw_batch["source_files"][0] == indexed[3]["source_locator"] and indexed[3]["title"] == "回城",
                "RAW-4-6 读到的必须是「第四章 回城」")
        require(protected_snapshot(root) == protected, "对齐过程不得改动旧拆文文件")

        # Old runs whose table already counted 楔子 as 第1章 stay aligned without folding.
        counted = area / "旧版已把楔子算作第1章"
        make_legacy_stage1_library(counted, [(1, "楔子 雨夜", 3)] + [
            (number + 1, title, line) for number, title, line in OLD_BOUNDARIES[:5]])
        require(build_index(counted).returncode == 0, "旧章节表与新索引一致时不能误拦")

        # Option ②: the author moves the old files aside and restarts from Stage 1.
        restart = area / "楔子单独成章重拆"
        make_legacy_stage1_library(restart, OLD_BOUNDARIES)
        backup = restart / "_analysis_cache" / "legacy" / "旧章号"
        backup.mkdir(parents=True)
        for name in ("_progress.md", "快速预览.md", "章节"):
            shutil.move(str(restart / name), str(backup / name))
        require(build_index(restart).returncode == 0
                and rows(restart / "chapter_index.csv")[0]["source_chapter"] == "楔子",
                "旧文件挪进备份后必须能按新章号（楔子为第1章）重拆")


def test_legacy_summaries_prologue_way_out() -> None:
    with tempfile.TemporaryDirectory(prefix="long-legacy-summaries-") as temporary:
        area = Path(temporary)
        for name, progress in (("有章节表", legacy_progress(OLD_BOUNDARIES)), ("无章节表", None)):
            root = area / name
            source = root / "原文" / "原文.txt"
            source.parent.mkdir(parents=True)
            source.write_text(PROLOGUE_BOOK, encoding="utf-8")
            if progress:
                (root / "_progress.md").write_text(progress, encoding="utf-8")
            for chapter in range(1, 7):
                path = root / "章节" / f"第{chapter}章_摘要.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"**概要**：旧版第{chapter}章", encoding="utf-8")
            blocked = build_index(root)
            payload = json.loads(blocked.stdout)
            require(blocked.returncode == 2 and "按旧章号继续" in payload.get("author_message", "")
                    and author_text_is_plain(payload["author_message"]),
                    f"{name}：楔子开头的旧摘要库必须给出可执行出路：" + blocked.stdout)
            folded = build_index(root, "--fold-prologue")
            require(folded.returncode == 0, f"{name}：并入楔子后必须能建索引：" + folded.stdout)
            plan = run(MANAGE, "plan", "--root", root)
            require(plan.returncode == 0 and json.loads(plan.stdout)["batches"] == [],
                    f"{name}：对齐后旧摘要全部复用、无需重读：" + plan.stdout)


def test_legacy_table_title_variants() -> None:
    """Old tables whose titles differ only in notes, brackets or width still line up."""
    variants = {
        "尾注": ("第一章 起程（求收藏）\n一\n第二章 遇敌(二合一)\n二\n第三章 破局\n三\n", "第一章 起程"),
        "方括号": ("第一章 【起程】\n一\n第二章 遇敌\n二\n第三章 破局\n三\n", "起程"),
        "全角": ("第一章 Ｈｅｌｌｏ起程\n一\n第二章 遇敌\n二\n第三章 破局\n三\n", "第一章 Hello起程"),
        "数字标题": ("1. 起程\n一\n2. 遇敌\n二\n3. 破局\n三\n", "1. 起程"),
    }
    with tempfile.TemporaryDirectory(prefix="long-legacy-titles-") as temporary:
        for name, (text, first_title) in variants.items():
            # Exact start lines, then the same table shifted by one line (titles decide).
            for shift in (0, 1):
                root = Path(temporary) / f"{name}-{shift}"
                make_legacy_stage1_library(root, [(1, first_title, 1 + shift), (2, "第二章 遇敌", 3 + shift),
                                                  (3, "第三章 破局", 5 + shift)])
                (root / "原文" / "原文.txt").write_text(text, encoding="utf-8")
                result = build_index(root)
                require(result.returncode == 0, f"{name}（行差 {shift}）：标题只差尾注/括号/全半角时不能拦：" + result.stdout)
        title_less = Path(temporary) / "只有章号"
        make_legacy_stage1_library(title_less, [(1, "第一章", 1), (2, "第二章", 3), (3, "第三章", 6)])
        (title_less / "原文" / "原文.txt").write_text("第一章\n一\n\n第二章\n二\n\n第三章\n三\n", encoding="utf-8")
        require(build_index(title_less).returncode == 0, "只有章号的旧表按章号对齐，不能按行误判错位")


def test_fold_prologue_survives_rebuild() -> None:
    with tempfile.TemporaryDirectory(prefix="long-fold-rebuild-") as temporary:
        root = Path(temporary) / "并入楔子后追加章节"
        make_legacy_stage1_library(root, OLD_BOUNDARIES)
        require(build_index(root, "--fold-prologue").returncode == 0, "并入楔子建索引失败")
        source = root / "原文" / "原文.txt"
        source.write_text(PROLOGUE_BOOK + "\n第七章 归来\n正文七。\n", encoding="utf-8")
        rebuilt = build_index(root, "--rebuild")
        payload = json.loads(rebuilt.stdout)
        indexed = rows(root / "chapter_index.csv")
        require(rebuilt.returncode == 0 and payload["pending_chapters"] == [7]
                and payload["folded_into_first_chapter"] == ["楔子"]
                and indexed[0]["source_chapter"] == "1" and indexed[6]["title"] == "归来",
                "重建必须沿用上次并入楔子的章号口径：" + rebuilt.stdout)
        # The source now lost chapters: the rebuild stops with a plain explanation.
        source.write_text(PROLOGUE_BOOK.split("第五章")[0], encoding="utf-8")
        shrunk = build_index(root, "--rebuild")
        message = json.loads(shrunk.stdout).get("author_message", "")
        require(shrunk.returncode == 2 and "换一个新目录" in message and author_text_is_plain(message),
                "重建对不上时必须给作者能看懂的出路：" + shrunk.stdout)
        unfolded = Path(temporary) / "楔子单独成章后重建"
        (unfolded / "原文").mkdir(parents=True)
        (unfolded / "原文" / "原文.txt").write_text(PROLOGUE_BOOK, encoding="utf-8")
        require(build_index(unfolded).returncode == 0, "无旧成果的楔子新书必须能建索引")
        mismatch = build_index(unfolded, "--rebuild", "--fold-prologue")
        mismatch_payload = json.loads(mismatch.stdout)
        require(mismatch.returncode == 2 and mismatch_payload["error"] == "chapter_mapping_ambiguous:position=1"
                and author_text_is_plain(mismatch_payload.get("author_message", "")),
                "重建改变章号口径时必须停下并说明：" + mismatch.stdout)


def test_cli_output_is_utf8_on_legacy_consoles() -> None:
    with tempfile.TemporaryDirectory(prefix="long-cp1252-") as temporary:
        root = Path(temporary)
        for encoding in ("cp1252", "gbk"):
            env = {"PYTHONIOENCODING": encoding}
            missing = run(INDEX, "--source", root / "不存在的原文.txt", "--output", root / "索引.csv",
                          extra_env=env)
            require(missing.returncode == 2 and "不存在的原文" in json.loads(missing.stdout)["error"],
                    f"{encoding} 控制台下错误路径必须输出 UTF-8 JSON 而不是崩溃：" + missing.stdout + missing.stderr)
            inspected = run(INSPECT, "--root", root / "不存在", extra_env=env)
            require(inspected.returncode == 2 and "不存在" in json.loads(inspected.stdout)["error"],
                    f"{encoding} 控制台下检查器必须输出 UTF-8")
            helped = run(INSPECT, "--help", extra_env=env)
            require(helped.returncode == 0 and "拆文库" in helped.stdout,
                    f"{encoding} 控制台下检查器的帮助必须能输出：" + helped.stderr[-300:])
            planned = run(MANAGE, "plan", "--root", root / "不存在", extra_env=env)
            require(planned.returncode == 2 and "不存在" in json.loads(planned.stdout)["detail"],
                    f"{encoding} 控制台下运行脚本必须输出 UTF-8")


CHART = RUNTIME / "render_relation_chart.py"


def test_relation_chart_never_falls_back_to_pinyin() -> None:
    with tempfile.TemporaryDirectory(prefix="long-chart-") as temporary:
        root = Path(temporary) / "测试书"
        (root / "角色").mkdir(parents=True)
        (root / "角色" / "角色关系.md").write_text(
            "# 角色关系\n\n| 关系ID | 主体 → 客体 | 关系动作/类型 | 表面关系 | 真实关系 | 触发事件 | 双方得失 | 变化后状态 | 证据强度 | 证据 |\n"
            "|---|---|---|---|---|---|---|---|---|---|\n"
            "| REL-001 | 林远 → 苏晴 | 保护 | 同门 | 暗中倾慕 | 山门遇险 | 林远受伤 | 信任 | A | 第3章 |\n"
            "| REL-002 | 苏晴 → 林远 | 依赖 | 同门 | 依赖 | 山门遇险 | 苏晴脱险 | 依赖 | A | 第3章 |\n"
            "| REL-003 | 林远 → 苏晴 | 背离 | 同门 | 对立 | 宗门大比 | 两败俱伤 | 反目 | B | 第9章 |\n",
            encoding="utf-8")
        for flags, env in (((), {}), (("--png",), {"STORY_ANALYZE_CHART_FONT": "none"})):
            result = run(CHART, "--root", root, *flags, extra_env=env)
            payload = json.loads(result.stdout)
            require(result.returncode == 0 and payload["ok"] and payload["png"] == [],
                    "关系图脚本失败：" + result.stdout + result.stderr)
            chart = (root / "人物关系图" / "人物关系图.md").read_text(encoding="utf-8")
            require("```mermaid" in chart and '["林远"]' in chart and '["苏晴"]' in chart
                    and "信任（山门遇险） → 反目（宗门大比）" in chart,
                    "Markdown 关系图必须保留中文人名和关系演变：" + chart)
            require(not list((root / "人物关系图").glob("*.png")), "没有中文字体时不能生成 PNG")
        require("人物关系图/人物关系图.md" in (payload.get("author_message") or ""),
                "画不了中文图片时必须用大白话告诉作者去看 Markdown 版：" + json.dumps(payload, ensure_ascii=False))
        missing = run(CHART, "--root", Path(temporary))
        require(missing.returncode == 2 and json.loads(missing.stdout)["author_message"],
                "缺关系表时必须给作者能看懂的原因")


def load_chart_module():  # noqa: ANN201 - module object
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_relation_chart_under_test", CHART)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_relation_chart_font_choice() -> None:
    chart = load_chart_module()

    class Face:
        def __init__(self, covered, family: str = "Test") -> None:
            self.covered = covered
            self.family_name = family

        def get_char_index(self, codepoint: int) -> int:
            return 1 if self.covered(chr(codepoint)) else 0

    def cjk_only(char: str) -> bool:
        return char != "\U00020000" and ord(char) < 0x1F000 and char != "⚔"

    faces = {
        "/System/Library/Fonts/LastResort.otf": Face(lambda char: True, "LastResort"),
        "/fonts/AdobeBlank.otf": Face(lambda char: True, "Adobe Blank"),
        "/fonts/NotoSansCJK.ttc": Face(cjk_only),
    }
    chart.font_candidates = lambda: list(faces)
    chart.font_face = lambda path: faces[path]
    os.environ.pop("STORY_ANALYZE_CHART_FONT", None)
    path, missing = chart.find_cjk_font(chart.png_text("🐉龙君⚔ → 林远"))
    require(path == "/fonts/NotoSansCJK.ttc" and not missing,
            "表情和符号应从图片文字里去掉，不能因此放弃中文字体：%s %s" % (path, missing))
    path, missing = chart.find_cjk_font(chart.png_text("\U00020000祖 林远"))
    require(path is None and missing == ["\U00020000"],
            "中文字体缺字时不能退到 LastResort 这类只画方框的兜底字体：%s %s" % (path, missing))
    cjk_face = faces.pop("/fonts/NotoSansCJK.ttc")
    require(chart.find_cjk_font("林远") == (None, []), "只剩兜底字体时等同于没有中文字体")
    faces["/fonts/NotoSansCJK.ttc"] = cjk_face

    with tempfile.TemporaryDirectory(prefix="long-chart-font-") as temporary:
        root = Path(temporary) / "测试书"
        (root / "角色").mkdir(parents=True)
        (root / "角色" / "角色关系.md").write_text(
            "| 主体 → 客体 | 变化后状态 |\n|---|---|\n| \U00020000祖 → 林远 | 师徒 |\n", encoding="utf-8")
        chart.matplotlib_available = lambda: True
        payload = chart.render(root, True)
        require(payload["png"] == [] and "显示不了" in payload["author_message"]
                and "没有找到能显示中文的字体" not in payload["author_message"],
                "有中文字体只是缺字时，要照实说缺哪几个字：" + json.dumps(payload, ensure_ascii=False))
        faces["/fonts/NotoSansCJK.ttc"] = Face(lambda char: True)

        def broken_draw(*_args: object) -> list[str]:
            raise RuntimeError("draw failed")

        chart.draw_png = broken_draw
        payload = chart.render(root, True)
        require(payload["ok"] and (root / "人物关系图" / "人物关系图.md").is_file() and payload["author_message"],
                "画图片出错时 Markdown 关系图必须已经写好：" + json.dumps(payload, ensure_ascii=False))


def test_relation_chart_mermaid_edge_cases() -> None:
    with tempfile.TemporaryDirectory(prefix="long-chart-mermaid-") as temporary:
        root = Path(temporary) / "测试书"
        (root / "角色").mkdir(parents=True)
        (root / "角色" / "角色关系.md").write_text(
            "| 关系ID | 主体 → 客体 | 关系动作/类型 | 变化后状态 |\n|---|---|---|---|\n"
            "| R1 | ** → 林远 | ** | %%{init: {}}%% |\n"
            "| R2 | 林远 ↔ 苏晴 | 同盟 | 同盟 |\n"
            "| R3 | 林远 -> 苏晴 -> 赵三 | 利用 | 利用 |\n"
            "| R4 | 只有一个人 | 敌对 | 敌对 |\n",
            encoding="utf-8")
        result = run(CHART, "--root", root)
        payload = json.loads(result.stdout)
        chart = (root / "人物关系图" / "人物关系图.md").read_text(encoding="utf-8")
        block = chart.split("```mermaid", 1)[1].split("```", 1)[0]
        require(result.returncode == 0 and '[""]' not in block and '|""|' not in block and "%%" not in block,
                "Mermaid 标签清洗后为空或含 %% 时必须换成占位词：" + block)
        require(re.search(r'p\d+ -->\|"同盟"\| p\d+', block) and block.count('-->|"同盟"|') == 1
                and "苏晴 → 林远：同盟" in chart and "苏晴 → 赵三：利用" in chart,
                "↔ 要画成双向、链式关系要逐段画出：" + chart)
        require(payload["skipped_rows"] == 1 and "1 行" in (payload["author_message"] or ""),
                "认不出的关系行要报出数量：" + result.stdout)


def main() -> int:
    test_index_contract()
    test_invalid_root_and_manage_entry()
    test_index_existing_supported_forms()
    test_inspection_legacy_and_partial()
    test_plan_commit_repair_and_state_preservation()
    test_split_survives_replanning()
    test_panlong_acceptance_samples()
    test_audit_recovery_regressions()
    test_audit_stage_and_mapping_regressions()
    test_legacy_prologue_alignment()
    test_legacy_summaries_prologue_way_out()
    test_legacy_table_title_variants()
    test_fold_prologue_survives_rebuild()
    test_cli_output_is_utf8_on_legacy_consoles()
    test_relation_chart_never_falls_back_to_pinyin()
    test_relation_chart_font_choice()
    test_relation_chart_mermaid_edge_cases()
    print("OK: single-state long-analyze runtime regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
