#!/usr/bin/env python3
"""公开 CLI 回归：取段闭包、存量卷纲、组装与召回降档。"""
import json
import os
from pathlib import Path
import shutil
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
        self.assertIn('author_preferences（作者记忆', result.stdout)
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
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：蒸汽朋克考古\n')
        self.assertIn('题材卡无匹配', self.build().stdout)

    def test_bare_out_archives_into_book_work_dir(self):
        result = self.call('build_writer_prompt.py', '--project', self.book, '--chapter', 1, '--out')
        self.assertEqual(result.returncode, 0, result.stderr)
        work = (self.book / '.story/work/第001章').resolve()
        archived = work / 'writer_prompt.md'
        self.assertTrue(archived.is_file())
        self.assertIn(f'留档：{archived}', result.stdout)
        prompt = archived.read_text(encoding='utf-8')
        # Segment paths are concrete, book-local and never under 正文/ or /tmp.
        self.assertIn(str(work / '前组.md'), prompt)
        self.assertIn(str(work / '后组.md'), prompt)
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


    def test_architect_brief_carries_only_the_moment_files(self):
        # 开书按作者确认点分时刻：卷纲任务包只带卷纲时刻的流程、模板与技法，细纲任务包只带细纲时刻的；
        # 主会话不读包，story-architect 在新上下文里只读包和项目文件。
        refs = SCRIPTS.parent / 'references'
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
        self.assertTrue(any('单元 L1-01' in name for name in first['includes']))
        self.assertTrue(any('单元 L1-02' in name for name in later['includes']))
        self.assertFalse(any('单元 L1-01' in name for name in later['includes']))
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
        self.assertIn('找不到覆盖第30-31章的剧情单元', uncovered.stderr)
        # 单元只覆盖请求的一部分：不能静默只给一半，点名缺的章。
        partial = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '10-14')
        self.assertEqual(partial.returncode, 2, partial.stdout)
        self.assertIn('剧情单元只覆盖了一部分，缺覆盖第13-14章', partial.stderr)
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
        self.assertIn('第1节：主角卡', outline_text)
        self.assertNotIn('第3节：反派设计', outline_text)
        world = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'world').stdout)
        world_text = Path(world['brief']).read_text(encoding='utf-8')
        self.assertIn('## 作者已定', world_text)  # 设定模板随包，定方向落盘的作者决定有处可读
        self.assertIn('核心梗三层递进设计', world_text)
        self.assertIn('## 金手指', world_text)
        self.assertIn(f"{refs / 'character-relations.md'}` 「感情线阶段」一节", world_text)
        self.assertNotIn('## 微创新与差异化设计', world_text)
        self.assertNotIn('## 感情流人设核心法', world_text)
        self.assertNotIn('全书体量与阶段总览', world_text)
        self.assertNotIn('主会话自己定设定时读', world_text)  # 主会话的读取清单不进包
        self.assertIn(f"{refs / 'female-audience-writing.md'}` 整份", world_text)
        self.assertIn('按下附「新增物三级」属先问作者', world_text)
        too_many = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-11')
        self.assertEqual(too_many.returncode, 2)
        self.assertIn('一批细纲最多 10 章', too_many.stderr)


    def test_architect_brief_names_unit_cards_missing_scope_lines(self):
        # 单元卡少了「> 作用域：」行时取段器认不出它，报错要点名这张卡，而不是笼统说「要写章节范围」。
        self.volume.write_text('# 第一卷\n### 剧情单元 L1-01\n- 章节范围：第1-3章\n', encoding='utf-8')
        result = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-3')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('缺「> 作用域：单元级 {单元ID}」声明行：卷纲_第一卷.md「剧情单元 L1-01」', result.stderr)
        self.assertIn('--check --strict', result.stderr)


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

    def test_incomplete_summaries_budget_complementary_prose(self):
        for chapter in range(1, 26):
            self.put(f'正文/第{chapter:03d}章_雨夜.md', f'# 第{chapter}章\n' + '正文证据。' * 1000)
        original = {p.name: p.read_bytes() for p in (self.book / '正文').iterdir()}
        for summary in ('', '# 只有标题\n', self.SUMMARY.format(n=1).split('**情节点**')[0],
                        self.SUMMARY.format(n=1).replace('**因果**：雨夜来信', '**因果**：[待补充]')):
            with self.subTest(summary=summary[:40]):
                for chapter in range(1, 26):
                    self.summary(chapter, summary)
                info, text = self.brief('1-20')
                end = int(info['chapters'].split('-')[1])
                self.assertLess(end, 20)
                self.assertEqual(info['next'], end + 1)
                self.assertLessEqual(info['chars'], info['limit'])
                extra = sum(len(''.join((self.book / f'正文/第{chapter:03d}章_雨夜.md')
                                       .read_text(encoding='utf-8').split())) for chapter in range(1, end + 1))
                self.assertEqual(info['chars'], len(''.join(text.split())) + extra)
                self.assertEqual(info['missing_summaries'], [], "existing summaries remain distinct from missing files")
                self.assertEqual(original, {p.name: p.read_bytes() for p in (self.book / '正文').iterdir()})

    def test_unit_cards_selected_by_chapter_range_field(self):
        self.volume(('L1-01', '第1-5章', '接信'), ('L1-02', '第6-9章', '反击'), ('L1-03', '第10-12章', '余波'),
                    ('L1-04', '第15-15章', '单元编号不当章号'), ('L1-05', '第13-25章', '远处'))
        _, text = self.brief('1-12')
        for card in ('### 剧情单元 L1-01', '### 剧情单元 L1-02', '### 剧情单元 L1-03'):
            self.assertIn(card, text)
        self.assertNotIn('L1-04', text)  # 只认「章节范围」字段，其他字段里的「第1-2章」不算
        self.assertNotIn('L1-05', text)

    def test_unit_card_coverage_must_be_complete_and_unique(self):
        for cards, missing, duplicate in (
            ((('L1-01', '第1-10章', '接信'), ('L1-02', '第13-25章', '后续')), '11,12', '无'),
            ((('L1-01', '第1-12章', '接信'), ('L1-02', '第10-25章', '后续')), '无', '10,11,12'),
        ):
            with self.subTest(cards=cards):
                self.volume(*cards)
                result = self.call('1-12')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(f'缺覆盖：{missing}', result.stderr)
                self.assertIn(f'重复覆盖：{duplicate}', result.stderr)
                self.assertFalse((self.book / '.story/work/排纲').exists())

    def test_cards_the_writer_cannot_read_stop_the_brief(self):
        # 写正文时 outline_view.py --unit 认不出的卷纲（缺作用域行、旧的表格形单元），任务包也不收。
        self.put('大纲/卷纲_第1卷.md', '# 第一卷\n\n### 剧情单元 L1-01\n- 章节范围：第1-12章\n')
        missing_scope = self.call('1-12')
        self.assertEqual(missing_scope.returncode, 2)
        self.assertIn('作用域：单元级', missing_scope.stderr)
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
        self.assertIn('单元情绪引擎', unit.stdout)
        _, text = self.brief('1-12')
        self.assertIn('### 剧情单元 L1-01', text)
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


class VolumeTemplateContractTests(unittest.TestCase):
    """artifact-protocols.md 的卷纲模板原样落盘，必须过取段器的严格校验。"""

    def test_template_passes_strict_check(self):
        doc = (ROOT / 'skills/story-long-write/references/artifact-protocols.md').read_text(encoding='utf-8')
        after = doc.split('\n## 大纲/卷纲_第X卷.md\n', 1)[1]
        template = after.split('```markdown\n', 1)[1].split('\n```\n', 1)[0]
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
            self.assertIn('### 剧情单元 L1-01', unit.stdout)
            self.assertEqual(unit.stderr, '')


if __name__ == '__main__':
    unittest.main()
