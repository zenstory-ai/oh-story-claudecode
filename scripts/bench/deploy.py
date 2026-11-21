#!/usr/bin/env python3
"""把某个版本的 skill 包确定性地部署进一个书项目，供基准会话使用。

与 story-setup 的部署清单同构（Claude Code / Codex 两端），但不经过模型：
同一版本、同一 fixture 每次部署出来的字节相同，版本间对比才有意义。

用法：
  deploy.py export --ref v0.7.11 --out <pkg目录>        # 从 git 导出一份包
  deploy.py deploy --pkg <pkg目录> --host claude-code --proj <项目目录>
"""
import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def export(ref, out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.NamedTemporaryFile(suffix='.tar') as tmp:
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar', '-o', tmp.name, ref,
                        'skills', 'scripts/current-contract.json'], check=True)
        with tarfile.open(tmp.name) as tar:
            tar.extractall(out)
    sha = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', ref], check=True,
                         capture_output=True, text=True).stdout.strip()
    (out / 'PACKAGE.json').write_text(json.dumps({'ref': ref, 'sha': sha}, ensure_ascii=False) + '\n',
                                      encoding='utf-8')
    print(out)


def copytree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.zip'))


def render(tmpl, proj):
    return tmpl.read_text(encoding='utf-8').replace('{项目名}', proj.name)


def instructions(pkg, host, tmpl, path, proj):
    """项目指令文件：包里有管理块合并脚本就照 story-setup 合并（多端共用一份文件），旧包按原样渲染。"""
    merger_js = pkg / 'skills/story-setup/scripts/merge-project-instructions.js'
    merger_py = pkg / 'skills/story-setup/scripts/merge-project-instructions.py'
    if merger_js.is_file():
        cmd = ['node', str(merger_js)]
    elif merger_py.is_file():
        cmd = [sys.executable, str(merger_py)]
    else:
        path.write_text(render(tmpl, proj), encoding='utf-8')
        return
    subprocess.run([*cmd, '--host', host, '--template', str(tmpl),
                    '--existing', str(path), '--output', str(path), '--project-name', proj.name],
                   check=True, stdout=subprocess.DEVNULL)


def sentinel(proj, contract, target, refs_dir):
    """多端部署进同一项目时 target_cli 逗号合并，references_dir 保留先部署的那端。"""
    path = proj / '.story-deployed'
    old = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition(':')
            if sep:
                old[key.strip()] = value.strip()
    targets = [t for t in old.get('target_cli', '').split(',') if t]
    if target not in targets:
        targets.append(target)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    path.write_text(
        f"deployed_at: {stamp}\n"
        f"agents_version: {contract['agents_version']}\n"
        f"setup_skill_version: {contract['setup_skill_version']}\n"
        f"target_cli: {','.join(targets)}\n"
        "resolver_strategy: project-local-skill-reference\n"
        f"references_dir: {old.get('references_dir') or refs_dir}\n", encoding='utf-8')


def deploy_claude(pkg, proj, contract):
    skills, setup = pkg / 'skills', pkg / 'skills/story-setup'
    tpl = setup / 'references/templates'
    claude = proj / '.claude'
    claude.mkdir(parents=True, exist_ok=True)
    for skill in sorted(p for p in skills.iterdir() if (p / 'SKILL.md').is_file()):
        copytree(skill, claude / 'skills' / skill.name)
    instructions(pkg, 'claude-code', tpl / 'CLAUDE.md.tmpl', proj / 'CLAUDE.md', proj)
    copytree(tpl / 'hooks', claude / 'hooks')
    for sh in (claude / 'hooks').glob('*.sh'):
        sh.chmod(0o755)
    for sub in ('rules', 'agents'):
        (claude / sub).mkdir(exist_ok=True)
        for f in (tpl / sub).glob('*.md'):
            shutil.copy2(f, claude / sub / f.name)
    settings = claude / 'settings.local.json'
    merge_hooks_js = setup / 'scripts/merge-hooks.js'
    if merge_hooks_js.is_file():
        merge_cmd = ['node', str(merge_hooks_js), '--host', 'claude']
    else:
        merge_cmd = [sys.executable, str(setup / 'scripts/merge-claude-settings.py')]
    subprocess.run([*merge_cmd,
                    '--existing', str(settings), '--template', str(tpl / 'settings-hooks.json'),
                    '--output', str(settings)], check=True, stdout=subprocess.DEVNULL)
    sentinel(proj, contract, 'claude-code', '.claude/skills/story-setup/references/agent-references')


def deploy_codex(pkg, proj, contract):
    skills, setup = pkg / 'skills', pkg / 'skills/story-setup'
    ref = setup / 'references/codex'
    for skill in sorted(p for p in skills.iterdir() if (p / 'SKILL.md').is_file()):
        copytree(skill, proj / '.agents/skills' / skill.name)
    instructions(pkg, 'codex', ref / 'AGENTS.md.tmpl', proj / 'AGENTS.md', proj)
    codex = proj / '.codex'
    (codex / 'agents').mkdir(parents=True, exist_ok=True)
    for f in (ref / 'agents').glob('*.toml'):
        shutil.copy2(f, codex / 'agents' / f.name)
    (codex / 'hooks').mkdir(exist_ok=True)
    for name in ('story_codex_hook.js', 'story_hook_core.js', 'run-story-hook.sh', 'run-story-hook.cmd'):
        if (ref / 'hooks' / name).is_file():
            shutil.copy2(ref / 'hooks' / name, codex / 'hooks' / name)
    if (ref / 'hooks' / 'story_codex_hook.py').is_file():
        shutil.copy2(ref / 'hooks' / 'story_codex_hook.py', codex / 'hooks' / 'story_codex_hook.py')
    (codex / 'hooks/run-story-hook.sh').chmod(0o755)
    merge_hooks_js = setup / 'scripts/merge-hooks.js'
    if merge_hooks_js.is_file():
        merge_cmd = ['node', str(merge_hooks_js), '--host', 'codex']
    else:
        merge_cmd = [sys.executable, str(setup / 'scripts/merge-codex-hooks.py')]
    subprocess.run([*merge_cmd,
                    '--existing', str(codex / 'hooks.json'), '--template', str(ref / 'hooks/hooks.json'),
                    '--output', str(codex / 'hooks.json')], check=True, stdout=subprocess.DEVNULL)
    copytree(setup / 'references/agent-references', codex / 'skills/story-setup/references/agent-references')
    sentinel(proj, contract, 'codex', '.codex/skills/story-setup/references/agent-references')


def deploy(pkg, host, proj):
    pkg, proj = Path(pkg).resolve(), Path(proj).resolve()
    contract = json.loads((pkg / 'scripts/current-contract.json').read_text(encoding='utf-8'))
    proj.mkdir(parents=True, exist_ok=True)
    {'claude-code': deploy_claude, 'codex': deploy_codex}[host](pkg, proj, contract)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export')
    e.add_argument('--ref', required=True)
    e.add_argument('--out', required=True)
    d = sub.add_parser('deploy')
    d.add_argument('--pkg', required=True)
    d.add_argument('--host', required=True, choices=['claude-code', 'codex'])
    d.add_argument('--proj', required=True)
    a = ap.parse_args()
    if a.cmd == 'export':
        export(a.ref, a.out)
    else:
        deploy(a.pkg, a.host, a.proj)


if __name__ == '__main__':
    main()
