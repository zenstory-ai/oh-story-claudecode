#!/usr/bin/env python3
"""Run isolated real story-deslop cases; preserve outputs and bounded execution evidence.

Explicit opt-in, requires an authenticated Codex CLI; never runs in CI by default.
Uses the installed CLI default model without overriding it; CLI version and rule hashes are recorded.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_NAMES = ('正文.md', '报告.md', 'final.txt')
REQUIRED_ARTIFACTS = ('正文.md', '报告.md')
# Failure evidence retains only the last 16 Ki characters, enough for the final
# CLI diagnostic without allowing an unbounded JSON artifact.
STDOUT_TAIL_CHARS = 16_384

def as_text(value):
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)

def event_evidence(stdout):
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get('item', {})
        if (event.get('type') == 'item.completed' and isinstance(item, dict)
                and item.get('type') == 'command_execution'):
            events.append({'command': item.get('command'), 'exit_code': item.get('exit_code')})
        elif event.get('type') in ('turn.completed', 'turn.failed', 'error'):
            events.append(event)
    return events

def preserve_artifacts(work, target):
    artifacts = {}
    for name in ARTIFACT_NAMES:
        source = work / name
        if not source.is_file():
            continue
        destination = target / name
        shutil.copyfile(source, destination)
        artifacts[name] = {
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    return artifacts

def bounded_stdout_tail(stdout, work):
    sanitized = as_text(stdout).replace(str(work), '{workspace}')
    truncated = len(sanitized) > STDOUT_TAIL_CHARS
    return {
        'text': sanitized[-STDOUT_TAIL_CHARS:],
        'truncated': truncated,
        'max_chars': STDOUT_TAIL_CHARS,
    }

def run_cli(command, timeout):
    # Codex may use a Node launcher. Kill the whole POSIX process group on timeout.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, text=True,
                          start_new_session=os.name != 'nt') as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.kill()
            stdout, stderr = process.communicate()
            error.stdout = as_text(stdout or error.stdout)
            error.output = error.stdout
            error.stderr = as_text(stderr or error.stderr)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

def run_case(source, case, dest, run_id, timeout):
    target = dest / run_id
    target.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='story-deslop-eval-') as tmp:
        work = Path(tmp)
        skill = work / '.agents/skills/story-deslop'
        shutil.copytree(source / 'skills/story-deslop', skill)
        shutil.copyfile(case, work / '正文.md')
        prompt = ('请实际执行 $story-deslop，处理当前项目的 正文.md。这是虚构网文片段，'
                  '只去AI味，不续写，不增加人物、事件或后续义务，保留事实、结局和必要情绪。'
                  '不安装环境；项目没有专业agent时按skill明确报告solo fallback。'
                  '完整读取当前skill及其所需参考，执行检测和收尾，直接修改正文.md；'
                  '报告另存报告.md。不要向用户提问。')
        command = ['codex', 'exec', '--ephemeral', '--ignore-user-config', '--skip-git-repo-check',
                   '-s', 'workspace-write', '-C', str(work), '--json', '-o', str(work / 'final.txt'), prompt]
        meta = {'case': case.name, 'run': run_id,
                'input_sha256': hashlib.sha256(case.read_bytes()).hexdigest(),
                'skill_sha256': hashlib.sha256((skill / 'SKILL.md').read_bytes()).hexdigest(),
                'reference_sha256': {str(p.relative_to(skill)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted((skill / 'references').rglob('*')) if p.is_file()}}
        stdout = ''
        stderr = ''
        try:
            result = run_cli(command, timeout)
            meta['exit_code'] = result.returncode
            stdout = as_text(result.stdout)
            stderr = as_text(result.stderr)
        except subprocess.TimeoutExpired as error:
            meta.update({'exit_code': None, 'error': 'timeout', 'seconds': timeout})
            stdout = as_text(error.stdout)
            stderr = as_text(error.stderr)
        except Exception as error:
            meta.update({
                'exit_code': None,
                'error': 'runner-error',
                'exception': type(error).__name__,
            })
            stderr = str(error)

        meta['commands'] = event_evidence(stdout)
        meta['stderr'] = stderr.replace(str(work), '{workspace}')
        meta['artifacts'] = preserve_artifacts(work, target)
        if '正文.md' in meta['artifacts']:
            meta['output_sha256'] = meta['artifacts']['正文.md']['sha256']
            meta['changed'] = meta['output_sha256'] != meta['input_sha256']
        else:
            meta['output_sha256'] = None
            meta['changed'] = False

        missing = [name for name in REQUIRED_ARTIFACTS if name not in meta['artifacts']]
        empty = []
        invalid = []
        for name in REQUIRED_ARTIFACTS:
            if name not in meta['artifacts']:
                continue
            try:
                if not (target / name).read_text(encoding='utf-8').strip():
                    empty.append(name)
            except UnicodeDecodeError:
                invalid.append(name)
        if missing:
            meta['missing_outputs'] = missing
            meta.setdefault('error', 'missing-output')
        if empty:
            meta['empty_outputs'] = empty
            meta.setdefault('error', 'empty-output')
        if invalid:
            meta['invalid_outputs'] = invalid
            meta.setdefault('error', 'invalid-output')
        event_types = {event['type'] for event in meta['commands'] if 'type' in event}
        if event_types & {'turn.failed', 'error'}:
            meta.setdefault('error', 'failed-turn')
        elif 'turn.completed' not in event_types:
            meta.setdefault('error', 'incomplete-turn')
        # A no-op can be the correct edit. Execution completeness is not a quality verdict.
        meta['completed'] = meta['exit_code'] == 0 and 'error' not in meta
        if meta['exit_code'] != 0 or 'error' in meta:
            meta['stdout_tail'] = bounded_stdout_tail(stdout, work)

        serialized = json.dumps(meta, ensure_ascii=False, indent=2)
        (target / 'run.json').write_text(serialized.replace(str(work), '{workspace}')+'\n')
        summary = {'run': run_id, 'exit_code': meta['exit_code'],
                   'completed': meta['completed'], 'changed': meta['changed']}
        if 'error' in meta:
            summary['error'] = meta['error']
        return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replicates', type=int, default=2)
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if min(args.replicates, args.jobs, args.timeout) < 1:
        parser.error('replicates, jobs and timeout must be positive')
    cases = sorted((ROOT / 'tests/fixtures/deslop-eval').glob('*.md'))
    if not cases:
        parser.error(f'no evaluation cases found in {ROOT / "tests/fixtures/deslop-eval"}')
    args.output.mkdir(parents=True, exist_ok=True)
    tasks = [(case, f'{case.stem}-{n}') for case in cases for n in range(1, args.replicates + 1)]
    # Freeze one arm before starting: concurrent repository edits must not mix rule versions.
    with tempfile.TemporaryDirectory(prefix='story-deslop-arm-') as tmp:
        source = Path(tmp)
        shutil.copytree(args.source_root / 'skills/story-deslop', source / 'skills/story-deslop')
        version = subprocess.run(['codex', '--version'], capture_output=True, text=True, check=True).stdout.strip()
        (args.output / 'arm.json').write_text(json.dumps({
            'cli_version': version, 'model': 'CLI default (not overridden)',
            'replicates': args.replicates,
            'files_sha256': {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(source.rglob('*')) if p.is_file()},
        }, ensure_ascii=False, indent=2)+'\n')
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(run_case, source, case, args.output, ident, args.timeout) for case, ident in tasks]
            results = [future.result() for future in futures]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(not row['completed'] for row in results))

if __name__ == '__main__':
    raise SystemExit(main())
