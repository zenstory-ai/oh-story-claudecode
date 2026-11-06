#!/usr/bin/env python3
"""Generate ZCode plugin-agent Markdown from canonical Claude agent templates."""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_GENERATOR = REPO_ROOT / "scripts/generate-codex-agents.py"
TOOL_ORDER = ("Read", "Glob", "Grep", "Write", "Edit", "Bash")
ZCODE_TOOLS = frozenset(TOOL_ORDER)
CLAUDE_MODEL_ALIASES = frozenset({"opus", "sonnet", "haiku"})
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def load_canonical_helpers():
    spec = importlib.util.spec_from_file_location(
        "oh_story_codex_agent_generator", CANONICAL_GENERATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load canonical parser: {CANONICAL_GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_frontmatter, module.parse_tool_list, module.publish_rendered


parse_frontmatter, parse_tool_list, publish_rendered = load_canonical_helpers()


def ordered_tools(values: set[str]) -> list[str]:
    unsupported = values - ZCODE_TOOLS
    if unsupported:
        raise ValueError(f"unsupported ZCode capabilities: {sorted(unsupported)}")
    return [tool for tool in TOOL_ORDER if tool in values]


def inline_list(values: list[str]) -> str:
    return "[" + ", ".join(values) + "]"


def block_scalar(value: str) -> list[str]:
    return ["description: |", *(f"  {line}" for line in value.splitlines())]


def adapt_body(body: str, name: str) -> str:
    adapted = body.replace(".claude/skills/", ".zcode/skills/")
    adapted = adapted.replace("当前 Claude 部署", "当前 ZCode 部署")
    adapted = adapted.replace("Claude Code subagent", "ZCode subagent")
    adapted = re.sub(
        r"(?<![A-Za-z0-9_])/(story(?:-[a-z0-9]+)*)",
        lambda match: "$" + match.group(1),
        adapted,
    )
    adapted = re.sub(
        r'`Agent\(subagent_type: "([A-Za-z0-9_-]+)"\)`',
        lambda match: f"ZCode 子代理 `{match.group(1)}`",
        adapted,
    )
    if name == "chapter-extractor":
        adapted = (
            adapted.rstrip()
            + "\n\n> ZCode 权限边界：本宿主不提供 Claude inline hook 的 per-agent 写入强隔离。"
            + "你仍只能 Write/Edit 调用方指定的单个 `_analysis_cache/输入-{批次ID}.md`，"
            + "不得写改其他路径；调用方必须复核回执与产物路径。\n"
        )
    return adapted.rstrip() + "\n"


def render_file(source: Path) -> tuple[str, str]:
    meta, body = parse_frontmatter(source.read_text(encoding="utf-8"))
    name = meta.get("name", "").strip()
    if not name:
        raise ValueError(f"{source}: missing required name")
    if name != source.stem or SAFE_NAME_RE.fullmatch(name) is None:
        raise ValueError(
            f"{source}: agent name {name!r} must match its safe filename stem {source.stem!r}"
        )
    description = meta.get("description", "").strip()
    if not description:
        raise ValueError(f"{source}: missing required description")
    if "tools" not in meta:
        raise ValueError(f"{source}: missing required tools whitelist")
    declared = parse_tool_list(meta["tools"], "tools")
    denied = (
        parse_tool_list(meta["disallowedTools"], "disallowedTools")
        if "disallowedTools" in meta
        else set()
    )
    effective = declared - denied
    tools = ordered_tools(effective)
    denied_tools = ordered_tools(denied)
    if not tools:
        raise ValueError(f"{source}: tools whitelist has zero effective tools")

    raw_turns = meta.get("maxTurns", "").strip()
    if not raw_turns or not raw_turns.isdigit() or int(raw_turns) <= 0:
        raise ValueError(f"{source}: maxTurns must be a positive integer")

    raw_model = meta.get("model", "").strip()
    model = "inherit" if not raw_model or raw_model in CLAUDE_MODEL_ALIASES else raw_model
    output = ["---", f"name: {name}", *block_scalar(description), f"model: {model}"]
    output.append(f"tools: {inline_list(tools)}")
    if "disallowedTools" in meta:
        output.append(f"disallowedTools: {inline_list(denied_tools)}")
    output.extend(
        (
            f"maxTurns: {int(raw_turns)}",
            "injectAgentsMd: false",
            "---",
            "",
            adapt_body(body, name),
        )
    )
    return f"{name}.md", "\n".join(output).rstrip() + "\n"


def render_all(source_dir: Path) -> dict[str, str]:
    if not source_dir.is_dir():
        raise ValueError(f"source directory does not exist: {source_dir}")
    sources = sorted(source_dir.glob("*.md"))
    if not sources:
        raise ValueError(f"source directory contains no agent markdown files: {source_dir}")
    rendered: dict[str, str] = {}
    for source in sources:
        filename, output = render_file(source)
        if filename in rendered:
            raise ValueError(f"duplicate generated agent filename: {filename}")
        rendered[filename] = output
    return rendered


def check_rendered(rendered: dict[str, str], destination: Path) -> None:
    actual = {path.name for path in destination.glob("*.md")} if destination.is_dir() else set()
    expected = set(rendered)
    problems = [*(f"missing: {name}" for name in sorted(expected - actual))]
    problems.extend(f"stale: {name}" for name in sorted(actual - expected))
    for name in sorted(expected & actual):
        if (destination / name).read_text(encoding="utf-8") != rendered[name]:
            problems.append(f"drifted: {name}")
    if problems:
        raise ValueError("generated ZCode agents are stale: " + ", ".join(problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=REPO_ROOT / "skills/story-setup/references/templates/agents",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=REPO_ROOT / "skills/story-setup/references/zcode/agents",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render_all(args.source)
    if args.check:
        check_rendered(rendered, args.dest)
        print(f"OK: {len(rendered)} generated ZCode agents are current")
    else:
        publish_rendered(rendered, args.dest, pattern="*.md")
        print(f"Generated {len(rendered)} ZCode agent files in {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
