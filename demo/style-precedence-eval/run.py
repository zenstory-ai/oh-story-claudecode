#!/usr/bin/env python3
"""Paired real Codex CLI replay. No personal skills, agents, network research or live books."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    'book_style': {
        'style': '本书采用冷静的短句，叙述句以8至15字为主，允许孤立重拍。对白用省略号表现未说完，用破折号表现被外界打断。保留有上下文根据的直接情绪判断，不为情绪添加身体反应。“不是退让，而是给彼此留条路。”是本章人物关系的判断，保留这句有功能的修辞。',
        'prose': '''## 第1章 留灯
周宁把钥匙放在桌边。母亲没有接。
门锁换过了。她试了两次，旧钥匙都转不动。母亲端着碗，站在离她两步远的地方。
“钥匙在——”
楼下的电钻突然响了。母亲指指抽屉，等那阵声音过去。
周宁拉开抽屉。新钥匙压在缴费单下面。一把给她，一把给母亲。她把自己的那把挂上钥匙圈。
“你……还住这里吗？”
母亲问得很轻。周宁已经租好房子，周六搬走。这件事上周就说过了。
“周三回来吃饭。”
母亲把碗放下。她原本想说，空着的房间也要交物业费。话到了嘴边，又收了回去。
周宁害怕她再提钱。搬家押金借了同事一半，下个月才还得上。
不是退让，而是给彼此留条路。
“周三我买菜。”她说。
母亲把冰箱上的送菜电话揭掉。纸角粘得紧，撕下一小块，白白地留在门上。
她们并排吃完了饭。周宁洗碗，母亲擦桌子。谁也没再提房租。
周宁不是没有想过回头，而是根本没有回头的勇气。她的心中涌起一股难以言喻的复杂情绪。
出门前，她按了一下楼道的开关。灯没有亮。母亲从抽屉里拿出备用灯泡，递到她手里。
周宁搬来椅子换好灯。她下到一楼时，身后的灯还亮着。
''',
    },
    'omniscient': {
        'style': '本书采用有限全知，允许进入周宁和母亲各自的内心。人物不必把想法说出口。叙述者可直接解释人物已知的因果，但不泄露尚未发生的事情。不删功能性内心，只删重复和空泛总结。',
        'prose': '''## 第1章 留灯
周宁把钥匙放在桌边。母亲没有接。
母亲盯着钥匙，心里算着下一季的物业费。少一份工资，她还能负担；少一个人吃饭，她不想提前算。
周宁以为她又要提钱。搬家的押金借了同事一半，下个月才还得上。她把缴费单向母亲那边推了一点。
“这笔我已经交了。”
母亲没有看账单。她想问新住处有没有电梯，又怕一开口，女儿就当她在挑毛病。
楼下的电钻响起来。周宁去关窗，窗扣松了，扣了两次才扣紧。
母亲趁她转身，把新钥匙放在缴费单上。一把给女儿，一把留给自己。锁是昨天换的，旧锁坏了很久，她一直拖着没修。
“周三回来吃饭吗？”
周宁说好。她其实怕自己回来得太勤，又被劝着搬回家。但周三只是一顿饭，答应一顿饭还不算认输。
母亲想烧鱼，想到女儿嫌挑刺，改口问她想吃什么。周宁说番茄炒蛋。
她的心中涌起一股难以言喻的复杂情绪。命运的齿轮开始转动。
母亲揭下冰箱上的送菜电话，把周三两个字写在便笺上。女儿洗碗时没看见。她也不打算叫她看。
出门前，周宁按了一下楼道的开关。灯没亮。母亲递来备用灯泡，她搬椅子换好了灯。
''',
    },
    'default': {
        'style': None,
        'prose': '''## 第1章 账单
林青把账单放在桌上，手指还按着最后一行。收款人是王建，金额两万，日期是上周五。
她不是来讨价还价，而是来拿回自己的钱。她的心中涌起一股难以言喻的复杂情绪。
“你说昨天就退。”
王建把账单翻过去。他说财务还没有上班。林青点开手机，财务十分钟前发来的消息还在：退款申请没收到。
王建的声音不大，却带着不容置疑的威严。他让林青把手机收起来。
没有道歉，没有解释，没有任何让步。他把抽屉推回去，钥匙转了两圈。
林青拍下抽屉里的收据编号。她没有碰他的东西。手机往自己这边收，录像里仍能看清账单上的两万。
“现在发申请。我在这里等。”
王建给财务拨了电话。第一次没人接。他把电话放下，想说改天再来，林青先把椅子拉到了桌边。
第二次电话接通了。财务说收到申请后十分钟到账。林青在手机上设好计时，屏幕朝着王建。
王建打开电脑，终于发出了申请。
没人知道，这才刚刚开始。命运的齿轮开始转动。
''',
    },
}

CASES['memory_only'] = {
    **CASES['omniscient'],
    'style': None,
    'book_preference': '这本书采用有限全知，允许进入周宁和母亲各自的内心。保留有根据的直接情绪判断，只删空泛和重复总结。',
}
CASES['current_request'] = {
    **CASES['omniscient'],
    'request': '本次例外：改为周宁的限知视角，只写她能感知的事情。母亲没有说出口且周宁看不见的内心不再直接叙述，也不要把它们改成新台词；不为此改动任何长期文风或记忆。',
}


def memory(project, repo, book_preference=None):
    tool = repo / 'skills/story/scripts/author_memory_commit.py'
    for i, (scope, assertion) in enumerate([
        ({'level': 'global', 'value': None}, '一贯用深度限知和逗号长句，不用省略号或破折号。'),
        ({'level': 'book', 'value': '留灯'}, book_preference or '这本书的短句可保留，具体视角和标点按本书文风。'),
    ]):
        event = {'schema_version': 1, 'event_id': f'fixture-{i}', 'operation': {'action': 'remember', 'preference': {
            'kind': 'prose_style', 'scope': scope, 'assertion': assertion, 'quote': assertion,
            'source_ref': 'synthetic:user', 'source': 'explicit_user', 'confidence': 'high',
            'importance': 'high', 'status': 'active', 'reason': 'isolated experiment fixture', 'conflicts_with': []}}}
        inp = project / 'event.json'; inp.write_text(json.dumps(event, ensure_ascii=False), encoding='utf-8')
        subprocess.run([sys.executable, str(tool), 'record', '--workspace', str(project), '--input', str(inp)], check=True, capture_output=True)
        inp.unlink()


def run_case(out, arm, case, repo, repeat):
    run = out / f'{case}-{arm}-{repeat}'
    project = run / 'project'; project.mkdir(parents=True)
    shutil.copytree(repo / 'skills/story-deslop', project / 'skills/story-deslop')
    title = '账单' if case == 'default' else '留灯'
    book = project / title; (book / '正文').mkdir(parents=True); (book / '设定').mkdir()
    data = CASES[case]
    file = book / f'正文/第001章_{title}.md'; file.write_text(data['prose'], encoding='utf-8')
    if data['style']:
        (book / '设定/文风.md').write_text('# 文风\n' + data['style'] + '\n', encoding='utf-8')
    if data['style'] or data.get('book_preference'):
        memory(project, repo, data.get('book_preference'))
    request = f'''请先读取 skills/story-deslop/SKILL.md，使用这份 skill 对《{title}》第1章去 AI 味，完成必要检查并交付。正文在 {title}/正文/第001章_{title}.md。按这本书的既有约定处理，保留人物、已发生事件、人物知识边界和因果；不要扩写或新增情节。无须询问，按现有材料完成。
实验环境限制：solo/direct，无专业 agent，不联网、不读个人 skills。只可修改该正文和按技能协议维护本书 .deslop-whitelist；不得改文风、作者记忆、skills 或其他文件。所有材料位于当前工作区。不要用程序生成正文。'''
    request += '\n' + data.get('request', '')
    protected = {p: p.read_bytes() for directory in [book / '设定', project / '.story'] for p in directory.rglob('*') if p.is_file()}
    (run / 'PROMPT.md').write_text(request, encoding='utf-8')
    start=time.monotonic()
    cmd=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','-s','workspace-write','-C',str(project),'--json','-o',str(run/'OUTPUT.md'),'-']
    env={**os.environ,'PYTHONIOENCODING':'utf-8'}
    with (run/'events.jsonl').open('w') as log, (run/'stderr.log').open('w') as err:
        result=subprocess.run(cmd,input=request,text=True,stdout=log,stderr=err,env=env,timeout=900)
    events=[]
    for line in (run/'events.jsonl').read_text().splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    body=file.read_text(encoding='utf-8')
    subprocess.run(['node',str(project/'skills/story-deslop/scripts/check-ai-patterns.js'),'--json','--fail-on=blocking',str(file)],stdout=(run/'scan.json').open('w'),check=False)
    facts={'case':case,'arm':arm,'repeat':repeat,'exit':result.returncode,'seconds':round(time.monotonic()-start,1),
           'usage':[e.get('usage') for e in events if e.get('type')=='turn.completed'],
           'ellipsis':body.count('……'),'em_dash':body.count('——'),
           'protected_inputs_unchanged': all(p.read_bytes() == content for p,content in protected.items()),
           'approved_sentence': '不是退让，而是给彼此留条路。' in body,
           'generic_complex_emotion': '难以言喻' in body,
           'whitelist': (book/'.deslop-whitelist').read_text() if (book/'.deslop-whitelist').exists() else None}
    (run/'RESULT.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(facts,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',required=True,type=Path);parser.add_argument('--out',required=True,type=Path);parser.add_argument('--repeat',type=int,default=1);parser.add_argument('--cases',nargs='+',choices=CASES,default=list(CASES));parser.add_argument('--arms',nargs='+',choices=['baseline','candidate'],default=['baseline','candidate']);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    candidate = out / 'candidate-source'
    shutil.copytree(ROOT / 'skills', candidate / 'skills')
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(run_case,out,arm,case,repo,repeat) for repeat in range(1,args.repeat+1) for case in args.cases for arm,repo in [('baseline',args.baseline.resolve()),('candidate',candidate)] if arm in args.arms]
        for job in jobs:job.result()

if __name__=='__main__':main()
