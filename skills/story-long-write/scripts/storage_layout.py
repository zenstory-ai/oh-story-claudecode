"""Book-local body layout, chapter identity and verified layout migration."""

import argparse
import json
from pathlib import Path
import re
import sys
import hashlib
import shutil
import uuid
from datetime import datetime, timezone


class StorageError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StorageError(message)


def positive(value):
    return type(value) is int and value > 0


def volume_number(name):
    match = re.match(r"卷([1-9][0-9]*)_", name) if isinstance(name, str) else None
    return int(match[1]) if match else None


def validate(config):
    require(isinstance(config, dict), "storage config must be an object")
    mode = config.get("body_layout")
    require(type(config.get("schema_version")) is int and config["schema_version"] == 1,
            "unsupported storage schema_version")
    require(mode in ("flat", "volumes"), "body_layout must be flat or volumes")
    keys = {"schema_version", "body_layout"} | ({"volumes"} if mode == "volumes" else set())
    require(set(config) == keys, "only body layout fields are configurable")
    if mode == "volumes":
        volumes = config["volumes"]
        require(isinstance(volumes, list) and volumes, "volumes must be a nonempty list")
        names, numbers, ranges = set(), set(), []
        for item in volumes:
            require(isinstance(item, dict) and set(item) == {
                "directory", "first_chapter", "last_chapter"}, "invalid volume fields")
            name = item["directory"]
            require(isinstance(name, str) and re.fullmatch(
                r"卷[零〇一二三四五六七八九十百千万两0-9]+_[^<>:\"/\\|?*\x00-\x1f]+", name)
                and not name.endswith((".", " ")), "invalid volume directory")
            require(name.casefold() not in names, "duplicate volume directory")
            names.add(name.casefold())
            number = volume_number(name)
            if number is not None:
                require(number not in numbers, "duplicate volume number")
                numbers.add(number)
            start, end = item["first_chapter"], item["last_chapter"]
            require(positive(start) and positive(end) and start <= end, "invalid chapter range")
            require(all(end < low or start > high for low, high in ranges),
                    "overlapping volume chapter ranges")
            ranges.append((start, end))
        # 新格式按卷号数值排序，不能让卷10排在卷2前；旧中文目录仍按全书章号排序。
        return {**config, "volumes": sorted(volumes, key=lambda item: (
            volume_number(item["directory"]) if volume_number(item["directory"]) is not None
            else item["first_chapter"]))}
    return config


