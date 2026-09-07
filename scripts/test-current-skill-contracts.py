#!/usr/bin/env python3
"""Focused regressions for the structured current-contract validator."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MODULE_PATH = SCRIPT_DIR / "check-current-skill-contracts.py"
SPEC = importlib.util.spec_from_file_location("current_contract_validator", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def finding_codes(findings: list[object]) -> set[str]:
    return {finding.code for finding in findings}


def repository_manifest() -> object:
    manifest, findings = VALIDATOR.load_manifest(SCRIPT_DIR / "current-contract.json")
    require(not findings and manifest is not None, "repository manifest must load")
    return manifest


def manifest_with(**overrides: object) -> object:
    """按正常加载路径构造一个改过值的当前契约，用来演练 bump。"""
    raw = json.loads((SCRIPT_DIR / "current-contract.json").read_text(encoding="utf-8"))
    raw.update(overrides)
    with tempfile.TemporaryDirectory() as tmp:
        bumped_path = Path(tmp) / "bumped.json"
        bumped_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        manifest, findings = VALIDATOR.load_manifest(bumped_path)
    require(not findings and manifest is not None, "bumped manifest must stay well-formed")
    return manifest


def flagged_paths(manifest: object, code: str) -> set[str]:
    return {
        finding.path.relative_to(REPO_ROOT).as_posix()
        for finding in VALIDATOR.validate_repository(REPO_ROOT, manifest)
        if finding.code == code and finding.path is not None
    }


def test_manifest_contract() -> None:
    manifest_path = SCRIPT_DIR / "current-contract.json"
    manifest, findings = VALIDATOR.load_manifest(manifest_path)
    require(not findings, "repository manifest should validate: {}".format(findings))
    require(manifest is not None, "repository manifest should load")
    require(not VALIDATOR.validate_repository(REPO_ROOT, manifest), "manifest and repository must agree")

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        wrong_type = dict(raw)
        wrong_type["agents_version"] = "18"
        wrong_type_path = tmpdir / "wrong-type.json"
        wrong_type_path.write_text(json.dumps(wrong_type, ensure_ascii=False), encoding="utf-8")
        _, wrong_type_findings = VALIDATOR.load_manifest(wrong_type_path)
        require(
            "manifest-value-type" in finding_codes(wrong_type_findings),
            "string agents_version must be rejected",
        )

        stale = dict(raw)
        stale["topic_decision_phase"] = 4
        stale_path = tmpdir / "stale.json"
        stale_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        stale_manifest, stale_findings = VALIDATOR.load_manifest(stale_path)
        require(
            not stale_findings and stale_manifest is not None,
            "a well-formed manifest remains the source of truth",
        )
        require(
            "topic-decision-phase" in finding_codes(
                VALIDATOR.validate_repository(REPO_ROOT, stale_manifest)
            ),
            "repository drift from the manifest must be rejected",
        )

        malformed_sections = dict(raw)
        malformed_sections["required_outline_sections"] = [{"rule": "阶段位置"}]
        malformed_path = tmpdir / "malformed-sections.json"
        malformed_path.write_text(json.dumps(malformed_sections, ensure_ascii=False), encoding="utf-8")
        _, malformed_findings = VALIDATOR.load_manifest(malformed_path)
        require(
            "manifest-outline-type" in finding_codes(malformed_findings),
            "incomplete outline-section objects must be rejected",
        )

        duplicate_artifacts = dict(raw)
        duplicate_artifacts["primary_benchmark_artifacts"] = ["全局分析/六维拆书.md", "全局分析/六维拆书.md"]
        duplicate_path = tmpdir / "duplicate-artifacts.json"
        duplicate_path.write_text(json.dumps(duplicate_artifacts, ensure_ascii=False), encoding="utf-8")
        _, duplicate_findings = VALIDATOR.load_manifest(duplicate_path)
        require(
            "manifest-artifact-duplicate" in finding_codes(duplicate_findings),
            "duplicate primary artifacts must be rejected",
        )

        renamed_artifacts = dict(raw)
        renamed_artifacts["primary_benchmark_artifacts"] = [
            "剧情/主情绪.md",
            "剧情/主节奏.md",
        ]
        renamed_path = tmpdir / "renamed-artifacts.json"
        renamed_path.write_text(
            json.dumps(renamed_artifacts, ensure_ascii=False), encoding="utf-8"
        )
        renamed_manifest, renamed_findings = VALIDATOR.load_manifest(renamed_path)
        require(
            not renamed_findings and renamed_manifest is not None,
            "renamed current artifacts must remain manifest-driven",
        )
        renamed_semantic = semantic_findings(
            "- 若 `剧情/主节奏.md` 缺失，回退读取 `拆文报告.md`。",
            renamed_manifest.primary_benchmark_artifacts,
        )
        require(
            "silent-primary-artifact-fallback" in finding_codes(renamed_semantic),
            "semantic guard must follow renamed manifest artifacts",
        )


def semantic_findings(
    text: str, primary_artifacts: tuple[str, ...] | None = None
) -> list[object]:
    if primary_artifacts is None:
        primary_artifacts = repository_manifest().primary_benchmark_artifacts
    return VALIDATOR.semantic_primary_fallback_findings(
        text,
        Path("fixture.md"),
        primary_artifacts,
    )


def test_bad_fallbacks_fail() -> None:
    bad_cases = {
        "inline report fallback": "- 若 `全局分析/爆款机制.md` 缺失，回退读取 `拆文报告.md`。",
        "nested summary substitution": """
