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
        require(not required, "missing .story/storage.json; confirm and initialize body layout first")
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


def body_directory(project, chapter, config):
    require(positive(chapter), "chapter must be >= 1")
    if config["body_layout"] == "flat":
        return Path(project) / "正文"
    for volume in config["volumes"]:
        if volume["first_chapter"] <= chapter <= volume["last_chapter"]:
            return Path(project) / "正文" / volume["directory"]
    raise StorageError(f"chapter {chapter} has no configured volume")


def chapter_files(project, config=None):
    project = Path(project)
    if config is None:
        config = load(project)
    body = project / "正文"
    require(not body.is_symlink(), "body directory cannot be a symlink")
    files = sorted((*body.glob("*.md"), *body.glob("*/*.md")), key=str)
    result, seen = [], {}
    for file in files:
        number = chapter_number(file.name)
        if number is None or file.parent.name.startswith("."):
            continue
        require(not file.is_symlink() and not file.parent.is_symlink(),
                f"chapter cannot be a symlink: {file}")
        if not file.is_file():
            continue
        require(number not in seen, f"duplicate chapter {number}: {seen.get(number)} / {file}")
        seen[number] = file
        if config is not None:
            require(file.parent == body_directory(project, number, config),
                    f"chapter {number} is outside configured layout: {file}; migrate before writing")
        result.append(file)
    return sorted(result, key=lambda file: chapter_number(file.name))


def find_chapter(project, chapter):
    require(positive(chapter), "chapter must be >= 1")
    return next((file for file in chapter_files(project) if chapter_number(file.name) == chapter), None)


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
