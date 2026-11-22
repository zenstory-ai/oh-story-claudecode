#!/usr/bin/env python3
"""Book-local expression exceptions through the public scanners and shared hook runtime.

0.10 删掉了文风裁决（style_resolution 槽与长篇的 style-resolution.md），但书级白名单
`.deslop-whitelist` 仍在用（规则在 long-format「书级白名单」一节），本测试守的是它的运行时行为，保留。
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/story-deslop/scripts'
HOOK = ROOT / 'skills/story-setup/references/templates/hooks/story_hook_core.js'
APPROVED = '不是退让，而是给彼此留条路。'
NOT_IS_PAD = '这不是巧合，而是早有预谋。这不是失误，而是故意试探。'
BLOCKING_NOT_IS = APPROVED + NOT_IS_PAD
OTHER = '声音不大，却压住了所有人的争吵。'
OTHER_2 = '他声音不高，却传遍了整条走廊。'
BLOCKING_VOICE = OTHER + OTHER_2


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

    def scan(self, fail_on='review_required'):
        return self.node(SCRIPTS / 'check-ai-patterns.js', '--json', f'--fail-on={fail_on}', self.file)

    def test_default_check_still_blocks(self):
        self.file.write_text('## 第1章 门\n“钥匙在——”\n钥匙在手——门开了。\n' + BLOCKING_NOT_IS, encoding='utf-8')
        self.assertEqual(self.scan('blocking').returncode, 0)
        result = self.scan()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        findings = payload['findings']
        self.assertGreater(payload['review_required'], 0)
        self.assertEqual(payload['blocking'], 0)
        self.assertEqual({'em-dash', 'not-is-comparison'}, {f['type'] for f in findings})
        self.assertEqual([3], [f['line'] for f in findings if f['type'] == 'em-dash'])

    def test_allowed_span_does_not_hide_other_problem_same_line(self):
        self.file.write_text('## 第1章 门\n😀' + BLOCKING_NOT_IS + BLOCKING_VOICE, encoding='utf-8')
        self.allow.write_text('# 来源：本书反复使用的和解判断\n' + APPROVED + '\n', encoding='utf-8')
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        findings = json.loads(result.stdout)['findings']
        review_req = [f for f in findings if f['severity'] == 'review_required']
        self.assertEqual(['voice-contrast', 'voice-contrast'], [f['type'] for f in review_req])
        self.assertIn('声音不大', review_req[0]['excerpt'])

    def test_pause_normalizer_keeps_author_choice_and_removes_unapproved_pause(self):
        self.allow.write_text('# 来源：文风；旁白停顿保留破折号\n——\n……\n', encoding='utf-8')
        original = '## 第1章 门\r\n钥匙在手——门开了。\n“你……也来了。”\r\n他--推门。\n'
        self.file.write_bytes(original.encode())
        result = self.node(SCRIPTS / 'normalize-punctuation.js', '--check', self.file)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('em-dash', result.stdout)
        self.assertNotIn('ellipsis', result.stdout)
        self.assertIn('double-hyphen', result.stdout)
        self.assertEqual(self.file.read_bytes(), original.encode())
        self.assertEqual(self.node(SCRIPTS / 'normalize-punctuation.js', self.file).returncode, 0)
        output = self.file.read_bytes()
        self.assertIn('钥匙在手——门开了。'.encode(), output)
        self.assertIn('“你……也来了。”'.encode(), output)
        self.assertNotIn(b'--', output)
        self.assertEqual(self.node(SCRIPTS / 'normalize-punctuation.js', '--check', self.file).returncode, 0)
        self.assertEqual(self.node(SCRIPTS / 'normalize-punctuation.js', self.file).returncode, 0)
        self.assertEqual(self.file.read_bytes(), output)

    def test_whitelist_does_not_escape_book_or_act_as_regex(self):
        self.file.write_text(BLOCKING_NOT_IS, encoding='utf-8')
        (self.root / '.deslop-whitelist').write_text(APPROVED, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 1)
        self.allow.write_text('# comment\n.*\n不是.*而是\n', encoding='utf-8')
        self.assertEqual(self.scan().returncode, 1)
        self.allow.write_text(APPROVED, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 0)
        self.allow.unlink()
        self.assertEqual(self.scan().returncode, 1)

    def test_hook_runtime_and_structural_findings_survive(self):
        text = BLOCKING_NOT_IS + BLOCKING_VOICE + '\nTODO\n最后还没'
        self.file.write_text(text, encoding='utf-8')
        self.allow.write_text(APPROVED + '\nTODO\n最后还没\n', encoding='utf-8')
        result = self.node('-e', "const h=require(process.argv[1]); console.log(h.proseAfterWrite(process.argv[2],process.argv[3]));", HOOK, self.root, self.file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('not-is-comparison', result.stdout)
        self.assertIn('voice-contrast', result.stdout)
        self.assertIn('占位符', result.stdout)
        self.assertIn('疑似截断', result.stdout)

    def test_next_chapter_gate_honors_only_approved_sentence(self):
        for dirname in ['大纲', '追踪']:
            (self.book / dirname).mkdir()
        # 细纲须写了内容（不计 # 号和空白 ≥30 字），否则写正文守卫先按空细纲拦下。
        (self.book / '大纲/细纲_第002章.md').write_text('# 已确认细纲\n她在门口等了一夜，天亮时终于决定不再回头，把钥匙留在了门垫下面。', encoding='utf-8')
        (self.book / '追踪/_tracking-state.json').write_text(json.dumps({'schema_version': 4, 'state_revision': 0, 'last_committed_chapter': 1}), encoding='utf-8')
        (self.book / '追踪/上下文.md').write_text('> 状态修订：0', encoding='utf-8')
        next_file = self.book / '正文/第002章_再见.md'
        for body, approved, should_warn in [
            (BLOCKING_NOT_IS, '', True),
            (BLOCKING_NOT_IS, APPROVED, False),
            (BLOCKING_NOT_IS + BLOCKING_VOICE, APPROVED, True),
        ]:
            self.file.write_text(body, encoding='utf-8')
            self.allow.write_text(approved, encoding='utf-8')
            result = self.node(
                '-e',
                "const h=require(process.argv[1]); console.log(JSON.stringify({block: h.proseBlockReason(process.argv[2],process.argv[3]), warnings: h.prosePreWriteWarnings(process.argv[2],process.argv[3])}));",
                HOOK,
                self.root,
                next_file,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertIsNone(payload['block'])
            warnings = payload['warnings']
            self.assertEqual(len(warnings) > 0, should_warn)
            if should_warn:
                self.assertIn('毒句式', '\n'.join(warnings))
        (self.book / '大纲/细纲_第002章.md').unlink()
        result = self.node('-e', "console.log(JSON.stringify(require(process.argv[1]).proseBlockReason(process.argv[2],process.argv[3])));", HOOK, self.root, next_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('缺少细纲', json.loads(result.stdout))

    def test_short_book_lookup(self):
        self.file = self.book / '正文.md'
        self.file.write_text(BLOCKING_NOT_IS, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 1)
        self.allow.write_text(APPROVED, encoding='utf-8')
        self.assertEqual(self.scan().returncode, 0)
        result = self.node('-e', "console.log(JSON.stringify(require(process.argv[1]).loadStyleWhitelist(process.argv[2])));", HOOK, self.file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [APPROVED])


if __name__ == '__main__':
    unittest.main()
