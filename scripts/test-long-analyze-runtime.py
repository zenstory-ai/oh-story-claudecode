#!/usr/bin/env python3
"""Runtime regressions for the mechanical index and contract-v5 inspiration flow."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "skills/story-long-analyze/scripts/build_chapter_index.py"
INSPIRATION_SCRIPT = REPO_ROOT / "skills/story-inspiration-distill/scripts/inspiration_index.py"
CHAPTER_COLUMNS = ("chapter", "title", "source_locator", "char_count", "status")
BLOCK_COLUMNS = (
    "block_id", "chapter_range", "block_name", "initial_gap", "goal", "pressure",
    "turning_point", "payoff", "remaining_hook", "state_change", "main_characters",
    "evidence_locator", "plot_intensity", "emotion_type", "emotion_intensity",
    "description_density", "relationship_delta", "rhythm_anchors", "inspiration_title",
    "inspiration_mechanism", "inspiration_reader_effect", "inspiration_transfer_boundary",
    "inspiration_risk", "confidence", "status",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)],
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        check=False,
    )


def load_module(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mechanical_index_is_single_write_and_resumable() -> None:
    with tempfile.TemporaryDirectory(prefix="story-index-v4-") as temp:
        root = Path(temp)
        source = root / "小说.txt"
        output = root / "chapter_index.csv"
        progress = root / "_progress.json"
        snapshot = root / "_state_snapshot.json"
        source.write_text(
            "第一章\n开篇内容。\n\n第二章 有标题\n推进内容。\n\nChapter 3\n转折内容。\n\n第四章：收束\n收束内容。\n",
            encoding="utf-8",
        )
        base_args = (
            BUILD_SCRIPT,
            "--source",
            source,
            "--output",
            output,
            "--progress",
            progress,
            "--snapshot",
            snapshot,
            "--locator-path",
            "原文/小说.txt",
        )
        stage0_args = (
            BUILD_SCRIPT,
            "--mode",
            "boundaries",
            "--source",
            source,
            "--progress",
            progress,
            "--snapshot",
            snapshot,
            "--locator-path",
            "原文/小说.txt",
        )
        stage0 = run(*stage0_args)
        require(stage0.returncode == 0, "Stage 0 boundary build failed")
        require(not output.exists(), "Stage 0 must not create chapter_index.csv")
        paused = json.loads(progress.read_text(encoding="utf-8"))
        paused.update(
            {
                "current_stage": "paused_after_stage1",
                "last_committed_batch": "golden_chapters",
                "completed_ranges": paused["completed_ranges"] + ["1-3:golden_chapters"],
                "pending_ranges": ["stage_2_index"],
                "next_action": "stage_2_index",
            }
        )
        saved_snapshot = json.loads(snapshot.read_text(encoding="utf-8"))
        saved_snapshot["aliases"] = {"林雷": ["主角"]}
        snapshot.write_text(json.dumps(saved_snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        import hashlib
        paused["artifact_checksums"]["_state_snapshot.json"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        progress.write_text(json.dumps(paused, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        first = run(*base_args)
        require(first.returncode == 0, "first index build failed: {}".format(first.stderr or first.stdout))
        first_payload = json.loads(first.stdout)
        require(first_payload.get("reused") is False and first_payload.get("chapters") == 4, "bare chapter headings must be indexed")
        committed = json.loads(progress.read_text(encoding="utf-8"))
        require("1-3:golden_chapters" in committed["completed_ranges"], "Stage 2 must preserve the Stage 1 checkpoint")
        require(json.loads(snapshot.read_text(encoding="utf-8"))["aliases"] == {"林雷": ["主角"]}, "Stage 2 must not overwrite the Stage 0/1 snapshot")
        with output.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            header = tuple(reader.fieldnames or ())
        require(header == CHAPTER_COLUMNS, "chapter index must contain only five mechanical columns")
        require(len(rows) == 4, "all four fixture chapters must be indexed")
        before = (output.stat().st_mtime_ns, output.read_bytes())
        second = run(*base_args)
        require(second.returncode == 0, "same-source rerun must succeed")
        require(json.loads(second.stdout).get("reused") is True, "same hashes must reuse the index")
        after = (output.stat().st_mtime_ns, output.read_bytes())
        require(after == before, "reuse must not rewrite chapter_index.csv")

        tampered = output.read_text(encoding="utf-8-sig").replace("原文/小说.txt:L1-L3", "原文/小说.txt:L1-L2")
        output.write_text(tampered, encoding="utf-8-sig")
        corrupt = run(*base_args)
        require(corrupt.returncode == 2, "same-row-count index corruption must not be reused")
        require(json.loads(corrupt.stdout).get("error") == "existing_index_incompatible", "corrupt index needs explicit repair")
        repaired = run(*base_args, "--rebuild")
        require(repaired.returncode == 0, "explicit rebuild must repair a corrupt index")

        checksum_progress = json.loads(progress.read_text(encoding="utf-8"))
        checksum_progress["artifact_checksums"]["chapter_index.csv"] = "0" * 64
        progress.write_text(json.dumps(checksum_progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bad_checksum = run(*base_args)
        require(bad_checksum.returncode == 2, "registered checksum corruption must block reuse")
        require(json.loads(bad_checksum.stdout).get("error") == "artifact_checksum_mismatch", "checksum mismatch must be explicit")
        require(run(*base_args, "--rebuild").returncode == 0, "explicit rebuild must repair checksum registration")

        source.write_text(source.read_text(encoding="utf-8") + "补充一行。\n", encoding="utf-8")
        changed = run(*base_args)
        require(changed.returncode == 2, "changed source must refuse an implicit overwrite")
        require(json.loads(changed.stdout).get("error") in {"existing_index_incompatible", "existing_boundaries_incompatible"}, "source changes need an explicit rebuild")
        rebuilt = run(*base_args, "--rebuild")
        require(rebuilt.returncode == 0 and not json.loads(rebuilt.stdout).get("reused"), "explicit rebuild must refresh the index")
        require(json.loads(progress.read_text(encoding="utf-8"))["schema_version"] == 4, "progress must use schema v4")
        require(json.loads(progress.read_text(encoding="utf-8"))["contract_version"] == "5.0", "analysis contract must use v5.0")
        require(json.loads(snapshot.read_text(encoding="utf-8"))["schema_version"] == 4, "snapshot must use schema v4")

        invalid = root / "跳章.txt"
        invalid.write_text("第一章\n一。\n第三章\n三。\n第二卷第一章\n重置。\n", encoding="utf-8")
        rejected = run(
            BUILD_SCRIPT,
            "--source", invalid,
            "--output", root / "invalid.csv",
            "--progress", root / "invalid-progress.json",
            "--snapshot", root / "invalid-snapshot.json",
        )
        require(rejected.returncode == 2 and "chapter_number_gap" in json.loads(rejected.stdout).get("error", ""), "jumped chapter numbers must be rejected")

        volumes = root / "多卷.txt"
        volumes.write_text("第一卷 起点\n第一章\n一。\n第二章\n二。\n第二卷 新局\n第一章\n三。\n第二章\n四。\n", encoding="utf-8")
        volume_run = run(
            BUILD_SCRIPT,
            "--source", volumes,
            "--output", root / "volumes.csv",
            "--progress", root / "volumes-progress.json",
            "--snapshot", root / "volumes-snapshot.json",
        )
        require(volume_run.returncode == 0, "explicit volume boundaries may reset local chapter numbers")


def write_card(root: Path, relative: str, title: str, marker: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# {}\n{}\n".format(title, marker), encoding="utf-8")


def write_inspiration_index(root: Path, ia_tags: str = "", cba_tags: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if cba_tags is None:
        cba_tags = "题材=都市脑洞；读者需求=身份跃迁；情绪=期待；剧情功能=能力兑现；适用阶段=正文；风险=数值膨胀"
    rows = [
        ["IA-001", "原子灵感", "延迟兑现", "测试书", "原子灵感/测试书/IA-001.md", "SB-001", "1", "1", ia_tags, "active"],
        ["NM-001", "单小说灵感合并", "单书延迟兑现", "测试书", "单小说灵感合并/测试书.md", "IA-001", "1", "1", "", "active"],
        ["CBA-001", "跨书灵感聚合", "压低预期后兑现", "测试书", "跨书灵感聚合/CBA-001_压低预期后兑现.md", "NM-001|IA-001", "1", "1", cba_tags, "active"],
        ["CBA-002", "跨书灵感聚合", "停用机制", "测试书", "跨书灵感聚合/CBA-002_停用机制.md", "NM-001|IA-001", "1", "1", cba_tags, "inactive"],
    ]
    with (root / "灵感索引.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("item_id", "layer", "title", "source_book", "path", "source_ids", "novel_count", "atom_count", "tags", "status"))
        writer.writerows(rows)


def write_structure_blocks(workspace: Path) -> None:
    path = workspace / "拆文库/测试书/structure_blocks.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(BLOCK_COLUMNS)
        writer.writerow(
            (
                "SB-001", "1-3", "测试块", "缺口", "目标", "压力", "转折", "兑现", "新债",
                "状态变化", "主角甲", "原文/测试.txt:L1-L9", "4", "期待", "4", "2",
                "主角甲--保护-->伙伴乙：疏离→合作@第3章", "第2章:蓄力:P3/E3/D2|第3章:释放:P4/E4/D2",
                "延迟兑现建立信用", "先压低预期，再用有成本行动改写关系判断",
                "让读者从戒备转为期待与信任", "可迁移行动验真；必须替换身份、资源和兑现事件",
                "无成本补偿会让信用变化失真", "A 明确", "ok",
            )
        )


def test_atoms_are_rendered_without_a_second_semantic_pass() -> None:
    with tempfile.TemporaryDirectory(prefix="story-inspiration-render-v1-") as temp:
        workspace = Path(temp)
        root = workspace / "灵感库"
        blocks = workspace / "拆文库/测试书/structure_blocks.csv"
        write_structure_blocks(workspace)
        first = run(INSPIRATION_SCRIPT, "render-atoms", "--root", root, "--blocks", blocks, "--book", "测试书")
        require(first.returncode == 0, "mechanical IA render failed: {}".format(first.stderr or first.stdout))
        payload = json.loads(first.stdout)
        require(payload == {"ok": True, "book": "测试书", "atoms": 1, "index_writes": 1}, "render result must expose one index write")
        card = root / "原子灵感/测试书/IA-001.md"
        require(card.is_file(), "mechanical IA card must be created")
        text = card.read_text(encoding="utf-8")
        require("延迟兑现建立信用" in text and "主角甲" not in text, "IA body must use pre-abstracted fields without source names")
        before = (root / "灵感索引.csv").read_bytes()
        second = run(INSPIRATION_SCRIPT, "render-atoms", "--root", root, "--blocks", blocks, "--book", "测试书")
        require(second.returncode == 0, "same blocks must rerender deterministically")
        with (root / "灵感索引.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        require(len(rows) == 1 and rows[0]["item_id"] == "IA-001", "rerender must replace the book IA set without duplicates")
        require((root / "灵感索引.csv").read_bytes() == before, "deterministic rerender must keep index bytes stable")


def test_inspiration_index_only_exposes_tagged_active_cba() -> None:
    module = load_module(INSPIRATION_SCRIPT, "inspiration_index_contract")
    with tempfile.TemporaryDirectory(prefix="story-inspiration-v1-") as temp:
        workspace = Path(temp)
        root = workspace / "灵感库"
        write_structure_blocks(workspace)
        for relative, title in (
            ("原子灵感/测试书/IA-001.md", "IA"),
            ("单小说灵感合并/测试书.md", "NM"),
            ("跨书灵感聚合/CBA-001_压低预期后兑现.md", "CBA active"),
            ("跨书灵感聚合/CBA-002_停用机制.md", "CBA inactive"),
        ):
            marker = "- 验证状态：单书假设" if relative.startswith("跨书灵感聚合/") else ""
            write_card(root, relative, title, marker)
        write_inspiration_index(root)
        require(module.validate(root) == [], "valid three-layer inspiration index must pass")
        matches = module.query(root, ["题材=都市脑洞", "适用阶段=正文"], 8)
        require([item["item_id"] for item in matches] == ["CBA-001"], "query must expose only active CBA cards")
        require(module.query(root, ["题材=科幻"], 8) == [], "zero-overlap tags must not recall unrelated CBA cards")

        write_inspiration_index(root, ia_tags="题材=都市脑洞")
        require(any("tags_reserved_for_cba" in item for item in module.validate(root)), "IA/NM public tags must be rejected")
        write_inspiration_index(root, cba_tags="题材=都市脑洞；读者需求=身份跃迁")
        require(any("cba_tags_missing" in item for item in module.validate(root)), "missing required CBA axes must be rejected")

        write_inspiration_index(root)
        index_path = root / "灵感索引.csv"
        with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[1]["source_ids"] = "IA-999"
        with index_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        require(any("nm_source_ia_missing" in item for item in module.validate(root)), "NM links to missing IA must be rejected")

        write_inspiration_index(root)
        with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[2]["atom_count"] = "2"
        with index_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        require(any("cba_atom_count_mismatch" in item for item in module.validate(root)), "CBA atom_count must equal its source closure")

        write_inspiration_index(root)
        block_path = workspace / "拆文库/测试书/structure_blocks.csv"
        with block_path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerow(
                (
                    "SB-002", "4-6", "漏原子块", "缺口", "目标", "压力", "转折", "兑现", "新债",
                    "状态变化", "主角乙", "原文/测试.txt:L10-L18", "3", "期待", "3", "2",
                    "无明确变化", "第6章:释放:P3/E3/D2", "公开验真", "公开结果改写群体判断",
                    "带来爽感和确认", "可迁移公开验证；必须替换场域与证据", "旁观者降智会削弱兑现",
                    "B 强推断", "ok",
                )
            )
        require(any("ia_block_set_mismatch" in item for item in module.validate(root)), "every valid structure block must have exactly one IA")


def main() -> int:
    test_mechanical_index_is_single_write_and_resumable()
    test_atoms_are_rendered_without_a_second_semantic_pass()
    test_inspiration_index_only_exposes_tagged_active_cba()
    print("OK: long-analyze contract v5 runtime regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
