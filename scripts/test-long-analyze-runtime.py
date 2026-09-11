#!/usr/bin/env python3
"""Behavioral regressions for long-analysis indexing and reuse inspection."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills/story-long-analyze/scripts/build_chapter_index.py"
INSPECT_SCRIPT = ROOT / "skills/story-long-analyze/scripts/inspect_existing_assets.py"
COMMIT_SCRIPT = ROOT / "skills/story-long-analyze/scripts/commit_batch_output.py"
PLAN_SCRIPT = ROOT / "skills/story-long-analyze/scripts/plan_analysis_run.py"
CHECKPOINT_SCRIPT = ROOT / "skills/story-long-analyze/scripts/manage_batch_checkpoint.py"
STAGE_SCRIPT = ROOT / "skills/story-long-analyze/scripts/commit_stage_output.py"
EXPECTED_COLUMNS = (
    "chapter",
    "source_chapter",
    "volume",
    "title",
    "start_line",
    "end_line",
    "char_count",
    "source_locator",
    "status",
    "source_sha256",
    "parser_version",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(source: Path, output: Path, progress: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(source),
            "--output",
            str(output),
            "--progress",
            str(progress),
            "--locator-path",
            f"原文/{source.name}",
            *extra,
        ],
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        check=False,
    )


def read_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return tuple(reader.fieldnames or ()), rows


def run_inspect(root: Path, expected: int | None = None) -> dict[str, object]:
    command = [sys.executable, str(INSPECT_SCRIPT), "--root", str(root)]
    if expected is not None:
        command.extend(["--expected-chapters", str(expected)])
    completed = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        check=False,
    )
    require(completed.returncode == 0, completed.stdout or completed.stderr)
    return json.loads(completed.stdout)


def run_plan(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PLAN_SCRIPT), "--root", str(root), *extra],
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        check=False,
    )


def write_index(root: Path, counts: list[int], source_hash: str = "a" * 64) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "chapter_index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        line = 1
        for chapter, count in enumerate(counts, start=1):
            writer.writerow(
                {
                    "chapter": chapter,
                    "source_chapter": chapter,
                    "volume": "",
                    "title": f"第{chapter}章",
                    "start_line": line,
                    "end_line": line + 9,
                    "char_count": count,
                    "source_locator": f"原文/原文.txt#L{line}-L{line + 9}",
                    "status": "ok" if count else "empty",
                    "source_sha256": source_hash,
                    "parser_version": "1",
                }
            )
            line += 10


def run_commit(
    source: Path,
    root: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(COMMIT_SCRIPT),
            "--input",
            str(source),
            "--root",
            str(root),
            "--batch-id",
            "B001",
            "--start",
            "1",
            "--end",
            "2",
            "--source-sha256",
            "a" * 64,
            *extra,
        ],
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        check=False,
    )


def valid_batch() -> str:
    return """# 批次 B001：第1-2章

<!-- CHAPTER_START:1 -->
## 第1章 开端

**概要**：甲索要钥匙被拒绝，进入房间的目标暂时受阻。

**关键事件**：
1. 甲索要钥匙，守门人拒绝。

**章节卡**：

| 一句话因果 | 目标/障碍/结果 | 信息变化 | 关系/状态变化 | 章尾钩子 | 三维节奏 | 证据 |
|---|---|---|---|---|---|---|
| 甲要进房但被拒绝 | 进房/守门人/失败 | 读者知道门被控制 | 甲转为求助乙 | 谁会帮甲 | 剧情2；紧张2；展开1 | 原文/小说.txt#L2 |

**情节点**：

P1 **索要钥匙**：类型冲突 | 甲索要钥匙，守门人拒绝 | 涉及甲 | 地点门口 | 物品钥匙 | 时间无 | 证据拒绝交钥匙
主题标签权力 | 基调：紧张

<!-- CHAPTER_END:1 -->

<!-- CHAPTER_START:2 -->
## 第2章 援助

**概要**：乙交出备用钥匙，甲得以进入房间，乙也因此暴露立场。

**关键事件**：
1. 乙把备用钥匙交给甲。

**章节卡**：

| 一句话因果 | 目标/障碍/结果 | 信息变化 | 关系/状态变化 | 章尾钩子 | 三维节奏 | 证据 |
|---|---|---|---|---|---|---|
| 乙为帮甲交钥匙并承担风险 | 进房/无钥匙/成功 | 读者确认乙愿意帮助 | 甲乙暂时结盟 | 乙是否被追查 | 剧情4；释然3；展开2 | 原文/小说.txt#L8 |

**情节点**：

P1 **交出钥匙**：类型行动 | 乙把备用钥匙交给甲，甲得以进房 | 涉及甲,乙 | 地点门口 | 物品钥匙 | 时间无 | 证据备用钥匙
主题标签友情 | 基调：紧张

<!-- CHAPTER_END:2 -->

<!-- BATCH_OBSERVATIONS_START -->
## 跨章观察

### 剧情点

| 剧情点ID | 章节范围 | 起始目标 | 阻碍 | 关键选择/行动/外部事件 | 局面变化 | 得失与承担者 | 后续影响 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| BP-B001-01 | 1-2 | 甲要进房 | 守门人拒绝 | 乙交钥匙 | 甲进入 | 甲获机会，乙担风险 | 乙可能被追查 | closed | 索要钥匙、备用钥匙 |

### 客观事件

| 事件ID | 客观发生时间/顺序 | 事件 | 参与者 | 结果 | 证据强度 | 证据 |
|---|---|---|---|---|---|---|
| EV1 | 2 | 乙交钥匙 | 甲、乙 | 甲进入 | A | 备用钥匙 |

### 信息披露

