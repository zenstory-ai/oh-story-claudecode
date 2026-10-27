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
EVALUATION_PROTOCOL = 1

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


def valid_result(result, mode):
    """Validate observations before they become scores or reusable assessments."""
    if mode not in ('coverage', 'strict', 'pairwise') or not isinstance(result, dict):
        return False
    if mode == 'pairwise':
        return result.get('winner') in ('A', 'B', 'tie') and isinstance(result.get('reason'), str) and bool(result['reason'].strip())
    field, values = ('render', ('scene', 'summary', 'missing')) if mode == 'strict' else (
        'status', ('landed', 'summarized', 'missing'))
    beats = result.get('beats')
    if not isinstance(beats, list) or not beats:
        return False
    ids = set()
    for beat in beats:
        if not isinstance(beat, dict):
            return False
        item_id = beat.get('id')
        if not isinstance(item_id, str) or not item_id.strip() or item_id in ids:
            return False
        ids.add(item_id)
        if not isinstance(beat.get('beat'), str) or not beat['beat'].strip() or beat.get(field) not in values:
            return False
        if mode == 'strict' and not isinstance(beat.get('quote'), str):
            return False
    if mode == 'strict':
        return True
    unauthorized = result.get('unauthorized')
    return isinstance(unauthorized, list) and all(
        isinstance(item, dict) and all(isinstance(item.get(k), str) and item[k].strip() for k in ('fact', 'quote'))
        for item in unauthorized)


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
    if completed.returncode != 0:
        return None, text + completed.stderr
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
        if not body or not outline:
            raise ValueError(f'{run}: committed chapter {n} is missing prose or outline')
        yield meta, n, body[0], outline[0]


def request_key(mode, inputs, prompts):
    payload = {'protocol': EVALUATION_PROTOCOL, 'mode': mode, 'judge': JUDGE_MODELS[JUDGE],
               'inputs': inputs, 'prompts': prompts}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def coverage_requests(runs, strict=False):
    mode = 'strict' if strict else 'coverage'
    for run in runs:
        run = Path(run).resolve()
        for meta, n, body, outline in chapters(run):
            prompt = (SCENE_PROMPT if strict else COVERAGE_PROMPT).format(
                outline=outline.read_text(encoding='utf-8'), body=body.read_text(encoding='utf-8'))
            identity = {'run': str(run), 'host': meta['host'], 'case': meta['case']['id'],
                        'pkg': meta['pkg'].get('ref'), 'chapter': n}
            key = request_key(mode, [{'run': str(run), 'meta': meta}], [prompt])
            yield identity, key, prompt


def pairwise_requests(base_runs, cand_runs):
    index = {}
    for label, runs in (('base', base_runs), ('cand', cand_runs)):
        for run in runs:
            for meta, n, body, outline in chapters(run):
                pair = index.setdefault((meta['host'], meta['case']['id'], n), {})
                if label in pair:
                    raise ValueError(f'{meta["host"]}/{meta["case"]["id"]}/{n}: duplicate {label} run; evaluate repetitions separately')
                pair[label] = (Path(run).resolve(), meta, body, outline)
    for (host, case, n), pair in sorted(index.items()):
        if len(pair) != 2:
            continue
        seed = int(hashlib.sha256(f'{host}{case}{n}'.encode()).hexdigest(), 16)
        first = random.Random(seed).choice(['base', 'cand'])
        second = 'cand' if first == 'base' else 'base'
        outlines = {k: v[3].read_text(encoding='utf-8') for k, v in pair.items()}
        texts = {k: v[2].read_text(encoding='utf-8') for k, v in pair.items()}
        requests = []
        for a, b in ((first, second), (second, first)):
            if outlines['base'] == outlines['cand']:
                source, outline = '同一份细纲', '===== 细纲 =====\n' + outlines['base']
            else:
                source = '各自细纲（同一段剧情、分别补写）'
                outline = '===== A 的细纲 =====\n%s\n\n===== B 的细纲 =====\n%s' % (outlines[a], outlines[b])
            prompt = PAIRWISE_PROMPT.format(source=source, chapter=n, outline=outline, a=texts[a], b=texts[b])
            requests.append((a, b, prompt))
        inputs = {label: {'run': str(value[0]), 'meta': value[1]} for label, value in pair.items()}
        key = request_key('pairwise', inputs, [r[2] for r in requests])
        identity = {'host': host, 'case': case, 'chapter': n,
                    'runs': {label: str(value[0]) for label, value in pair.items()}}
        yield identity, key, requests


