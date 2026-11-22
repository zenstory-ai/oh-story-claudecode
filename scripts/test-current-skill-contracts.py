#!/usr/bin/env python3
"""Focused regressions for the hard runtime contract pins in lint-repo.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MODULE_PATH = SCRIPT_DIR / "lint-repo.py"
SPEC = importlib.util.spec_from_file_location("lint_repo_validator", MODULE_PATH)
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
    require(not findings and manifest is not None, f"repository manifest must load: {findings}")
    return manifest


def manifest_with(**overrides: object) -> object:
    raw = json.loads((SCRIPT_DIR / "current-contract.json").read_text(encoding="utf-8"))
    raw.update(overrides)
    with tempfile.TemporaryDirectory() as tmp:
        bumped_path = Path(tmp) / "bumped.json"
        bumped_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        manifest, findings = VALIDATOR.load_manifest(bumped_path)
    require(not findings and manifest is not None, f"bumped manifest must stay well-formed: {findings}")
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
    require(not findings and manifest is not None, f"repository manifest should validate: {findings}")
    require(not VALIDATOR.validate_repository(REPO_ROOT, manifest), "real repository contracts must pass")

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        wrong_type = dict(raw, agents_version="44")
        p = tmpdir / "wrong-type.json"
        p.write_text(json.dumps(wrong_type, ensure_ascii=False), encoding="utf-8")
        _, f = VALIDATOR.load_manifest(p)
        require("manifest-value-type" in finding_codes(f), "string agents_version must be rejected")

        for removed_key, sample_val in (
            ("topic_decision_phase", 5),
            ("required_outline_sections", [{"rule": "阶段位置", "demo": "阶段位置"}]),
        ):
            legacy = dict(raw, **{removed_key: sample_val})
            p = tmpdir / f"legacy-{removed_key}.json"
            p.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            _, f = VALIDATOR.load_manifest(p)
            require("manifest-key-unknown" in finding_codes(f), f"removed key {removed_key} must be rejected")

        dup = dict(raw, primary_benchmark_artifacts=["剧情/节奏.md", "剧情/节奏.md"])
        p = tmpdir / "dup.json"
        p.write_text(json.dumps(dup, ensure_ascii=False), encoding="utf-8")
        _, f = VALIDATOR.load_manifest(p)
        require("manifest-artifact-duplicate" in finding_codes(f), "duplicate primary artifacts must be rejected")


def test_structured_sentinel_contract() -> None:
    manifest = repository_manifest()
    scattered = (
        f"agents_version: {manifest.agents_version}\n"
        f"setup_skill_version: {manifest.setup_skill_version}\n"
        "说明文字中提到了 target_cli、resolver_strategy 与 references_dir。\n"
    )
    require(VALIDATOR.extract_sentinel_fields(scattered) is None, "scattered tokens must not satisfy sentinel block")
    require(
        "setup-sentinel-block"
        in finding_codes(VALIDATOR.sentinel_contract_findings(scattered, manifest, Path("fixture.md"))),
        "missing structured sentinel block must fail",
    )

    structured = f"""
### Step 8：创建部署标记

- 写入以下字段：

```yaml
deployed_at: 2026-07-14T00:00:00Z
agents_version: {manifest.agents_version}
setup_skill_version: {manifest.setup_skill_version}
target_cli: codex
resolver_strategy: project-first
references_dir: .codex/skills/story-setup/references
```
"""
    require(
        not VALIDATOR.sentinel_contract_findings(structured, manifest, Path("fixture.md")),
        "well-formed structured sentinel must pass",
    )
    incomplete = structured.replace("target_cli: codex\n", "")
    require(
        "setup-sentinel-fields"
        in finding_codes(VALIDATOR.sentinel_contract_findings(incomplete, manifest, Path("fixture.md"))),
        "missing generated sentinel fields must fail",
    )


def test_upgrading_version_contract() -> None:
    manifest = repository_manifest()
    structured = f"""
## 当前版本

