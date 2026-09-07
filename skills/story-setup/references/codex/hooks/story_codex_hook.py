#!/usr/bin/env python3
"""Codex hook adapter for oh-story writing projects.

This script intentionally has no third-party dependencies. It adapts the core
story guardrails to Codex hook stdin/stdout JSON contracts.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


HOOK_CWD: Path | None = None


def read_hook_input() -> dict[str, Any]:
    global HOOK_CWD
    # Read raw UTF-8 bytes, not the locale-decoded text stream: Codex/Claude tool
    # payloads carry Chinese 正文/细纲 paths, and Windows Python defaults stdin to the
    # ANSI code page (cp1252/cp936), which mojibakes them so the prose guard never
    # matches and silently allows (issue #164 class — same fix as the bash hooks).
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    if not raw.strip():
        return {}
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return {}
        cwd = obj.get("cwd")
        if isinstance(cwd, str) and Path(cwd).is_dir():
            HOOK_CWD = Path(cwd).resolve()
        return obj
    except Exception:
        return {}


def emit(obj: dict[str, Any] | None) -> None:
    if obj:
        # Write UTF-8 bytes directly: Windows Python stdout defaults to the ANSI code
        # page and would garble/raise on the Chinese deny reasons and additionalContext.
        sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _deployed_root_from_file() -> Path | None:
    """Self-locate the project root from this script's deployed path.

    story-setup deploys this hook to <root>/.codex/hooks/story_codex_hook.py, so the
    project root is __file__'s great-grandparent. This is the most reliable resolver on
    Windows: the launcher computes the root in (Git Bash) shell as an MSYS path like
    /c/proj, which does NOT survive as a native-Python env var or cwd — but __file__ is
    always a native path. So a non-git project launched from a nested cwd still resolves.
    """
    try:
        here = Path(__file__).resolve()
    except Exception:
        return None
    if here.parent.name == "hooks" and here.parent.parent.name == ".codex":
        root = here.parent.parent.parent
        if root.is_dir():
            return root
    return None


def project_root() -> Path:
    for env_name in ("CODEX_PROJECT_DIR", "CLAUDE_PROJECT_DIR"):
        value = os.environ.get(env_name)
        if not value:
            continue
        try:
            candidate = Path(value)
            if candidate.is_dir():
                return candidate.resolve()
        except Exception:
            pass
    deployed = _deployed_root_from_file()
    if deployed is not None:
        return deployed
    start = HOOK_CWD if HOOK_CWD and HOOK_CWD.is_dir() else Path.cwd()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return start.resolve()


def safe_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _walk_project_entries(root: Path, max_depth: int = 4):
    """Yield non-ignored entries below project directories up to max_depth.

    ``max_depth`` matches ``find -maxdepth``: root children are depth 1, entries at
    depth 4 are visible, and depth 5 is not.
    Hidden directories, node_modules and directory symlinks are pruned before descent.
    """

    def walk(base: Path, remaining: int):
        if remaining <= 0:
            return
        try:
            entries = sorted(base.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        visible = [
            entry
            for entry in entries
            if not entry.name.startswith(".") and entry.name != "node_modules"
        ]
        yield from visible
        if remaining == 1:
            return
        for entry in visible:
            try:
                if entry.is_dir() and not entry.is_symlink():
                    yield from walk(entry, remaining - 1)
            except OSError:
                continue

    yield from walk(root, max_depth)


def read_active_book(root: Path) -> Path | None:
    active_file = root / ".active-book"
    if active_file.exists():
        lines = active_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        # A blank/whitespace first line must fall through to discovery, not resolve to
        # root/"" == root (mirrors the bash oracle common.sh discover_active_book, which
        # trims then requires non-empty, and the JS hook's firstLine()+truthy guard).
        declared = lines[0].strip() if lines else ""
        if declared:
            candidate = (root / declared).resolve()
            try:
                candidate.relative_to(root.resolve())
            except Exception:
                candidate = None  # type: ignore[assignment]
            if candidate and candidate.is_dir():
                return candidate
    entries = list(_walk_project_entries(root))
    for marker in ("追踪", "正文"):
        for entry in entries:
            if entry.name == marker and entry.is_dir() and not entry.is_symlink():
                return entry.parent
    for entry in entries:
        if entry.name == "正文.md" and entry.is_file() and not entry.is_symlink():
            return entry.parent
    return None


def hook_context(event: str, text: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


# ── 轻量确定性网（与 templates/hooks/check-prose-after-write.sh 内嵌 python 同实现，保持 parity）──
# 只兜「硬信号」（漏跑最伤、退化模型自己发现不了的）：截断 / 生成拒绝语·AI 自指 /
# 工程词漏进正文 / 紧邻整行复读。不依赖 check-degeneration.js，是独立的轻量网。
# 收尾标点集与深扫 oracle check-degeneration.js 的 findTruncation 对齐（[。！？!?…”"』」）)】]）：
# 】 是章尾系统播报模板的收束符（agent-references/long-chapter-hooks.md 章尾实战模板一/四），ASCII "
# 是 normalize-punctuation.js --quote-mode ascii 的合法收引号，两者都不该被判「疑似截断」。
_NET_TERMINAL = set("。！？…”』」）)!?.~—】\"")
_NET_SOFT_PATTERNS = [
    # 型号后缀（AI语言模型/AI助手/人工智能语言模型/AI模型/AI大模型）必须可选吃掉：否则前视断言
    # 紧跟在「AI」后面看到的是「语」/「助」/「模」，最典型的退化开场整类漏检。
    (re.compile(r'作为(一个)?(AI|人工智能|大?语言模型|智能助手|聊天助手)(?:语言模型|大?模型|助手|机器人)?(?=，|,|。|、|；|;|：|:|！|!|？|\?|\s|）|\)|」|』|"|】|我|无法|不能|没法|$)'), "AI 自指"),
    (re.compile(r"^(Sure|Certainly|Here'?s|As an AI|I (?:cannot|can't|am unable|apologize))"), "英文 AI 腔"),
    (re.compile(r"我(无法|不能)(继续(写|创作|生成|下去|输出)?|生成(内容|文本|正文)?|创作|续写|写作|完成(这个|本)?(章|篇|创作|请求)?)"), "生成拒绝语"),
]
_NET_HARD_PATTERNS = [
    (re.compile(r"[（(](此处|以下|这里|下文|后续)?[^）)]{0,10}(省略|略去|略过)[^）)]{0,10}[）)]"), "占位符（括号省略）"),
    (re.compile(r"(TODO|占位符|placeholder|待补充|此处待填|此处待补)"), "占位符"),
    (re.compile(r"(细纲|情节点|卷纲|功能标签|目标情绪|字数目标|章首钩子|章尾钩子|任务描述)"), "工程词泄漏"),
    (re.compile("�"), "乱码（替换字符）"),
]


def _net_is_skippable(stripped: str) -> bool:
    if not stripped:
        return True
    if stripped[0] == "#":
        return True
    if stripped == "---":
        return True
    if re.match(r"^[-—=*·•\s]+$", stripped):
        return True
    return False


# ── 毒句式（确定性 AI 句式指纹，与 JS 核 toxicPhraseFindings 同构，文案以 JS 核为准）──
# 与 check-ai-patterns.js 的同名新规则统一规格：只收确定性、低误报的句式；密度型/
# advisory 检测归 check-ai-patterns.js 深扫。全部正则线性扫描、量词有界。台词/弹幕/
# 系统播报不算：逐行把成对引号段等长问号占位（见 _toxic_mask_quoted 为何用问号而不是句号），
# 占位后仍残留引号字符（跨行对话/未闭合）的行整行跳过。
# js↔py 由 scripts/check-hook-regex-sync.sh（规范串逐字锁）与
# scripts/test-prose-net-parity.sh（fixture 逐字 diff）锁 parity。
# 单引号须成对；词内撇号（don't、O’Connor）不作为开闭引号。
_TOXIC_QUOTE_SPANS = [re.compile(r"「[^」]*」"), re.compile(r"『[^』]*』"), re.compile(r"【[^】]*】"), re.compile(r"“[^”]*”"), re.compile(r"(?<![A-Za-z0-9_])‘(?:[^’]|(?<=[A-Za-z0-9_])’(?=[A-Za-z0-9_]))*(?!(?<=[A-Za-z0-9_])’[A-Za-z0-9_])’"), re.compile(r'"[^"]*"'), re.compile(r"(?<![A-Za-z0-9_])'(?:[^']|(?<=[A-Za-z0-9_])'(?=[A-Za-z0-9_]))*(?!(?<=[A-Za-z0-9_])'[A-Za-z0-9_])'")]
_TOXIC_QUOTE_CHARS = set("「」『』【】“”‘’\"'")
# 分句起点边界（前一字符属于它才认「是A，不是B」的分句首「是」）；同时用作确认语的右边界。
_TOXIC_CLAUSE_BOUNDARY = set("，,。.！!？?；;：:、…—~ \t　")
# 疑问尾（是吗/是吧/是嘛）与确认语（是的/是啊/是呀/是呢+边界）里的「是」不是对比句系动词；
# 排除逻辑移植自 check-ai-patterns.js 的 TAG_PARTICLES / AFFIRMATION_TAG_PARTICLES。
_TOXIC_TAG_PARTICLES = ("吗", "吧", "嘛")
_TOXIC_AFFIRM_PARTICLES = ("的", "啊", "呀", "呢")
_TOXIC_TRAILER_WINDOW = 600
_TOXIC_SENTENCE_PATTERNS = [
    (re.compile(r"声音(?:并)?不[大高响亮][^。！？!?\n]{0,16}[却但偏]"), "voice-contrast", "删「不X…却Y」反差腔，直接写具体效果或动作。"),
    (re.compile(r"(?:没有[^。！？!?\n，,]{1,12}[，,]){2}"), "negation-parade", "「没有…，没有…」排比删到只剩一个或全删，改写正面在场的细节。"),
    (re.compile(r"是[^。！？!?\n，,]{1,12}[，,]\s*(?:而)?不是[^。！？!?\n]{1,20}"), "reverse-not-is", "删否定铺垫，直接写肯定项，或改成动作细节。"),
    (re.compile(r"不是[^。！？!?\n]{1,16}[，,]\s*(?:而)?是"), "not-is-comparison", "删否定铺垫，直接写肯定项，或改成动作细节。"),
]
# 「正式拉开序幕/帷幕」是场内事件的报幕式陈述，不是叙述者预告，lookbehind 排除（同 check-ai-patterns.js）。
_TOXIC_TRAILER = re.compile(r"没人知道|谁也不知道|谁也没想到|殊不知|(?:这)?才刚刚开(?:始|头)|正(?:朝着|向着)[^。！？!?\n]{0,24}(?:压|涌|袭|逼)(?:了?过去|了?过来|来)|(?<!正式)拉开(?:序幕|帷幕)|即将(?:开始|来临|降临)")
# 章尾状态总结体：与 trailer-ending 共用文末窗口，盖章过去而非预告将来（同 story_hook_core.js）。
# 收的都是 banned-words 已按名禁掉的形态；不收「(这|那)一刻…终于明白」——真人叙述里那是正常认知
# 节拍，短篇第一人称审判句还是卖点。各分支要求落在句末断言位，避免吃进条件从句/动补/成语/及物用法/否定认知。
_TOXIC_TRAILER_SUMMARY = re.compile(r"这一(?:夜|天|刻|战|年|局|役)[，,]?[^。！？!?，,\n]{0,6}(?<!命中)(?<!是)注定[^。！？!?\n]{0,8}[。！]|就这样[，,][^。！？!?，,\n]{0,8}(?:一切|全部)[^。！？!?，,\n]{0,4}(?:结束了|落幕|收场)[。！]|这一切[，,]?[^。！？!?，,\n]{0,6}(?:都)?(?:说明|意味着|结束了)(?!的)(?:(?!什么)[^。！？!?\n]){0,6}[。！]|(?:新的篇章|新的旅程|崭新的篇章|新的人生)[^。！？!?\n]{0,6}(?:开始|拉开|展开)|命运[^。！？!?\n]{0,6}齿轮")
# 「是A，不是B」的反问尾巴（…，不是吗/么/吧）不算对比句；取匹配段最后一个「不是」后的首字判断。
_TOXIC_REVERSE_TAIL = re.compile(r".*[，,]\s*(?:而)?不是([^。！？!?\n]*)$")


def _toxic_mask_quoted(line: str) -> str:
    # 占位字符用「？」而不是「。」：占位既要截断各规则的 [^。！？!?…] 否定类（？与句号在每条规则的
    # 否定类里等效），又不能落在任何规则的接受位。句号占位会替 trailer-summary 的句末 [。！] 伪造出
    # 终止符，让「这一战注定是「血屠」的开端，…」这类引号里放代号/绰号的叙述行被误报，且报出的
    # 『这一战注定是。』在原文里 grep 不到。
    # 占位长度按 UTF-16 码元计（emoji 等增补面字符算 2），与 JS 核 "？".repeat(m.length)
    # 逐字对齐——否则含 emoji 台词的行两端 masked 长度不同，trailer 窗口切点漂移。
    out = line
    for rx in _TOXIC_QUOTE_SPANS:
        out = rx.sub(lambda m: "？" * (len(m.group(0).encode("utf-16-le")) // 2), out)
    return out


def _toxic_not_is_excluded(line: str, matched: str, start: int) -> bool:
    """「是不是」疑问、翻转「是」后跟疑问尾/确认语 → 不算「不是A，(而)是B」对比句。"""
    if start > 0 and line[start - 1] == "是":
        return True
    end = start + len(matched)
    c1 = line[end] if end < len(line) else ""
    c2 = line[end + 1] if end + 1 < len(line) else ""
    if c1 in _TOXIC_TAG_PARTICLES:
        return True
    if c1 in _TOXIC_AFFIRM_PARTICLES and (c2 == "" or c2 in _TOXIC_CLAUSE_BOUNDARY):
        return True
    return False


def _toxic_reverse_not_is_excluded(line: str, matched: str, start: int) -> bool:
    """只认分句首的「是A，不是B」：句中「但是/还是/只是/他是…」的「是」一律不算（either-or
    「不是/就是/也是」与全部「X是」连词/副词合成词都被分句首判定排除）；「是的，不是…」
    确认语开头、「是不是…」问句起头、「…，不是吗/么/吧」反问尾巴不算（同 check-ai-patterns.js）。"""
    prev = line[start - 1] if start > 0 else ""
    if prev != "" and prev not in _TOXIC_CLAUSE_BOUNDARY:
        return True
    if line[start + 1:start + 3] == "不是":
        return True
    c1 = line[start + 1] if start + 1 < len(line) else ""
    c2 = line[start + 2] if start + 2 < len(line) else ""
    if (c1 in _TOXIC_TAG_PARTICLES or c1 in _TOXIC_AFFIRM_PARTICLES) and (c2 == "" or c2 in _TOXIC_CLAUSE_BOUNDARY):
        return True
    tail = _TOXIC_REVERSE_TAIL.search(matched)
    t1 = tail.group(1)[:1] if tail and tail.group(1) else ""
    if t1 in ("吗", "么", "吧"):
        return True
    return False


def _toxic_match_sentence(line: str) -> tuple[str, str, str] | None:
    """每行只报第一条命中的句式规则（复扫到净哲学：改完一处再扫下一处）。"""
    for rx, label, fix in _TOXIC_SENTENCE_PATTERNS:
        for m in rx.finditer(line):
            if label == "not-is-comparison" and _toxic_not_is_excluded(line, m.group(0), m.start()):
                continue
            if label == "reverse-not-is" and _toxic_reverse_not_is_excluded(line, m.group(0), m.start()):
                continue
            return (label, fix, m.group(0))
    return None


def toxic_phrase_findings(text: str) -> list[str]:
    findings: list[str] = []
    content: list[tuple[int, str]] = []
    for i, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if _net_is_skippable(s):
            continue
        masked = _toxic_mask_quoted(s)
        if any(ch in _TOXIC_QUOTE_CHARS for ch in masked):
            continue
        content.append((i, masked))
    for line_no, masked in content:
        hit = _toxic_match_sentence(masked)
        if hit:
            findings.append(f"第{line_no}行 毒句式[{hit[0]}]：『{hit[2][:20]}』——{hit[1]}")
    # trailer-ending 只扫文末 600 字窗口（引号占位后按行累计，边界行整行计入）。
    acc = 0
    cut = len(content)
    while cut > 0 and acc < _TOXIC_TRAILER_WINDOW:
        cut -= 1
        acc += len(content[cut][1])
    for line_no, masked in content[cut:]:
        m = _TOXIC_TRAILER.search(masked)
        if m:
            findings.append(f"第{line_no}行 毒句式[trailer-ending]：『{m.group(0)[:20]}』——删章尾预告腔，用正在发生的动作或画面收章。")
        ms = _TOXIC_TRAILER_SUMMARY.search(masked)
        if ms:
            findings.append(f"第{line_no}行 毒句式[trailer-summary]：『{ms.group(0)[:20]}』——删章尾状态总结句，收束状态是细纲的规划口径，正文落到具体动作、画面或台词上。")
    if findings:
        findings.append("毒句式是确定性 AI 指纹：本章须清零后再继续。完整扫描：node <skill>/scripts/check-ai-patterns.js --check <正文文件>")
    return findings


def prose_net_findings(text: str) -> list[str]:
    findings: list[str] = []
    content: list[tuple[int, str]] = []
    for i, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if _net_is_skippable(s):
            continue
        content.append((i, s))
        hit = False
        # 只豁免成对引号内的内容，继续检查引号外叙述。
        outside_quotes = _toxic_mask_quoted(s)
        for rx, label in _NET_SOFT_PATTERNS:
            m = rx.search(outside_quotes)
            if m:
                findings.append(f"第{i}行 元信息泄漏（{label}）：「{m.group(0)[:20]}」")
                hit = True
                break
        if hit:
            continue
        for rx, label in _NET_HARD_PATTERNS:
            m = rx.search(s)
            if m:
                findings.append(f"第{i}行 {label}：「{m.group(0)[:20]}」")
                break
    for (la, sa), (lb, sb) in zip(content, content[1:]):
        if sa == sb and len(sa) >= 8:
            findings.append(f"第{lb}行 紧邻复读：整行与上一行完全相同「{sa[:20]}」")
    if content:
        ln, last = content[-1]
        if last and last[-1] not in _NET_TERMINAL:
            findings.append(f"第{ln}行 疑似截断：结尾「…{last[-12:]}」未以标点收束")
    # 「去味:跳过」豁免与欠账门同判据（文件首 6 行）：标记在场时跳过毒句式推回，
    # 其余网（元信息/占位/复读/截断）照常——否则按拦截提示加标记的那次 Edit 会把
    # 已豁免的毒句式再次当硬信号推回。
    if not re.search(r"去味(：|:)跳过", "\n".join(re.split(r"\r?\n", text)[:6])):
        findings.extend(toxic_phrase_findings(text))
    return findings


def _is_prose_path(root: Path, abs_path: Path) -> bool:
    """正文文件判定（与 check-prose-after-write.sh 的 over-capture 门一致）：
    短篇 {书}/正文.md 且同目录有 设定.md；长篇 {书}/正文/第N章*.md 且 {书} 有 大纲/追踪/设定。"""
    base = abs_path.name
    parent = abs_path.parent.name
    if base == "正文.md":
        return (abs_path.parent / "设定.md").exists()
    if parent == "正文" and re.match(r"^第.*章.*\.md$", base):
        book = abs_path.parent.parent
        return (book / "大纲").is_dir() or (book / "追踪").is_dir() or (book / "设定").is_dir() or (book / "设定.md").exists()
    return False


def find_changed_prose_files(root: Path) -> list[Path]:
    """本回合改动过的正文文件（git 改动 + untracked），用于 Stop 兜底——Codex 无 PostToolUse，
    故内容网在回合结束的 Stop 事件按 git 改动集复扫。非 git 仓库或无改动则空（best-effort）。"""
    # diff 两支必须带 --relative（且 -- .）：不带时 git 吐的是仓库根相对路径，项目根是仓库子目录
    # （.git 在上层）时 root/rel 拼出 <root>/<proj>/<proj>/… 这种不存在的路径，被 exists() 全量丢掉
    # ——已提交章节的改稿因此整类漏扫，而 Codex 无 PostToolUse，这张 Stop 网是它唯一的内容网。
    # --relative 同时把范围收窄到 -C 的子树，与 ls-files（本就 cwd 相对）口径一致；同
    # staged_markdown_warnings 与 JS 核 stagedMarkdownWarnings。
    out: list[Path] = []
    seen: set[str] = set()
    for args in (
        ["git", "-C", str(root), "-c", "core.quotepath=false", "diff", "--relative", "--name-only", "-z", "--diff-filter=ACM", "--", "."],
        ["git", "-C", str(root), "-c", "core.quotepath=false", "diff", "--relative", "--name-only", "--cached", "-z", "--diff-filter=ACM", "--", "."],
        ["git", "-C", str(root), "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        try:
            raw = subprocess.check_output(args, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        for chunk in raw.split(b"\0"):
            if not chunk:
                continue
            rel = chunk.decode("utf-8", errors="ignore")
            if not rel.endswith(".md"):
                continue
            abs_path = (root / rel).resolve()
            key = str(abs_path)
            if key in seen or not abs_path.exists():
                continue
            if _is_prose_path(root, abs_path):
                seen.add(key)
                out.append(abs_path)
    return out


def _discover_all_books(root: Path) -> list[Path]:
    books: list[Path] = []
    seen: set[str] = set()
    for hit in _walk_project_entries(root):
        try:
            is_marker = (
                hit.name in {"追踪", "正文"}
                and hit.is_dir()
                and not hit.is_symlink()
            )
            is_body_file = (
                hit.name == "正文.md" and hit.is_file() and not hit.is_symlink()
            )
        except OSError:
            continue
        if not is_marker and not is_body_file:
            continue
        book = hit.parent
        key = str(book.resolve())
        if key not in seen:
            seen.add(key)
            books.append(book)
    return books


def tracking_checkpoint_issue(
    book: Path,
    *,
    require_state: bool = False,
    expected_last_committed: int | None = None,
) -> str | None:
    state = book / "追踪" / "_tracking-state.json"
    if not state.exists():
        if require_state:
            return "追踪/_tracking-state.json 缺失；已有正文项目走 /story-import 的「旧追踪项目迁移」重建追踪（不必重跑全书拆解），新书先用 tracking_commit.py init 初始化"
        return None
    try:
        document = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "追踪/_tracking-state.json 无法解析；停止写正文并重新 /story-import，不能猜测或手补状态"
    if not isinstance(document, dict) or document.get("schema_version") != 4:
        return "追踪/_tracking-state.json 不是当前 schema_version=4；停止写正文并重新 /story-import，不保留旧结构兼容路径"
    revision = document.get("state_revision")
    if type(revision) is not int:
        return "追踪/_tracking-state.json 缺少整数 state_revision；停止写正文并重新 /story-import"
    context = book / "追踪" / "上下文.md"
    context_revision = None
    try:
        match = re.search(r"状态修订：(\d+)", context.read_text(encoding="utf-8"))
        if match:
            context_revision = int(match.group(1))
    except (OSError, UnicodeError):
        pass
    if context_revision != revision:
        shown = "缺失" if context_revision is None else str(context_revision)
        return (
            f"追踪/上下文.md 状态修订 {shown} 与 _tracking-state.json 的 {revision} 不一致；"
            "重新提交该章的 mode=revision 事务重建派生视图（expected_state_revision 取 追踪/_tracking-state.json 的 state_revision 字段（check 失败时不输出 JSON））"
        )
    if expected_last_committed is not None:
        last_committed = document.get("last_committed_chapter")
        if type(last_committed) is not int:
            return "追踪/_tracking-state.json 缺少整数 last_committed_chapter；停止写正文并重新 /story-import"
        # 章号已在追踪范围内 = 回炉/改名/留原稿备份，不是首建新章：文件名新但章节早已提交过，
        # 顺序校验对它恒为假（workflow-revision 的「备份原稿」步骤必然命中），跳过。
        if expected_last_committed < last_committed:
            return None
        if last_committed != expected_last_committed:
            return (
                f"追踪已提交到第{last_committed}章，首建第{expected_last_committed + 1}章前"
                f"必须先提交第{expected_last_committed}章追踪事务"
            )
    return None


def continuity_findings(root: Path) -> list[str]:
    """跨批连续性兜底：① 追踪 staleness（写了章但 续写状态卡没跟上）；
    ② 章节标题去重（两章同名多半是误复制）。模型无关，回合/会话边界提醒，无问题则静默。
    扫描范围 repo-wide（与缺口检测一致），非活跃书也提醒——有意为之，不按 .active-book 收窄；
    staleness 用 mtime +1 秒容差，是启发式 advisory（checkout / 带 -p 拷贝可能偏差）。"""
    msgs: list[str] = []
    for book in _discover_all_books(root):
        body_dir = book / "正文"
        chapters = sorted(body_dir.glob("第*章*.md")) if body_dir.is_dir() else []
        # ① 追踪 staleness（仅长篇：有 追踪/上下文.md）
        ctx = book / "追踪" / "上下文.md"
        checkpoint_issue = tracking_checkpoint_issue(book, require_state=bool(chapters))
        if checkpoint_issue:
            msgs.append(f"[continuity] {safe_rel(root, book)}：{checkpoint_issue}。")
        if chapters and ctx.exists():
            newest = max((c.stat().st_mtime for c in chapters), default=0)
            try:
                ctx_m = ctx.stat().st_mtime
            except Exception:
                ctx_m = 0
            if newest > ctx_m + 1:
                latest = max(chapters, key=lambda c: c.stat().st_mtime).name
                msgs.append(f"[continuity] {safe_rel(root, book)}：正文已更新到「{latest}」但续写状态卡更早——为该章提交 tracking_commit.py 事务、check 通过后再续写，禁止分别手改 上下文.md/伏笔.md。")
        # ①b 续写状态卡预算：上下文.md 由事务工具整份重建，硬上限 12288 字节。
        # 若不处理，每章读取量会随章节数增长，最终达到 O(N^2)。这里只提醒、不阻止；应把超出规定的区块移到 追踪/逐章记录/。
        if ctx.exists():
            try:
                ctx_size = ctx.stat().st_size
            except Exception:
                ctx_size = 0
            if ctx_size > 12288:
                msgs.append(f"[continuity] {safe_rel(root, book)}：追踪/上下文.md 已 {ctx_size} 字节，超出续写状态卡预算 12288 字节——提交一份 mode=revision 事务让 tracking_commit.py 整份重建，不要手改也不要继续追加。")
        # ② 标题去重（按文件名 第N章_标题 的标题部分）
        titles: dict[str, list[str]] = {}
        for c in chapters:
            mt = re.match(r"^第0*\d+章[_\- 　]+(.+)$", c.stem)
            if not mt:
                continue
            key = mt.group(1).strip()
            if key:
                titles.setdefault(key, []).append(c.name)
        for title, files in titles.items():
            if len(files) > 1:
                msgs.append(f"[continuity] {safe_rel(root, book)}：{len(files)} 章标题重复「{title}」（{('、'.join(files))[:60]}），建议改名。")
    return msgs


def session_start() -> None:
    root = project_root()
    messages: list[str] = []
    sentinel = root / ".story-deployed"
    if sentinel.exists():
        sent_text = sentinel.read_text(encoding="utf-8", errors="ignore")
        if "target_cli:" not in sent_text:
            messages.append("[story-setup] .story-deployed 缺少 target_cli 字段；建议重新运行 $story-setup。")
        elif "codex" not in re.search(r"target_cli:\s*(.*)", sent_text).group(1):  # type: ignore[union-attr]
            messages.append("[story-setup] 当前部署标记未包含 codex；如需 Codex hooks/agents，请重新运行 $story-setup 并选择 Codex。")
    book = read_active_book(root)
    if book:
        ctx = book / "追踪" / "上下文.md"
        if ctx.exists():
            messages.append(f"[story context] Active book: {safe_rel(root, book)}. Read {safe_rel(root, ctx)} before continuing long-form writing.")
        else:
            messages.append(f"[story context] Active story project detected: {safe_rel(root, book)}.")
    messages.extend(continuity_findings(root))
    if messages:
        emit(hook_context("SessionStart", "\n".join(messages)))


def resolve_target(root: Path, target: str, base: Path | None = None) -> Path:
    normalized = target.replace("\\", "/")
    p = Path(normalized)
    return p if p.is_absolute() else ((base or root) / p).resolve()


def _shell_words(segment: str) -> list[str]:
    """引号感知的线性分词（与 JS 核 shellWords 同构，逐字对齐）：引号内原样取字（成对引号剥掉，
    不闭合就取到段尾），只按 ASCII 空白（空格/Tab/CR/LF）分词——U+3000 不是 shell 分词符，故不切。
    不解 \\ 转义：resolve_target 把 \\ 当路径分隔符（Windows 路径）。"""
    words: list[str] = []
    current = ""
    started = False
    quote = ""
    escaped = False
    for ch in segment:
        if escaped:
            current += ch
            escaped = False
            started = True
            continue
        if ch == "\\" and quote != "'":
            current += ch
            escaped = True
            started = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            else:
                current += ch
            continue
        if ch in ('"', "'"):
            quote = ch
            started = True
            continue
        if ch in (" ", "\t", "\r", "\n"):
            if started:
                words.append(current)
            current = ""
            started = False
            continue
        started = True
        current += ch
    if started:
        words.append(current)
    return words


def _shell_segments(command: str) -> list[str]:
    """只在引号外按 shell 控制符切段；保留引号交给 _shell_words 去除。"""
    segments: list[str] = []
    current = ""
    quote = ""
    escaped = False
    for ch in command:
        if escaped:
            current += ch
            escaped = False
            continue
        if ch == "\\" and quote != "'":
            current += ch
            escaped = True
            continue
        if quote:
            current += ch
            if ch == quote:
                quote = ""
            continue
        if ch in ('"', "'"):
            quote = ch
            current += ch
            continue
        if ch in (";", "&", "|", "\n"):
            if current:
                segments.append(current)
            current = ""
            continue
        current += ch
    if current:
        segments.append(current)
    return segments


def _before_shell_redirection(segment: str) -> str:
    """去掉首个引号外重定向及其后内容；2> 里的 fd 数字也一并去掉。"""
    current = ""
    quote = ""
    escaped = False
    for ch in segment:
        if escaped:
            current += ch
            escaped = False
            continue
        if ch == "\\" and quote != "'":
            current += ch
            escaped = True
            continue
        if quote:
            current += ch
            if ch == quote:
                quote = ""
            continue
        if ch in ('"', "'"):
            quote = ch
            current += ch
            continue
        if ch in ("<", ">"):
            return re.sub(r"\d+$", "", current)
        current += ch
    return current


def _read_shell_word(value: str, start: int) -> tuple[str, int]:
    word = ""
    quote = ""
    escaped = False
    started = False
    index = start
    while index < len(value):
        ch = value[index]
        if escaped:
            word += ch
            escaped = False
            started = True
            index += 1
            continue
        if ch == "\\" and quote != "'":
            word += ch
            escaped = True
            started = True
            index += 1
            continue
        if quote:
            if ch == quote:
                quote = ""
            else:
                word += ch
            started = True
            index += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            started = True
            index += 1
            continue
        if ch in (" ", "\t", "\r", "\n", ";", "&", "|", "<", ">", "(", ")"):
            break
        word += ch
        started = True
        index += 1
    return (word if started else "", index)


def _read_heredoc_delimiter(value: str, start: int) -> tuple[str, int]:
    word = ""
    quote = ""
    escaped = False
    started = False
    index = start
    while index < len(value):
        ch = value[index]
        if escaped:
            word += ch
            escaped = False
            started = True
            index += 1
            continue
        if ch == "\\" and quote != "'":
            next_char = value[index + 1:index + 2]
            if quote == '"' and next_char not in ("$", "`", '"', "\\", "\n"):
                word += ch
            else:
                escaped = True
            started = True
            index += 1
            continue
        if quote:
            if ch == quote:
                quote = ""
            else:
                word += ch
            started = True
            index += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            started = True
            index += 1
            continue
        if ch in (" ", "\t", "\r", "\n", ";", "&", "|", "<", ">", "(", ")"):
            break
        word += ch
        started = True
        index += 1
    return (word if started else "", index)


def _heredoc_declarations(line: str) -> list[tuple[str, bool]]:
    declarations: list[tuple[str, bool]] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(line):
        ch = line[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if ch == quote:
                quote = ""
            index += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            index += 1
            continue
        if not (
            ch == "<"
            and index + 1 < len(line)
            and line[index + 1] == "<"
            and (index == 0 or line[index - 1] != "<")
            and (index + 2 >= len(line) or line[index + 2] != "<")
        ):
            index += 1
            continue
        cursor = index + 2
        strip_tabs = False
        if cursor < len(line) and line[cursor] == "-":
            strip_tabs = True
            cursor += 1
        while cursor < len(line) and line[cursor] in (" ", "\t"):
            cursor += 1
        delimiter, cursor = _read_heredoc_delimiter(line, cursor)
        if delimiter:
            declarations.append((delimiter, strip_tabs))
        index = max(index + 1, cursor)
    return declarations


def _mask_heredoc_bodies(command: str) -> str:
    pending: list[tuple[str, bool]] = []
    output: list[str] = []
    for line in command.split("\n"):
        if pending:
            delimiter, strip_tabs = pending[0]
            comparable = re.sub(r"^\t+", "", line) if strip_tabs else line
            if comparable == delimiter:
                pending.pop(0)
                output.append(line)
            else:
                output.append(" " * len(line))
            continue
        pending.extend(_heredoc_declarations(line))
        output.append(line)
    return "\n".join(output)


def _command_word_index(words: list[str]) -> int:
    index = 0
    while index < len(words):
        while index < len(words) and (
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[index])
            or words[index] == "noglob"
        ):
            index += 1
        if index < len(words) and words[index] == "command":
            index += 1
            while index < len(words):
                option = words[index]
                if option == "--":
                    index += 1
                    break
                if option in ("-v", "-V") or re.match(r"^-[p]*[vV]", option):
                    return len(words)
                if option == "-p" or re.match(r"^-p+$", option):
                    index += 1
                    continue
                break
            continue
        if index < len(words) and words[index] == "env":
            index += 1
            while index < len(words):
                option = words[index]
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", option) or option in (
                    "-i",
                    "--ignore-environment",
                ):
                    index += 1
                    continue
                if option in ("-u", "--unset"):
                    index += 2
                    continue
                if option.startswith("--unset=") or (re.match(r"^-u.+", option) and option != "-u"):
                    index += 1
                    continue
                if option == "--":
                    index += 1
                break
            continue
        break
    return index


def _nested_shell_command(args: list[str]) -> str:
    value_options = {"-o", "+o", "-O", "+O"}
    index = 0
    while index < len(args):
        option = args[index]
        if option == "--":
            return ""
        if option == "-c" or (re.match(r"^-[^-]+$", option) and "c" in option[1:]):
            return args[index + 1] if index + 1 < len(args) else ""
        if option in value_options:
            index += 2
            continue
        if not option.startswith(("-", "+")):
            break
        index += 1
    return ""


def _command_substitutions(command: str) -> list[str]:
    substitutions: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        ch = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote == "'":
            if ch == "'":
                quote = ""
            index += 1
            continue
        if ch == '"':
            quote = "" if quote == '"' else '"'
            index += 1
            continue
        if not quote and ch == "'":
            quote = "'"
            index += 1
            continue
        if ch == "$" and command[index + 1:index + 2] == "(" and command[index + 2:index + 3] != "(":
            depth = 1
            inner_quote = ""
            inner_escaped = False
            end = index + 2
            while end < len(command):
                inner = command[end]
                if inner_escaped:
                    inner_escaped = False
                    end += 1
                    continue
                if inner == "\\" and inner_quote != "'":
                    inner_escaped = True
                    end += 1
                    continue
                if inner_quote:
                    if inner == inner_quote:
                        inner_quote = ""
                    end += 1
                    continue
                if inner in ('"', "'"):
                    inner_quote = inner
                elif inner == "(":
                    depth += 1
                elif inner == ")":
                    depth -= 1
                    if depth == 0:
                        break
                end += 1
            if depth == 0:
                substitutions.append(command[index + 2:end])
                index = end + 1
                continue
        if ch == "`":
            end = index + 1
            tick_escaped = False
            while end < len(command):
                inner = command[end]
                if tick_escaped:
                    tick_escaped = False
                elif inner == "\\":
                    tick_escaped = True
                elif inner == "`":
                    break
                end += 1
            if end < len(command):
                substitutions.append(command[index + 1:end])
                index = end + 1
                continue
        index += 1
    return substitutions


def _redirect_targets(command: str) -> list[str]:
    targets: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        ch = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if ch == quote:
                quote = ""
            index += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            index += 1
            continue
        if ch != ">":
            index += 1
            continue
        cursor = index + (2 if command[index + 1:index + 2] == ">" else 1)
        if command[cursor:cursor + 1] in ("|", "&"):
            cursor += 1
        while command[cursor:cursor + 1] in (" ", "\t"):
            cursor += 1
        target, cursor = _read_shell_word(command, cursor)
        if "正文" in target:
            targets.append(target)
        index = max(index + 1, cursor)
    return targets


def _write_operands(command: str, args: list[str]) -> list[str]:
    operands: list[str] = []
    value_options = (
        {"-d", "--date", "-r", "--reference", "-t", "--time"}
        if command == "touch"
        else set()
    )
    options = True
    index = 0
    while index < len(args):
        arg = args[index]
        if options and arg == "--":
            options = False
            index += 1
            continue
        if options and arg in value_options:
            index += 2
            continue
        if options and any(
            option.startswith("--") and arg.startswith(option + "=")
            for option in value_options
        ):
            index += 1
            continue
        if options and arg.startswith("-") and arg != "-":
            index += 1
            continue
        operands.append(arg)
        index += 1
    return operands


def _command_basename(value: str) -> str:
    return re.split(r"[\\/]", value or "")[-1]


def _join_posix(directory: str, name: str) -> str:
    """目录形态目标一律用 "/" 拼：Path 在 Windows 产出反斜杠，会破坏三端 parity 的逐字比较。"""
    return re.sub(r"[\\/]+$", "", directory) + "/" + name


def _copy_like_targets(command: str, args: list[str]) -> list[str]:
    positionals: list[str] = []
    target_directory = ""
    directory_only = False
    options = True
    index = 0
    while index < len(args):
        arg = args[index]
        if options and arg == "--":
            options = False
            index += 1
            continue
        if options and arg in ("-t", "--target-directory"):
            target_directory = args[index + 1] if index + 1 < len(args) else ""
            index += 2
            continue
        if options and arg.startswith("--target-directory="):
            target_directory = arg[len("--target-directory="):]
            index += 1
            continue
        if options and command == "install" and arg in ("-d", "--directory"):
            directory_only = True
            index += 1
            continue
        if options and arg.startswith("-") and arg != "-":
            index += 1
            continue
        positionals.append(arg)
        index += 1
    if directory_only or not positionals:
        return []
    if target_directory:
        return [_join_posix(target_directory, _command_basename(source)) for source in positionals]
    if len(positionals) < 2:
        return []
    destination = positionals[-1]
    normalized = destination.replace("\\", "/")
    if normalized.endswith("/") or normalized.rsplit("/", 1)[-1] == "正文":
        return [_join_posix(destination, _command_basename(source)) for source in positionals[:-1]]
    return [destination]


def extract_prose_targets_from_command(command: str, depth: int = 0) -> list[str]:
    # Only treat a 正文 path as a write target when it is the destination of an actual
    # write op (redirection / tee / touch / cp|mv dest). Scanning the whole command would
    # flag any heredoc body, doc string, or grep pattern that merely *mentions*
    # 正文/第N章.md and wrongly deny the edit.
    targets: list[str] = []
    scannable = _mask_heredoc_bodies(command)
    if depth < 8:
        for nested in _command_substitutions(scannable):
            targets.extend(extract_prose_targets_from_command(nested, depth + 1))
    targets.extend(_redirect_targets(scannable))
    # cp/mv: the write destination is the last positional arg of the segment. Parse it (regex can't
    # tell a 正文 source from a 正文 dest, and a trailing 2>/dev/null / >log / || breaks end-anchoring).
    for raw_segment in _shell_segments(scannable):
        seg = _before_shell_redirection(raw_segment)
        # 引号感知分词（同 JS 核 shellWords）：str.split() 会按 U+3000 和引号内空格切碎目标，
        # 末位取到 book/正文/第1章.md —— 判到另一本书上（那本有细纲就直接放行）。
        words = _shell_words(seg)
        command_index = _command_word_index(words)
        command_name = _command_basename(words[command_index]) if command_index < len(words) else ""
        command_args = words[command_index + 1:]
        if command_name in ("sh", "bash", "dash", "ksh", "zsh"):
            nested = _nested_shell_command(command_args)
            if nested:
                targets.extend(extract_prose_targets_from_command(nested, depth + 1))
        if command_name in ("tee", "touch"):
            targets.extend(
                destination
                for destination in _write_operands(command_name, command_args)
                if "正文" in destination
            )
        if command_name in ("cp", "mv", "install"):
            targets.extend(
                destination
                for destination in _copy_like_targets(command_name, command_args)
                if "正文" in destination
            )
    return list(dict.fromkeys(target for target in targets if target))


def extract_apply_patch_targets(command: str) -> list[str]:
    # 与 JS 共享核 extractPatchTargets 逐字同构（parity 由 test-prose-net-parity.sh 的命令函数
    # fixture 锁）。只认 Add/Update 会漏掉 `*** Move to:`——它是 Update File 段的子指令
    # （apply_patch 的改名/搬家形态），落盘路径是**目的地**，源路径搬完就不存在了：一份没细纲的
    # 草稿曾能靠 `Update File: draft.md` + `Move to: 书/正文/第9章.md` 直接搬进 正文/（细纲门放行、
    # 写后兜底网扫的还是已不存在的源）。故 Move 用目的地**顶替**同段的源目标。
    # Delete File 一律不入表：删除不是写入，prose_block_reason 对已存在的正文本就放行、删完文件
    # 也不在了没东西可扫，认它只会给「删稿」误报；但 Delete 段也能带 Move to（搬走后删源），
    # 那条 Move 的目的地照样要进表，故 Delete 只清掉待顶替的源槽位。
    targets: list[str] = []
    source_index = -1
    for line in command.splitlines():
        # 控制行必须从第 0 列开始；前导空格是 apply_patch 的上下文 marker，不能 strip 掉。
        m = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if m:
            if m.group(1) == "Delete":
                source_index = -1
                continue
            targets.append(m.group(2).strip())
            source_index = len(targets) - 1
            continue
        m = re.match(r"^\*\*\* Move to: (.+)$", line)
        if m:
            destination = m.group(1).strip()
            if not destination:
                continue
            if source_index >= 0:
                targets[source_index] = destination
            else:
                targets.append(destination)
            source_index = -1
    return targets


def target_paths_from_hook(obj: dict[str, Any]) -> list[Path]:
    root = project_root()
    base = root
    if HOOK_CWD and HOOK_CWD.is_dir():
        try:
            HOOK_CWD.relative_to(root)
            base = HOOK_CWD
        except ValueError:
            pass
    tool_name = str(obj.get("tool_name") or "")
    tool_input = obj.get("tool_input") if isinstance(obj.get("tool_input"), dict) else {}
    assert isinstance(tool_input, dict)
    raw_targets: list[str] = []
    for key in ("file_path", "filePath", "path", "target", "filename"):
        value = tool_input.get(key)
        if isinstance(value, str):
            raw_targets.append(value)
    command = tool_input.get("command")
    if isinstance(command, str):
        if tool_name == "Bash":
            raw_targets.extend(extract_prose_targets_from_command(command))
        else:
            raw_targets.extend(extract_apply_patch_targets(command))
            raw_targets.extend(extract_prose_targets_from_command(command))
    return [resolve_target(root, t, base) for t in raw_targets if t]


def prose_block_reason(root: Path, abs_path: Path) -> str | None:
    base = abs_path.name
    parent = abs_path.parent.name
    if base == "正文.md":
        if abs_path.exists():
            return None
        book_dir = abs_path.parent
        if (root / "拆文库" / book_dir.name).exists():
            return None
        if not (book_dir / "设定.md").exists():
            return None
        if not (book_dir / "小节大纲.md").exists():
            # 文案对齐 JS core proseBlockReason（py↔js 由 test-prose-net-parity.sh Part E 锁 parity）
            return f"⛔ 写正文被拦截：{safe_rel(root, abs_path)} 缺少同目录 小节大纲.md。先按 story-short-write 完成「小节大纲.md」再写正文。"
        return None
    if parent != "正文":
        return None
    if not re.match(r"^第.*章.*\.md$", base):
        return None
    m = re.match(r"^第0*(\d+)章", base)
    if not m:
        return None
    num = m.group(1)
    book_dir = abs_path.parent.parent
    # 新书可能在任何大纲/追踪/设定脚手架存在前就首建正文；核心守卫必须 fail closed。
    # 相对路径由 HOOK_CWD 解析，不能靠削弱这条 canonical guard 来掩盖 cwd 语义。
    state = book_dir / "追踪" / "_tracking-state.json"
    # story-import 在复制既有正文、尚未执行 tracking init 的窗口可以写；一旦 state 存在，
    # 即进入当前追踪协议，不再因为保留了 拆文库/ 分析资产而永久绕过守卫。
    if (root / "拆文库" / book_dir.name).exists() and not state.exists():
        return None
    exists = abs_path.exists()
    outline_dir = book_dir / "大纲"
    found = False
    if not exists:
        if outline_dir.is_dir():
            for candidate in outline_dir.iterdir():
                fm = re.match(r"^细纲_第0*(\d+)章.*\.md$", candidate.name)
                if fm and fm.group(1) == num:
                    found = True
                    break
        if not found:
            return f"⛔ 写正文被拦截：第 {num} 章缺少细纲（{safe_rel(root, outline_dir)}/细纲_第{num}章.md）。先按 story-long-write 单章流程补建细纲再写正文。"
    checkpoint_issue = tracking_checkpoint_issue(
        book_dir,
        require_state=True,
        expected_last_committed=None if exists else int(num) - 1,
    )
    if checkpoint_issue:
        return f"⛔ 写正文被拦截：{safe_rel(root, book_dir)} 的{checkpoint_issue}。"
    if exists:
        return None
    # 欠账门（无状态）：写第 N 章（首建）前，上一章有未清毒句式且未标「去味:跳过」豁免时先清再写。
    # 判据现算自上一章文件本身，不落任何状态文件；找不到上一章/读取失败一律放行（宁可漏拦不可误伤）。
    # js↔py 文案由 check-hook-regex-sync.sh 锁同步，判定由 test-prose-net-parity.sh Part E 锁 parity。
    prev_num = int(num) - 1
    if prev_num >= 1:
        prev_file = None
        try:
            # iterdir 顺序在 ext4/overlayfs 上是哈希序：不排序就可能挑中同章号的原稿备份
            # （workflow-revision 的「备份原稿」产物），拿早已被改写掉的旧文本报欠账。
            # 显式排除 _原稿_ 备份并排序，保证四端与各文件系统上取到同一个「上一章」。
            candidates = sorted(
                c for c in abs_path.parent.iterdir()
                if re.match(r"^第0*(\d+)章.*\.md$", c.name)
                and int(re.match(r"^第0*(\d+)章", c.name).group(1)) == prev_num
                and "_原稿_" not in c.name
            )
            prev_file = candidates[0] if candidates else None
        except OSError:
            prev_file = None
        if prev_file is not None:
            prev_text = None
            try:
                prev_text = prev_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                prev_text = None
            if prev_text is not None and not re.search(r"去味(：|:)跳过", "\n".join(re.split(r"\r?\n", prev_text)[:6])):
                hits = [ln for ln in toxic_phrase_findings(prev_text) if ln.startswith("第")]
                if hits:
                    shown = hits[:6]
                    more = len(hits) - len(shown)
                    reason = (
                        f"⛔ 写正文被拦截：上一章（{prev_file.name}）有 {len(hits)} 处未清毒句式欠账，"
                        f"先清零再写第 {num} 章；用户显式豁免时在上一章标题行下加 <!-- 去味:跳过 --> 后重试。\n"
                        + "\n".join(shown)
                    )
                    if more > 0:
                        reason += f"\n（另有 {more} 处，完整扫描：node <skill>/scripts/check-ai-patterns.js --check 上一章文件）"
                    return reason
    return None


def pre_tool_prose_guard(obj: dict[str, Any]) -> None:
    root = project_root()
    for path in target_paths_from_hook(obj):
        reason = prose_block_reason(root, path)
        if reason:
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            })
            return


def find_command(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("command", "cmd", "script"):
            if isinstance(value.get(key), str):
                return value[key]
        for key in ("tool_input", "input", "parameters", "args"):
            found = find_command(value.get(key))
            if found:
                return found
    return ""


def is_git_commit_command(raw: str) -> bool:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ; ")
    try:
        lexer = shlex.shlex(raw, posix=True, punctuation_chars="();|&{}")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except TypeError:
        try:
            tokens = shlex.split(raw, posix=True)
        except Exception:
            tokens = raw.split()
    except Exception:
        tokens = raw.split()
    assignment = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    separators = {";", "&&", "||", "|", "|&", "&"}
    openers = {"(", "{"}
    closers = {")",
        "}",
    }
    control_words = {"then", "do", "else", "elif"}
    wrappers = {"command", "noglob"}
    git_options_with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}

    def skip_shell_wrappers(i: int) -> int:
        while i < len(tokens):
            tok = tokens[i]
            if tok in openers or assignment.match(tok) or tok in wrappers:
                i += 1
                continue
            if tok == "env":
                i += 1
                while i < len(tokens):
                    if assignment.match(tokens[i]) or tokens[i] in {"-i", "--ignore-environment"}:
                        i += 1
                        continue
                    break
                continue
            break
        return i

    def is_git_commit_at(i: int) -> bool:
        if i >= len(tokens) or tokens[i] != "git":
            return False
        i += 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in closers or tok in separators:
                return False
            if tok == "commit":
                return True
            if tok == "--":
                i += 1
                continue
            if tok in git_options_with_value:
                i += 2
                continue
            if any(tok.startswith(prefix + "=") for prefix in git_options_with_value if prefix.startswith("--")):
                i += 1
                continue
            if tok.startswith("-c") and tok != "-c":
                i += 1
                continue
            if tok.startswith("-"):
                i += 1
                continue
            return False
        return False

    segment_start = True
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in separators or tok in control_words:
            segment_start = True
            i += 1
            continue
        if segment_start or tok in openers:
            start = skip_shell_wrappers(i)
            if is_git_commit_at(start):
                return True
            segment_start = False
        i += 1
    return False


# 设定/ 直属的项目级设定件：artifact-protocols.md 规定的 关系.md（正文是「# 角色关系图」）、
# 题材定位.md，以及 文风.md、题材正文提示卡.md 等，它们本来就没有 名字/姓名 字段。
_SETTING_NON_CHARACTER_FILES = {"关系.md", "题材定位.md", "题材正文提示卡.md", "文风.md", "世界规则.md", "世界观.md", "金手指.md", "背景设定.md"}


def _is_character_sheet_path(rel: str) -> bool:
    """只查角色卡：整棵 设定/ 一刀切会让每次碰设定的提交都刷一屏假警告，把同框的
    「正文硬编码角色属性」真警告埋掉。判定口径与 validate-story-commit.sh / opencode
    pre-commit.sh 的 case 分支一一对齐（bash↔js↔py 四端同口径，别单边改回一刀切）：
    ① 设定/角色|人物 子目录内的文件 → 角色卡；
    ② 其余 设定/<子目录>/ → 整目录跳过（世界观/势力/报告/原理/人物关系 等）；
    ③ 设定/ 直属的扁平文件 → 除已知项目级设定件外都算角色卡（主角.md/配角.md/反派.md 等自定义命名）。
    bash 的 `*` 跨 `/` 匹配，`设定/角色/*|*/设定/角色/*` 等价于「路径里存在某个 设定 目录段满足该
    分支」，所以两趟扫描（先全路径找分支①，再全路径找分支②）而不是只看第一个 设定 段就定分支——
    后者在 设定/其他/设定/角色/x.md 这类嵌套路径上会与 bash 判定分叉。
    与 JS core isCharacterSheetPath 同实现，py↔js 由 scripts/test-prose-net-parity.sh Part E 锁 parity。"""
    segments = rel.split("/")
    last = len(segments) - 1
    # 分支①：某个 设定 段紧跟 角色/人物，且其下还有文件段
    for i in range(last - 1):
        if segments[i] == "设定" and segments[i + 1] in ("角色", "人物"):
            return True
    # 分支②：某个 设定 段后还有 ≥2 段，即落在非角色子目录里
    for i in range(last - 1):
        if segments[i] == "设定":
            return False
    # 分支③：设定 直属扁平文件（分支②已排掉更深的路径，设定 段只能是倒数第二段）
    return last >= 1 and segments[last - 1] == "设定" and segments[last] not in _SETTING_NON_CHARACTER_FILES


def staged_markdown_warnings(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=false", "diff", "--cached", "--relative", "--name-only", "--diff-filter=ACM", "-z", "--", "."],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return ""
    warnings: list[str] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        file = raw.decode("utf-8", errors="ignore")
        if not file.endswith(".md"):
            continue
        full = root / file
        if not full.exists():
            continue
        text = full.read_text(encoding="utf-8", errors="ignore")
        # 匹配语义与警告文案对齐 JS core（story_hook_core.js stagedMarkdownWarnings，跨 CLI 的
        # 权威实现）：name 字段 re.I 大小写不敏感、中文文案。py↔js 由
        # scripts/test-prose-net-parity.sh Part E 锁 parity。
        if file == "正文.md" or "/正文.md" in file or file.startswith("正文/") or "/正文/" in file:
            hits = []
            for idx, line in enumerate(text.splitlines(), 1):
                if re.search(r"(身高|体重|年龄)(\s|　)*(：|:)(\s|　)*[0-9]+", line):
                    hits.append(f"{idx}:{line}")
            if hits:
                warnings.append(f"⚠ {file}: 正文硬编码角色属性，应引用设定文件：\n" + "\n".join(hits))
        if _is_character_sheet_path(file):
            if not re.search(r"^(\s|　)*(名字|姓名|名称|name)(\s|　)*(：|:)", text, re.M | re.I):
                warnings.append(f"⚠ {file}: 设定文件缺少 name/名字 必填字段。")
    if not warnings:
        return ""
    return "=== Story Commit Warnings（advisory only）===\n" + "\n".join(warnings) + "\n=== End Warnings ==="


def pre_tool_commit_advisory(obj: dict[str, Any]) -> None:
    command = find_command(obj)
    if not command or not is_git_commit_command(command):
        return
    warnings = staged_markdown_warnings(project_root())
    if warnings:
        emit(hook_context("PreToolUse", warnings))


def compact_summary(event: str) -> None:
    root = project_root()
    lines = ["=== Story Compact Summary ==="]
    book = read_active_book(root)
    if book:
        ctx = book / "追踪" / "上下文.md"
        if ctx.exists():
            line_count = len(ctx.read_text(encoding="utf-8", errors="ignore").splitlines())
            lines.append(f"Writing context: {safe_rel(root, ctx)} ({line_count} lines)")
        else:
            lines.append(f"Active story project: {safe_rel(root, book)}")
    else:
        lines.append("Active state: not found")
    try:
        # -z + bytes so a Chinese filename under a user-global core.quotepath=false can't raise
        # UnicodeDecodeError on a Windows ANSI code page (these are counts only).
        # --relative -- . 把计数收窄到项目根子树：项目根是仓库子目录时，不带它会把上层整仓的
        # 改动都算进来（同 find_changed_prose_files / staged_markdown_warnings 的口径）。
        changed = subprocess.check_output(["git", "-C", str(root), "-c", "core.quotepath=false", "diff", "--relative", "--name-only", "-z", "--", "."], stderr=subprocess.DEVNULL)
        staged = subprocess.check_output(["git", "-C", str(root), "-c", "core.quotepath=false", "diff", "--relative", "--name-only", "--cached", "-z", "--", "."], stderr=subprocess.DEVNULL)
        n_changed = len([x for x in changed.split(b"\0") if x])
        n_staged = len([x for x in staged.split(b"\0") if x])
        lines.append(f"Git: {n_changed} unstaged, {n_staged} staged")
    except Exception:
        pass
    emit({"systemMessage": "\n".join(lines)})


def stop_event() -> None:
    # Codex 无 PostToolUse，正文内容网在回合结束的 Stop 事件兜底：对本回合 git 改动过的正文
    # 复扫硬信号（截断/拒绝语/工程词/复读）。非阻塞、无发现静默；解析失败一律 {continue:True}。
    # Stop hooks require JSON on stdout.
    try:
        root = project_root()
        blocks: list[str] = []
        for abs_path in find_changed_prose_files(root):
            try:
                text = abs_path.read_text(encoding="utf-8")
            except Exception:
                continue
            findings = prose_net_findings(text)
            if findings:
                blocks.append(f"=== {safe_rel(root, abs_path)} ===\n" + "\n".join(findings))
        if blocks:
            emit({
                "continue": True,
                "systemMessage": "=== 正文兜底检测（回合结束复扫，模型无关）===\n硬信号命中即回正文改掉、复扫到净：\n"
                + "\n".join(blocks),
            })
            return
    except Exception:
        pass
    emit({"continue": True})


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    obj = read_hook_input()
    if event == "session-start":
        session_start()
    elif event == "pre-tool-prose-guard":
        pre_tool_prose_guard(obj)
    elif event == "pre-tool-commit-advisory":
        pre_tool_commit_advisory(obj)
    elif event == "pre-compact":
        compact_summary("PreCompact")
    elif event == "post-compact":
        compact_summary("PostCompact")
    elif event == "stop":
        stop_event()
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
