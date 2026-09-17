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
        for command in ("plan", "commit", "split", "repair-progress", "mark-stage", "migrate-legacy"):
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


def compact_output(start: int, end: int, *, tone: str = "期待", theme: str = "陌生主题") -> str:
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
**情节点类型**：动作
**情节点标题**：取得入口
**主题标签**：{theme}
**基调**：{tone}
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
        require("类型行动" in summary and "涉及人物甲、人物乙" in summary, "情节点类型与涉及人物必须兼容旧消费者")
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
        require([batch["batch_id"] for batch in changed_plan["batches"]] == ["RAW-2-2"], "局部原文变化只重做对应章")

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
        write_source_and_index(root, 12)
        first = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require(first["batches"][0]["batch_id"] == "RAW-1-10", "恰好10章必须合法成块")
        split = run(MANAGE, "split", "--root", root, "--batch-id", "RAW-1-10", "--at", 5)
        require(split.returncode == 0 and json.loads(split.stdout)["children"] == ["RAW-1-5", "RAW-6-10"], split.stdout)
        second = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        ids = [batch["batch_id"] for batch in second["batches"]]
        require("RAW-1-5" in ids and "RAW-6-10" in ids and "RAW-1-10" not in ids, "拆分必须相邻且重规划不能合回父块")


def test_panlong_acceptance_samples() -> None:
    source_demo = ROOT / "demo" / "拆文库" / "盘龙"
    require(source_demo.is_dir(), "盘龙验收样本缺失")
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

        reanalyze = area / "明确重拆"
        shutil.copytree(source_demo, reanalyze)
        require(run(INDEX, "--source", reanalyze / "原文" / "原文.txt", "--output", reanalyze / "chapter_index.csv", "--locator-path", "原文/原文.txt").returncode == 0, "重拆索引失败")
        reanalyze_plan = json.loads(run(MANAGE, "plan", "--root", reanalyze, "--intent", "reanalyze").stdout)
        require(sum(batch["chapter_range"][1] - batch["chapter_range"][0] + 1 for batch in reanalyze_plan["batches"]) == 23, "明确重拆必须覆盖全部章")
        require(all(batch["input_kind"] == "raw-original" for batch in reanalyze_plan["batches"]), "明确重拆不能复用旧语义")


def test_six_script_migration_is_read_only() -> None:
    with tempfile.TemporaryDirectory(prefix="long-migrate-refactor-") as temporary:
        root = Path(temporary)
        for chapter in (1, 2):
            path = root / "章节" / f"第{chapter}章_摘要.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"旧摘要{chapter}", encoding="utf-8")
        progress = root / "_progress.md"
        progress.write_text(
            "# 旧六脚本进度\n- schema_version: 2\n"
            "<!-- story-long-analyze:batch:B001:start -->\n"
            "- chapters: 1-2\n- input_kind: raw-original\n- status: success\n"
            "<!-- story-long-analyze:batch:B001:end -->\n",
            encoding="utf-8",
        )
        old_cache = root / "_analysis_cache" / "批次-1-2.md"
        old_cache.parent.mkdir(parents=True, exist_ok=True)
        old_cache.write_text("# 旧缓存\n<!-- BATCH_OBSERVATIONS_END -->\n", encoding="utf-8")
        receipt = {
            "status": "success", "chapter_range": [1, 2], "input_kind": "raw-original",
            "source_sha256": "a" * 64,
            "outputs": {"_analysis_cache/批次-1-2.md": hashlib.sha256(old_cache.read_bytes()).hexdigest()},
        }
        receipt_path = root / "_analysis_cache" / "receipts" / "B001.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        legacy_before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        migrated = run(MANAGE, "migrate-legacy", "--root", root)
        payload = json.loads(migrated.stdout)
        require(migrated.returncode == 0 and [item["batch_id"] for item in payload["migrated"]] == ["RAW-1-2"], migrated.stdout)
        compat = root / "_analysis_cache" / "迁移-RAW-1-2.md"
        require(compat.read_text(encoding="utf-8").rstrip().endswith("<!-- story-long-analyze:cache:end -->"), "迁移缓存必须有新的完整结束标记")
        for relative, data in legacy_before.items():
            if relative == "_progress.md":
                continue
            require((root / relative).read_bytes() == data, "迁移不能修改或删除旧文件：" + relative)
        require("schema_version: 2" in progress.read_text(encoding="utf-8-sig"), "迁移不能改旧 schema")
        second = run(MANAGE, "migrate-legacy", "--root", root)
        require(second.returncode == 0 and compat.is_file(), "迁移必须幂等")


