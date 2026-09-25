#!/usr/bin/env python3
"""基准正文的质量评测：单份细纲兑现核对 + 配对盲评，评委走 Antigravity（Gemini，与写手不同家族）。

用法：
  judge.py coverage <run目录>... --out <结果目录>
  judge.py pairwise --base <run目录>... --cand <run目录>... --out <结果目录>

coverage：每章单独评，评委只看本章细纲与正文，不知道版本；逐条判情节点是否落地、
          列出细纲没授权的新剧情事实。可数，结论不靠打分。
pairwise：同 (主机, 用例, 章号) 的两个版本随机分 A/B，交换顺序各评一次；
          两次一致才算胜负，不一致记平。评委不知道哪份是哪个版本。
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

JUDGE_MODEL = 'gemini-3.8-flash-high'

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

PAIRWISE_PROMPT = """你是番茄小说的资深编辑。下面是同一份细纲写出的两版第 {chapter} 章正文（A 与 B），
来源未知。请站在追更读者的角度判断哪一版更好看：更想往下读、人物更像活人、场面更具体、
更不像 AI 写的。只看成品，不因长短本身加减分。

只输出一个 JSON 对象，不要任何别的文字：
{{"winner": "A|B|tie", "reason": "两三句具体理由，引用原文片段"}}

===== 细纲 =====
{outline}

===== A =====
{a}

===== B =====
{b}
"""


def ask(prompt, cwd):
    completed = subprocess.run(
        ['agy', '-p', prompt, '--model', JUDGE_MODEL, '--output-format', 'text', '--print-timeout', '10m',
         '--disable-slash-commands', '--sandbox', '--dangerously-skip-permissions'],
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', stdin=subprocess.DEVNULL)
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


def coverage(runs, out):
    out.mkdir(parents=True, exist_ok=True)
    for run in runs:
        for meta, n, body, outline in chapters(run):
            dest = out / f'{Path(run).name}-{n:03d}.json'
            if dest.exists():
                continue
            prompt = COVERAGE_PROMPT.format(outline=outline.read_text(encoding='utf-8'),
                                            body=body.read_text(encoding='utf-8'))
            result, raw = ask(prompt, out)
            dest.write_text(json.dumps({'run': Path(run).name, 'host': meta['host'], 'case': meta['case']['id'],
                                        'pkg': meta['pkg'].get('ref'), 'chapter': n, 'result': result, 'raw': raw},
                                       ensure_ascii=False, indent=1), encoding='utf-8')
            print(dest.name, 'ok' if result else 'PARSE_FAIL', flush=True)


def pairwise(base_runs, cand_runs, out):
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for label, runs in (('base', base_runs), ('cand', cand_runs)):
        for run in runs:
            for meta, n, body, outline in chapters(run):
                index.setdefault((meta['host'], meta['case']['id'], n), {})[label] = (body, outline)
    for (host, case, n), pair in sorted(index.items()):
        if len(pair) != 2:
            continue
        dest = out / f'{host}-{case}-{n:03d}.json'
        if dest.exists():
            continue
        seed = int(hashlib.sha256(f'{host}{case}{n}'.encode()).hexdigest(), 16)
        first = random.Random(seed).choice(['base', 'cand'])
        second = 'cand' if first == 'base' else 'base'
        outline = pair['base'][1].read_text(encoding='utf-8')
        texts = {k: v[0].read_text(encoding='utf-8') for k, v in pair.items()}
        rounds = []
        for a, b in ((first, second), (second, first)):
            result, raw = ask(PAIRWISE_PROMPT.format(chapter=n, outline=outline, a=texts[a], b=texts[b]), out)
            w = (result or {}).get('winner')
            rounds.append({'A': a, 'B': b, 'winner': {'A': a, 'B': b}.get(w, 'tie' if w == 'tie' else None),
                           'reason': (result or {}).get('reason'), 'raw': raw})
        votes = [r['winner'] for r in rounds]
        final = votes[0] if votes[0] == votes[1] and votes[0] in ('base', 'cand') else 'tie'
        dest.write_text(json.dumps({'host': host, 'case': case, 'chapter': n, 'final': final, 'rounds': rounds},
                                   ensure_ascii=False, indent=1), encoding='utf-8')
        print(dest.name, final, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('coverage')
    c.add_argument('runs', nargs='+')
    c.add_argument('--out', required=True)
    p = sub.add_parser('pairwise')
    p.add_argument('--base', nargs='+', required=True)
    p.add_argument('--cand', nargs='+', required=True)
    p.add_argument('--out', required=True)
    a = ap.parse_args()
    if a.cmd == 'coverage':
        coverage(a.runs, Path(a.out))
    else:
        pairwise(a.base, a.cand, Path(a.out))


if __name__ == '__main__':
    sys.exit(main())
