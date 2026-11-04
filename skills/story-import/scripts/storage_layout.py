"""Book-local body layout and chapter identity. No file moves are performed."""

import argparse
import json
from pathlib import Path
import re
import sys


class StorageError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StorageError(message)


def positive(value):
    return type(value) is int and value > 0


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
        names, ranges = set(), []
        for item in volumes:
            require(isinstance(item, dict) and set(item) == {
                "directory", "first_chapter", "last_chapter"}, "invalid volume fields")
            name = item["directory"]
            require(isinstance(name, str) and re.fullmatch(
                r"卷[零〇一二三四五六七八九十百千万两0-9]+_[^<>:\"/\\|?*\x00-\x1f]+", name)
                and not name.endswith((".", " ")), "invalid volume directory")
            require(name.casefold() not in names, "duplicate volume directory")
            names.add(name.casefold())
            start, end = item["first_chapter"], item["last_chapter"]
            require(positive(start) and positive(end) and start <= end, "invalid chapter range")
            require(all(end < low or start > high for low, high in ranges),
                    "overlapping volume chapter ranges")
            ranges.append((start, end))
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
        initialize(project, config)
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


def initialize(project, config):
    project = Path(project).resolve()
    require(project.is_dir(), "book directory must exist")
    config = validate(config)
    file = project / ".story" / "storage.json"
    require(not file.parent.is_symlink(), "storage metadata cannot be a symlink")
    require(not file.exists() and not file.is_symlink(), "storage config already exists; migration required to change it")
    chapter_files(project, config)
    file.parent.mkdir(exist_ok=True)
    with file.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return file


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
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = str(initialize(args.project, json.loads(args.config.read_text(encoding="utf-8-sig"))))
        elif args.command == "show":
            result = load(args.project, required=True)
            chapter_files(args.project, result)
        else:
            result = str(output_path(args.project, args.chapter, args.title))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
        return 0
    except (StorageError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