| 披露ID | 事件引用 | 披露章节/片段 | 异常/线索/解释/确认 | 读者所知 | 关键角色所知 | 判断变化 | 叙事作用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| RV1 | EV1 | 第2章 | 确认 | 乙愿意帮助 | 甲知情 | 不确定转为确认 | 兑现期待 | 交出钥匙 |

### 关系变化

| 关系ID | 主体 → 客体 | 关系动作 | 表面/真实状态 | 触发 | 双方得失 | 变化后状态 | 证据强度 | 证据 |
|---|---|---|---|---|---|---|---|---|
| R1 | 乙 → 甲 | 援助 | 一致 | 交钥匙 | 甲获机会，乙担风险 | 暂时结盟 | A | 备用钥匙 |

### 三维节奏

| 节奏ID | 章节/剧情点 | 事件推进1-5及理由 | 读者情绪类型/强度1-5及触发 | 篇幅展开度1-3 | 展开/压缩/省略/反复及作用 | 证据 |
|---|---|---|---|---|---|---|
| AX1 | 1-2 | 4，进入资格改变 | 紧张3，因乙暴露 | 2 | 展开选择，压缩进门 | 拒绝、备用钥匙 |

### 跨批状态

- 未闭合剧情点：无
- 未决悬念：乙是否被追查
- 关系状态：甲乙暂时结盟
- 待核事项：无

<!-- BATCH_OBSERVATIONS_END -->
"""


def compact_batch() -> str:
    chapters = []
    for chapter, title, summary, causal, info, state, rhythm, hook, evidence in (
        (1, "开端", "甲索要钥匙被拒，进入房间的目标受阻。", "目标：甲进房｜阻碍：守门人拒绝｜行动：甲转而求助乙｜结果：获得新的解决路径｜得失：甲暂未进房，乙面临选边", "读者知道门被控制；甲不知道乙是否愿意帮忙", "甲乙关系从陌生转为可能结盟；暴露风险上升", "事件2/5｜情绪紧张3/5｜篇幅1/3｜事件较少但等待答案维持紧张", "悬念：乙是否帮甲", "原文/小说.txt#L2-L7 + 拒绝交钥匙"),
        (2, "援助", "乙交出备用钥匙，甲得以进入房间，乙也暴露立场。", "目标：甲进房｜阻碍：没有钥匙｜行动：乙交出备用钥匙｜结果：甲成功进房｜得失：甲获得入口，乙承担被追查风险", "读者与甲确认乙愿意帮助；守门人仍不知道", "甲乙形成临时同盟；乙的风险升高", "事件4/5｜情绪释然3/5｜篇幅2/3｜行动推进明显，情绪释放适中", "风险：乙是否被追查", "原文/小说.txt#L8-L14 + 备用得把这把钥匙"),
    ):
        chapters.append(
            f"""<!-- CHAPTER_START:{chapter} -->
## 第{chapter}章 {title}

**概要**：{summary}

**因果**：{causal}

**信息变化**：{info}

**状态变化**：{state}

**三维节奏**：{rhythm}

**章尾钩子**：{hook}

**证据**：{evidence}
<!-- CHAPTER_END:{chapter} -->"""
        )
    return "# 批次 B001：第1-2章\n\n" + "\n\n".join(chapters) + """

<!-- BATCH_OBSERVATIONS_START -->
## 跨章观察

### 剧情点
- BP-B001-01｜1-2｜甲进房→受阻→乙交钥匙→成功进入；甲获入口，乙承担风险｜closed｜原文/小说.txt#L2-L14

### 关键事件与披露候选
- KE-B001-01｜第2章｜乙交钥匙｜读者与甲同步确认乙站队｜结盟判断成立｜原文/小说.txt#L8-L14

### 关系变化
- 甲→乙：求助并接受帮助；乙→甲：冒险支持；由陌生转为临时同盟。

### 三维节奏
- 第2章｜事件4/5｜释然3/5｜篇幅2/3｜快速行动释放上一章等待。

