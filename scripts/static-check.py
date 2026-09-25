#!/usr/bin/env python3
"""Structured, dependency-free validation for repository skill Markdown."""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote


ATX_HEADING_RE = re.compile(r"^[ ]{0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$")
OPEN_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
# 只还原“强调符完整包住一条 skill 内路径”的形态。开始/结束 marker 必须同宽，
# 且两边不能粘着 ASCII 路径字符；这样 CJK 连写的 references/*.md与references/*.json
# 不会把两个 glob 星号跨片段配成一对强调符。
EMPHASIS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?P<marker>\*{1,2})"
    r"(?P<path>(?:[a-z0-9_-]+/)?(?:references|scripts|assets)/[^\s*]+)"
    r"(?P=marker)(?![A-Za-z0-9_./-])"
)
SKILL_PATH_PREFIX = r"(?:[a-z0-9_-]+/)?(?:references|scripts|assets)/"
# 中文说明常把多个路径写成 `references/*.md与assets/*.json`。重复体必须在“连接词 +
# 下一个路径前缀”前停住，否则首个 match 会把整串吞掉，normalize_path_token 再于第一个
# `*` 截成 references/，后面的缺失路径永远没有独立参与校验。
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
    # 括号形态同时接受全角/半角括号与冒号（正文标注常写「（subagent_type: x）」），
    # 引号可选。保留括号收尾锚点：兼容性说明里大量出现裸 `subagent_type` 词条，
    # 不带括号/引号锚点的裸形态会把这些非引用语境误抓成 agent 引用。
    re.compile(r"[（(]subagent_type\s*[:：]\s*\"?([a-z][a-z0-9_-]*)\"?\s*[)）]"),
)
# 「见 SKILL.md + 章节名」是无法被链接校验的文本猜测：SKILL.md 改标题后引用会静默失效。
# 分隔符两侧统一用 \s*——中文正文里「详见SKILL.md的阶段二流程」不带空格，恰是最常见的写法，
# 只认 `\s+` 会让这类写法整体绕过本规则。
# 章节名首字符排除括号/引号/竖线/井号：`见 SKILL.md「输出目录结构」`、`见 SKILL.md（…）`、
# 表格里的 `见 SKILL.md）|` 是原样引用标题或句子收尾，不属于本规则要清理的模糊猜测。
UNLINKED_SECTION_RE = re.compile(
    r"(?:见|参考|参见|详见)\s*SKILL\.md\s*"
    r"[^\s，。；;、（）()「」『』【】《》〈〉\[\]{}<>#|\"'“”‘’]"
    r"[^，。；;\n]*"
)
EXTERNAL_SCHEMES = ("http://", "https://", "ftp://", "mailto:", "data:", "tel:")
DEPLOYED_RUNTIME_PREFIXES = (".claude/", ".codex/", ".opencode/", ".agents/")
# browser-cdp is the repository's explicit infrastructure skill.  Business
# skills may reference its launcher; every other cross-skill file path remains
# forbidden so domain workflows stay self-contained.
FOUNDATION_SKILL_REFERENCES = frozenset({"browser-cdp"})
# 变更日志按定义记录历史状态：其内联路径是「当时」的引用（含已删/已移动/跨 skill 的旧文件），
# 不是当前运行时依赖，不作跨 skill / 死链校验（与 check-current-skill-contracts.py 的跳过一致）。
CHANGELOG_DOCS = frozenset({"UPGRADING.md", "CHANGELOG.md"})
EXTERNAL_URL_RE = re.compile(
    r"(?i)\b(?:https?|ftp)://[^\s<>\"'`]+"
)
# 花括号枚举（含逗号）是「逐个点名」，可以展开成具体路径；`{题材}` 这种单占位符不是枚举。
BRACE_LIST_RE = re.compile(r"\{([^{}/]*,[^{}/]*)\}")
# 跨 skill 扫描覆盖全部文本资产。模板（*.md.tmpl / *.json.patch）与前端资产同样会被
# story-setup 部署进作者项目，漏扫等于把「skill 自包含」这条红线在部署面上放空。
SKILL_TEXT_SUFFIXES = {
    ".cmd",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".patch",
    ".py",
    ".sh",
    ".tmpl",
    ".toml",
    ".ts",
    ".yaml",
    ".yml",
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
    """Return the GitHub-style subset used by this repository's headings."""

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
    """把点名枚举 `{a,b,c}` 展开成逐条路径。

    `{story_codex_hook.py,run-story-hook.sh,run-story-hook.cmd}` 是作者逐个点名的文件，
    等价于分别写三条引用：展开后每条都参与存在性与可达性校验。`{题材}` 这类单占位符
    不是枚举（没有点名任何文件），保持原样交给 normalize_path_token 当通配处理。
    """

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
                r"[ ]{0,3}"
                + re.escape(fence_char)
                + r"{"
                + str(fence_size)
                + r",}[ \t]*",
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

        # 外部 URL 命名远程资源，不是仓库内 skill 路径（与 cross_skill_path_issues 同一约定）：
        # 两条扫描通道都必须先剥掉，否则 URL 尾段（.../references/x.md）会被当成本地路径误报。
        # 正文里的加粗/斜体包裹也要还原：`**references/x.md**` 的 `*` 会被字符类吃进 token，
        # 让它被误判成通配符并截断到父目录，从而跳过存在性校验。行内代码内不作强调还原——
        # 反引号里的 `*` 是字面通配符。
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
    """返回（目标, 锚点, 是否本地引用, 是否通配引用）。"""

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
            # Markdown link destinations are resolved exactly relative to the
            # containing document.  Broader fallbacks would hide broken links
            # when a same-named file happens to exist elsewhere in the skill.
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
    """Reject explicit file paths into another repository skill.

    This repository keeps each runtime skill self-contained.  Scan every text
    asset, not only Markdown links, so comments, generated agent TOML, and
    executable help text cannot quietly reintroduce a cross-skill dependency.
    """

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
            # URL paths name remote resources, not repository skill imports.
            # Preserve local POSIX, Windows, and mixed-separator tokens.
            local_text = EXTERNAL_URL_RE.sub("", line)
            for match in pattern.finditer(local_text):
                target_skill = match.group("skill")
                if (
                    target_skill == skill_dir.name
                    or target_skill in FOUNDATION_SKILL_REFERENCES
                ):
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


def validate_skill(
    skill_dir: Path,
    root: Path,
    agent_names: set[str],
) -> list[Issue]:
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
        # 变更日志的历史内联路径不作死链/跨 skill 校验（仍可作为其它文件的链接目标）
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
            target, fragment, local, dynamic = resolve_ref(
                ref, document, skill_dir, root, documents
            )
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
            # 通配引用只声明范围（`references/*` 说的是「本 skill 的参考目录」），并没有点名
            # 任何文件；把它解析出的目录当作可达起点会把整棵子树标成「已被引用」，
            # dead-reference 检查对该 skill 就永久失效。点名枚举已在 path_alternatives 展开。
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
            # .gitkeep 是占位符；__pycache__ 是 .gitignore 的构建产物，都不是参考内容。
            return candidate.name != ".gitkeep" and "__pycache__" not in candidate.parts

        def add_target(target: Path) -> None:
            try:
                target.relative_to(references_dir.resolve())
            except ValueError:
                return
            candidates = [target] if target.is_file() else sorted(path for path in target.rglob("*") if path.is_file())
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
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


if __name__ == "__main__":
    raise SystemExit(main())
