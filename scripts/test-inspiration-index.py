#!/usr/bin/env python3
"""Regression tests for the three-layer inspiration index (EM-card based)."""

from __future__ import annotations

import csv
import io
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = runpy.run_path(
    str(ROOT / "skills" / "story-long-analyze" / "scripts" / "inspiration_index.py"),
    run_name="test",
)

EM_MODULE_TEXT = """# 情绪模块：测试书

## 读者需求 / 情绪引擎

| 读者需求 | 本书满足方式 | 证据章节/情节点 | 持续追读机制 | 可迁移边界 |
|---|---|---|---|---|
| 认知反转 | 先低估后翻面 | 第 6-7 章 | 悬置异变时点 | 可保留功能跃迁 |

## 其他机制索引

EM-004｜低成本善行回报｜关系铺垫｜第 16-19 章｜TR-004

## 最强三个可复现模块卡

### EM-001 压低预期后兑现

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 被轻视者用结果反证。 |
| 情绪链 | 缺口 → 加压 → 触发 → 爆发 → 余波 |
| 戏剧单元 | 被轻视者在公开场合用结果反证。 |
| 关键触发物 | 误判者/见证者/证据 |
| 可替换项 | 角色身份、场景、道具 |
| 不可照搬 | 甲某人的专属台词与场景顺序 |

### EM-002 低估物件延迟翻面

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 已埋物件何时异变。 |
| 情绪链 | 低估 → 搁置 → 异变 → 揭示 |
| 戏剧单元 | 日常物件在危机中集中揭示身份与功能。 |
| 关键触发物 | 物件/危机/见证者 |
| 可替换项 | 物件形态、触发方式 |
| 不可照搬 | 原书戒指外形与认主方式 |
"""

INCOMPLETE_CARD = """# 情绪模块：残卡书

## 最强三个可复现模块卡

### EM-001 半张卡

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 有需求。 |
| 情绪链 | 有链。 |
"""

