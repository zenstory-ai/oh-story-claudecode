#!/usr/bin/env python3
"""对比两个版本的基准结果：效率降幅 + 质量非劣效门槛。

用法：
  compare.py --base <run目录>... --cand <run目录>... --coverage <judge coverage 目录>
             --pairwise <judge pairwise 目录> [--judge agy|claude|codex] [--tell <tell仓库>] [--json]

门槛（非劣效，全部满足才算通过；数值在预注册协议里冻结，这里是默认值）：
  Q1 情节点兑现率（landed=1、summarized=0.5、missing=0；未提交的章按 0 计）候选 − 基线 ≥ −0.05
  Q2 每章越界新增 候选 − 基线 ≤ +0.3
  Q3 配对盲评：有胜负的对里候选胜率 ≥ 0.35；有胜负的对少于 6 个判「证据不足」
  Q4 每章检测器 advisory 候选 − 基线 ≤ +1.0；给了 --tell 时人类区间越界项中位数差 ≤ +1
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402
import judge  # noqa: E402

SCORE = {'landed': 1.0, 'summarized': 0.5, 'missing': 0.0}


def coverage_rows(cov_dir, runs):
    rows = {}
    for identity, key, _ in judge.coverage_requests(runs):
        document = judge.cached_evaluation(cov_dir, 'coverage', key)
        if document is None:
            raise ValueError(f'{identity["run"]}, chapter {identity["chapter"]}: missing, stale or invalid '
                             'ordinary coverage; rerun judge.py coverage without --strict using the selected --judge')
        beats = document['result']['beats']
        rate = sum(SCORE[b['status']] for b in beats) / len(beats)
        rows[(identity['run'], identity['chapter'])] = (rate, len(document['result']['unauthorized']))
    return rows


def side(runs, cov_dir, tell):
    summaries = [metrics.summarize(r, tell) for r in runs]
    cov = coverage_rows(cov_dir, runs)
    rates, unauth, adv, tells = [], [], [], []
    for run, s in zip(runs, summaries):
        goal_chapters = s['chapters_goal']
        committed = {p['chapter']: p for p in s['prose'] if not p.get('missing')}
        keys = [k for k in cov if k[0] == str(Path(run).resolve())]
        for k in keys:
            rates.append(cov[k][0])
            unauth.append(cov[k][1])
        rates.extend([0.0] * max(0, goal_chapters - len(keys)))  # 没写出来的章按全漏计
        for p in committed.values():
            adv.append(p.get('detector', {}).get('advisory', 0))
            if p.get('human_ref_out_of_range') is not None:
                tells.append(p['human_ref_out_of_range'])
    eff = {}
    for key in ('wall_min', 'input_tokens_total_M', 'main_calls', 'spawns'):
        eff[key] = round(statistics.mean(s['per_chapter'][key] for s in summaries), 2)
    eff['compactions'] = sum(s['compactions'] for s in summaries)
    eff['chapters'] = f"{sum(s['chapters_committed'] for s in summaries)}/{sum(s['chapters_goal'] for s in summaries)}"
    return {
        'efficiency': eff,
        'coverage': round(statistics.mean(rates), 3) if rates else None,
        'unauthorized_per_chapter': round(statistics.mean(unauth), 2) if unauth else None,
        'advisory_per_chapter': round(statistics.mean(adv), 2) if adv else None,
        'tell_median': statistics.median(tells) if tells else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', nargs='+', required=True)
    ap.add_argument('--cand', nargs='+', required=True)
    ap.add_argument('--coverage', required=True)
    ap.add_argument('--pairwise', required=True)
    ap.add_argument('--tell')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--judge', choices=sorted(judge.JUDGE_MODELS), default='agy')
    a = ap.parse_args()
    judge.JUDGE = a.judge
    base, cand = side(a.base, a.coverage, a.tell), side(a.cand, a.coverage, a.tell)
    finals = []
    for identity, key, _ in judge.pairwise_requests(a.base, a.cand):
        document = judge.cached_evaluation(a.pairwise, 'pairwise', key)
        if document is None:
            raise ValueError(f'{identity}: missing, stale or invalid pairwise assessment; rerun judge.py pairwise')
        finals.append(document['final'])
    decisive = [f for f in finals if f in ('base', 'cand')]
    win = sum(f == 'cand' for f in decisive) / len(decisive) if decisive else None
    gates = {
        'Q1_coverage': (cand['coverage'] - base['coverage']) >= -0.05,
        'Q2_unauthorized': ('证据不足' if cand['unauthorized_per_chapter'] is None or base['unauthorized_per_chapter'] is None
                            else (cand['unauthorized_per_chapter'] - base['unauthorized_per_chapter']) <= 0.3),
        'Q3_pairwise': ('证据不足' if len(decisive) < 6 else win >= 0.35),
        'Q4_advisory': ('证据不足' if cand['advisory_per_chapter'] is None or base['advisory_per_chapter'] is None
                        else (cand['advisory_per_chapter'] - base['advisory_per_chapter']) <= 1.0),
    }
    if base['tell_median'] is not None and cand['tell_median'] is not None:
        gates['Q4_tell'] = (cand['tell_median'] - base['tell_median']) <= 1
    report = {'base': base, 'cand': cand,
              'pairwise': {'pairs': len(finals), 'decisive': len(decisive), 'cand_win_rate': win,
                           'tally': {k: finals.count(k) for k in ('cand', 'base', 'tie')}},
              'gates': gates}
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return
    print('| 指标 | 基线 | 候选 |\n|---|---|---|')
    for k in base['efficiency']:
        print(f"| {k} | {base['efficiency'][k]} | {cand['efficiency'][k]} |")
    for k in ('coverage', 'unauthorized_per_chapter', 'advisory_per_chapter', 'tell_median'):
        print(f'| {k} | {base[k]} | {cand[k]} |')
    print(f"\n配对盲评：{report['pairwise']}")
    print('门槛：' + '，'.join(f'{k}={v}' for k, v in gates.items()))


if __name__ == '__main__':
    try:
        main()
    except ValueError as exc:
        sys.exit(str(exc))
