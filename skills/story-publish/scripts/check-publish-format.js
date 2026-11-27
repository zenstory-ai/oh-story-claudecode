#!/usr/bin/env node
"use strict";

// Read-only check of a publishing-preparation document against its platform reference.
//
// The platform rules come from the reference files' frontmatter (one JSON line per work type),
// so adding a platform means adding references, not editing this script.
// FAIL: the file breaks the format contract or names an option the platform doesn't offer.
// WARN: a confirmed value the platform may reject; the author decides.

const fs = require("node:fs");
const path = require("node:path");

const REFERENCES = path.resolve(__dirname, "../references");
const FORMAT_VERSION = "1";
const HEADER_KEYS = ["格式版本", "目标平台", "作品类型", "核验"];
const TAIL = ["作品简介", "待作者确认", "待平台核实", "来源说明"];
const COVER_FIELDS = ["模式", "状态", "提示词", "图片"];
const COVER_MODES = new Set(["直接生成", "仅提示词", "暂缓"]);
const BLANK = "（不填）";
const PLACEHOLDER = new RegExp(
  "待(?:作者|平台)?确认" +
    "|(?<![^\\s（(【\\[<：:、，,；;])(?:待定|未定|暂定|暂无|草案)(?=$|[\\s）)】\\]>、，,。；;])" +
    "|(?:^|[（(【\\[<])\\s*建议|建议\\s*[：:]|建议(?:候选|草案|填|选|用|改为)" +
    "|\\b(?:TBD|TODO)\\b",
  "i"
);

function splitLines(text) {
  if (!text) return [];
  const normalized = text.replace(/\r\n?/g, "\n");
  return (normalized.endsWith("\n") ? normalized.slice(0, -1) : normalized).split("\n");
}

function readUtf8(filePath) {
  return fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
}

function frontmatter(filePath) {
  const text = readUtf8(filePath);
  const match = text.match(/^---\n([\s\S]*?)\n---\n/);
  if (!match) return {};
  const meta = {};
  for (const line of splitLines(match[1])) {
    const idx = line.indexOf(": ");
    if (idx >= 0) {
      meta[line.slice(0, idx)] = line.slice(idx + 2);
    }
  }
  return meta;
}

function loadSpec(platform, workType) {
  const entries = fs
    .readdirSync(REFERENCES)
    .filter((name) => name.endsWith(".md"))
    .sort();
  for (const name of entries) {
    const meta = frontmatter(path.join(REFERENCES, name));
    if (meta.platform === platform && Object.prototype.hasOwnProperty.call(meta, workType)) {
      return JSON.parse(meta[workType]);
    }
  }
  throw new Error(`没有「${platform}」的「${workType}」适配资料。`);
}

function loadOptions(name) {
  const text = readUtf8(path.join(REFERENCES, name));
  const blocks = text.split(/^## /m).slice(1);
  const options = new Map();
  for (const block of blocks) {
    const nl = block.indexOf("\n");
    const field = (nl >= 0 ? block.slice(0, nl) : block).trim();
    const body = nl >= 0 ? block.slice(nl + 1) : "";
    const values = body.match(/^候选值：(.+?)。?\s*$/m);
    if (values) {
      const limit = body.match(/^规则：.*?选\s*(\d+)\s*个/m);
      options.set(field, [new Set(values[1].split("、")), limit ? parseInt(limit[1], 10) : null]);
    }
  }
  if (!options.size) {
    throw new Error(`${name} 没有可读的候选值。`);
  }
  return options;
}

function unfenced(lines, start = 0, end = lines.length) {
  const kept = [];
  let fence = null;
  for (let index = start; index < end; index++) {
    const marker = lines[index].match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (
        marker &&
        marker[1][0] === fence[0] &&
        marker[1].length >= fence.length &&
        !marker[2].trim()
      ) {
        fence = null;
      }
    } else if (marker) {
      // Only enter a fenced code block when a matching closing fence exists later and the
      // opening info string is valid (prevents decorative dividers like "~~~~~·" in synopses
      // from swallowing subsequent "## " headings).
      const ch = marker[1][0];
      const len = marker[1].length;
      const info = marker[2].trim();
      const validInfo = ch === "`" ? !info.includes("`") : /^[A-Za-z0-9_+-]*$/.test(info);
      let hasClosing = false;
      if (validInfo) {
        for (let j = index + 1; j < end; j++) {
          const close = lines[j].match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
          if (close && close[1][0] === ch && close[1].length >= len) {
            hasClosing = true;
            break;
          }
        }
      }
      if (hasClosing) {
        fence = marker[1];
      } else {
        kept.push([index, lines[index]]);
      }
    } else {
      kept.push([index, lines[index]]);
    }
  }
  return kept;
}

