#!/usr/bin/env node
"use strict";

// Merge one host's oh-story block into a project instruction file.
//
// CLAUDE.md and the shared root AGENTS.md carry one managed block per host:
//
//     <!-- oh-story:codex 开始：重新部署时整块替换，自己的内容写在块外 -->
//     ...rendered template...
//     <!-- oh-story:codex 结束 -->
//
// Redeploying replaces only this host's block; text outside every block and
// other hosts' blocks stay byte-identical. Files written before blocks existed
// are migrated once: the oh-story title line, its intro and the sections whose
// headings the current template owns are removed and the block takes their place.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const HOSTS = Object.freeze([
  "claude-code",
  "opencode",
  "codex",
  "zcode",
  "openclaw",
  "reasonix",
  "generic",
]);
// 旧模板里有、现模板已删的受管节；迁移旧文件时一并清掉。
const RETIRED_HEADINGS = new Set(["协作规则"]);
// 名字太常见的节，旧文件里只有带 oh-story 痕迹才算受管，避免误删作者自己的同名节。
const GENERIC_HEADINGS = new Set(["Skill 路由表", "文件结构", "写作约束"]);
const LEGACY_SIGNALS = Object.freeze([
  "story-",
  "拆文库",
  "追踪/",
  "细纲",
  "作者记忆",
  "oh-story",
]);
// 各宿主模板共有的节；文件里已有别的宿主的块、块外又没有旧标题时，这些节归作者。
const SHARED_HEADINGS = new Set([
  "Skill 路由表",
  "文件结构",
  "写作约束",
  "与作者协作",
  "Compact 后恢复上下文",
]);
const TITLE_SIGNAL = "网文写作工具集";
const LEGACY_MARKER = "<!-- managed-by: story-setup -->";
const HEADING_RE = /^##\s+(.+?)\s*$/;