def test_audit_recovery_and_request_regressions() -> None:
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

        reanalyze = json.loads(run(MANAGE, "plan", "--root", root, "--intent", "reanalyze").stdout)
        request_id = reanalyze["request_id"]
        require(request_id and [batch["batch_id"] for batch in reanalyze["batches"]] == ["RAW-1-2"],
                "首次明确重拆不能被旧 completed 跳过")
        rerun = run(MANAGE, "commit", "--root", root, "--input", model,
                    "--batch-id", "RAW-1-2", "--range-sha256", reanalyze["batches"][0]["range_sha256"],
                    "--intent", "reanalyze", "--request-id", request_id)
        require(rerun.returncode == 0, rerun.stdout or rerun.stderr)
        resumed = json.loads(run(MANAGE, "plan", "--root", root, "--intent", "reanalyze",
                                 "--request-id", request_id).stdout)
        require(resumed["batches"] == [], "同一重拆请求恢复时不得重复已完成批次")
        next_request = json.loads(run(MANAGE, "plan", "--root", root, "--intent", "reanalyze").stdout)
        require(next_request["request_id"] != request_id and next_request["batches"],
                "新的明确重拆请求必须有新请求 ID 并重新执行")

        oversized = area / "超限提交"
        write_source_and_index(oversized, 11)
        oversized_model = area / "oversized.md"
        oversized_model.write_text(compact_output(1, 11), encoding="utf-8")
        index_rows = rows(oversized / "chapter_index.csv")
        payload = "range-v1\n" + "".join(f"{row['chapter']}:{row['chapter_sha256']}\n" for row in index_rows)
        range_hash = hashlib.sha256(payload.encode("ascii")).hexdigest()
        refused = run(MANAGE, "commit", "--root", oversized, "--input", oversized_model,
                      "--batch-id", "RAW-1-11", "--range-sha256", range_hash)
        require(refused.returncode != 0 and json.loads(refused.stdout)["error"] == "batch_too_large",
                "提交入口必须拒绝超过10章的手工批次")


def test_audit_stage_compact_and_mapping_regressions() -> None:
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
        for stage in ("stage1", "stage2", "stage3", "stage4", "stage5", "stage6"):
            marked = run(MANAGE, "mark-stage", "--root", root, "--stage", stage)
            require(marked.returncode == 0, marked.stdout or marked.stderr)
        complete = json.loads(run(INSPECT, "--root", root).stdout)
        require(complete["classification"] == "current_complete"
                and complete["recommended_path"] == "direct_use",
                "受管 Stage 1-6 全部完成时必须识别为 current_complete/direct_use")

        compact = area / "精简成果"
        (compact / "v2" / "章节卡").mkdir(parents=True)
        (compact / "v2" / "章节卡" / "批次1.md").write_text(
            "| 1 | 第一章 | 事实一 |\n| 2 | 第二章 | 事实二 |\n", encoding="utf-8")
        (compact / "v2" / "_progress.md").write_text(
            "# 进度\n- 总章数：2\n- 最终状态：completed\n", encoding="utf-8")
        (compact / "v2" / "全局建模.md").write_text("有效全局建模", encoding="utf-8")
        inspected = run(INSPECT, "--root", compact)
        payload = json.loads(inspected.stdout)
        require(inspected.returncode == 0 and payload["classification"] == "legacy_complete",
                "完整精简成果必须可检查，不能触发 NameError")

        compact_mixed = area / "精简与标准成果混存"
        shutil.copytree(compact, compact_mixed)
        standard = compact_mixed / "章节" / "第1章_摘要.md"
        standard.parent.mkdir(parents=True)
        standard.write_text("标准摘要事实", encoding="utf-8")
        mixed_inspected = run(INSPECT, "--root", compact_mixed)
        mixed_payload = json.loads(mixed_inspected.stdout)
        require(mixed_inspected.returncode == 0 and mixed_payload["classification"] == "legacy_complete"
                and mixed_payload["mixed_sources"],
                "精简成果与标准摘要混存时必须可检查并报告来源混存")

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


def test_audit_legacy_source_change_regression() -> None:
    source_demo = ROOT / "demo" / "拆文库" / "盘龙"
    with tempfile.TemporaryDirectory(prefix="long-audit-source-change-") as temporary:
        root = Path(temporary) / "盘龙"
        shutil.copytree(source_demo, root)
        require(run(INDEX, "--source", root / "原文" / "原文.txt", "--output", root / "chapter_index.csv",
                    "--locator-path", "原文/原文.txt").returncode == 0, "旧项目首次索引失败")
        indexed = rows(root / "chapter_index.csv")
        source = root / "原文" / "原文.txt"
        source_lines = source.read_text(encoding="utf-8-sig").split("\n")
        source_lines[int(indexed[6]["start_line"])] += "第七章输入已经变化。"
        source.write_text("\n".join(source_lines), encoding="utf-8")
        rebuilt = run(INDEX, "--source", source, "--output", root / "chapter_index.csv",
                      "--locator-path", "原文/原文.txt", "--rebuild")
        require(rebuilt.returncode == 0 and json.loads(rebuilt.stdout)["pending_chapters"] == [7],
                "旧项目局部变化必须由索引精确定位")
        changed_plan = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require([batch["batch_id"] for batch in changed_plan["batches"]] == ["RAW-7-7"],
                "旧摘要不能掩盖已知的第7章原文变化")
        old_summary = (root / "章节" / "第7章_摘要.md").read_bytes()
        model = Path(temporary) / "chapter7.md"
        model.write_text(compact_output(7, 7), encoding="utf-8")
        committed = run(MANAGE, "commit", "--root", root, "--input", model,
                        "--batch-id", "RAW-7-7", "--range-sha256", changed_plan["batches"][0]["range_sha256"])
        require(committed.returncode == 0 and (root / "章节" / "第7章_摘要.md").read_bytes() == old_summary,
                "原文变化分析必须保留用户已有摘要")
        after = json.loads(run(MANAGE, "plan", "--root", root).stdout)
        require(after["batches"] == [] and {"stage3", "stage4", "stage5", "stage6"}.issubset(after["required_stages"]),
                "当前 RAW 完成后应停止重复提取，并保留下游阶段 pending")