function blockLines(lines, headings, position) {
  const start = headings[position][0] + 1;
  const end = position + 1 < headings.length ? headings[position + 1][0] : lines.length;
  return unfenced(lines, start, end)
    .map(([, line]) => line)
    .filter((line) => line.trim() !== "");
}

function parseFields(lines, where, errors) {
  const fields = new Map();
  for (const line of lines) {
    const match = line.match(/^- ([^：:]+)：(.*)$/);
    if (!match) {
      errors.push(`${where}的每个字段必须写成独立的「- 字段：值」行：${line.trim()}`);
      continue;
    }
    const name = match[1];
    const value = match[2].trim();
    if (fields.has(name)) {
      errors.push(`${where}的 ${name} 出现了不止一次。`);
    }
    if (
      !(where === "封面" && (name === "提示词" || name === "图片" || name === "状态")) &&
      /[^\s、，,]+\s*[：:]/.test(value)
    ) {
      errors.push(`${where}的 ${name} 行混入了其他字段，要拆行。`);
    }
    fields.set(name, value);
  }
  return fields;
}

function checkValue(where, name, value, errors) {
  if (value && value !== BLANK && PLACEHOLDER.test(value)) {
    errors.push(`${where}的 ${name} 写了建议或占位词；未定就留空，决定不填写「${BLANK}」。`);
  }
}

