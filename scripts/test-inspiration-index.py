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


GENRE_VARIANT_MODULE = """# 情绪模块：体裁书

## 其他机制索引

EM-07｜延迟报偿｜关系铺垫｜第 12 章｜TR-002

## 可复现模块卡

### EM-01 · 短编号分隔符卡

| 维度 | 内容 |
|---|---|
| **读者想看什么** | 被低估者翻面。 |
| **情绪链** | 缺口 → 爆发 |
| **戏剧单元** | 公开场合用结果反证。 |
| **可替换项** | 场景、道具 |
| **不可照搬项** | 原书台词 |

### EM-02 — 粗体列表卡

- **读者想看什么**：延迟满足的兑现。
- **情绪链**：搁置 → 异变 → 揭示
- **戏剧单元**：日常物件在危机中揭示身份。
- **可替换项**：物件形态
- **不可照搬**：原书物件外形
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


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
    (root / "灵感索引.csv").write_bytes(text.encode("utf-8"))


def base_row(**overrides: str) -> dict[str, str]:
    row = {column: "" for column in MODULE["COLUMNS"]}
    row.update({"novel_count": "1", "atom_count": "1", "status": "active"})
    row.update(overrides)
    return row


CBA_TAGS = "题材=玄幻；读者需求=认知反转；情绪=期待；剧情功能=信息揭示；适用阶段=细纲；风险=泄底过早"


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


def test_parse_genre_variants() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base, book="体裁书", module_text=GENRE_VARIANT_MODULE)
        module_path = base / "拆文库" / "体裁书" / "剧情" / "情绪模块.md"
        payload = MODULE["register_atoms"](root, module_path, "体裁书")
        require(payload["atoms_full"] == 2 and payload["atoms_index"] == 1,
                f"短编号/分隔符/粗体表格/粗体列表/同义字段名都必须被识别：{payload}")
        rows = index_rows(root)
        require([row["item_id"] for row in rows] == ["IA-01", "IA-02", "IA-07"], f"IA 编号必须镜像短编号 EM：{rows}")
        require(not MODULE["validate"](root), "体裁变体登记后必须通过校验")


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


def test_workspace_gate_and_check_atoms() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        # 沙箱布局：root 上方没有 拆文库/ → 必须显式失败，不得静默空名单
        orphan_root = base / "孤立" / "灵感库"
        write(base / "孤立" / "情绪模块.md", EM_MODULE_TEXT)
        try:
            MODULE["register_atoms"](orphan_root, base / "孤立" / "情绪模块.md", "测试书")
            raise AssertionError("找不到工作区必须报错")
        except ValueError as exc:
            require("workspace_not_located" in str(exc), f"须报 workspace_not_located：{exc}")

        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        payload = MODULE["register_atoms"](root, module_path, "测试书")
        require(payload["character_roster"] == 0, f"名单规模必须报出：{payload}")
        require(any("character_roster_missing" in warning for warning in payload["warnings"]),
                f"无 角色/ 的书必须给 warning：{payload}")

        # 一次报全：缺字段与泄漏并存时两个错误码同时出现
        write(base / "拆文库" / "问题书" / "剧情" / "情绪模块.md",
              INCOMPLETE_CARD + "\n### EM-002 张三登场\n\n| 字段 | 内容 |\n|---|---|\n"
              "| 读者想看什么 | 张三翻盘。 |\n| 情绪链 | 链。 |\n| 戏剧单元 | 单元。 |\n"
              "| 可替换项 | 场景 |\n| 不可照搬 | 张三的台词 |\n")
        write(base / "拆文库" / "问题书" / "角色" / "张三.md", "# 张三\n")
        try:
            MODULE["register_atoms"](root, base / "拆文库" / "问题书" / "剧情" / "情绪模块.md", "问题书")
            raise AssertionError("问题卡必须报错")
        except ValueError as exc:
            require("em_fields_missing" in str(exc) and "source_specific_name_in_mechanism" in str(exc),
                    f"必须一次报出全部问题：{exc}")

        # check-atoms 只读：报告同样的问题且不动索引
        before = (root / "灵感索引.csv").read_bytes()
        report = MODULE["check_atoms"](root, base / "拆文库" / "问题书" / "剧情" / "情绪模块.md", "问题书")
        require(not report["ok"] and len(report["errors"]) == 2, f"check-atoms 须报全错误：{report}")
        require((root / "灵感索引.csv").read_bytes() == before, "check-atoms 不得写盘")
        clean = MODULE["check_atoms"](root, module_path, "测试书")
        require(clean["ok"] and clean["cards_full"] == 2 and clean["cards_index"] == 1,
                f"干净书 check-atoms 须给出卡数：{clean}")


MULTILINE_MODULE = """# 情绪模块：多行书

