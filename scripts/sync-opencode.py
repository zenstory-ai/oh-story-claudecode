#!/usr/bin/env python
"""Sync Claude Code agent templates to OpenCode format.

Scans templates/agents/*.md, converts frontmatter to opencode format,
and writes to opencode/agents/. Also syncs CLAUDE.md.tmpl -> AGENTS.md.tmpl.
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# agent 正文里表达 shell 步骤的写法：「执行 / 运行 / 跑 `<命令>`」。只认「执行」会漏——
# #283 给只读 agent 写的越权指令用的正是「运行 `tracking_commit.py check`」，两层守卫都没拦住。
# 只读 agent 若出现这种指令，生成直接失败：OpenCode shell.ts 只检查 command 的直接父节点，
# 即使“完整命令字面量”白名单也会被 `( command ) > 正文.md` 的 subshell 外层重定向绕过。
BODY_COMMAND_RE = re.compile(r"(?:执行|运行|跑) `([^`]+)`")
# 委派给别人跑的不算本 agent 的 shell 步骤（「由父流程提示重新运行 X」「提示调用方在主会话跑 X」）。
# 只在同一行出现委派主语时豁免，避免把「自己跑」写成委派句式蒙混过关。
BODY_DELEGATION_RE = re.compile(r"(调用方|父流程|主会话|用户|由.{0,6}提示)")
CAPABILITY_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def body_bash_commands(body: str) -> list[str]:
    """从 agent 正文抽出它明确要求执行的命令（按出现顺序去重）。

    刻意不用「agent 名字硬编码集合」——那正是早前审计在 generate-codex-agents.py 里点名的
    反模式：名单与正文各自漂移，新加了指令的 agent 拿不到权限、删了指令的 agent 白留着权限。
    这里以正文为唯一事实来源；只读 agent 抽到任何命令都会在转换阶段中断。
    """
    commands: list[str] = []
    for line in body.splitlines():
        if BODY_DELEGATION_RE.search(line):
            continue
        for match in BODY_COMMAND_RE.finditer(line):
            command = match.group(1).strip()
            if command and command not in commands:
                commands.append(command)
    return commands


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML-like frontmatter and body from markdown content."""
    # 结束分隔符必须是独占一行的 `---`（锚定 "\n---\n"），不能用 content.split("---", 2)：
    # 后者会被 frontmatter 值里的三连字符（描述里的 `---`、注释里的 `---`）当成结束标记，
    # 把剩余键连同 permission/steps 一起截断进正文，且静默 exit 0。
    # 与同源生成器 generate-codex-agents.py 的解析口径保持一致。
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---\n", len("---"))
    if end < 0:
        return {}, content
    fm_text = content[len("---") : end].strip()
    body = content[end + len("\n---") :]
    fm = {}
    lines = fm_text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()

            if val == "|":
                continuation = []
                i += 1
                while i < len(lines):
                    cont_line = lines[i]
                    if cont_line.startswith((" ", "\t")) and cont_line.strip():
                        continuation.append(cont_line.strip())
                        i += 1
                    elif not cont_line.strip():
                        continuation.append("")
                        i += 1
                    else:
                        break
                fm[key] = "\n".join(continuation).strip()
                continue
            else:
                fm[key] = val

        i += 1

    return fm, body