### 跨批状态
- 未闭合剧情点：无。
- 未决悬念：乙是否被追查。
- 关系状态：甲乙临时同盟。
- 待核事项：无。
<!-- BATCH_OBSERVATIONS_END -->
"""

def valid_existing_result_batch() -> str:
    observations = valid_batch().split("<!-- BATCH_OBSERVATIONS_START -->", maxsplit=1)[1]
    observations = observations.replace("### 候选剧情单元", "### 剧情点", 1)
    return (
        "# 已有成果二次提取 B001：第1-2章\n\n"
        "<!-- REUSED_CHAPTERS:1-2 -->\n\n"
        "<!-- BATCH_OBSERVATIONS_START -->"
        + observations
    )


def put(path: Path, text: str = "有效资料") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_boundaries_reuse_and_source_change() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-index-") as temporary:
        root = Path(temporary)
        source = root / "小说.txt"
        output = root / "chapter_index.csv"
        progress = root / "_progress.md"
        progress.write_text("# 进度\n- schema_version: 2\n", encoding="utf-8")
        source.write_text(
            "第一章没有空格的标题\n开篇。\n0.1秒遭到回怼。\n1. 这是正文里的列表。\n第二章 有空格\n推进。\nChapter 3: End\n收束。\n第四章\n",
            encoding="utf-8",
        )

        first = run(source, output, progress)
        require(first.returncode == 0, first.stdout or first.stderr)
        payload = json.loads(first.stdout)
        require(payload["chapters"] == 4 and payload["empty_chapters"] == 1, "empty chapters must be explicit")
        columns, rows = read_rows(output)
        require(columns == EXPECTED_COLUMNS, "index must contain the documented mechanical columns")
        require(rows[0]["title"] == "没有空格的标题", "Chinese headings without spaces must be accepted")
        require(rows[-1]["status"] == "empty" and rows[-1]["char_count"] == "0", "heading text is not chapter body")
        require(len({row["source_sha256"] for row in rows}) == 1, "source hash must be recorded")
        require({row["parser_version"] for row in rows} == {"2"}, "parser version must be recorded")
        require("story-long-analyze:chapter-index:start" in progress.read_text(encoding="utf-8"), "progress metadata missing")

        before = (output.stat().st_mtime_ns, output.read_bytes(), progress.stat().st_mtime_ns)
        second = run(source, output, progress)
        second_payload = json.loads(second.stdout)
        require(second.returncode == 0 and second_payload["reused"], "valid same-source index must be reused")
        require(not second_payload["parsed_source"], "same-source reuse must skip chapter-boundary parsing")
        after = (output.stat().st_mtime_ns, output.read_bytes(), progress.stat().st_mtime_ns)
        require(before == after, "reuse must not rewrite index or progress")

        stable_index = (output.stat().st_mtime_ns, output.read_bytes())
        progress.write_text("# 进度\n- schema_version: 2\n", encoding="utf-8")
        recovered = run(source, output, progress)
        recovered_payload = json.loads(recovered.stdout)
        require(
            recovered.returncode == 0 and recovered_payload["reused"] and recovered_payload["repaired_progress"],
            "an interrupted index/progress pair must repair progress without a rebuild",
        )
        require(stable_index == (output.stat().st_mtime_ns, output.read_bytes()), "progress recovery must not rewrite the valid index")
        require("story-long-analyze:chapter-index:start" in progress.read_text(encoding="utf-8"), "recovery must restore progress metadata")

        source.write_text(source.read_text(encoding="utf-8") + "补充正文。\n", encoding="utf-8")
        changed = run(source, output, progress)
        require(changed.returncode == 2, "source changes require an explicit rebuild")
        require(json.loads(changed.stdout)["error"] == "existing_index_incompatible", "source change error must be specific")
        rebuilt = run(source, output, progress, "--rebuild")
        require(rebuilt.returncode == 0 and not json.loads(rebuilt.stdout)["reused"], "explicit rebuild must refresh the index")


def test_toc_short_chapters_and_volumes() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-forms-") as temporary:
        root = Path(temporary)

        short = root / "短章.txt"
        short.write_text("第一章\n一。\n第二章\n二。\n第三章\n三。\n第四章\n四。\n", encoding="utf-8")
        short_result = run(short, root / "short.csv", root / "short-progress.md")
        require(short_result.returncode == 0 and json.loads(short_result.stdout)["chapters"] == 4, "short real chapters are not a TOC")

        toc = root / "目录.txt"
        toc.write_text(
            "目录\n第一章 开端\n第二章 推进\n第三章 收束\n\n说明文字很多。\n说明文字很多。\n"
            "第一章 开端\n正文一。\n正文一。\n第二章 推进\n正文二。\n正文二。\n第三章 收束\n正文三。\n",
            encoding="utf-8",
        )
        toc_result = run(toc, root / "toc.csv", root / "toc-progress.md")
        require(toc_result.returncode == 0 and json.loads(toc_result.stdout)["chapters"] == 3, "a repeated dense leading TOC must be removed")

        volumes = root / "多卷.txt"
        volumes.write_text(
            "第一卷 第一章 起点\n一。\n第一卷 第二章 推进\n二。\n第二卷 第一章 新局\n三。\n第二卷 第二章 收束\n四。\n",
            encoding="utf-8",
        )
        volume_result = run(volumes, root / "volumes.csv", root / "volume-progress.md")
        require(volume_result.returncode == 0, volume_result.stdout or volume_result.stderr)
        _, volume_rows = read_rows(root / "volumes.csv")
        require([row["chapter"] for row in volume_rows] == ["1", "2", "3", "4"], "global chapter ids must stay continuous")
        require([row["source_chapter"] for row in volume_rows] == ["1", "2", "1", "2"], "volume-local chapter ids must be preserved")

        duplicate = root / "重复.txt"
        duplicate.write_text("第一卷 第一章\n一。\n第一卷 第一章\n又一。\n", encoding="utf-8")
        duplicate_result = run(duplicate, root / "duplicate.csv", root / "duplicate-progress.md")
        require(duplicate_result.returncode == 2, "duplicates inside a combined volume heading must be rejected")
        require("chapter_number_duplicate" in json.loads(duplicate_result.stdout)["error"], "duplicate error must be specific")

        exported_duplicate = root / "导出重复标题.txt"
        exported_duplicate.write_text(
            "1.开端\n正文一。\n2.推进（作者话）\n\n    2.推进\n正文二。\n3.收束\n正文三。\n",
            encoding="utf-8",
        )
        exported_result = run(
            exported_duplicate,
            root / "exported-duplicate.csv",
            root / "exported-duplicate-progress.md",
        )
        require(
            exported_result.returncode == 0 and json.loads(exported_result.stdout)["chapters"] == 3,
            "an adjacent numeric export duplicate separated only by blank lines must be repaired",
        )

        missing = root / "缺章.txt"
        missing.write_text("第一章 开端\n一。\n第三章 跳号\n三。\n", encoding="utf-8")
        missing_result = run(missing, root / "missing.csv", root / "missing-progress.md")
        require(missing_result.returncode == 2, "missing chapter numbers must be rejected")
        require("chapter_number_gap" in json.loads(missing_result.stdout)["error"], "chapter gaps must be explicit")

        numeric = root / "数字标题.txt"
        numeric.write_text("1. 开端\n正文一。\n2．推进\n正文二。\n3、收束\n正文三。\n", encoding="utf-8")
        numeric_result = run(numeric, root / "numeric.csv", root / "numeric-progress.md")
        require(numeric_result.returncode == 0, numeric_result.stdout or numeric_result.stderr)
        _, numeric_rows = read_rows(root / "numeric.csv")
        require([row["title"] for row in numeric_rows] == ["开端", "推进", "收束"], "documented numeric headings must parse")

        numbered_prose = root / "正文列表.txt"
        numbered_prose.write_text("第一章 开端\n1. 不是章名\n正文。\n第二章 收束\n2. 也不是章名\n正文。\n", encoding="utf-8")
        numbered_result = run(numbered_prose, root / "numbered.csv", root / "numbered-progress.md")
        require(
            numbered_result.returncode == 0 and json.loads(numbered_result.stdout)["chapters"] == 2,
            "numbered prose must not override explicit chapter headings",
        )

        encoded = root / "国标编码.txt"
        encoded.write_bytes("第一章 编码\n正文一。\n第二章 继续\n正文二。\n".encode("gb18030"))
        encoded_result = run(encoded, root / "encoded.csv", root / "encoded-progress.md")
        require(encoded_result.returncode == 0, "GB18030 source text must be readable")


def test_existing_asset_compatibility_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-assets-") as temporary:
        fixture_root = Path(temporary)

        legacy = fixture_root / "legacy-complete"
        for chapter in range(1, 4):
            put(legacy / "章节" / f"第{chapter}章_摘要.md")
        put(legacy / "拆文报告.md", "# 拆文报告\n\n| 项目 | 内容 |\n|---|---|\n| 总章数 | 3章 |\n")
        put(legacy / "剧情" / "故事线.md")
        put(legacy / "角色" / "甲.md")
        put(legacy / "设定" / "世界观.md")
        put(legacy / "文风.md")
        before = {path: path.read_bytes() for path in legacy.rglob("*") if path.is_file()}
        legacy_result = run_inspect(legacy)
        after = {path: path.read_bytes() for path in legacy.rglob("*") if path.is_file()}
        require(legacy_result["classification"] == "legacy_complete", "complete legacy assets must remain directly usable")
        require(legacy_result["expected_chapters_source"] == "拆文报告.md", "legacy report totals should prove coverage without an index")
        require(legacy_result["recommended_path"] == "direct_use", "legacy completion must not imply automatic enhancement")
        require(legacy_result["legacy_capabilities"]["import_facts"], "legacy summaries must remain available to import")
        require(not legacy_result["current_capabilities"]["emotion_module_recall"], "missing new analysis must be reported honestly")
        require(before == after, "asset inspection must be read-only")
        legacy_plan_result = run_plan(legacy)
        require(legacy_plan_result.returncode == 0, legacy_plan_result.stdout or legacy_plan_result.stderr)
        legacy_plan = json.loads(legacy_plan_result.stdout)
        require(legacy_plan["mode"] == "direct_use", "complete legacy output must work without a mechanical index")
        require(
            legacy_plan["routing"]["raw_original_read"]["count"] == 0,
            "complete legacy output must not require the original novel",
        )
        put(legacy / "chapter_index.csv", "chapter,char_count\n1,broken\n")
        legacy_with_bad_index = run_plan(legacy)
        require(
            legacy_with_bad_index.returncode == 0 and json.loads(legacy_with_bad_index.stdout)["mode"] == "direct_use",
            "an unused stale index must not block a complete legacy result",
        )

        partial = fixture_root / "partial"
        put(partial / "章节" / "第1章_摘要.md")
        put(partial / "章节" / "第2章_摘要.md")
        put(partial / "拆文报告.md")
        put(partial / "剧情" / "故事线.md")
        partial_result = run_inspect(partial, 4)
        require(partial_result["classification"] == "partial_or_mixed", "partial legacy work must not be marked complete")
        require(partial_result["recommended_path"] == "continue_partial", "partial work must continue from missing ranges")
        require(partial_result["completed_summary_chapters"] == [1, 2], "completed legacy chapters must be preserved")
        require(partial_result["missing_summary_chapters"] == [3, 4], "only missing chapters should be scheduled")

        paused = fixture_root / "paused-current"
        put(
            paused / "_progress.md",
            "- 总章数：2\n- 最终状态：paused_after_stage1\n- schema_version: 2\n"
            f"- source_sha256: {'b' * 64}\n",
        )
        paused_result = run_inspect(paused)
        require(
            paused_result["final_state"] == "paused_after_stage1",
            "progress states containing digits must not be truncated",
        )
        require(paused_result["source_hash"] == "b" * 64, "canonical progress source_sha256 must be reusable")

        mixed = fixture_root / "mixed"
        for chapter in range(1, 3):
            put(mixed / "章节" / f"第{chapter}章_摘要.md")
        put(mixed / "拆文报告.md")
        put(mixed / "剧情" / "故事线.md")
        put(mixed / "剧情" / "情绪模块.md")
        put(mixed / "_analysis_cache" / "批次-1-2.md")
        mixed_result = run_inspect(mixed, 2)
        require(mixed_result["mixed_sources"], "new and legacy assets must be reported as mixed when provenance is not current")
        require(mixed_result["provenance_requires_review"], "mixed sources require explicit provenance review")
        require(mixed_result["current_capabilities"]["emotion_module_recall"], "available new capability must be retained")
        require(not mixed_result["current_capabilities"]["rhythm_reference_recall"], "missing companion analysis must stay visible")

        current_broken = fixture_root / "current-broken"
        put(current_broken / "_progress.md", "- 总章数：2\n- 最终状态：completed\n- schema_version: 2\n")
        for chapter in range(1, 3):
            put(current_broken / "章节" / f"第{chapter}章_摘要.md")
        put(current_broken / "拆文报告.md")
        put(current_broken / "剧情" / "故事线.md")
        put(current_broken / "剧情" / "情绪模块.md")
        broken_result = run_inspect(current_broken)
        require(broken_result["classification"] == "current_incomplete", "damaged current output must not be misclassified as legacy")
        require(broken_result["recommended_path"] == "enhance_existing", "current semantic gaps should trigger targeted enhancement")
        require(broken_result["conflicts"], "false completed state must be reported as a conflict")

        current = fixture_root / "current-complete"
        put(current / "_progress.md", "- 总章数：2\n- 最终状态：completed\n- schema_version: 2\n")
        for chapter in range(1, 3):
            put(current / "章节" / f"第{chapter}章_摘要.md")
        put(current / "拆文报告.md")
        put(current / "剧情" / "故事线.md")
        put(current / "剧情" / "情绪模块.md")
        put(current / "剧情" / "节奏.md")
        current_result = run_inspect(current)
        require(current_result["classification"] == "current_complete", "verified current output must remain directly usable")
        require(current_result["recommended_path"] == "direct_use", "complete current output must not be reprocessed")

        current_with_golden = fixture_root / "current-complete-with-golden"
        put(current_with_golden / "_progress.md", "- 总章数：4\n- 最终状态：completed\n- schema_version: 2\n")
        for chapter in range(1, 4):
            put(current_with_golden / "章节" / f"第{chapter}章_深度拆解.md")
        put(current_with_golden / "章节" / "第4章_摘要.md")
        put(current_with_golden / "拆文报告.md")
        put(current_with_golden / "剧情" / "故事线.md")
        put(current_with_golden / "剧情" / "情绪模块.md")
        put(current_with_golden / "剧情" / "节奏.md")
        golden_result = run_inspect(current_with_golden)
        require(
            golden_result["classification"] == "current_complete",
            "the normal three golden analyses plus later summaries must satisfy the current contract",
        )
        require(not golden_result["mixed_sources"], "golden analyses and summaries are one standard provenance family")


def test_execution_routes_and_compact_chapter_cards() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-plan-") as temporary:
        fixture_root = Path(temporary)

        complete = fixture_root / "compact-complete"
        write_index(complete, [3000] * 8)
        put(
            complete / "v2" / "_progress.md",
            "# 进度\n- schema_version: v2\n- 当前状态：completed\n- 输入覆盖：全文8章\n",
        )
        put(
            complete / "_progress.md",
            "# 旧流程进度\n- schema_version: 2\n- 总章数：8\n- 最终状态：paused_after_stage1\n",
        )
        put(complete / "v2" / "全局建模.md")
        put(
            complete / "v2" / "章节卡" / "批次01.md",
            "| 章 | 一句话因果 | 人物目标/障碍/结果 |\n|---:|---|---|\n"
            + "\n".join(f"| {chapter} | 事实{chapter} | 目标{chapter} |" for chapter in range(1, 9)),
        )
        put(complete / "章节" / "第1章_摘要.md", "标准格式优先")

        inspected = run_inspect(complete)
        require(inspected["classification"] == "legacy_complete", "a verified compact result must be directly reusable")
        require(inspected["completed_semantic_chapters"] == list(range(1, 9)), "chapter cards must prove semantic coverage")
        require(
            inspected["chapter_sources"]["selection_strategy"] == "complete_compact_family",
            "a complete compact family must stay internally consistent when upstream coverage is partial",
        )
        require(
            inspected["chapter_sources"]["preferred_by_chapter"]["2"] == "compact_chapter_card",
            "the complete compact family must supply every enhancement chapter",
        )

        direct = run_plan(complete)
        require(direct.returncode == 0, direct.stdout or direct.stderr)
        direct_plan = json.loads(direct.stdout)
        require(direct_plan["mode"] == "direct_use", "complete local results must stop without reanalysis")
        require(not direct_plan["pause_after_stage1"], "direct use must not inherit a stale preview pause")
        require(direct_plan["routing"]["raw_original_read"]["count"] == 0, "direct use must read no original prose")
        require(direct_plan["existing_result_batches"] == [], "direct use must not auto-enhance old results")

        compact_without_index = fixture_root / "compact-complete-without-index"
        put(
            compact_without_index / "_progress.md",
            "# 旧流程停点\n- schema_version: 2\n- 总章数：3\n- 最终状态：paused_after_stage1\n",
        )
        put(
            compact_without_index / "v2" / "_progress.md",
            "# 完整成果\n- schema_version: v2\n- 当前状态：completed\n- 输入覆盖：全文8章\n",
        )
        put(compact_without_index / "v2" / "全局建模.md")
        put(
            compact_without_index / "v2" / "章节卡" / "全书.md",
            "| 章 | 一句话因果 |\n|---:|---|\n"
            + "\n".join(f"| {chapter} | 事实{chapter} |" for chapter in range(1, 9)),
        )
        no_index_inspected = run_inspect(compact_without_index)
        require(
            no_index_inspected["expected_chapters"] == 8,
            "a completed compact result must outrank a stale preview total",
        )
        no_index_plan_result = run_plan(compact_without_index)
        require(no_index_plan_result.returncode == 0, no_index_plan_result.stdout or no_index_plan_result.stderr)
        require(
            json.loads(no_index_plan_result.stdout)["mode"] == "direct_use",
            "a complete compact result must work without rebuilding an index",
        )

        enhanced = run_plan(complete, "--intent", "enhance", "--full-run")
        require(enhanced.returncode == 0, enhanced.stdout or enhanced.stderr)
        enhanced_plan = json.loads(enhanced.stdout)
        require(enhanced_plan["mode"] == "enhance_complete", "explicit enhancement must use existing results")
        require(enhanced_plan["routing"]["raw_original_read"]["count"] == 0, "enhancement must not reread covered prose")
        require(
            enhanced_plan["routing"]["existing_results"]["count"] == 8,
            "all existing chapters must enter secondary extraction",
        )
        require(
            all(batch["input_kind"] == "existing-results" for batch in enhanced_plan["existing_result_batches"]),
            "reuse batches must use the extractor and commit CLI input-kind spelling",
        )
        require(
            enhanced_plan["execution_order"][0] == "reuse_complete_results_without_mechanical_index",
            "complete-result enhancement must not build an index",
        )

        repeated = run_plan(complete, "--intent", "reanalyze", "--full-run")
        require(repeated.returncode == 0, repeated.stdout or repeated.stderr)
        repeated_plan = json.loads(repeated.stdout)
        require(repeated_plan["mode"] == "reanalyze_all", "explicit reanalysis must select the new-book route")
        require(repeated_plan["routing"]["existing_results"]["count"] == 0, "explicit reanalysis must ignore old results")
        require(repeated_plan["routing"]["golden_three_original_read"]["ranges"] == ["1-3"], "golden three must run once")
        require(repeated_plan["routing"]["raw_original_read"]["ranges"] == ["4-8"], "later chapters must use blocks")

        partial = fixture_root / "partial"
        write_index(partial, [3000] * 15)
        put(partial / "章节" / "第1章_摘要.md")
        put(partial / "章节" / "第2章_摘要.md")
        put(partial / "章节" / "第3章_深度拆解.md")
        put(
            partial / "章节卡" / "已有卡.md",
            "| 章 | 一句话因果 |\n|---:|---|\n| 4 | 四 |\n| 5 | 五 |\n",
        )
        partial_result = run_plan(partial, "--full-run")
        require(partial_result.returncode == 0, partial_result.stdout or partial_result.stderr)
        partial_plan = json.loads(partial_result.stdout)
        require(partial_plan["mode"] == "resume_partial", "partial work must use the mixed resume route")
        require(partial_plan["routing"]["existing_results"]["ranges"] == ["1-5"], "existing coverage must be retained")
        require(
            [batch["source_kind"] for batch in partial_plan["existing_result_batches"]]
            == ["upstream_summary", "golden_analysis", "compact_chapter_card"],
            "partial source families must use upstream artifacts first and cards only for gaps",
        )
        require(partial_plan["routing"]["raw_original_read"]["ranges"] == ["6-15"], "only missing chapters may read original prose")
        require(
            not set(range(1, 6)) & {
                chapter
                for block in partial_plan["routing"]["raw_original_read"]["blocks"]
                for chapter in range(block["start"], block["end"] + 1)
            },
            "existing chapters must never leak into raw blocks",
        )

        paused = fixture_root / "paused-after-golden"
        write_index(paused, [3_000] * 6)
        put(
            paused / "_progress.md",
            "# 进度\n- schema_version: 2\n- 总章数：6\n- 最终状态：paused_after_stage1\n",
        )
        for chapter in range(1, 4):
            put(paused / "章节" / f"第{chapter}章_深度拆解.md", f"第{chapter}章黄金三章成果")
        paused_result = run_plan(paused)
        require(paused_result.returncode == 0, paused_result.stdout or paused_result.stderr)
        paused_plan = json.loads(paused_result.stdout)
        require(paused_plan["mode"] == "resume_partial", "a golden-three checkpoint must resume as partial work")
        require(paused_plan["pause_after_stage1"], "a saved golden-three checkpoint must retain the confirmation gate")
        require(
            paused_plan["routing"]["golden_three_original_read"]["count"] == 0,
            "saved golden-three chapters must not reread original prose",
        )
        require(
            paused_plan["routing"]["raw_original_read"]["ranges"] == ["4-6"],
            "only post-preview chapters may enter raw blocks",
        )
        paused_full_result = run_plan(paused, "--full-run")
        require(paused_full_result.returncode == 0, paused_full_result.stdout or paused_full_result.stderr)
        require(
            not json.loads(paused_full_result.stdout)["pause_after_stage1"],
            "an explicit full run must pass the saved confirmation gate",
        )

        fresh = fixture_root / "fresh"
        write_index(fresh, [12_000] * 5 + [2_000] * 10)
        preview = run_plan(fresh)
        require(preview.returncode == 0, preview.stdout or preview.stderr)
        preview_plan = json.loads(preview.stdout)
        require(preview_plan["mode"] == "new_analysis", "an empty directory with an index is a new book")
        require(preview_plan["pause_after_stage1"], "new books must pause after the golden three by default")
        require(preview_plan["routing"]["golden_three_original_read"]["ranges"] == ["1-3"], "golden chapters must be isolated")
        blocks = preview_plan["routing"]["raw_original_read"]["blocks"]
        require(all(block["chapters"] <= 10 for block in blocks), "raw blocks must never exceed ten chapters")
        require(all(block["input_kind"] == "raw-original" for block in blocks), "raw blocks must use the public input kind")
        require(all(block["char_count"] <= 25_000 for block in blocks), "multi-chapter raw blocks must respect the character cap")
        raw_sequence = [chapter for block in blocks for chapter in range(block["start"], block["end"] + 1)]
        require(raw_sequence == list(range(4, 16)), "raw blocks must be continuous, complete, and non-overlapping")

        oversized = fixture_root / "oversized-single-chapter"
        write_index(oversized, [3_000] * 3 + [45_000, 2_000])
        oversized_result = run_plan(oversized, "--full-run")
        require(oversized_result.returncode == 0, oversized_result.stdout or oversized_result.stderr)
        oversized_blocks = json.loads(oversized_result.stdout)["routing"]["raw_original_read"]["blocks"]
        require(oversized_blocks[0]["start"] == 4 and oversized_blocks[0]["end"] == 4, "an oversized chapter must stand alone")
        require(oversized_blocks[0]["oversized_single_chapter"], "an oversized chapter must be explicit in the plan")


def test_batch_commit_and_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-commit-") as temporary:
        fixture_root = Path(temporary)
        result_root = fixture_root / "拆文库" / "测试书"
        source = fixture_root / "B001.md"
        source.write_text(valid_batch(), encoding="utf-8")
        put(result_root / "_progress.md", "# 旧进度\n- schema_version: 1\n- 自定义状态: 保留\n")

        first = run_commit(source, result_root)
        require(first.returncode == 0, first.stdout or first.stderr)
        first_payload = json.loads(first.stdout)
        chapter_one = result_root / "章节" / "第1章_摘要.md"
        chapter_two = result_root / "章节" / "第2章_摘要.md"
        cache = result_root / "_analysis_cache" / "批次-1-2.md"
        receipt = result_root / "_analysis_cache" / "receipts" / "B001.json"
        progress = result_root / "_progress.md"
        targets = (chapter_one, chapter_two, cache, receipt, progress)
        require(all(path.is_file() for path in targets), "a committed batch must contain outputs, receipt, and progress")
        require("schema_version: 2" in progress.read_text(encoding="utf-8"), "continuing a batch must record current schema")
        require("自定义状态: 保留" in progress.read_text(encoding="utf-8"), "progress extension must preserve existing state")
        require("story-long-analyze:batch:B001:start" in progress.read_text(encoding="utf-8"), "progress receipt marker missing")

        before = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in targets}
        second = run_commit(source, result_root)
        require(second.returncode == 0 and json.loads(second.stdout)["reused"], "identical batches must be reused")
        after = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in targets}
        require(before == after, "identical batch reuse must not rewrite files")

        chapter_one_before = (chapter_one.stat().st_mtime_ns, chapter_one.read_bytes())
        chapter_two.unlink()
        recovered = run_commit(source, result_root)
        recovered_payload = json.loads(recovered.stdout)
        require(recovered.returncode == 0 and not recovered_payload["reused"], "missing output must be restored")
        require(chapter_two.is_file(), "interrupted batch recovery must restore the missing chapter")
        require(
            chapter_one_before == (chapter_one.stat().st_mtime_ns, chapter_one.read_bytes()),
            "recovery must preserve valid completed chapter files",
        )

        stable = {path: path.read_bytes() for path in targets}
        source.write_text(valid_batch().replace("乙是否被追查", "乙何时被追查"), encoding="utf-8")
        conflict = run_commit(source, result_root)
        require(conflict.returncode == 2, "different existing output must require explicit replacement")
        require(json.loads(conflict.stdout)["error"] == "existing_output_conflict", "conflict error must be specific")
        require(stable == {path: path.read_bytes() for path in targets}, "a conflict must not modify any committed files")

        malformed_root = fixture_root / "拆文库" / "畸形输出"
        malformed = fixture_root / "malformed.md"
        malformed.write_text(valid_batch().replace("<!-- CHAPTER_END:2 -->", ""), encoding="utf-8")
        rejected = run_commit(malformed, malformed_root)
        require(rejected.returncode == 2, "malformed extractor output must be rejected")
        require(not (malformed_root / "章节").exists(), "validation failure must happen before any output write")
        require(not (malformed_root / "_progress.md").exists(), "validation failure must not create progress")

        reused_root = fixture_root / "拆文库" / "旧成果二次提取"
        old_one = reused_root / "章节" / "第1章_摘要.md"
        old_two = reused_root / "章节" / "第2章_摘要.md"
        put(old_one, "用户旧成果一")
        put(old_two, "用户旧成果二")
        old_bytes = {old_one: old_one.read_bytes(), old_two: old_two.read_bytes()}
        reused_input = fixture_root / "reuse-B001.md"
        reused_input.write_text(valid_existing_result_batch(), encoding="utf-8")
        reused_commit = subprocess.run(
            [
                sys.executable,
                str(COMMIT_SCRIPT),
                "--input",
                str(reused_input),
                "--root",
                str(reused_root),
                "--batch-id",
                "REUSE001",
                "--start",
                "1",
                "--end",
                "2",
                "--input-kind",
                "existing-results",
            ],
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            check=False,
        )
        require(reused_commit.returncode == 0, reused_commit.stdout or reused_commit.stderr)
        reused_payload = json.loads(reused_commit.stdout)
        require(reused_payload["input_kind"] == "existing-results", "receipt route must record secondary extraction")
        require(
            old_bytes == {old_one: old_one.read_bytes(), old_two: old_two.read_bytes()},
            "secondary extraction must not overwrite any old chapter result",
        )
        require(
            (reused_root / "_analysis_cache" / "复用提取-1-2.md").is_file(),
            "secondary extraction must use a separate cache namespace",
        )


def test_compact_projection_and_retry_checkpoints() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-compact-") as temporary:
        fixture_root = Path(temporary)
        compact_root = fixture_root / "拆文库" / "紧凑输出"
        source = fixture_root / "compact.md"
        source.write_text(compact_batch(), encoding="utf-8")
        committed = run_commit(source, compact_root)
        require(committed.returncode == 0, committed.stdout or committed.stderr)
        chapter = (compact_root / "章节" / "第1章_摘要.md").read_text(encoding="utf-8")
        require("**关键事件**" in chapter and "**情节点**" in chapter and "基调：紧张" in chapter, "mechanical projection must retain current consumer labels")
        require("**章节卡**" not in chapter, "compact projection must not restore the verbose chapter-card table")
        cache_text = (compact_root / "_analysis_cache" / "批次-1-2.md").read_text(encoding="utf-8")
        require("## 逐章紧凑事实" in cache_text and "### 第1章" in cache_text and "## 跨章观察" in cache_text, "one batch cache must carry both compact chapter facts and cross-chapter observations")
        receipt = json.loads((compact_root / "_analysis_cache" / "receipts" / "B001.json").read_text(encoding="utf-8"))
        require(receipt["projection_schema"] == "compact-v1", "receipt must identify compact model output")
        ledger = json.loads((compact_root / "_analysis_cache" / "batch-checkpoints.json").read_text(encoding="utf-8"))
        require(ledger["batches"]["B001"]["status"] == "success", "successful commit must close the batch checkpoint")

        retry_root = fixture_root / "拆文库" / "失败拆块"
        write_index(retry_root, [1_000] * 12)
        plan_path = retry_root / "_analysis_cache" / "run-plan.json"
        planned = run_plan(retry_root, "--full-run", "--output", str(plan_path))
        require(planned.returncode == 0, planned.stdout or planned.stderr)
        first_block = json.loads(planned.stdout)["routing"]["raw_original_read"]["blocks"][0]
        base = [sys.executable, str(CHECKPOINT_SCRIPT), "--root", str(retry_root), "--batch-id", first_block["id"], "--source-sha256", "a" * 64]
        started = subprocess.run(base[:2] + ["start"] + base[2:] + ["--start", str(first_block["start"]), "--end", str(first_block["end"]), "--input-kind", "raw-original"], text=True, encoding="utf-8", capture_output=True, check=False)
        require(started.returncode == 0, started.stdout or started.stderr)
        failed = subprocess.run(base[:2] + ["fail"] + base[2:] + ["--reason", "truncated", "--split", "--plan", str(plan_path)], text=True, encoding="utf-8", capture_output=True, check=False)
        require(failed.returncode == 0, failed.stdout or failed.stderr)
        failed_payload = json.loads(failed.stdout)
        require(len(failed_payload["children"]) == 2 and failed_payload["status"] == "superseded", "failed raw block must split into two resumable children")
        split_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        split_blocks = split_plan["routing"]["raw_original_read"]["blocks"]
        require(all(block["id"] != first_block["id"] for block in split_blocks), "superseded parent must leave the active plan")
        regenerated = run_plan(retry_root, "--full-run")
        regenerated_blocks = json.loads(regenerated.stdout)["routing"]["raw_original_read"]["blocks"]
        boundary = split_blocks[0]["end"]
        require(any(block["end"] == boundary for block in regenerated_blocks), "regenerated plans must retain a learned retry boundary")


def test_stage_receipt_verification() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-stage-") as temporary:
        root = Path(temporary)
        dependency = root / "_analysis_cache" / "批次-1-2.md"
        output = root / "剧情" / "节奏.md"
        put(dependency, "batch facts")
        put(output, "aggregate result")
        command = [sys.executable, str(STAGE_SCRIPT), "commit", "--root", str(root), "--stage", "aggregate", "--dependency", str(dependency), "--output", str(output)]
        committed = subprocess.run(command, text=True, encoding="utf-8", capture_output=True, check=False)
        require(committed.returncode == 0, committed.stdout or committed.stderr)
        verify = subprocess.run([sys.executable, str(STAGE_SCRIPT), "verify", "--root", str(root), "--stage", "aggregate"], text=True, encoding="utf-8", capture_output=True, check=False)
        require(verify.returncode == 0 and json.loads(verify.stdout)["reused"], "unchanged stage outputs must resume without recomputation")
        dependency.write_text("changed batch facts", encoding="utf-8")
        stale = subprocess.run([sys.executable, str(STAGE_SCRIPT), "verify", "--root", str(root), "--stage", "aggregate"], text=True, encoding="utf-8", capture_output=True, check=False)
        require(stale.returncode == 0 and not json.loads(stale.stdout)["reused"], "changed dependencies must invalidate only their stage receipt")


def test_replanned_run_reuses_verified_batch_cache() -> None:
    with tempfile.TemporaryDirectory(prefix="long-analyze-replan-") as temporary:
        root = Path(temporary)
        write_index(root, [1_000] * 6)
        put(root / "_progress.md", "# 进度\n- schema_version: 2\n- 总章数：6\n- 最终状态：pending\n")
        outputs = {
            "章节/第4章_摘要.md": "## 第4章\n\n**概要**：已完成第四章。\n",
            "章节/第5章_摘要.md": "## 第5章\n\n**概要**：已完成第五章。\n",
            "_analysis_cache/批次-4-5.md": "# 批次\n\n## 逐章紧凑事实\n\n## 跨章观察\n",
        }
        hashes = {}
        for relative, body in outputs.items():
            target = root / relative
            put(target, body)
            hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        receipt = {
            "schema_version": 2,
            "batch_id": "RAW-001",
            "chapter_range": [4, 5],
            "input_kind": "raw-original",
            "source_sha256": "a" * 64,
            "outputs": hashes,
            "status": "success",
        }
        put(root / "_analysis_cache" / "receipts" / "RAW-001.json", json.dumps(receipt, ensure_ascii=False))

        replanned = run_plan(root, "--full-run")
        require(replanned.returncode == 0, replanned.stdout or replanned.stderr)
        plan = json.loads(replanned.stdout)
        require(plan["verified_batch_caches"][0]["start"] == 4, "verified committed batches must be exposed as reusable cache input")
        require(not plan["existing_result_batches"], "verified current batches must not be sent through old-result semantic extraction")
        require(plan["routing"]["raw_original_read"]["ranges"] == ["6"], "only the genuinely missing raw chapter may be scheduled")

        (root / "_analysis_cache" / "批次-4-5.md").write_text("corrupt", encoding="utf-8")
        stale = run_plan(root, "--full-run")
        stale_plan = json.loads(stale.stdout)
        require(not stale_plan["verified_batch_caches"], "a cache with a mismatched hash must not be trusted")
        require(stale_plan["existing_result_batches"], "stale cache chapters must fall back to compatible existing-result extraction")


def main() -> int:
    test_boundaries_reuse_and_source_change()
    test_toc_short_chapters_and_volumes()
    test_existing_asset_compatibility_paths()
    test_execution_routes_and_compact_chapter_cards()
    test_batch_commit_and_recovery()
    test_compact_projection_and_retry_checkpoints()
    test_stage_receipt_verification()
    test_replanned_run_reuses_verified_batch_cache()
    print("OK: long-analyze runtime, compatibility, and recovery regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
