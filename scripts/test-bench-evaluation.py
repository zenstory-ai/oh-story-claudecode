#!/usr/bin/env python3
"""Offline regressions for benchmark observations, scoring and cache identity."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BENCH = Path(__file__).resolve().parent / 'bench'
sys.path.insert(0, str(BENCH))
import judge
import compare

NORMAL = {'beats': [{'id': '1', 'beat': '拿出证据', 'status': 'landed'}], 'unauthorized': []}
STRICT = {'beats': [{'id': '1', 'beat': '拿出证据', 'render': 'scene', 'quote': '他拿出证据。'}]}
TIE = {'winner': 'tie', 'reason': '两版都呈现了证据交锋。'}


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='bench-evaluation-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.out = self.root / 'assessments'
        self.base = self.make_run('base')
        self.cand = self.make_run('cand')

    def make_run(self, name):
        run = self.root / name
        book = run / 'proj/book'
        (book / '正文').mkdir(parents=True)
        (book / '大纲').mkdir()
        (book / '正文/第001章.md').write_text('他拿出证据。', encoding='utf-8')
        (book / '大纲/细纲_第001章.md').write_text('1. 拿出证据', encoding='utf-8')
        meta = {'host': 'claude-code', 'model': 'writer', 'case': {'id': 'case', 'book_dir': 'book', 'chapters': 1},
                'start_committed': 0, 'end_committed': 1, 'pkg': {'ref': name}, 'turns': []}
        (run / 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
        return run

    def evaluate(self, run=None, result=None, strict=False):
        result = (STRICT if strict else NORMAL) if result is None else result
        with patch.object(judge, 'ask', return_value=(result, json.dumps(result))):
            return judge.coverage([run or self.base], self.out, strict=strict)

    def test_strict_is_separate_and_never_scores_as_zero_or_zero_unauthorized(self):
        self.assertEqual(self.evaluate(strict=True), 0)
        with self.assertRaisesRegex(ValueError, 'ordinary coverage'):
            compare.coverage_rows(self.out, [self.base])
        self.assertEqual(self.evaluate(), 0)
        self.assertEqual(compare.coverage_rows(self.out, [self.base]), {(str(self.base), 1): (1.0, 0)})
        self.assertEqual(self.evaluate(strict=True), 0)

    def test_missing_observations_are_invalid_not_zero_counts(self):
        invalid_results = [[], {'beats': []}, {'beats': NORMAL['beats']},
                           {'beats': [{'id': '1', 'beat': '拿出证据', 'status': 'unknown'}], 'unauthorized': []}]
        for result in invalid_results:
            with self.subTest(result=result):
                self.assertEqual(self.evaluate(result=result), 1)
                with self.assertRaises(ValueError):
                    compare.coverage_rows(self.out, [self.base])
        self.assertEqual(self.evaluate(), 0)
        self.assertEqual(compare.coverage_rows(self.out, [self.base])[(str(self.base), 1)], (1.0, 0))

    def test_invalid_pairwise_is_not_tie_and_can_be_retried(self):
        for result in (None, ['invalid'], {'winner': 'A'}, {'winner': 'unexpected', 'reason': '理由'}):
            with self.subTest(result=result), patch.object(judge, 'ask', return_value=(result, 'invalid')):
                self.assertEqual(judge.pairwise([self.base], [self.cand], self.out), 1)
                document = json.loads(next(self.out.glob('pairwise-*.json')).read_text(encoding='utf-8'))
                self.assertEqual(document['status'], 'invalid')
                self.assertIsNone(document['final'])
        with patch.object(judge, 'ask', return_value=(TIE, json.dumps(TIE))):
            self.assertEqual(judge.pairwise([self.base], [self.cand], self.out), 0)
        _, key, _ = next(judge.pairwise_requests([self.base], [self.cand]))
        self.assertEqual(judge.cached_evaluation(self.out, 'pairwise', key)['final'], 'tie')

    def test_swapped_votes_select_the_same_actual_run(self):
        identity, key, requests = next(judge.pairwise_requests([self.base], [self.cand]))
        replies = [({'winner': 'A' if a == 'cand' else 'B', 'reason': '候选把交锋写成了场景。'}, '')
                   for a, b, prompt in requests]
        with patch.object(judge, 'ask', side_effect=replies):
            self.assertEqual(judge.pairwise([self.base], [self.cand], self.out), 0)
        document = judge.cached_evaluation(self.out, 'pairwise', key)
        self.assertEqual(document['final'], 'cand')
        # A partial or tampered result must not become a cached victory.
        document['rounds'].pop()
        (self.out / f'pairwise-{key}.json').write_text(json.dumps(document), encoding='utf-8')
        self.assertIsNone(judge.cached_evaluation(self.out, 'pairwise', key))

    def test_cache_reuses_only_unchanged_valid_inputs(self):
        self.assertEqual(self.evaluate(), 0)
        with patch.object(judge, 'ask', side_effect=AssertionError('unexpected paid reevaluation')):
            self.assertEqual(judge.coverage([self.base], self.out), 0)
        body = self.base / 'proj/book/正文/第001章.md'
        body.write_text('他收起证据。', encoding='utf-8')
        with self.assertRaises(ValueError):
            compare.coverage_rows(self.out, [self.base])
        changed = copy.deepcopy(NORMAL)
        changed['beats'][0]['status'] = 'missing'
        self.assertEqual(self.evaluate(result=changed), 0)
        self.assertEqual(compare.coverage_rows(self.out, [self.base])[(str(self.base), 1)][0], 0.0)
        outline = self.base / 'proj/book/大纲/细纲_第001章.md'
        outline.write_text('1. 收起证据', encoding='utf-8')
        with self.assertRaises(ValueError):
            compare.coverage_rows(self.out, [self.base])
        self.assertEqual(self.evaluate(), 0)
        _, key, _ = next(judge.coverage_requests([self.base]))
        (self.out / f'coverage-{key}.json').write_text('{truncated', encoding='utf-8')
        self.assertEqual(self.evaluate(), 0)
        self.assertIsNotNone(judge.cached_evaluation(self.out, 'coverage', key))

    def test_model_prompt_and_protocol_changes_invalidate_cache(self):
        self.evaluate()
        changes = (
            patch.dict(judge.JUDGE_MODELS, {judge.JUDGE: 'different-model'}),
            patch.object(judge, 'COVERAGE_PROMPT', judge.COVERAGE_PROMPT + '\n新协议'),
            patch.object(judge, 'EVALUATION_PROTOCOL', judge.EVALUATION_PROTOCOL + 1),
        )
        for change in changes:
            with change:
                with self.assertRaises(ValueError):
                    compare.coverage_rows(self.out, [self.base])
                self.assertEqual(self.evaluate(), 0)
        self.assertEqual(compare.coverage_rows(self.out, [self.base])[(str(self.base), 1)], (1.0, 0))

    def test_runs_with_same_basename_do_not_share_coverage(self):
        other = self.make_run('other/base')
        self.evaluate()
        with self.assertRaises(ValueError):
            compare.coverage_rows(self.out, [other])
        missing = copy.deepcopy(NORMAL)
        missing['beats'][0]['status'] = 'missing'
        self.evaluate(other, missing)
        rows = compare.coverage_rows(self.out, [self.base, other])
        self.assertEqual(rows, {(str(self.base), 1): (1.0, 0), (str(other), 1): (0.0, 0)})

    def test_pairwise_cache_binds_both_runs_and_texts(self):
        with patch.object(judge, 'ask', return_value=(TIE, json.dumps(TIE))):
            judge.pairwise([self.base], [self.cand], self.out)
        with patch.object(judge, 'ask', side_effect=AssertionError('unexpected paid reevaluation')):
            self.assertEqual(judge.pairwise([self.base], [self.cand], self.out), 0)
        other = self.make_run('different-candidate')
        for candidate in (other, self.cand):
            if candidate == self.cand:
                (candidate / 'proj/book/正文/第001章.md').write_text('证据消失了。', encoding='utf-8')
            _, key, _ = next(judge.pairwise_requests([self.base], [candidate]))
            self.assertIsNone(judge.cached_evaluation(self.out, 'pairwise', key))

    def test_nonzero_judge_exit_cannot_supply_a_successful_assessment(self):
        failed = subprocess.CompletedProcess([], 1, json.dumps(NORMAL), 'process failed')
        with patch.object(judge.subprocess, 'run', return_value=failed):
            result, raw = judge.ask('evaluate', self.root)
        self.assertIsNone(result)
        self.assertIn('process failed', raw)


if __name__ == '__main__':
    unittest.main()