## 可复现模块卡

### EM-001 多行值卡

- **读者想看什么**：延迟兑现。
- **情绪链**：搁置 → 揭示
- **戏剧单元**：日常物件在危机中揭示身份。
- **可替换项**：
  - 物件可以换成任何“被低估的日常之物”
  - 危机场景可以换成任何“公开检验场合”
- **不可照搬**：原书物件外形
"""

TIERING_MODULE = """# 情绪模块：分级书

## 可复现模块卡

### EM-001 空值卡

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 有需求。 |
| 情绪链 | 有链。 |
| 戏剧单元 | 有单元。 |
| 可替换项 |  |
| 不可照搬 | 专名。 |

### EM-002 反模式卡

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 压制者被反杀。 |
| 情绪链 | 缺口 → 爆发 |
| 戏剧单元 | 公开场合反证。 |
| 可替换项 | 王二→任何欺压者 |
| 不可照搬 | 原书场景顺序 |

### EM-003 嫌疑卡

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 剑客式的以武证道。 |
| 情绪链 | 蓄势 → 出手 |
| 戏剧单元 | 沉默强者一击定局。 |
| 可替换项 | 场景、对手 |
| 不可照搬 | 原书招式名 |
"""


def test_multiline_values_and_leak_tiering() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base, book="多行书", module_text=MULTILINE_MODULE)
        module_path = base / "拆文库" / "多行书" / "剧情" / "情绪模块.md"
        payload = MODULE["register_atoms"](root, module_path, "多行书")
        require(payload["atoms_full"] == 1, f"多行字段值必须被吸收成有效值：{payload}")

    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base, book="分级书", module_text=TIERING_MODULE)
        for name in ("王二", "剑客"):
            write(base / "拆文库" / "分级书" / "角色" / f"{name}.md", f"# {name}\n")
        module_path = base / "拆文库" / "分级书" / "剧情" / "情绪模块.md"
        report = MODULE["check_atoms"](root, module_path, "分级书")
        require(not report["ok"], f"空值与反模式必须拦下：{report}")
        require(any("em_field_value_empty" in error and "可替换项" in error for error in report["errors"]),
                f"字段在而值空必须报 em_field_value_empty：{report['errors']}")
        require(not any("em_fields_missing" in error for error in report["errors"]),
                f"空值不得误报成缺字段：{report['errors']}")
        require(any("replaceable_antipattern" in error and "王二" in error for error in report["errors"]),
                f"「专名→任意X」必须报反模式：{report['errors']}")
        require(any("leak_suspect" in warning and "剑客" in warning and "@" in warning for warning in report["warnings"]),
                f"未经佐证的名单命中降为带位置的 warning：{report['warnings']}")
        require(not any("source_specific_name_in_mechanism" in error and "剑客" in error for error in report["errors"]),
                f"嫌疑命中不得直接按泄漏报错：{report['errors']}")


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

        payload = MODULE["query"](root, ["题材=玄幻", "情绪=期待"], 6)
        require([match["item_id"] for match in payload["matches"]] == ["CBA-001"], "带核心轴命中必须返回该 CBA")
        require(payload["unmatched_tags"] == [], f"值都在库内时不得报 unmatched：{payload}")
        require(not MODULE["query"](root, ["风险=泄底过早"], 6)["matches"], "只命中非核心轴不得返回")
        drift = MODULE["query"](root, ["题材=东方玄幻"], 6)
        require(not drift["matches"] and drift["unmatched_tags"] == ["题材=东方玄幻"],
                f"漂移值必须被点名而不是静默零命中：{drift}")
        require(drift["axis_inventory"]["题材"] == ["玄幻"], f"须给出该轴现存值供纠词：{drift}")

        resolved = MODULE["resolve"](root, ["测试书/EM-002", "CBA-001"])
        require(resolved["ok"] and resolved["resolved"][0]["location"].endswith("情绪模块.md#EM-002"),
                f"EM 引用必须解析回情绪模块锚点:{resolved}")


VOCABULARY_TEXT = """# 标签词表