1. 检查 `全局分析/六维拆书.md` 的“三维节奏”章节。
2. 任一主产物缺失时：
   - 使用 `章节/*_摘要.md` 代替。
""",
        "structured gap story fallback": "- `rhythm_missing: true` 时改用 `故事线.md` 补足节奏。",
    }
    for label, text in bad_cases.items():
        findings = semantic_findings(text)
        require(
            "silent-primary-artifact-fallback" in finding_codes(findings),
            "{} should fail".format(label),
        )


def test_fail_fast_prose_passes() -> None:
    good_cases = {
        "explicit不得": "- `全局分析/爆款机制.md` 缺失时必须停止；不得以 `拆文报告.md`、章节摘要或故事线代替。",
        "explicit禁止 fallback": "- `rhythm_missing: true` 时返回 `missing_primary_contract`，禁止 fallback 到 `故事线.md`。",
        "normal complete branch": "- 两个主产物都存在时读取 `拆文报告.md`，仅作人类可读概览。",
        "deep-dive fallback is not primary fallback": (
            "- 先读 `全局分析/爆款机制.md` 与 `全局分析/六维拆书.md`；机制或六维文件缺失时停止修复。"
            "匹配 `章节/*_摘要.md` 后，若同章深度拆解不存在，则回退黄金三章深度拆解。"
        ),
    }
    for label, text in good_cases.items():
        findings = semantic_findings(text)
        require(not findings, "{} should pass, got {}".format(label, findings))


def test_sibling_bullets_do_not_lend_the_missing_condition() -> None:
    """相邻条目各自是独立契约：fail-fast 兄弟条目不得把「主产物缺失」借给正确的读取条目。"""
    fail_fast = "- `全局分析/六维拆书.md` → 缺失时停止导入，不得以 `拆文报告.md`、章节摘要或故事线代替"
    good_neighbours = {
        "benign read after a fail-fast sibling": "- 两个主产物都存在时读取 `拆文报告.md`，仅作人类可读概览。",
        "human-readable overview bullet": "- 故事线（人类可读概览）→ 从 `剧情/故事线.md` 读取；缺失时留空",
        "prose block after a fail-fast bullet": "**无损检查**（任一不过即删除 `_章节摘要汇总.md`、回退逐文件扫描）：",
    }
    for label, good in good_neighbours.items():
        findings = semantic_findings(fail_fast + "\n" + good + "\n")
        require(not findings, "{} should pass, got {}".format(label, findings))

    nested = (
        "任一主产物缺失时：\n"
        "- 先记录到追踪\n"
        "- 再确认块状态\n"
        "- 回退读取 `拆文报告.md` 拼出对标视图\n"
    )
    require(
        "silent-primary-artifact-fallback" in finding_codes(semantic_findings(nested)),
        "上级条目给出的缺失条件必须仍然拦住降级子项",
    )
    deep = "- 主产物缺失时：\n  - 导入分支：\n    - 采用 `故事线.md` 顶替。\n"
    require(
        "silent-primary-artifact-fallback" in finding_codes(semantic_findings(deep)),
        "隔了一层的上级条件也要拦住降级子项",
    )
    wrapped = "- 若 `全局分析/六维拆书.md` 缺失，\n  则改读 `章节/*_摘要.md` 补足节奏。\n"
    require(
        "silent-primary-artifact-fallback" in finding_codes(semantic_findings(wrapped)),
        "同一条目的续行仍与条件同属一件事",
    )
    table_rows = (
        "| 条件 | 行为 |\n"
        "|---|---|\n"
        "| `全局分析/六维拆书.md` 缺失 | 停止 Stage 6 并报 `missing_primary_contract` |\n"
        "| `章节/第1-3章_深度拆解.md` 缺失 | 对话潜台词段从拆文报告兜底 |\n"
    )
    require(
        not semantic_findings(table_rows),
        "表格里相邻行是独立记录，深度拆解兜底不是主产物降级：{}".format(
            semantic_findings(table_rows)
        ),
    )
    bad_row = (
        "| 条件 | 行为 |\n"
        "|---|---|\n"
        "| `全局分析/六维拆书.md` 缺失 | 回退读取 `拆文报告.md` 补足节奏 |\n"
    )
    require(
        "silent-primary-artifact-fallback" in finding_codes(semantic_findings(bad_row)),
        "同一表格行内的主产物降级必须拦住",
    )


def test_undecodable_markdown_is_a_named_failure() -> None:
    """非 UTF-8 文本会让所有内容规则静默放行，必须命名报错；二进制资产照旧跳过。"""
    rule = next(
        r for r in VALIDATOR.LEGACY_RULES if r.code == "dotted-demo-workflow-label"
    )
    dotted = "# 流程说明\n\n旧编号：Step 1.2：旧编号标签\n"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        demo = root / "demo"
        demo.mkdir()
        target = demo / "流程说明.md"
        target.write_text(dotted, encoding="utf-8")
        require(
            VALIDATOR.check_absent_rule(root, rule),
            "UTF-8 的旧编号标签必须被内容规则拦住",
        )
        target.write_bytes(dotted.encode("gb18030"))
        require(
            not VALIDATOR.check_absent_rule(root, rule),
            "内容规则读不出 GBK 文件，这正是需要专门扫描的原因",
        )
        require(
            "unreadable-source-file"
            in finding_codes(VALIDATOR.undecodable_source_findings([demo])),
            "非 UTF-8 的契约文本必须是命名失败，不能静默跳过",
        )
        target.write_text(dotted, encoding="utf-16")
        require(
            "unreadable-source-file"
            in finding_codes(VALIDATOR.undecodable_source_findings([demo])),
            "UTF-16 Markdown 含 NUL，但仍是契约文本，不能伪装成二进制资产跳过",
        )
        target.write_text(dotted, encoding="utf-8")
        (demo / "封面.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
        # 无后缀 / 非白名单后缀的二进制（.DS_Store 之类）靠 NUL 字节识别，不能误报
        (demo / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1\xff\xfe")
        require(
            not VALIDATOR.undecodable_source_findings([demo]),
            "二进制资产不是契约文本，必须保持静默：{}".format(
                VALIDATOR.undecodable_source_findings([demo])
            ),
        )


def test_progress_schema_pins_are_repo_wide() -> None:
    """bump progress_schema_version 时，每个字面锚点都要被点名，不能只点 pipeline-ops.md。"""
    current = repository_manifest().progress_schema_version
    stale = flagged_paths(
        manifest_with(progress_schema_version=current + 1), "progress-schema-version"
    )
    for relative in (
        "skills/story-long-analyze/references/pipeline-ops.md",
        "skills/story-long-analyze/SKILL.md",
        "skills/story-import/SKILL.md",
        "skills/story-setup/UPGRADING.md",
        "demo/拆文库/盘龙/_progress.json",
        "demo/拆文库/盘龙/_state_snapshot.json",
    ):
        require(
            relative in stale,
            "{} 的 schema_version 锚点必须跟着 manifest 走，实际命中 {}".format(
                relative, sorted(stale)
            ),
        )
    require(
        "CHANGELOG.md" not in stale,
        "CHANGELOG 的历史记录不受当前值约束",
    )


def test_stale_scan_phase_reference_accepts_backticks() -> None:
    """房子风格 `story-long-scan` Phase N 与裸 token 写法都要被 stale 引用扫描抓到。"""
    current = repository_manifest().topic_decision_phase
    stale = flagged_paths(
        manifest_with(topic_decision_phase=current + 1),
        "stale-topic-decision-phase-reference",
    )
    # 长篇「先查选题决策」随 Phase 1 搬进 workflow-setup.md（#269），扫描目标跟着内容走。
    for relative in (
        "skills/story-long-write/references/workflow-setup.md",
        "skills/story-long-analyze/SKILL.md",
    ):
        require(
            relative in stale,
            "{} 的选题决策阶段引用必须被扫到，实际命中 {}".format(relative, sorted(stale)),
        )


def test_structured_sentinel_contract() -> None:
    manifest = repository_manifest()
    scattered = """