def convert_claude_to_opencode(fm: dict, body: str) -> dict:
    """Convert Claude Code agent frontmatter to OpenCode format.

    `body` 不是可选的：bash 白名单按「正文是否真的要求执行该命令」逐个 agent 授权，
    少传一个正文就等于凭空收紧/放宽权限，所以这里强制调用方交出正文。
    """
    result = {}
    name = fm.get("name", "")

    if "description" in fm:
        result["description"] = fm["description"]

    result["mode"] = "subagent"

    tools = _parse_list(fm["tools"], "tools") if "tools" in fm else []
    disallowed = (
        _parse_list(fm["disallowedTools"], "disallowedTools")
        if "disallowedTools" in fm
        else []
    )
    denied_tools = set(disallowed)
    effective_tools = set(tools) - denied_tools

    perm = {}
    read_like = {"Read", "Glob", "Grep"}
    if effective_tools & read_like:
        perm["read"] = "allow"
    elif denied_tools & read_like:
        perm["read"] = "deny"
    has_write = any(t in tools for t in ("Write", "Edit"))
    has_edit_disallowed = any(t in disallowed for t in ("Write", "Edit"))
    creation_only = (
        "Write" in tools
        and "Write" not in disallowed
        and "Edit" in disallowed
    )

    # OpenCode's aggregate edit permission controls both file creation and edits.
    # A canonical creation-only agent (effective Write + denied Edit) therefore
    # needs edit: allow regardless of its name. All other explicit denials retain
    # priority over allowed Write/Edit declarations.
    if creation_only:
        perm["edit"] = "allow"
    elif has_edit_disallowed:
        perm["edit"] = "deny"
    elif has_write:
        perm["edit"] = "allow"

    # bash 同样走 "disallowedTools 优先"。OpenCode 未声明 bash 权限时默认为 ask；只读 agent
    # 必须写成标量 deny，让上游 disabled() 直接摘掉 bash 工具。不要加“只读命令”白名单：
    # shell.ts 只鉴权 command 的直接父节点，`( allowlisted-command ) > 正文.md` 会把外层重定向
    # 藏在 subshell 外，字面量白名单也守不住文件系统边界。
    mentioned_bash = body_bash_commands(body)
    restricted_bash = "Bash" in disallowed
    if restricted_bash:
        if mentioned_bash:
            raise ValueError(
                f"{name or '<unnamed>'}: 只读 agent 禁止 Bash，但正文要求执行 "
                + "、".join(f"`{command}`" for command in mentioned_bash)
                + "；改写正文以使用宿主已提供的工作区和 Read/Glob/Grep，不得开放 shell 例外。"
            )
        perm["bash"] = "deny"
    elif "Bash" in tools:
        perm["bash"] = "allow"
    if perm:
        result["permission"] = perm

    if "maxTurns" in fm:
        try:
            result["steps"] = int(fm["maxTurns"])
        except ValueError:
            pass

    return result


def _parse_list(val: str, field: str) -> list[str]:
    """Parse the supported inline capability-list subset or reject it."""
    if not val:
        raise ValueError(
            f"{field}: empty or block-style capability declarations are unsupported"
        )
    match = re.fullmatch(r"\[\s*(.*?)\s*\]", val)
    if not match:
        raise ValueError(f"{field}: expected an inline list like [Read, Glob]")
    inner = match.group(1)
    if not inner.strip():
        return []
    parsed: list[str] = []
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
        parsed.append(item)
    return parsed


