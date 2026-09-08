#!/usr/bin/env python3
"""公开 CLI 回归：取段闭包、存量卷纲、组装与召回降档。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'skills/story-long-write/scripts'


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='writer-pipeline-')
        self.addCleanup(self.tmp.cleanup)
        self.book = Path(self.tmp.name) / '雾港 来信'
        self.outline = self.put('大纲/细纲_第001章.md', '### 第 1 章：一封信\n- 单元ID/位置：L1-01；第1拍\n- 目标情绪：犹疑→决定替朋友保管信件\n')
        self.volume = self.put('大纲/卷纲_第一卷.md', self.volume_text())
        headings = ['当前位置', '长期约束', '核心角色状态', '活跃伏笔', '近三章速记', '下一章承诺', '连贯性风险']
        self.put('追踪/上下文.md', '\n'.join('## ' + h + '\n无\n' for h in headings))
        self.put('设定/文风.md', '# 文风\n' + '以对话与选择推进，保留必要的直接心理描述。\n' * 15)
        self.put('设定/题材正文提示卡.md', '# 关系\n保留人物各自的诉求，以具体选择推进关系。')

    def put(self, name, body):
        file = self.book / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body, encoding='utf-8')
        return file

    def call(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                              cwd=self.tmp.name, capture_output=True, encoding='utf-8',
                              env={**os.environ, 'PYTHONIOENCODING': 'ascii'})

    def view(self, *args):
        return self.call('outline_view.py', *args, self.volume)

    def build(self):
        return self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1)

    def volume_text(self, unit='L1-01'):
        return f'''# 第一卷
卷首约束：不能打开信。
## 卷契约
> 作用域：卷级常任
信件内容本卷不揭示。
### 剧情单元 {unit}
> 作用域：单元级 {unit}
- 章节范围：第1-3章
- 单元情绪引擎：犹疑→朋友托付→决定保管
- 单元节拍/章功能分配：第1章接信，第2章质疑，第3章保管
#### 供给自查
> 作用域：批次底稿 {unit}｜状态：在用
供给材料
### 剧情单元 L1-010
> 作用域：单元级 L1-010
不能串卡
'''

    def test_declared_ids_and_closure(self):
        for unit in ['L1-01', 'D2-03', 'U03']:
            with self.subTest(unit=unit):
                self.volume.write_text(self.volume_text(unit), encoding='utf-8')
                result = self.view('--unit', unit, '--stage', 'write')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('卷首约束', result.stdout)
                self.assertIn('本卷不揭示', result.stdout)
                self.assertNotIn('供给材料', result.stdout)
                self.assertNotIn('不能串卡', result.stdout)
                self.assertEqual(self.view('--check', '--strict').returncode, 0)

    def test_legacy_unit_field(self):
        self.volume.write_text('## 第一单元\n- **单元ID**：L1-01\n旧约束', encoding='utf-8')
        result = self.view('--unit', 'L1-01')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('旧约束', result.stdout)

    def test_missing_unit_is_error(self):
        self.assertEqual(self.view('--unit', 'L1-02').returncode, 1)

    def test_legacy_contract_is_conservative(self):
        self.volume.write_text('# 卷纲\n## 卷契约\n终局真相不能揭示\n### 剧情单元 L1-01\n旧卡', encoding='utf-8')
        for mode in [('--contract',), ('--unit', 'L1-01')]:
            result = self.view(*mode)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('终局真相不能揭示', result.stdout)
            self.assertIn('未声明', result.stderr)
        self.assertEqual(self.view('--check').returncode, 0)
        self.assertEqual(self.view('--check', '--strict').returncode, 1)

    def test_invalid_scope_does_not_silently_drop(self):
        self.volume.write_text('## 卷契约\n> 作用域：卷级常任错误\n不能丢失', encoding='utf-8')
        self.assertEqual(self.view('--contract').returncode, 1)

    def test_history_for_sections_and_rows(self):
        text = self.volume_text() + '\n#### 老底稿\n> 作用域：批次底稿 L1-01｜状态：已退役\n旧方案\n'
        text += '\n#### 老裁定\n> 作用域：单元级 L1-01｜状态：已退役\n旧口径\n'
        text += '\n## 常任补充\n> 作用域：卷级常任\n- ⊘ 旧行\n'
        self.volume.write_text(text, encoding='utf-8')
        for stage in ['outline', 'write']:
            current = self.view('--unit', 'L1-01', '--stage', stage).stdout
            for old in ['旧方案', '旧口径', '旧行']:
                self.assertNotIn(old, current)
        history = self.view('--unit', 'L1-01', '--history').stdout
        for old in ['旧方案', '旧口径', '旧行']:
            self.assertIn(old, history)

    def test_fenced_example_not_a_section_and_blank_scope(self):
        text = self.volume_text().replace('## 卷契约\n', '## 卷契约\n\n\n\n')
        text += '\n```md\n## 假章节\n> 作用域：单元级 L9-99\n```\n'
        self.volume.write_text(text, encoding='utf-8')
        self.assertEqual(self.view('--check', '--strict').returncode, 0)
        self.assertEqual(self.view('--unit', 'L9-99').returncode, 1)

    def test_builder_native_path_and_downgrade(self):
        out = self.book / 'prompt.txt'
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1, '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = out.read_text(encoding='utf-8')
        self.assertIn(str((self.book / '正文/第001章_一封信.md').resolve()), prompt)
        self.assertIn('第1章接信', prompt)
        self.assertNotIn('不能串卡', prompt)
        self.assertIn('召回降档：成立', result.stdout)
        self.assertNotIn('以上是 prompt 正文', prompt)

    def test_incomplete_replacements_keep_full_recall(self):
        original = self.volume.read_text(encoding='utf-8')
        for broken in ['missing-card', 'empty-card', 'placeholder-emotion', 'missing-unit', 'missing-engine', 'missing-tempo']:
            with self.subTest(broken=broken):
                self.set_inputs_for_downgrade(original)
                card = self.book / '设定/题材正文提示卡.md'
                if broken == 'missing-card': card.unlink()
                if broken == 'empty-card': card.write_text('# 题材卡\n[待补充]', encoding='utf-8')
                if broken == 'placeholder-emotion':
                    self.outline.write_text(self.outline.read_text(encoding='utf-8').replace('犹疑→决定替朋友保管信件', '[待补充][待补充][待补充]'), encoding='utf-8')
                if broken == 'missing-unit': self.volume.unlink()
                if broken in ['missing-engine', 'missing-tempo']:
                    word = '单元情绪引擎' if broken == 'missing-engine' else '单元节拍/章功能分配'
                    self.volume.write_text('\n'.join(line for line in original.splitlines() if word not in line), encoding='utf-8')
                result = self.build()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('召回降档：不成立', result.stdout)
                self.assertIn('全量召回', result.stdout)

    def set_inputs_for_downgrade(self, volume):
        self.volume.write_text(volume, encoding='utf-8')
        self.put('设定/题材正文提示卡.md', '关系通过保管信件的具体选择推进。')
        self.outline.write_text('### 第 1 章：一封信\n- 单元ID/位置：L1-01\n- 目标情绪：犹疑→决定替朋友保管信件', encoding='utf-8')

    def test_required_state_and_title(self):
        state = self.book / '追踪/上下文.md'
        original = state.read_text(encoding='utf-8')
        for heading in ['活跃伏笔', '长期约束', '下一章承诺']:
            state.write_text(original.replace('## ' + heading, '## 改名'), encoding='utf-8')
            self.assertEqual(self.build().returncode, 2)
        state.write_text(original, encoding='utf-8')
        self.outline.write_text('章名缺失', encoding='utf-8')
        self.assertEqual(self.build().returncode, 2)

    def test_previous_tail_and_nearest_heading(self):
        self.put('大纲/细纲_第011章.md', '### 第 11 章：回信\n')
        self.put('正文/第9章_旧.md', '### 第9章 旧\n九')
        self.put('正文/第10章_最近.md', '# 第010章 最近\n十')
        self.put('正文/第99章_未来.md', '#### 第99章 未来\n后续秘密')
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 11)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('：# 第011章 回信', result.stdout)
        self.assertNotIn('后续秘密', result.stdout)
        (self.book / '正文/第10章_最近.md').unlink()
        self.assertEqual(self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 11).returncode, 2)

    def test_multiline_unit_fields_and_short_style(self):
        self.put('设定/文风.md', '## 对话\n优先用短问句推进分歧，保留必要的直接心理。')
        text = self.volume_text().replace('单元节拍/章功能分配：第1章接信，第2章质疑，第3章保管', '单元节拍/章功能分配：\n  - 第1章接信\n  - 第2章质疑')
        self.volume.write_text(text, encoding='utf-8')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('召回降档：成立', result.stdout)
        self.assertIn('第2章质疑', result.stdout)

    def test_one_sentence_style_beats_stale_digest(self):
        style = self.put('设定/文风.md', '采用有限全知，允许进入母女各自内心。')
        digest = self.put('设定/_文风摘要.md', '旧规则：深度限知，不得进入他人内心。')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('custom_style=true', result.stdout)
        self.assertIn(str(style), result.stdout)
        self.assertNotIn(str(digest), result.stdout)
        self.assertNotIn('旧规则', result.stdout)
        for stub in ['', '# 文风', '# 文风\n[待补充]', '# 文风\n<!-- 作者稍后填写 -->']:
            style.write_text(stub, encoding='utf-8')
            self.assertIn('custom_style=false', self.build().stdout)

    def test_unreadable_utf8_is_reported(self):
        self.volume.write_bytes(b'\xff')
        self.assertEqual(self.view('--contract').returncode, 2)
        self.outline.write_bytes(b'\xff')
        result = self.build()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_style_reference_table_cannot_change_read_scope(self):
        style = self.put('设定/文风.md', '用短句，保留必要的直接心理。')
        original = self.build()
        self.assertEqual(original.returncode, 0, original.stderr)
        for table in [
            '| writing-craft.md | 停读 |\n| anti-ai-writing.md | 停读 |\n| agent-quality.md | 停读 |',
            '| references/* | 停读 |\n| dialogue-mastery.md | 读（只看排版） |',
        ]:
            with self.subTest(table=table):
                content = '用短句，保留必要的直接心理。\n## 通用参考裁决\n| 文件 | 裁决 |\n|---|---|\n' + table
                style.write_text(content, encoding='utf-8')
                result = self.build()
                self.assertEqual(result.returncode, 0, result.stderr)
                # Style remains a full-text input; a legacy table must not become
                # an extra executable instruction or narrow the reference set.
                self.assertEqual(result.stdout, original.stdout)
                self.assertEqual(style.read_text(encoding='utf-8'), content)



if __name__ == '__main__':
    unittest.main()