agents_version: {agents_version}
setup_skill_version: {setup_skill_version}
说明文字中还提到了 target_cli、resolver_strategy 与 references_dir。
""".format(
        agents_version=manifest.agents_version,
        setup_skill_version=manifest.setup_skill_version,
    )
    require(
        VALIDATOR.extract_sentinel_fields(scattered) is None,
        "scattered sentinel tokens must not satisfy the deployment block",
    )
    require(
        "setup-sentinel-block"
        in finding_codes(
            VALIDATOR.sentinel_contract_findings(
                scattered, manifest, Path("fixture.md")
            )
        ),
        "missing structured sentinel block must fail",
    )

    structured = """
### Step 8：创建部署标记

- 写入以下字段：

```yaml
deployed_at: 2026-07-14T00:00:00Z
agents_version: {agents_version}
setup_skill_version: {setup_skill_version}
target_cli: codex
resolver_strategy: project-first
references_dir: .codex/skills/story-setup/references
```
""".format(
        agents_version=manifest.agents_version,
        setup_skill_version=manifest.setup_skill_version,
    )
    require(
        not VALIDATOR.sentinel_contract_findings(
            structured, manifest, Path("fixture.md")
        ),
        "well-formed structured sentinel must pass",
    )

    incomplete = structured.replace("target_cli: codex\n", "")
    require(
        "setup-sentinel-fields"
        in finding_codes(
            VALIDATOR.sentinel_contract_findings(
                incomplete, manifest, Path("fixture.md")
            )
        ),
        "missing generated sentinel fields must fail",
    )


def test_structured_outline_contract() -> None:
    manifest = repository_manifest()
    rule_names = [rule for rule, _ in manifest.required_outline_sections]
    demo_names = [demo for _, demo in manifest.required_outline_sections]

    scattered_rule = "2. **细纲必填项**\n\n" + "、".join(rule_names)
    require(
        "outline-rule-section"
        in finding_codes(
            VALIDATOR.outline_rule_contract_findings(
                scattered_rule, manifest, Path("rule.md")
            )
        ),
        "outline names scattered in prose must not satisfy structured rules",
    )
    structured_rule = (
        "2. **细纲必填项**\n"
        + "\n".join("- {}：必填".format(name) for name in rule_names)
        + "\n3. **下一条规则**\n"
    )
    require(
        not VALIDATOR.outline_rule_contract_findings(
            structured_rule, manifest, Path("rule.md")
        ),
        "structured outline rule fields must pass",
    )

    scattered_demo = "本章应包含：" + "、".join(demo_names)
    declared = VALIDATOR.extract_demo_outline_fields(scattered_demo)
    require(
        not set(demo_names).issubset(declared),
        "demo names scattered in prose must not count as declared sections",
    )
    structured_demo = "\n".join("## {}".format(name) for name in demo_names)
    require(
        set(demo_names).issubset(
            VALIDATOR.extract_demo_outline_fields(structured_demo)
        ),
        "structured demo headings must be recognized",
    )


def test_upgrading_version_contract() -> None:
    manifest = repository_manifest()
    structured = """