function valuesOf(value) {
  if (value === "" || value === BLANK) return [];
  return value
    .split("、")
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

function arrayEqual(a, b) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function isAlnum(ch) {
  return /^[\p{L}\p{N}]$/u.test(ch);
}

function titleWarnings(title, rule) {
  const warnings = [];
  const chars = [...title];
  if (chars.some((ch) => /\s/.test(ch))) {
    warnings.push("书名不能有空格。");
  }
  const half = rule.half_width;
  let length = 0;
  for (const ch of chars) {
    length += half && ch.codePointAt(0) < 128 ? half : 1;
  }
  if (length > rule.max) {
    warnings.push(`书名计 ${length} 个字，平台上限 ${rule.max}。`);
  }
  if (Object.prototype.hasOwnProperty.call(rule, "symbols")) {
    const seen = new Set();
    const invalid = [];
    for (const ch of chars) {
      if (!isAlnum(ch) && !/\s/.test(ch) && !rule.symbols.includes(ch) && !seen.has(ch)) {
        seen.add(ch);
        invalid.push(ch);
      }
    }
    if (invalid.length) {
      warnings.push(`书名只能用这些符号：${rule.symbols}，不能用：${invalid.join("")}`);
    }
  }
  if (rule.warn_chars) {
    const found = [...new Set(chars.filter((ch) => rule.warn_chars.includes(ch)))];
    if (found.length) {
      warnings.push(`书名含「${found.join("")}」，后台可能提示无法签约。`);
    }
  }
  if (rule.warn_emoji && /(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F)/u.test(title)) {
    warnings.push("书名含 emoji，后台可能提示无法签约。");
  }
  return warnings;
}

function check(text) {
  const lines = splitLines(String(text).replace(/^\uFEFF/, ""));
  const headings = [];
  for (const [index, line] of unfenced(lines)) {
    const match = line.match(/^(#{1,6})\s+(.*?)\s*$/);
    if (match) {
      headings.push([index, match[1].length, match[2]]);
    }
  }
  const errors = [];
  const warnings = [];

  if (!headings.length || headings[0][1] !== 1 || !headings[0][2].startsWith("书本名称：")) {
    return [["第一个标题必须是「# 书本名称：<书名>」，前面只放元信息。"], []];
  }
  const titleLine = headings[0][0];
  const headerLines = lines.slice(0, titleLine).filter((line) => line.trim() !== "");
  const headerMatches = headerLines.map((line) => line.match(/^> ([^：]+)：(.*)$/));
  if (
    headerMatches.some((m) => !m) ||
    !arrayEqual(
      headerMatches.map((m) => m[1]),
      HEADER_KEYS
    )
  ) {
    return [[`元信息必须每行一项（每行以「> 字段：值」开头），依次为：${HEADER_KEYS.join("、")}。`], []];
  }
  const meta = {};
  for (const m of headerMatches) {
    meta[m[1]] = m[2].trim();
  }
  if (meta["格式版本"] !== FORMAT_VERSION) {
    return [[`格式版本应为 ${FORMAT_VERSION}。`], []];
  }
  let spec;
  try {
    spec = loadSpec(meta["目标平台"], meta["作品类型"]);
  } catch (err) {
    return [[String(err.message || err)], []];
  }

  const colonIdx = headings[0][2].indexOf("：");
  const title = (colonIdx >= 0 ? headings[0][2].slice(colonIdx + 1) : "").trim();
  checkValue("书名", "书本名称", title, errors);
  if (title && title !== BLANK && !errors.length) {
    warnings.push(...titleWarnings(title, spec.title));
  }

  const hasSynopsis = spec.synopsis !== undefined ? spec.synopsis : true;
  const tagSectionEntries = Object.entries(spec.tag_sections);
  const sections = [
    "封面",
    ...tagSectionEntries.map(([name]) => name),
    ...(hasSynopsis ? TAIL : TAIL.slice(1)),
  ];
  const actualSubheadings = headings.slice(1);
  const sectionsMatch =
    actualSubheadings.length === sections.length &&
    actualSubheadings.every(([, level, name], i) => level === 2 && name === sections[i]);
  if (!sectionsMatch) {
    errors.push(`小节必须依次为：${sections.join(" → ")}，都用二级标题。`);
    return [errors, warnings];
  }

  const basics = parseFields(blockLines(lines, headings, 0), "基础资料", errors);
  if (!arrayEqual([...basics.keys()], spec.basics)) {
    errors.push(`基础字段必须依次为：${spec.basics.join("、")}。`);
  }
  for (const [name, value] of basics.entries()) {
    checkValue("基础资料", name, value, errors);
    const choices = spec.choices && spec.choices[name];
    if (choices && value !== "" && value !== BLANK && !choices.includes(value)) {
      errors.push(`${name} 只能是：${choices.join("、")}，不能是 ${value}。`);
    }
    const limit = spec.max_length && spec.max_length[name];
    const valueLen = [...value].length;
    if (limit && value !== BLANK && valueLen > limit) {
      warnings.push(`${name} ${valueLen} 个字，平台上限 ${limit}。`);
    }
  }

  const cover = parseFields(blockLines(lines, headings, 1), "封面", errors);
  if (!arrayEqual([...cover.keys()], COVER_FIELDS)) {
    errors.push(`封面小节字段必须依次为：${COVER_FIELDS.join("、")}。`);
  }
  const coverMode = cover.get("模式");
  if (coverMode && !COVER_MODES.has(coverMode)) {
    errors.push(`封面模式只能是：${[...COVER_MODES].sort().join("、")}，未选时留空。`);
  }
  for (const fieldName of ["状态", "提示词", "图片"]) {
    if (cover.has(fieldName)) {
      checkValue("封面", fieldName, cover.get(fieldName), errors);
    }
  }

  tagSectionEntries.forEach(([section, rule], offset) => {
    const position = offset + 2;
    const fields = parseFields(blockLines(lines, headings, position), section, errors);
    const byVal = rule.by ? basics.get(rule.by) || "" : "";
    const file = rule.files["*"] || rule.files[byVal] || null;
    let options;
    if (file === null) {
      const firstFile = Object.values(rule.files)[0];
      options = loadOptions(firstFile);
      if ([...fields.values()].some((value) => valuesOf(value).length > 0)) {
        errors.push(`填${section}前先确定${rule.by}（${Object.keys(rule.files).join("或")}）。`);
      }
    } else {
      options = loadOptions(file);
    }
    if (!arrayEqual([...fields.keys()], [...options.keys()])) {
      errors.push(`${section}字段必须依次为：${[...options.keys()].join("、")}。`);
    }
    let total = 0;
    for (const [name, value] of fields.entries()) {
      checkValue(section, name, value, errors);
      const chosen = valuesOf(value);
      total += chosen.length;
      if (!options.has(name) || file === null) continue;
      const [candidates, limit] = options.get(name);
      if (chosen.length !== new Set(chosen).size) {
        errors.push(`${section}的 ${name} 有重复值。`);
      }
      if (limit && chosen.length > limit) {
        errors.push(`${section}的 ${name} 选了 ${chosen.length} 个，最多 ${limit} 个。`);
      }
      for (const item of chosen) {
        if (!candidates.has(item)) {
          errors.push(`${section}的 ${name} 不在候选里：${item}。`);
        }
      }
    }
    if (rule.total && total > rule.total) {
      errors.push(`${section}合计 ${total} 个，最多 ${rule.total} 个。`);
    }
  });

  const synopsis = hasSynopsis
    ? blockLines(lines, headings, tagSectionEntries.length + 2).join("\n").trim()
    : BLANK;
  if (synopsis !== "" && synopsis !== BLANK) {
    checkValue("作品简介", "正文", synopsis, errors);
    const minLimit = spec.min_length && spec.min_length["作品简介"];
    const limit = spec.max_length && spec.max_length["作品简介"];
    const synLen = [...synopsis].length;
    if (minLimit && synLen < minLimit) {
      warnings.push(`作品简介 ${synLen} 字，平台下限 ${minLimit}。`);
    }
    if (limit && synLen > limit) {
      warnings.push(`作品简介 ${synLen} 字，平台上限 ${limit}。`);
    }
  }
  // Blank fields are allowed: this is a preparation document, not submission readiness.
  return [errors, warnings];
}

function main(argv = process.argv.slice(2)) {
  if (argv.length !== 1 || argv[0] === "-h" || argv[0] === "--help") {
    const out = argv.includes("-h") || argv.includes("--help") ? process.stdout : process.stderr;
    out.write("usage: check-publish-format.js <file>\n");
    return argv.includes("-h") || argv.includes("--help") ? 0 : 2;
  }
  let errors;
  let warnings;
  try {
    [errors, warnings] = check(readUtf8(argv[0]));
  } catch (err) {
    errors = [String(err.message || err)];
    warnings = [];
  }
  for (const warning of warnings) {
    process.stdout.write(`WARN: ${warning}\n`);
  }
  for (const error of errors) {
    process.stderr.write(`FAIL: ${error}\n`);
  }
  if (!errors.length) {
    process.stdout.write("PASS: 发布资料格式与平台候选项校验通过\n");
  }
  return errors.length ? 1 : 0;
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  BLANK,
  COVER_FIELDS,
  COVER_MODES,
  FORMAT_VERSION,
  HEADER_KEYS,
  REFERENCES,
  TAIL,
  check,
  loadOptions,
  loadSpec,
  main,
};