LEAKY_CARD = """# 情绪模块：泄漏书

## 最强三个可复现模块卡

### EM-001 张三妙计安天下

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 张三用妙计翻盘。 |
| 情绪链 | 缺口 → 爆发 |
| 戏剧单元 | 张三在公开场合反证。 |
| 可替换项 | 场景 |
| 不可照搬 | 张三的台词 |
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_workspace(base: Path, book: str = "测试书", module_text: str = EM_MODULE_TEXT) -> Path:
    write(base / "拆文库" / book / "剧情" / "情绪模块.md", module_text)
    return base / "灵感库"


def index_rows(root: Path) -> list[dict[str, str]]:
    with (root / "灵感索引.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def append_row(root: Path, row: dict[str, str]) -> None:
    rows = index_rows(root)
    rows.append(row)
    text = MODULE["csv_text"](rows)
    (root / "灵感索引.csv").write_text(text, encoding="utf-8", newline="")


def base_row(**overrides: str) -> dict[str, str]:
    row = {column: "" for column in MODULE["COLUMNS"]}
    row.update({"novel_count": "1", "atom_count": "1", "status": "active"})
    row.update(overrides)
    return row


CBA_TAGS = "题材=玄幻；读者需求=认知反转；情绪=期待；剧情功能=信息揭示；适用阶段=正文；风险=泄底过早"


def test_register_and_idempotence() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        payload = MODULE["register_atoms"](root, module_path, "测试书")
        require(payload["atoms_full"] == 2 and payload["atoms_index"] == 1, f"应登记 2 完整卡＋1 索引条目：{payload}")
        rows = index_rows(root)
        require([row["item_id"] for row in rows] == ["IA-001", "IA-002", "IA-004"], "IA 编号必须镜像 EM 编号")
        require(all(row["path"] == "" for row in rows), "IA 不得生成卡片文件路径")
        require({row["grade"] for row in rows} == {"full", "index"}, "grade 必须区分完整卡与索引条目")
        require(not any((root / "原子灵感").rglob("*.md")) if (root / "原子灵感").is_dir() else True, "不得落任何 IA 文件")
        first = (root / "灵感索引.csv").read_bytes()
        MODULE["register_atoms"](root, module_path, "测试书")
        require((root / "灵感索引.csv").read_bytes() == first, "重复登记必须逐字节幂等")
        require(not MODULE["validate"](root), "干净登记必须通过校验")


def test_register_rejects_incomplete_and_leaky_cards() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base, book="残卡书", module_text=INCOMPLETE_CARD)
        module_path = base / "拆文库" / "残卡书" / "剧情" / "情绪模块.md"
        try:
            MODULE["register_atoms"](root, module_path, "残卡书")
            raise AssertionError("字段不全的 EM 卡必须报错")
        except ValueError as exc:
            require("em_fields_missing" in str(exc) and "Stage 3" in str(exc), f"报错须指回拆文侧修复：{exc}")
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base, book="泄漏书", module_text=LEAKY_CARD)
        write(base / "拆文库" / "泄漏书" / "角色" / "张三.md", "# 张三\n")
        module_path = base / "拆文库" / "泄漏书" / "剧情" / "情绪模块.md"
        try:
            MODULE["register_atoms"](root, module_path, "泄漏书")
            raise AssertionError("机制字段带角色名必须报错")
        except ValueError as exc:
            require("source_specific_name_in_mechanism" in str(exc) and "张三" in str(exc), f"须点名泄漏专名：{exc}")


def test_validate_cba_closure_and_markers() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        MODULE["register_atoms"](root, module_path, "测试书")
        write(root / "跨书灵感聚合" / "CBA-001_压低预期后兑现.md",
              "# CBA-001：压低预期后兑现\n\n- 验证状态：单书假设\n- 来源：测试书/EM-001\n\n## 共同机制链\n缺口 → 爆发。\n")
        append_row(root, base_row(item_id="CBA-001", layer="跨书灵感聚合", title="压低预期后兑现",
                                  source_book="测试书", path="跨书灵感聚合/CBA-001_压低预期后兑现.md",
                                  source_ids="测试书/EM-001", tags=CBA_TAGS))
        require(not MODULE["validate"](root), "单书 CBA＋标记齐全必须通过：" + ";".join(MODULE["validate"](root)))

        matches = MODULE["query"](root, ["题材=玄幻", "情绪=期待"], 6)
        require([match["item_id"] for match in matches] == ["CBA-001"], "带核心轴命中必须返回该 CBA")
        require(not MODULE["query"](root, ["风险=泄底过早"], 6), "只命中非核心轴不得返回")

        resolved = MODULE["resolve"](root, ["测试书/EM-002", "CBA-001"])
        require(resolved["ok"] and resolved["resolved"][0]["location"].endswith("情绪模块.md#EM-002"),
                f"EM 引用必须解析回情绪模块锚点:{resolved}")


def test_validate_rejects_path_reference_in_card() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        MODULE["register_atoms"](root, module_path, "测试书")
        write(root / "跨书灵感聚合" / "CBA-001_带路径.md",
              "# CBA-001：带路径\n\n- 验证状态：单书假设\n- 来源：[IA-001](../原子灵感/测试书/IA-001.md)\n")
        append_row(root, base_row(item_id="CBA-001", layer="跨书灵感聚合", title="带路径",
                                  source_book="测试书", path="跨书灵感聚合/CBA-001_带路径.md",
                                  source_ids="测试书/EM-001", tags=CBA_TAGS))
        errors = MODULE["validate"](root)
        require(any("path_reference_in_card" in error for error in errors), f"卡内路径引用必须被拒：{errors}")


def test_validate_set_mismatch_and_nm_rules() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        MODULE["register_atoms"](root, module_path, "测试书")
        module_text = module_path.read_text(encoding="utf-8")
        write(module_path, module_text + "\n### EM-005 新增机制\n\n| 字段 | 内容 |\n|---|---|\n| 读者想看什么 | 新需求。 |\n| 情绪链 | 链。 |\n| 戏剧单元 | 单元。 |\n| 可替换项 | 项。 |\n| 不可照搬 | 专名。 |\n")
        errors = MODULE["validate"](root)
        require(any("ia_em_set_mismatch" in error for error in errors), f"EM 增卡未重登记必须被发现：{errors}")
        MODULE["register_atoms"](root, module_path, "测试书")
        require(not MODULE["validate"](root), "重登记后必须恢复一致")

        write(root / "单小说灵感合并" / "测试书" / "NM-001.md",
              "# NM-001：预期压制系\n\n- 合并对象：EM-001、EM-002\n- 合并理由：同为先抑后扬的兑现结构；差异在触发物是人还是物件。\n")
        append_row(root, base_row(item_id="NM-001", layer="单小说灵感合并", title="预期压制系",
                                  source_book="测试书", path="单小说灵感合并/测试书/NM-001.md",
                                  source_ids="EM-001|EM-002", atom_count="2"))
        require(not MODULE["validate"](root), "合法 NM 必须通过：" + ";".join(MODULE["validate"](root)))
        write(root / "跨书灵感聚合" / "CBA-002_经由NM.md",
              "# CBA-002：经由 NM\n\n- 验证状态：单书假设\n- 来源：测试书/NM-001\n")
        append_row(root, base_row(item_id="CBA-002", layer="跨书灵感聚合", title="经由NM",
                                  source_book="测试书", path="跨书灵感聚合/CBA-002_经由NM.md",
                                  source_ids="测试书/NM-001", atom_count="2", tags=CBA_TAGS))
        require(not MODULE["validate"](root), "NM 展开闭包必须通过：" + ";".join(MODULE["validate"](root)))


def main() -> int:
    test_register_and_idempotence()
    test_register_rejects_incomplete_and_leaky_cards()
    test_validate_cba_closure_and_markers()
    test_validate_rejects_path_reference_in_card()
    test_validate_set_mismatch_and_nm_rules()
    print("OK: inspiration index regressions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