## 当前版本

- `setup_skill_version: {setup_skill_version}`
- `agents_version: {agents_version}`

## 下一节
""".format(
        setup_skill_version=manifest.setup_skill_version,
        agents_version=manifest.agents_version,
    )
    require(
        not VALIDATOR.upgrading_version_findings(
            structured, manifest, Path("UPGRADING.md")
        ),
        "structured current-version bullets must pass",
    )
    scattered = (
        "说明 setup_skill_version: {}，agents_version: {}，但没有当前版本字段。".format(
            manifest.setup_skill_version, manifest.agents_version
        )
    )
    require(
        "upgrading-current-version"
        in finding_codes(
            VALIDATOR.upgrading_version_findings(
                scattered, manifest, Path("UPGRADING.md")
            )
        ),
        "version strings scattered in prose must not satisfy current-version bullets",
    )


def test_deeply_nested_fallback_keeps_all_governing_ancestors() -> None:
    text = (
        "- `剧情/节奏.md` 缺失时：\n"
        "  - 导入阶段：\n"
        "    - 第六阶段：\n"
        "      - 对标视图：\n"
        "        - 回退读取 `拆文报告.md` 拼出节奏。\n"
    )
    found = VALIDATOR.semantic_primary_fallback_findings(
        text,
        Path("deeply-nested.md"),
        ("剧情/节奏.md",),
    )
    require(
        "silent-primary-artifact-fallback" in finding_codes(found),
        "深层列表的主产物缺失条件必须一路传到回退动作，不能在三层后丢失",
    )


def test_old_artifact_prose_silent_only() -> None:
    """keep C：带显式标记的旧格式大纲容忍放行，无标记的静默降级仍拦（drop A/B 不受影响）。"""
    rule = next(r for r in VALIDATOR.LEGACY_RULES if r.code == "old-artifact-prose")
    require(rule.exempt_when is not None, "old-artifact-prose must narrow to silent-only")
    flagged = [
        "旧版细纲缺这些字段不阻塞读取，未知项写 `[待补充]`。",
        "旧版细纲回退读取核心事件、情节点序列、目标情绪。",
        "旧版卷纲缺少卷契约/剧情单元卡不阻塞日更；本轮记录到 `追踪/上下文.md`。",
        "旧版细纲只核对核心事件、目标情绪、章首/章尾钩子和字数目标。",
    ]
    silent = [
        "直接改读旧版细纲当权威，不提示。",
        "早期拆文库格式直接拿来用。",
        "兼容旧结构，静默继续写作。",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        skills = root / "skills" / "story-long-write"
        skills.mkdir(parents=True)
        (skills / "keep-c.md").write_text("\n".join(flagged) + "\n", encoding="utf-8")
        require(
            not VALIDATOR.check_absent_rule(root, rule),
            "flagged old-outline tolerance (keep C) must pass, got {}".format(
                VALIDATOR.check_absent_rule(root, rule)
            ),
        )
        (skills / "keep-c.md").write_text("\n".join(silent) + "\n", encoding="utf-8")
        found = VALIDATOR.check_absent_rule(root, rule)
        require(
            len(found) == len(silent),
            "each silent old-format downgrade must fire, got {}".format(found),
        )


def test_story_import_keeps_self_out_of_benchmarks() -> None:
    cases = {
        "story-import-self-main-benchmark": "主对标书: {书名}\n导入当前书时至少登记自身为 `主`。\n",
        "story-import-self-benchmark-copy": (
            "把 `拆文库/{书名}/` 复制到 `{项目}/对标/{书名}/`。\n"
            "短篇复制到 `{标题}/对标/{书名}/`。\n"
        ),
        "story-import-self-benchmark-summary": "## 对标摘要：{原书名}\n",
        "story-import-self-benchmark-fields": (
            "把 `拆文报告.md` 的故事核/题材/对标字段映射进本书设定。\n"
        ),
        "story-import-import-title-benchmark-target": (
            "将 `拆文库/{导入书名}/` 整体复制到项目 `对标/`。\n"
        ),
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "skills" / "story-import" / "fixture.md"
        target.parent.mkdir(parents=True)
        for code, content in cases.items():
            target.write_text(content, encoding="utf-8")
            rule = next(r for r in VALIDATOR.LEGACY_RULES if r.code == code)
            found = VALIDATOR.check_absent_rule(root, rule)
            require(found, "{} must reject imported-work benchmark leakage".format(code))

        guard_rule = next(
            r
            for r in VALIDATOR.LEGACY_RULES
            if r.code == "story-import-import-title-benchmark-target"
        )
        target.write_text(
            "不得把 `拆文库/{导入书名}/` 整体复制进 `对标/`。\n",
            encoding="utf-8",
        )
        require(
            not VALIDATOR.check_absent_rule(root, guard_rule),
            "explicit self-benchmark prohibition must remain documentable",
        )


def test_spawn_preflight_uses_agents_version_not_file_existence() -> None:
    manifest = repository_manifest()
    stale = manifest.agents_version - 1
    existence_only = """
