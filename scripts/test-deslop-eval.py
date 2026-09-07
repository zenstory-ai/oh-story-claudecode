#!/usr/bin/env python3
"""Offline behavior tests for the optional real-CLI evaluation harness."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('deslop_eval', Path(__file__).with_name('run-deslop-eval.py'))
assert SPEC is not None and SPEC.loader is not None
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)

class EvalTests(unittest.TestCase):
    def test_completion_requires_turn_and_nonempty_body_and_report(self):
        scenarios = [
            ('unchanged', '原文。', '无需改动，已检测。', 'turn.completed', True, None),
            ('missing-report', '改文。', None, 'turn.completed', False, 'missing-output'),
            ('empty-report', '改文。', ' \n', 'turn.completed', False, 'empty-output'),
            ('empty-body', '\n', '完成报告。', 'turn.completed', False, 'empty-output'),
            ('no-turn', '改文。', '完成报告。', None, False, 'incomplete-turn'),
            ('failed-turn', '改文。', '部分报告。', 'turn.failed', False, 'failed-turn'),
        ]
        for name, body, prose_report, event, completed, error in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'skills/story-deslop'
                source.mkdir(parents=True)
                (source / 'SKILL.md').write_text('fixture policy')
                case = root / 'input.md'
                case.write_text('原文。')

                def cli(command, timeout):
                    work = Path(command[command.index('-C') + 1])
                    (work / '正文.md').write_text(body)
                    if prose_report is not None:
                        (work / '报告.md').write_text(prose_report)
                    stdout = json.dumps({'type': event}) if event else ''
                    return subprocess.CompletedProcess(command, 0, stdout, '')

                with patch.object(EVAL, 'run_cli', side_effect=cli):
                    result = EVAL.run_case(root, case, root / 'output', name, 30)
                self.assertEqual(result['completed'], completed)
                self.assertEqual(result.get('error'), error)
                report = json.loads((root / 'output' / name / 'run.json').read_text())
                self.assertEqual(report['completed'], completed)
                self.assertEqual(report['changed'], body != '原文。')
                if error:
                    self.assertIn('stdout_tail', report)

    def test_main_separates_change_from_completion(self):
        for report_present, expected_code in ((True, 0), (False, 1)):
            with self.subTest(report_present=report_present), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                skill = root / 'skills/story-deslop'
                skill.mkdir(parents=True)
                (skill / 'SKILL.md').write_text('fixture policy')
                cases = root / 'tests/fixtures/deslop-eval'
                cases.mkdir(parents=True)
                (cases / 'natural.md').write_text('原文。')

                def cli(command, timeout):
                    work = Path(command[command.index('-C') + 1])
                    if report_present:
                        (work / '报告.md').write_text('原文自然，无需修改。')
                    else:
                        (work / '正文.md').write_text('已改正文但遗漏报告。')
                    return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}', '')

                argv = ['run-deslop-eval.py', '--source-root', str(root), '--output', str(root / 'output'),
                        '--jobs', '1', '--replicates', '1']
                with (
                    patch.object(EVAL, 'ROOT', root), patch.object(sys, 'argv', argv),
                    patch.object(EVAL, 'run_cli', side_effect=cli),
                    patch.object(EVAL.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'test-cli', '')),
                ):
                    self.assertEqual(EVAL.main(), expected_code)

    def test_corrupt_output_is_preserved_as_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'skills/story-deslop'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('fixture policy')
            case = root / 'input.md'
            case.write_text('原文。')

            def cli(command, timeout):
                work = Path(command[command.index('-C') + 1])
                (work / '报告.md').write_bytes(b'\xff\xfe')
                return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}', '')

            with patch.object(EVAL, 'run_cli', side_effect=cli):
                result = EVAL.run_case(root, case, root / 'output', 'corrupt', 30)
            report = json.loads((root / 'output/corrupt/run.json').read_text())
            self.assertFalse(result['completed'])
            self.assertEqual(result['error'], 'invalid-output')
            self.assertEqual(report['invalid_outputs'], ['报告.md'])
            self.assertEqual((root / 'output/corrupt/报告.md').read_bytes(), b'\xff\xfe')
            self.assertIn('stdout_tail', report)

    def test_complete_artifacts_do_not_override_cli_or_event_failure(self):
        for name, code, event in (('exit', 7, None), ('error-event', 0, 'error'),
                                  ('failed-event', 0, 'turn.failed')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'skills/story-deslop'
                source.mkdir(parents=True)
                (source / 'SKILL.md').write_text('fixture policy')
                case = root / 'input.md'
                case.write_text('原文。')

                def cli(command, timeout):
                    work = Path(command[command.index('-C') + 1])
                    (work / '正文.md').write_text('改文。')
                    (work / '报告.md').write_text('非空报告。')
                    stdout = '{"type":"turn.completed"}\n'
                    if event:
                        stdout += json.dumps({'type': event})
                    return subprocess.CompletedProcess(command, code, stdout, '')

                with patch.object(EVAL, 'run_cli', side_effect=cli):
                    result = EVAL.run_case(root, case, root / 'output', name, 30)
                self.assertFalse(result['completed'])
                self.assertTrue(result['changed'])
                self.assertEqual(result['exit_code'], code)
                if event:
                    self.assertEqual(result['error'], 'failed-turn')

    def test_malformed_events_do_not_hide_completion_or_failure(self):
        events = ['null', '[]', '1', '"text"', '{"type":"item.completed","item":null}',
                  '{"type":"item.completed","item":[]}', 'not json',
                  '{"type":"turn.completed","usage":{"input_tokens":10}}',
                  '{"type":"turn.failed","message":"failure"}']
        self.assertEqual(EVAL.event_evidence('\n'.join(events)), [
            {'type': 'turn.completed', 'usage': {'input_tokens': 10}},
            {'type': 'turn.failed', 'message': 'failure'},
        ])

    def test_cli_success_and_timeout(self):
        result = EVAL.run_cli([sys.executable, '-c', 'print("fixture")'], 10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'fixture')
        timeout_command = [
            sys.executable,
            '-c',
            (
                'import sys,time; '
                'print("partial stdout", flush=True); '
                'print("partial stderr", file=sys.stderr, flush=True); '
                'time.sleep(30)'
            ),
        ]
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            EVAL.run_cli(timeout_command, 0.2)
        self.assertIn('partial stdout', raised.exception.stdout)
        self.assertIn('partial stderr', raised.exception.stderr)

    def test_isolation_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source/skills/story-deslop'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('fixture policy')
            case = root / 'input.md'
            case.write_text('原文。')
            seen = []
            def cli(command, timeout):
                work = Path(command[command.index('-C') + 1])
                seen.append(work)
                self.assertEqual((work / '.agents/skills/story-deslop/SKILL.md').read_text(), 'fixture policy')
                self.assertEqual((work / '正文.md').read_text(), '原文。')
                (work / '正文.md').write_text('改文。')
                (work / '报告.md').write_text('solo fallback; edited expression only')
                return subprocess.CompletedProcess(command, 0, json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10}}), '')
            with patch.object(EVAL, 'run_cli', side_effect=cli):
                result = EVAL.run_case(root / 'source', case, root / 'output', 'S01', 30)
            self.assertTrue(result['changed'])
            self.assertEqual(case.read_text(), '原文。')
            self.assertEqual((source / 'SKILL.md').read_text(), 'fixture policy')
            self.assertEqual((root / 'output/S01/正文.md').read_text(), '改文。')
            report = json.loads((root / 'output/S01/run.json').read_text())
            self.assertNotEqual(report['input_sha256'], report['output_sha256'])
            self.assertEqual(report['commands'][0]['usage']['input_tokens'], 10)
            self.assertFalse(seen[0].exists())

    def test_unchanged_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'skills/story-deslop'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('fixture policy')
            case = root / 'input.md'; case.write_text('原文。')
            with patch.object(EVAL, 'run_cli', return_value=subprocess.CompletedProcess([], 1, 'not json', 'offline')):
                result = EVAL.run_case(root, case, root / 'output', 'S02', 30)
            self.assertEqual(result['exit_code'], 1)
            self.assertFalse(result['changed'])
            report = json.loads((root / 'output/S02/run.json').read_text())
            self.assertEqual(report['stderr'], 'offline')
            self.assertEqual(report['stdout_tail']['text'], 'not json')
            self.assertFalse(report['stdout_tail']['truncated'])
            self.assertEqual(report['stdout_tail']['max_chars'], EVAL.STDOUT_TAIL_CHARS)

    def test_failure_stdout_tail_is_bounded_and_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'skills/story-deslop'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('fixture policy')
            case = root / 'input.md'
            case.write_text('原文。')

            def noisy_failure(command, timeout):
                work = Path(command[command.index('-C') + 1])
                stdout = 'x' * (EVAL.STDOUT_TAIL_CHARS + 100) + str(work) + '/failure.log'
                return subprocess.CompletedProcess(command, 3, stdout, 'failed')

            with patch.object(EVAL, 'run_cli', side_effect=noisy_failure):
                EVAL.run_case(root, case, root / 'output', 'S05', 30)

            report = json.loads((root / 'output/S05/run.json').read_text())
            tail = report['stdout_tail']
            self.assertTrue(tail['truncated'])
            self.assertEqual(tail['max_chars'], EVAL.STDOUT_TAIL_CHARS)
            self.assertLessEqual(len(tail['text']), EVAL.STDOUT_TAIL_CHARS)
            self.assertIn('{workspace}/failure.log', tail['text'])
            self.assertNotIn(str(root), tail['text'])

    def test_timeout_preserves_partial_artifacts_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'skills/story-deslop'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('fixture policy')
            case = root / 'input.md'
            case.write_text('原文。')

            def timeout_after_writes(command, timeout):
                work = Path(command[command.index('-C') + 1])
                (work / '正文.md').write_text('部分改文。')
                (work / '报告.md').write_text('partial report')
                (work / 'final.txt').write_text('partial final')
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=json.dumps({'type': 'turn.failed', 'message': 'timed out'}),
                    stderr='partial stderr',
                )

            with patch.object(EVAL, 'run_cli', side_effect=timeout_after_writes):
                result = EVAL.run_case(root, case, root / 'output', 'S03', 7)

            target = root / 'output/S03'
            report = json.loads((target / 'run.json').read_text())
            self.assertEqual(result['error'], 'timeout')
            self.assertEqual(report['error'], 'timeout')
            self.assertEqual(report['seconds'], 7)
            self.assertEqual((target / '正文.md').read_text(), '部分改文。')
            self.assertEqual((target / '报告.md').read_text(), 'partial report')
            self.assertEqual((target / 'final.txt').read_text(), 'partial final')
            for name in ('正文.md', '报告.md', 'final.txt'):
                expected = hashlib.sha256((target / name).read_bytes()).hexdigest()
                self.assertEqual(report['artifacts'][name]['sha256'], expected)
            self.assertTrue(report['changed'])
            self.assertIn('timed out', json.dumps(report['commands']))
            self.assertEqual(report['stderr'], 'partial stderr')

    def test_missing_body_after_cli_failure_is_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'skills/story-deslop'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('fixture policy')
            case = root / 'input.md'
            case.write_text('原文。')

            def failed_without_body(command, timeout):
                work = Path(command[command.index('-C') + 1])
                (work / '正文.md').unlink()
                (work / '报告.md').write_text('failure report')
                (work / 'final.txt').write_text('failure final')
                return subprocess.CompletedProcess(command, 9, '', 'cli failed')

            with patch.object(EVAL, 'run_cli', side_effect=failed_without_body):
                result = EVAL.run_case(root, case, root / 'output', 'S04', 30)

            target = root / 'output/S04'
            report = json.loads((target / 'run.json').read_text())
            self.assertEqual(result['error'], 'missing-output')
            self.assertEqual(result['exit_code'], 9)
            self.assertEqual(report['error'], 'missing-output')
            self.assertEqual(report['missing_outputs'], ['正文.md'])
            self.assertIsNone(report['output_sha256'])
            self.assertFalse(report['changed'])
            self.assertNotIn('正文.md', report['artifacts'])
            self.assertIn('报告.md', report['artifacts'])
            self.assertIn('final.txt', report['artifacts'])
            self.assertEqual(report['stderr'], 'cli failed')

    def test_empty_fixture_set_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'output'
            argv = ['run-deslop-eval.py', '--output', str(output)]
            with (
                patch.object(EVAL, 'ROOT', root),
                patch.object(sys, 'argv', argv),
                patch.object(EVAL.subprocess, 'run') as launch,
                self.assertRaises(SystemExit) as raised,
            ):
                EVAL.main()
            self.assertEqual(raised.exception.code, 2)
            launch.assert_not_called()
            self.assertFalse(output.exists())

if __name__ == '__main__':
    unittest.main()