def test_local_rebuild_preserves_unchanged_batch_chapters() -> None:
    with tempfile.TemporaryDirectory(prefix="long-local-rebuild-") as temporary:
        root = Path(temporary) / "原批次"
        source = write_source_and_index(root, 3)
        model = Path(temporary) / "model.md"

        def plan() -> dict:
            result = run(MANAGE, "plan", "--root", root)
            require(result.returncode == 0, result.stdout or result.stderr)
            return json.loads(result.stdout)

        def commit(batch: dict) -> None:
            start, end = batch["chapter_range"]
            model.write_text(compact_output(start, end), encoding="utf-8")
            result = run(MANAGE, "commit", "--root", root, "--input", model,
                         "--batch-id", batch["batch_id"], "--range-sha256", batch["range_sha256"])
            require(result.returncode == 0, result.stdout or result.stderr)

        def change_chapter(chapter: int) -> None:
            source.write_text(source.read_text(encoding="utf-8").replace(
                f"正文{chapter}。", f"正文{chapter}已改变。"), encoding="utf-8")
            rebuilt = run(INDEX, "--source", source, "--output", root / "chapter_index.csv",
                          "--locator-path", "原文/原文.txt", "--rebuild")
            require(rebuilt.returncode == 0, rebuilt.stdout or rebuilt.stderr)

        commit(plan()["batches"][0])
        original_summaries = protected_snapshot(root)
        parent_cache = root / "_analysis_cache" / "批次-RAW-1-3.md"
        parent_bytes = parent_cache.read_bytes()

        change_chapter(2)
        changed = plan()
        require([batch["batch_id"] for batch in changed["batches"]] == ["RAW-2-2"],
                "局部变化只应分析第2章")
        commit(changed["batches"][0])
        progress_before = (root / "_progress.md").read_bytes()
        for _ in range(2):
            after = plan()
            require(after["batches"] == [] and after["read_counts"]["raw_chapters"] == 0,
                    "变化章补完后不能把旧父批次的未变化章重新规划：" + json.dumps(after, ensure_ascii=False))
        require((root / "_progress.md").read_bytes() == progress_before, "重规划必须仍然只读")

        # A second rebuild moves the parent's matching index into legacy evidence.
        change_chapter(3)
        next_plan = plan()
        require([batch["batch_id"] for batch in next_plan["batches"]] == ["RAW-3-3"],
                "连续重建仍须保留第1章完成资格，且不能重做刚补完的第2章")
        commit(next_plan["batches"][0])
        require(plan()["batches"] == [], "第二次局部补完后也不应留下原文任务")
        require(protected_snapshot(root) == original_summaries and parent_cache.read_bytes() == parent_bytes,
                "局部恢复不得改写已有摘要或旧父批次缓存")

        # Historical index evidence cannot excuse a missing or truncated cache.
        for broken in (None, parent_bytes[:len(parent_bytes) // 2]):
            if broken is None:
                parent_cache.unlink()
            else:
                parent_cache.write_bytes(broken)
            retry = plan()
            require([batch["batch_id"] for batch in retry["batches"]] == ["RAW-1-1"],
                    "旧缓存缺失或截断时，未被新有效缓存覆盖的第1章仍须恢复")
        parent_cache.write_bytes(parent_bytes)
        require(plan()["batches"] == [], "完整旧缓存恢复后应再次复用未变化章")


def main() -> int:
    test_index_contract()
    test_invalid_root_and_manage_entry()
    test_index_existing_supported_forms()
    test_inspection_legacy_and_partial()
    test_plan_commit_repair_and_state_preservation()
    test_split_survives_replanning()
    test_panlong_acceptance_samples()
    test_six_script_migration_is_read_only()
    test_audit_recovery_and_request_regressions()
    test_audit_stage_compact_and_mapping_regressions()
    test_audit_legacy_source_change_regression()
    test_local_rebuild_preserves_unchanged_batch_chapters()
    print("OK: single-state long-analyze runtime regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
