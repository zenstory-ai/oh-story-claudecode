#!/usr/bin/env python3
"""Validate agent reference prefixes, reachability and profile ownership.

Template scanning enforces source policy only, not actual model read behavior.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import deque
from pathlib import Path


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
    text: str, references: set[str], url_spans: list[tuple[int, int]],
) -> list[tuple[int, str]]:
    """Inspect reference tokens, not arbitrary project artifact filenames."""
    names = sorted(references | {Path(name).name for name in references}, key=lambda name: (-len(name), name))
    patterns = [AGENT_REF_RE.pattern, r"genre-prose-cards/\{[^}\n]+\}\.md"]
    if names:
        patterns.append(
            r"(?<![A-Za-z0-9_./-])(?:" + "|".join(re.escape(name) for name in names)
            + r")(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])"
        )
    tokens = re.compile("|".join(patterns))
    canonical = re.compile(
        r"(?<![A-Za-z0-9_.-])" + re.escape(CANONICAL_PREFIX) + r"[^`\s)】」]+?\.md"
    )
    ignored = [match.span() for match in canonical.finditer(text)]
    ignored.extend(url_spans)
    # Link labels are display text; their destinations are scanned normally.
    ignored.extend(
        match.span(1) for match in re.finditer(r"\[([^]\n]*)\]\(([^)\n]+)\)", text)
    )
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
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

    architect_refs = {
        path.name for path in local_references(architect_path, references_dir)
    } - {profile_path.name}
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


if __name__ == "__main__":
    raise SystemExit(main())
