#!/usr/bin/env python3
"""基准正文的质量评测：单份细纲兑现核对 + 配对盲评。评委默认走 Antigravity（Gemini），
写手是 Gemini 时用 --judge claude 或 codex 换家族：评委必须与写手不同家族。

用法：
  judge.py [--judge agy|claude|codex] coverage <run目录>... --out <结果目录>
  judge.py [--judge agy|claude|codex] pairwise --base <run目录>... --cand <run目录>... --out <结果目录>

coverage：每章单独评，评委只看本章细纲与正文，不知道版本；逐条判情节点是否落地、
          列出细纲没授权的新剧情事实。可数，结论不靠打分。
          --strict：改判「演成场景 / 概括转述 / 缺失」并摘原句——默认口径对 Gemini Flash 太宽，
          两个版本全是 1.00，看不出关键交锋被写成概括的问题。
pairwise：同 (主机, 用例, 章号) 的两个版本随机分 A/B，交换顺序各评一次；
          两次一致才算胜负，不一致记平。评委不知道哪份是哪个版本。两版细纲不同（用例现补细纲）时
          各附各的细纲，不拿一方的细纲评另一方。
          --criterion reader：改问「哪一版更像目标平台读者会追的网文」（抓手、站到主角这边、情绪推进、
          期待回击、章尾）。默认口径偏爱克制，看不出「写成了现实主义短篇、不像网文」这类问题。
所有原始回复落在 --out，便于复核；重复运行跳过已有结果。
"""
import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
from pathlib import Path

JUDGE_MODELS = {'agy': 'gemini-3.8-flash-high', 'claude': 'claude-opus-5-5', 'codex': 'gpt-5.6-sol'}
JUDGE = 'agy'

COVERAGE_PROMPT = """你是网文责编，只核对事实，不评文笔。下面是一章的细纲和成稿正文。

任务一：把细纲里的情节点逐条列出（优先用细纲「情节点」表的编号；没有表就按「情节安排」逐条拆），
对每条判定正文是否演出来了：landed（演成了场景）、summarized（只用一两句交代带过）、missing（没有）。
任务二：列出正文里细纲没有授权、且会影响后续章节的新剧情事实（新主线事件、新反转、新能力规则、
改变细纲已定结果、提前写后续章剧情）。现场细节、路人、一次性对话不算。

只输出一个 JSON 对象，不要任何别的文字：
{{"beats": [{{"id": "1", "beat": "情节点一句话", "status": "landed|summarized|missing"}}],
  "unauthorized": [{{"fact": "一句话", "quote": "正文原句片段"}}]}}

===== 细纲 =====
{outline}

===== 正文 =====
{body}
"""

SCENE_PROMPT = """你是网文责编，只核对「演没演」，不评文笔。下面是一章的细纲和成稿正文。

把细纲里的情节点逐条列出（优先用「情节点」表的编号），对每条在正文里找到对应段落，判定呈现方式：
- scene：演成了场景——读者看到逐拍的动作、对话或物件变化，关键交锋用人物的原话呈现；
- summary：叙述者概括转述——例如「他讲了十分钟证据」「两人争了几句」「她把来龙去脉说了一遍」，
  或只给结果不给过程；
- missing：正文里没有。
每条都要摘一句最能说明判定的正文原句（≤40 字）。宁严勿宽：半场景半概括的，关键交锋被概括就判 summary。

只输出一个 JSON 对象，不要任何别的文字：
{{"beats": [{{"id": "1", "beat": "情节点一句话", "render": "scene|summary|missing", "quote": "正文原句"}}]}}

===== 细纲 =====
{outline}

===== 正文 =====
{body}
"""

PAIRWISE_PROMPT = """你是番茄小说的资深编辑。下面是{source}写出的两版第 {chapter} 章正文（A 与 B），
来源未知。请站在追更读者的角度判断哪一版更好看：更想往下读、人物更像活人、场面更具体、
更不像 AI 写的。只看成品，不因长短本身加减分。

只输出一个 JSON 对象，不要任何别的文字：
{{"winner": "A|B|tie", "reason": "两三句具体理由，引用原文片段"}}

{outline}

===== A =====
{a}

===== B =====
{b}
"""


READER_PAIRWISE_PROMPT = """你是番茄小说的签约编辑。下面是{source}写出的两版第 {chapter} 章正文（A 与 B），
来源未知。只回答一个问题：哪一版更像目标平台读者会点进来并追下去的网文？看开头几百字有没有抓手，
读者能不能站到主角这边（她要什么、受了什么委屈、心里怎么想），有没有情绪推进和让人期待她回击的东西，
章尾想不想点下一章。不评文学性，不因长短本身加减分。

只输出一个 JSON 对象，不要任何别的文字：
{{"winner": "A|B|tie", "reason": "两三句具体理由，引用原文片段"}}

{outline}

===== A =====
{a}

===== B =====
{b}
"""


