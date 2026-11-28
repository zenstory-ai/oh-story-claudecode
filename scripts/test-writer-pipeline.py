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
NODE = shutil.which('node') or 'node'


def template_block(text, tag):
    completed = subprocess.run(
        [NODE, '-e',
         'const fs=require("fs");const m=require(process.argv[1]);'
         'process.stdout.write(m.templateBlock(fs.readFileSync(0,"utf8"),process.argv[2]));',
         str(SCRIPTS / 'build_architect_brief.js'), tag],
        input=text, text=True, encoding='utf-8', capture_output=True, check=True,
    )
    return completed.stdout


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
        script_js = script[:-3] + '.js' if script.endswith('.py') else script
        return subprocess.run([NODE, str(SCRIPTS / script_js), *map(str, args)],
                              cwd=self.tmp.name, capture_output=True, encoding='utf-8',
                              env={**os.environ, **(env or {})})

    def view(self, *args):
        return self.call('outline_view.js', *args, self.volume)

    def build(self):
        return self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 1)

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
                result = self.view('--unit', unit)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('卷首约束', result.stdout)
                self.assertIn('本卷不揭示', result.stdout)
                self.assertNotIn('不能串卡', result.stdout)
                self.assertEqual(self.view('--check', '--strict').returncode, 0)

    def test_default_view_is_the_writing_closure(self):
        result = self.view('--unit', 'L1-01')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('本卷不揭示', result.stdout)
        self.assertNotIn('不能串卡', result.stdout)

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
        text = self.volume_text() + '\n#### 老裁定\n> 作用域：单元级 L1-01｜状态：已退役\n旧口径\n'
        text += '\n## 常任补充\n> 作用域：卷级常任\n- ⊘ 旧行\n'
        self.volume.write_text(text, encoding='utf-8')
        current = self.view('--unit', 'L1-01').stdout
        for old in ['旧口径', '旧行']:
            self.assertNotIn(old, current)
        history = self.view('--unit', 'L1-01', '--history').stdout
        for old in ['旧口径', '旧行']:
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
        # 新书没有旧版题材正文提示卡时：脚本按「题材类型」匹配 references/genre-styles/ 流派包，
        # 召回降档按流派包命中判定（不再要求 设定/题材正文提示卡.md），也不再输出冗余手动提示卡槽位。
        (self.book / '设定/题材正文提示卡.md').unlink()
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市日常 · 豪门总裁\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        cards = SCRIPTS.parent / 'references' / 'genre-styles'
        prompt_body, report_body = result.stdout.split('以下不进 prompt', 1)
        # prompt 正文给写手用已部署 agent-references/genre-styles/ 路径，不得泄漏跨 skill 源码路径；
        # 核对报告保留已解析源路径供主会话诊断。
        self.assertIn('主流派包：agent-references/genre-styles/都市日常神豪.md（置信度 high）', prompt_body)
        self.assertIn('辅流派包：agent-references/genre-styles/豪门虐恋追妻.md（置信度 high）', prompt_body)
        self.assertNotIn('story-long-write/references/genre-styles', prompt_body)
        self.assertIn(f"主题材 {cards / '都市日常神豪.md'}（置信度 high）；辅题材 {cards / '豪门虐恋追妻.md'}", report_body)
        self.assertIn('召回降档：成立', result.stdout)
        self.assertNotIn('题材正文提示卡（genre_prose_card', result.stdout)
        self.assertIn('——— 语感锚点切片', result.stdout)
        # 最长匹配优先与 20 流派精确路由：
        # 「玄幻言情」「仙侠言情」独立进 幻想言情仙侠.md，不再落进古言或被短别名「玄幻/仙侠」抢走；
        # 「都市种田」「西方奇幻 / 领主种田」「男频乡村 / 赶山打猎」不被女频 年代种田经商.md 抢走；
        # 「古代情缘 / 先婚后爱」「民国旧影 / 督军府宅斗」稳落 古言宅斗重生.md，不串入现代豪门或男频谍战。
        for line, main, loser in [('玄幻言情', '幻想言情仙侠.md', '传统玄幻仙侠.md'),
                                  ('玄幻言情', '幻想言情仙侠.md', '古言宅斗重生.md'),
                                  ('仙侠言情', '幻想言情仙侠.md', '传统玄幻仙侠.md'),
                                  ('都市种田', '男频年代乡村.md', '年代种田经商.md'),
                                  ('西方奇幻 / 领主种田', '西幻游戏同人.md', '年代种田经商.md'),
                                  ('古代情缘 / 先婚后爱', '古言宅斗重生.md', '豪门虐恋追妻.md'),
                                  ('都市高手 / 强者回归', '都市日常神豪.md', '都市高武异能.md'),
                                  ('男频乡村 / 赶山打猎', '男频年代乡村.md', '年代种田经商.md'),
                                  ('民国旧影 / 督军府宅斗', '古言宅斗重生.md', '历史架空权谋.md'),
                                  ('传统玄幻 · 玄幻言情', '传统玄幻仙侠.md', None)]:
            with self.subTest(genre=line, loser=loser):
                self.put('设定/题材定位.md', f'# 题材定位\n- 题材类型：{line}\n')
                out = self.build().stdout
                self.assertIn(f"主题材 {cards / main}", out)
                if loser:
                    self.assertNotIn(str(cards / loser), out)
                else:
                    self.assertIn(f"辅题材 {cards / '幻想言情仙侠.md'}", out)
        # 高频细分别名与 4 个新增流派包可精确命中。
        for alias, expected in [('异能', '都市高武异能.md'), ('虐恋', '豪门虐恋追妻.md'),
                                ('商战', '官场商战职场.md'), ('官场', '官场商战职场.md'),
                                ('种田经商', '年代种田经商.md'), ('赶海', '男频年代乡村.md'),
                                ('动漫衍生', '动漫男频衍生.md'), ('玄学直播', '幻想言情仙侠.md'),
                                ('校园', '青春甜宠文娱.md'), ('轻小说', '西幻游戏同人.md')]:
            with self.subTest(alias=alias):
                self.put('设定/题材定位.md', f'# 题材定位\n- 题材类型：{alias}\n')
                self.assertIn(f"主题材 {cards / expected}", self.build().stdout)
        # 匹配不到时给通用长篇兜底包，和命中走同一条路（同一行点名包的路径）。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：蒸汽朋克考古\n')
        out = self.build().stdout
        self.assertIn('流派无匹配', out)
        self.assertIn(f"主题材 {cards / '通用长篇.md'}（置信度 low）", out)
        # 兜底包（fallback: true）绝不参与按名匹配：含「跨题材融合」+具体题材时只命中真实题材包。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：跨题材融合 / 悬疑\n')
        hybrid_fb = self.build().stdout
        self.assertIn(f"主题材 {cards / '悬疑灵异.md'}", hybrid_fb)
        self.assertNotIn('通用长篇.md', hybrid_fb)
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市日常\n')
        self.assertNotIn('通用长篇.md', self.build().stdout)

    def test_prose_anchor_injected_even_under_recall_downgrade(self):
        # 召回降档成立时，仍必须注入语感锚点切片（优先主对标文风原文锚点，否则流派包内置切片）。
        self.set_inputs_for_downgrade(self.volume.read_text(encoding='utf-8'))
        (self.book / '设定/题材正文提示卡.md').unlink()
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市脑洞\n- 主对标书：无\n')
        downgraded = self.build()
        self.assertEqual(downgraded.returncode, 0, downgraded.stderr)
        self.assertIn('召回降档：成立', downgraded.stdout)
        self.assertIn('——— 语感锚点切片', downgraded.stdout)
        self.assertIn('流派包「都市脑洞系统」内置原文切片', downgraded.stdout)
        # 有主对标文风原文锚点时优先注入对标切片，且不把围栏前的 **出处**/**示范点** 元数据混入切片。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市脑洞\n- 主对标书：《测试热书》、《副对标》\n')
        self.put(
            '对标/测试热书/文风.md',
            '# 文风\n## 原文锚点片段\n### 片段 A — 基调：开篇钩子\n'
            '**出处**：第 1 章 第 1 段（行 1-10）\n'
            '**示范点**：竖屏短段开篇\n'
            '```text\n“把合同撕了。”\n他把黑卡甩在桌上。\n```\n',
        )
        with_bench = self.build()
        self.assertEqual(with_bench.returncode, 0, with_bench.stderr)
        self.assertIn('召回降档：成立', with_bench.stdout)
        self.assertIn('主对标「测试热书」文风原文锚点', with_bench.stdout)
        self.assertIn('把合同撕了', with_bench.stdout)
        self.assertNotIn('**出处**', with_bench.stdout)
        self.assertNotIn('**示范点**', with_bench.stdout)

    def test_workspace_library_benchmark_found_under_long_dir_and_unclosed_comment_safe(self):
        # 标准 长篇/{书名} 布局下，主对标在 {workspace}/拆文库/{对标书名}/文风.md 时应命中对标原文锚点；
        # 题材定位.md 出现未闭合 HTML 注释时不得截断至 EOF 导致后续对标登记失效。
        book = self.move_book('工作区甲', '长篇', '雾港 来信')
        workspace = book.parent.parent
        bench_style = workspace / '拆文库' / '工作区对标书' / '文风.md'
        bench_style.parent.mkdir(parents=True, exist_ok=True)
        bench_style.write_text(
            '# 文风\n## 原文锚点片段\n### 片段 1：开篇\n'
            '```text\n“退婚书签了吧。”\n林默把玉佩拍在案上。\n```\n',
            encoding='utf-8',
        )
        self.put(
            '设定/题材定位.md',
            '# 题材定位\n<!-- 未闭合草稿备注\n- 题材类型：都市脑洞\n- 主对标书：《工作区对标书》、《第二本》\n',
        )
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn('主对标「工作区对标书」文风原文锚点', res.stdout)
        self.assertIn('退婚书签了吧', res.stdout)

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
        for broken in ['placeholder-emotion', 'missing-unit', 'missing-engine', 'missing-tempo']:
            with self.subTest(broken=broken):
                self.set_inputs_for_downgrade(original)
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
        self.assertIn('剧情段 L1-01', result.stdout)
        # 新细纲只写段名、不写编号：按章号落在卷纲哪段剧情的章节范围里定位。
        self.outline.write_text('### 第 1 章：一封信\n- 属于哪段剧情：第一段剧情：接信，第一步：接下托付\n'
                                '- 目标情绪：犹疑→决定替朋友保管信件\n- 主角目标/关键选择：决定替朋友保管信件\n',
                                encoding='utf-8')
        self.assertIn('剧情段 L1-01', self.build().stdout)

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
        # 开书按作者确认点分时刻：卷纲任务包只带卷纲时刻的流程、模板与流派包，细纲任务包只带细纲时刻的；
        # 主会话不读包，story-architect 在新上下文里只读包和项目文件。
        vol = self.call('build_architect_brief.py', '--project', self.book, '--task', 'volume', '--volume', 1)
        self.assertEqual(vol.returncode, 0, vol.stderr)
        info = json.loads(vol.stdout)
        text = Path(info['brief']).read_text(encoding='utf-8')
        self.assertEqual(Path(info['brief']).parent, self.book / '.story' / 'work' / '排纲')
        self.assertEqual(info['includes'], ['flow-opening-plan.md（排纲方法）', 'flow-opening-plan.md（大纲与卷纲模板）',
                                            'SKILL.md（新增物三级）', '按条件可读（包外）'])
        # 包外读不到 SKILL.md：新增物三级判据随包；条件参考指向 agent-references/benchmark-recall.md。
        bundle = SCRIPTS.parents[1] / 'story-setup' / 'references' / 'agent-references'
        self.assertIn('**先问作者**：新主线事件或反转', text)
        self.assertIn('agent-references/benchmark-recall.md` 整份', text)
        # 卷纲任务包带排纲方法（含四个排纲问题）与大纲/卷纲模板，主会话调度与细纲模板不进包。
        self.assertIn('## 排纲方法（卷纲）', text)
        self.assertIn('四个排纲问题', text)
        self.assertIn('排纲刻度与松紧', text)
        self.assertIn('并补齐 `设定/题材定位.md`「题材框架」的「关键转折节点」', text)
        self.assertNotIn('<!-- author-report -->', text)
        self.assertNotIn('## 主会话：立项与调度', text)
        self.assertNotIn('## 细纲（第 N 章）', text)
        self.assertLess(info['chars'], 30000)
        # 设定/题材定位.md 写了题材类型时，自动附带命中的 1 份 genre-styles 流派包。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市脑洞\n')
        vol_with_pack = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'volume', '--volume', 1).stdout)
        self.assertTrue(any(name.startswith('genre-styles/都市脑洞系统.md') for name in vol_with_pack['includes']), vol_with_pack['includes'])
        # story-architect 不能执行命令：覆盖本批章节的单元闭包由脚本取好放进包里。
        self.volume.write_text(self.volume_text() + '### 剧情单元 L1-02\n> 作用域：单元级 L1-02\n'
                               '- 章节范围：第4-12章\n- 单元情绪引擎：保管→被追查→反将一军\n', encoding='utf-8')
        first = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline',
                                     '--chapters', '1-3').stdout)
        later = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline',
                                     '--chapters', '4-10').stdout)
        self.assertIn('flow-outline.md（排纲方法·含黄金三章）', first['includes'])
        self.assertIn('flow-outline.md（排纲方法）', later['includes'])
        self.assertNotIn('flow-outline.md（排纲方法·含黄金三章）', later['includes'])
        self.assertTrue(any(name.startswith('genre-styles/都市脑洞系统.md') for name in first['includes']), first['includes'])
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
        self.assertIn('### 黄金三章规划', outline_text)
        self.assertIn('### 高频章首 / 章尾硬钩子', outline_text)
        self.assertNotIn('留白钩子', outline_text)
        self.assertNotIn('<!-- author-report -->', outline_text)
        later_text = Path(later['brief']).read_text(encoding='utf-8')
        self.assertIn('### 爽点倒推与高潮构建', later_text)
        self.assertNotIn('### 黄金三章规划', later_text)
        # 角色卡按围栏标签只取模板本身。
        self.assertIn('### 设定/角色/{名}.md（主角）', outline_text)
        self.assertIn('角色定位：', outline_text)
        self.assertIn('flow-outline.md（细纲与排纲笔记模板）', first['includes'])
        self.assertIn('排纲笔记', outline_text)
        world = json.loads(self.call('build_architect_brief.py', '--project', self.book, '--task', 'world').stdout)
        world_text = Path(world['brief']).read_text(encoding='utf-8')
        self.assertIn('## 作者已定', world_text)
        self.assertIn('核心梗三层与金手指', world_text)
        self.assertNotIn('## 主会话：立项与调度', world_text)
        self.assertIn('按下附「新增物三级」属问作者', world_text)
        # 定设定多一份全书梗概：任务包点名要写它，模板随包，结局一节写明可空。
        self.assertIn('`设定/全书梗概.md`', world_text)
        self.assertIn('## 结局（目前的设想，可空）', world_text)
        self.assertIn('「题材框架」留到出卷纲补', world_text)
        self.assertIn('## 核心设定\n', world_text)
        self.assertIn('## 题材框架\n', world_text)
        for brief_text in (text, outline_text, world_text):
            refs = re.findall(r'`agent-references/([\w-]+\.md)`', brief_text)
            self.assertTrue(refs)
            for name in refs:
                self.assertTrue((bundle / name).is_file(), name)
        # 细纲模板是新写法：「这章怎么走」、默认三列情节点表，「这章不能说破」挪进可选块，不再写字数口径。
        self.assertIn('#### 这章怎么走', outline_text)
        self.assertIn('| # | 情节点（谁做了什么） | 作用 |\n', outline_text)
        self.assertIn('- 这章不能说破：', outline_text)
        self.assertNotIn('- 字数口径：', outline_text)
        self.assertNotIn('<!-- {单元编号', outline_text)
        # 前 3 章细纲要排正面交锋、立起切身赌注。
        self.assertIn('正面交锋', outline_text)
        self.assertIn('切身赌注', outline_text)
        too_many = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-11')
        self.assertEqual(too_many.returncode, 2)
        self.assertIn('一批细纲最多 10 章', too_many.stderr)

    def test_genre_card_routing_channel_priority(self):
        # Round 5: 女频「玄幻仙侠/幻想言情」不被男频「传统玄幻仙侠」按字符位置抢主卡；「双男主」优先于泛言情标签。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：玄幻仙侠 / 幻想言情\n- 目标读者：女频（言情仙侠读者）\n')
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        prompt = res.stdout.split('以下不进 prompt', 1)[0]
        self.assertIn('主流派包：agent-references/genre-styles/幻想言情仙侠.md', prompt)

        arch = self.call('build_architect_brief.py', '--project', self.book, '--task', 'world')
        self.assertEqual(arch.returncode, 0, arch.stderr)
        arch_text = Path(json.loads(arch.stdout)['brief']).read_text(encoding='utf-8')
        self.assertIn('幻想言情仙侠', arch_text)

        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：白月光 · 豪门 · 双男主\n- 目标读者：女频（纯爱读者）\n')
        res_bl = self.build()
        self.assertEqual(res_bl.returncode, 0, res_bl.stderr)
        prompt_bl = res_bl.stdout.split('以下不进 prompt', 1)[0]
        self.assertIn('主流派包：agent-references/genre-styles/双男主.md', prompt_bl)

        # Round 16: 女频年代军婚 & 女频末世天灾囤货 精准优先，不被男频末世/古代种田/男频乡村抢主卡。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：七零年代 / 随军军婚\n- 目标读者：女频（年代甜宠读者）\n')
        res_mil = self.build()
        self.assertEqual(res_mil.returncode, 0, res_mil.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/女频年代军婚.md', res_mil.stdout.split('以下不进 prompt', 1)[0])

        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：末世 / 天灾囤货空间\n- 目标读者：女频（天灾囤货读者）\n')
        res_apo = self.build()
        self.assertEqual(res_apo.returncode, 0, res_apo.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/女频末世天灾囤货.md', res_apo.stdout.split('以下不进 prompt', 1)[0])


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

    def test_unpadded_own_chapter_does_not_clash_and_general_volume_filename_is_read(self):
        # 已有未补零的本章正文（第1章_一封信.md）不应触发与自己重名的假告警；其他章同名仍要报。
        self.put('正文/第1章_一封信.md', '# 第1章 一封信\n旧稿。\n')
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn('标题预检：《一封信》无重名', res.stdout)
        self.put('正文/第2章_一封信.md', '# 第2章 一封信\n别章。\n')
        res2 = self.build()
        self.assertEqual(res2.returncode, 0, res2.stderr)
        self.assertIn('标题预检：《一封信》与既有章重名 → 第2章_一封信.md', res2.stdout)

        # build_architect_brief.js 与 build_writer_prompt.js 统一匹配 /^卷纲_.*\.md$/（如 卷纲_序章.md）。
        self.volume.unlink()
        self.put('大纲/卷纲_序章.md', self.volume_text())
        brief = self.call('build_architect_brief.py', '--project', self.book, '--task', 'outline', '--chapters', '1-3')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        info = json.loads(brief.stdout)
        self.assertTrue(any('剧情段 L1-01' in name for name in info['includes']), info['includes'])

    def test_fenced_headings_in_slices_and_html_comments_in_positioning(self):
        # 1) extractProseSlices 遇到围栏代码块内部的 `# ` 标题不应提前截断切片提取。
        self.put('对标/热书甲/文风.md',
                 '# 文风\n\n### 切片 1\n```text\n第一段开场。\n# 代码块里的伪标题\n继续往下写的正文切片。\n```\n')
        # 2) 题材定位.md 中的注释不应污染 ownNames、genreLine 或 build_architect_brief 的 matchPrimaryGenreStyle。
        self.put('设定/题材定位.md',
                 '# 题材定位\n'
                 '<!--\n- 书名：热书甲\n- 题材类型：豪门虐恋\n-->\n'
                 '- 书名：真书名\n'
                 '- 题材类型：悬疑灵异\n'
                 '- 主对标书：热书甲\n')
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        prompt = res.stdout
        self.assertIn('继续往下写的正文切片。', prompt)
        self.assertIn('悬疑灵异.md', prompt)
        self.assertNotIn('豪门虐恋追妻.md', prompt)
        brief = self.call('build_architect_brief.py', '--project', self.book, '--task', 'world')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        brief_text = Path(json.loads(brief.stdout)['brief']).read_text(encoding='utf-8')
        self.assertIn('悬疑灵异', brief_text)
        self.assertNotIn('豪门虐恋追妻', brief_text)

    def test_genre_slice_rotation_cycles_across_chapters(self):
        # 3 个及以上语感切片按章号循环轮换（Ch1: A+B → Ch2: B+C → Ch3: C+A → Ch4: A+B），
        # 1–2 个切片保持原样全选不重复。
        self.put('设定/题材定位.md', '# 题材定位\n- 题材类型：都市脑洞\n- 主对标书：轮换测试书\n')
        self.put(
            '对标/轮换测试书/文风.md',
            '# 文风\n'
            '### 切片 A\n```text\n第一段切片甲内容。\n```\n'
            '### 切片 B\n```text\n第二段切片乙内容。\n```\n'
            '### 切片 C\n```text\n第三段切片丙内容。\n```\n',
        )
        for ch in range(1, 5):
            self.put(f'大纲/细纲_第{ch:03d}章.md', f'### 第 {ch} 章：测试章{ch}\n- 单元ID/位置：L1-01\n- 目标情绪：推进\n')
            if ch > 1:
                self.put(f'正文/第{ch - 1:03d}章_测试章{ch - 1}.md', f'# 第{ch - 1}章 测试章{ch - 1}\n上章收尾。\n')

        expected = {
            1: (['切片 A', '切片 B'], ['切片 C']),
            2: (['切片 B', '切片 C'], ['切片 A']),
            3: (['切片 C', '切片 A'], ['切片 B']),
            4: (['切片 A', '切片 B'], ['切片 C']),
        }
        for ch, (present, absent) in expected.items():
            with self.subTest(chapter=ch):
                res = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', ch)
                self.assertEqual(res.returncode, 0, res.stderr)
                prompt_body = res.stdout.split('以下不进 prompt', 1)[0]
                for item in present:
                    self.assertIn(f'【{item}】', prompt_body)
                for item in absent:
                    self.assertNotIn(f'【{item}】', prompt_body)

        # 只有 2 个切片时，任何章号都保留全部 2 个切片且不重复。
        self.put(
            '对标/轮换测试书/文风.md',
            '# 文风\n### 切片 A\n```text\n切片甲。\n```\n### 切片 B\n```text\n切片乙。\n```\n',
        )
        res2 = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 3)
        self.assertEqual(res2.returncode, 0, res2.stderr)
        prompt2 = res2.stdout.split('以下不进 prompt', 1)[0]
        self.assertEqual(prompt2.count('【切片 A】'), 1)
        self.assertEqual(prompt2.count('【切片 B】'), 1)

    def test_comma_benchmark_title_injects_style_slices_under_downgrade_and_espionage_routes_to_general(self):
        # BUG-01: 含逗号的对标书名在召回降档下不能被截断，必须精准命中 对标/{全书名}/文风.md 注入切片。
        full_title = '全球僵尸降临，你说道士序列没用'
        self.put(
            '设定/题材定位.md',
            f'- 题材类型：都市高武异能\n## 对标登记\n- 主对标书：{full_title}\n'
            f'| 书名 | 题材类型 | 引用强度 | 用途 |\n|---|---|---|---|\n'
            f'| {full_title} | 都市高武异能 | 主 | 文风主对标 |\n',
        )
        self.put('设定/文风.md', '# 本书文风\n竖屏短段，口语直给。\n')
        self.put(
            f'对标/{full_title}/文风.md',
            '# 对标文风\n'
            '### 片段 A — 开篇\n```text\n铜铃一响，整条长街的僵尸齐刷刷跪了一地。\n```\n'
            '### 片段 B — 打脸\n```text\n测力柱嗡的一声裂开三道缝，台下鸦雀无声。\n```\n',
        )
        self.put('大纲/细纲_第001章.md', '### 第 1 章：破局\n- 单元ID/位置：L1-01\n- 目标情绪：憋屈→爽\n')
        res = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 1)
        self.assertEqual(res.returncode, 0, res.stderr)
        prompt_body, report_body = res.stdout.split('以下不进 prompt', 1)
        self.assertIn('铜铃一响，整条长街的僵尸齐刷刷跪了一地。', prompt_body)
        self.assertIn('测力柱嗡的一声裂开三道缝，台下鸦雀无声。', prompt_body)
        self.assertIn(f'对标/{full_title}/文风.md', report_body)
        self.assertIn('召回降档', report_body)

        # 2026-11-26: 历史架空权谋.md 已纳入男频抗战/民国谍战专线，不再落入通用长篇；女频民国旧影另走古言宅斗重生。
        self.put('设定/题材定位.md', '- 题材类型：民国谍战\n## 对标登记\n- 主对标书：无\n')
        res_spy = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 1)
        self.assertEqual(res_spy.returncode, 0, res_spy.stderr)
        self.assertIn('历史架空权谋.md', res_spy.stdout)
        self.assertNotIn('通用长篇.md', res_spy.stdout)

        # 本书 设定/文风.md 含原文锚点切片时，优先级必须高于外部主对标与流派包内置切片。
        self.put(
            '设定/文风.md',
            '# 本书文风\n## 原文锚点片段\n### 片段 1：冷峭电报\n```text\n发报键敲下第三声短促滴答，暗门外的皮鞋声停住了。\n```\n',
        )
        self.put(
            '设定/题材定位.md',
            f'- 题材类型：民国谍战\n## 对标登记\n- 主对标书：{full_title}\n',
        )
        res_own = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 1)
        self.assertEqual(res_own.returncode, 0, res_own.stderr)
        self.assertIn('发报键敲下第三声短促滴答', res_own.stdout)
        self.assertIn('本书文风', res_own.stdout)
        self.assertNotIn('铜铃一响，整条长街的僵尸齐刷刷跪了一地。', res_own.stdout)

    def test_secondary_benchmark_style_never_leaks_when_primary_lacks_style_file(self):
        # NEW-BUG-02: 主对标缺 文风.md 时，绝不滑落加载副/参考对标的 文风.md 并错标成主对标。
        self.put('对标/主标神瞳/剧情/节奏.md', '# 主标节奏\n')
        self.put(
            '对标/副标权谋/文风.md',
            '# 副标文风\n### 切片 1\n```text\n副标专属泄漏文本绝不能进主对标。\n```\n',
        )
        self.put('大纲/细纲_第001章.md', '### 第 1 章：破局\n- 单元ID/位置：L1-01\n- 目标情绪：憋屈→爽\n')

        # 情形 A：显式写了「主对标书：主标神瞳」+ 对标登记表含副标权谋（辅）
        self.put(
            '设定/题材定位.md',
            '- 题材类型：都市脑洞\n'
            '## 对标登记\n'
            '- 主对标书：主标神瞳\n'
            '| 书名 | 题材类型 | 引用强度 | 用途 |\n'
            '|---|---|---|---|\n'
            '| 主标神瞳 | 都市脑洞 | 主 | 主对标 |\n'
            '| 副标权谋 | 历史架空 | 辅 | 只看权谋结构 |\n',
        )
        res_a = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 1)
        self.assertEqual(res_a.returncode, 0, res_a.stderr)
        self.assertNotIn('副标专属泄漏文本绝不能进主对标', res_a.stdout)
        self.assertNotIn('对标/副标权谋/文风.md', res_a.stdout)

        # 情形 B：未写「主对标书：」行，仅靠「对标登记」表的「引用强度」列区分主/辅/参考
        self.put(
            '设定/题材定位.md',
            '- 题材类型：都市脑洞\n'
            '## 对标登记\n'
            '| 书名 | 题材类型 | 引用强度 | 用途 |\n'
            '|---|---|---|---|\n'
            '| 主标神瞳 | 都市脑洞 | 主 | 主对标 |\n'
            '| 副标权谋 | 历史架空 | 参考 | 仅参考配角 |\n',
        )
        res_b = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 1)
        self.assertEqual(res_b.returncode, 0, res_b.stderr)
        self.assertNotIn('副标专属泄漏文本绝不能进主对标', res_b.stdout)
        self.assertNotIn('对标/副标权谋/文风.md', res_b.stdout)

    def test_range_outline_and_hybrid_genre_routing(self):
        # Polish #1: 范围细纲 细纲_第1-10章.md 按目标章切片读取；缺目标章小节时明确中止。
        for existing in (self.book / '大纲').glob('细纲_*.md'):
            existing.unlink()
        self.put(
            '大纲/细纲_第1-10章.md',
            '# 第1-10章细纲\n\n'
            '### 第 1 章：雾起\n'
            '- 单元ID/位置：L1-01\n'
            '- 目标情绪：悬念\n'
            '- 主角目标与关键选择：进城摸底。\n\n'
            '### 第 2 章：夜审\n'
            '- 单元ID/位置：L1-01\n'
            '- 目标情绪：紧绷→反杀\n'
            '- 主角目标与关键选择：借假密电反扣内鬼。\n',
        )
        self.put('正文/第001章_雾起.md', '# 第001章 雾起\n\n雨夜电报机滴滴作响，他把密码本塞进炉灰里。\n')
        self.put('设定/题材定位.md', '- 题材类型：民国谍战 / 悬疑\n## 对标登记\n- 主对标书：无\n')
        res_ch2 = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 2)
        self.assertEqual(res_ch2.returncode, 0, res_ch2.stderr)
        self.assertIn('第002章_夜审.md', res_ch2.stdout)
        self.assertIn('细纲_第1-10章.md', res_ch2.stdout)
        self.assertIn('紧绷→反杀', res_ch2.stdout)
        # 2026-11-26: 混合标签「民国谍战 / 悬疑」以 历史架空权谋.md 为主流派包、悬疑灵异.md 为辅流派包，不再落 通用长篇.md。
        self.assertIn('主流派包：agent-references/genre-styles/历史架空权谋.md', res_ch2.stdout)
        self.assertIn('辅流派包：agent-references/genre-styles/悬疑灵异.md', res_ch2.stdout)
        self.assertNotIn('通用长篇.md', res_ch2.stdout)

        res_missing = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 3)
        self.assertEqual(res_missing.returncode, 2)
        self.assertIn('未找到第 3 章小节', res_missing.stderr)

        # 规则怪谈归 悬疑灵异.md 独占；班级求生 / 载具求生归 末世规则科幻.md，互不抢包。
        self.put('设定/题材定位.md', '- 题材类型：悬疑灵异 / 规则怪谈\n## 对标登记\n- 主对标书：无\n')
        res_rule = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 2)
        self.assertEqual(res_rule.returncode, 0, res_rule.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/悬疑灵异.md', res_rule.stdout)
        self.assertNotIn('末世规则科幻.md', res_rule.stdout)

        self.put('设定/题材定位.md', '- 题材类型：班级求生 / 载具求生\n## 对标登记\n- 主对标书：无\n')
        res_surv = self.call('build_writer_prompt.js', '--project', self.book, '--chapter', 2)
        self.assertEqual(res_surv.returncode, 0, res_surv.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/末世规则科幻.md', res_surv.stdout)

        # 全量 22 长篇 + 14 短篇流派包跨包别名唯一性校验，以及 2 个新增短篇流派包过构思契约检查。
        for kind, directory, expected_count in (
            ('long', ROOT / 'skills/story-long-write/references/genre-styles', 22),
            ('short', ROOT / 'skills/story-short-write/references/genre-styles', 14),
        ):
            files = sorted(directory.glob('*.md'))
            self.assertEqual(len(files), expected_count, f'{kind} genre pack count mismatch')
            seen_aliases = {}
            for fp in files:
                text = fp.read_text(encoding='utf-8')
                parts = text.split('---')
                self.assertGreaterEqual(len(parts), 3, f'{fp.name} missing frontmatter')
                meta = parts[1]
                genre_m = re.search(r'^genre:\s*(.+)$', meta, re.M)
                aliases_m = re.search(r'^aliases:\s*\[(.*)\]', meta, re.M)
                self.assertIsNotNone(genre_m, f'{fp.name} missing genre')
                self.assertIsNotNone(aliases_m, f'{fp.name} missing aliases')
                names = {genre_m.group(1).strip().lower()}
                names.update(
                    a.strip().strip('\'"').lower()
                    for a in aliases_m.group(1).split(',')
                    if a.strip().strip('\'"')
                )
                for name in names:
                    self.assertNotIn(
                        name,
                        seen_aliases,
                        f'{kind} duplicate alias {name!r}: {seen_aliases.get(name)} vs {fp.name}',
                    )
                    seen_aliases[name] = fp.name

        phase2_script = ROOT / 'skills/story-short-write/scripts/check-phase2-contract.js'
        for short_genre in ('校园青春暗恋', '仙侠奇幻末世'):
            short_dir = self.book.parent / f'short-{short_genre}'
            short_dir.mkdir(parents=True, exist_ok=True)
            (short_dir / '设定.md').write_text(
                '## 短篇核心框架\n\n### 基本信息\n'
                '- 标题（暂定）：测试短篇\n- 目标字数：10000 字\n- 目标平台：知乎盐言\n'
                '### 导语草稿\n放榜那晚，我把成绩单拍在桌上。\n'
                '### 这篇用的套路\n- 套路一：第1节立赌注\n- 套路二：第4节翻盘\n'
                '## 构思要点\n'
                f'- 题材：{short_genre}\n'
                '- 反派：\n  - 身份：对头\n  - 动机：嫉妒\n  - 作恶方式：造谣\n  - 致命弱点：贪心\n  - 报应：身败名裂\n'
                '- 反转类型：身份反转\n- 反转在：第 3 节（共 5 节）\n- 付费点：第 2 节末\n',
                encoding='utf-8',
            )
            (short_dir / '小节大纲.md').write_text(
                '| 在全篇哪一段 | 这节发生的事 | 情绪 | 节尾停在哪 | 目标字数 |\n'
                '|---|---|---|---|---|\n'
                '| 开局入局 | 冲突爆发 | 压 | 钩子 | 2000 |\n'
                '| 付费卡点 | 亮底牌一角 | 紧 | 付费点 | 2000 |\n'
                '| 连环反击 | 反转揭底 | 爽 | 钩子 | 2000 |\n'
                '| 连环反击 | 当众打脸 | 爽 | 钩子 | 2000 |\n'
                '| 清算收尾 | 回旋镖落幕 | 稳 | 清算 | 2000 |\n',
                encoding='utf-8',
            )
            p2 = subprocess.run(
                ['node', str(phase2_script), '--json', '--strict', str(short_dir)],
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
            self.assertEqual(p2.returncode, 0, f'{short_genre} failed phase2 contract: {p2.stdout}\n{p2.stderr}')

    def test_all_writing_deslop_review_cli_scripts_support_help(self):
        # 系统性回归：长篇/短篇/去味/审稿全部 CLI 脚本都必须干净支持 --help 与 -h（exit 0、stdout 非空、stderr 为空）。
        library_only = {'wordcount_core.js', 'style-whitelist.js'}
        skill_dirs = [
            ROOT / 'skills/story-long-write/scripts',
            ROOT / 'skills/story-short-write/scripts',
            ROOT / 'skills/story-deslop/scripts',
            ROOT / 'skills/story-review/scripts',
        ]
        cli_scripts = []
        for directory in skill_dirs:
            for script in sorted(directory.glob('*.js')):
                if script.name in library_only:
                    continue
                cli_scripts.append(script)
        self.assertGreaterEqual(len(cli_scripts), 20, f'unexpectedly few CLI scripts: {cli_scripts}')
        for script in cli_scripts:
            rel = script.relative_to(ROOT).as_posix()
            for flag in ('--help', '-h'):
                with self.subTest(script=rel, flag=flag):
                    completed = subprocess.run(
                        [NODE, str(script), flag],
                        cwd=ROOT,
                        capture_output=True,
                        encoding='utf-8',
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        f'{rel} {flag} exited {completed.returncode}: stdout={completed.stdout!r} stderr={completed.stderr!r}',
                    )
                    self.assertTrue(completed.stdout.strip(), f'{rel} {flag} produced empty stdout')
                    self.assertEqual(completed.stderr.strip(), '', f'{rel} {flag} wrote to stderr: {completed.stderr!r}')

    def test_builder_injects_compact_recent_timeline_anchors_without_leaking_unrevealed_facts(self):
        # 追踪/_tracking-state.json 存在时间线事件时，注入 ≤5 条、≤180 字的近期时间锚点，
        # 展示当前 position.story_time 对照与完整日期后缀（≤22 字不截断），且未揭示事件绝不泄露作者侧 objective_fact。
        timeline = {}
        for idx in range(1, 8):
            timeline[f'E{idx:03d}'] = {
                'id': f'E{idx:03d}',
                'story_time': '10月14日 20:30（第1天）' if idx == 6 else f'第{idx}天傍晚',
                'objective_fact': f'秘密真相第{idx}号不可下放' if idx == 7 else f'事件{idx}落定',
                'reader_knowledge': f'读者只知第{idx}天雨夜有异动' if idx == 7 else f'已知事件{idx}',
                'reveal_status': '未揭示' if idx == 7 else '已揭示',
                'reveal_chapter': None if idx == 7 else idx,
                'characters': ['主角'],
                'first_recorded_chapter': idx,
                'updated_chapter': idx,
            }
        state = {
            'schema_version': 4,
            'book_title': '雾港 来信',
            'last_committed_chapter': 7,
            'imported_through_chapter': 0,
            'state_revision': 7,
            'context': {
                'position': {
                    'volume': '第一卷',
                    'volume_start_chapter': 1,
                    'story_time': '第8天清晨',
                    'scene': '码头仓库',
                },
                'long_term_constraints': [],
                'active_character_names': [],
                'continuity_risks': [],
                'recent_chapters': [],
                'next_chapter_commitments': [],
            },
            'characters': {},
            'foreshadow': {},
            'timeline': timeline,
            'wordcount_records': {},
        }
        self.put('追踪/_tracking-state.json', json.dumps(state, ensure_ascii=False))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt_body, report_body = result.stdout.split('以下不进 prompt', 1)
        self.assertIn('——— 近期时间锚点', prompt_body)
        self.assertIn('第8天清晨', prompt_body)
        self.assertIn('10月14日 20:30（第1天）', prompt_body)
        self.assertIn('E007', prompt_body)
        self.assertNotIn('E001', prompt_body)  # 只取最近 ≤5 条
        self.assertNotIn('E002', prompt_body)
        self.assertNotIn('秘密真相第7号不可下放', prompt_body)  # 未揭示事件禁泄作者侧真相
        self.assertIn('近期时间锚点：已注入', report_body)
        anchor_section = prompt_body.split('——— 近期时间锚点', 1)[1].split('\n\n——— ', 1)[0]
        anchor_body = anchor_section.split('\n', 1)[1].strip()
        self.assertLessEqual(len(anchor_body.replace('\n', '')), 180, anchor_body)

    def test_builder_omits_timeline_anchors_when_state_empty_or_absent(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('——— 近期时间锚点', result.stdout)


class ImportOutlineBriefTests(unittest.TestCase):
    """导入逐批反推细纲：任务包只带本批规则、抽好的摘要要点、测好的长度与重叠的剧情单元卡。"""

    SCRIPT = ROOT / 'skills/story-import/scripts/build_outline_brief.js'
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
        return subprocess.run([NODE, str(self.SCRIPT), '--project', str(self.book), '--chapters', chapters],
                              cwd=self.root, capture_output=True, encoding='utf-8')

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
        # 兼容补零摘要文件名（如 第007章_摘要.md），与 inspect_existing_assets.js 一致。
        padded7 = self.root / '拆文库' / '旧书' / '章节' / '第007章_摘要.md'
        padded7.write_text(self.SUMMARY.format(n=7), encoding='utf-8')
        info, text = self.brief('1-12')
        self.assertEqual(info['missing_summaries'], [])
        self.assertIn('关键事件：江晨推门7 看见雨', text)
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
            [NODE, str(SCRIPTS / 'outline_view.js'), *args, str(volume)],
            capture_output=True, encoding='utf-8')
        check = view('--check', '--strict')
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn('问题 0 ／ 告警 0', check.stdout)
        unit = view('--unit', 'L1-01')
        self.assertEqual(unit.returncode, 0, unit.stderr)
        self.assertIn('这段让读者图什么', unit.stdout)
        _, text = self.brief('1-12')
        self.assertIn('### 第一段剧情：{一句话} <!-- L1-01 -->', text)
        # 导入带的取段器副本与写作端是同一份，两边解析不会分叉。
        self.assertEqual((ROOT / 'skills/story-import/scripts/outline_view.js').read_bytes(),
                         (SCRIPTS / 'outline_view.js').read_bytes())

    def test_batch_bounds(self):
        too_many = self.call('1-21')
        self.assertEqual(too_many.returncode, 2)
        self.assertIn('最多 20 章', too_many.stderr)
        too_few = self.call('1-5')
        self.assertEqual(too_few.returncode, 2)
        self.assertIn('至少 10 章', too_few.stderr)
        for ch in range(1, 6):
            self.put(f'大纲/细纲_第{ch:03d}章.md', f'## 细纲（第 {ch} 章）\n')
        rerun_ok = self.call('1-5')  # 已有细纲落盘的章节返修无需额外参数直接放行
        self.assertEqual(rerun_ok.returncode, 0, rerun_ok.stderr)
        self.assertEqual(json.loads(rerun_ok.stdout)['chapters'], '1-5')
        partial = self.root / '半成品四章'
        for ch in range(1, 5):
            p = partial / '正文' / f'第{ch:03d}章_起笔.md'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'# 第{ch}章 起笔\n\n刚写了四章的半成品。\n', encoding='utf-8')
        vol = partial / '大纲' / '卷纲_第1卷.md'
        vol.parent.mkdir(parents=True, exist_ok=True)
        vol.write_text('# 第一卷 卷纲\n\n### 第一段剧情：开局 <!-- L1-01 -->\n- 章节范围：第1-4章\n- 单元节拍/章功能分配：起笔\n', encoding='utf-8')
        partial_ok = subprocess.run(
            [NODE, str(self.SCRIPT), '--project', str(partial), '--chapters', '1-4'],
            cwd=self.root, capture_output=True, encoding='utf-8',
        )
        self.assertEqual(partial_ok.returncode, 0, partial_ok.stderr)
        self.assertEqual(json.loads(partial_ok.stdout)['chapters'], '1-4')
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
    """flow-opening-plan.md 的卷纲模板原样落盘，必须过取段器的严格校验。"""

    def test_template_passes_strict_check(self):
        doc = (ROOT / 'skills/story-long-write/references/flow-opening-plan.md').read_text(encoding='utf-8')
        template = template_block(doc, '卷纲')  # 与任务包同一取法：按围栏标签取
        with tempfile.TemporaryDirectory(prefix='volume-template-') as tmp:
            volume = Path(tmp) / '大纲' / '卷纲_第一卷.md'
            volume.parent.mkdir()
            volume.write_text(template + '\n', encoding='utf-8')
            run = lambda *args: subprocess.run(
                [NODE, str(SCRIPTS / 'outline_view.js'), *args, str(volume)],
                capture_output=True, encoding='utf-8')
            check = run('--check', '--strict')
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertIn('问题 0 ／ 告警 0', check.stdout)
            unit = run('--unit', 'L1-01')
            self.assertEqual(unit.returncode, 0, unit.stderr)
            self.assertIn('### 第一段剧情：{一句话} <!-- L1-01 -->', unit.stdout)
            self.assertEqual(unit.stderr, '')


class Round21RegressionTests(unittest.TestCase):
    """Round 21 实战回归：女频末世路由/抑制反向副包、无 # 标题、导入时间锚、文风切片与无双分隔线。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='round21-reg-')
        self.book = Path(self.tmp.name) / '回归书'
        (self.book / '设定').mkdir(parents=True)
        (self.book / '大纲').mkdir()
        (self.book / '正文').mkdir()
        (self.book / '追踪').mkdir()
        (self.book / '大纲' / '卷纲_第1卷.md').write_text(
            '# 第一卷 卷纲\n\n### 第一段剧情：开局 <!-- L1-01 -->\n'
            '- 章节范围：第1-10章\n- 这段让读者图什么：压迫→反杀\n- 这段怎么排：第1章入局，第2章反打\n',
            encoding='utf-8',
        )
        (self.book / '大纲' / '细纲_第001章.md').write_text(
            '### 第 1 章：不坐公车办私事，先签潘明的调令\n'
            '- 属于哪段剧情：L1-01\n- 字数目标：2200 字\n'
            '- 目标情绪：紧绷→反杀\n- 主角目标/关键选择：拒背黑锅并反压筹码\n',
            encoding='utf-8',
        )
        (self.book / '追踪' / '上下文.md').write_text(
            '\n'.join(f'## {h}\n无' for h in [
                '当前位置', '长期约束', '核心角色状态', '活跃伏笔', '近三章速记', '下一章承诺', '连贯性风险',
            ]),
            encoding='utf-8',
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_builder(self, chapter=1):
        return subprocess.run(
            [NODE, str(SCRIPTS / 'build_writer_prompt.js'), '--project', str(self.book), '--chapter', str(chapter)],
            capture_output=True, encoding='utf-8',
        )

    def test_female_apocalypse_routing_and_opposite_secondary_suppression(self):
        # 七猫女频 幻想言情 / 末世求生 与 末世 / 天灾囤货空间 均稳落女频包，且不注入男频 末世规则科幻.md 辅包
        for genre_line, audience in [
            ('幻想言情 / 末世求生', '女频'),
            ('末世 / 天灾囤货空间', '女频（天灾囤货）'),
            ('末世 / 天灾囤货空间', ''),
        ]:
            with self.subTest(genre=genre_line, audience=audience):
                profile = f'# 题材定位\n- 题材类型：{genre_line}\n- 主对标书：无\n'
                if audience:
                    profile += f'- 目标读者：{audience}\n'
                (self.book / '设定' / '题材定位.md').write_text(profile, encoding='utf-8')
                res = self.run_builder(1)
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertIn('主流派包：agent-references/genre-styles/女频末世天灾囤货.md', res.stdout)
                self.assertNotIn('辅流派包：agent-references/genre-styles/末世规则科幻.md', res.stdout)
                self.assertIn('本书流派包（女频末世天灾囤货）语感写', res.stdout)
                self.assertNotIn('单元情绪引擎', res.stdout)
        # 男频 末世危机 / 异能 稳落 末世规则科幻.md（已纳入 MALE_GENRE_CARDS）
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：末世危机 / 异能\n- 目标读者：男频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        male_res = self.run_builder(1)
        self.assertEqual(male_res.returncode, 0, male_res.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/末世规则科幻.md', male_res.stdout)

    def test_plain_heading_outline_copy_and_learn_heading_and_import_anchors(self):
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：官场商战\n- 目标读者：男频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        (self.book / '设定' / '文风.md').write_text(
            '# 本书文风\n\n## 原文语感锚点切片\n```text\n冯致远推回茶盒：“公职人员一分礼不碰。”\n```\n',
            encoding='utf-8',
        )
        ch1 = self.book / '正文' / '第001章_不坐公车办私事，先签潘明的调令.md'
        ch1.write_text('第1章 不坐公车办私事，先签潘明的调令\n周五下午，冯致远合上台账没碰复核表。\n', encoding='utf-8')
        # 无 # 纯文本长标题不误报细纲照搬
        copy_res = subprocess.run(
            [NODE, str(SCRIPTS / 'check-outline-copy.js'), str(ch1)],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(copy_res.returncode, 0, copy_res.stdout + copy_res.stderr)
        # Ch2 能学习无 # 标题形态，导入书时间锚优先用 reveal_chapter，且语感锚点抽自 设定/文风.md
        (self.book / '大纲' / '细纲_第002章.md').write_text(
            '### 第 2 章：会议室反将一军\n- 属于哪段剧情：L1-01\n- 字数目标：2200 字\n'
            '- 目标情绪：建压→爽\n- 主角目标/关键选择：拿出账册\n',
            encoding='utf-8',
        )
        (self.book / '追踪' / '_tracking-state.json').write_text(json.dumps({
            'last_committed_chapter': 2,
            'context': {'position': {'story_time': '周六上午'}},
            'timeline': {
                'E001': {
                    'id': 'E001', 'story_time': '周五下午', 'objective_fact': '拒坐公车',
                    'reader_knowledge': '已揭示', 'reveal_status': '已揭示',
                    'reveal_chapter': 1, 'first_recorded_chapter': 2, 'updated_chapter': 2,
                },
            },
        }, ensure_ascii=False), encoding='utf-8')
        res2 = self.run_builder(2)
        self.assertEqual(res2.returncode, 0, res2.stderr)
        self.assertIn('标题行（逐字照抄，勿按通用规则推导）：第2章 会议室反将一军', res2.stdout)
        self.assertIn('E001(第1章揭·周五下午)', res2.stdout)
        self.assertIn('来源：本书文风', res2.stdout)
        # build_architect_brief 不再产出双 --- 分隔线
        brief_run = subprocess.run(
            [NODE, str(SCRIPTS / 'build_architect_brief.js'), '--project', str(self.book), '--task', 'outline', '--chapters', '1-2'],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(brief_run.returncode, 0, brief_run.stderr)
        brief_path = Path(json.loads(brief_run.stdout)['brief'])
        self.assertIsNone(re.search(r'---\s*\n\s*---', brief_path.read_text(encoding='utf-8')))

    def test_campaign4_routing_corrupt_state_slices_and_outline_contracts(self):
        # 1) 西幻游戏同人.md 纳入 MALE_GENRE_CARDS（西方奇幻 + 玄幻 不被传统玄幻抢主包）
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：西方奇幻 / 玄幻\n- 目标读者：男频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        r_xf = self.run_builder(1)
        self.assertEqual(r_xf.returncode, 0, r_xf.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/西幻游戏同人.md', r_xf.stdout)

        # 2) 悬疑灵异.md 双频 tier=1（女频 悬疑 / 甜宠 与男频 悬疑 / 国运 均稳住主包）
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：现代悬疑 / 甜宠\n- 目标读者：女频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        r_susp = self.run_builder(1)
        self.assertEqual(r_susp.returncode, 0, r_susp.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/悬疑灵异.md', r_susp.stdout)

        # 3) 男频下禁止 tier=3 跨频包占 hits[0]（年代单标签不误落 女频年代军婚.md）
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：年代\n- 目标读者：男频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        r_male_era = self.run_builder(1)
        self.assertEqual(r_male_era.returncode, 0, r_male_era.stderr)
        self.assertNotIn('女频年代军婚.md', r_male_era.stdout)

        # 4) 双男主（tier=0）不混载 BG 女频副包
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：双男主 / 甜宠 / 娱乐圈\n- 目标读者：女频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        r_bl = self.run_builder(1)
        self.assertEqual(r_bl.returncode, 0, r_bl.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/双男主.md', r_bl.stdout)
        self.assertNotIn('青春甜宠文娱.md', r_bl.stdout)

        # 5) 设定/文风.md 无二级子标题但有 ```text 代码块时仍可抽取语感切片
        (self.book / '设定' / '文风.md').write_text(
            '# 本书文风\n\n```text\n雨声砸在石阶上，他把铁匣扣死，只回了一个字：“走。”\n```\n',
            encoding='utf-8',
        )
        r_plain_style = self.run_builder(1)
        self.assertEqual(r_plain_style.returncode, 0, r_plain_style.stderr)
        self.assertIn('雨声砸在石阶上', r_plain_style.stdout)
        (self.book / '设定' / '文风.md').unlink()

        # 6) 损毁 _tracking-state.json 时必须显式报错（禁止 rc=0 静默放行）
        (self.book / '追踪' / '_tracking-state.json').write_text('{BROKEN_JSON', encoding='utf-8')
        r_corrupt = self.run_builder(1)
        self.assertNotEqual(r_corrupt.returncode, 0)
        self.assertIn('_tracking-state.json', r_corrupt.stderr + r_corrupt.stdout)
        (self.book / '追踪' / '_tracking-state.json').unlink()

        # 7) check-outline-contract.js 传目录给友好报错而非裸 EISDIR，且 evidence 不拼接布尔值 true
        oc_dir = subprocess.run(
            [NODE, str(SCRIPTS / 'check-outline-contract.js'), '--json', str(self.book / '大纲')],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(oc_dir.returncode, 1)
        self.assertNotIn('EISDIR', oc_dir.stdout)
        self.assertIn('目录', oc_dir.stdout)
        oc_file = subprocess.run(
            [NODE, str(SCRIPTS / 'check-outline-contract.js'), '--json', str(self.book / '大纲' / '细纲_第001章.md')],
            capture_output=True, encoding='utf-8',
        )
        self.assertNotIn('）：true', oc_file.stdout)

        # 8) check-outline-copy.js 豁免 细纲「章尾钩子」里的预设原话
        (self.book / '大纲' / '细纲_第001章.md').write_text(
            '### 第 1 章：暗账\n- 字数目标：2200 字\n- 目标情绪：压抑→反击\n'
            '- 主角目标/关键选择：亮账册\n'
            '- 章尾钩子：“明早九点带着公章去税务局补缴这三百万欠税吧。”\n',
            encoding='utf-8',
        )
        ch1 = self.book / '正文' / '第001章_暗账.md'
        ch1.write_text(
            '# 第1章 暗账\n\n他把账簿推回桌面，抬头看着慌了神的经理。\n'
            '“明早九点带着公章去税务局补缴这三百万欠税吧。”\n',
            encoding='utf-8',
        )
        cp = subprocess.run(
            [NODE, str(SCRIPTS / 'check-outline-copy.js'), str(ch1)],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)


        # 9) Wave 5 路由回归：男频 明星娱乐 进 都市日常神豪.md；无同频包时 tier=3 合法回退防跌 通用长篇.md；
        # 严格 BL 词表防 宿敌/纯爱 误劫男频或女频常规书。
        for genre, reader, expected_main, forbidden in [
            ('都市 / 明星娱乐', '男频', '都市日常神豪.md', '通用长篇.md'),
            ('都市 / 热血校园', '男频', '青春甜宠文娱.md', '通用长篇.md'),
            ('游戏竞技 / 网游电竞', '女频', '西幻游戏同人.md', '通用长篇.md'),
            ('动漫衍生', '女频', '动漫男频衍生.md', '通用长篇.md'),
            ('都市生活 / 纯爱', '男频', '都市日常神豪.md', '双男主.md'),
            ('古代情缘 / 宿敌 / 纯爱', '女频', '古言宅斗重生.md', '双男主.md'),
            ('纯爱', '大众', '双男主.md', '通用长篇.md'),
            ('ABO / 权谋', '女频', '双男主.md', '古言宅斗重生.md'),
        ]:
            with self.subTest(genre=genre, reader=reader):
                (self.book / '设定' / '题材定位.md').write_text(
                    f'# 题材定位\n- 题材类型：{genre}\n- 目标读者：{reader}\n- 主对标书：无\n',
                    encoding='utf-8',
                )
                r_w5 = self.run_builder(1)
                self.assertEqual(r_w5.returncode, 0, r_w5.stderr)
                self.assertIn(f'主流派包：agent-references/genre-styles/{expected_main}', r_w5.stdout)
                self.assertNotIn(forbidden, r_w5.stdout)

        # 10) Wave 7A 回归：主类型/子类型/题材参考包识别、星际向哨与商战实业切片加权、
        #     Ch1 无 正文/ 中性提示、白话卷纲段标题降档识别、章首钩子引号豁免。
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 主类型：星际向哨\n- 频道：女频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        (self.book / '大纲' / '卷纲_第一卷.md').write_text(
            '# 第一卷 卷纲\n\n## 本卷剧情 <!-- 全卷 -->\n\n'
            '### 第一段：七日狂囤与合闸建堡（第1–3章）\n'
            '- 这段让读者图什么：倒计时搬空冷库并唤醒精神海\n'
            '- 这段怎么排：第1章验真立约，第2章狂囤建堡，第3章破冰反杀\n',
            encoding='utf-8',
        )
        (self.book / '大纲' / '细纲_第001章.md').write_text(
            '### 第 1 章：荒星合闸\n'
            '- 所属剧情段：第一段（第1–3章）\n'
            '- 字数目标：2200 字\n'
            '- 目标情绪：紧迫→掌控\n'
            '- 主角目标/关键选择：锁死冷库并接管防线\n'
            '- 章首钩子：“这纸卖身契你留着擦鞋吧，冷库钥匙归我了！”\n',
            encoding='utf-8',
        )
        import shutil
        if (self.book / '正文').exists():
            shutil.rmtree(self.book / '正文')
        r_w7_sci = self.run_builder(1)
        self.assertEqual(r_w7_sci.returncode, 0, r_w7_sci.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/女频末世天灾囤货.md', r_w7_sci.stdout)
        self.assertIn('星际向哨', r_w7_sci.stdout)
        self.assertIn('首章尚无前文标题参照', r_w7_sci.stdout)
        self.assertIn('召回降档：成立', r_w7_sci.stdout)

        # R049 回归：build_architect_brief.js 与 build_writer_prompt.js 共用路由（支持主类型/频道/防纯爱误劫持）
        arch_sci = subprocess.run(
            [NODE, str(SCRIPTS / 'build_architect_brief.js'), '--project', str(self.book), '--task', 'world'],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(arch_sci.returncode, 0, arch_sci.stderr)
        arch_sci_out = json.loads(arch_sci.stdout)
        self.assertTrue(any(name.startswith('genre-styles/女频末世天灾囤货.md') for name in arch_sci_out['includes']), arch_sci_out['includes'])

        # 4 字复合词（商战职场 / 实业崛起）命中 官场商战职场.md 的职场博弈切片，且 architect 同路由
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材参考包：商战职场\n- 子类型：实业崛起 / 职场博弈\n- 目标读者：男频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        r_w7_ind = self.run_builder(1)
        self.assertEqual(r_w7_ind.returncode, 0, r_w7_ind.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/官场商战职场.md', r_w7_ind.stdout)
        self.assertIn('切片 B：职场博弈', r_w7_ind.stdout)
        arch_ind = subprocess.run(
            [NODE, str(SCRIPTS / 'build_architect_brief.js'), '--project', str(self.book), '--task', 'world'],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(arch_ind.returncode, 0, arch_ind.stderr)
        self.assertTrue(any(name.startswith('genre-styles/官场商战职场.md') for name in json.loads(arch_ind.stdout)['includes']))

        # R049 回归：BG 言情带「纯爱」时 build_architect_brief 不再误劫持进 双男主.md
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- 题材类型：古代情缘 / 宿敌 / 纯爱\n- 目标读者：女频\n- 主对标书：无\n',
            encoding='utf-8',
        )
        arch_bg = subprocess.run(
            [NODE, str(SCRIPTS / 'build_architect_brief.js'), '--project', str(self.book), '--task', 'world'],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(arch_bg.returncode, 0, arch_bg.stderr)
        arch_bg_inc = json.loads(arch_bg.stdout)['includes']
        self.assertTrue(any(name.startswith('genre-styles/古言宅斗重生.md') for name in arch_bg_inc), arch_bg_inc)
        self.assertFalse(any(name.startswith('genre-styles/双男主.md') for name in arch_bg_inc), arch_bg_inc)

        # R049 回归：author_memory_commit.js --help 列出 --genre 与 --workflow
        mem_help = subprocess.run(
            [NODE, str(SCRIPTS / 'author_memory_commit.js'), '--help'],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(mem_help.returncode, 0)
        self.assertIn('--genre', mem_help.stdout)
        self.assertIn('--workflow', mem_help.stdout)

        # R089 回归 1：genreLine() 识别「流派」标签，不再静默降档为 通用长篇.md
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n- **书名**：测试书\n- **流派**：豪门虐恋追妻\n- **目标读者**：女频\n- **主对标书**：无\n',
            encoding='utf-8',
        )
        r_r089_genre = self.run_builder(1)
        self.assertEqual(r_r089_genre.returncode, 0, r_r089_genre.stderr)
        self.assertIn('主流派包：agent-references/genre-styles/豪门虐恋追妻.md（置信度 high）', r_r089_genre.stdout)
        self.assertNotIn('主流派包：agent-references/genre-styles/通用长篇.md', r_r089_genre.stdout)
        arch_r089 = subprocess.run(
            [NODE, str(SCRIPTS / 'build_architect_brief.js'), '--project', str(self.book), '--task', 'world'],
            capture_output=True, encoding='utf-8',
        )
        self.assertEqual(arch_r089.returncode, 0, arch_r089.stderr)
        self.assertTrue(any(name.startswith('genre-styles/豪门虐恋追妻.md') for name in json.loads(arch_r089.stdout)['includes']))

        # R089 回归 2：长程时间锚点满载长时间戳时，绝不输出 0 字空摘要条目，宁可少留 1 条也保证每条带可读摘要
        long_timeline = {}
        for idx, (st, fact) in enumerate([
            ('10月8日上午十一点（冷静期第7天）', '梁母携方知韵拍十万支票上门被老藏家打脸'),
            ('10月10日上午至雨夜（冷静期第9天）', '许明棠提前两天交付册页全票获博物院特聘函'),
            ('10月13日清晨（冷静期第12天）', '许明棠在恒温库测出加湿器水样十点二强碱'),
            ('10月16日傍晚（冷静期第15天）', '梁景行递交三百八十万五年劳务补结协议认错'),
            ('10月19日上午（冷静期第18天）', '梁景行出示红章注销回执反杀亲妈起拍价翻倍'),
        ], start=5):
            long_timeline[f'E{idx:03d}'] = {
                'id': f'E{idx:03d}',
                'story_time': st,
                'objective_fact': fact,
                'reader_knowledge': fact,
                'reveal_status': '已揭示',
                'reveal_chapter': idx,
                'characters': ['许明棠', '梁景行'],
                'first_recorded_chapter': idx,
                'updated_chapter': idx,
            }
        (self.book / '追踪').mkdir(exist_ok=True)
        (self.book / '追踪' / '_tracking-state.json').write_text(json.dumps({
            'schema_version': 1,
            'last_committed_chapter': 9,
            'state_revision': 9,
            'context': {
                'position': {'volume': '第一卷', 'volume_start_chapter': 1, 'story_time': '10月19日上午十点半（冷静期第18天）', 'scene': '展厅'},
                'long_term_constraints': [], 'active_character_names': [], 'continuity_risks': [],
                'recent_chapters': [], 'next_chapter_commitments': [],
            },
            'characters': {}, 'foreshadow': {}, 'timeline': long_timeline, 'wordcount_records': {},
        }, ensure_ascii=False), encoding='utf-8')
        r_r089_anchor = self.run_builder(1)
        self.assertEqual(r_r089_anchor.returncode, 0, r_r089_anchor.stderr)
        prompt_p, _ = r_r089_anchor.stdout.split('以下不进 prompt', 1)
        anchor_sec = prompt_p.split('——— 近期时间锚点', 1)[1].split('\n\n——— ', 1)[0]
        anchor_lines = anchor_sec.split('\n')[1:]
        anchor_body = '\n'.join(anchor_lines).strip()
        self.assertLessEqual(len(anchor_body.replace('\n', '')), 180, anchor_body)
        items = [seg for seg in anchor_lines[1].split('；') if seg.strip()]
        self.assertGreaterEqual(len(items), 2, items)
        for item in items:
            after_paren = item.rsplit(')', 1)[-1]
            self.assertGreaterEqual(len(after_paren), 6, f'空摘要或过度截断的时间锚点条目: {item!r}')

        # WS4 回归：writer prompt 必须注入精炼写作硬底线，并更新语感切片引导语
        self.assertIn('——— 写作硬底线 ———', prompt_p)
        self.assertIn('叙述保人物内心盘算与口语因果连接', prompt_p)
        self.assertIn('短对话直接交锋', prompt_p)
        self.assertIn('关键道具和证物', prompt_p)
        self.assertIn('反派须按私心反咬设阻', prompt_p)
        self.assertIn('只学口语连接、句长断行与对话推进感', prompt_p)

    def test_v5_genre_pack_section_split_and_fallback(self):
        """v5 题材包按节分读：架构师仅拿 1–3 节（不含 4–5 节），写手拿 4–5 节（不含 1–3 节），非标包优雅回退。"""
        v5_js = r"""
const assert = require('node:assert/strict');
const { sliceGenrePack, extractGenreProseTechniques } = require('./skills/story-long-write/scripts/build_writer_prompt.js');
const { sliceGenrePack: archSlice } = require('./skills/story-long-write/scripts/build_architect_brief.js');

assert.equal(sliceGenrePack, archSlice);

const v5Sample = `---
genre: 测试题材
aliases: [测试]
---
# 长篇题材包：测试题材

> 核心底线：反派按私心反咬。

## 1. 故事线设计
主轴推进：先受阻再破局。

## 2. 常见剧情设计
黄金三章：首章抛硬账单。

## 3. 人物设计
主角清醒，反派有牙齿。

## 4. 正文技巧
- 对白净白短打，砍无功能材质贴纸。
- ✅ 高分改写法：实戏示范文本。

## 5. 案例片段
### 片段一：测试原文
\`\`\`text
“这账怎么算？”
\`\`\`
- **学什么**：短打对白推进。
`;

const archRes = sliceGenrePack(v5Sample, [1, 2, 3]);
assert.equal(archRes.sliced, true);
assert.ok(archRes.text.includes('# 长篇题材包：测试题材'));
assert.ok(archRes.text.includes('> 核心底线：反派按私心反咬。'));
assert.ok(archRes.text.includes('## 1. 故事线设计'));
assert.ok(archRes.text.includes('## 2. 常见剧情设计'));
assert.ok(archRes.text.includes('## 3. 人物设计'));
assert.ok(!archRes.text.includes('## 4. 正文技巧'));
assert.ok(!archRes.text.includes('## 5. 案例片段'));
assert.ok(!archRes.text.includes('genre: 测试题材'));

const tech = extractGenreProseTechniques(v5Sample);
assert.ok(tech && tech.includes('对白净白短打'));
assert.ok(!tech.includes('## 1. 故事线设计'));
assert.ok(!tech.includes('## 5. 案例片段'));

const legacySample = `---
genre: 旧包
---
# 旧版流派包

## 1. 定位、平台与读者期待
旧内容。

## 6. 真·网文原文语感切片
### 切片 A
\`\`\`text
旧切片。
\`\`\`
`;

const fbArch = sliceGenrePack(legacySample, [1, 2, 3]);
assert.equal(fbArch.sliced, false);
assert.equal(fbArch.text, legacySample);
assert.equal(extractGenreProseTechniques(legacySample), null);
console.log('V5_SLICE_UNIT_OK');
"""
        unit_res = subprocess.run([NODE, '-e', v5_js], cwd=str(ROOT), capture_output=True, encoding='utf-8')
        self.assertEqual(unit_res.returncode, 0, unit_res.stderr + unit_res.stdout)
        self.assertIn('V5_SLICE_UNIT_OK', unit_res.stdout)

        # 端到端检验：若 豪门虐恋追妻.md 已切为 v5 五段结构，架构师任务包只含 1–3 节、写手 prompt 注入 4. 正文技巧 + 5. 案例片段且不含 1–3 节
        pack_text = (ROOT / 'skills/story-long-write/references/genre-styles/豪门虐恋追妻.md').read_text(encoding='utf-8')
        if '## 1. 故事线设计' in pack_text:
            (self.book / '设定' / '题材定位.md').write_text(
                '# 题材定位\n- **书名**：测试书\n- **流派**：豪门虐恋追妻\n- **目标读者**：女频\n- **主对标书**：无\n',
                encoding='utf-8',
            )
            arch_r = subprocess.run(
                [NODE, str(SCRIPTS / 'build_architect_brief.js'), '--project', str(self.book), '--task', 'world'],
                capture_output=True, encoding='utf-8',
            )
            self.assertEqual(arch_r.returncode, 0, arch_r.stderr)
            arch_payload = json.loads(arch_r.stdout)
            self.assertIn('genre-styles/豪门虐恋追妻.md（1–3节：故事线/剧情/人物）', arch_payload['includes'])
            arch_body = Path(arch_payload['brief']).read_text(encoding='utf-8')
            self.assertIn('## 1. 故事线设计', arch_body)
            self.assertIn('## 2. 常见剧情设计', arch_body)
            self.assertIn('## 3. 人物设计', arch_body)
            self.assertNotIn('## 4. 正文技巧', arch_body)
            self.assertNotIn('## 5. 案例片段', arch_body)

            writer_r = self.run_builder(1)
            self.assertEqual(writer_r.returncode, 0, writer_r.stderr)
            writer_prompt, writer_report = writer_r.stdout.split('以下不进 prompt', 1)
            self.assertIn('仅读 4. 正文技巧 与 5. 案例片段；已注入下方', writer_prompt)
            self.assertIn('——— 流派正文技巧（豪门虐恋追妻 · 4. 正文技巧）———', writer_prompt)
            self.assertIn('——— 语感锚点切片', writer_prompt)
            self.assertNotIn('## 1. 故事线设计', writer_prompt)
            self.assertNotIn('## 2. 常见剧情设计', writer_prompt)
            self.assertNotIn('## 3. 人物设计', writer_prompt)
            self.assertIn('流派正文技巧：已注入「豪门虐恋追妻」4. 正文技巧', writer_report)

    def test_benchmark_auto_recalls_emotion_rhythm_guardrails_and_high_strength(self):
        # 拆文→写作增强：表格填「引用强度：高」也可识别主对标；即便召回降档成立且 设定/文风.md 含普通代码块，
        # 仍自动注入主对标 情绪模块(EM-xxx)、节奏循环(RH-xxx)、不建议模仿/分层模仿要点 与 基调匹配原文切片。
        bench = '对标拆文样板书'
        (self.book / '设定' / '题材定位.md').write_text(
            '# 题材定位\n'
            '- 题材类型：都市高武异能\n'
            '## 对标登记\n'
            '| 书名 | 题材类型 | 引用强度 | 用途 |\n'
            '|---|---|---|---|\n'
            f'| {bench} | 都市高武异能 | 高 | 节奏与语感主对标 |\n',
            encoding='utf-8',
        )
        (self.book / '设定' / '文风.md').write_text(
            '# 本书文风\n竖屏自然呼吸。\n```text\n示例面板：气血+10\n```\n',
            encoding='utf-8',
        )
        bdir = self.book / '对标' / bench
        (bdir / '剧情').mkdir(parents=True, exist_ok=True)
        (bdir / '文风.md').write_text(
            f'# {bench} 文风\n\n'
            '## 分层模仿建议\n'
            '- 基础层（必学）：短对白快推，叙述默认句号\n'
            '- 适配层（当前项目）：保留三级参照，不搬道士僵尸专名\n\n'
            '## 原文锚点片段\n\n'
            '### 片段 A — 基调：开篇钩子/紧张\n```text\n开篇钩子原文切片测试文本。\n```\n\n'
            '### 片段 B — 基调：爽点/打脸\n```text\n爽点打脸原文切片测试文本。\n```\n\n'
            '### 片段 C — 基调：轻松日常\n```text\n日常换气原文切片测试文本。\n```\n\n'
            '## 不建议模仿\n'
            '- 感叹号刷屏过密。\n'
            '- 配角围观三连呼降智且反复报流水账；\n',
            encoding='utf-8',
        )
        (bdir / '剧情' / '情绪模块.md').write_text(
            '# 情绪模块\n\n'
            '## 可复现模块卡\n\n'
            '### EM-001 三级参照打脸\n'
            '| 字段 | 内容 |\n|---|---|\n'
            '| 读者想看什么 | 冷门专精越级破限 |\n'
            '| 情绪链 | 群嘲 → 三级垫脚 → 一击碾穿 → 权威重评 |\n'
            '| 戏剧单元 | 公开考核反杀 |\n'
            '| 不可照搬 | 原书人名与道具 |\n',
            encoding='utf-8',
        )
        (bdir / '剧情' / '节奏.md').write_text(
            '# 节奏索引\n\n'
            '## 爽点循环索引\n'
            '| 循环ID | 章节范围 | 铺垫层 | 释放层 | 反应层 | 衔接层/新钩子 | 强度递进 |\n'
            '|---|---|---|---|---|---|---|\n'
            '| RH-001 | 第1-2章 | 选冷门遭嘲 | 越级一击破限 | 权威失态重评 | 触发新能力 | 首轮强 |\n',
            encoding='utf-8',
        )
        res = self.run_builder(1)
        self.assertEqual(res.returncode, 0, res.stderr)
        prompt_body, report_body = res.stdout.split('以下不进 prompt', 1)
        self.assertIn('EM-001 三级参照打脸', prompt_body)
        self.assertIn('RH-001', prompt_body)
        self.assertIn(f'——— 主对标「{bench}」避坑与写法要点', prompt_body)
        self.assertIn('感叹号刷屏过密；配角围观三连呼降智且反复报流水账', prompt_body)
        self.assertNotIn('。；', prompt_body)
        self.assertNotIn('；；', prompt_body)
        self.assertIn('适配层（当前项目）', prompt_body)
        self.assertIn(f'主对标「{bench}」文风原文锚点', report_body)
        self.assertIn('主对标结构参考：已从', report_body)
        self.assertIn('主对标避坑：已从', report_body)

        # 验证细纲自然中文基调词可精准命中对应切片（而非因 4 字硬拆落空）
        (self.book / '大纲' / '细纲_第001章.md').write_text(
            '### 第 1 章：炖肉换气\n'
            '- 所属剧情段：U1-1\n'
            '- 目标情绪：轻松日常烟火暖意\n'
            '- 主角目标/关键选择：回屋炖肉换气，化开家里紧绷气氛\n'
            '- 核心事件：买肉回家做晚饭，日常换气\n',
            encoding='utf-8',
        )
        res2 = self.run_builder(1)
        self.assertEqual(res2.returncode, 0, res2.stderr)
        prompt2, _ = res2.stdout.split('以下不进 prompt', 1)
        self.assertIn('【片段 C — 基调：轻松日常】', prompt2)


if __name__ == '__main__':
    unittest.main()