def pairwise_winner(rounds):
    if not isinstance(rounds, list) or len(rounds) != 2:
        return None
    for item in rounds:
        if (not isinstance(item, dict) or item.get('A') not in ('base', 'cand')
                or item.get('B') not in ('base', 'cand') or item['A'] == item['B']):
            return None
        if item.get('winner') not in ('base', 'cand', 'tie') or not isinstance(item.get('reason'), str) or not item['reason'].strip():
            return None
    if rounds[0]['A'] != rounds[1]['B']:
        return None
    votes = [item['winner'] for item in rounds]
    return votes[0] if votes[0] == votes[1] else 'tie'


def cached_evaluation(out, mode, key):
    path = Path(out) / f'{mode}-{key}.json'
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or document.get('cache_key') != key or document.get('mode') != mode:
        return None
    if document.get('status') != 'complete' or document.get('judge') != JUDGE_MODELS[JUDGE]:
        return None
    if mode == 'pairwise':
        winner = pairwise_winner(document.get('rounds'))
        valid = winner is not None and document.get('final') == winner
    else:
        valid = valid_result(document.get('result'), mode)
    return document if valid else None


def coverage(runs, out, strict=False):
    out.mkdir(parents=True, exist_ok=True)
    mode = 'strict' if strict else 'coverage'
    failed = False
    for identity, key, prompt in coverage_requests(runs, strict):
        if cached_evaluation(out, mode, key) is not None:
            continue
        result, raw = ask(prompt, out)
        valid = valid_result(result, mode)
        failed |= not valid
        dest = out / f'{mode}-{key}.json'
        dest.write_text(json.dumps({**identity, 'cache_key': key, 'judge': JUDGE_MODELS[JUDGE],
                                    'mode': mode, 'status': 'complete' if valid else 'invalid',
                                    'result': result, 'raw': raw},
                                   ensure_ascii=False, indent=1), encoding='utf-8')
        print(dest.name, 'ok' if valid else 'INVALID', flush=True)
    return int(failed)


def pairwise(base_runs, cand_runs, out):
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    for identity, key, requests in pairwise_requests(base_runs, cand_runs):
        if cached_evaluation(out, 'pairwise', key) is not None:
            continue
        rounds = []
        for a, b, prompt in requests:
            result, raw = ask(prompt, out)
            w = result['winner'] if valid_result(result, 'pairwise') else None
            rounds.append({'A': a, 'B': b, 'winner': {'A': a, 'B': b}.get(w, 'tie' if w == 'tie' else None),
                           'reason': result.get('reason') if isinstance(result, dict) else None, 'raw': raw})
        final = pairwise_winner(rounds)
        valid = final is not None
        failed |= not valid
        dest = out / f'pairwise-{key}.json'
        dest.write_text(json.dumps({**identity, 'cache_key': key, 'judge': JUDGE_MODELS[JUDGE],
                                    'mode': 'pairwise', 'status': 'complete' if valid else 'invalid',
                                    'final': final, 'rounds': rounds},
                                   ensure_ascii=False, indent=1), encoding='utf-8')
        print(dest.name, final if valid else 'INVALID', flush=True)
    return int(failed)


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
    a = ap.parse_args()
    JUDGE = a.judge
    if a.cmd == 'coverage':
        return coverage(a.runs, Path(a.out), strict=a.strict)
    return pairwise(a.base, a.cand, Path(a.out))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as exc:
        sys.exit(str(exc))
