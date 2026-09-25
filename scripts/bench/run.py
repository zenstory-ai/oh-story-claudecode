#!/usr/bin/env python3
"""跑一个基准用例：从 fixture 起一个隔离项目，部署指定版本的包，用真实 CLI 会话执行用例的轮次。

用法：
  run.py --case mid-daily --pkg <pkg目录> --host claude-code --out <runs目录> [--label v0711]

fixture 与主机配置都放在仓库外（见 README.md）：
  BENCH_HOME（默认 ~/.oh-story-bench）/fixtures/<fixture>/   一本冻结的书
  BENCH_HOME/hosts.json                                       各主机的可执行文件、模型和凭据文件
产物（会话日志、项目快照）写到 --out，不进 git。
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import deploy  # noqa: E402

BENCH_HOME = Path(os.environ.get('BENCH_HOME', Path.home() / '.oh-story-bench'))
IDLE_S, HARD_S = 30 * 60, 4 * 60 * 60


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def host_env(cfg, home):
    env = {
        'HOME': str(home), 'USER': os.environ.get('USER', ''), 'LOGNAME': os.environ.get('USER', ''),
        'SHELL': '/bin/zsh', 'TERM': 'xterm-256color', 'LANG': 'zh_CN.UTF-8', 'LC_ALL': 'zh_CN.UTF-8',
        'PATH': cfg.get('path', '/usr/bin:/bin:/usr/sbin:/sbin'), 'TMPDIR': str(home / 'tmp'),
    }
    for k, v in cfg.get('env', {}).items():
        env[k] = v
    for k, f in cfg.get('env_files', {}).items():
        env[k] = Path(os.path.expanduser(f)).read_text(encoding='utf-8').strip()
    (home / 'tmp').mkdir(parents=True, exist_ok=True)
    return env


def drive_claude(cfg, proj, home, log, prompt, resume):
    """一轮 Claude Code stream-json 会话；后台子 agent 未结束前保持进程存活。"""
    cmd = [os.path.expanduser(cfg['bin']), '-p', '--input-format', 'stream-json', '--output-format',
           'stream-json', '--verbose', '--permission-mode', 'bypassPermissions']
    if resume:
        cmd += ['--resume', resume]
    err = open(str(log).replace('.jsonl', '.err'), 'w')
    p = subprocess.Popen(cmd, cwd=proj, env=host_env(cfg, home), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=err, text=True, encoding='utf-8')
    p.stdin.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': prompt}},
                             ensure_ascii=False) + '\n')
    p.stdin.flush()
    q = queue.Queue()

    def reader():
        for line in p.stdout:
            q.put(line)
        q.put(None)
    threading.Thread(target=reader, daemon=True).start()
    out = open(log, 'w', encoding='utf-8')
    outstanding, closed, sid = set(), False, None
    start = last = time.time()
    while True:
        try:
            line = q.get(timeout=30)
        except queue.Empty:
            line = ''
        now = time.time()
        if line is None:
            break
        if line:
            last = now
            out.write(line)
            out.flush()
            try:
                d = json.loads(line)
            except ValueError:
                continue
            sid = d.get('session_id', sid)
            st = d.get('subtype')
            if d.get('type') == 'system' and st == 'task_started' and d.get('is_backgrounded'):
                outstanding.add(d['task_id'])
            if d.get('type') == 'system' and st == 'task_notification':
                outstanding.discard(d.get('task_id'))
            if d.get('type') == 'result' and not outstanding and not closed:
                p.stdin.close()
                closed = True
        if (now - last > IDLE_S or now - start > HARD_S) and not closed:
            out.write(json.dumps({'type': 'driver', 'event': 'timeout', 'outstanding': sorted(outstanding)}) + '\n')
            p.stdin.close()
            closed = True
        if closed and now - last > 600:
            p.kill()
            break
    p.wait(timeout=60)
    return sid


def drive_codex(cfg, proj, home, log, prompt, resume):
    if prompt.startswith('/story'):
        prompt = '$' + prompt[1:]
    base =[os.path.expanduser(cfg['bin']), 'exec', '-c', f'model="{cfg["model"]}"',
            '-c', f'projects."{proj}".trust_level="trusted"', '--json', '--skip-git-repo-check',
            '--dangerously-bypass-approvals-and-sandbox'] + cfg.get('extra_args', [])
    cmd = base + (['resume', resume, prompt] if resume else ['-C', str(proj), prompt])
    env = dict(os.environ) if cfg.get('inherit_env', True) else host_env(cfg, home)
    # 必须给独立 CODEX_HOME：用户全局配置里的插件（computer-use、浏览器）、notify 钩子和全局 skills
    # 会被基准会话继承，既污染测量，也会去操作用户的电脑。
    env.update({k: os.path.expanduser(v) for k, v in cfg.get('env', {}).items()})
    if 'CODEX_HOME' not in env or Path(env['CODEX_HOME']).resolve() == (Path.home() / '.codex').resolve():
        raise SystemExit('codex 主机必须在 hosts.json 里配置独立的 CODEX_HOME（见 README）')
    with open(log, 'w', encoding='utf-8') as out, open(str(log).replace('.jsonl', '.err'), 'w') as err:
        subprocess.run(cmd, cwd=proj, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                       timeout=HARD_S)
    sid = None
    for line in open(log, encoding='utf-8'):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('type') == 'thread.started':
            sid = d.get('thread_id')
    return sid


DRIVERS = {'claude-code': drive_claude, 'codex': drive_codex}


def committed(book):
    state = book / '追踪/_tracking-state.json'
    if not state.is_file():
        return 0
    return int(load_json(state).get('last_committed_chapter') or 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', required=True)
    ap.add_argument('--pkg', required=True)
    ap.add_argument('--host', required=True, choices=sorted(DRIVERS))
    ap.add_argument('--out', required=True)
    ap.add_argument('--label', default='')
    a = ap.parse_args()

    case = next(c for c in load_json(HERE / 'cases.json')['cases'] if c['id'] == a.case)
    hosts = load_json(BENCH_HOME / 'hosts.json')
    cfg = hosts[a.host]
    run_dir = Path(a.out).resolve() / '-'.join(x for x in (a.label, a.host, a.case) if x)
    if run_dir.exists():
        subprocess.run(['chmod', '-R', 'u+w', str(run_dir)], check=True)
        shutil.rmtree(run_dir)
    proj, home = run_dir / 'proj', run_dir / 'home'
    book = proj / case['book_dir']
    shutil.copytree(BENCH_HOME / 'fixtures' / case['fixture'], book)
    subprocess.run(['chmod', '-R', 'u+w', str(book)], check=True)  # fixture 可能是只读冻结的
    deploy.deploy(a.pkg, a.host, proj)
    subprocess.run(['git', 'init', '-q'], cwd=proj, check=True)
    home.mkdir(parents=True, exist_ok=True)

    start_ch = committed(book)
    goal = start_ch + case['chapters']
    meta = {'case': case, 'host': a.host, 'model': cfg.get('model'), 'pkg': load_json(Path(a.pkg) / 'PACKAGE.json'),
            'start_committed': start_ch, 'turns': []}
    prompts = list(case['turns'])
    sid, n = None, 0
    while prompts or (committed(book) < goal and n < len(case['turns']) + case.get('max_follow_ups', 0)):
        prompt = prompts.pop(0) if prompts else case['follow_up']
        log = run_dir / f't{n}.jsonl'
        t0 = time.time()
        sid = DRIVERS[a.host](cfg, proj, home, log, prompt, sid)
        meta['turns'].append({'prompt': prompt, 'log': log.name, 'session': sid, 'started': t0,
                              'ended': time.time(), 'committed_after': committed(book)})
        (run_dir / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
        n += 1
    meta['end_committed'] = committed(book)
    (run_dir / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    print(run_dir)


if __name__ == '__main__':
    main()