def load(project, required=False):
    project = Path(project)
    file = project / ".story" / "storage.json"
    require(not file.is_symlink() and not file.parent.is_symlink(), "storage metadata cannot be a symlink")
    if not file.exists():
        if required:
            return initialize_legacy_layout(project)
        return None
    try:
        return validate(json.loads(file.read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StorageError(f"invalid storage metadata: {error}") from error


def chapter_number(name):
    if "_原稿_" in name:
        return None
    match = re.fullmatch(r"第0*(\d+)章.*\.md", name)
    return int(match[1]) if match and int(match[1]) > 0 else None


def ignored_chapter_directory(name):
    return (name.startswith(".") or "_原稿_" in name
            or bool(re.match(r"^(?:备份|临时|草稿)", name))
            or bool(re.match(r"^_?(?:backups?|bak|tmp|temp|drafts?)(?:$|[_ -])", name, re.I)))


def body_directory(project, chapter, config):
    require(positive(chapter), "chapter must be >= 1")
    if config["body_layout"] == "flat":
        return Path(project) / "正文"
    for volume in config["volumes"]:
        if volume["first_chapter"] <= chapter <= volume["last_chapter"]:
            return Path(project) / "正文" / volume["directory"]
    raise StorageError(f"chapter {chapter} has no configured volume；请向作者确认所属卷和章节范围，不擅自延长最后一卷。")


def chapter_files(project, config=None):
    project = Path(project)
    if config is None:
        config = load(project)
    body = project / "正文"
    require(not body.is_symlink(), "body directory cannot be a symlink")
    def read(directory, optional=False):
        try:
            return sorted(directory.iterdir(), key=str)
        except FileNotFoundError as error:
            if optional:
                return []
            raise StorageError(f"正文目录读取失败：{directory}；可重试读取，不要据此调整章节位置。") from error
        except OSError as error:
            raise StorageError(f"正文目录读取失败：{directory}；可重试读取，不要据此调整章节位置。") from error

    files = []
    for entry in read(body, optional=True):
        if ignored_chapter_directory(entry.name):
            continue
        if entry.is_dir():
            require(not entry.is_symlink(), f"volume directory cannot be a symlink: {entry}")
            files.extend(read(entry))
        else:
            files.append(entry)
    result, seen = [], {}
    for file in files:
        number = chapter_number(file.name)
        if number is None:
            continue
        require(not file.is_symlink() and not file.parent.is_symlink(),
                f"chapter cannot be a symlink: {file}")
        if not file.is_file():
            continue
        require(number not in seen, f"duplicate chapter {number}: {seen.get(number)} / {file}；"
                "请向作者确认保留哪份，按作者决定修正后重试；不要自动移动或删除。")
        seen[number] = file
        if config is not None:
            require(file.parent == body_directory(project, number, config),
                    f"chapter {number} is outside configured layout: {file}；"
                    "请向作者说明实际位置与配置的差异，确认后再修正；不要自动移动文件或修改配置。")
        result.append(file)
    return sorted(result, key=lambda file: chapter_number(file.name))


def find_chapter(project, chapter):
    require(positive(chapter), "chapter must be >= 1")
    return next((file for file in chapter_files(project) if chapter_number(file.name) == chapter), None)


def initialize_legacy_layout(project):
    """Only register an unambiguous existing body; never invent future volume ranges."""
    project = Path(project)
    files = chapter_files(project)
    require(files, "missing .story/storage.json; 没有可判断布局的正式章节，请向作者确认不分卷或分卷后初始化。")
    body = project / "正文"
    parents = {file.parent for file in files}
    if parents == {body}:
        config = {"schema_version": 1, "body_layout": "flat"}
    else:
        require(body not in parents, "正文同时存在直属章节和分卷章节，请向作者确认目标布局后再登记；不要自动移动。")
        volumes = []
        for directory in parents:
            numbers = [chapter_number(file.name) for file in files if file.parent == directory]
            volumes.append({"directory": directory.name, "first_chapter": min(numbers), "last_chapter": max(numbers)})
        config = {"schema_version": 1, "body_layout": "volumes",
                  "volumes": sorted(volumes, key=lambda item: item["first_chapter"])}
        try:
            validate(config)
        except StorageError as error:
            raise StorageError(f"已有卷目录或章节范围无法唯一登记（{error}）；请向作者确认目录与范围，不自动改名或移动。") from error
    try:
        initialize(project, config, legacy=True)
    except FileExistsError:
        # Another invocation may have initialized the same book; read and validate it.
        return load(project, required=True)
    return config


def output_path(project, chapter, title):
    project = Path(project)
    config = load(project, required=True)
    files = chapter_files(project, config)
    require(isinstance(title, str) and title.strip() and not re.search(r'[<>:"/\\|?*\x00-\x1f]', title)
            and not title.endswith((".", " ")), "invalid chapter title")
    directory = body_directory(project, chapter, config)
    require(not directory.is_symlink(), "volume directory cannot be a symlink")
    existing = next((file for file in files if chapter_number(file.name) == chapter), None)
    return existing or directory / f"第{chapter:03d}章_{title}.md"


def initialize(project, config, *, legacy=False):
    project = Path(project).resolve()
    require(project.is_dir(), "book directory must exist")
    config = validate(config)
    if config["body_layout"] == "volumes" and not legacy:
        require(all(volume_number(item["directory"]) is not None for item in config["volumes"]),
                "新建卷目录须使用阿拉伯数字，例如 卷1_重生归来、卷2_新的开始；已有目录不自动改名。")
    file = project / ".story" / "storage.json"
    require(not file.parent.is_symlink(), "storage metadata cannot be a symlink")
    require(not file.exists() and not file.is_symlink(), "storage config already exists; migration required to change it")
    chapter_files(project, config)
    file.parent.mkdir(exist_ok=True)
    with file.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return file


def digest(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def migration_documents(project):
    """Inspect author-facing documents, never rewrite body or machine event journals."""
    for file in sorted(Path(project).rglob('*'), key=str):
        relative = file.relative_to(project)
        if any(part in {'.git', '.story', '正文', '对标', '拆文库'} or ignored_chapter_directory(part)
               for part in relative.parts[:-1]):
            continue
        if file.suffix.lower() in {'.md', '.txt', '.json', '.yaml', '.yml', '.toml'} and file.is_file():
            require(not file.is_symlink(), f"迁移不读取符号链接：{relative}")
            yield file
    if active_workspace(project):
        for file in sorted(Path(project).parent.iterdir(), key=str):
            if file.is_file() and file.suffix.lower() in {'.md', '.txt'}:
                require(not file.is_symlink(), f'工作区说明不能是符号链接：{file.name}')
                yield file


def active_workspace(project):
    project = Path(project).resolve()
    marker = project.parent/'.active-book'
    if not marker.is_file():
        return False
    return (project.parent/marker.read_text(encoding='utf-8-sig').strip()).resolve() == project


def document_key(project, file):
    return file.relative_to(project).as_posix() if file.is_relative_to(project) else '@workspace/' + file.name


def reference_file(project, relative):
    if relative.startswith('@workspace/'):
        name = relative[len('@workspace/'):]
        require(active_workspace(project) and Path(name).name == name and name not in {'.', '..'},
                '工作区资料不属于当前活跃书目')
        return project.parent/name
    file = (project/relative).resolve()
    require(file.is_relative_to(project), '资料路径超出书目录')
    return file


def reference_review_needed(source, target, mapping, text):
    directories = {Path(item['source']).parent.name for item in mapping
                   if item['source'] != item['target'] and Path(item['source']).parent != Path('正文')}
    return (any(name in text for name in directories)
            or (source['body_layout'] != target['body_layout'] and
                any(word in text for word in ('平铺', '分卷存储', '分卷目录', '存储结构', '目录结构', '正文/', '正文\\'))))


def plan_migration(project, target):
    project = Path(project).resolve()
    source = load(project)
    require(source is not None, '缺少布局配置，请先 show 自动登记既有结构，再生成迁移计划。')
    target = validate(target)
    if target['body_layout'] == 'volumes':
        require(all(volume_number(v['directory']) is not None for v in target['volumes']),
                '目标卷目录必须使用卷1_卷名等阿拉伯数字命名')
    files = chapter_files(project, source)
    mapping = []
    for file in files:
        destination = body_directory(project, chapter_number(file.name), target) / file.name
        require(not destination.parent.is_symlink(), f"目标目录不能是符号链接：{destination.parent}")
        require(destination == file or not destination.exists(), f"目标已存在，不覆盖：{destination}")
        mapping.append({'source': file.relative_to(project).as_posix(),
                        'target': destination.relative_to(project).as_posix(), 'sha256': digest(file)})
    # Full paths first; longest prefixes first prevent partial replacements.
    substitutions = {}
    for item in mapping:
        if item['source'] == item['target']:
            continue
        for old, new in [(item['source'], item['target']),
                         (str(project/item['source']), str(project/item['target']))]:
            substitutions[old] = new
            substitutions[old.replace('/', '\\')] = new.replace('/', '\\')
    updates, review = [], []
    for file in migration_documents(project):
        raw = file.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            review.append(document_key(project, file))
            continue
        new = text
        for old in sorted(substitutions, key=len, reverse=True):
            new = new.replace(old, substitutions[old])
        relative = document_key(project, file)
        if new != text and file.suffix.lower() in {'.md', '.txt'}:
            updates.append({'path': relative, 'sha256': digest(file), 'text': new})
        elif new != text:
            review.append(relative)
            new = text
        # Directory trees and prose cannot be safely inferred from literal path replacements.
        if reference_review_needed(source, target, mapping, new):
            review.append(relative)
    return {'schema_version': 1, 'project': str(project), 'source': source, 'target': target,
            'storage_sha256': digest(project/'.story/storage.json'), 'chapters': mapping,
            'document_updates': updates, 'reference_review': sorted(set(review))}


def atomic_bytes(file, raw):
    file = Path(file)
    temporary = file.with_name(file.name + '.migration-' + uuid.uuid4().hex)
    try:
        temporary.write_bytes(raw)
        temporary.replace(file)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_migration(project, backup):
    project = Path(project).resolve()
    backup = Path(backup).resolve()
    require(backup.is_relative_to(project/'.backup'), '迁移备份必须在本书 .backup 内')
    receipt = json.loads((backup/'receipt.json').read_text(encoding='utf-8'))
    plan = receipt['plan']
    require(plan['project'] == str(project), '备份不属于当前项目')
    require(load(project) == plan['target'], '迁移后的配置与目标不符')
    files = chapter_files(project, plan['target'])
    require({f.relative_to(project).as_posix() for f in files} == {i['target'] for i in plan['chapters']},
            '迁移后的章节集合与计划不一致')
    for item in plan['chapters']:
        require(digest(project/item['target']) == item['sha256'], f"正文内容改变：{item['target']}")
    unresolved = [relative for relative in plan['reference_review'] if not reference_file(project, relative).is_file()]
    completed = receipt.get('reviewed', {})
    candidates = set(plan['reference_review'])
    old_paths = [i['source'] for i in plan['chapters'] if i['source'] != i['target']]
    for file in migration_documents(project):
        relative = document_key(project, file)
        try:
            text = file.read_text(encoding='utf-8')
        except UnicodeError:
            unresolved.append(relative)
            continue
        if any(old in text.replace('\\', '/') for old in old_paths):
            unresolved.append(relative)
        if (relative in candidates or reference_review_needed(plan['source'], plan['target'], plan['chapters'], text)) and completed.get(relative) != digest(file):
            unresolved.append(relative)
    return {'status': 'needs_reference_review' if unresolved else 'complete',
            'chapter_count': len(files), 'backup': str(backup),
            'reference_review': sorted(set(unresolved))}


def migrate(project, plan):
    project = Path(project).resolve()
    lock = project/'.story/storage-migration.lock'
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError as error:
        raise StorageError('已有迁移锁，请先核对上次迁移结果，不重复执行。') from error
    try:
        with handle:
            handle.write(str(project))
        return _migrate(project, plan)
    finally:
        lock.unlink(missing_ok=True)


def _migrate(project, plan):
    project = Path(project).resolve()
    require(plan.get('project') == str(project), '迁移计划不属于当前项目')
    require('target' in plan and 'chapters' in plan, '迁移计划格式不完整')
    require(not (project/'.backup').is_symlink(), '.backup 不能是符号链接')
    require(plan == plan_migration(project, plan['target']), '计划后文件已改变，请重新生成计划')
    # Refuse links anywhere in the snapshot, including non-chapter draft folders.
    require(not any(f.is_symlink() for f in (project/'正文').rglob('*')), '正文存在符号链接，不自动迁移')
    backup = project/'.backup'/('正文迁移-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    shutil.copytree(project/'正文', backup/'正文')
    shutil.copy2(project/'.story/storage.json', backup/'storage.json')
    # Snapshot every reviewed or edited document before the first write.
    documents = {i['path'] for i in plan['document_updates']} | set(plan['reference_review'])
    for relative in documents:
        destination = backup/'关联资料'/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reference_file(project, relative), destination)
    receipt = {'status': 'prepared', 'plan': plan, 'reviewed': {}}
    (backup/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    moved = []
    try:
        for item in plan['chapters']:
            source, target = project/item['source'], project/item['target']
            if source == target:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            require(not target.exists(), f'目标已存在：{target}')
            source.rename(target)
            moved.append((source, target))
        for item in plan['document_updates']:
            atomic_bytes(reference_file(project, item['path']), item['text'].encode('utf-8'))
        atomic_bytes(project/'.story/storage.json', (json.dumps(plan['target'], ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        result = verify_migration(project, backup)
        receipt['status'] = result['status']
        (backup/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        for directory in sorted({source.parent for source, _ in moved}, key=str, reverse=True):
            if directory != project/'正文' and directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return result
    except Exception:
        for source, target in reversed(moved):
            source.parent.mkdir(parents=True, exist_ok=True)
            target.rename(source)
        for directory in sorted({target.parent for _, target in moved}, key=str, reverse=True):
            if directory != project/'正文' and directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        for relative in documents:
            shutil.copy2(backup/'关联资料'/relative, reference_file(project, relative))
        shutil.copy2(backup/'storage.json', project/'.story/storage.json')
        receipt['status'] = 'rolled_back'
        (backup/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        raise


def acknowledge_references(project, backup, files):
    project, backup = Path(project).resolve(), Path(backup).resolve()
    require(backup.is_relative_to(project/'.backup'), '备份不属于当前项目')
    receipt = json.loads((backup/'receipt.json').read_text(encoding='utf-8'))
    require(receipt['plan']['project'] == str(project), '备份不属于当前项目')
    pending = set(verify_migration(project, backup)['reference_review']) | set(receipt['plan']['reference_review'])
    for relative in files:
        require(relative in pending, f'不是待核对资料：{relative}')
        file = reference_file(project, relative)
        receipt['reviewed'][relative] = digest(file)
    atomic_bytes(backup/'receipt.json', json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8'))
    result = verify_migration(project, backup)
    receipt['status'] = result['status']
    atomic_bytes(backup/'receipt.json', json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--config", required=True, type=Path)
    commands.add_parser("show")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--chapter", required=True, type=int)
    resolve.add_argument("--title", required=True)
    plan_parser = commands.add_parser('plan-migration')
    plan_parser.add_argument('--config', required=True, type=Path)
    plan_parser.add_argument('--out', required=True, type=Path)
    migrate_parser = commands.add_parser('migrate')
    migrate_parser.add_argument('--plan', required=True, type=Path)
    verify_parser = commands.add_parser('verify-migration')
    verify_parser.add_argument('--backup', required=True, type=Path)
    review_parser = commands.add_parser('review-references')
    review_parser.add_argument('--backup', required=True, type=Path)
    review_parser.add_argument('--files', required=True, nargs='+')
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = str(initialize(args.project, json.loads(args.config.read_text(encoding="utf-8-sig"))))
        elif args.command == "show":
            result = load(args.project, required=True)
            chapter_files(args.project, result)
        elif args.command == 'plan-migration':
            result = plan_migration(args.project, json.loads(args.config.read_text(encoding='utf-8-sig')))
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            result = {'plan': str(args.out), 'chapters': len(result['chapters']), 'reference_review': result['reference_review']}
        elif args.command == 'migrate':
            result = migrate(args.project, json.loads(args.plan.read_text(encoding='utf-8-sig')))
        elif args.command == 'verify-migration':
            result = verify_migration(args.project, args.backup)
        elif args.command == 'review-references':
            result = acknowledge_references(args.project, args.backup, args.files)
        else:
            result = str(output_path(args.project, args.chapter, args.title))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
        return 0
    except (StorageError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