- `setup_skill_version: {manifest.setup_skill_version}`
- `agents_version: {manifest.agents_version}`

## 下一节
"""
    require(not VALIDATOR.upgrading_version_findings(structured, manifest, Path("UPGRADING.md")), "valid UPGRADING passes")
    scattered = f"setup_skill_version: {manifest.setup_skill_version}, agents_version: {manifest.agents_version}"
    require(
        "upgrading-current-version"
        in finding_codes(VALIDATOR.upgrading_version_findings(scattered, manifest, Path("UPGRADING.md"))),
        "scattered version strings must not satisfy current-version bullets",
    )
    stale_step = structured + f"\n确认 `.story-deployed` 中为 `agents_version: {manifest.agents_version - 1}`。\n"
    require(
        "upgrading-step-version"
        in finding_codes(VALIDATOR.upgrading_version_findings(stale_step, manifest, Path("UPGRADING.md"))),
        "stale agents_version step line must fail",
    )


def test_spawn_agents_version_pin() -> None:
    manifest = repository_manifest()
    stale = f"读取 `.story-deployed` 的 `agents_version: {manifest.agents_version - 1}`。\n"
    require(
        "spawn-agents-version-pin"
        in finding_codes(VALIDATOR.spawn_version_findings(stale, manifest, Path("fixture.md"))),
        "stale agents_version must fail",
    )
    current = f"读取 `.story-deployed` 的 `agents_version: {manifest.agents_version}`。\n"
    require(
        not VALIDATOR.spawn_version_findings(current, manifest, Path("fixture.md")),
        "current agents_version pin must pass",
    )
    bumped = manifest_with(agents_version=manifest.agents_version + 1)
    stale_paths = flagged_paths(bumped, "spawn-agents-version-pin")
    require(
        stale_paths == set(VALIDATOR.SPAWN_CAPABLE_SKILLS),
        f"agents_version bump must flag all spawn-capable skills, got {sorted(stale_paths)}",
    )


def test_progress_schema_pins_are_repo_wide() -> None:
    current = repository_manifest().progress_schema_version
    stale = flagged_paths(manifest_with(progress_schema_version=current + 1), "progress-schema-version")
    for relative in (
        "skills/story-long-analyze/references/pipeline-ops.md",
        "skills/story-long-analyze/SKILL.md",
        "skills/story-import/references/deep-analysis.md",
        "skills/story-setup/UPGRADING.md",
        "demo/拆文库/盘龙/_progress.md",
    ):
        require(relative in stale, f"{relative} schema_version pin must follow manifest; got {sorted(stale)}")
    require("CHANGELOG.md" not in stale, "CHANGELOG.md history is not pinned")


def test_rubric_parity_guard() -> None:
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
        require(not VALIDATOR.rubric_parity_findings(root), "matching rubric dimensions must pass")
        table, _ = VALIDATOR.rubric_dimension_names(root)
        require(table == ["核心卖点", "标点节奏"], f"only 核心维度 table counts, got {table}")

        build(root, rubric.replace("| 标点节奏 |", "| 标点节奏X |", 1), embedded)
        require(
            finding_codes(VALIDATOR.rubric_parity_findings(root)) == {"rubric-dimension-drift"},
            "dimension only in embedded fallback must fail",
        )
        build(root, rubric, embedded.replace("- 标点节奏：y\n", "", 1))
        require(
            finding_codes(VALIDATOR.rubric_parity_findings(root)) == {"rubric-dimension-drift"},
            "dimension only in quality-rubric.md must fail",
        )
        build(root, rubric, "没有内置 rubric 了\n")
        require(
            finding_codes(VALIDATOR.rubric_parity_findings(root)) == {"rubric-parity-unreadable"},
            "missing embedded rubric must not pass vacuously",
        )


def main() -> int:
    test_manifest_contract()
    test_structured_sentinel_contract()
    test_upgrading_version_contract()
    test_spawn_agents_version_pin()
    test_progress_schema_pins_are_repo_wide()
    test_rubric_parity_guard()
    print("OK: hard runtime contract regressions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
