#!/usr/bin/env python3
"""Regression tests for the structured skill Markdown checker."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts/static-check.py"
LAUNCHER = REPO_ROOT / "scripts/static-check.sh"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def build_agent_catalog(root: Path) -> None:
    write(
        root / "skills/story-setup/references/templates/agents/helper.md",
        "---\nname: helper\ndescription: helper\n---\n",
    )
    write(
        root / "skills/story-setup/SKILL.md",
        "---\nname: story-setup\ndescription: setup\n---\n# Setup\n"
        "Use `references/templates/agents/`.\n",
    )


def test_valid_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-valid-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo skill\n---\n"
            "# Demo\n\n"
            "Read [the guide](references/guide.md#details).\n\n"
            "Use `references/data/` and spawn `subagent_type: \"helper\"`.\n",
        )
        write(
            root / "skills/demo/references/guide.md",
            "# Guide\n\n## Details\n\n"
            "Continue with [nested details](nested.md#nested-section).\n",
        )
        write(
            root / "skills/demo/references/nested.md",
            "# Nested\n\n## Nested section\n",
        )
        write(root / "skills/demo/references/data/schema.json", "{}\n")

        result = run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Total: 2 | Pass: 2 | Fail: 0 | Warn: 0" in result.stdout


def test_structural_failures_are_not_hidden_by_prose() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-invalid-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/broken/SKILL.md",
            "---\nname: broken\n---\n"
            "# Broken\n\n"
            "This prose contains description: but frontmatter does not.\n\n"
            "[missing](references/missing.md)\n\n"
            "[bad anchor](references/guide.md#does-not-exist)\n\n"
            "`subagent_type: \"ghost\"`\n",
        )
        write(
            root / "skills/broken/references/guide.md",
            "# Guide\n\n## Real section\n\n详见 SKILL.md Phase 2。\n",
        )
        write(root / "skills/broken/references/orphan.md", "# Orphan\n")

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        for code in (
            "frontmatter-description",
            "broken-link-path",
            "broken-link-anchor",
            "unknown-agent",
            "unlinked-skill-section",
        ):
            assert f"[{code}]" in result.stdout, result.stdout
        assert "[dead-reference]" in result.stdout


def test_local_paths_stay_in_skill_and_repository_scope() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-path-scope-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "Read [the guide](references/guide.md).\n",
        )
        write(
            root / "skills/demo/references/guide.md",
            "# Guide\n\n"
            "A root-relative host path must not pass: [host](/etc/passwd).\n\n"
            "A traversal must fail: [escape](../../../../../../etc/passwd).\n\n"
            "A cross-skill link must fail: "
            "[other](../../other/references/output-contract.md).\n\n"
            "A bare path stays in this skill: `output-contract.md`.\n",
        )
        write(
            root / "skills/other/SKILL.md",
            "---\nname: other\ndescription: Other\n---\n# Other\n\n"
            "Read `references/output-contract.md`.\n",
        )
        write(
            root / "skills/other/references/output-contract.md",
            "# Other output contract\n",
        )

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "[broken-link-path]" in result.stdout, result.stdout
        assert "[local-path-outside-root]" in result.stdout, result.stdout
        assert "[cross-skill-reference]" in result.stdout, result.stdout
        assert "[broken-inline-path]" in result.stdout, result.stdout


def test_markdown_links_do_not_use_fallback_locations() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-link-exact-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "Read [the guide](references/guide.md).\n",
        )
        write(
            root / "skills/demo/references/guide.md",
            "# Guide\n\n[wrong relative target](duplicate.md)\n",
        )
        write(root / "skills/demo/duplicate.md", "# Same basename, wrong directory\n")

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "[broken-link-path]" in result.stdout, result.stdout
        assert "references/duplicate.md" in result.stdout, result.stdout


def test_fenced_examples_do_not_leak_into_validation() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-fence-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "```markdown\n"
            "```python\n"
            "[example only](references/missing.md)\n"
            "`subagent_type: \"ghost\"`\n"
            "```\n",
        )

        result = run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[broken-link-path]" not in result.stdout, result.stdout
        assert "[unknown-agent]" not in result.stdout, result.stdout


def test_cjk_joined_globs_are_not_misread_as_emphasis_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-cjk-glob-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "批量读取 references/*.md与references/*.json，再汇总结果。\n",
        )
        write(root / "skills/demo/references/example.md", "# Example\n")
        write(root / "skills/demo/references/example.json", "{}\n")

        result = run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[broken-link-path]" not in result.stdout, result.stdout


def test_cjk_joined_globs_validate_every_named_path() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-cjk-missing-glob-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "批量读取 references/*.md与assets/missing/*.json，再汇总结果。\n",
        )
        write(root / "skills/demo/references/example.md", "# Example\n")

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "assets/missing/" in result.stdout, result.stdout
        assert "[broken-inline-path]" in result.stdout, result.stdout


def test_fullwidth_paren_agent_refs_are_validated() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-fullwidth-agent-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "**Agent 1: helper**（subagent_type: helper）\n\n"
            "**Agent 2: phantom**（subagent_type: phantom）\n",
        )

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "unknown subagent_type 'phantom'" in result.stdout, result.stdout
        assert "unknown subagent_type 'helper'" not in result.stdout, result.stdout
        assert result.stdout.count("[unknown-agent]") == 1, result.stdout


def test_cross_skill_paths_in_runtime_scripts_fail() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-cross-script-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "Read [the local guide](references/guide.md).\n",
        )
        write(
            root / "skills/demo/references/guide.md",
            "# Guide\n\nRead [other][foreign].\n\n"
            "[foreign]: ../../story-setup/SKILL.md\n",
        )
        write(
            root / "skills/demo/scripts/runner.js",
            "// Never invoke story-setup/scripts/helper.py from this skill.\n",
        )
        write(
            root / "skills/demo/scripts/runner.cmd",
            "@copy skills\\story-setup\\SKILL.md out.md\r\n",
        )

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "[cross-skill-reference]" in result.stdout, result.stdout
        assert "scripts/runner.js:1" in result.stdout, result.stdout
        assert "scripts/runner.cmd:1" in result.stdout, result.stdout


def test_foundation_browser_cdp_reference_passes() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-foundation-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/browser-cdp/SKILL.md",
            "---\nname: browser-cdp\ndescription: Browser infrastructure\n---\n"
            "# Browser CDP\n",
        )
        write(
            root / "skills/browser-cdp/scripts/setup-cdp-chrome.js",
            "console.log('setup');\n",
        )
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "Run `browser-cdp/scripts/setup-cdp-chrome.js` first.\n",
        )

        result = run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[cross-skill-reference]" not in result.stdout, result.stdout


def test_external_urls_are_not_cross_skill_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-external-url-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "See [remote docs](https://example.test/repo/skills/story-setup/SKILL.md), "
            "[uppercase HTTPS](HTTPS://example.test/repo/skills/story-setup/SKILL.md), "
            "and [FTP](FTP://example.test/repo/skills/story-setup/SKILL.md).\n\n"
            "源码见 https://example.test/repo/skills/story-setup/references/agent-references/craft.md\n\n"
            "参考 <https://example.test/docs/references/guide.md> 的说明。\n\n"
            "命令 `curl https://example.test/docs/references/guide.md`，"
            "文档 `https://example.test/docs/guide.md`。\n",
        )
        write(
            root / "skills/demo/scripts/runner.js",
            "const docs = 'https://example.test/repo/story-setup/scripts/helper.js';\n",
        )

        result = run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[cross-skill-reference]" not in result.stdout, result.stdout
        assert "[broken-inline-path]" not in result.stdout, result.stdout


def test_unlinked_section_covers_cjk_without_spaces() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-unlinked-cjk-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n## 阶段二流程\n\n"
            "Read [the guide](references/guide.md).\n",
        )
        write(
            root / "skills/demo/references/guide.md",
            "# Guide\n\n详见SKILL.md的阶段二流程。\n\n"
            "榜单清单与 URL 见 SKILL.md「起点采集目标」表。\n",
        )

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "[unlinked-skill-section]" in result.stdout, result.stdout
        assert "详见SKILL.md的阶段二流程" in result.stdout, result.stdout
        # 括号里原样引用标题不是模糊猜测，不在本规则范围内
        assert "起点采集目标" not in result.stdout, result.stdout
        assert result.stdout.count("[unlinked-skill-section]") == 1, result.stdout


def test_templates_and_web_assets_are_scanned_for_cross_skill_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-asset-scan-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "Deploy `references/CLAUDE.md.tmpl` and `assets/index.html`, "
            "patch with `references/opencode.json.patch`, style with `assets/styles.css`.\n",
        )
        write(
            root / "skills/demo/references/CLAUDE.md.tmpl",
            "# 项目约定\n\n必读：story-setup/references/agent-references/craft.md。\n",
        )
        write(
            root / "skills/demo/references/opencode.json.patch",
            "+  \"instructions\": \"story-setup/references/generic/AGENTS.md.tmpl\"\n",
        )
        write(
            root / "skills/demo/assets/index.html",
            "<!-- see story-setup/references/templates/agents/helper.md -->\n",
        )
        write(
            root / "skills/demo/assets/styles.css",
            "/* derived from story-setup/assets/base.css */\n",
        )

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        for asset in (
            "references/CLAUDE.md.tmpl:3",
            "references/opencode.json.patch:1",
            "assets/index.html:1",
            "assets/styles.css:1",
        ):
            assert f"[cross-skill-reference] skills/demo/{asset}" in result.stdout, result.stdout


def test_emphasized_paths_are_still_existence_checked() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-emphasis-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "参见 **references/definitely-missing.md** 获取细节。\n\n"
            "题材卡在 references/cards/*.md 与 references/data/*.json 里，按需加载。\n\n"
            "Read [the guide](references/guide.md).\n",
        )
        write(root / "skills/demo/references/guide.md", "# Guide\n")
        write(root / "skills/demo/references/cards/都市.md", "# 都市\n")
        write(root / "skills/demo/references/data/rules.json", "{}\n")

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert (
            "[broken-inline-path] skills/demo/SKILL.md:7" in result.stdout
        ), result.stdout
        assert "references/definitely-missing.md" in result.stdout, result.stdout
        # 真通配符仍按父目录校验，不能因为剥强调符而被截断成断链
        assert result.stdout.count("[broken-inline-path]") == 1, result.stdout
        assert "[broken-inline-path] skills/demo/SKILL.md:9" not in result.stdout, result.stdout


def test_wildcard_mentions_do_not_hide_dead_references() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-wildcard-reach-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "只读取本 Skill 的 `demo/references/*`，不要跨 skill。\n\n"
            "Read [the guide](references/guide.md).\n",
        )
        write(root / "skills/demo/references/guide.md", "# Guide\n")
        write(root / "skills/demo/references/orphan.md", "# Orphan\n")
        write(root / "skills/demo/references/nested/deep-orphan.md", "# Deep orphan\n")

        result = run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[dead-reference] skills/demo/references/orphan.md" in result.stdout, result.stdout
        assert (
            "[dead-reference] skills/demo/references/nested/deep-orphan.md" in result.stdout
        ), result.stdout
        assert "[dead-reference] skills/demo/references/guide.md" not in result.stdout, result.stdout


def test_brace_enumerations_name_each_file() -> None:
    with tempfile.TemporaryDirectory(prefix="story-static-brace-enum-") as tmp:
        root = Path(tmp)
        build_agent_catalog(root)
        write(
            root / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: Demo\n---\n# Demo\n\n"
            "平台 rubric：`references/rubrics/{fanqie,qidian,zhihu}.md`\n",
        )
        write(root / "skills/demo/references/rubrics/fanqie.md", "# fanqie\n")
        write(root / "skills/demo/references/rubrics/qidian.md", "# qidian\n")
        write(root / "skills/demo/references/rubrics/orphan.md", "# orphan\n")

        result = run(root)
        assert result.returncode == 1, result.stdout + result.stderr
        # 点名枚举展开成逐个路径：缺失成员是断链，命中成员算已引用，未点名的仍是死引用
        assert "references/rubrics/zhihu.md" in result.stdout, result.stdout
        assert "[broken-inline-path]" in result.stdout, result.stdout
        assert (
            "[dead-reference] skills/demo/references/rubrics/orphan.md" in result.stdout
        ), result.stdout
        for reached in ("fanqie.md", "qidian.md"):
            assert f"[dead-reference] skills/demo/references/rubrics/{reached}" not in result.stdout, (
                result.stdout
            )


def test_launcher_reports_missing_git_repository() -> None:
    bash = shutil.which("bash")
    if bash is None:
        print("SKIP: bash unavailable, launcher guard not exercised")
        return
    with tempfile.TemporaryDirectory(prefix="story-static-launcher-") as tmp:
        outside = Path(tmp) / "not-a-repo"
        outside.mkdir()
        launcher = outside / "static-check.sh"
        launcher.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")

        proc = subprocess.run(
            [bash, str(launcher)],
            cwd=str(outside),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        # `set -e` 曾让裸赋值直接中断脚本：退出码 128 且无任何提示
        assert proc.returncode == 1, f"exit={proc.returncode}\n{proc.stdout}{proc.stderr}"
        assert "not in a git repository" in proc.stderr, proc.stdout + proc.stderr


def main() -> None:
    test_valid_contract()
    test_structural_failures_are_not_hidden_by_prose()
    test_local_paths_stay_in_skill_and_repository_scope()
    test_markdown_links_do_not_use_fallback_locations()
    test_fenced_examples_do_not_leak_into_validation()
    test_fullwidth_paren_agent_refs_are_validated()
    test_cross_skill_paths_in_runtime_scripts_fail()
    test_foundation_browser_cdp_reference_passes()
    test_external_urls_are_not_cross_skill_paths()
    test_unlinked_section_covers_cjk_without_spaces()
    test_templates_and_web_assets_are_scanned_for_cross_skill_paths()
    test_emphasized_paths_are_still_existence_checked()
    test_cjk_joined_globs_are_not_misread_as_emphasis_paths()
    test_cjk_joined_globs_validate_every_named_path()
    test_wildcard_mentions_do_not_hide_dead_references()
    test_brace_enumerations_name_each_file()
    test_launcher_reports_missing_git_repository()
    print("PASS: structured static-check regression")


if __name__ == "__main__":
    main()
