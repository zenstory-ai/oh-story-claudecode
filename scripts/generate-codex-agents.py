#!/usr/bin/env python3
"""Generate Codex custom-agent TOML templates from Claude agent markdown.

The Claude/OpenCode agent markdown remains the source of truth for role text.
Codex expects standalone TOML files with at least name, description, and
`developer_instructions`; this script performs a deterministic conversion.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MUTATING_TOOLS = frozenset({"Write", "Edit", "Bash"})
CAPABILITY_FIELDS = frozenset({"tools", "disallowedTools"})
CAPABILITY_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
NICKNAMES = {
    "chapter-extractor": ["Chapter Extractor", "Scene Splitter"],
    "character-designer": ["Character Designer", "Voice Crafter"],
    "consistency-checker": ["Consistency Checker", "Continuity Guard"],
    "narrative-writer": ["Narrative Writer", "Prose Crafter"],
    "story-architect": ["Story Architect", "Plot Architect"],
    "story-explorer": ["Story Explorer", "Lore Scout"],
    "story-researcher": ["Story Researcher", "Source Scout"],
}


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    raw = text[4:end]
    body = text[end + len("\n---\n") :].lstrip()
    data: dict[str, str] = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), (m.group(2) or "").rstrip()
        if value == "|":
            block: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt and not nxt.startswith((" ", "\t")):
                    break
                block.append(nxt[2:] if nxt.startswith("  ") else nxt.lstrip())
                i += 1
            data[key] = "\n".join(block).strip()
            continue
        normalized = value.strip()
        data[key] = (
            normalized
            if key in CAPABILITY_FIELDS
            else normalized.strip('"').strip("'")
        )
        i += 1
    return data, body


def toml_basic_string(value: str) -> str:
    # Use a multi-line basic string so Chinese instructions and Markdown remain readable.
    escaped = value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return f'"""\n{escaped.rstrip()}\n"""'


def toml_list(values: list[str]) -> str:
    return "[" + ", ".join(repr(v).replace("'", '"') for v in values) + "]"


def parse_tool_list(value: str, field: str) -> set[str]:
    """Parse the supported inline capability-list subset or reject it."""
    if not value:
        raise ValueError(
            f"{field}: empty or block-style capability declarations are unsupported"
        )
    match = re.fullmatch(r"\[\s*(.*?)\s*\]", value)
    if not match:
        raise ValueError(f"{field}: expected an inline list like [Read, Glob]")
    inner = match.group(1)
    if not inner.strip():
        return set()
    parsed: set[str] = set()
    for raw_item in inner.split(","):
        item = raw_item.strip()
        if not item:
            raise ValueError(f"{field}: empty capability-list item")
        if item[0] in {'"', "'"}:
            quote = item[0]
            if len(item) < 2 or item[-1] != quote or quote in item[1:-1]:
                raise ValueError(f"{field}: malformed quoted capability {item!r}")
            item = item[1:-1]
        elif '"' in item or "'" in item:
            raise ValueError(f"{field}: malformed quoted capability {item!r}")
        if CAPABILITY_NAME_RE.fullmatch(item) is None:
            raise ValueError(f"{field}: invalid capability name {item!r}")
        parsed.add(item)
    return parsed


def is_read_only(meta: dict[str, str]) -> bool:
    """Derive filesystem confinement from effective canonical capabilities."""
    declared = (
        parse_tool_list(meta["tools"], "tools") if "tools" in meta else set()
    )
    denied = (
        parse_tool_list(meta["disallowedTools"], "disallowedTools")
        if "disallowedTools" in meta
        else set()
    )
    if not declared:
        return MUTATING_TOOLS.issubset(denied)
    effective = declared - denied
    return effective.isdisjoint(MUTATING_TOOLS)


def adapt_body_for_codex(body: str, name: str) -> str:
    """Translate Claude/OpenCode caller terminology to Codex custom-agent wording."""
    adapted = body.replace("subagent_type", "agent_type")
    adapted = adapted.replace(
        ".claude/skills/story-setup/references/agent-references/",
        ".codex/skills/story-setup/references/agent-references/",
    )
    adapted = adapted.replace("当前 Claude 部署", "当前 Codex 部署")
    adapted = re.sub(
        r"(?<![A-Za-z0-9_])/(story(?:-[a-z0-9]+)*)",
        lambda match: "$" + match.group(1),
        adapted,
    )
    adapted = adapted.replace("Claude Code subagent", "Codex custom agent")
    return (
        adapted.rstrip()
        + "\n\n---\n\n"
        + "Codex adaptation notes:\n"
        + f'- Codex callers should request this custom agent with `agent_type: "{name}"` when the current runtime exposes project-local custom agents.\n'
        + "- If Codex reports `unknown agent_type` or the custom-agent registry is unavailable, the parent workflow must fall back to solo/direct execution and report the fallback instead of failing.\n"
        + "- Stay within this agent's role boundary; escalate adjacent work back to the parent agent.\n"
        + "- Use the deployed Codex reference path only: `.codex/skills/story-setup/references/agent-references/`. If it is missing, report the missing deployment instead of probing other CLI directories.\n"
        + "- Do not assume Claude-only tool names or frontmatter fields exist in Codex.\n"
    )


def render_file(src: Path) -> tuple[str, str]:
    """Validate and render one source without touching the destination."""
    text = src.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    name = meta.get("name") or src.stem
    if name != src.stem or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) is None:
        raise ValueError(
            f"{src}: agent name {name!r} must match its safe filename stem {src.stem!r}"
        )
    description = meta.get("description", "").strip()
    if not description:
        raise ValueError(f"{src}: missing description")
    instructions = adapt_body_for_codex(body, name)
    out = [
        f'name = "{name}"',
        f"description = {toml_basic_string(description)}",
        f"nickname_candidates = {toml_list(NICKNAMES.get(name, [name]))}",
    ]
    if is_read_only(meta):
        out.append('sandbox_mode = "read-only"')
    out.append(f"developer_instructions = {toml_basic_string(instructions)}")
    return f"{name}.toml", "\n".join(out) + "\n"


def publish_rendered(rendered: dict[str, str], dst_dir: Path) -> list[Path]:
    """Publish generated files with rollback while leaving the directory present."""
    if dst_dir.is_symlink():
        raise ValueError(f"destination directory must not be a symlink: {dst_dir}")
    if dst_dir.exists() and not dst_dir.is_dir():
        raise ValueError(f"destination is not a directory: {dst_dir}")

    dst_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{dst_dir.name}.staging-", dir=dst_dir.parent)
    )
    backup = Path(
        tempfile.mkdtemp(prefix=f".{dst_dir.name}.backup-", dir=dst_dir.parent)
    )
    try:
        for filename, output in rendered.items():
            with (staging / filename).open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(output)

        existing = sorted(dst_dir.glob("*.toml"))
        for path in existing:
            if path.is_dir() and not path.is_symlink():
                raise IsADirectoryError(f"generated target is a directory: {path}")
            if path.is_symlink():
                (backup / path.name).symlink_to(os.readlink(path))
            else:
                shutil.copy2(path, backup / path.name)

        try:
            for filename in rendered:
                os.replace(staging / filename, dst_dir / filename)
            for stale in existing:
                if stale.name not in rendered:
                    stale.unlink()
        except BaseException:
            # Best-effort rollback: a single un-removable file (immutable flag,
            # lock, read-only mount) must not abort the restore and strand a
            # partial commit. Files present in the backup are overwritten in
            # place; only outputs that were absent before the commit are removed.
            restore_names = {path.name for path in backup.iterdir()}
            for current in list(dst_dir.glob("*.toml")):
                if current.is_dir() and not current.is_symlink():
                    continue
                if current.name in restore_names:
                    continue
                try:
                    current.unlink()
                except OSError:
                    pass
            for original in backup.iterdir():
                target = dst_dir / original.name
                try:
                    if original.is_symlink():
                        if target.is_symlink() or target.exists():
                            target.unlink()
                        target.symlink_to(os.readlink(original))
                    else:
                        # target is provably a regular file (a commit only
                        # os.replace's regular staged outputs), so copy2 safely
                        # overwrites it in place.
                        shutil.copy2(original, target)
                except OSError:
                    pass
            raise
        return [dst_dir / filename for filename in rendered]
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / "skills/story-setup/references/templates/agents",
        help="Claude agent template directory",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=REPO_ROOT / "skills/story-setup/references/codex/agents",
        help="Codex TOML output directory",
    )
    args = parser.parse_args()
    src_dir = args.source
    dst_dir = args.dest
    if not src_dir.is_dir():
        parser.error(f"source directory does not exist: {src_dir}")
    sources = sorted(src_dir.glob("*.md"))
    if not sources:
        parser.error(f"source directory contains no agent markdown files: {src_dir}")
    # Render every source before the first destination write. A malformed later
    # template must not leave a half-updated generated directory.
    rendered: dict[str, str] = {}
    for path in sources:
        filename, output = render_file(path)
        if filename in rendered:
            raise ValueError(f"duplicate generated agent filename: {filename}")
        rendered[filename] = output

    generated = publish_rendered(rendered, dst_dir)
    print(f"Generated {len(generated)} Codex agent files in {dst_dir}")
    for path in generated:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