## 题材
- 玄幻
## 读者需求
- 认知反转
## 情绪
- 期待
## 剧情功能
- 信息揭示
## 适用阶段
- 细纲
## 风险
- 泄底过早
"""


def test_vocabulary_guard() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        MODULE["register_atoms"](root, module_path, "测试书")
        write(root / "跨书灵感聚合" / "CBA-001_卡.md",
              "# CBA-001：卡\n\n- 验证状态：单书假设\n- 来源：测试书/EM-001\n")
        append_row(root, base_row(item_id="CBA-001", layer="跨书灵感聚合", title="卡",
                                  source_book="测试书", path="跨书灵感聚合/CBA-001_卡.md",
                                  source_ids="测试书/EM-001", tags=CBA_TAGS))
        require(not MODULE["validate"](root), "无词表文件时维持旧行为不报错")
        write(root / "标签词表.md", VOCABULARY_TEXT)
        require(not MODULE["validate"](root), "标签值全在词表内必须通过：" + ";".join(MODULE["validate"](root)))
        require(MODULE["query"](root, ["题材=玄幻", "情绪=期待"], 6)["vocabulary_loaded"], "query 须报告词表已加载")

        write(root / "标签词表.md", VOCABULARY_TEXT.replace("- 泄底过早", "- 铺垫不足"))
        errors = MODULE["validate"](root)
        require(any("tag_value_not_in_vocabulary:风险=泄底过早" in error for error in errors),
                f"表外值必须点名：{errors}")

        write(root / "标签词表.md", VOCABULARY_TEXT.replace("- 认知反转", "- 认知反转\n* 高潮前\n- 高潮"))
        errors = MODULE["validate"](root)
        require(not errors and "高潮前" in MODULE["load_vocabulary"](root)["读者需求"],
                f"子串关系的正常值（高潮前/高潮）不能被当成同义拦下，`* 值` 也要读入：{errors}")

        write(root / "标签词表.md", "# 标签词表\n\n## 题材\n- 玄幻\n")
        errors = MODULE["validate"](root)
        require(any("vocabulary_axis_missing" in error for error in errors),
                f"词表缺必填轴必须报：{errors}")


def test_coverage_reports_uncovered_atoms() -> None:
    with tempfile.TemporaryDirectory(prefix="ilib-") as temporary:
        base = Path(temporary)
        root = make_workspace(base)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        MODULE["register_atoms"](root, module_path, "测试书")
        write(root / "跨书灵感聚合" / "CBA-001_压低预期后兑现.md",
              "# CBA-001：压低预期后兑现\n\n- 验证状态：单书假设\n- 来源：测试书/EM-001\n")
        append_row(root, base_row(item_id="CBA-001", layer="跨书灵感聚合", title="压低预期后兑现",
                                  source_book="测试书", path="跨书灵感聚合/CBA-001_压低预期后兑现.md",
                                  source_ids="测试书/EM-001", tags=CBA_TAGS))
        payload = MODULE["coverage"](root)
        book = payload["books"]["测试书"]
        require(book["atoms"] == 3 and book["covered"] == 1, f"闭包覆盖数必须准确：{payload}")
        require(book["uncovered"] == ["EM-002", "EM-004"], f"未覆盖原子必须点名：{payload}")
        require(payload["single_book_hypotheses"] == ["CBA-001"], f"单书假设卡必须列出待复核：{payload}")


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


def test_parser_and_gate_hardening() -> None:
    card = "| 字段 | 内容 |\n|---|---|\n| 读者想看什么 | 甲 |\n| 情绪链 | 乙 |\n| 戏剧单元 | 丙 |\n| 可替换项 | 丁 |\n| 不可照搬 | 戊 |\n"
    with tempfile.TemporaryDirectory(prefix="ilib-harden-") as temporary:
        base = Path(temporary)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"

        root = make_workspace(base, module_text="## 可复现模块卡\n\n### EM-002\n\n" + card)
        report = MODULE["check_atoms"](root, module_path, "测试书")
        require(any("EM-002:em_title_missing" in error for error in report["errors"]),
                f"无标题卡头不能被截成 EM-00 静默登记：{report}")

        swallowed = "## 可复现模块卡\n\n### EM-001 第一卡\n\n" + card + "\n#### EM-002 第二卡\n\n" + card
        make_workspace(base, module_text=swallowed)
        report = MODULE["check_atoms"](root, module_path, "测试书")
        require(any("em_header_unrecognized" in error for error in report["errors"]),
                f"认不出的 EM 标题不能把下一张卡并进上一张：{report}")
        make_workspace(base, module_text=swallowed.replace("#### EM-002", "### **EM-002**"))
        report = MODULE["check_atoms"](root, module_path, "测试书")
        require(report["ok"] and report["cards_full"] == 2, f"粗体卡头应识别为独立卡：{report}")

        make_workspace(base, module_text="## 可复现模块卡\n\n### EM-001 卡\n\n" + card + "| 情绪链 | 重复 |\n")
        report = MODULE["check_atoms"](root, module_path, "测试书")
        require(any("EM-001:em_field_duplicate:情绪链" in error for error in report["errors"]), f"同卡重复字段必须报：{report}")

        make_workspace(base, book="乙书", module_text=LEAKY_CARD)
        make_workspace(base)
        report = MODULE["check_atoms"](root, base / "拆文库" / "乙书" / "剧情" / "情绪模块.md", "测试书")
        require(any("module_book_mismatch" in error for error in report["errors"]), f"--book 与 --module 必须同书：{report}")

        write(base / "拆文库" / "泄漏书" / "角色" / "主角" / "01-张三.md", "角色卡")
        leaky_root = make_workspace(base, book="泄漏书", module_text=LEAKY_CARD.replace("| 可替换项 | 场景 |", "| 可替换项 | 张三 → 任意主角 |"))
        report = MODULE["check_atoms"](leaky_root, base / "拆文库" / "泄漏书" / "剧情" / "情绪模块.md", "泄漏书")
        require(report["character_roster"] == 1 and any("replaceable_antipattern:张三" in error for error in report["errors"]),
                f"子目录与编号前缀的角色卡也要进泄漏门名单：{report}")

        MODULE["register_atoms"](root, module_path, "测试书")
        with (root / "灵感索引.csv").open("a", encoding="utf-8") as handle:
            handle.write("CBA-009,跨书灵感聚合,短行\n")
        errors = MODULE["validate"](root)
        require(any("column_count_mismatch" in error for error in errors), f"列数不对的行必须报错而不是崩溃：{errors}")
        require(MODULE["coverage"] is not None, "coverage 可用")


def test_parser_does_not_block_legit_modules() -> None:
    fields = "| 读者想看什么 | 甲 |\n| 情绪链 | 乙 |\n| 戏剧单元 | 丙 |\n| 可替换项 | 丁 |\n| 不可照搬 | 戊 |\n"
    legit = (
        "# 情绪模块：EM-001 等机制\n\n## 其他机制索引（EM-004 起）\n\nEM-004｜索引条目｜用途\n\n## 可复现模块卡\n\n"
        "### EM-001 第一卡\n\n| 字段 | 内容 |\n|:---|:---|\n" + fields
        + "| 关键触发物 | 一 |\n| 关键触发物 | 二 |\n\n| 项目 | 内容 |\n|:---|:---|\n| 注意 | 附表 |\n"
        "- **注意**：一\n- **注意**：二\n\n#### 与 EM-002 的区别\n\n说明文字。\n\n"
        "### **EM-002 第二卡**\n\n- ***读者想看什么***：翻盘\n- **情绪链**：\n  - **缺口：**被否定\n  - **爆发：**反证\n"
        "- **戏剧单元：** 公开反证\n- **可替换项**：场景\n- **不可照搬**：原台词\n\n### 重组指南：EM-001 与 EM-002 组合\n\n说明。\n"
    )
    with tempfile.TemporaryDirectory(prefix="ilib-legit-") as temporary:
        base = Path(temporary)
        root = make_workspace(base, module_text=legit)
        module_path = base / "拆文库" / "测试书" / "剧情" / "情绪模块.md"
        report = MODULE["check_atoms"](root, module_path, "测试书")
        require(report["ok"] and report["cards_full"] == 2, f"分隔行、非门禁字段重复、提到 EM 的普通标题与缩进多行值都不能挡住登记：{report}")
        cards, _, _ = MODULE["parse_em_module"](legit)
        require(cards[1]["title"] == "第二卡" and "被否定" in cards[1]["情绪链"] and "反证" in cards[1]["情绪链"],
                f"粗体卡头标题去星号、缩进小标题并入多行值：{cards[1]}")

        make_workspace(base, module_text="## 可复现模块卡\n\n### EM-001 第一卡\n\n" + fields + "\n## EM-002 被吞的卡\n\n" + fields)
        report = MODULE["check_atoms"](root, module_path, "测试书")
        require(any("em_header_unrecognized" in error for error in report["errors"]), f"`## EM-xxx` 卡头必须报错：{report}")

        make_workspace(base, book="乙书", module_text=LEAKY_CARD)
        report = MODULE["check_atoms"](root, base / "拆文库" / "乙书" / "剧情" / "情绪模块.md", ".")
        require(any("book_name_invalid" in error for error in report["errors"]), f"`--book .` 必须拒绝：{report}")

        make_workspace(base)
        MODULE["register_atoms"](root, module_path, "测试书")
        rows = index_rows(root)
        text = (root / "灵感索引.csv").read_text(encoding="utf-8-sig").rstrip("\n").split("\n")
        text.insert(2, "IA-099,原子灵感,短行")
        (root / "灵感索引.csv").write_bytes(("\ufeff" + "\n".join(text) + "\n").encode("utf-8"))
        errors = MODULE["validate"](root)
        require("line_3:column_count_mismatch" in errors, f"坏行按文件实际行号报告：{errors}")
        require(MODULE["coverage"] is not None and rows, "fixture 可用")


def main() -> int:
    test_register_and_idempotence()
    test_parse_genre_variants()
    test_register_rejects_incomplete_and_leaky_cards()
    test_workspace_gate_and_check_atoms()
    test_multiline_values_and_leak_tiering()
    test_validate_cba_closure_and_markers()
    test_vocabulary_guard()
    test_coverage_reports_uncovered_atoms()
    test_validate_rejects_path_reference_in_card()
    test_validate_set_mismatch_and_nm_rules()
    test_parser_and_gate_hardening()
    test_parser_does_not_block_legit_modules()
    print("OK: inspiration index regressions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