def ask(prompt, cwd):
    model = JUDGE_MODELS[JUDGE]
    if JUDGE == 'claude':
        # 不读任何用户/项目设置与 CLAUDE.md，评委只看 prompt。
        cmd, stdin = ['claude', '-p', '--model', model, '--output-format', 'text', '--setting-sources', '',
                      '--disallowedTools', 'Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Agent'], prompt
    elif JUDGE == 'codex':
        cmd, stdin = ['codex', 'exec', '-c', f'model="{model}"', '--skip-git-repo-check', '--sandbox', 'read-only',
                      '-'], prompt
    else:
        cmd, stdin = ['agy', '-p', prompt, '--model', model, '--output-format', 'text', '--print-timeout', '10m',
                      '--disable-slash-commands', '--sandbox', '--dangerously-skip-permissions'], None
    completed = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, encoding='utf-8',
                               **({} if stdin is not None else {'stdin': subprocess.DEVNULL}))
    text = completed.stdout
    match = re.search(r'\{.*\}', text, re.S)
    try:
        return json.loads(match.group(0)) if match else None, text
    except ValueError:
        return None, text


def chapters(run):
    run = Path(run)
    meta = json.loads((run / 'meta.json').read_text(encoding='utf-8'))
    book = run / 'proj' / meta['case']['book_dir']
    for n in range(meta['start_committed'] + 1, meta.get('end_committed', 0) + 1):
        body = sorted((book / '正文').glob(f'第{n:03d}章*.md'))
        outline = sorted((book / '大纲').glob(f'细纲_第{n:03d}章*.md'))
        if body and outline:
            yield meta, n, body[0], outline[0]


def coverage(runs, out, strict=False):
    out.mkdir(parents=True, exist_ok=True)
    for run in runs:
        for meta, n, body, outline in chapters(run):
            dest = out / f'{Path(run).name}-{n:03d}-{JUDGE}.json'
            if dest.exists():
                continue
            prompt = (SCENE_PROMPT if strict else COVERAGE_PROMPT).format(
                outline=outline.read_text(encoding='utf-8'), body=body.read_text(encoding='utf-8'))
            result, raw = ask(prompt, out)
            dest.write_text(json.dumps({'run': Path(run).name, 'host': meta['host'], 'case': meta['case']['id'],
                                        'pkg': meta['pkg'].get('ref'), 'chapter': n, 'judge': JUDGE_MODELS[JUDGE],
                                        'result': result, 'raw': raw},
                                       ensure_ascii=False, indent=1), encoding='utf-8')
            print(dest.name, 'ok' if result else 'PARSE_FAIL', flush=True)


def pairwise(base_runs, cand_runs, out, criterion='quality'):
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for label, runs in (('base', base_runs), ('cand', cand_runs)):
        for run in runs:
            for meta, n, body, outline in chapters(run):
                index.setdefault((meta['host'], meta['case']['id'], n), {})[label] = (body, outline)
    for (host, case, n), pair in sorted(index.items()):
        if len(pair) != 2:
            continue
        suffix = '' if criterion == 'quality' else f'-{criterion}'
        dest = out / f'{host}-{case}-{n:03d}-{JUDGE}{suffix}.json'
        if dest.exists():
            continue
        seed = int(hashlib.sha256(f'{host}{case}{n}'.encode()).hexdigest(), 16)
        first = random.Random(seed).choice(['base', 'cand'])
        second = 'cand' if first == 'base' else 'base'
        outlines = {k: v[1].read_text(encoding='utf-8') for k, v in pair.items()}
        texts = {k: v[0].read_text(encoding='utf-8') for k, v in pair.items()}
        rounds = []
        for a, b in ((first, second), (second, first)):
            if outlines['base'] == outlines['cand']:
                source, outline = '同一份细纲', '===== 细纲 =====\n' + outlines['base']
            else:
                source = '各自细纲（同一段剧情、分别补写）'
                outline = '===== A 的细纲 =====\n%s\n\n===== B 的细纲 =====\n%s' % (outlines[a], outlines[b])
            template = READER_PAIRWISE_PROMPT if criterion == 'reader' else PAIRWISE_PROMPT
            result, raw = ask(template.format(source=source, chapter=n, outline=outline, a=texts[a], b=texts[b]),
                              out)
            w = (result or {}).get('winner')
            rounds.append({'A': a, 'B': b, 'winner': {'A': a, 'B': b}.get(w, 'tie' if w == 'tie' else None),
                           'reason': (result or {}).get('reason'), 'raw': raw})
        votes = [r['winner'] for r in rounds]
        final = votes[0] if votes[0] == votes[1] and votes[0] in ('base', 'cand') else 'tie'
        dest.write_text(json.dumps({'host': host, 'case': case, 'chapter': n, 'judge': JUDGE_MODELS[JUDGE],
                                    'criterion': criterion,
                                    'final': final, 'rounds': rounds},
                                   ensure_ascii=False, indent=1), encoding='utf-8')
        print(dest.name, final, flush=True)


def main():
    global JUDGE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--judge', choices=sorted(JUDGE_MODELS), default='agy',
                    help='评委主机；必须与被评正文的写手不同家族')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('coverage')
    c.add_argument('runs', nargs='+')
    c.add_argument('--out', required=True)
    c.add_argument('--strict', action='store_true', help='逐条判「演成场景 / 概括转述」并摘原句')
    p = sub.add_parser('pairwise')
    p.add_argument('--base', nargs='+', required=True)
    p.add_argument('--cand', nargs='+', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--criterion', choices=['quality', 'reader'], default='quality',
                   help='quality：更好看、更不像 AI（默认）；reader：更像目标平台读者会追的网文')
    a = ap.parse_args()
    JUDGE = a.judge
    if a.cmd == 'coverage':
        coverage(a.runs, Path(a.out), strict=a.strict)
    else:
        pairwise(a.base, a.cand, Path(a.out), criterion=a.criterion)


if __name__ == '__main__':
    sys.exit(main())
