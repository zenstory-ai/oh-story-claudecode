#!/usr/bin/env python3
"""Unified repository linter merging real-breakage guards.

Sub-checks (--only <check>, or all 4 by default):
  static      Skill Markdown frontmatter, links/anchors, agents, cross-skill isolation, dead refs.
  contracts   Hard runtime contract pins from current-contract.json (versions, schema, demo, rubric).
  shared      Shared runtime assets, shared references, and deployed agent-reference consumers.
  numbering   Dotted workflow label guard (Step 1.5 / Phase 2.1 / Stage 0.5) in skills/**/*.md.
  agent-refs  (Standalone subset of `shared`) Deployed agent-reference consumer checks only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple
from urllib.parse import unquote


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = SCRIPT_DIR.parent

# ============================================================================
# 1. Static Skill Integrity (absorbed from static-check.py)
# ============================================================================

ATX_HEADING_RE = re.compile(r"^[ ]{0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$")
OPEN_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
EMPHASIS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?P<marker>\*{1,2})"
    r"(?P<path>(?:[a-z0-9_-]+/)?(?:references|scripts|assets)/[^\s*]+)"
    r"(?P=marker)(?![A-Za-z0-9_./-])"
)
SKILL_PATH_PREFIX = r"(?:[a-z0-9_-]+/)?(?:references|scripts|assets)/"
SKILL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?P<path>"
    + SKILL_PATH_PREFIX
    + r"(?:(?!(?:与|和|及|、)"
    + SKILL_PATH_PREFIX
    + r")[^\s`\"')\]><「（，。；：、])+)"
)
ASCII_MD_RE = re.compile(r"^[a-z0-9_-]+\.md$")
INLINE_MD_PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9._-]+/)*[a-z0-9_-]+\.md)(?=$|[^A-Za-z0-9_.-])"
)
AGENT_REF_RES = (
    re.compile(r"subagent_type\s*:\s*\"([a-z][a-z0-9_-]*)\""),
    re.compile(r"subagent_type\s*=\s*\"([a-z][a-z0-9_-]*)\""),
    re.compile(r"[（(]subagent_type\s*[:：]\s*\"?([a-z][a-z0-9_-]*)\"?\s*[)）]"),
)
UNLINKED_SECTION_RE = re.compile(
    r"(?:见|参考|参见|详见)\s*SKILL\.md\s*"
    r"[^\s，。；;、（）()「」『』【】《》〈〉\[\]{}<>#|\"'“”‘’]"
    r"[^，。；;\n]*"
)
EXTERNAL_SCHEMES = ("http://", "https://", "ftp://", "mailto:", "data:", "tel:")
DEPLOYED_RUNTIME_PREFIXES = (".claude/", ".codex/", ".opencode/", ".agents/")
FOUNDATION_SKILL_REFERENCES = frozenset({"browser-cdp"})
CHANGELOG_DOCS = frozenset({"UPGRADING.md", "CHANGELOG.md"})
EXTERNAL_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"'`]+")
BRACE_LIST_RE = re.compile(r"\{([^{}/]*,[^{}/]*)\}")
SKILL_TEXT_SUFFIXES = {
    ".cmd", ".css", ".html", ".js", ".json", ".md", ".mjs",
    ".patch", ".py", ".sh", ".tmpl", ".toml", ".ts", ".yaml", ".yml",
}


@dataclass(frozen=True)
class SourceRef:
    line: int
    raw: str
    kind: str


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    path: Path
    line: int
    message: str


@dataclass
class Document:
    path: Path
    anchors: set[str] = field(default_factory=set)
    refs: list[SourceRef] = field(default_factory=list)
    agent_refs: list[tuple[int, str]] = field(default_factory=list)
    unlinked_sections: list[tuple[int, str]] = field(default_factory=list)


def display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def inside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def skill_owner(path: Path, root: Path) -> str | None:
    try:
        relative = path.resolve().relative_to((root / "skills").resolve())
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


def markdown_slug(title: str) -> str:
    result: list[str] = []
    for char in title.strip().lower():
        category = unicodedata.category(char)
        if char.isspace():
            result.append("-")
        elif char in "-_" or category[0] in {"L", "M", "N"}:
            result.append(char)
    return "".join(result)


def strip_link_title(target: str) -> str:
    target = target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    match = re.match(r"^(.*?)(?:\s+[\"'].*[\"'])?$", target)
    return (match.group(1) if match else target).strip()


def is_external_ref(raw: str) -> bool:
    return raw.strip().lower().startswith(EXTERNAL_SCHEMES)


def strip_inline_markup(line: str) -> str:
    line = LINK_RE.sub("", line)
    return INLINE_CODE_RE.sub("", line)


def path_alternatives(raw: str) -> list[str]:
    match = BRACE_LIST_RE.search(raw)
    if not match:
        return [raw]
    head, tail = raw[: match.start()], raw[match.end() :]
    parts = [part.strip() for part in match.group(1).split(",")]
    return [f"{head}{part}{tail}" for part in parts if part]


def normalize_path_token(raw: str) -> tuple[str, bool]:
    token = raw.rstrip(".,;:!?，。；：！？|）】」』")
    dynamic = any(char in token for char in "*?{[")
    if dynamic:
        cut = min((token.find(char) for char in "*?{[" if char in token), default=len(token))
        token = token[:cut]
        if token and not token.endswith("/"):
            token = token.rsplit("/", 1)[0] + "/"
    return token, dynamic


def parse_document(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    document = Document(path=path)
    fence_char: str | None = None
    fence_size = 0
    slug_counts: dict[str, int] = {}

    for line_number, line in enumerate(text.splitlines(), start=1):
        if fence_char is not None:
            closing_fence = re.fullmatch(
                r"[ ]{0,3}" + re.escape(fence_char) + r"{" + str(fence_size) + r",}[ \t]*",
                line,
            )
            if closing_fence:
                fence_char = None
                fence_size = 0
            continue

        opening_fence = OPEN_FENCE_RE.match(line)
        if opening_fence:
            marker, info = opening_fence.groups()
            if marker[0] == "`" and "`" in info:
                opening_fence = None
            else:
                fence_char = marker[0]
                fence_size = len(marker)
                continue

        for pattern in AGENT_REF_RES:
            document.agent_refs.extend(
                (line_number, match.group(1)) for match in pattern.finditer(line)
            )

        heading = ATX_HEADING_RE.match(line)
        if heading:
            base = markdown_slug(heading.group(1))
            suffix = slug_counts.get(base, 0)
            slug_counts[base] = suffix + 1
            document.anchors.add(base if suffix == 0 else f"{base}-{suffix}")

        for match in LINK_RE.finditer(line):
            document.refs.append(
                SourceRef(line=line_number, raw=strip_link_title(match.group(1)), kind="link")
            )

        prose_without_code = EMPHASIS_PATH_RE.sub(
            r"\g<path>", EXTERNAL_URL_RE.sub("", LINK_RE.sub("", INLINE_CODE_RE.sub("", line)))
        )
        for match in SKILL_PATH_RE.finditer(prose_without_code):
            document.refs.extend(
                SourceRef(line=line_number, raw=alternative, kind="skill-path")
                for alternative in path_alternatives(match.group("path"))
            )

        for match in INLINE_CODE_RE.finditer(line):
            code = EXTERNAL_URL_RE.sub("", match.group(1)).strip()
            for path_match in SKILL_PATH_RE.finditer(code):
                document.refs.extend(
                    SourceRef(line=line_number, raw=alternative, kind="skill-path")
                    for alternative in path_alternatives(path_match.group("path"))
                )
            for path_match in INLINE_MD_PATH_RE.finditer(code):
                raw = path_match.group("path")
                base = Path(raw).name
                if ASCII_MD_RE.fullmatch(base) and not base.startswith("_"):
                    document.refs.append(SourceRef(line=line_number, raw=raw, kind="inline-md"))

        prose = strip_inline_markup(line)
        document.unlinked_sections.extend(
            (line_number, match.group(0).strip())
            for match in UNLINKED_SECTION_RE.finditer(prose)
        )

    return document


def parse_frontmatter(path: Path) -> tuple[dict[str, str], int | None]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, None
    closing = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if closing is None:
        return {}, None
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip("\"'")
    return values, closing + 1


def resolve_ref(
    ref: SourceRef,
    document: Document,
    skill_dir: Path,
    root: Path,
    documents: dict[Path, Document],
) -> tuple[Path | None, str, bool, bool]:
    raw = ref.raw.strip()
    if not raw or is_external_ref(raw):
        return None, "", False, False

    path_part, separator, fragment = raw.partition("#")
    fragment = unquote(fragment).lower() if separator else ""
    dynamic = False
    candidates: list[Path]
    if ref.kind == "skill-path":
        path_part, dynamic = normalize_path_token(path_part)
        decoded = unquote(path_part)
        candidates = [skill_dir / decoded, root / decoded, root / "skills" / decoded]
    elif not path_part:
        candidates = [document.path]
    else:
        path_part, dynamic = normalize_path_token(path_part)
        decoded = unquote(path_part)
        if ref.kind == "link" and decoded.startswith("/"):
            candidates = [root / decoded.lstrip("/")]
        elif ref.kind == "link":
            candidates = [document.path.parent / decoded]
        elif ref.kind == "inline-md" and "/" not in decoded:
            candidates = [
                document.path.parent / decoded,
                skill_dir / decoded,
                skill_dir / "references" / decoded,
                skill_dir / "references/agent-references" / decoded,
                root / decoded,
                root / "skills" / decoded,
            ]
        else:
            candidates = [
                document.path.parent / decoded,
                skill_dir / decoded,
                root / decoded,
                root / "skills" / decoded,
            ]

    unique_candidates = list(dict.fromkeys(candidate.resolve() for candidate in candidates))
    local_candidates = [candidate for candidate in unique_candidates if inside_root(candidate, root)]
    selectable = local_candidates or unique_candidates
    target = next((candidate for candidate in selectable if candidate.exists()), selectable[0])

    if target.suffix.lower() == ".md" and target.is_file() and target not in documents:
        documents[target] = parse_document(target)
    return target, fragment, True, dynamic


def is_deployed_runtime_ref(
    ref: SourceRef,
    document: Document,
    skill_dir: Path,
    agent_names: set[str],
) -> bool:
    normalized = ref.raw.strip().replace("\\", "/")
    if normalized.startswith(DEPLOYED_RUNTIME_PREFIXES):
        return True
    if ref.kind == "inline-md" and "/" not in normalized and Path(normalized).stem in agent_names:
        return True
    try:
        relative = document.path.resolve().relative_to(skill_dir.resolve()).as_posix()
    except ValueError:
        return False
    return (
        normalized.startswith("scripts/")
        and ("/agents/" in f"/{relative}" or relative.startswith("references/templates/agents/"))
    )


def cross_skill_path_issues(skill_dir: Path, root: Path) -> list[Issue]:
    skills_dir = root / "skills"
    skill_names = sorted(
        (
            path.name
            for path in skills_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        ),
        key=len,
        reverse=True,
    )
    if len(skill_names) < 2:
        return []
    pattern = re.compile(
        r"(?<![A-Za-z0-9_-])(?P<skill>"
        + "|".join(re.escape(name) for name in skill_names)
        + r")[\\/]+(?P<asset>SKILL\.md|(?:references|scripts|assets)(?:[\\/]+|\b))"
    )
    issues: list[Issue] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SKILL_TEXT_SUFFIXES:
            continue
        if path.name in CHANGELOG_DOCS:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            local_text = EXTERNAL_URL_RE.sub("", line)
            for match in pattern.finditer(local_text):
                target_skill = match.group("skill")
                if target_skill == skill_dir.name or target_skill in FOUNDATION_SKILL_REFERENCES:
                    continue
                issues.append(
                    Issue(
                        "error",
                        "cross-skill-reference",
                        path,
                        line_number,
                        (
                            f"path enters skill {target_skill!r}; runtime skills must "
                            "carry their own files instead of reading another skill"
                        ),
                    )
                )
    return issues


def validate_skill(skill_dir: Path, root: Path, agent_names: set[str]) -> list[Issue]:
    skill_file = skill_dir / "SKILL.md"
    issues: list[Issue] = []
    frontmatter, closing_line = parse_frontmatter(skill_file)
    if closing_line is None:
        issues.append(Issue("error", "frontmatter-block", skill_file, 1, "missing closed frontmatter block"))
    if not frontmatter.get("name"):
        issues.append(Issue("error", "frontmatter-name", skill_file, 1, "frontmatter requires a non-empty name"))
    elif frontmatter["name"] != skill_dir.name:
        issues.append(
            Issue(
                "error",
                "frontmatter-name",
                skill_file,
                2,
                f"frontmatter name must equal directory name {skill_dir.name!r}",
            )
        )
    if not frontmatter.get("description"):
        issues.append(
            Issue("error", "frontmatter-description", skill_file, 1, "frontmatter requires a non-empty description")
        )

    issues.extend(cross_skill_path_issues(skill_dir, root))

    markdown_paths = sorted(path for path in skill_dir.rglob("*.md") if path.is_file())
    documents = {path.resolve(): parse_document(path) for path in markdown_paths}
    resolved_by_document: dict[Path, set[Path]] = {path.resolve(): set() for path in markdown_paths}

    for document in list(documents.values()):
        if document.path.name in CHANGELOG_DOCS:
            continue
        seen_refs: set[tuple[int, str, str]] = set()
        for ref in document.refs:
            key = (ref.line, ref.raw, ref.kind)
            if key in seen_refs:
                continue
            seen_refs.add(key)
            if is_deployed_runtime_ref(ref, document, skill_dir, agent_names):
                continue
            target, fragment, local, dynamic = resolve_ref(ref, document, skill_dir, root, documents)
            if not local or target is None:
                continue
            if not inside_root(target, root):
                issues.append(
                    Issue(
                        "error",
                        "local-path-outside-root",
                        document.path,
                        ref.line,
                        f"local reference {ref.raw!r} escapes repository root",
                    )
                )
                continue
            target_owner = skill_owner(target, root)
            if (
                target_owner is not None
                and target_owner != skill_dir.name
                and target_owner not in FOUNDATION_SKILL_REFERENCES
            ):
                issues.append(
                    Issue(
                        "error",
                        "cross-skill-reference",
                        document.path,
                        ref.line,
                        (
                            f"{ref.raw!r} resolves into skill {target_owner!r}; "
                            "copy the required contract into this skill or use a runtime artifact"
                        ),
                    )
                )
                continue
            if not target.exists():
                issues.append(
                    Issue(
                        "error",
                        "broken-link-path" if ref.kind == "link" else "broken-inline-path",
                        document.path,
                        ref.line,
                        f"{ref.raw!r} resolves to missing {display(target, root)}",
                    )
                )
                continue
            if not (dynamic and target.is_dir()):
                resolved_by_document.setdefault(document.path.resolve(), set()).add(target)
            if fragment:
                target_document = documents.get(target)
                if target_document is None or fragment not in target_document.anchors:
                    issues.append(
                        Issue(
                            "error",
                            "broken-link-anchor",
                            document.path,
                            ref.line,
                            f"anchor #{fragment} does not exist in {display(target, root)}",
                        )
                    )

        for line, agent_name in sorted(set(document.agent_refs)):
            if agent_name not in agent_names:
                issues.append(
                    Issue(
                        "error",
                        "unknown-agent",
                        document.path,
                        line,
                        f"unknown subagent_type {agent_name!r}",
                    )
                )

        if document.path != skill_file:
            for line, phrase in document.unlinked_sections:
                issues.append(
                    Issue(
                        "error",
                        "unlinked-skill-section",
                        document.path,
                        line,
                        f"replace textual section guess {phrase!r} with a Markdown link to ../SKILL.md#anchor",
                    )
                )

    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        reached: set[Path] = set()
        queue: list[Path] = []

        def is_reference_content(candidate: Path) -> bool:
            return candidate.name != ".gitkeep" and "__pycache__" not in candidate.parts

        def add_target(target: Path) -> None:
            try:
                target.relative_to(references_dir.resolve())
            except ValueError:
                return
            candidates = (
                [target] if target.is_file() else sorted(path for path in target.rglob("*") if path.is_file())
            )
            for candidate in candidates:
                resolved = candidate.resolve()
                if not is_reference_content(candidate) or resolved in reached:
                    continue
                reached.add(resolved)
                if candidate.suffix.lower() == ".md":
                    queue.append(resolved)

        for target in resolved_by_document.get(skill_file.resolve(), set()):
            add_target(target)
        while queue:
            source = queue.pop()
            for target in resolved_by_document.get(source, set()):
                add_target(target)

        for candidate in sorted(path for path in references_dir.rglob("*") if path.is_file()):
            if not is_reference_content(candidate) or candidate.resolve() in reached:
                continue
            issues.append(
                Issue(
                    "warning",
                    "dead-reference",
                    candidate,
                    1,
                    "reference file is not reachable from SKILL.md through explicit paths or links",
                )
            )

    return sorted(
        issues,
        key=lambda issue: (display(issue.path, root), issue.line, issue.severity, issue.code),
    )


def run_static_check(root: Path) -> int:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        print(f"ERROR: skills/ not found at {skills_dir}", file=sys.stderr)
        return 2

    agent_dir = skills_dir / "story-setup/references/templates/agents"
    agent_names = {path.stem for path in agent_dir.glob("*.md")} if agent_dir.is_dir() else set()
    skill_dirs = sorted(path for path in skills_dir.iterdir() if (path / "SKILL.md").is_file())
    if not skill_dirs:
        print("ERROR: no skill entrypoints found", file=sys.stderr)
        return 2

    print("Skill Static Check")
    print("==================")
    print(f"Repo: {root}")

    passed = 0
    failed = 0
    warned = 0
    for skill_dir in skill_dirs:
        print(f"\n--- {skill_dir.name} ---")
        try:
            issues = validate_skill(skill_dir, root, agent_names)
        except (OSError, UnicodeError) as exc:
            issues = [Issue("error", "read-error", skill_dir / "SKILL.md", 1, str(exc))]
        errors = [issue for issue in issues if issue.severity == "error"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        if not issues:
            print("  [PASS] structured frontmatter, links, anchors, agents, and references")
        for issue in issues:
            label = "FAIL" if issue.severity == "error" else "WARN"
            print(
                f"  [{label}] [{issue.code}] {display(issue.path, root)}:{issue.line}: {issue.message}"
            )
        if errors:
            failed += 1
            print(f"  Result: FAIL ({len(errors)} errors, {len(warnings)} warnings)")
        else:
            passed += 1
            if warnings:
                warned += 1
                print(f"  Result: PASS ({len(warnings)} warnings)")
            else:
                print("  Result: PASS")

    print("\n==================")
    print(f"Total: {len(skill_dirs)} | Pass: {passed} | Fail: {failed} | Warn: {warned}")
    return 1 if failed else 0


# ============================================================================
# 2. Hard Runtime Contract Pins (slimmed from check-current-skill-contracts.py)
# ============================================================================

SUPPORTED_MANIFEST_VERSION = 1
REQUIRED_MANIFEST_KEYS = {
    "manifest_version",
    "setup_skill_version",
    "agents_version",
    "progress_schema_version",
    "primary_benchmark_artifacts",
}
ALLOWED_MANIFEST_KEYS = REQUIRED_MANIFEST_KEYS
SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ARTIFACT_PATH_RE = re.compile(r"(?:[^/\s]+/)+[^/\s]+\.md")
SCHEMA_VERSION_PIN_RE = re.compile(r"schema_version:\s*([0-9]+)")

SPAWN_CAPABLE_SKILLS = (
    "skills/story/SKILL.md",
    "skills/story-deslop/SKILL.md",
    "skills/story-import/SKILL.md",
    "skills/story-long-analyze/SKILL.md",
    "skills/story-long-write/SKILL.md",
    "skills/story-review/SKILL.md",
    "skills/story-short-write/SKILL.md",
)


@dataclass(frozen=True)
class ContractManifest:
    manifest_version: int
    setup_skill_version: str
    agents_version: int
    progress_schema_version: int
    primary_benchmark_artifacts: Tuple[str, ...]


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
                location += f":{self.line}"
            location += ": "
        suffix = f" [{self.excerpt.strip()}]" if self.excerpt else ""
        return f"{location}{self.message}{suffix}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def iter_contract_md(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        if path.name in CHANGELOG_DOCS:
            continue
        if any(part in {".git", ".omx"} for part in path.parts):
            continue
        yield path


def load_manifest(path: Path) -> Tuple[Optional[ContractManifest], List[Finding]]:
    findings: List[Finding] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [Finding("manifest-missing", "current contract manifest is missing", path)]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [Finding("manifest-invalid-json", f"cannot parse manifest: {exc}", path)]

    if not isinstance(raw, dict):
        return None, [Finding("manifest-type", "manifest root must be a JSON object", path)]

    keys = set(raw)
    for missing in sorted(REQUIRED_MANIFEST_KEYS - keys):
        findings.append(Finding("manifest-key-missing", f"missing manifest key: {missing}", path))
    for unknown in sorted(keys - ALLOWED_MANIFEST_KEYS):
        findings.append(Finding("manifest-key-unknown", f"unknown manifest key: {unknown}", path))

    if "manifest_version" in raw:
        if not _is_int(raw["manifest_version"]):
            findings.append(Finding("manifest-value-type", "manifest_version has the wrong type", path))
        elif raw["manifest_version"] != SUPPORTED_MANIFEST_VERSION:
            findings.append(
                Finding(
                    "manifest-version-unsupported",
                    f"manifest_version must be {SUPPORTED_MANIFEST_VERSION}, got {raw['manifest_version']}",
                    path,
                )
            )

    setup_version = raw.get("setup_skill_version")
    if not isinstance(setup_version, str):
        if "setup_skill_version" in raw:
            findings.append(Finding("manifest-value-type", "setup_skill_version has the wrong type", path))
    elif not SEMVER_RE.fullmatch(setup_version):
        findings.append(Finding("manifest-value-format", "setup_skill_version must be x.y.z", path))

    for key in ("agents_version", "progress_schema_version"):
        if key not in raw:
            continue
        if not _is_int(raw[key]):
            findings.append(Finding("manifest-value-type", f"{key} has the wrong type", path))
        elif raw[key] < 1:
            findings.append(Finding("manifest-value-range", f"{key} must be a positive integer", path))

    artifacts = raw.get("primary_benchmark_artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        findings.append(Finding("manifest-artifact-type", "primary_benchmark_artifacts must be a string array", path))
    elif not artifacts:
        findings.append(Finding("manifest-artifact-empty", "primary_benchmark_artifacts must not be empty", path))
    elif len(set(artifacts)) != len(artifacts):
        findings.append(Finding("manifest-artifact-duplicate", "primary_benchmark_artifacts must be unique", path))
    elif any(ARTIFACT_PATH_RE.fullmatch(item) is None for item in artifacts):
        findings.append(
            Finding("manifest-artifact-format", "primary benchmark artifacts must be relative Markdown paths", path)
        )

    if findings:
        return None, findings

    assert isinstance(artifacts, list)
    manifest = ContractManifest(
        manifest_version=raw["manifest_version"],
        setup_skill_version=raw["setup_skill_version"],
        agents_version=raw["agents_version"],
        progress_schema_version=raw["progress_schema_version"],
        primary_benchmark_artifacts=tuple(artifacts),
    )
    return manifest, []


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


def extract_sentinel_fields(text: str) -> Optional[dict[str, str]]:
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


def sentinel_contract_findings(text: str, manifest: ContractManifest, path: Path) -> List[Finding]:
    fields = extract_sentinel_fields(text)
    if fields is None:
        return [Finding("setup-sentinel-block", "cannot find the structured generated-sentinel fenced block", path)]

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
            Finding("setup-sentinel-fields", f"generated sentinel is missing fields: {', '.join(missing)}", path)
        )
    for key, value in (
        ("agents_version", str(manifest.agents_version)),
        ("setup_skill_version", manifest.setup_skill_version),
    ):
        actual = fields.get(key)
        if actual != value:
            findings.append(
                Finding("setup-sentinel-field", f"generated sentinel {key} must be {value!r}, got {actual!r}", path)
            )
    return findings


def extract_current_version_fields(text: str) -> dict[str, str]:
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
        match = re.fullmatch(r"\s*-\s+`(setup_skill_version|agents_version):\s*([^`]+)`\s*", line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return fields


def upgrading_version_findings(text: str, manifest: ContractManifest, path: Path) -> List[Finding]:
    fields = extract_current_version_fields(text)
    findings: List[Finding] = []
    for key, value in (
        ("setup_skill_version", manifest.setup_skill_version),
        ("agents_version", str(manifest.agents_version)),
    ):
        actual = fields.get(key)
        if actual != value:
            findings.append(
                Finding(
                    "upgrading-current-version",
                    f"UPGRADING current-version bullet {key} must be {value!r}, got {actual!r}",
                    path,
                )
            )
    for raw in text.splitlines():
        match = re.search(r"`agents_version:\s*(\d+)`", raw)
        if match and match.group(1) != str(manifest.agents_version):
            findings.append(
                Finding(
                    "upgrading-step-version",
                    f"UPGRADING step line pins agents_version {match.group(1)!r}, must be {str(manifest.agents_version)!r}: {raw.strip()}",
                    path,
                )
            )
    return findings


def spawn_version_findings(text: str, manifest: ContractManifest, path: Path) -> List[Finding]:
    current = str(manifest.agents_version)
    if re.search(rf"`agents_version:\s*{re.escape(current)}`", text) is None:
        return [
            Finding(
                "spawn-agents-version-pin",
                f"spawn-capable Skill must pin current `agents_version: {current}`",
                path,
            )
        ]
    findings: List[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in re.finditer(r"`agents_version:\s*(\d+)`", line):
            if match.group(1) != current:
                findings.append(
                    Finding(
                        "spawn-agents-version-pin",
                        f"stale agents_version {match.group(1)!r}, expected {current!r}",
                        path,
                        line_number,
                        line,
                    )
                )
    return findings


def progress_schema_pin_findings(repo_root: Path, expected: int) -> List[Finding]:
    findings: List[Finding] = []
    paths: List[Path] = []
    for root in (repo_root / "skills", repo_root / "demo"):
        paths.extend(iter_contract_md(root))
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
                        f"every pipeline schema_version must equal {expected} (found {match.group(1)})",
                        path,
                        line_number,
                        line_text,
                    )
                )
    return findings


def rubric_dimension_names(repo_root: Path) -> Tuple[List[str], List[str]]:
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
    findings: List[Finding] = []
    for missing, where in (
        (sorted(set(table) - set(embedded)), "内置 fallback rubric"),
        (sorted(set(embedded) - set(table)), "quality-rubric.md"),
    ):
        if missing:
            findings.append(
                Finding(
                    "rubric-dimension-drift",
                    f"generic rubric dimensions drifted: {'、'.join(missing)} missing from {where}",
                    path,
                )
            )
    return findings


def validate_repository(repo_root: Path, manifest: ContractManifest) -> List[Finding]:
    findings: List[Finding] = []

    setup_skill = repo_root / "skills/story-setup/SKILL.md"
    actual_setup_version = parse_frontmatter_version(setup_skill)
    if actual_setup_version != manifest.setup_skill_version:
        findings.append(
            Finding(
                "setup-frontmatter-version",
                f"story-setup frontmatter version must be {manifest.setup_skill_version}, got {actual_setup_version!r}",
                setup_skill,
            )
        )
    findings.extend(sentinel_contract_findings(read_text(setup_skill) or "", manifest, setup_skill))

    upgrading = repo_root / "skills/story-setup/UPGRADING.md"
    findings.extend(upgrading_version_findings(read_text(upgrading) or "", manifest, upgrading))

    for relative in SPAWN_CAPABLE_SKILLS:
        spawn_skill = repo_root / relative
        findings.extend(spawn_version_findings(read_text(spawn_skill) or "", manifest, spawn_skill))

    pipeline = repo_root / "skills/story-long-analyze/references/pipeline-ops.md"
    if not SCHEMA_VERSION_PIN_RE.search(read_text(pipeline) or ""):
        findings.append(
            Finding(
                "progress-schema-version",
                f"every pipeline schema_version must equal {manifest.progress_schema_version} (found none)",
                pipeline,
            )
        )
    findings.extend(progress_schema_pin_findings(repo_root, manifest.progress_schema_version))

    demo_root = repo_root / "demo/拆文库/盘龙"
    for artifact in manifest.primary_benchmark_artifacts:
        artifact_path = demo_root / artifact
        try:
            has_content = artifact_path.is_file() and artifact_path.stat().st_size > 0
        except OSError:
            has_content = False
        if not has_content:
            findings.append(
                Finding(
                    "demo-primary-artifact",
                    f"demo deconstruction is missing non-empty {artifact}",
                    artifact_path,
                )
            )

    findings.extend(rubric_parity_findings(repo_root))
    return findings


def run_contracts_check(root: Path, manifest_path: Path) -> int:
    manifest, manifest_findings = load_manifest(manifest_path.resolve())
    print("Current Skill Contract Check")
    print("============================")
    if manifest_findings:
        for finding in manifest_findings:
            print(f"  [FAIL] {finding.code}: {finding.detail(root)}")
        print(f"\nResult: {len(manifest_findings)} failure(s)")
        return 1

    assert manifest is not None
    print("  [PASS] manifest schema and declared release values")
    findings = validate_repository(root, manifest)
    if findings:
        for finding in findings:
            print(f"  [FAIL] {finding.code}: {finding.detail(root)}")
        print(f"\nResult: {len(findings)} failure(s)")
        return 1

    print("  [PASS] setup/agents version alignment")
    print("  [PASS] progress schema_version pins")
    print("  [PASS] demo primary benchmark artifacts")
    print("  [PASS] quality-rubric parity")
    print("\nResult: all current-contract checks passed")
    return 0


# ============================================================================
# 3. Shared Files & Agent-Reference Consumers (absorbed from check-shared-files.sh
#    + check-agent-reference-consumers.py)
# ============================================================================

AGENT_REF_RE = re.compile(r"agent-references/([^`\s)】」]+?\.md)")
LOCAL_MD_RE = re.compile(r"(?<![A-Za-z0-9_.-])([\w\-./\u0080-\uffff]+\.md)")
PROFILE_LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+\.md)\)")
CANONICAL_PREFIX = "story-setup/references/agent-references/"
URL_RE = re.compile(r"https?://[^\s`<>)]+")
PROFILE_HEADINGS = {
    "## Common": "common",
    "## Long profile": "long",
    "## Short profile": "short",
}


def template_prefix_errors(
    text: str, references: set[str], url_spans: list[tuple[int, int]]
) -> list[tuple[int, str]]:
    names = sorted(
        references | {Path(name).name for name in references},
        key=lambda name: (-len(name), name),
    )
    patterns = [AGENT_REF_RE.pattern, r"genre-prose-cards/\{[^}\n]+\}\.md"]
    if names:
        patterns.append(
            r"(?<![A-Za-z0-9_./-])(?:\.{1,2}/)*(?:references/)?(?:"
            + "|".join(re.escape(name) for name in names)
            + r")(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])"
        )
    tokens = re.compile("|".join(patterns))
    canonical = re.compile(
        r"(?<![A-Za-z0-9_.-])" + re.escape(CANONICAL_PREFIX) + r"[^`\s)】」]+?\.md"
    )
    ignored = [match.span() for match in canonical.finditer(text)]
    ignored.extend(url_spans)
    ignored.extend(match.span(1) for match in re.finditer(r"\[([^]\n]*)\]\(([^)\n]+)\)", text))
    errors = []
    for match in tokens.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in ignored):
            continue
        errors.append((text.count("\n", 0, match.start()) + 1, match.group(0)))
    return errors


def local_references(path: Path, references_dir: Path) -> set[Path]:
    text = path.read_text(encoding="utf-8")
    found: set[Path] = set()
    for match in LOCAL_MD_RE.finditer(text):
        raw = match.group(1)
        candidates = (path.parent / raw, references_dir / raw)
        target = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
        if target is not None:
            try:
                target.relative_to(references_dir.resolve())
            except ValueError:
                continue
            found.add(target)
    return found


def profile_contract(path: Path) -> dict[str, set[str]]:
    sections: dict[str, set[str]] = {name: set() for name in PROFILE_HEADINGS.values()}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = line.strip()
        if heading in PROFILE_HEADINGS:
            current = PROFILE_HEADINGS[heading]
            continue
        if heading.startswith("## "):
            current = None
            continue
        if current is not None:
            sections[current].update(Path(raw).name for raw in PROFILE_LINK_RE.findall(line))
    return sections


def run_agent_ref_consumers_check(root: Path) -> int:
    references_dir = root / "skills/story-setup/references/agent-references"
    agents_dir = root / "skills/story-setup/references/templates/agents"
    if not references_dir.is_dir() or not agents_dir.is_dir():
        print("ERROR: story-setup agent templates or references directory missing", file=sys.stderr)
        return 2

    reference_files = set(references_dir.rglob("*.md"))
    all_references = {path.resolve() for path in reference_files}
    reference_names = {path.relative_to(references_dir).as_posix() for path in reference_files}
    roots: set[Path] = set()
    missing_roots: set[str] = set()
    prefix_errors: list[str] = []
    for agent in sorted(agents_dir.glob("*.md")):
        text = agent.read_text(encoding="utf-8")
        url_spans = [match.span() for match in URL_RE.finditer(text)]
        for line, reference in template_prefix_errors(text, reference_names, url_spans):
            prefix_errors.append(f"{agent.relative_to(root)}:{line}: {reference}")
        for match in AGENT_REF_RE.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in url_spans):
                continue
            raw = match.group(1)
            if "{" in raw or "}" in raw:
                continue
            target = (references_dir / raw).resolve()
            if target.is_file():
                roots.add(target)
            else:
                missing_roots.add(raw)

    if prefix_errors:
        print(f"INVALID AGENT REFERENCE PREFIX: require {CANONICAL_PREFIX}")
        for error in prefix_errors:
            print(f"  {error}")
        return 1

    if missing_roots:
        print("MISSING DEPLOYED AGENT REFERENCES")
        for missing in sorted(missing_roots):
            print(f"  {missing}")
        return 1

    profile_path = references_dir / "agent-reference-profiles.md"
    architect_path = agents_dir / "story-architect.md"
    if not profile_path.is_file() or not architect_path.is_file():
        print("ERROR: story-architect profile contract missing", file=sys.stderr)
        return 2

    contract = profile_contract(profile_path)
    if any(not contract[name] for name in ("common", "long", "short")):
        print("INVALID PROFILE CONTRACT: common, long and short must all be non-empty")
        return 1
    overlaps = (
        (contract["common"] & contract["long"])
        | (contract["common"] & contract["short"])
        | (contract["long"] & contract["short"])
    )
    if overlaps:
        print("INVALID PROFILE CONTRACT: files appear in multiple ownership sections")
        for name in sorted(overlaps):
            print(f"  {name}")
        return 1
    wrong_long = sorted(name for name in contract["long"] if name.startswith("short-"))
    wrong_short = sorted(name for name in contract["short"] if name.startswith("long-"))
    if wrong_long or wrong_short:
        print("INVALID PROFILE CONTRACT: profile-prefixed files are routed to the other profile")
        for name in wrong_long + wrong_short:
            print(f"  {name}")
        return 1

    declared = contract["common"] | contract["long"] | contract["short"]
    missing_declared = sorted(name for name in declared if not (references_dir / name).is_file())
    if missing_declared:
        print("MISSING PROFILE REFERENCES")
        for name in missing_declared:
            print(f"  {name}")
        return 1

    common_mode_sections: list[str] = []
    for name in sorted(contract["common"]):
        text = (references_dir / name).read_text(encoding="utf-8")
        if re.search(r"^## .*?(?:长篇|短篇)专项", text, re.MULTILINE):
            common_mode_sections.append(name)
    if common_mode_sections:
        print("MODE-SPECIFIC SECTION IN COMMON PROFILE")
        for name in common_mode_sections:
            print(f"  {name}")
        return 1

    architect_refs = {path.name for path in local_references(architect_path, references_dir)} - {
        profile_path.name
    }
    outside_contract = sorted(architect_refs - declared)
    if outside_contract:
        print("STORY-ARCHITECT REFERENCES OUTSIDE PROFILE CONTRACT")
        for name in outside_contract:
            print(f"  {name}")
        return 1
    if "| 参考文件 | 必读条件 |" in architect_path.read_text(encoding="utf-8"):
        print("DUPLICATED STORY-ARCHITECT REFERENCE INVENTORY")
        return 1

    reachable: set[Path] = set()
    queue = deque(sorted(roots))
    while queue:
        path = queue.popleft()
        if path in reachable:
            continue
        reachable.add(path)
        queue.extend(sorted(local_references(path, references_dir) - reachable))

    unreachable = sorted(all_references - reachable)
    if unreachable:
        print("UNCONSUMED DEPLOYED AGENT REFERENCES")
        for path in unreachable:
            print(f"  {path.relative_to(root)}")
        return 1
    print(
        f"Agent reference consumers: {len(all_references)} deployed Markdown files reachable "
        f"from {len(roots)} direct agent roots; profile contract "
        f"{len(contract['common'])} common / {len(contract['long'])} long / "
        f"{len(contract['short'])} short"
    )
    return 0


def run_shared_check(root: Path) -> int:
    print("Shared File Governance Check")
    print("============================")
    assets_cmd = [sys.executable, str(SCRIPT_DIR / "sync-shared-assets.py"), "check", "--root", str(root)]
    refs_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "shared-references.py"),
        "check",
        "--root",
        str(root),
        "--runtime-manifest",
        str(root / "scripts/shared-assets.json"),
    ]
    for cmd in (assets_cmd, refs_cmd):
        proc = subprocess.run(cmd, check=False)
        if proc.returncode != 0:
            return proc.returncode
    rc = run_agent_ref_consumers_check(root)
    if rc != 0:
        return rc
    print("All declared shared files and agent reference consumers are consistent.")
    return 0


# ============================================================================
# 4. Dotted Workflow Label Guard (replaces skill-numbering.py)
# ============================================================================

DOTTED_WORKFLOW_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<kind>Step|Phase|Stage)[ \t]+"
    r"(?P<label>[0-9]+\.[0-9]+(?:\.[0-9]+)*)(?!\.?[0-9])(?!\w)"
)


def dotted_workflow_label_findings(root: Path) -> List[Finding]:
    findings: List[Finding] = []
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return findings
    for path in sorted(skills_dir.rglob("*.md")):
        if not path.is_file() or path.name in CHANGELOG_DOCS:
            continue
        fence_char: str | None = None
        fence_size = 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if fence_char is not None:
                if re.fullmatch(
                    r"[ ]{0,3}" + re.escape(fence_char) + r"{" + str(fence_size) + r",}[ \t]*",
                    line,
                ):
                    fence_char = None
                    fence_size = 0
                continue
            opening = OPEN_FENCE_RE.match(line)
            if opening:
                marker, info = opening.groups()
                if not (marker[0] == "`" and "`" in info):
                    fence_char = marker[0]
                    fence_size = len(marker)
                    continue
            for match in DOTTED_WORKFLOW_LABEL_RE.finditer(line):
                findings.append(
                    Finding(
                        "dotted-workflow-label",
                        f"dotted workflow label {match.group(0)!r} is disallowed; use sequential integers",
                        path,
                        line_number,
                        line,
                    )
                )
    return findings


def run_numbering_check(root: Path) -> int:
    print("Workflow Numbering Check")
    print("========================")
    findings = dotted_workflow_label_findings(root)
    if findings:
        for finding in findings:
            print(f"  [FAIL] {finding.code}: {finding.detail(root)}")
        print(f"\nResult: {len(findings)} dotted workflow label(s) found")
        return 1
    print("  [PASS] no dotted workflow labels (Step/Phase/Stage N.M) in skills/**/*.md")
    return 0


# ============================================================================
# CLI Entrypoint
# ============================================================================

ALL_CHECKS = ("static", "contracts", "shared", "numbering")
ONLY_CHOICES = (*ALL_CHECKS, "agent-refs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=ONLY_CHOICES,
        default=None,
        help="run only one sub-check instead of the full suite",
    )
    parser.add_argument(
        "--root",
        "--repo-root",
        dest="root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=SCRIPT_DIR / "current-contract.json",
        help="current contract manifest path (used by --only contracts and default run)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    manifest_path = args.manifest.resolve()

    if args.only == "static":
        return run_static_check(root)
    if args.only == "contracts":
        return run_contracts_check(root, manifest_path)
    if args.only == "shared":
        return run_shared_check(root)
    if args.only == "agent-refs":
        return run_agent_ref_consumers_check(root)
    if args.only == "numbering":
        return run_numbering_check(root)

    checks = (
        ("static", lambda: run_static_check(root)),
        ("contracts", lambda: run_contracts_check(root, manifest_path)),
        ("shared", lambda: run_shared_check(root)),
        ("numbering", lambda: run_numbering_check(root)),
    )
    failed: list[str] = []
    worst_rc = 0
    for idx, (name, runner) in enumerate(checks):
        if idx > 0:
            print()
        rc = runner()
        if rc != 0:
            failed.append(name)
            worst_rc = max(worst_rc, rc)

    if failed:
        print(f"\nLINT REPO FAIL: failed checks = {', '.join(failed)}")
        return worst_rc
    print("\nLINT REPO PASS: static, contracts, shared, numbering")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
