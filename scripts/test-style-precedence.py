#!/usr/bin/env python3
"""Book-local expression exceptions through the public scanners and both hook runtimes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/story-deslop/scripts'
HOOK = ROOT / 'skills/story-setup/references/templates/hooks/story_hook_core.js'
spec = importlib.util.spec_from_file_location('codex_hook', ROOT / 'skills/story-setup/references/codex/hooks/story_codex_hook.py')
pyhook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pyhook)
APPROVED = '不是退让，而是给彼此留条路。'
OTHER = '声音不大，却压住了所有人的争吵。'


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='style-precedence-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.book = self.root / '书 A'
        (self.book / '正文').mkdir(parents=True)
        (self.book / '设定').mkdir()
        self.file = self.book / '正文/第001章_门.md'
        self.allow = self.book / '.deslop-whitelist'

    def node(self, script, *args):
        return subprocess.run(['node', str(script), *map(str, args)], capture_output=True, encoding='utf-8')

    def scan(self):
        return self.node(SCRIPTS / 'check-ai-patterns.js', '--json', '--fail-on=blocking', self.file)

    def test_default_check_still_blocks(self):
        self.file.write_text('## 第1章 门\n“钥匙在——”\n' + APPROVED, encoding='utf-8')
        result = self.scan()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual({'em-dash', 'not-is-comparison'}, {f['type'] for f in json.loads(result.stdout)['findings']})

    def test_allowed_span_does_not_hide_other_problem_same_line(self):
        self.file.write_text('## 第1章 门\n😀' + APPROVED + OTHER, encoding='utf-8')
        self.allow.write_text('# 来源：本书反复使用的和解判断\n' + APPROVED + '\n', encoding='utf-8')
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        findings = json.loads(result.stdout)['findings']
        self.assertEqual(['voice-contrast'], [f['type'] for f in findings])
        self.assertIn('声音不大', findings[0]['excerpt'])

    def test_pause_normalizer_keeps_author_choice_and_removes_unapproved_pause(self):
        self.allow.write_text('# 来源：文风；对白打断和犹豫\n——\n……\n', encoding='utf-8')
        original = '## 第1章 门\r\n“钥匙在——”\n“你……也来了。”\r\n他--推门。\n'
        self.file.write_bytes(original.encode())
        result = self.node(SCRIPTS / 'normalize-punctuation.js', '--check', self.file)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('em-dash', result.stdout)
        self.assertNotIn('ellipsis', result.stdout)
        self.assertIn('double-hyphen', result.stdout)
        self.assertEqual(self.file.read_bytes(), original.encode())
        self.assertEqual(self.node(SCRIPTS / 'normalize-punctuation.js', self.file).returncode, 0)
        output = self.file.read_bytes()
        self.assertIn('“钥匙在——”'.encode(), output)
        self.assertIn('“你……也来了。”'.encode(), output)
        self.assertNotIn(b'--', output)
        self.assertEqual(self.node(SCRIPTS / 'normalize-punctuation.js', '--check', self.file).returncode, 0)
        self.assertEqual(self.node(SCRIPTS / 'normalize-punctuation.js', self.file).returncode, 0)
        self.assertEqual(self.file.read_bytes(), output)

    def test_whitelist_does_not_escape_book_or_act_as_regex(self):
        self.file.write_text(APPROVED, encoding='utf-8')
        (self.root / '.deslop-whitelist').write_text(APPROVED, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 1)
        self.allow.write_text('# comment\n.*\n不是.*而是\n', encoding='utf-8')
        self.assertEqual(self.scan().returncode, 1)
        self.allow.write_text(APPROVED, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 0)
        self.allow.unlink()
        self.assertEqual(self.scan().returncode, 1)

    def test_hook_runtime_parity_and_structural_findings_survive(self):
        text = APPROVED + OTHER + '\nTODO\n最后还没'
        self.file.write_text(text, encoding='utf-8')
        self.allow.write_text(APPROVED + '\nTODO\n最后还没\n', encoding='utf-8')
        expected = pyhook.prose_net_findings(text, pyhook.load_style_whitelist(self.file))
        result = self.node('-e', "const fs=require('fs'), h=require(process.argv[1]); console.log(h.proseAfterWrite(process.argv[2],process.argv[3]));", HOOK, self.root, self.file)
        self.assertEqual(result.returncode, 0, result.stderr)
        for finding in expected:
            self.assertIn(finding, result.stdout)
        self.assertNotIn('not-is-comparison', result.stdout)
        self.assertIn('voice-contrast', result.stdout)
        self.assertIn('占位符', result.stdout)
        self.assertIn('疑似截断', result.stdout)

    def test_next_chapter_gate_honors_only_approved_sentence(self):
        for dirname in ['大纲', '追踪']:
            (self.book / dirname).mkdir()
        (self.book / '大纲/细纲_第002章.md').write_text('已确认细纲', encoding='utf-8')
        (self.book / '追踪/_tracking-state.json').write_text(json.dumps({'schema_version': 4, 'state_revision': 0, 'last_committed_chapter': 1}), encoding='utf-8')
        (self.book / '追踪/上下文.md').write_text('> 状态修订：0', encoding='utf-8')
        next_file = self.book / '正文/第002章_再见.md'
        for body, approved, should_block in [(APPROVED, '', True), (APPROVED, APPROVED, False), (APPROVED + OTHER, APPROVED, True)]:
            self.file.write_text(body, encoding='utf-8')
            self.allow.write_text(approved, encoding='utf-8')
            expected = pyhook.prose_block_reason(self.root, next_file)
            result = self.node('-e', "console.log(JSON.stringify(require(process.argv[1]).proseBlockReason(process.argv[2],process.argv[3])));", HOOK, self.root, next_file)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), expected)
            self.assertEqual(expected is not None, should_block)
            if should_block: self.assertIn('毒句式', expected)
        (self.book / '大纲/细纲_第002章.md').unlink()
        self.assertIn('缺少细纲', pyhook.prose_block_reason(self.root, next_file))

    def test_short_book_lookup(self):
        self.file = self.book / '正文.md'
        self.file.write_text(APPROVED, encoding='utf-8')
        self.allow.write_text(APPROVED, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 0)
        self.assertEqual(pyhook.load_style_whitelist(self.file), [APPROVED])


if __name__ == '__main__':
    unittest.main()