def format_frontmatter(fm: dict) -> str:
    """Format frontmatter dict to YAML-like string."""
    lines = ["---"]
    for key, value in fm.items():
        if key == "permission" and isinstance(value, dict):
            lines.append("permission:")
            for pk, pv in value.items():
                if isinstance(pv, dict):
                    # 命令 glob 形式（如 bash）：glob 键必须加引号，裸 `*` 在 YAML 里是别名标记。
                    # 严禁对这里的键排序：OpenCode 用 findLast 解析，后写的规则覆盖先写的，
                    # 键顺序即优先级。必须按 dict 的插入顺序原样输出。
                    lines.append(f"  {pk}:")
                    for glob, action in pv.items():
                        lines.append(f'    "{glob}": {action}')
                else:
                    lines.append(f"  {pk}: {pv}")
        elif key == "description" and "\n" in value:
            lines.append("description: |")
            for desc_line in value.split("\n"):
                lines.append(f"  {desc_line}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def replace_claude_paths(body: str) -> str:
    """Replace .claude/ path references with .opencode/ equivalents.

    路径规则段由 fix_path_rules_section() 幂等处理，无需手动修复。
    """
    replacements = [
        (".claude/skills/", ".opencode/skills/"),
        (".claude/agents/", ".opencode/agents/"),
        (".claude/hooks/", ".opencode/hooks/"),
        ("~/.claude/", "~/.config/opencode/"),
        ("$HOME/.claude/", "$HOME/.config/opencode/"),
        ("CLAUDE.md", "AGENTS.md"),
    ]
    for old, new in replacements:
        if old in body:
            body = body.replace(old, new)
    return body


def fix_path_rules_section(body: str) -> str:
    """Replace the reference file path rules section with correct opencode paths.

    Detects the "参考文件路径规则" section and replaces it with the one
    canonical path that story-setup deploys for OpenCode.
    This is idempotent — running multiple times produces the same output.
    """
    # Some agents do not read reference files and intentionally have no such
    # section. Only warn when the section marker exists but its shape drifted.
    if "参考文件路径规则" not in body:
        return body

    pattern = r"(## 参考文件路径规则\s*\*\*确定项目根目录：\*\*.*?\s*)读取参考文件时.*?(?=\s*禁止只读|\r?\n## )"

    replacement = (
        r"\1"
        r"读取参考文件时，直接 Read 当前 OpenCode 部署的 canonical 路径，禁止先用 Glob/Grep 搜索：\n"
        r"1. `{项目根}/skills/story-setup/references/agent-references/{文件名}`\n"
        r"\n"
        r"文件不存在时返回缺失事实，由父流程提示重新运行 `/story-setup`；不要探测其他 CLI 的目录。"
    )

    new_body, count = re.subn(pattern, replacement, body, flags=re.DOTALL)
    if count == 0:
        print(
            "  [WARN] fix_path_rules_section: 未检测到路径规则段，可能源模板格式已变更",
            file=sys.stderr,
        )
    return new_body


def file_status(dst: Path, output: str) -> tuple[str, bool]:
    """Compare one generated file without mutating the destination."""
    if not os.path.lexists(dst):
        return "missing", True
    if dst.is_symlink() or not dst.is_file():
        return "stale", True
    old_content = dst.read_text(encoding="utf-8")
    if old_content == output:
        return "unchanged", False
    return "stale", True


def render_agents() -> dict[str, str]:
    """Validate and render every OpenCode agent before any destination write."""
    src_dir = ROOT / "skills/story-setup/references/templates/agents"
    sources = sorted(src_dir.glob("*.md"))
    if not sources:
        raise RuntimeError(f"no agent markdown files found in {src_dir}")
    rendered: dict[str, str] = {}
    for md_file in sources:
        content = md_file.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        name = str(fm.get("name", "")).strip()
        description = str(fm.get("description", "")).strip()
        if not name:
            raise ValueError(f"{md_file}: missing agent name")
        if name != md_file.stem:
            raise ValueError(
                f"{md_file}: agent name {name!r} must match filename {md_file.stem!r}"
            )
        if not description:
            raise ValueError(f"{md_file}: missing agent description")
        # 用**源模板正文**（未做 .claude→.opencode 路径替换）推导 bash 白名单：
        # 授权依据是源定义里写没写这条命令，不是生成产物的措辞。
        new_fm = convert_claude_to_opencode(fm, body)
        new_body = replace_claude_paths(body)
        new_body = fix_path_rules_section(new_body)  # 覆盖路径规则段的错误替换
        output = format_frontmatter(new_fm) + new_body
        output = output.rstrip("\n") + "\n"  # 规范行尾为单个换行，避免 EOF 空行
        if md_file.name in rendered:
            raise ValueError(f"duplicate generated agent filename: {md_file.name}")
        rendered[md_file.name] = output
    return rendered


def agent_statuses(
    rendered: dict[str, str], dst_dir: Path, check: bool
) -> tuple[list[str], bool]:
    """Return deterministic status lines for the generated agent surface."""
    results: list[str] = []
    changed = False
    for filename, output in rendered.items():
        dst_file = dst_dir / filename
        raw_status, file_changed = file_status(dst_file, output)
        if check:
            status = raw_status
        else:
            status = (
                "created"
                if raw_status == "missing"
                else "updated"
                if raw_status == "stale"
                else raw_status
            )
        changed = changed or file_changed
        results.append(f"  [{status}] {dst_file.name}")

    for stale in sorted(dst_dir.glob("*.md")):
        if stale.name in rendered:
            continue
        changed = True
        results.append(f"  [{'extra' if check else 'deleted'}] {stale.name}")

    return results, changed


def render_agents_md() -> str:
    """Validate and render CLAUDE.md.tmpl for OpenCode."""
    src = ROOT / "skills/story-setup/references/templates/CLAUDE.md.tmpl"
    if not src.is_file():
        raise RuntimeError(f"source template not found: {src}")

    content = src.read_text(encoding="utf-8")
    new_content = replace_claude_paths(content)
    return new_content.rstrip("\n") + "\n"  # 规范行尾为单个换行，避免 EOF 空行


def publish_tree(rendered: dict[str, str], agents_md: str, dst_root: Path) -> None:
    """Publish generated OpenCode files with rollback, preserving manual assets."""
    if dst_root.is_symlink():
        raise ValueError(f"destination directory must not be a symlink: {dst_root}")
    if dst_root.exists() and not dst_root.is_dir():
        raise ValueError(f"destination is not a directory: {dst_root}")
    existing_agents = dst_root / "agents"
    if existing_agents.is_symlink():
        raise ValueError(
            f"generated agents directory must not be a symlink: {existing_agents}"
        )
    if existing_agents.exists() and not existing_agents.is_dir():
        raise ValueError(
            f"generated agents path is not a directory: {existing_agents}"
        )

    dst_root.mkdir(parents=True, exist_ok=True)
    existing_agents.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{dst_root.name}.staging-", dir=dst_root.parent)
    )
    backup = Path(
        tempfile.mkdtemp(prefix=f".{dst_root.name}.backup-", dir=dst_root.parent)
    )
    try:
        agents_dir = staging / "agents"
        backup_agents = backup / "agents"
        agents_dir.mkdir()
        backup_agents.mkdir()
        for filename, output in rendered.items():
            with (agents_dir / filename).open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(output)

        staged_agents_md = staging / "AGENTS.md.tmpl"
        with staged_agents_md.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(agents_md)

        existing_md = sorted(existing_agents.glob("*.md"))
        for path in existing_md:
            if path.is_dir() and not path.is_symlink():
                raise IsADirectoryError(f"generated target is a directory: {path}")
            if path.is_symlink():
                (backup_agents / path.name).symlink_to(os.readlink(path))
            else:
                shutil.copy2(path, backup_agents / path.name)

        target_agents_md = dst_root / "AGENTS.md.tmpl"
        had_agents_md = os.path.lexists(target_agents_md)
        if target_agents_md.is_dir() and not target_agents_md.is_symlink():
            raise IsADirectoryError(
                f"generated target is a directory: {target_agents_md}"
            )
        if had_agents_md:
            if target_agents_md.is_symlink():
                (backup / "AGENTS.md.tmpl").symlink_to(
                    os.readlink(target_agents_md)
                )
            else:
                shutil.copy2(target_agents_md, backup / "AGENTS.md.tmpl")

        try:
            for filename in rendered:
                os.replace(agents_dir / filename, existing_agents / filename)
            os.replace(staged_agents_md, target_agents_md)
            for stale in existing_md:
                if stale.name not in rendered:
                    stale.unlink()
        except BaseException:
            # Best-effort rollback: a single un-removable file must not abort the
            # restore and strand a partial commit. Backed-up files are overwritten
            # in place; only outputs absent before the commit are removed.
            restore_names = {path.name for path in backup_agents.iterdir()}
            for current in list(existing_agents.glob("*.md")):
                if current.is_dir() and not current.is_symlink():
                    continue
                if current.name in restore_names:
                    continue
                try:
                    current.unlink()
                except OSError:
                    pass
            for original in backup_agents.iterdir():
                target = existing_agents / original.name
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
            original_agents_md = backup / "AGENTS.md.tmpl"
            try:
                if had_agents_md:
                    if original_agents_md.is_symlink():
                        if target_agents_md.is_symlink() or target_agents_md.exists():
                            target_agents_md.unlink()
                        target_agents_md.symlink_to(os.readlink(original_agents_md))
                    else:
                        shutil.copy2(original_agents_md, target_agents_md)
                elif os.path.lexists(target_agents_md) and (
                    not target_agents_md.is_dir() or target_agents_md.is_symlink()
                ):
                    target_agents_md.unlink()
            except OSError:
                pass
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify generated files without modifying the working tree",
    )
    args = parser.parse_args()

    # The agents and top-level instructions form one generated adapter. Render
    # and validate both phases before inspecting or publishing either one.
    rendered = render_agents()
    agents_md = render_agents_md()
    dst_root = ROOT / "skills/story-setup/references/opencode"
    agent_results, agents_changed = agent_statuses(
        rendered, dst_root / "agents", args.check
    )
    raw_md_status, agents_md_changed = file_status(
        dst_root / "AGENTS.md.tmpl", agents_md
    )
    if args.check:
        md_status = raw_md_status
    else:
        md_status = (
            "created"
            if raw_md_status == "missing"
            else "updated"
            if raw_md_status == "stale"
            else raw_md_status
        )

    print("=== opencode sync script ===\n")
    print("1. Syncing agents...")
    for r in agent_results:
        print(r)

    print("\n2. Syncing AGENTS.md.tmpl...")
    print(f"  [{md_status}] AGENTS.md.tmpl")

    if args.check:
        if agents_changed or agents_md_changed:
            print(
                "\nERROR: generated OpenCode templates are out of sync.",
                file=sys.stderr,
            )
            return 1
        print("\nOK: generated OpenCode templates are in sync.")
        return 0

    publish_tree(rendered, agents_md, dst_root)

    print("\n3. Manual maintenance required:")
    print("  - skills/story-setup/references/opencode/plugin.ts (hooks logic)")
    print("  - skills/story-setup/references/opencode/commands/ (slash commands)")
    print(
        "  - skills/story-setup/references/opencode/opencode.json.patch (config fragment)"
    )
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
