#!/usr/bin/env python3
"""check-reference-routing.py — 长短篇写作参考文件的路由、子代理副本和模板标签三条守卫。

1. 路由与预算互查：story-long-write、story-short-write 的 SKILL.md「写前必读」里的总表（长篇含「本章技法」表）
   是各自唯一的文件级路由。表里点名的每个 references 文件，必须出现在 scripts/doc-budget.json 里该 skill 的某条路径里；
   该 skill 路径里登记的每个 references 文件，也必须出现在总表里（例外见 ROUTED_SKILLS，写明原因）。
   只读得到一边的文件，要么是路由漏写（模型不知道什么时候读），要么是预算漏算（每次调用的加载量失真）。
2. 子代理副本链接闭包：story-setup/references/agent-references/ 下每份文件里的 Markdown 链接、
   反引号路径和正文里点名的 *.md 文件名，都必须指向子代理那边存在的文件（同目录副本，或项目里的
   `设定/`、`大纲/` 这类中文路径）。指向写作端 references、SKILL.md 这类子代理读不到的文件判红。
3. 模板围栏标签：scripts/current-contract.json 的 template_fences 是标签名的唯一清单。每个标签在
   全部 skills/*/references 里（不算 shared-references.json 登记的同步副本）恰好出现一次；
   出现了清单外的标签、或运行时脚本按名取的标签不在清单里、不在点名的文件里，都判红。

用法：python3 scripts/check-reference-routing.py [--root 仓库根] [--self-test]
Exit: 0 = 通过；1 = 有违规；2 = 仓库结构读不了。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

LONG = "skills/story-long-write"
SHORT = "skills/story-short-write"
AGENT_REFS = "skills/story-setup/references/agent-references"
AGENT_PREFIX = "story-setup/references/agent-references/"

# 纳入路由互查的 skill，以及预算里登记、总表里不逐个点名的文件：(相对 references 的路径前缀, 原因)。
ROUTED_SKILLS = (
    (LONG, "长篇", (
        ("genre-prose-cards/",
         "单张题材卡由组装脚本按「题材类型」匹配后在核对报告里点名（匹配不到给流派兜底卡），"
         "总表只写「核对报告点名的卡」；预算里登记最大的两张和兜底卡算最坏情况。"),
    )),
    (SHORT, "短篇", (
        ("genre-styles/",
         "题材包按 设定.md 的题材十选一，总表写 `genre-styles/{题材}.md`；预算里十个题材包各登记一条分支。"),
    )),
)

MD_NAME = r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.md"
TABLE_MD_RE = re.compile(r"(?<![A-Za-z0-9_./-])([a-z0-9][a-z0-9_-]*\.md)(?![A-Za-z0-9_.-])")
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
# 一段路径：ASCII 目录段（可带 {占位}）加 ASCII 文件名；中文目录下的文件（设定/x.md）整段是项目路径，
# 前面紧挨 / 的不单独取。
PATH_RE = re.compile(r"(?<![A-Za-z0-9_./{}-])((?:[A-Za-z0-9_.{}-]+/)*" + MD_NAME + r")(?![A-Za-z0-9_.-])")
CALL_RE = re.compile(r"templates\(\s*\"([^\"]+\.md)\"((?:\s*,\s*\"[^\"]+\")+)\s*\)")
BLOCK_CALL_RE = re.compile(r"template_block\([^,()]+,\s*\"([^\"]+)\"")


class Violations(list):
    def add(self, rule: str, message: str) -> None:
        self.append(f"[{rule}] {message}")


# ---------- 1. 路由与预算互查 ----------


def routing_table_files(skill_text: str) -> set[str]:
    """SKILL.md「写前必读」一节里各张表（总表、本章技法表）点名的 references 文件名。"""
    match = re.search(r"^## 写前必读[^\n]*\n(.*?)(?=^## |\Z)", skill_text, re.M | re.S)
    if not match:
        return set()
    names: set[str] = set()
    for line in match.group(1).splitlines():
        if line.lstrip().startswith("|"):
            names.update(TABLE_MD_RE.findall(line))
    return names


def budget_skill_files(budget: dict, skill_rel: str) -> dict[str, list[str]]:
    """doc-budget 里该 skill 的路径（任一文件在 skill 目录下）登记的 references 文件 → 出现在哪些路径。"""
    refs_rel = f"{skill_rel}/references"
    found: dict[str, list[str]] = {}
    for path in budget.get("paths", []):
        files = list(path.get("files", []))
        for branch in path.get("branches", []):
            files += branch.get("files", [])
        if not any(f.startswith(skill_rel + "/") for f in files):
            continue
        for item in files:
            item = item.split("#", 1)[0]
            if item.startswith(refs_rel + "/"):
                found.setdefault(item[len(refs_rel) + 1:], []).append(path["label"])
    return found


def check_routing(root: Path, out: Violations) -> None:
    budget_doc = json.loads((root / "scripts/doc-budget.json").read_text(encoding="utf-8"))
    for skill_rel, kind, exceptions in ROUTED_SKILLS:
        skill = root / skill_rel / "SKILL.md"
        refs = root / skill_rel / "references"
        if not skill.is_file():
            out.add("路由", f"{skill_rel}/SKILL.md 不存在")
            continue
        table = routing_table_files(skill.read_text(encoding="utf-8"))
        if not table:
            out.add("路由", f"{skill.relative_to(root)} 的「写前必读」里没找到读取总表")
            continue
        budget = budget_skill_files(budget_doc, skill_rel)
        for name in sorted(table):
            if not (refs / name).is_file():
                out.add("路由", f"{kind} SKILL.md 总表点名的 references/{name} 不存在")
            elif name not in budget:
                out.add("路由", f"{kind} SKILL.md 总表点名了 references/{name}，doc-budget.json 没有一条{kind}路径登记它"
                        "——加进对应时刻的路径或分支，否则这次读取不计入每次调用的加载量")
        for name, labels in sorted(budget.items()):
            if name in table or any(name.startswith(prefix) for prefix, _ in exceptions):
                continue
            out.add("路由", f"doc-budget.json 的{kind}路径（{labels[0]}）登记了 references/{name}，{kind} SKILL.md 总表里没有"
                    "——总表是唯一的读取清单，补进对应时刻那一行，或确实不该读就从预算里删掉")


# ---------- 2. 子代理副本链接闭包 ----------


def is_project_path(token: str) -> bool:
    """项目里的路径：首段带中文（设定/、大纲/、对标/{书}/…）、以 { 占位或 .story/ 起头。"""
    head = token.split("/", 1)[0]
    return bool(re.search(r"[^\x00-\x7f]", head)) or head.startswith("{") or head in (".story", "~")


def agent_ref_tokens(text: str):
    """(行号, 种类, 目标)：Markdown 链接、反引号里的路径、正文里点名的 *.md。围栏里的也算（子代理一样会读）。"""
    for number, line in enumerate(text.splitlines(), 1):
        for match in LINK_RE.finditer(line):
            target = match.group(1).strip().split()[0].split("#", 1)[0]
            if target and not re.match(r"^[a-z]+:", target):
                yield number, "链接", target
        rest = LINK_RE.sub(" ", line)
        for match in CODE_RE.finditer(rest):
            for path in PATH_RE.findall(match.group(1)):
                yield number, "反引号路径", path
        for path in PATH_RE.findall(CODE_RE.sub(" ", rest)):
            yield number, "文件名", path


def check_agent_closure(root: Path, out: Violations) -> None:
    base = root / AGENT_REFS
    long_refs = root / LONG / "references"
    if not base.is_dir():
        out.add("子代理副本", f"{AGENT_REFS} 不存在")
        return
    # 不带 .md 的写法（「见 workflow-volume「排纲刻度」」）同样指向子代理读不到的文件：
    # 写作端有、副本这边没有同名文件的 references，名字一出现就算。
    stems = sorted(p.stem for p in long_refs.glob("*.md") if not (base / p.name).exists())
    bare = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(map(re.escape, stems)) + r")(?![A-Za-z0-9_.-])") if stems else None
    for doc in sorted(base.rglob("*.md")):
        text = doc.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for name in (bare.findall(line) if bare else []):
                out.add("子代理副本", f"{doc.relative_to(root)}:{number} 提到写作端的 {name}，子代理那边没有这份文件"
                        "——改成副本里有的说法，或在 shared-references.json 给它登记副本")
        for number, kind, target in agent_ref_tokens(text):
            if is_project_path(target):
                continue
            rel = target[len(AGENT_PREFIX):] if target.startswith(AGENT_PREFIX) else target
            if "{" in rel:  # genre-prose-cards/{题材}.md：占位只要求目录在
                candidates = [base / rel.split("{", 1)[0]]
            elif kind == "链接":
                candidates = [doc.parent / rel]
            else:
                candidates = [doc.parent / rel, base / rel]
            if any(c.exists() for c in candidates):
                continue
            hint = ("：这是写作端 references 里的文件，子代理那边没有副本" if (long_refs / Path(rel).name).exists()
                    else "：子代理那边没有这个文件")
            out.add("子代理副本", f"{doc.relative_to(root)}:{number} 的{kind} {target}{hint}"
                    "——改成指向同目录副本，或在 shared-references.json 给它登记副本")


# ---------- 3. 模板围栏标签 ----------


def load_fence_module(root: Path):
    path = root / LONG / "scripts" / "template_fence.py"
    spec = importlib.util.spec_from_file_location("template_fence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def synced_copies(root: Path) -> set[Path]:
    """shared-references.json 登记的同步副本：和源文件逐字相同，不重复计数。"""
    manifest = json.loads((root / "scripts/shared-references.json").read_text(encoding="utf-8"))
    copies: set[Path] = set()
    for group in manifest.get("groups", []):
        copies.update((root / target).resolve() for target in group.get("targets", []))
    for tree in manifest.get("tree_groups", []):
        for target in tree.get("targets", []):
            copies.update((root / target / name).resolve() for name in tree.get("files", []))
    return copies


def check_template_fences(root: Path, out: Violations) -> None:
    contract = json.loads((root / "scripts/current-contract.json").read_text(encoding="utf-8"))
    tags = contract.get("template_fences")
    if not isinstance(tags, list) or not tags:
        out.add("模板标签", "scripts/current-contract.json 缺 template_fences 清单")
        return
    fence = load_fence_module(root)
    copies = synced_copies(root)
    where: dict[str, list[str]] = {}
    for doc in sorted(root.glob("skills/*/references/**/*.md")):
        if doc.resolve() in copies:
            continue
        for tag, line, _ in fence.template_blocks(doc.read_text(encoding="utf-8")):
            where.setdefault(tag, []).append(f"{doc.relative_to(root)}:{line}")
    for tag in tags:
        hits = where.get(tag, [])
        if not hits:
            out.add("模板标签", f"清单里的模板「{tag}」在参考文件里一处都没有（围栏信息串写 template={tag}）")
        elif len(hits) > 1:
            out.add("模板标签", f"模板「{tag}」出现了 {len(hits)} 次：{'、'.join(hits)}——只能有一处")
    for tag in sorted(set(where) - set(tags)):
        out.add("模板标签", f"{where[tag][0]} 的模板「{tag}」不在 scripts/current-contract.json 的 template_fences 清单里")
    for script in sorted(root.glob("skills/*/scripts/*.py")):
        text = script.read_text(encoding="utf-8")
        used = [(m.group(1), re.findall(r"\"([^\"]+)\"", m.group(2))) for m in CALL_RE.finditer(text)]
        used += [(None, [m.group(1)]) for m in BLOCK_CALL_RE.finditer(text)]
        for source, names in used:
            for tag in names:
                if tag not in tags:
                    out.add("模板标签", f"{script.relative_to(root)} 按名取的模板「{tag}」不在清单里")
                elif source and not any(h.split(":", 1)[0].endswith("/" + source) for h in where.get(tag, [])):
                    out.add("模板标签", f"{script.relative_to(root)} 到 {source} 取模板「{tag}」，那份文件里没有")


def run(root: Path) -> Violations:
    out = Violations()
    check_routing(root, out)
    check_agent_closure(root, out)
    check_template_fences(root, out)
    return out


# ---------- 自测 ----------


def self_test(repo: Path) -> int:
    """在临时仓库里各造一个违规，确认三条规则都会判红，修好后判绿。"""
    failures = []

    def build(tmp: Path) -> None:
        refs = tmp / LONG / "references"
        (refs / "genre-prose-cards").mkdir(parents=True)
        (tmp / LONG / "scripts").mkdir(parents=True)
        (tmp / AGENT_REFS).mkdir(parents=True)
        (tmp / "scripts").mkdir()
        (tmp / LONG / "scripts/template_fence.py").write_bytes((repo / LONG / "scripts/template_fence.py").read_bytes())
        (tmp / LONG / "SKILL.md").write_text(
            "# x\n\n## 写前必读\n\n| 时刻 | 必读 |\n|---|---|\n| 出细纲 | `workflow-outline.md`、`outline-template.md` |\n\n## 别的\n",
            encoding="utf-8")
        (tmp / SHORT / "references/genre-styles").mkdir(parents=True)
        (tmp / SHORT / "SKILL.md").write_text(
            "# s\n\n## 写前必读\n\n| 时刻 | 必读 |\n|---|---|\n| 写正文 | `workflow-draft.md`、`genre-styles/{题材}.md` |\n",
            encoding="utf-8")
        (tmp / SHORT / "references/workflow-draft.md").write_text("# d\n", encoding="utf-8")
        (tmp / SHORT / "references/genre-styles/甜宠.md").write_text("# g\n", encoding="utf-8")
        (refs / "workflow-outline.md").write_text("# w\n", encoding="utf-8")
        (refs / "outline-template.md").write_text("# t\n\n```markdown template=细纲\n- 核心事件：\n```\n", encoding="utf-8")
        (refs / "genre-prose-cards/年代.md").write_text("# 卡\n", encoding="utf-8")
        (tmp / AGENT_REFS / "plot.md").write_text("见 [卡](genre-prose-cards/年代.md) 与 `设定/题材定位.md`\n", encoding="utf-8")
        (tmp / AGENT_REFS / "genre-prose-cards").mkdir()
        (tmp / AGENT_REFS / "genre-prose-cards/年代.md").write_text("# 卡\n", encoding="utf-8")
        (tmp / "scripts/doc-budget.json").write_text(json.dumps({"paths": [{"label": "长篇出细纲", "files": [
            f"{LONG}/SKILL.md", f"{LONG}/references/workflow-outline.md", f"{LONG}/references/outline-template.md"],
            "branches": [{"label": "卡", "files": [f"{LONG}/references/genre-prose-cards/年代.md"]}]},
            {"label": "短篇写正文", "files": [f"{SHORT}/SKILL.md", f"{SHORT}/references/workflow-draft.md"],
             "branches": [{"label": "甜宠", "files": [f"{SHORT}/references/genre-styles/甜宠.md"]}]}]}),
            encoding="utf-8")
        (tmp / "scripts/current-contract.json").write_text(json.dumps({"template_fences": ["细纲"]}), encoding="utf-8")
        (tmp / "scripts/shared-references.json").write_text(json.dumps({"groups": [], "tree_groups": []}), encoding="utf-8")

    cases = [
        ("总表点名、预算没登记", lambda t: (t / LONG / "SKILL.md").write_text(
            (t / LONG / "SKILL.md").read_text(encoding="utf-8").replace("`outline-template.md` |", "`outline-template.md`、`plot.md` |"),
            encoding="utf-8") or (t / LONG / "references/plot.md").write_text("# p\n", encoding="utf-8"), "[路由]"),
        ("预算登记、总表没点名", lambda t: (t / "scripts/doc-budget.json").write_text(
            (t / "scripts/doc-budget.json").read_text(encoding="utf-8").replace(
                "outline-template.md\"]", "outline-template.md\", \"" + LONG + "/references/workflow-outline.md\", \"" + LONG + "/references/extra.md\"]"),
            encoding="utf-8"), "[路由]"),
        ("短篇预算登记、总表没点名", lambda t: ((t / SHORT / "references/agent-calls.md").write_text("# a\n", encoding="utf-8"), (t / "scripts/doc-budget.json").write_text(
            (t / "scripts/doc-budget.json").read_text(encoding="utf-8").replace(
                "workflow-draft.md\"]", "workflow-draft.md\", \"" + SHORT + "/references/agent-calls.md\"]"),
            encoding="utf-8")), "[路由]"),
        ("副本指向写作端文件", lambda t: (t / AGENT_REFS / "plot.md").write_text("按 workflow-outline.md「排纲方法」\n", encoding="utf-8"), "[子代理副本]"),
        ("副本不带 .md 点名写作端文件", lambda t: (t / AGENT_REFS / "plot.md").write_text("章数见 workflow-outline「排纲刻度」\n", encoding="utf-8"), "[子代理副本]"),
        ("副本指向 SKILL.md", lambda t: (t / AGENT_REFS / "plot.md").write_text("见 `SKILL.md`「本章技法」\n", encoding="utf-8"), "[子代理副本]"),
        ("标签重复", lambda t: (t / LONG / "references/workflow-outline.md").write_text("```markdown template=细纲\nx\n```\n", encoding="utf-8"), "[模板标签]"),
        ("标签缺失", lambda t: (t / LONG / "references/outline-template.md").write_text("```markdown\nx\n```\n", encoding="utf-8"), "[模板标签]"),
        ("清单外标签", lambda t: (t / LONG / "references/workflow-outline.md").write_text("```markdown template=卷纲\nx\n```\n", encoding="utf-8"), "[模板标签]"),
        ("脚本按名取清单外标签", lambda t: (t / LONG / "scripts/build.py").write_text('templates("outline-template.md", "大纲")\n', encoding="utf-8"), "[模板标签]"),
    ]
    with tempfile.TemporaryDirectory(prefix="routing-ok-") as tmp:
        build(Path(tmp))
        clean = run(Path(tmp))
        if clean:
            failures.append(f"干净夹具不该报错：{clean}")
    for name, mutate, rule in cases:
        with tempfile.TemporaryDirectory(prefix="routing-bad-") as tmp:
            build(Path(tmp))
            mutate(Path(tmp))
            found = run(Path(tmp))
            if not any(v.startswith(rule) for v in found):
                failures.append(f"{name}：应报 {rule}，实际 {found or '无'}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if not failures:
        print(f"OK: check-reference-routing 自测 {len(cases) + 1} 例通过")
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test(args.root)
    try:
        violations = run(args.root)
    except (OSError, json.JSONDecodeError, StopIteration) as exc:
        print(f"ERROR: 读不了仓库结构：{exc}", file=sys.stderr)
        return 2
    for violation in violations:
        print(violation)
    if violations:
        print(f"FAIL: 长短篇参考文件路由/副本/模板标签有 {len(violations)} 处问题")
        return 1
    print("OK: 长短篇 SKILL.md 总表与预算互相覆盖；子代理副本的链接都指向副本那边的文件；模板标签各恰好一处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