检测到 `.claude/agents/chapter-extractor.md` 存在，所以可以 spawn。
.story-deployed:
  agents_version: {stale}
""".format(stale=stale)
    found = VALIDATOR.spawn_preflight_findings(
        existence_only, manifest, Path("story-import-fixture.md")
    )
    require(
        "spawn-agents-version-preflight" in finding_codes(found),
        "a stale agent file must not satisfy the spawn preflight",
    )

    current = manifest.agents_version
    current_contract = """
读取 `.story-deployed` 的 `agents_version: {current}`；不一致时照常按文件存在性检查并 spawn，
报告 `Notice: agents bundle 版本不匹配（项目 {{N}}，本版 {current}）` 并提示重跑 `/story-setup`。
大于 {current} 时额外提示先更新 oh-story-claudecode。
只有 agent 文件缺失、或运行时不暴露 custom agent 时才降级 solo/direct，报告 `Fallback: ... -> solo`。
""".format(current=current)
    require(
        not VALIDATOR.spawn_preflight_findings(
            current_contract, manifest, Path("current-fixture.md")
        ),
        "the current shared spawn preflight must pass",
    )

    bumped = manifest_with(agents_version=current + 1)
    stale_paths = flagged_paths(bumped, "spawn-agents-version-preflight")
    require(
        stale_paths == set(VALIDATOR.SPAWN_CAPABLE_SKILLS),
        "an agents_version bump must flag every spawn-capable Skill, got {}".format(
            sorted(stale_paths)
        ),
    )


def test_reviewed_benchmark_wording_stays_removed() -> None:
    cases = {
        "benchmark-primary-nonblocking-wording": "缺失按原流程，不阻塞。\n",
        "no-benchmark-skips-genre-card": "无对标时跳过「对标模块/节奏/题材卡/文风召回」。\n",
        "style-profile-all-inputs-required": "前置依赖：报告、摘要、原文齐全。\n",
        "context-missing-skips-all": "读取上下文（按需加载，缺失则跳过）。\n",
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for code, content in cases.items():
            rule = next(r for r in VALIDATOR.LEGACY_RULES if r.code == code)
            relative = Path(rule.relative_roots[0])
            target = root / relative
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
                target = target / "fixture.md"
            target.write_text(content, encoding="utf-8")
            require(
                VALIDATOR.check_absent_rule(root, rule),
                "{} must reject the reviewed stale wording".format(code),
            )


def test_p1_deletion_guards() -> None:
    rules = {rule.code: rule for rule in VALIDATOR.LEGACY_RULES}
    cases = {
        "static-long-word-floor": (
            "skills/story-long-write/SKILL.md",
            "**默认最低字数：3000 字/章。**\n",
            "长篇按细纲字数目标验收；实际字数低于目标 90% 时阻断。\n",
        ),
        "broad-chrome-cleanup-doc": (
            "skills/browser-cdp/SKILL.md",
            "卡死时执行 `pkill -9 -x 'Google Chrome'`。\n",
            "卡死时关闭已确认属于 debug profile 的 Chrome 窗口；不要终止普通 Chrome。\n",
        ),
    }
    for code, (relative_path, bad, good) in cases.items():
        rule = rules[code]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(bad, encoding="utf-8")
            require(
                finding_codes(VALIDATOR.check_absent_rule(root, rule)) == {code},
                "{} must reject its retired authority/bypass".format(code),
            )
            path.write_text(good, encoding="utf-8")
            require(
                not VALIDATOR.check_absent_rule(root, rule),
                "{} must accept the canonical contract".format(code),
            )


def test_analyze_portability_guards() -> None:
    """Stage 6 的样本路径与 Stage 0 的目录块剔除都必须留在文档里。

    两者都只在真实运行时才暴露：/tmp 绝对路径要探到 Windows 原生 python 才炸，
    目录块要原文自带目录才多切一遍章。守卫是它们唯一的回归网。
    """

    rule = next(
        r for r in VALIDATOR.LEGACY_RULES if r.code == "analyze-posix-tmp-sample-path"
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "skills/story-long-analyze/references/style-profile-generator.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("把 3 段拼接写入 `/tmp/style-sample.txt`。\n", encoding="utf-8")
        require(
            finding_codes(VALIDATOR.check_absent_rule(root, rule))
            == {"analyze-posix-tmp-sample-path"},
            "the POSIX /tmp sample path must be rejected",
        )
        path.write_text(
            "把 3 段拼接写入 `拆文库/{书名}/_style-sample.txt`。\n", encoding="utf-8"
        )
        require(
            not VALIDATOR.check_absent_rule(root, rule),
            "a project-relative sample path must be accepted",
        )

    stage0_cases = (
        (r"先剔掉目录块", "stage0-toc-block-removal"),
        (r"落表前校验章号连续", "stage0-chapter-table-validation"),
    )
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "SKILL.md"
        fixture.write_text("- grep 出全部章节行号\n", encoding="utf-8")
        for pattern, code in stage0_cases:
            require(
                finding_codes(VALIDATOR.require_pattern(fixture, pattern, code, code))
                == {code},
                "{} must fire when Stage 0 drops the rule".format(code),
            )
        fixture.write_text(
            "- **先剔掉目录块**：按行距丢弃开头的目录命中\n"
            "- 落表前校验章号连续、无重复、无跳号\n",
            encoding="utf-8",
        )
        for pattern, code in stage0_cases:
            require(
                not VALIDATOR.require_pattern(fixture, pattern, code, code),
                "{} must accept the documented Stage 0 contract".format(code),
            )


def test_rubric_parity_guard() -> None:
    """两份通用 rubric 必须同维度；两边都读不到时不能算通过。"""

    rubric = (
        "## 核心维度\n\n"
        "| 维度 | PASS | WARN | FAIL |\n"
        "|---|---|---|---|\n"
        "| 核心卖点 | a | b | c |\n"
        "| 标点节奏 | a | b | c |\n"
        "\n## 发布建议门槛\n\n"
        "| 综合情况 | Verdict |\n"
        "|---|---|\n"
        "| 无 S1/S2 | PASS |\n"
    )
    embedded = "通用网文内容 rubric：\n- 核心卖点：x\n- 标点节奏：y\n\nAI 味 fallback：\n"

    def build(root: Path, rubric_body: str, skill_body: str) -> None:
        r = root / "skills/story-review/references/quality-rubric.md"
        s = root / "skills/story-review/SKILL.md"
        r.parent.mkdir(parents=True, exist_ok=True)
        r.write_text(rubric_body, encoding="utf-8")
        s.write_text(skill_body, encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build(root, rubric, embedded)
        require(
            not VALIDATOR.rubric_parity_findings(root),
            "matching rubric dimensions must pass",
        )
        # 发布门槛表不是维度表，不能被算进来
        table, _ = VALIDATOR.rubric_dimension_names(root)
        require(
            table == ["核心卖点", "标点节奏"],
            "only the 核心维度 table counts, got {}".format(table),
        )

        build(root, rubric.replace("| 标点节奏 |", "| 标点节奏X |", 1), embedded)
        require(
            finding_codes(VALIDATOR.rubric_parity_findings(root)) == {"rubric-dimension-drift"},
            "a dimension present only in the embedded fallback must fail",
        )

        build(root, rubric, embedded.replace("- 标点节奏：y\n", "", 1))
        require(
            finding_codes(VALIDATOR.rubric_parity_findings(root)) == {"rubric-dimension-drift"},
            "a dimension present only in the file must fail",
        )

        # 整块删掉时两边都是空列表——空集相等，必须显式拦成读取失败而不是静默通过
        build(root, rubric, "没有内置 rubric 了\n")
        require(
            finding_codes(VALIDATOR.rubric_parity_findings(root)) == {"rubric-parity-unreadable"},
            "a missing embedded rubric must not pass vacuously",
        )


def test_style_profile_is_not_a_book_existence_probe() -> None:
    """文风.md 兼任目录探针会把「书在但缺文风」判成「书不存在」。

    explorer 在步骤 3 就提前返回 benchmark_book_missing，步骤 6 的 profile_missing 变成
    不可达，调用方 profile_missing + custom_style 的降级续写分支被整条吞掉——是功能回退，
    不是措辞问题，所以旧探针写法必须硬拦。
    """

    rules = {rule.code: rule for rule in VALIDATOR.LEGACY_RULES}
    explorer = "skills/story-setup/references/templates/agents/story-explorer.md"
    cases = {
        "style-profile-as-book-existence-probe": (
            explorer,
            "3. **对标书路径查找**：优先探 `{项目}/对标/{书名}/文风.md`，"
            "回退探 `拆文库/{书名}/文风.md`；探针是文件不是目录\n",
            "3. **对标书路径查找（只判书目录有效性，不判文风）**："
            "优先探 `{项目}/对标/{书名}/**/*`，回退探 `拆文库/{书名}/**/*`；"
            "**不得用 `文风.md` 兼作目录存在性探针**\n",
        ),
        "forbidden-outline-numeric-capacity": (
            "skills/story-long-write/references/workflow-setup.md",
            "末尾写一行 `目标字数合计：下限X字（章目标Y，范围Y-Z）`。\n",
            "情节点只写语义义务，不填写逐点字数。\n",
        ),
    }
    for code, (relative_path, bad, good) in cases.items():
        rule = rules[code]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(bad, encoding="utf-8")
            require(
                finding_codes(VALIDATOR.check_absent_rule(root, rule)) == {code},
                "{} must reject the pre-fix wording".format(code),
            )
            path.write_text(good, encoding="utf-8")
            require(
                not VALIDATOR.check_absent_rule(root, rule),
                "{} must accept the canonical wording".format(code),
            )

    # 未登记主对标的枚举回退同样不能拿文风.md 当候选过滤器：缺文风但资料完整的书会被
    # 算成 no_benchmark，和「一本对标都没有」混为一谈。
    probe_rule = rules["style-profile-as-book-existence-probe"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / explorer
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "若字段缺失或已忽略 → `Glob 对标/*/文风.md`，取字典序第一个\n",
            encoding="utf-8",
        )
        require(
            finding_codes(VALIDATOR.check_absent_rule(root, probe_rule))
            == {"style-profile-as-book-existence-probe"},
            "benchmark enumeration must not filter candidates by 文风.md",
        )

    # 显式禁止旧字段的说明文字本身不算违规，否则规则没法写进文档。
    budget_rule = rules["forbidden-outline-numeric-capacity"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "skills/story-long-write/references/workflow-setup.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("不得再写旧字段 `预算合计` 或 `目标字数合计`。\n", encoding="utf-8")
        require(
            not VALIDATOR.check_absent_rule(root, budget_rule),
            "an explicit prohibition of 预算合计 must stay documentable",
        )


def test_outline_total_and_profile_gap_parity() -> None:
    """跨文件契约必须在真仓库上真命中。

    require_pattern 在路径写错时会退化成同 code 的 `cannot read required file`，所以
    「这些 code 一个都不出现」同时证明了目标文件存在、且正则确实匹配上了内容。
    """

    manifest = repository_manifest()
    expected_clean = {
        "explorer-book-dir-probe",
        "explorer-profile-missing-distinct",
        "daily-profile-missing-custom-style",
        "outline-semantic-capacity-parity",
    }
    actual = finding_codes(VALIDATOR.validate_repository(REPO_ROOT, manifest))
    leaked = sorted(expected_clean & actual)
    require(
        not leaked,
        "repository must satisfy the profile-gap / outline-total contracts: {}".format(leaked),
    )


def main() -> int:
    test_manifest_contract()
    test_bad_fallbacks_fail()
    test_fail_fast_prose_passes()
    test_sibling_bullets_do_not_lend_the_missing_condition()
    test_undecodable_markdown_is_a_named_failure()
    test_progress_schema_pins_are_repo_wide()
    test_deeply_nested_fallback_keeps_all_governing_ancestors()
    test_stale_scan_phase_reference_accepts_backticks()
    test_old_artifact_prose_silent_only()
    test_story_import_keeps_self_out_of_benchmarks()
    test_spawn_preflight_uses_agents_version_not_file_existence()
    test_reviewed_benchmark_wording_stays_removed()
    test_p1_deletion_guards()
    test_analyze_portability_guards()
    test_rubric_parity_guard()
    test_structured_sentinel_contract()
    test_structured_outline_contract()
    test_upgrading_version_contract()
    test_style_profile_is_not_a_book_existence_probe()
    test_outline_total_and_profile_gap_parity()
    print("OK: current-contract manifest, structure, and fallback regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