class MergeError extends Error {
  constructor(message) {
    super(message);
    this.name = "MergeError";
  }
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function beginMarker(host) {
  return `<!-- oh-story:${host} 开始：重新部署时整块替换，自己的内容写在块外 -->`;
}

function endMarker(host) {
  return `<!-- oh-story:${host} 结束 -->`;
}

function blockRe(host) {
  const escaped = escapeRegExp(host);
  return new RegExp(
    `^<!-- oh-story:${escaped} 开始[^\\n]*-->\\n[\\s\\S]*?^<!-- oh-story:${escaped} 结束 -->[ \\t]*$`,
    "gm"
  );
}

function splitLines(text) {
  if (!text) return [];
  const normalized = text.replace(/\r\n?/g, "\n");
  return (normalized.endsWith("\n") ? normalized.slice(0, -1) : normalized).split("\n");
}

function renderBlock(template, host, projectName) {
  const body = template
    .replace(/\r\n/g, "\n")
    .split("{项目名}")
    .join(projectName)
    .replace(/^\n+|\n+$/g, "");
  if (body.includes("<!-- oh-story:")) {
    throw new MergeError("template must not carry its own oh-story markers");
  }
  return `${beginMarker(host)}\n${body}\n${endMarker(host)}`;
}

function managedHeadings(template) {
  const headings = new Set(RETIRED_HEADINGS);
  for (const line of splitLines(template)) {
    const match = line.match(HEADING_RE);
    if (match) headings.add(match[1]);
  }
  return headings;
}

function protectedSpans(text) {
  const spans = [];
  const anyBeginRe = /^<!-- oh-story:([a-z-]+) 开始[^\n]*-->$/gm;
  let match;
  while ((match = anyBeginRe.exec(text)) !== null) {
    const host = match[1];
    const endRe = new RegExp(`^<!-- oh-story:${escapeRegExp(host)} 结束 -->[ \\t]*$`, "gm");
    endRe.lastIndex = match.index + match[0].length;
    const end = endRe.exec(text);
    if (!end) {
      throw new MergeError(`unterminated oh-story:${host} block`);
    }
    spans.push([match.index, end.index + end[0].length]);
  }
  return spans;
}

function titleRe(template) {
  const first = splitLines(template).find((line) => line.startsWith("# ")) || "";
  if (!first.includes(TITLE_SIGNAL)) return null;
  const parts = first
    .trim()
    .split("{项目名}")
    .map((part) => escapeRegExp(part));
  return new RegExp("^" + parts.join(".*") + "\\s*$");
}

function stripLegacy(text, template) {
  let headings = managedHeadings(template);
  const ownTitle = titleRe(template);
  const spans = protectedSpans(text);
  const lines = text.split("\n");
  const offsets = [];
  let pos = 0;
  for (const line of lines) {
    offsets.push(pos);
    pos += line.length + 1;
  }

  function insideBlock(index) {
    const offset = offsets[index];
    return spans.some(([start, end]) => start <= offset && offset < end);
  }

  // 旧部署的凭据：块外有 oh-story 标题行（任一宿主）或旧版托管标记。
  const outside = lines.filter((_, i) => !insideBlock(i));
  const legacyDeploy = outside.some(
    (line) => (line.startsWith("# ") && line.includes(TITLE_SIGNAL)) || line.trim() === LEGACY_MARKER
  );
  if (!legacyDeploy) {
    if (!spans.length) {
      return { text, insertAt: null, removed: [] };
    }
    // 已有别的宿主的块：共有节在先迁移的宿主那里清过了，剩下的只可能是本宿主独有的节。
    headings = new Set(
      [...headings].filter((h) => !SHARED_HEADINGS.has(h) && !RETIRED_HEADINGS.has(h))
    );
  }

  // 把块外的行切成「本宿主标题行 + 引言」与「## 节」两类片段。
  const pieces = [];
  let index = 0;
  while (index < lines.length) {
    if (insideBlock(index)) {
      index += 1;
      continue;
    }
    const line = lines[index];
    if (ownTitle !== null && ownTitle.test(line)) {
      let end = index + 1;
      while (end < lines.length && !lines[end].startsWith("#") && !insideBlock(end)) {
        end += 1;
      }
      pieces.push(["#title", index, end]);
      index = end;
      continue;
    }
    const heading = line.match(HEADING_RE);
    if (heading) {
      let end = index + 1;
      while (
        end < lines.length &&
        !lines[end].startsWith("# ") &&
        !HEADING_RE.test(lines[end]) &&
        !insideBlock(end)
      ) {
        end += 1;
      }
      pieces.push([heading[1], index, end]);
      index = end;
      continue;
    }
    index += 1;
  }

  const removedRanges = [];
  const removedTitles = [];
  for (const [title, start, end] of pieces) {
    const body = lines.slice(start, end).join("\n");
    if (title === "#title") {
      removedRanges.push([start, end]);
      removedTitles.push(lines[start].replace(/^[# ]+/, "").trim());
    } else if (
      headings.has(title) &&
      (!GENERIC_HEADINGS.has(title) || LEGACY_SIGNALS.some((signal) => body.includes(signal)))
    ) {
      removedRanges.push([start, end]);
      removedTitles.push(title);
    }
  }
  if (!removedRanges.length) {
    return { text, insertAt: null, removed: [] };
  }

  const drop = new Set();
  for (const [start, end] of removedRanges) {
    for (let i = start; i < end; i++) drop.add(i);
  }
  const first = Math.min(...removedRanges.map(([start]) => start));
  const keptBefore = [];
  for (let i = 0; i < first; i++) {
    if (!drop.has(i)) keptBefore.push(lines[i]);
  }
  const keptAfter = [];
  for (let i = first; i < lines.length; i++) {
    if (!drop.has(i)) keptAfter.push(lines[i]);
  }
  const head = keptBefore.join("\n");
  const insertAt = head.length + (keptBefore.length ? 1 : 0);
  const newText = head + (keptBefore.length ? "\n" : "") + keptAfter.join("\n");
  return { text: newText, insertAt, removed: removedTitles };
}

function tidy(text) {
  return text.replace(/\n{3,}/g, "\n\n").replace(/^\n+|\n+$/g, "") + "\n";
}

function countOccurrences(text, needle) {
  if (!text) return 0;
  let count = 0;
  let idx = 0;
  while ((idx = text.indexOf(needle, idx)) !== -1) {
    count += 1;
    idx += needle.length;
  }
  return count;
}

function merge(existing, template, host, projectName) {
  const block = renderBlock(template, host, projectName);
  const crlf = existing
    ? countOccurrences(existing, "\r\n") > countOccurrences(existing, "\n") / 2
    : false;
  const text = existing.replace(/\r\n/g, "\n");
  const report = { host, removed_legacy_sections: [] };
  let merged;

  if (!text.trim()) {
    report.status = "created";
    merged = block + "\n";
  } else {
    protectedSpans(text); // 先校验已有块都闭合
    const pattern = blockRe(host);
    const matches = [...text.matchAll(pattern)];
    if (matches.length > 1) {
      throw new MergeError(`more than one oh-story:${host} block`);
    }
    if (matches.length === 1) {
      report.status = "replaced";
      const m = matches[0];
      merged = tidy(text.slice(0, m.index) + block + text.slice(m.index + m[0].length));
    } else {
      const { text: stripped, insertAt, removed } = stripLegacy(text, template);
      if (insertAt === null) {
        report.status = "appended";
        merged = tidy(text.replace(/\n+$/g, "") + "\n\n" + block);
      } else {
        report.status = "migrated";
        report.removed_legacy_sections = removed;
        const before = stripped.slice(0, insertAt);
        const after = stripped.slice(insertAt);
        merged = tidy(
          (before.trim() ? before.replace(/\n+$/g, "") + "\n\n" : "") +
            block +
            (after.trim() ? "\n\n" + after.replace(/^\n+/g, "") : "")
        );
      }
    }
  }

  if (crlf) {
    merged = merged.replace(/\n/g, "\r\n");
  }
  return { merged, report };
}

function atomicWrite(filePath, text) {
  const dir = path.dirname(filePath);
  const base = path.basename(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = path.join(dir, `.${base}.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`);
  let fd = null;
  try {
    fd = fs.openSync(tmp, "wx", 0o644);
    fs.writeSync(fd, text, 0, "utf8");
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = null;
    fs.renameSync(tmp, filePath);
  } catch (err) {
    if (fd !== null) {
      try {
        fs.closeSync(fd);
      } catch (_) {}
    }
    try {
      fs.unlinkSync(tmp);
    } catch (_) {}
    throw err;
  }
}

function toAsciiJson(value) {
  return JSON.stringify(value).replace(/[^\x00-\x7F]/g, (ch) => {
    const code = ch.charCodeAt(0);
    return "\\u" + code.toString(16).padStart(4, "0");
  });
}

class CliUsageError extends Error {
  constructor(message) {
    super(message);
    this.name = "CliUsageError";
  }
}

const USAGE =
  "usage: merge-project-instructions.js --host <host> --template <path> --existing <path> --output <path> --project-name <name>\n";

const VALUE_FLAGS = new Set(["--host", "--template", "--existing", "--output", "--project-name"]);

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") {
      return { help: true };
    }
    let flag = arg;
    let inlineValue = null;
    const eqIdx = arg.indexOf("=");
    if (arg.startsWith("--") && eqIdx !== -1) {
      flag = arg.slice(0, eqIdx);
      inlineValue = arg.slice(eqIdx + 1);
    }
    if (VALUE_FLAGS.has(flag)) {
      const value = inlineValue !== null ? inlineValue : argv[++i];
      if (value === undefined) {
        throw new CliUsageError(`merge-project-instructions: ${flag} requires a value\n`);
      }
      args[flag.slice(2)] = value;
    } else {
      throw new CliUsageError(`merge-project-instructions: unknown argument: ${arg}\n`);
    }
  }
  const required = ["host", "template", "existing", "output", "project-name"];
  for (const key of required) {
    if (args[key] === undefined) {
      throw new CliUsageError(`merge-project-instructions: missing required option --${key}\n`);
    }
  }
  if (!HOSTS.includes(args.host)) {
    throw new CliUsageError(
      `merge-project-instructions: invalid --host ${args.host} (choose from ${HOSTS.join(", ")})\n`
    );
  }
  args.help = false;
  return args;
}

function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (err) {
    if (err instanceof CliUsageError) {
      process.stderr.write(err.message);
      return 2;
    }
    throw err;
  }
  if (args.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  try {
    const template = fs.readFileSync(args.template, "utf8");
    const existing =
      fs.existsSync(args.existing) && fs.statSync(args.existing).isFile()
        ? fs.readFileSync(args.existing, "utf8")
        : "";
    const { merged, report } = merge(existing, template, args.host, args["project-name"]);
    const unchanged =
      merged === existing && path.resolve(args.output) === path.resolve(args.existing);
    if (!unchanged) {
      atomicWrite(args.output, merged);
    }
    // 只输出 ASCII（中文转义），避免 Windows 控制台编码把报告打成乱码。
    process.stdout.write(toAsciiJson(report) + "\n");
    return 0;
  } catch (err) {
    process.stdout.write(toAsciiJson({ status: "error", error: String(err.message || err) }) + "\n");
    return 1;
  }
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  HOSTS,
  MergeError,
  atomicWrite,
  beginMarker,
  endMarker,
  main,
  merge,
  protectedSpans,
  renderBlock,
  stripLegacy,
};
