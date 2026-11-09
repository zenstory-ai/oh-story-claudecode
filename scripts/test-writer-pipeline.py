#!/usr/bin/env python3
"""公开 CLI 回归：取段闭包、存量卷纲、组装与召回降档。"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'skills/story-long-write/scripts'
sys.path.insert(0, str(SCRIPTS))
from template_fence import TemplateNotFound, template_block  # noqa: E402
sys.path.pop(0)


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

    def call(self, script, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                              cwd=self.tmp.name, capture_output=True, encoding='utf-8',
                              env={**os.environ, 'PYTHONIOENCODING': 'ascii', **(env or {})})

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

    def test_arc_rows_sliced_in_template_form(self):
        # 卷纲模板的情绪弧线首列写「第{N}章」：按单元取段时同样只留本单元的行
        text = self.volume_text() + ('## 情绪弧线\n> 作用域：卷级常任\n| 章 | 定位 |\n|---|---|\n'
                                     '| 第1章 | 高压 |\n| 第3章 | 推进 |\n| 第5章 | 低压 |\n| 7 | 关系 |\n')
        self.volume.write_text(text, encoding='utf-8')
        out = self.view('--unit', 'L1-01').stdout
        self.assertIn('| 第1章 | 高压 |', out)
        self.assertIn('| 第3章 | 推进 |', out)
        self.assertNotIn('第5章', out)
        self.assertNotIn('| 7 |', out)

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

    def test_default_view_is_the_writing_closure(self):
        result = self.view('--unit', 'L1-01')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('本卷不揭示', result.stdout)
        self.assertNotIn('供给材料', result.stdout)
        self.assertIn('供给材料', self.view('--unit', 'L1-01', '--stage', 'outline').stdout)

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
            self.assertIn('没标全卷或单元编号', result.stderr)
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
        for old in ['旧口径', '旧行']:
            self.assertIn(old, history)
        # 老卷纲里的批次底稿只在排纲档出现（默认写作档不带底稿）
        self.assertNotIn('旧方案', history)
        self.assertIn('旧方案', self.view('--unit', 'L1-01', '--history', '--stage', 'outline').stdout)

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

    def test_builder_injects_author_memory_query(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('作者偏好（作者记下的写作习惯', result.stdout)
        self.assertIn('作者记忆：无相关 active 条目', result.stdout)
        (self.book / '.story-deployed').write_text('agents_version: 34\n', encoding='utf-8')
        event = {'schema_version': 1, 'event_id': 'e1', 'operation': {'action': 'remember', 'preference': {
            'kind': 'prose_style', 'scope': {'level': 'global', 'value': None}, 'assertion': '对话一律用直角引号',
            'quote': '对话一律用「」', 'source_ref': 'test', 'source': 'explicit_user', 'confidence': 'high',
            'importance': 'high', 'status': 'active', 'reason': '作者明确要求', 'conflicts_with': [],
            }}}
        memory_input = Path(self.tmp.name) / 'memory.json'
        memory_input.write_text(json.dumps(event, ensure_ascii=False), encoding='utf-8')
        recorded = self.call('author_memory_commit.py', 'record', '--workspace', self.book, '--input', memory_input)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        result = self.build()
        self.assertIn('- 对话一律用直角引号（AP001）', result.stdout)
        self.assertIn('作者记忆：已注入 1 条', result.stdout)

    def test_builder_reports_missed_author_memory_in_author_words(self):
        # 超编时装不下的条目不能悄悄略过：注入块只放写手读到的那几行（计满 2KB），
        # 核对报告点名全部漏项（不再只数前 20 个编号），并拼好章末对作者说的原话。
        (self.book / '.story-deployed').write_text('agents_version: 34\n', encoding='utf-8')
        self.assertEqual(self.call('author_memory_commit.py', 'init', '--workspace', self.book).returncode, 0)
        operations = [{'action': 'remember', 'preference': {
            'kind': 'prose_style', 'scope': {'level': 'global', 'value': None},
            'assertion': f'习惯{n:02d}：' + '写' * 36, 'quote': f'第{n}条习惯', 'source_ref': 'test',
            'source': 'explicit_user', 'confidence': 'high', 'importance': 'medium', 'status': 'active',
            'reason': '作者明确要求', 'conflicts_with': [],
        }} for n in range(1, 41)]
        memory_input = Path(self.tmp.name) / 'memory.json'
        for revision, batch in enumerate((operations[:32], operations[32:])):  # 一份事务最多 32 条
            memory_input.write_text(json.dumps({'schema_version': 1, 'transaction_id': f'flood-{revision}',
                                                'expected_state_revision': revision, 'operations': batch},
                                               ensure_ascii=False), encoding='utf-8')
            committed = self.call('author_memory_commit.py', 'commit', '--workspace', self.book, '--input', memory_input)
            self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        out = self.book / 'prompt.txt'
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1, '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = out.read_text(encoding='utf-8')
        injected = [line for line in prompt.splitlines() if line.startswith('- 习惯')]
        self.assertEqual(len(injected), 15)  # 每行 133 字节，2048 装 15 条；旧口径按 JSON 外壳只装 8 条
        self.assertEqual(sum(len((line + '\n').encode('utf-8')) for line in injected) <= 2048, True)
        # 同重要度按最近更新排：第二批（AP033-040）先装，第一批装到 AP007 为止
        self.assertNotIn('习惯08：', prompt)
        self.assertNotIn('没带上', prompt)  # 给作者的话只在核对报告里，不进写手 prompt
        report = result.stdout.split('以下不进 prompt', 1)[1]
        self.assertIn('这章没带上 25 条（AP008、', report)
        self.assertIn('AP032）', report)
        self.assertIn('你记下的写作习惯这章有 25 条没带上：「习惯08：写写写写写写写写写…」', report)
        self.assertIn('「习惯15：写写写写写写写写写…」等；说「整理作者记忆」可以合并相近的、调低不常用的。', report)

    def test_builder_merges_multi_genre_misses_by_importance(self):
        # 本书两个题材各查一次再合并：某次漏、另一次带上的不算没带上；两次都带上的只注入一遍；
        # 合并后的漏项按重要度排，后一次查询才漏的 high 习惯排在前一次漏的 low 习惯前面；不到 8 条不加「等」。
        (self.book / '.story-deployed').write_text('agents_version: 34\n', encoding='utf-8')
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市 · 悬疑\n')
        self.assertEqual(self.call('author_memory_commit.py', 'init', '--workspace', self.book).returncode, 0)

        def op(assertion, importance, level='global', value=None):
            return {'action': 'remember', 'preference': {
                'kind': 'prose_style', 'scope': {'level': level, 'value': value}, 'assertion': assertion,
                'quote': assertion, 'source_ref': 'test', 'source': 'explicit_user', 'confidence': 'high',
                'importance': importance, 'status': 'active', 'reason': '作者明确要求', 'conflicts_with': [],
            }}

        first = ([op(f'全局低{n:02d}：' + '写' * 35, 'low') for n in range(1, 11)]  # AP001-010
                 + [op('全局高：短句推进', 'high')]  # AP011
                 + [op(f'悬疑高{n:02d}：' + '写' * 35, 'high', 'genre', '悬疑') for n in range(1, 9)])  # AP012-019
        second = [op(f'都市高{n:02d}：' + '写' * 35, 'high', 'genre', '都市') for n in range(1, 17)]  # AP020-035
        memory_input = Path(self.tmp.name) / 'memory.json'
        for revision, batch in enumerate((first, second)):
            memory_input.write_text(json.dumps({'schema_version': 1, 'transaction_id': f'genres-{revision}',
                                                'expected_state_revision': revision, 'operations': batch},
                                               ensure_ascii=False), encoding='utf-8')
            committed = self.call('author_memory_commit.py', 'commit', '--workspace', self.book, '--input', memory_input)
            self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        out = self.book / 'prompt.txt'
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1, '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = out.read_text(encoding='utf-8')
        self.assertEqual(prompt.count('- 全局高：短句推进（AP011）'), 1)  # 两次查询都带上，只注入一遍
        self.assertIn('- 全局低07：', prompt)  # 悬疑那次带上、都市那次漏掉：算带上了
        report = result.stdout.split('以下不进 prompt', 1)[1]
        self.assertIn('这章没带上 4 条（AP035、AP008、AP009、AP010）', report)
        self.assertIn('你记下的写作习惯这章有 4 条没带上：「都市高16：写写写写写写写写…」「全局低08：', report)
        self.assertIn('「全局低10：写写写写写写写写…」；说「整理作者记忆」', report)  # 不到 8 条不加「等」

    def test_builder_keeps_misses_from_earlier_genre_query(self):
        # 只有前一次查询才漏的本题材习惯，合并时不能被后一次查询的结果冲掉；
        # 前一次挤掉、后一次带上的全局习惯不算没带上。
        (self.book / '.story-deployed').write_text('agents_version: 34\n', encoding='utf-8')
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市 · 悬疑\n')
        self.assertEqual(self.call('author_memory_commit.py', 'init', '--workspace', self.book).returncode, 0)

        def op(assertion, importance, level='global', value=None):
            return {'action': 'remember', 'preference': {
                'kind': 'prose_style', 'scope': {'level': level, 'value': value}, 'assertion': assertion,
                'quote': assertion, 'source_ref': 'test', 'source': 'explicit_user', 'confidence': 'high',
                'importance': importance, 'status': 'active', 'reason': '作者明确要求', 'conflicts_with': [],
            }}

        first = ([op(f'全局低{n:02d}', 'low') for n in range(1, 5)]  # AP001-004，每行 25 字节
                 + [op('全局高', 'high')]  # AP005
                 + [op(f'悬疑高{n:02d}：' + '写' * 35, 'high', 'genre', '悬疑') for n in range(1, 17)])  # AP006-021
        second = [op(f'都市高{n:02d}：' + '写' * 35, 'high', 'genre', '都市') for n in range(1, 6)]  # AP022-026
        memory_input = Path(self.tmp.name) / 'memory.json'
        for revision, batch in enumerate((first, second)):
            memory_input.write_text(json.dumps({'schema_version': 1, 'transaction_id': f'early-{revision}',
                                                'expected_state_revision': revision, 'operations': batch},
                                               ensure_ascii=False), encoding='utf-8')
            committed = self.call('author_memory_commit.py', 'commit', '--workspace', self.book, '--input', memory_input)
            self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = result.stdout.split('以下不进 prompt', 1)[1]
        # 悬疑那次漏 AP021 与 AP002-004；都市那次全装下，AP002-004 算带上了
        self.assertIn('这章没带上 1 条（AP021）', report)
        self.assertIn('- 全局低04（AP004）', result.stdout)

    def remember(self, workspace, assertion, *, book_root=None, level='global', value=None):
        event = {'schema_version': 1, 'event_id': f'm-{assertion}', 'operation': {'action': 'remember', 'preference': {
            'kind': 'prose_style', 'scope': {'level': level, 'value': value}, 'assertion': assertion,
            'quote': assertion, 'source_ref': 'test', 'source': 'explicit_user', 'confidence': 'high',
            'importance': 'high', 'status': 'active', 'reason': '作者明确要求', 'conflicts_with': [],
        }}}
        memory_input = Path(self.tmp.name) / 'memory.json'
        memory_input.write_text(json.dumps(event, ensure_ascii=False), encoding='utf-8')
        args = ['record', '--workspace', workspace, '--input', memory_input]
        if book_root is not None:
            args += ['--book-root', book_root]
        recorded = self.call('author_memory_commit.py', *args)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def move_book(self, *parts):
        target = Path(self.tmp.name).joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.book), str(target))
        self.book = target
        return target

    def memory_files(self, root):
        return sorted(str(p.relative_to(root)) for p in root.rglob('*') if '作者记忆' in str(p))

    def test_builder_finds_workspace_without_deploy_marker(self):
        # DSH 等宿主不写 .story-deployed：按 长篇/ 上一层、.active-book、拆文库/ 或项目级记忆认出工作区，
        # 全局条目（项目级）与本书条目都要代查进来，不能退回主会话手查。
        cases = [
            ('长篇下的书', ('多书甲', '长篇', '雾港 来信'), None),
            ('有 .active-book', ('多书乙', '雾港 来信'), '.active-book'),
            ('有拆文库', ('多书丙', '雾港 来信'), '拆文库'),
        ]
        for name, parts, marker in cases:
            with self.subTest(layout=name):
                book = self.move_book(*parts)
                workspace = Path(self.tmp.name) / parts[0]
                if marker == '.active-book':
                    (workspace / marker).write_text('雾港 来信\n', encoding='utf-8')
                elif marker:
                    (workspace / marker).mkdir()
                # 先只有本书条目：工作区根还没有项目级记忆，只能靠 长篇/、.active-book、拆文库/ 认出来
                self.remember(workspace, f'{name}：本书条目', book_root=book, level='book', value='雾港 来信')
                result = self.build()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'- {name}：本书条目（BP', result.stdout)
                self.assertNotIn('脚本查询失败', result.stdout)
                self.remember(workspace, f'{name}：全局条目')
                result = self.build()
                self.assertIn(f'- {name}：全局条目（AP', result.stdout)
                self.assertIn(f'- {name}：本书条目（BP', result.stdout)

    def test_builder_single_book_layout_without_deploy_marker(self):
        # DSH 常用的单书布局：书根就是工作区，项目级与书级（书级/）两份记忆都在书目录下。
        # 外层目录恰好有 拆文库/ 也不改认：项目级记忆所在的最近一层就是工作区。
        self.move_book('外层', '雾港 来信')
        (Path(self.tmp.name) / '外层' / '拆文库').mkdir()
        # 先只有书级记忆（住在 书级/）：同样认书目录，否则本书条目会去外层找而丢失。
        self.remember(self.book, '单书：本书条目', book_root=self.book, level='book', value='雾港 来信')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- 单书：本书条目（BP001）', result.stdout)
        self.remember(self.book, '单书：全局条目')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- 单书：全局条目（AP001）', result.stdout)
        self.assertIn('- 单书：本书条目（BP001）', result.stdout)

    def test_builder_never_takes_book_under_long_dir_as_workspace(self):
        # 长篇/ 下的书目录永远不当工作区：哪怕书的记忆目录里多了个 书级/（比如旧版误挪留下的空目录），
        # 也要先按上一层叫 长篇 认出工作区，不能当成单书布局去查（作者记忆工具会直接报错）。
        book = self.move_book('多书丁', '长篇', '雾港 来信')
        workspace = book.parent.parent
        self.remember(workspace, '长篇优先：本书条目', book_root=book, level='book', value='雾港 来信')
        (book / '.story' / '作者记忆' / '书级').mkdir()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- 长篇优先：本书条目（BP001）', result.stdout)
        self.assertNotIn('脚本查询失败', result.stdout)

    def test_builder_never_takes_home_as_workspace(self):
        # 主目录本身不当工作区：主目录里误放的 .active-book 不能把书认到主目录去。
        book = self.move_book('假主目录', '雾港 来信')
        home = book.parent
        (home / '.active-book').write_text('雾港 来信\n', encoding='utf-8')
        self.remember(home, '主目录：本书条目', book_root=book, level='book', value='雾港 来信')
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1,
                           env={'HOME': str(home), 'USERPROFILE': str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('认不出创作工作区', result.stdout)

    def test_builder_does_not_guess_workspace_over_book_memory(self):
        # 书直接放在没有任何迹象的工作区下、只有书级记忆：拿书目录当工作区去查会被当成单书布局的旧版记忆
        # 「归位」进 书级/，此后用正确工作区查询全部报错。认不出就不代查、零写入，交主会话定工作区。
        book = self.move_book('无迹象工作区', '雾港 来信')
        workspace = book.parent
        self.remember(workspace, '无迹象：本书条目', book_root=book, level='book', value='雾港 来信')
        before = self.memory_files(workspace)
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('认不出创作工作区', result.stdout)
        self.assertEqual(self.memory_files(workspace), before, '代查不得挪动书级记忆')
        query = self.call('author_memory_commit.py', 'query', '--workspace', workspace, '--book-root', book,
                          '--kind', 'prose_style')
        self.assertEqual(query.returncode, 0, query.stdout + query.stderr)
        self.assertEqual(json.loads(query.stdout)['lines'], ['- 无迹象：本书条目（BP001）'])

    def test_builder_queries_scoped_author_memory(self):
        (self.book / '.story-deployed').write_text('agents_version: 34\n', encoding='utf-8')
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市 · 悬疑（无言情线）\n')
        memory_input = Path(self.tmp.name) / 'memory.json'
        for n, (level, value, assertion) in enumerate([
                ('genre', '悬疑', '悬疑线索先埋后揭'), ('workflow', '长篇', '长篇每章结尾留钩子'),
                ('genre', '仙侠', '仙侠用古风称谓'), ('workflow', '交稿', '交稿前先报字数'),
                ('genre', '言情', '言情线慢热')], 1):
            event = {'schema_version': 1, 'event_id': f's{n}', 'operation': {'action': 'remember', 'preference': {
                'kind': 'prose_style', 'scope': {'level': level, 'value': value}, 'assertion': assertion,
                'quote': assertion, 'source_ref': 'test', 'source': 'explicit_user', 'confidence': 'high',
                'importance': 'high', 'status': 'active', 'reason': '作者明确要求', 'conflicts_with': [],
                }}}
            memory_input.write_text(json.dumps(event, ensure_ascii=False), encoding='utf-8')
            recorded = self.call('author_memory_commit.py', 'record', '--workspace', self.book, '--input', memory_input)
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        # 本书题材与长篇流程的限定条目要代查进来，不能只剩全局与本书条目。
        self.assertIn('悬疑线索先埋后揭', result.stdout)
        self.assertIn('长篇每章结尾留钩子', result.stdout)
        self.assertNotIn('仙侠用古风称谓', result.stdout)
        # 判断不了的限定取值不静默丢弃，留给主会话。
        self.assertNotIn('言情线慢热', result.stdout)  # 「无言情线」不是言情题材
        self.assertIn('另有限定范围的作者记忆未代查（题材：仙侠、言情；流程：交稿）', result.stdout)

    def test_builder_injects_author_decided_with_a_cap(self):
        # 定方向落盘的书级决定（偏好、红线）写章时要能看到：脚本注入「作者已定」，超长截断并指回原文。
        self.put('设定/题材定位.md', '# 题材定位\n## 基本信息\n- 题材类型：都市\n## 作者已定\n'
                 '- {作者在对话里定下的方向}\n- 不写感情线，主角全程单身\n- 否掉：重生开局（作者嫌老套）\n'
                 '## 读者契约\n- 核心读者承诺：不注入这一节\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('——— 作者已定（本书的决定', result.stdout)
        self.assertIn('- 不写感情线，主角全程单身', result.stdout)
        self.assertNotIn('{作者在对话里定下的方向}', result.stdout)
        self.assertNotIn('不注入这一节', result.stdout)
        self.assertIn('作者已定：已注入', result.stdout)
        self.put('设定/题材定位.md', '## 作者已定\n' + ''.join(f'- 第{i}条红线：' + '禁' * 40 + '\n' for i in range(30)))
        long = self.build()
        self.assertIn('超过 600 字已截断', long.stdout)
        self.assertIn('第0条红线', long.stdout)
        self.assertNotIn('第29条红线', long.stdout)
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市\n')
        self.assertIn('作者已定：题材定位里没有或为空，未注入', self.build().stdout)

    def test_builder_matches_genre_cards_when_the_book_has_none(self):
        # 新书第 1 章还没有题材正文提示卡：脚本按「题材类型」匹配卡，主会话不必整读 3K 的索引。
        (self.book / '设定/题材正文提示卡.md').unlink()
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市日常 · 豪门总裁\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        cards = SCRIPTS.parent / 'references' / 'genre-prose-cards'
        self.assertIn(f"主题材 {cards / '都市日常.md'}（置信度 high）；辅题材 {cards / '豪门总裁.md'}", result.stdout)
        self.assertIn('召回降档：不成立（题材正文提示卡缺有效内容）', result.stdout)
        # 最长匹配优先：「玄幻言情」「仙侠言情」里的「玄幻」「仙侠」是别的卡的短别名，不能抢走主卡。
        for line, main, loser in [('玄幻言情', '玄幻言情.md', '传统玄幻.md'),
                                  ('仙侠言情', '玄幻言情.md', '东方仙侠.md'),
                                  ('传统玄幻 · 玄幻言情', '传统玄幻.md', None)]:
            with self.subTest(genre=line):
                self.put('设定/题材定位.md', f'# 题材定位\n- 题材类型：{line}\n')
                out = self.build().stdout
                self.assertIn(f"主题材 {cards / main}", out)
                if loser:
                    self.assertNotIn(str(cards / loser), out)
                else:
                    self.assertIn(f"辅题材 {cards / '玄幻言情.md'}", out)
        # 匹配不到时给流派兜底卡，和命中走同一条路（同一行点名卡的路径）。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：蒸汽朋克考古\n')
        out = self.build().stdout
        self.assertIn('题材卡无匹配', out)
        self.assertIn(f"主题材 {cards / '流派兜底.md'}（置信度 low）", out)
        # 兜底卡不参与按名匹配：它的名字写进题材类型也不会被当成真题材卡。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市日常\n')
        self.assertNotIn('流派兜底.md', self.build().stdout)

    def test_bare_out_archives_into_book_work_dir(self):
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1, '--out')
        self.assertEqual(result.returncode, 0, result.stderr)
        work = (self.book / '.story/work/第001章').resolve()
        archived = work / 'writer_prompt.md'
        self.assertTrue(archived.is_file())
        self.assertIn(f'留档：{archived}', result.stdout)
        prompt = archived.read_text(encoding='utf-8')
        # The scratch dir is concrete and book-local; the chapter is written in one pass (no segments).
        self.assertIn(str(work), prompt)
        self.assertNotIn('前组', prompt)
        self.assertFalse((self.book / '正文').exists() and any((self.book / '正文').iterdir()))

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

    def test_no_benchmark_book_downgrades_without_style(self):
        # 作者定了不对标、也没写文风：情绪与节奏取细纲与单元卡，不因缺文风走全量召回
        style = self.book / '设定' / '文风.md'
        if style.exists():
            style.unlink()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('召回降档：成立，无对标', result.stdout)
        (self.book / '对标' / '某书').mkdir(parents=True)
        (self.book / '对标' / '某书' / '文风.md').write_text('x', encoding='utf-8')
        self.assertIn('召回降档：不成立', self.build().stdout)

    def test_imported_book_own_analysis_is_not_benchmark(self):
        # 导入的书在拆文库里留有与书目录同名的拆文目录：那是本书自己，仍判无对标
        style = self.book / '设定' / '文风.md'
        if style.exists():
            style.unlink()
        for base in (self.book.parent / '拆文库', self.book / '拆文库'):
            (base / self.book.name).mkdir(parents=True, exist_ok=True)
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('召回降档：成立，无对标', result.stdout)
        (self.book.parent / '拆文库' / '别的书').mkdir()
        self.assertIn('召回降档：不成立', self.build().stdout)

    def test_one_sentence_style_beats_stale_digest(self):
        style = self.put('设定/文风.md', '采用有限全知，允许进入母女各自内心。')
        digest = self.put('设定/_文风摘要.md', '旧规则：深度限知，不得进入他人内心。')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('文风：本书有 设定/文风.md', result.stdout)
        self.assertIn(str(style), result.stdout)
        self.assertNotIn(str(digest), result.stdout)
        self.assertNotIn('旧规则', result.stdout)
        for stub in ['', '# 文风', '# 文风\n[待补充]', '# 文风\n<!-- 作者稍后填写 -->']:
            style.write_text(stub, encoding='utf-8')
            self.assertNotIn('文风：本书有 设定/文风.md', self.build().stdout)

    def test_outline_two_lines_are_reported_not_blocked(self):
        # 写前两行缺了只在核对报告点名，不拒写；占位写法都算缺，新旧字段名都认。
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('细纲两行：缺 主角目标/关键选择', result.stdout)
        for value in ['[待补充]', '无', '待定', '{主角本章要什么}']:
            with self.subTest(value=value):
                self.outline.write_text('### 第 1 章：一封信\n- 单元ID/位置：L1-01\n- 目标情绪：犹疑→决定\n'
                                        f'- 主角目标/关键选择：{value}\n', encoding='utf-8')
                self.assertIn('细纲两行：缺 主角目标/关键选择', self.build().stdout)
        self.outline.write_text('### 第 1 章：一封信\n- 属于哪段剧情：第一段剧情：接信（L1-01）\n'
                                '- 目标情绪：犹疑→决定替朋友保管信件\n- 主角目标/关键选择：决定替朋友保管信件\n',
                                encoding='utf-8')
        result = self.build()
        self.assertIn('细纲两行：目标情绪、主角目标/关键选择都有', result.stdout)
        self.assertIn('单元 L1-01', result.stdout)
        # 新细纲只写段名、不写编号：按章号落在卷纲哪段剧情的章节范围里定位。
        self.outline.write_text('### 第 1 章：一封信\n- 属于哪段剧情：第一段剧情：接信，第一步：接下托付\n'
                                '- 目标情绪：犹疑→决定替朋友保管信件\n- 主角目标/关键选择：决定替朋友保管信件\n',
                                encoding='utf-8')
        self.assertIn('单元 L1-01', self.build().stdout)

    def test_chapter_lookup_by_range(self):
        # --chapter：按章号找本章落在哪段剧情的章节范围里，取那一段（同 --unit）；找不到不静默降级。
        hit = self.view('--chapter', '2')
        self.assertEqual(hit.returncode, 0, hit.stderr)
        self.assertIn('犹疑→朋友托付→决定保管', hit.stdout)
        self.assertNotIn('不能串卡', hit.stdout)
        self.assertIn('L1-01', hit.stderr)
        miss = self.view('--chapter', '9')
        self.assertEqual(miss.returncode, 1)
        self.assertIn('第 9 章', miss.stderr)

    def test_benchmark_registered_as_none_wins_over_library(self):
        # 「无对标」唯一定义：登记为无，或登记缺失且目录里没有别的书。
        (self.book / '设定' / '文风.md').unlink()
        (self.book.parent / '拆文库' / '别的书').mkdir(parents=True)
        self.assertIn('召回降档：不成立', self.build().stdout)
        self.put('设定/题材定位.md', '# 题材定位\n## 对标登记\n- 主对标书：无（作者 11 月 3 日定）\n')
        result = self.build()
        self.assertIn('召回降档：成立，无对标', result.stdout)
        self.assertIn('按作者这次的要求和通用写法写', result.stdout)
        self.put('设定/题材定位.md', '# 题材定位\n## 对标登记\n- 主对标书：别的书\n')
        result = self.build()
        self.assertIn('召回降档：不成立', result.stdout)
        self.assertIn('［主会话填］ 本书没有 设定/文风.md', result.stdout)
        # 排除本书自己按书目录名与题材定位「书名」两处认，对标/ 里误建的自对标同样不算。
        self.put('设定/题材定位.md', '# 题材定位\n- 书名：《雾港旧信》（暂定）\n')
        (self.book.parent / '拆文库' / '别的书').rmdir()
        (self.book / '对标' / '雾港旧信').mkdir(parents=True)
        self.assertIn('召回降档：成立，无对标', self.build().stdout)

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


    def test_architect_brief_carries_only_the_moment_files(self):
        # 开书按作者确认点分时刻：卷纲任务包只带卷纲时刻的流程、模板与技法，细纲任务包只带细纲时刻的；
        # 主会话不读包，story-architect 在新上下文里只读包和项目文件。
        bundle = SCRIPTS.parents[1] / 'story-setup' / 'references' / 'agent-references'
        vol = self.call('build_architect_brief.py', '--project', self.book, '--task', 'volume', '--volume', 1)
        self.assertEqual(vol.returncode, 0, vol.stderr)
        info = json.loads(vol.stdout)
        text = Path(info['brief']).read_text(encoding='utf-8')
        self.assertEqual(Path(info['brief']).parent, self.book / '.story' / 'work' / '排纲')
        self.assertEqual(info['includes'], ['workflow-volume.md（排纲方法）', 'artifact-protocols.md',
                                            'outline-methods.md（卷纲排法）',
                                            'reader-contract-and-progression.md', 'SKILL.md（新增物三级）',
                                            '按条件可读（包外）'])
        # 包外读不到 SKILL.md：新增物三级判据随包；流程点名的条件参考给出 agent 副本路径与小节，路径都要在副本里。
        self.assertIn('**先问作者**：新主线事件或反转', text)
        self.assertIn('agent-references/long-reversal.md` 「反转类型」一节', text)
        self.assertNotIn('## 情感虐心三板斧', text)
        # 卷纲排法每次随包；常见的八步结构、情绪模块公式、换地图按条件在包外读。
        self.assertIn('### 剧情单元设计', text)
        self.assertNotIn('## 常见的八步结构', text)
        self.assertNotIn('## 情绪模块公式', text)
        self.assertIn('agent-references/outline-methods.md` 「常见的八步结构」一节', text)
        self.assertIn('agent-references/character-relations.md` 「感情线阶段」一节', text)
        # 流程文件只截「排纲方法」：主会话的读取清单与作者汇报模板不进包。
        self.assertIn('## 排纲方法', text)
        self.assertIn('### 排纲刻度', text)
        self.assertNotIn('<!-- author-report -->', text)
        self.assertNotIn('## 主会话', text)
        self.assertNotIn('## 细纲（第 N 章）', text)
        self.assertLess(info['chars'], 30000)
        # story-architect 不能执行命令：覆盖本批章节的单元闭包由脚本取好放进包里。
        self.volume.write_text(self.volume_text() + '### 剧情单元 L1-02\n> 作用域：单元级 L1-02\n'
                               '- 章节范围：第4-12章\n- 单元情绪引擎：保管→被追查→反将一军\n', encoding='utf-8')
        first = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline',
                                     '--chapters', '1-3').stdout)
        later = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline',
                                     '--chapters', '4-10').stdout)
        self.assertIn('opening-design.md（开篇规划）', first['includes'])
        self.assertFalse(any(name.startswith('opening-design.md') for name in later['includes']))
        self.assertIn('plot-core-methods.md', first['includes'])
        self.assertIn('plot-core-methods.md（不含开篇噱头）', later['includes'])
        self.assertTrue(any('剧情段 L1-01' in name for name in first['includes']))
        self.assertTrue(any('剧情段 L1-02' in name for name in later['includes']))
        self.assertFalse(any('剧情段 L1-01' in name for name in later['includes']))
        # 排纲笔记写进书目录的隐藏目录，任务包点明路径
        self.assertTrue(any('.story/排纲笔记/L1-01.md' in name for name in first['includes']))
        outline_text = Path(first['brief']).read_text(encoding='utf-8')
        self.assertIn('卷首约束', outline_text)  # 卷级常任随闭包进包
        self.assertIn('你不执行命令', outline_text)
        both = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline',
                                    '--chapters', '2-5').stdout)
        both_text = Path(both['brief']).read_text(encoding='utf-8')
        self.assertIn('保管→被追查', both_text)
        self.assertEqual(both_text.count('信件内容本卷不揭示'), 1)  # 跨两个单元，卷级常任只给一次
        uncovered = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '30-31')
        self.assertEqual(uncovered.returncode, 2)
        self.assertIn('找不到覆盖第30-31章的剧情段', uncovered.stderr)
        # 单元只覆盖请求的一部分：不能静默只给一半，点名缺的章。
        partial = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '10-14')
        self.assertEqual(partial.returncode, 2, partial.stdout)
        self.assertIn('剧情段只覆盖了一部分，缺覆盖第13-14章', partial.stderr)
        rules = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline',
                                     '--chapters', '30-31', '--rules-only').stdout)
        self.assertFalse(any('卷纲取段' in name for name in rules['includes']))
        self.assertIn('## 细纲（第 N 章）', outline_text)
        self.assertIn('## 开篇规划', outline_text)
        self.assertNotIn('## 开篇落笔', outline_text)
        self.assertIn('## 高潮构建公式', outline_text)
        self.assertIn('## 噱头分类与开篇流程', outline_text)
        self.assertNotIn('<!-- author-report -->', outline_text)
        later_text = Path(later['brief']).read_text(encoding='utf-8')
        self.assertIn('## 高潮构建公式', later_text)
        self.assertNotIn('## 噱头分类与开篇流程', later_text)
        # 细纲模板要求从章首 7 式、章尾 13 式里选：两张表随包，实战模板不进包。
        self.assertIn('## 章尾钩子 13 式', outline_text)
        self.assertIn('## 章首钩子 7 式', outline_text)
        self.assertNotIn('## 章尾实战模板', outline_text)
        # 只带名称与公式两列，示例句不进包（细纲会照抄示例的句子形状）。
        self.assertIn('| 13 | 留白钩子 | 只展示反应，不揭示发生了什么 |\n', outline_text)
        self.assertNotIn('他看了信', outline_text)
        self.assertIn('long-chapter-hooks.md（章尾钩子 13 式、章首钩子 7 式）', later['includes'])
        # 角色卡按围栏标签只取模板本身：反派设计等方法不进细纲任务包。
        self.assertIn('### 设定/角色/{名}.md（主角）', outline_text)
        self.assertIn('角色定位：', outline_text)
        self.assertNotIn('第3节：反派设计', outline_text)
        self.assertIn('outline-template.md', first['includes'])  # 细纲与排纲笔记模板整份进包
        self.assertIn('## 排纲笔记（', outline_text)
        world = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'world').stdout)
        world_text = Path(world['brief']).read_text(encoding='utf-8')
        self.assertIn('## 作者已定', world_text)  # 设定模板随包，定方向落盘的作者决定有处可读
        self.assertIn('核心梗三层递进设计', world_text)
        self.assertIn('## 金手指', world_text)
        self.assertIn('agent-references/character-relations.md` 「感情线阶段」一节', world_text)
        self.assertNotIn('## 微创新与差异化设计', world_text)
        self.assertNotIn('## 感情流人设核心法', world_text)
        self.assertNotIn('全书体量与阶段总览', world_text)
        self.assertNotIn('主会话自己定设定时读', world_text)  # 主会话的读取清单不进包
        self.assertIn('agent-references/female-audience-writing.md` 整份', world_text)
        for brief_text in (text, outline_text, world_text):
            for name in re.findall(r'`agent-references/([\w-]+\.md)`', brief_text):
                self.assertTrue((bundle / name).is_file(), name)
        self.assertIn('按下附「新增物三级」属问作者', world_text)
        # 定设定多一份全书梗概：任务包点名要写它，模板随包，结局一节写明可空。
        self.assertIn('`设定/全书梗概.md`', world_text)
        self.assertIn('## 结局（目前的设想，可空）', world_text)
        # 细纲模板是新写法：「这章怎么走」、默认三列情节点表，「这章不能说破」挪进可选块，不再写字数口径。
        self.assertIn('#### 这章怎么走', outline_text)
        self.assertIn('| # | 情节点（谁做了什么） | 作用 |\n', outline_text)
        self.assertIn('- 这章不能说破：{这章确有一件具体的事要压住时才写一行', outline_text)
        self.assertNotIn('- 字数口径：', outline_text)
        self.assertNotIn('<!-- {单元编号', outline_text)  # 「属于哪段剧情」不再写编号注释
        # 前 3 章细纲要排一次正面冲突、立起够大的赌注。
        self.assertIn('正面冲突', outline_text)
        self.assertIn('够大的赌注', outline_text)
        too_many = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-11')
        self.assertEqual(too_many.returncode, 2)
        self.assertIn('一批细纲最多 10 章', too_many.stderr)


    def test_architect_brief_names_unit_cards_missing_scope_lines(self):
        # 单元卡少了「> 作用域：」行时取段器认不出它，报错要点名这张卡，而不是笼统说「要写章节范围」。
        self.volume.write_text('# 第一卷\n### 剧情单元 L1-01\n- 章节范围：第1-3章\n', encoding='utf-8')
        result = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-3')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('标题末尾缺单元编号注释（如 <!-- L1-01 -->）：卷纲_第一卷.md「剧情单元 L1-01」', result.stderr)
        self.assertIn('--check --strict', result.stderr)
        # 新写法：编号在标题尾部注释里，任务包照样取得到这段剧情（老写法见上面几条用例）。
        self.volume.write_text('# 第一卷\n## 全卷规矩 <!-- 全卷 -->\n1. 信不拆\n'
                               '### 第一段剧情：码头 <!-- L1-01 -->\n- 章节范围：第1-3章\n'
                               '#### 备注\n- 子标题跟着这一段\n', encoding='utf-8')
        fresh = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-3')
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        info = json.loads(fresh.stdout)
        self.assertTrue(any('剧情段 L1-01' in name for name in info['includes']))
        text = Path(info['brief']).read_text(encoding='utf-8')
        self.assertIn('子标题跟着这一段', text)
        self.assertIn('信不拆', text)


class ImportOutlineBriefTests(unittest.TestCase):
    """导入逐批反推细纲：任务包只带本批规则、抽好的摘要要点、测好的长度与重叠的剧情单元卡。"""

    SCRIPT = ROOT / 'skills/story-import/scripts/build_outline_brief.py'
    SUMMARY = ('## 第{n}章\n\n**概要**：概要不进包{n}\n\n**关键事件**：\n1. 江晨推门{n}\n2. 看见雨\n\n'
               '**因果**：雨夜来信\n\n**局面结果**：信被收下\n\n**涉及**：江晨，老周\n\n**信息变化**：读者知道信是假的\n\n'
               '**状态变化**：江晨 犹疑→决定\n\n**三维节奏**：三维节奏不进包\n\n**章尾钩子**：悬念：信里写了谁\n\n'
               '**证据**：证据不进包\n\n**情节点**：\n\n'
               'P1 **雨夜推门**：类型行动 | 白描不进包 | 涉及江晨 | 地点无 | 物品无 | 时间无\n\n'
               '主题标签悬念 | 基调：紧张\n\n---\n\n'
               'P2 **收下来信**：类型转折点 | 白描不进包 | 涉及江晨 | 地点无 | 物品信 | 时间无\n\n'
               '主题标签悬念 | 基调：压抑\n')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='import-brief-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.book = self.root / '旧书'
        for chapter in range(1, 26):
            self.put(f'正文/第{chapter:03d}章_雨夜.md', f'# 第{chapter}章 雨夜\n\n他推开门，看见雨。' + '字' * chapter + '\n')
            if chapter != 7:
                self.summary(chapter, self.SUMMARY.format(n=chapter))
        self.volume(('L1-01', '第1-12章', '接信'), ('L1-02', '第13-25章', '反击'))

    def put(self, name, body):
        file = self.book / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body, encoding='utf-8')

    def summary(self, chapter, body):
        file = self.root / '拆文库' / '旧书' / '章节' / f'第{chapter}章_摘要.md'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body, encoding='utf-8')

    def volume(self, *cards):
        """cards: (单元ID, 章节范围, 节拍)；按导入卷纲模板写单元卡。"""
        body = ''.join(f'### 剧情单元 {uid}\n> 作用域：单元级 {uid}\n\n- 单元ID：{uid}\n- 章节范围：{span}\n'
                       f'- 单元节拍/章功能分配：{beat}\n- 下一单元因果钩子：第1-2章的回响\n\n' for uid, span, beat in cards)
        self.put('大纲/卷纲_第1卷.md', '# 第一卷 卷纲\n\n## 剧情单元卡（反推）\n> 作用域：卷级常任\n\n' + body +
                 '## 人物弧线\n> 作用域：卷级常任\n\n| 角色 | 本卷起点 |\n|---|---|\n| 甲 | 第1-99章 |\n')

    def call(self, chapters):
        return subprocess.run([sys.executable, str(self.SCRIPT), '--project', str(self.book), '--chapters', chapters],
                              cwd=self.root, capture_output=True, encoding='utf-8',
                              env={**os.environ, 'PYTHONIOENCODING': 'ascii'})

    def brief(self, chapters):
        result = self.call(chapters)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        return info, Path(info['brief']).read_text(encoding='utf-8')

    def test_brief_carries_batch_evidence_and_rules(self):
        info, text = self.brief('1-12')
        self.assertEqual(Path(info['brief']).parent, (self.book / '.story' / 'work' / '排纲').resolve())
        # 长度按 visible_chars_v1 由脚本测好：story-architect 不能执行命令。
        self.assertEqual(info['metric'], 'visible_chars_v1')
        self.assertEqual(info['lengths']['3'], len('他推开门，看见雨。') + 3)
        self.assertEqual(info['missing_summaries'], [7])
        self.assertEqual((info['chapters'], info['next']), ('1-12', 13))
        self.assertIn('### 剧情单元 L1-01', text)
        self.assertIn('- 单元节拍/章功能分配：接信', text)
        self.assertNotIn('L1-02', text)
        self.assertNotIn('| 甲 |', text)  # 别的表不串进来
        self.assertIn('## 细纲（第 N 章）', text)
        self.assertIn('你不执行命令', text)
        self.assertIn('导入记录.md', text)

    def test_brief_extracts_summary_fields_instead_of_paths_only(self):
        info, text = self.brief('1-12')
        # 写细纲要用的字段抽进包里，执行者不再整读摘要。
        for want in ('关键事件：江晨推门3 看见雨', '因果：雨夜来信', '局面结果：信被收下', '涉及：江晨，老周',
                     '信息变化：读者知道信是假的', '状态变化：江晨 犹疑→决定', '章尾钩子：悬念：信里写了谁',
                     'P1 雨夜推门｜行动｜紧张；P2 收下来信｜转折点｜压抑'):
            self.assertIn(want, text)
        for skip in ('概要不进包', '三维节奏不进包', '证据不进包', '白描不进包'):
            self.assertNotIn(skip, text)
        # 缺摘要的章要读正文：chars 计入执行者真正要读的总量。
        body7 = (self.book / '正文' / '第007章_雨夜.md').read_text(encoding='utf-8')
        self.assertIn('摘要：未找到', text)
        self.assertEqual(info['chars'], len(''.join(text.split())) + len(''.join(body7.split())))

    def test_first_chapter_carries_previous_hook(self):
        # 章首钩子取上一章的章尾钩子；批内各章的上一章摘要都在包里，只有第一章要另带。
        _, text = self.brief('11-20')
        self.assertIn('- 上一章（第10章）章尾钩子：悬念：信里写了谁', text)
        self.assertEqual(text.count('章尾钩子：悬念'), 11)  # 10 章各自的章尾钩子 + 第一章带的上一章
        _, first = self.brief('1-12')
        self.assertNotIn('- 上一章（', first)

    def test_legacy_summary_labels_still_extracted(self):
        self.summary(2, '- 关键事件：推门\n\n**出场人物**：\n\n| 角色 | 本章重要性 |\n|---|---|\n| 林雷 | major |\n| 希尔曼 | minor |\n\n'
                        '- **卡点与伏笔**：结尾卡点：信没拆\n')
        _, text = self.brief('1-12')
        self.assertIn('关键事件：推门', text)
        self.assertIn('涉及：林雷、希尔曼', text)
        self.assertIn('章尾钩子：结尾卡点：信没拆', text)
        self.assertIn('局面结果：（摘要未写）', text)

    def test_batch_shrinks_when_brief_too_big(self):
        for chapter in range(1, 26):
            if chapter != 7:
                self.summary(chapter, self.SUMMARY.format(n=chapter).replace('看见雨', '雨' * 3000))
        info, text = self.brief('1-12')
        first, last = map(int, info['chapters'].split('-'))
        self.assertEqual(first, 1)
        self.assertLess(last, 10)  # 包按总量切，可以少于 10 章
        self.assertEqual(info['next'], last + 1)
        self.assertLessEqual(info['chars'], info['limit'])
        self.assertTrue(Path(info['brief']).name.endswith(f'第001-{last:03d}章.md'))
        self.assertNotIn(f'### 第{last + 1}章', text)

    def test_unit_cards_selected_by_chapter_range_field(self):
        self.volume(('L1-01', '第1-5章', '接信'), ('L1-02', '第6-9章', '反击'), ('L1-03', '第10-10章', '余波'),
                    ('L1-04', '第15-15章', '单元编号不当章号'), ('L1-05', '第13-25章', '远处'))
        _, text = self.brief('1-12')
        for card in ('### 剧情单元 L1-01', '### 剧情单元 L1-02', '### 剧情单元 L1-03'):
            self.assertIn(card, text)
        self.assertNotIn('L1-04', text)  # 只认「章节范围」字段，其他字段里的「第1-2章」不算
        self.assertNotIn('L1-05', text)

    def test_cards_the_writer_cannot_read_stop_the_brief(self):
        # 写正文时 outline_view.py --unit 认不出的卷纲（缺作用域行、旧的表格形单元），任务包也不收。
        self.put('大纲/卷纲_第1卷.md', '# 第一卷\n\n### 剧情单元 L1-01\n- 章节范围：第1-12章\n')
        missing_scope = self.call('1-12')
        self.assertEqual(missing_scope.returncode, 2)
        self.assertIn('单元编号注释', missing_scope.stderr)
        self.put('大纲/卷纲_第1卷.md', '# 第一卷\n\n## 剧情单元（反推）\n| 单元ID | 章节范围 |\n|---|---|\n| L1-1 | 第1-12章 |\n')
        table = self.call('1-12')
        self.assertEqual(table.returncode, 2)
        self.assertIn('--check --strict', table.stderr)

    def test_import_volume_template_passes_writer_gates(self):
        # 导入卷纲模板原样落盘要过取段器严格校验，写正文按单元取得到卡；填上章节范围后任务包也认得。
        doc = (ROOT / 'skills/story-import/references/structure-mapping-long.md').read_text(encoding='utf-8')
        after = doc.split('#### 目标格式模板（大纲/卷纲_第X卷.md）', 1)[1]
        template = after.split('```markdown\n', 1)[1].split('\n```\n', 1)[0]
        self.put('大纲/卷纲_第1卷.md', template.replace('第{A}-{B}章', '第1-25章') + '\n')
        volume = self.book / '大纲' / '卷纲_第1卷.md'
        view = lambda *args: subprocess.run(
            [sys.executable, str(SCRIPTS / 'outline_view.py'), *args, str(volume)],
            capture_output=True, encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        check = view('--check', '--strict')
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn('问题 0 ／ 告警 0', check.stdout)
        unit = view('--unit', 'L1-01')
        self.assertEqual(unit.returncode, 0, unit.stderr)
        self.assertIn('这段让读者图什么', unit.stdout)
        _, text = self.brief('1-12')
        self.assertIn('### 第一段剧情：{一句话} <!-- L1-01 -->', text)
        # 导入带的取段器副本与写作端是同一份，两边解析不会分叉。
        self.assertEqual((ROOT / 'skills/story-import/scripts/outline_view.py').read_bytes(),
                         (SCRIPTS / 'outline_view.py').read_bytes())

    def test_batch_bounds(self):
        too_many = self.call('1-21')
        self.assertEqual(too_many.returncode, 2)
        self.assertIn('最多 20 章', too_many.stderr)
        too_few = self.call('1-5')
        self.assertEqual(too_few.returncode, 2)
        self.assertIn('至少 10 章', too_few.stderr)
        info, text = self.brief('21-25')  # 全书最后一批可以不足 10 章
        self.assertIn('L1-02', text)
        self.assertIsNone(info['next'])
        beyond = self.call('20-30')
        self.assertEqual(beyond.returncode, 2)
        self.assertIn('正文只迁到第25章', beyond.stderr)

    def test_missing_volume_outline_stops(self):
        (self.book / '大纲' / '卷纲_第1卷.md').unlink()
        result = self.call('1-12')
        self.assertEqual(result.returncode, 2)
        self.assertIn('没有卷纲', result.stderr)


class TemplateFenceTests(unittest.TestCase):
    """按围栏标签取模板：只取那一块，不在或重复都报错，围栏里的围栏不算新围栏。"""

    def test_template_block(self):
        doc = ('# 文件\n\n````markdown template=细纲\n## 细纲\n```text\n示例\n```\n- 核心事件：\n````\n\n'
               '```markdown\n未标的模板\n```\n')
        self.assertEqual(template_block(doc, '细纲'), '## 细纲\n```text\n示例\n```\n- 核心事件：')
        with self.assertRaises(TemplateNotFound):
            template_block(doc, '卷纲')
        with self.assertRaises(TemplateNotFound):
            template_block(doc + '```md template=细纲\nx\n```\n', '细纲')


class VolumeTemplateContractTests(unittest.TestCase):
    """artifact-protocols.md 的卷纲模板原样落盘，必须过取段器的严格校验。"""

    def test_template_passes_strict_check(self):
        doc = (ROOT / 'skills/story-long-write/references/artifact-protocols.md').read_text(encoding='utf-8')
        template = template_block(doc, '卷纲')  # 与任务包同一取法：按围栏标签取
        with tempfile.TemporaryDirectory(prefix='volume-template-') as tmp:
            volume = Path(tmp) / '大纲' / '卷纲_第一卷.md'
            volume.parent.mkdir()
            volume.write_text(template + '\n', encoding='utf-8')
            run = lambda *args: subprocess.run(
                [sys.executable, str(SCRIPTS / 'outline_view.py'), *args, str(volume)],
                capture_output=True, encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            check = run('--check', '--strict')
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertIn('问题 0 ／ 告警 0', check.stdout)
            unit = run('--unit', 'L1-01')
            self.assertEqual(unit.returncode, 0, unit.stderr)
            self.assertIn('### 第一段剧情：{一句话} <!-- L1-01 -->', unit.stdout)
            self.assertEqual(unit.stderr, '')


class ConvertOutlineFormatTests(unittest.TestCase):
    """convert_outline_format.py：老卷纲、细纲、排纲底稿换成 0.10 写法，只换格式不改内容；新旧两种都能过检查。"""

    OLD_VOLUME = (
        '# 第一卷 卷纲\n\n'
        '## 卷契约与终局储备\n> 作用域：卷级常任\n\n- 卷契约：读者等主角翻身\n- 契约风险：需补强——补一段交换\n\n'
        '## 全卷常任裁定\n> 作用域：卷级常任\n\n1. 信不拆\n\n'
        '## 剧情单元卡\n> 作用域：卷级常任\n\n'
        '### 剧情单元 L1-03：码头\n> 作用域：单元级 L1-03\n\n- 单元ID：L1-03\n- 章节范围：第21-27章\n'
        '- 单元情绪引擎：憋屈→翻身\n- 单元节拍/章功能分配：铺垫→兑现\n- 禁止提前释放：信的内容\n'
        '- 终局底牌边界：宿敌身份\n\n'
        '#### 供给自查\n> 作用域：批次底稿 L1-03｜状态：在用\n\n- 对手供给：无缺口\n\n'
        '## 压力线轮转\n> 作用域：卷级常任\n\n| 压力线 |\n|---|\n| 时限 |\n\n'
        '## 情绪弧线\n> 作用域：卷级常任\n\n| 章节 | 章节定位 | 情绪 |\n|---|---|---|\n| 第21章 | 高压 | 热血 |\n'
        '| 第22章 | 关系回收 | 温馨 |\n\n'
        '## 对标结构坐标\n> 作用域：卷级常任\n\n无对标，按八节点自排\n\n'
        '```md\n## 围栏里的示例\n> 作用域：单元级 L9-99\n```\n'
    )
    OLD_CHAPTER = (
        '## 细纲（第 21 章）\n\n### 第 21 章：码头\n- 核心事件：江晨接下托付\n- 字数目标：2300 字\n'
        '- 字数口径：visible_chars_v1\n- 单元ID/位置：L1-03；单元内第1拍\n- 目标情绪：期待→沉重\n'
        '- 主角目标/关键选择：要素材；先去听故事\n- 章首钩子：悬念前置 — 铁盒\n- 爽点：无显性爽点，功能是托付\n'
        '- 本章禁止提前释放：铁盒内容\n- 契约风险：契约安全\n- 章节定位：信息整理\n- 写手自由区：屋内陈设\n\n'
        '#### 内容概括（五段式）\n- 起因：a\n- 发展：b\n- 转折：c\n- 高潮：d\n- 结尾：e\n\n'
        '#### 情节安排（多线）\n- 主线推进：x\n\n#### 人物关系和出场顺序\n- 出场顺序：江晨\n\n#### 情节细化\n'
        '| # | 情节点（谁做了什么） | 功能标签 | 执行边界（禁＋放） |\n|---|---|---|---|\n'
        '| 1 | 老人推过铁盒 | 高潮 | 禁：不开盒。放：允许老人说他留了几十年 |\n'
        '- 复沓锚句：\n  - 点1：立此为凭\n'
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='convert-outline-')
        self.book = Path(self.tmp.name) / '书'
        (self.book / '大纲').mkdir(parents=True)
        self.volume = self.book / '大纲' / '卷纲_第1卷.md'
        self.chapter = self.book / '大纲' / '细纲_第021章.md'
        self.volume.write_text(self.OLD_VOLUME, encoding='utf-8')
        self.chapter.write_text(self.OLD_CHAPTER, encoding='utf-8')
        (self.book / '大纲' / '排纲底稿_L1-03.md').write_text(
            '# L1-03 排纲底稿\n\n## 供给自查\n- 场景与底图：码头\n\n## 建纲追加\n无追加\n', encoding='utf-8')
        # 卷纲里没有剧情段覆盖第 30 章：转换时编号留在行末注释里，不丢定位。
        self.orphan = self.book / '大纲' / '细纲_第030章.md'
        self.orphan.write_text(self.OLD_CHAPTER.replace('21', '30'), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True,
                              encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})

    def contract(self, *args):
        return subprocess.run(['node', str(SCRIPTS / 'check-outline-contract.js'), '--json', *map(str, args)],
                              capture_output=True, encoding='utf-8')

    def unit_view(self):
        result = self.run_py('outline_view.py', '--unit', 'L1-03', self.volume)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_old_and_converted_files_give_the_same_reads(self):
        # 转之前：老写法照样能取段、过细纲检查、过查缺检查。
        before = self.unit_view()
        self.assertIn('信不拆', before)
        self.assertEqual(self.contract(self.chapter).returncode, 0)
        self.assertEqual(self.contract('--supply', self.volume, 'L1-03').returncode, 0)
        dry = self.run_py('convert_outline_format.py', self.book, '--dry-run')
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn('会改 4 个文件', dry.stdout)
        self.assertEqual(self.volume.read_text(encoding='utf-8'), self.OLD_VOLUME)  # 试跑不写

        done = self.run_py('convert_outline_format.py', self.book)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('问题 0', done.stdout)
        self.assertIn('压力线轮转', done.stdout)  # 新模板不要的表只列出来，不删
        volume = self.volume.read_text(encoding='utf-8')
        self.assertNotIn('> 作用域：', volume.split('```')[0])
        self.assertIn('## 这卷读者等着看什么 <!-- 全卷 -->', volume)
        self.assertIn('### 第三段剧情：码头 <!-- L1-03 -->', volume)
        self.assertIn('#### 写纲前查缺 <!-- 批次底稿 L1-03｜状态：在用 -->', volume)
        self.assertIn('- 这段让读者图什么：憋屈→翻身', volume)
        self.assertIn('- 这段怎么排：铺垫→兑现', volume)
        self.assertIn('- 有没有硬伤：要补——补一段交换', volume)
        self.assertIn('- 这段先不能揭开、不能用上的：宿敌身份', volume)
        self.assertIn('| 第21章 | 爆发 | 热血 |', volume)
        self.assertIn('| 第22章 | 感情或关系戏 | 温馨 |', volume)
        self.assertIn('没有对标书，按常见的八步结构排', volume)
        self.assertNotIn('大牌', volume)
        self.assertIn('## 全卷规矩 <!-- 全卷 -->', volume)
        self.assertIn('| 时限 |', volume)
        self.assertNotIn('- 单元ID：', volume)
        self.assertIn('> 作用域：单元级 L9-99', volume)  # 围栏里的示例不动
        strict = self.run_py('outline_view.py', '--check', '--strict', self.volume)
        self.assertEqual(strict.returncode, 0, strict.stdout)
        after = self.unit_view()
        for kept in ('信不拆', '憋屈→翻身', '铺垫→兑现'):
            self.assertIn(kept, after)
        self.assertNotIn('对手供给', after)  # 批次底稿写正文不给，转前转后一样
        staged = self.run_py('outline_view.py', '--unit', 'L1-03', '--stage', 'outline', self.volume)
        self.assertIn('对手供给：无缺口', staged.stdout)

        chapter = self.chapter.read_text(encoding='utf-8')
        self.assertNotIn('字数口径', chapter)
        self.assertIn('- 属于哪段剧情：第三段剧情，单元内第1拍\n', chapter)
        self.assertIn('#### 这章怎么走\n', chapter)
        self.assertIn('- 松紧：过渡', chapter)
        self.assertIn('- 可以放开写的地方：屋内陈设', chapter)
        self.assertIn('- 属于哪段剧情：第三段剧情，单元内第1拍 <!-- L1-03 -->', self.orphan.read_text(encoding='utf-8'))
        self.assertIn('- 这章不能说破：铁盒内容', chapter)
        self.assertIn('- 有没有硬伤：没问题', chapter)
        self.assertIn('| # | 情节点（谁做了什么） | 作用 | 分寸 |', chapter)
        self.assertIn('禁：不开盒。放：允许老人说他留了几十年', chapter)  # 内容不改
        self.assertIn('- 原样出现的原话：', chapter)
        report = self.contract(self.chapter)
        self.assertEqual(report.returncode, 0, report.stdout)
        sys.path.insert(0, str(SCRIPTS))
        try:
            from outline_view import chapter_unit, chapter_unit_in_volume
        finally:
            sys.path.pop(0)
        self.assertIsNone(chapter_unit(chapter))  # 新细纲不写编号，按章号定位
        self.assertEqual(chapter_unit_in_volume(volume, 21), 'L1-03')
        self.assertIsNone(chapter_unit_in_volume(volume, 30))
        self.assertEqual(chapter_unit(self.OLD_CHAPTER), 'L1-03')

        notes = self.book / '.story' / '排纲笔记' / 'L1-03.md'
        self.assertFalse((self.book / '大纲' / '排纲底稿_L1-03.md').exists())
        self.assertFalse((self.book / '大纲' / '排纲笔记_L1-03.md').exists())
        self.assertIn('## 写纲前查缺', notes.read_text(encoding='utf-8'))
        self.assertIn('## 写纲时补的', notes.read_text(encoding='utf-8'))
        self.assertIn('- 场景与布局：码头', notes.read_text(encoding='utf-8'))
        supply = self.contract('--supply', self.volume, 'L1-03')
        self.assertEqual(supply.returncode, 0, supply.stdout)
        self.assertEqual(Path(json.loads(supply.stdout)['file']).resolve(), notes.resolve())

        again = self.run_py('convert_outline_format.py', self.book)
        self.assertIn('改了 0 个文件', again.stdout)  # 再跑不再改


if __name__ == '__main__':
    unittest.main()
