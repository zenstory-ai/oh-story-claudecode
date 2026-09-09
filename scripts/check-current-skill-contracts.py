#!/usr/bin/env python3
"""Validate the repository's current-only skill and artifact contracts.

The JSON manifest is the single structured inventory for version numbers,
primary benchmark artifacts, and outline sections.  This module deliberately
keeps the older path/legacy guards too, but implements them with scoped file
walks and actionable findings rather than a chain of shell grep calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple


SUPPORTED_MANIFEST_VERSION = 1
EXPECTED_MANIFEST_KEYS = {
    "manifest_version",
    "setup_skill_version",
    "agents_version",
    "topic_decision_phase",
    "progress_schema_version",
    "expected_demo_outline_count",
    "primary_benchmark_artifacts",
    "required_outline_sections",
}
SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ARTIFACT_PATH_RE = re.compile(r"(?:[^/\s]+/)+[^/\s]+\.md")


@dataclass(frozen=True)
class ContractManifest:
    manifest_version: int
    setup_skill_version: str
    agents_version: int
    topic_decision_phase: int
    progress_schema_version: int
    primary_benchmark_artifacts: Tuple[str, ...]
    required_outline_sections: Tuple[Tuple[str, str], ...]
    expected_demo_outline_count: int


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    path: Optional[Path] = None
    line: Optional[int] = None
    excerpt: Optional[str] = None

    def detail(self, repo_root: Path) -> str:
        location = ""
        if self.path is not None:
            try:
                shown = self.path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                shown = self.path
            location = str(shown)
            if self.line is not None:
                location += ":{}".format(self.line)
            location += ": "
        suffix = ""
        if self.excerpt:
            suffix = " [{}]".format(self.excerpt.strip())
        return "{}{}{}".format(location, self.message, suffix)


@dataclass(frozen=True)
class AbsentRule:
    code: str
    label: str
    pattern: str
    relative_roots: Tuple[str, ...]
    # 「静默才禁」豁免：命中行的本地上下文若带显式容忍标记（不阻塞 / [待补充] / 回退 /
    # 只核对 / 记录…），说明是有据可查的旧格式容忍而非静默降级，放行。仅用于旧格式大纲容忍
    # （keep C）；benchmark 回退（drop A/B）的规则不设豁免，静默与显式一律禁。
    exempt_when: Optional[str] = None


LEGACY_RULES = (
    AbsentRule(
        "legacy-progress-branch",
        "no legacy deconstruction/progress branches",
        r"legacy_deconstruction|contract_version[^\n]*legacy|pre-v12|schema v1|lazy migration|schema_migration",
        ("skills",),
    ),
    AbsentRule(
        "old-artifact-prose",
        "no silent old artifact-format downgrade",
        r"旧拆文库|旧版细纲|旧式薄细纲|旧版内部降级标记|早期拆文库格式|兼容旧结构",
        ("skills",),
        # keep C：旧格式大纲/细纲容忍是显式、有据可查的（不阻塞日更、回退读取旧字段、未知写
        # [待补充]、记录到追踪），不是静默降级——带这些标记就放行，只拦无标记的静默兼容措辞。
        exempt_when=r"不阻塞|\[待补充\]|回退|只核对|记录|保留或映射|仍可续写|仍可用|仍要保留",
    ),
    AbsentRule(
        "removed-hook-alias",
        "removed hook alias stays removed",
        r"discover_book_dir\s*\(",
        ("skills/story-setup/references/templates/hooks",),
    ),
    AbsentRule(
        "obsolete-short-benchmark-path",
        "short writing uses only current benchmark paths",
        r"\{短篇标题\}/拆文库/\{书名\}",
        ("skills/story-short-write",),
    ),
    AbsentRule(
        "dotted-demo-workflow-label",
        "shipped demos do not preserve dotted workflow labels",
        r"(?:Step|Phase|Stage)\s*[0-9]+\.[0-9]+",
        ("demo",),
    ),
    AbsentRule(
        "obsolete-topic-decision-acceptance",
        "long analyze does not silently accept obsolete topic-decision contracts",
        r"旧模板或文件坏了|直接跳过，不提示",
        ("skills/story-long-analyze",),
    ),
    AbsentRule(
        "duplicate-adapter-reference-fallback",
        "story-setup deploys one canonical reference path per adapter",
        r"同步复制到\s*`skills/[^`]+`\s*作为 fallback",
        ("skills/story-setup/SKILL.md",),
    ),
    AbsentRule(
        "opencode-old-reference-prefix",
        "OpenCode agents use the deployed skills/ reference path only",
        r"\.opencode/skills/story-setup/references/agent-references/",
        ("skills/story-setup/references/opencode/agents",),
    ),
    AbsentRule(
        "codex-old-reference-prefix",
        "Codex agents use the deployed .codex/skills reference path only",
        r"\.(?:claude|opencode)/skills/story-setup/references/agent-references/|\{项目根\}/skills/story-setup/references/agent-references/",
        ("skills/story-setup/references/codex/agents",),
    ),
    AbsentRule(
        "story-import-self-main-benchmark",
        "story-import never registers the imported work itself as a benchmark",
        r"导入当前书时至少登记自身|主对标书:\s*\{书名\}",
        ("skills/story-import",),
    ),
    AbsentRule(
        "story-import-self-benchmark-copy",
        "story-import keeps imported-work analysis out of benchmark views",
        r"\{项目\}/对标/\{书名\}|\{标题\}/对标/\{书名\}|对标/\{书名\}/剧情",
        ("skills/story-import",),
    ),
    AbsentRule(
        "story-import-import-title-benchmark-target",
        "story-import never copies imported-work analysis into a benchmark target",
        r"拆文库/\{导入书名\}[^\n]{0,160}(?:复制|同步|迁移)[^\n]{0,120}对标|对标/\{导入书名\}",
        ("skills/story-import",),
        exempt_when=r"不得|禁止|严禁|未被|不复制|不属于|不是对标",
    ),
    AbsentRule(
        "story-import-self-benchmark-summary",
        "story-import does not label the imported work's own analysis as a benchmark summary",
        r"对标摘要：\{原书名\}",
        ("skills/story-import",),
    ),
    AbsentRule(
        "story-import-self-benchmark-fields",
        "story-import does not map self-benchmark fields into the imported project's settings",
        r"拆文报告\.md`?\s*的故事核/题材/对标字段",
        ("skills/story-import",),
    ),
    AbsentRule(
        "benchmark-primary-nonblocking-wording",
        "missing benchmark primary artifacts never use a nonblocking fallback",
        r"缺失按原流程，不阻塞",
        ("skills/story-long-write",),
    ),
    AbsentRule(
        "no-benchmark-skips-genre-card",
        "no-benchmark writing still generates the project genre prose card",
        r"无对标[^\n]{0,160}跳过[^\n]{0,80}对标模块/节奏/题材卡/文风召回",
        ("skills/story-long-write",),
    ),
    AbsentRule(
        "style-profile-all-inputs-required",
        "Stage 6 prerequisites follow the explicit degradation matrix",
        r"前置依赖：[^\n]*齐全",
        ("skills/story-long-analyze/references/style-profile-generator.md",),
    ),
    AbsentRule(
        "context-missing-skips-all",
        "single-chapter context follows item-specific missing-file decisions",
        r"按需加载，缺失则跳过",
        ("skills/story-long-write/SKILL.md",),
    ),
    AbsentRule(
        "static-long-word-floor",
        "long-form release uses the outline target and one 90-percent tolerance",
        r"默认最低字数[^\n]*3000\s*字/章|"
        r"长篇写作以章为验证粒度[^\n]*(?:2000|3000)\s*字|"
        r"(?:高速推进|正常节奏|舒缓铺垫|高潮爆发)\s*\|\s*≥\s*(?:2000|3000)\s*字/章",
        (
            "skills/story-long-write/SKILL.md",
            "skills/story-setup/references/templates/agents/narrative-writer.md",
            "skills/story-setup/references/opencode/agents/narrative-writer.md",
            "skills/story-setup/references/codex/agents/narrative-writer.toml",
        ),
    ),
    AbsentRule(
        "broad-chrome-cleanup-doc",
        "browser cleanup docs must not bypass consent with executable-name kills",
        r"pkill[^\n]*(?:Google Chrome|google-chrome|chrome)|"
        r"taskkill[^\n]*/IM\s+chrome\.exe",
        ("skills/browser-cdp/SKILL.md",),
    ),
    AbsentRule(
        "analyze-posix-tmp-sample-path",
        "style sampling stays on a project-relative path Windows python can open",
        r"/tmp/style-sample",
        ("skills/story-long-analyze",),
    ),
    # 文风.md 一旦兼任「书目录是否存在」的探针，缺文风的书就会被判成书不存在：explorer 在
    # 步骤 3 提前返回 benchmark_book_missing，步骤 6 的 profile_missing 变成不可达，
    # 调用方 profile_missing + custom_style 的降级续写分支被整条吞掉。目录存在性只能用
    # 目录下的任意文件探，文风缺失单独归 profile_missing。
    AbsentRule(
        "style-profile-as-book-existence-probe",
        "benchmark book existence is probed by any file under the book dir, never by 文风.md",
        r"(?:优先探|回退探)[^\n]{0,60}\{书名\}/文风\.md|"
        r"Glob\s*`?(?:对标|拆文库)/\*/文风\.md",
        (
            "skills/story-setup/references/templates/agents/story-explorer.md",
            "skills/story-setup/references/opencode/agents/story-explorer.md",
            "skills/story-setup/references/codex/agents/story-explorer.toml",
        ),
    ),
    # 现行字数口径不把语义情节点换算成固定容量；旧合计/Σ 契约会诱导自动补事件凑字。
    AbsentRule(
        "forbidden-outline-numeric-capacity",
        "outline beats never use numeric totals or sigma bands to predict prose capacity",
        r"预算合计|目标字数合计|Σ∈\[章目标",
        (
            "skills/story-long-write/references/workflow-setup.md",
            "skills/story-long-write/references/artifact-protocols.md",
            "skills/story-setup/references/templates/rules/story-outline.md",
            "skills/story-setup/references/templates/agents/story-architect.md",
            "skills/story-setup/references/opencode/agents/story-architect.md",
            "skills/story-setup/references/codex/agents/story-architect.toml",
        ),
        exempt_when=r"不得|禁止|已废弃|旧字段|旧口径",
    ),
)


SPAWN_CAPABLE_SKILLS = (
    "skills/story/SKILL.md",
    "skills/story-deslop/SKILL.md",
    "skills/story-import/SKILL.md",
    "skills/story-long-analyze/SKILL.md",
    "skills/story-long-write/SKILL.md",
    "skills/story-review/SKILL.md",
    "skills/story-short-write/SKILL.md",
)


# 细纲结构容量的 canonical 副本与消费方：逐点只写语义义务，不填数字配额。
OUTLINE_SEMANTIC_CAPACITY_CONSUMERS = (
    "skills/story-long-write/references/workflow-setup.md",
    "skills/story-long-write/references/artifact-protocols.md",
    "skills/story-setup/references/templates/rules/story-outline.md",
)


PRIMARY_GAP_TERMS = (
    "module_missing",
    "rhythm_missing",
    "missing_primary_contract",
    "主产物",
    "权威文件",
    "主文件",
)
MISSING_STATE_RE = r"(?:缺失|不存在|未找到|找不到|为\s*(?:true|真)|:\s*true)"
SUBSTITUTE_SOURCE_RE = re.compile(
    r"章节(?:/\*|/第[^\s`，。；;]*)?_?摘要(?:\.md)?|第[^\s`，。；;]*章_摘要(?:\.md)?|"
    r"拆文报告(?:\.md)?|故事线(?:\.md)?",
    re.IGNORECASE,
)
SUBSTITUTE_ACTION_RE = re.compile(
    r"回退|fallback|改读|转读|读取|使用|采用|改用|替代|代替|顶替|补足|补齐|拼出|兜底|"
    r"substitut(?:e|ion)",
    re.IGNORECASE,
)
PROHIBITION_RE = re.compile(
    r"不得|禁止|严禁|不允许|不可|不要|不能|不应|must\s+not|do\s+not|never",
    re.IGNORECASE,
)


def primary_term_pattern(primary_artifacts: Sequence[str]) -> str:
    """Build artifact terms from the manifest, including common local shorthand."""

    terms = set(PRIMARY_GAP_TERMS)
    for artifact in primary_artifacts:
        normalized = artifact.replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        for value in (normalized, basename):
            terms.add(value)
            if value.endswith(".md"):
                terms.add(value[:-3])
    return "(?:{})".format(
        "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_manifest(path: Path) -> Tuple[Optional[ContractManifest], List[Finding]]:
    findings: List[Finding] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [Finding("manifest-missing", "current contract manifest is missing", path)]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [Finding("manifest-invalid-json", "cannot parse manifest: {}".format(exc), path)]

    if not isinstance(raw, dict):
        return None, [Finding("manifest-type", "manifest root must be a JSON object", path)]

    keys = set(raw)
    for missing in sorted(EXPECTED_MANIFEST_KEYS - keys):
        findings.append(Finding("manifest-key-missing", "missing manifest key: {}".format(missing), path))
    for unknown in sorted(keys - EXPECTED_MANIFEST_KEYS):
        findings.append(Finding("manifest-key-unknown", "unknown manifest key: {}".format(unknown), path))

    if "manifest_version" in raw:
        if not _is_int(raw["manifest_version"]):
            findings.append(Finding("manifest-value-type", "manifest_version has the wrong type", path))
        elif raw["manifest_version"] != SUPPORTED_MANIFEST_VERSION:
            findings.append(
                Finding(
                    "manifest-version-unsupported",
                    "manifest_version must be {}, got {}".format(
                        SUPPORTED_MANIFEST_VERSION, raw["manifest_version"]
                    ),
                    path,
                )
            )

    setup_version = raw.get("setup_skill_version")
    if not isinstance(setup_version, str):
        if "setup_skill_version" in raw:
            findings.append(Finding("manifest-value-type", "setup_skill_version has the wrong type", path))
    elif not SEMVER_RE.fullmatch(setup_version):
        findings.append(Finding("manifest-value-format", "setup_skill_version must be x.y.z", path))

    for key in (
        "agents_version",
        "topic_decision_phase",
        "progress_schema_version",
        "expected_demo_outline_count",
    ):
        if key not in raw:
            continue
        if not _is_int(raw[key]):
            findings.append(Finding("manifest-value-type", "{} has the wrong type".format(key), path))
        elif raw[key] < 1:
            findings.append(Finding("manifest-value-range", "{} must be a positive integer".format(key), path))

    artifacts = raw.get("primary_benchmark_artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        findings.append(Finding("manifest-artifact-type", "primary_benchmark_artifacts must be a string array", path))
    elif not artifacts:
        findings.append(Finding("manifest-artifact-empty", "primary_benchmark_artifacts must not be empty", path))
    elif len(set(artifacts)) != len(artifacts):
        findings.append(Finding("manifest-artifact-duplicate", "primary_benchmark_artifacts must be unique", path))
    elif any(ARTIFACT_PATH_RE.fullmatch(item) is None for item in artifacts):
        findings.append(
            Finding(
                "manifest-artifact-format",
                "primary benchmark artifacts must be relative Markdown paths",
                path,
            )
        )

    sections = raw.get("required_outline_sections")
    valid_sections = isinstance(sections, list) and bool(sections) and all(
        isinstance(item, dict)
        and set(item) == {"rule", "demo"}
        and isinstance(item.get("rule"), str) and bool(item["rule"].strip())
        and isinstance(item.get("demo"), str) and bool(item["demo"].strip())
        for item in sections or []
    )
    if not valid_sections:
        findings.append(
            Finding(
                "manifest-outline-type",
                "required_outline_sections must be an array of exact {rule, demo} string objects",
                path,
            )
        )
    elif (
        len({item["rule"] for item in sections}) != len(sections)
        or len({item["demo"] for item in sections}) != len(sections)
    ):
        findings.append(
            Finding(
                "manifest-outline-duplicate",
                "required_outline_sections must use unique rule and demo names",
                path,
            )
        )

    if findings:
        return None, findings

    assert isinstance(artifacts, list)
    assert isinstance(sections, list)
    manifest = ContractManifest(
        manifest_version=raw["manifest_version"],
        setup_skill_version=raw["setup_skill_version"],
        agents_version=raw["agents_version"],
        topic_decision_phase=raw["topic_decision_phase"],
        progress_schema_version=raw["progress_schema_version"],
        primary_benchmark_artifacts=tuple(artifacts),
        required_outline_sections=tuple((item["rule"], item["demo"]) for item in sections),
        expected_demo_outline_count=raw["expected_demo_outline_count"],
    )
    return manifest, []


def iter_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        if root.name not in {"UPGRADING.md", "CHANGELOG.md"}:
            yield root
        return
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in {"UPGRADING.md", "CHANGELOG.md"}:
            continue
        if any(part in {".git", ".omx"} for part in path.parts):
            continue
        yield path


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


# 二进制资产读不出文本是正常的（demo 封面图、__pycache__ 字节码），静默跳过即可；其余文件
# 一律按 UTF-8 文本对待。GBK/cp936 的 Markdown 会让所有内容规则一起失效——regex_hits 拿到
# None 就当「没命中」，检查照样打 [PASS]——所以文本文件解码失败必须是命名失败，不是跳过。
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".mp3",
        ".mp4",
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
    }
)

TEXT_SUFFIXES = frozenset(
    {
        ".cmd",
        ".css",
        ".csv",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".patch",
        ".py",
        ".sh",
        ".svg",
        ".tmpl",
        ".toml",
        ".ts",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)


def is_binary_asset(path: Path) -> bool:
    """二进制资产（封面图、字节码、.DS_Store 之类）读不出文本是正常的。

    后缀白名单之外再看有没有 NUL 字节：这样 `.DS_Store`、无后缀的二进制不会误报，而
    GBK/cp936 的 Markdown（没有 NUL）仍会被判成必须修的文本文件。读不到字节就按文本算，
    宁可报错也不静默放行。
    """
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    # UTF-16 文本同样含大量 NUL；已知文本后缀必须先按契约文本处理，让 UTF-8 解码失败成为
    # 命名错误。NUL sniff 只服务于 .DS_Store / 未知扩展二进制，不能覆盖文件类型事实。
    if path.suffix.lower() in TEXT_SUFFIXES:
        return False
    try:
        return b"\x00" in path.read_bytes()[:8192]
    except OSError:
        return False


def undecodable_source_findings(roots: Sequence[Path]) -> List[Finding]:
    """内容规则扫过的文本文件必须能按 UTF-8 读出来，否则整条规则静默放行。"""
    findings: List[Finding] = []
    seen: set[str] = set()
    for root in roots:
        for path in iter_files(root):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            if read_text(path) is not None:
                continue
            if is_binary_asset(path):
                continue
            findings.append(
                Finding(
                    "unreadable-source-file",
                    "contract guards need UTF-8 text; this file cannot be read as UTF-8",
                    path,
                )
            )
    return findings


def regex_hits(path: Path, pattern: re.Pattern[str]) -> Iterator[Finding]:
    text = read_text(path)
    if text is None:
        return
    for match in pattern.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        excerpt = text.splitlines()[line - 1] if text.splitlines() else ""
        yield Finding("", "", path, line, excerpt)


def check_absent_rule(repo_root: Path, rule: AbsentRule) -> List[Finding]:
    compiled = re.compile(rule.pattern)
    exempt = re.compile(rule.exempt_when) if rule.exempt_when else None
    findings: List[Finding] = []
    for relative_root in rule.relative_roots:
        root = repo_root / relative_root
        for path in iter_files(root):
            for hit in regex_hits(path, compiled):
                if exempt is not None:
                    # 只看命中行本身：显式容忍标记须与旧格式措辞同处一行才算「有据可查」，
                    # 避免相邻的静默降级借上一行的标记蒙混过关
                    if exempt.search(hit.excerpt):
                        continue
                findings.append(
                    Finding(rule.code, rule.label, hit.path, hit.line, hit.excerpt)
                )
    return findings


# 列表项与表格行都是「一条独立记录」：条件与动作要在同一条记录（或它的上级）里才算一件事。
BLOCK_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]\s+|[0-9]+[.)]\s+|\|)")


def _indent_width(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def _block_item_indent(line: str) -> Optional[int]:
    """列表项 / 表格行返回其缩进；普通正文行返回 None。"""
    match = BLOCK_ITEM_RE.match(line)
    if match is None:
        return None
    return len(match.group(1).expandtabs(4))


def logical_bullet_context(lines: Sequence[str], index: int) -> str:
    """Return the hit line plus the branch that actually governs it.

    同一逻辑条目 = 命中行本身 + 它所属条目的续行 + 缩进更浅的上级条目或列表/表格引导句。
    条件常写在上级（`任一主产物缺失时：` 后跟缩进子项或表格行），必须读得到；但同级兄弟条目
    彼此是独立契约，相邻的 fail-fast 条目不得把「主产物缺失」借给本行——否则「两个主产物都
    存在时读取 `拆文报告.md`」这类正确文档会被误判成静默降级。不跨空行与标题。
    """
    parts = [lines[index]]
    own_item_indent = _block_item_indent(lines[index])
    threshold = (
        own_item_indent if own_item_indent is not None else _indent_width(lines[index])
    )
    cursor = index - 1
    while cursor >= 0:
        candidate = lines[cursor]
        if not candidate.strip() or candidate.lstrip().startswith("#"):
            break
        item_indent = _block_item_indent(candidate)
        indent = item_indent if item_indent is not None else _indent_width(candidate)
        # 上级条目（缩进更浅）或同层引导句/续行：条件对整棵子树生效，收进上下文。
        # 其余是同级、更深的兄弟条目及其续行，与命中行无关；跳过但继续往上找上级。
        if indent < threshold or (item_indent is None and indent <= threshold):
            parts.insert(0, candidate)
            threshold = indent
        cursor -= 1
    return "\n".join(parts)


def semantic_primary_fallback_findings(
    text: str,
    path: Path,
    primary_artifacts: Sequence[str],
) -> List[Finding]:
    """Find positive fallback branches for missing primary benchmark artifacts.

    Detection is intentionally local: a substitute source/action must occur in
    the same line, and the missing-primary condition must be in that line or in
    the bullet branch that governs it (its own continuation plus shallower
    parents).  Sibling bullets are independent contracts and never lend their
    condition.  Explicit negative clauses such as "不得以拆文报告代替" are accepted.
    """
    findings: List[Finding] = []
    lines = text.splitlines()
    primary_terms = primary_term_pattern(primary_artifacts)
    primary_missing = re.compile(
        primary_terms + r".{0,50}" + MISSING_STATE_RE,
        re.IGNORECASE,
    )
    primary_missing_reversed = re.compile(
        MISSING_STATE_RE + r".{0,50}" + primary_terms,
        re.IGNORECASE,
    )
    primary_artifact = re.compile(primary_terms, re.IGNORECASE)
    for index, line in enumerate(lines):
        # Bind the action to its source within one natural-language clause.
        # A line may legitimately read a chapter summary and later fall back
        # from a *deep-dive* to another deep-dive; whole-line co-occurrence
        # would incorrectly classify that as a primary-artifact fallback.
        substitute_clauses = [
            clause
            for clause in re.split(r"\）、|[，,；;。！？!?]", line)
            if SUBSTITUTE_SOURCE_RE.search(clause)
            and SUBSTITUTE_ACTION_RE.search(clause)
            and not PROHIBITION_RE.search(clause)
        ]
        if not substitute_clauses:
            continue
        context = logical_bullet_context(lines, index)
        has_missing = bool(
            primary_missing.search(context) or primary_missing_reversed.search(context)
        )
        has_primary = bool(primary_artifact.search(context))
        if not has_missing or not has_primary:
            continue
        findings.append(
            Finding(
                "silent-primary-artifact-fallback",
                "missing primary benchmark artifacts must fail fast; do not substitute summaries, 拆文报告, or 故事线",
                path,
                index + 1,
                substitute_clauses[0].strip() or line,
            )
        )
    return findings


def require_pattern(path: Path, pattern: str, code: str, message: str) -> List[Finding]:
    text = read_text(path)
    if text is None:
        return [Finding(code, "cannot read required file", path)]
    if re.search(pattern, text, re.MULTILINE):
        return []
    return [Finding(code, message, path)]


def spawn_preflight_findings(
    text: str, manifest: ContractManifest, path: Path
) -> List[Finding]:
    """Require every spawn-capable Skill to surface a stale/future agent bundle.

    版本不匹配只提示、不阻断：bump 的原因常常是别的部署物变了而 agent 模板根本没动
    （v23 就只改了 story-explorer），硬闸会让所有人为无关变更付并行代价。真正该降级的
    信号是 agent 文件缺失或运行时不暴露 custom agent。
    """

    current = str(manifest.agents_version)
    required = (
        (r"`agents_version:\s*{}`".format(current), "pin the current agents_version"),
        (
            r"照常按文件存在性检查并 spawn",
            "state that a version mismatch does not block spawn",
        ),
        (
            r"Notice: agents bundle 版本不匹配",
            "surface the version mismatch notice",
        ),
        (
            r"大于 {} 时额外提示先更新 oh-story-claudecode".format(current),
            "tell future deployments to update the package first",
        ),
        (
            r"只有 agent 文件缺失、或运行时不暴露 custom agent 时才降级 solo/direct",
            "reserve the solo/direct fallback for genuinely missing agents",
        ),
    )
    missing = [label for pattern, label in required if re.search(pattern, text) is None]
    if not missing:
        return []
    return [
        Finding(
            "spawn-agents-version-preflight",
            "spawn-capable Skill must use the shared agents_version preflight: {}".format(
                "; ".join(missing)
            ),
            path,
        )
    ]


def rubric_dimension_names(repo_root: Path) -> Tuple[List[str], List[str]]:
    """取 quality-rubric.md「核心维度」表与 SKILL.md 内置 fallback 的维度名。"""

    table: List[str] = []
    rubric_text = read_text(repo_root / "skills/story-review/references/quality-rubric.md") or ""
    in_table = False
    for line in rubric_text.splitlines():
        if line.startswith("| 维度 |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        cell = line.split("|")[1].strip()
        if cell and not set(cell) <= {"-", ":"}:
            table.append(cell)

    embedded: List[str] = []
    skill_text = read_text(repo_root / "skills/story-review/SKILL.md") or ""
    if "通用网文内容 rubric：" in skill_text:
        block = skill_text.split("通用网文内容 rubric：", 1)[1]
        for line in block.splitlines():
            if not line.startswith("- "):
                if embedded:
                    break
                continue
            embedded.append(line[2:].split("：", 1)[0].strip())
    return table, embedded


def rubric_parity_findings(repo_root: Path) -> List[Finding]:
    """内置 fallback rubric 与 quality-rubric.md 必须是同一套维度。

    两者是同一套标准的两个副本：文件可读时用文件，不可读时用内置。漂移过一次
    （文件版独有「任务卡点」，内置版独有「标点节奏」「具体字数表达校验」），
    结果是审查口径取决于路径可读性。手工对齐只管一次，这条断言管以后。
    """

    table, embedded = rubric_dimension_names(repo_root)
    path = repo_root / "skills/story-review/SKILL.md"
    if not table or not embedded:
        return [
            Finding(
                "rubric-parity-unreadable",
                "cannot read both generic rubrics to compare dimensions",
                path,
            )
        ]
    findings = []
    for missing, where in (
        (sorted(set(table) - set(embedded)), "内置 fallback rubric"),
        (sorted(set(embedded) - set(table)), "quality-rubric.md"),
    ):
        if missing:
            findings.append(
                Finding(
                    "rubric-dimension-drift",
                    "generic rubric dimensions drifted: {} missing from {}".format(
                        "、".join(missing), where
                    ),
                    path,
                )
            )
    return findings


def parse_frontmatter_version(path: Path) -> Optional[str]:
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.fullmatch(r"version:\s*([^\s]+)\s*", line)
        if match:
            return match.group(1)
    return None


def extract_current_version_fields(text: str) -> dict[str, str]:
    """Parse version bullets from the `## 当前版本` section only."""
    lines = text.splitlines()
    start: Optional[int] = None
    for index, line in enumerate(lines):
        if re.fullmatch(r"##\s+当前版本\s*", line):
            start = index + 1
            break
    if start is None:
        return {}

    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^#{1,2}\s+", lines[index]):
            end = index
            break

    fields: dict[str, str] = {}
    for line in lines[start:end]:
        match = re.fullmatch(
            r"\s*-\s+`(setup_skill_version|agents_version):\s*([^`]+)`\s*",
            line,
        )
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return fields


def upgrading_version_findings(
    text: str, manifest: ContractManifest, path: Path
) -> List[Finding]:
    fields = extract_current_version_fields(text)
    expected = {
        "setup_skill_version": manifest.setup_skill_version,
        "agents_version": str(manifest.agents_version),
    }
    findings: List[Finding] = []
    for key, value in expected.items():
        actual = fields.get(key)
        if actual != value:
            findings.append(
                Finding(
                    "upgrading-current-version",
                    "UPGRADING current-version bullet {} must be {!r}, got {!r}".format(
                        key, value, actual
                    ),
                    path,
                )
            )
    # 「升级步骤」里让用户核对的版本号是操作指令，bump 时最容易漏（它不在当前版本 bullet
    # 里，也不被部署检查的 TS10 锚点覆盖）。任何写成 `agents_version: N` 的行都必须是当前值。
    for raw in text.splitlines():
        match = re.search(r"`agents_version:\s*(\d+)`", raw)
        if match and match.group(1) != str(manifest.agents_version):
            findings.append(
                Finding(
                    "upgrading-step-version",
                    "UPGRADING step line pins agents_version {!r}, must be {!r}: {}".format(
                        match.group(1), str(manifest.agents_version), raw.strip()
                    ),
                    path,
                )
            )
    return findings


def extract_sentinel_fields(text: str) -> Optional[dict[str, str]]:
    """Parse the generated `.story-deployed` YAML example from its Step section.

    This intentionally ignores version strings in surrounding explanatory
    prose.  The deployment contract is the fenced block following the
    "写入以下字段" instruction inside "创建部署标记".
    """
    lines = text.splitlines()
    section_start: Optional[int] = None
    heading_level = 0
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+Step\s+[A-Za-z0-9]+[：:]\s*创建部署标记\s*$", line)
        if match:
            section_start = index + 1
            heading_level = len(match.group(1))
            break
    if section_start is None:
        return None

    section_end = len(lines)
    for index in range(section_start, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= heading_level:
            section_end = index
            break

    marker_index: Optional[int] = None
    for index in range(section_start, section_end):
        if "写入以下字段" in lines[index]:
            marker_index = index + 1
            break
    if marker_index is None:
        return None

    fence_start: Optional[int] = None
    for index in range(marker_index, section_end):
        if re.match(r"^\s*```(?:ya?ml)?\s*$", lines[index], re.IGNORECASE):
            fence_start = index + 1
            break
    if fence_start is None:
        return None

    fence_end: Optional[int] = None
    for index in range(fence_start, section_end):
        if re.match(r"^\s*```\s*$", lines[index]):
            fence_end = index
            break
    if fence_end is None:
        return None

    fields: dict[str, str] = {}
    for line in lines[fence_start:fence_end]:
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def sentinel_contract_findings(
    text: str, manifest: ContractManifest, path: Path
) -> List[Finding]:
    fields = extract_sentinel_fields(text)
    if fields is None:
        return [
            Finding(
                "setup-sentinel-block",
                "cannot find the structured generated-sentinel fenced block",
                path,
            )
        ]

    required = {
        "deployed_at",
        "agents_version",
        "setup_skill_version",
        "target_cli",
        "resolver_strategy",
        "references_dir",
    }
    findings: List[Finding] = []
    missing = sorted(required - set(fields))
    if missing:
        findings.append(
            Finding(
                "setup-sentinel-fields",
                "generated sentinel is missing fields: {}".format(", ".join(missing)),
                path,
            )
        )

    expected = {
        "agents_version": str(manifest.agents_version),
        "setup_skill_version": manifest.setup_skill_version,
    }
    for key, value in expected.items():
        actual = fields.get(key)
        if actual != value:
            findings.append(
                Finding(
                    "setup-sentinel-field",
                    "generated sentinel {} must be {!r}, got {!r}".format(key, value, actual),
                    path,
                )
            )
    return findings


def _clean_markdown_label(label: str) -> str:
    return label.strip().strip("`*_ ")


def _normalize_rule_field(label: str) -> str:
    label = _clean_markdown_label(label)
    if label.startswith("本章"):
        label = label[2:]
    label = re.sub(r"[（(].*$", "", label).strip()
    return label


def extract_outline_rule_fields(text: str) -> set[str]:
    """Return structured field labels from Rules item 2 (细纲必填项)."""
    lines = text.splitlines()
    start: Optional[int] = None
    for index, line in enumerate(lines):
        if re.match(r"^\s*2\.\s+\*\*细纲必填项\*\*", line):
            start = index + 1
            break
    if start is None:
        return set()

    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^\s*[3-9][0-9]*\.\s+\*\*", lines[index]):
            end = index
            break

    fields: set[str] = set()
    for line in lines[start:end]:
        match = re.match(r"^\s*-\s+(.+?)[：:]", line)
        if match:
            fields.add(_normalize_rule_field(match.group(1)))
    return fields


def outline_rule_contract_findings(
    text: str, manifest: ContractManifest, path: Path
) -> List[Finding]:
    fields = extract_outline_rule_fields(text)
    required = {rule for rule, _ in manifest.required_outline_sections}
    missing = sorted(required - fields)
    if not missing:
        return []
    return [
        Finding(
            "outline-rule-section",
            "outline rule is missing structured blueprint fields: {}".format(", ".join(missing)),
            path,
        )
    ]


def extract_demo_outline_fields(text: str) -> set[str]:
    """Return labels declared as headings or `- field: value` entries."""
    fields: set[str] = set()
    for line in text.splitlines():
        heading = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if heading:
            fields.add(_clean_markdown_label(heading.group(1)))
            continue
        bullet = re.match(r"^\s*-\s+(.+?)[：:]", line)
        if bullet:
            fields.add(_clean_markdown_label(bullet.group(1)))
    return fields


SCHEMA_VERSION_PIN_RE = re.compile(r"schema_version:\s*([0-9]+)")


def progress_schema_pin_findings(repo_root: Path, expected: int) -> List[Finding]:
    """每个字面 `schema_version: N` 锚点都必须是当前续跑契约版本。

    续跑契约同时写在 analyze 的写入/恢复段、import 的当前拆文契约、UPGRADING 当前契约段和
    demo 基准进度文件里。只核对 pipeline-ops.md 会让 bump 之后其余文件静默留在旧版本——技能
    包自相矛盾、续跑拒收自己写出的 `_progress.md`，而 CI 全绿。参照 `agents_version` 的做法
    （见 upgrading_version_findings）：任何写成 `schema_version: N` 的行都必须是当前值。
    仓库根的 CHANGELOG.md 是历史记录，故意不在扫描范围内；版本说明表的 `| 2 | 当前契约… |`
    不写成锚点形式，本规则也不会误伤。
    """
    findings: List[Finding] = []
    paths: List[Path] = []
    for root in (repo_root / "skills", repo_root / "demo"):
        paths.extend(path for path in iter_files(root) if path.suffix.lower() == ".md")
    # iter_files 按名字跳过 UPGRADING.md（历史章节不该被当前值约束），但 `## v21 当前契约`
    # 段里的续跑契约陈述与 agents_version 同理，bump 时必须跟着改。
    paths.append(repo_root / "skills/story-setup/UPGRADING.md")
    for path in paths:
        text = read_text(path)
        if text is None:
            continue
        for line_number, line_text in enumerate(text.splitlines(), start=1):
            for match in SCHEMA_VERSION_PIN_RE.finditer(line_text):
                if int(match.group(1)) == expected:
                    continue
                findings.append(
                    Finding(
                        "progress-schema-version",
                        "every pipeline schema_version must equal {} (found {})".format(
                            expected, match.group(1)
                        ),
                        path,
                        line_number,
                        line_text,
                    )
                )
    return findings


def validate_repository(repo_root: Path, manifest: ContractManifest) -> List[Finding]:
    findings: List[Finding] = []

    scan_roots = [repo_root / "skills", repo_root / "demo"]
    scan_roots.extend(
        repo_root / relative_root
        for rule in LEGACY_RULES
        for relative_root in rule.relative_roots
    )
    findings.extend(undecodable_source_findings(scan_roots))

    for rule in LEGACY_RULES:
        findings.extend(check_absent_rule(repo_root, rule))

    pipeline = repo_root / "skills/story-long-analyze/references/pipeline-ops.md"
    pipeline_text = read_text(pipeline) or ""
    if not SCHEMA_VERSION_PIN_RE.search(pipeline_text):
        findings.append(
            Finding(
                "progress-schema-version",
                "every pipeline schema_version must equal {} (found {})".format(
                    manifest.progress_schema_version, "none"
                ),
                pipeline,
            )
        )
    findings.extend(
        progress_schema_pin_findings(repo_root, manifest.progress_schema_version)
    )
    findings.extend(require_pattern(pipeline, r"章节边界", "chapter-boundary-table", "progress must keep the canonical chapter-boundary table"))

    setup_skill = repo_root / "skills/story-setup/SKILL.md"
    actual_setup_version = parse_frontmatter_version(setup_skill)
    if actual_setup_version != manifest.setup_skill_version:
        findings.append(
            Finding(
                "setup-frontmatter-version",
                "story-setup frontmatter version must be {}, got {!r}".format(
                    manifest.setup_skill_version, actual_setup_version
                ),
                setup_skill,
            )
        )
    setup_text = read_text(setup_skill) or ""
    findings.extend(sentinel_contract_findings(setup_text, manifest, setup_skill))

    for relative in SPAWN_CAPABLE_SKILLS:
        spawn_skill = repo_root / relative
        findings.extend(
            spawn_preflight_findings(
                read_text(spawn_skill) or "", manifest, spawn_skill
            )
        )

    upgrading = repo_root / "skills/story-setup/UPGRADING.md"
    upgrading_text = read_text(upgrading) or ""
    findings.extend(upgrading_version_findings(upgrading_text, manifest, upgrading))

    topic_file = repo_root / "skills/story-long-scan/references/topic-decision.md"
    topic_text = read_text(topic_file) or ""
    topic_match = re.search(r"Phase\s+([0-9]+)[^\n]*产出\s*`选题决策\.md`", topic_text)
    if not topic_match or int(topic_match.group(1)) != manifest.topic_decision_phase:
        findings.append(
            Finding(
                "topic-decision-phase",
                "topic-decision output phase must be {}, got {}".format(
                    manifest.topic_decision_phase,
                    topic_match.group(1) if topic_match else "none",
                ),
                topic_file,
            )
        )
    scan_skill = repo_root / "skills/story-long-scan/SKILL.md"
    findings.extend(
        require_pattern(
            scan_skill,
            r"^#{{2,6}}\s+Phase\s+{}[：:]\s*选题决策\s*$".format(manifest.topic_decision_phase),
            "topic-decision-phase-heading",
            "story-long-scan must expose topic decision as Phase {}".format(manifest.topic_decision_phase),
        )
    )
    for path in iter_files(repo_root / "skills"):
        if path.suffix.lower() != ".md":
            continue
        text = read_text(path) or ""
        for line_number, line_text in enumerate(text.splitlines(), start=1):
            if "选题决策" not in line_text:
                continue
            # 技能名在本包的房子风格是反引号包裹（`story-long-scan` Phase 5），裸 token 匹配
            # 跨不过反引号，会漏掉一半引用；两种写法都要拦。
            for match in re.finditer(
                r"`?story-long-scan`?[\s`]*Phase\s+([0-9]+)", line_text
            ):
                value = int(match.group(1))
                if value == manifest.topic_decision_phase:
                    continue
                findings.append(
                    Finding(
                        "stale-topic-decision-phase-reference",
                        "story-long-scan topic-decision references must use Phase {}".format(
                            manifest.topic_decision_phase
                        ),
                        path,
                        line_number,
                        line_text,
                    )
                )

    findings.extend(rubric_parity_findings(repo_root))

    long_analyze = repo_root / "skills/story-long-analyze/SKILL.md"
    findings.extend(require_pattern(long_analyze, r"invalid_topic_decision_contract", "invalid-topic-contract", "invalid topic-decision artifacts must fail explicitly"))
    # 章节边界表是 Stage 1/2/6 的唯一切片真值：原文开头的目录块会让每个章号命中两次，
    # 不剔就一路错到底。剔除步骤和落表前的连续性校验都必须留在 Stage 0。
    findings.extend(require_pattern(long_analyze, r"先剔掉目录块", "stage0-toc-block-removal", "Stage 0 must drop the leading table-of-contents block before building the chapter table"))
    findings.extend(require_pattern(long_analyze, r"落表前校验章号连续", "stage0-chapter-table-validation", "Stage 0 must validate chapter numbers before writing the boundary table"))
    explorer = repo_root / "skills/story-setup/references/templates/agents/story-explorer.md"
    findings.extend(require_pattern(explorer, r"missing_primary_contract", "explorer-primary-failure", "story-explorer must fail closed on missing current benchmark artifacts"))
    findings.extend(require_pattern(explorer, r"repair_action", "explorer-repair-action", "story-explorer must return an explicit repair action"))

    long_write = repo_root / "skills/story-long-write/SKILL.md"
    for artifact in manifest.primary_benchmark_artifacts:
        findings.extend(
            require_pattern(
                long_write,
                re.escape(artifact),
                "long-write-primary-artifact",
                "long writing must require {}".format(artifact),
            )
        )

    for relative in (
        "skills/story-import/SKILL.md",
        "skills/story-import/references/structure-mapping-long.md",
        "skills/story-import/references/structure-mapping-short.md",
    ):
        import_contract = repo_root / relative
        findings.extend(
            require_pattern(
                import_contract,
                r"\{导入书名\}",
                "story-import-import-title-boundary",
                "story-import must name the imported work independently",
            )
        )
        findings.extend(
            require_pattern(
                import_contract,
                r"\{对标书名\}",
                "story-import-benchmark-title-boundary",
                "story-import must name external benchmarks independently",
            )
        )

    # 长篇的「对标发现」随 Phase 1-3 从 SKILL.md 搬进 workflow-setup.md（#269 减无条件加载），
    # 断言跟着内容走；短篇对标发现位于独立的 benchmark-recall.md。
    for relative in (
        "skills/story-long-write/references/workflow-setup.md",
        "skills/story-short-write/references/benchmark-recall.md",
        "skills/story-long-write/references/cross-book-recall.md",
        "skills/story-short-write/references/cross-book-recall.md",
    ):
        benchmark_discovery = repo_root / relative
        findings.extend(
            require_pattern(
                benchmark_discovery,
                r"排除[^\n]*当前[^\n]*(?:拆文库|作品|正文)",
                "benchmark-discovery-excludes-current-work",
                "benchmark discovery must exclude the current imported work",
            )
        )

    explorer_template = repo_root / "skills/story-setup/references/templates/agents/story-explorer.md"
    findings.extend(
        require_pattern(
            explorer_template,
            r"self_benchmark_ignored",
            "explorer-self-benchmark-gap",
            "story-explorer must report and ignore self-benchmark candidates",
        )
    )
    # 「书在但缺文风」必须落到 profile_missing，不能被 benchmark_book_missing 吞掉——
    # 前者调用方可按 custom_style 降级续写，后者是硬停。两者混用是功能回退，不是措辞问题。
    findings.extend(
        require_pattern(
            explorer_template,
            r"对标/\{书名\}/\*\*/\*",
            "explorer-book-dir-probe",
            "story-explorer must probe book-dir validity with any file under it, not 文风.md",
        )
    )
    findings.extend(
        require_pattern(
            explorer_template,
            r"不得改填\s*`?benchmark_book_missing",
            "explorer-profile-missing-distinct",
            "story-explorer must keep profile_missing distinct from benchmark_book_missing",
        )
    )
    findings.extend(
        require_pattern(
            repo_root / "skills/story-long-write/references/workflow-daily.md",
            r"profile_missing[^\n]{0,60}custom_style[^\n]{0,40}继续",
            "daily-profile-missing-custom-style",
            "workflow-daily must keep the profile_missing + custom_style continuation branch",
        )
    )

    # 三处消费方都必须明确取消逐点字数，避免旧 Σ 契约从任一部署面回流。
    for relative in OUTLINE_SEMANTIC_CAPACITY_CONSUMERS:
        findings.extend(
            require_pattern(
                repo_root / relative,
                r"不(?:填写|含)逐点字数",
                "outline-semantic-capacity-parity",
                "outline beats must remain semantic and must not carry per-beat word quotas",
            )
        )

    outline_rule = repo_root / "skills/story-setup/references/templates/rules/story-outline.md"
    outline_rule_text = read_text(outline_rule) or ""
    findings.extend(
        outline_rule_contract_findings(outline_rule_text, manifest, outline_rule)
    )

    demo_root = repo_root / "demo/拆文库/盘龙"
    for artifact in manifest.primary_benchmark_artifacts:
        artifact_path = demo_root / artifact
        try:
            has_content = artifact_path.is_file() and artifact_path.stat().st_size > 0
        except OSError:
            has_content = False
        if not has_content:
            findings.append(
                Finding("demo-primary-artifact", "demo deconstruction is missing non-empty {}".format(artifact), artifact_path)
            )

    outline_dir = repo_root / "demo/长篇/让你管账号，你高燃混剪炸全网/大纲"
    outlines = sorted(outline_dir.glob("细纲_第*.md"))
    if len(outlines) != manifest.expected_demo_outline_count:
        findings.append(
            Finding(
                "demo-outline-count",
                "expected {} demo chapter outlines, found {}".format(
                    manifest.expected_demo_outline_count, len(outlines)
                ),
                outline_dir,
            )
        )
    for outline in outlines:
        text = read_text(outline) or ""
        declared_fields = extract_demo_outline_fields(text)
        missing = [
            demo
            for _, demo in manifest.required_outline_sections
            if demo not in declared_fields
        ]
        if missing:
            findings.append(
                Finding(
                    "demo-outline-section",
                    "demo outline is missing current blueprint sections: {}".format(", ".join(missing)),
                    outline,
                )
            )

    for path in iter_files(repo_root / "skills"):
        if path.suffix.lower() != ".md":
            continue
        text = read_text(path)
        if text is not None:
            findings.extend(
                semantic_primary_fallback_findings(
                    text,
                    path,
                    manifest.primary_benchmark_artifacts,
                )
            )

    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().with_name("current-contract.json"),
        help="current contract manifest",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    manifest, manifest_findings = load_manifest(args.manifest.resolve())

    print("Current Skill Contract Check")
    print("============================")
    if manifest_findings:
        for finding in manifest_findings:
            print("  [FAIL] {}: {}".format(finding.code, finding.detail(repo_root)))
        print("\nResult: {} failure(s)".format(len(manifest_findings)))
        return 1

    assert manifest is not None
    print("  [PASS] manifest schema and declared release values")
    findings = validate_repository(repo_root, manifest)
    if findings:
        for finding in findings:
            print("  [FAIL] {}: {}".format(finding.code, finding.detail(repo_root)))
        print("\nResult: {} failure(s)".format(len(findings)))
        return 1

    print("  [PASS] legacy/path guards")
    print("  [PASS] version, phase, progress, and artifact contracts")
    print("  [PASS] primary-artifact fallback semantics")
    print("  [PASS] demo primary artifacts and {} outlines".format(manifest.expected_demo_outline_count))
    print("\nResult: all current-contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
