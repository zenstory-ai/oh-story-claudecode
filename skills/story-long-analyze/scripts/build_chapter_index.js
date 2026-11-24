#!/usr/bin/env node
"use strict";
/**
 * Build the mechanical, content-addressed chapter index.
 *
 * The CSV is the only source for chapter boundaries. This script never writes
 * analysis progress and never interprets story semantics.
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const PARSER_VERSION = "3";
const CSV_COLUMNS = [
  "chapter", "source_chapter", "volume", "title", "start_line", "end_line",
  "char_count", "source_locator", "status", "chapter_sha256", "source_sha256",
  "parser_version",
];
const MAX_HEADING_CHARS = 50;
const MAX_VOLUME_HEADING_CHARS = 30;
const HEADING_PREFIX = "^\\s*(?:#{1,6}\\s+)?";
const HEADING_SEP = "[\\s:：、.．\\-—【《「（(]";
const NUMBER = "〇零一二三四五六七八九十百千万两0-9";
const VOLUME_RE = new RegExp(
  `${HEADING_PREFIX}(?:第(?<number>[${NUMBER}]+)(?:卷|部(?!分))(?=$|${HEADING_SEP})|卷(?<cn_number>[${NUMBER}]+)(?=$|${HEADING_SEP}))(?<title>.*)$`
);
const COMBINED_RE = new RegExp(
  `${HEADING_PREFIX}第(?<volume>[${NUMBER}]+)(?:卷|部(?!分))` +
  `(?:\\s+|《(?<vol_title>[^》\\n]{1,16})》\\s*)` +
  `第(?<chapter>[${NUMBER}]+)` +
  `(?:章(?!至[${NUMBER}]+章)(?<title>.*)|[回节](?<title_rs>$|(?=${HEADING_SEP}).*))$`
);
const CHAPTER_RE = new RegExp(
  `${HEADING_PREFIX}第(?<number>[${NUMBER}]+)` +
  `(?:章(?<title>.*)|[回节](?<title_rs>$|(?=${HEADING_SEP}).*))$`
);
const ENGLISH_RE = new RegExp(`${HEADING_PREFIX}Chapter\\s+(?<number>[0-9]+)\\b(?<title>.*)$`, "i");
const NUMERIC_RE = new RegExp(`${HEADING_PREFIX}(?<number>[0-9]+)[.．、]\\s*(?<title>.*)$`);
const SPECIAL_RE = new RegExp(
  `${HEADING_PREFIX}(?<label>楔子|序章|引子|前言|后记|尾声|番外(?:[${NUMBER}]+)?)` +
  `(?:[\\s:：\\-—]+(?<title>.*))?\\s*$`
);
const TITLE_PREFIX_RE = /^[\s\-—:：、.．,，]+/;
const DIGITS = {
  "〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
  "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
};
const UNITS = { "十": 10, "百": 100, "千": 1000, "万": 10000 };
const REBUILD_MISMATCH_MESSAGE =
  "重建章节表时发现，%s。照这样继续，已拆好的章节会和原文错开，所以章节表没有改。请选一种：" +
  "① 换回上次拆文时用的那份原文再继续（推荐）；② 换一个新目录，整本重新拆。";

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function existsPath(filePath) {
  try {
    fs.statSync(filePath);
    return true;
  } catch {
    return false;
  }
}

function atomicWrite(filePath, data) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const base = path.basename(filePath);
  const tmp = path.join(dir, `.${base}.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`);
  let fd = null;
  try {
    fd = fs.openSync(tmp, "wx");
    const buf = Buffer.isBuffer(data) ? data : Buffer.from(data, "utf8");
    fs.writeSync(fd, buf, 0, buf.length, 0);
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = null;
    fs.renameSync(tmp, filePath);
  } catch (err) {
    if (fd !== null) {
      try { fs.closeSync(fd); } catch {}
    }
    try { fs.unlinkSync(tmp); } catch {}
    throw err;
  }
}

function decodeUtf8Strict(raw) {
  const start = raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf ? 3 : 0;
  return new TextDecoder("utf-8", { fatal: true }).decode(raw.subarray(start));
}

function decodeSource(raw) {
  try {
    return decodeUtf8Strict(raw);
  } catch {
    // Fall through to gb18030
  }
  try {
    return new TextDecoder("gb18030", { fatal: true }).decode(raw);
  } catch {
    throw new Error("source_encoding_unsupported");
  }
}

function physicalLines(text) {
  // Split on LF only so CSV line numbers agree with grep -n and editors.
  const lines = text.split("\n");
  if (lines.length && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines.map((line) => (line.endsWith("\r") ? line.slice(0, -1) : line));
}

function isAsciiDigits(raw) {
  return /^[0-9]+$/.test(raw);
}

function parseNumber(raw) {
  if (isAsciiDigits(raw)) {
    return parseInt(raw, 10);
  }
  const chars = [...raw];
  const hasUnit = chars.some((ch) => Object.prototype.hasOwnProperty.call(UNITS, ch));
  if (!hasUnit) {
    let digits = "";
    for (const ch of chars) {
      if (!Object.prototype.hasOwnProperty.call(DIGITS, ch)) {
        throw new Error(`chapter_number_invalid:${raw}`);
      }
      digits += String(DIGITS[ch]);
    }
    if (!digits) {
      throw new Error(`chapter_number_invalid:${raw}`);
    }
    return parseInt(digits, 10);
  }
  let total = 0;
  let section = 0;
  let number = 0;
  for (const ch of chars) {
    if (Object.prototype.hasOwnProperty.call(DIGITS, ch)) {
      number = DIGITS[ch];
    } else if (Object.prototype.hasOwnProperty.call(UNITS, ch)) {
      const unit = UNITS[ch];
      if (unit === 10000) {
        total += (section + number) * unit;
        section = 0;
      } else {
        section += (number || 1) * unit;
      }
      number = 0;
    } else {
      throw new Error(`chapter_number_invalid:${raw}`);
    }
  }
  return total + section + number;
}

function cleanTitle(raw, fallback) {
  const title = (raw || "").replace(TITLE_PREFIX_RE, "").trim();
  return title || fallback;
}

function codepointLength(str) {
  return [...str].length;
}

function headingCandidates(lines) {
  const explicit = [];
  const numericCandidates = [];
  let volumeNumber = null;
  let volumeTitle = "";
  for (let i = 0; i < lines.length; i += 1) {
    const lineNumber = i + 1;
    const line = lines[i];
    const stripped = line.trim();
    if (!stripped || codepointLength(stripped) > MAX_HEADING_CHARS) {
      continue;
    }
    const combined = COMBINED_RE.exec(line);
    if (combined) {
      const rawVolume = combined.groups.volume;
      const rawChapter = combined.groups.chapter;
      volumeNumber = parseNumber(rawVolume);
      const volSub = combined.groups.vol_title;
      volumeTitle = volSub ? `《${volSub.trim()}》` : `第${rawVolume}卷`;
      const rawTitle = combined.groups.title !== undefined ? combined.groups.title : combined.groups.title_rs;
      const cleaned = (rawTitle || "").replace(TITLE_PREFIX_RE, "").trim();
      const chVal = parseNumber(rawChapter);
      explicit.push({
        line: lineNumber,
        heading_kind: "combined",
        source_chapter: String(chVal),
        number_value: chVal,
        volume_number: volumeNumber,
        volume: volumeTitle,
        title: cleaned || `第${rawChapter}章`,
        bare_title: !cleaned,
      });
      continue;
    }
    const volume = VOLUME_RE.exec(line);
    if (
      volume &&
      !CHAPTER_RE.test(line) &&
      codepointLength(stripped) <= MAX_VOLUME_HEADING_CHARS &&
      !stripped.endsWith("。") &&
      !stripped.endsWith("……") &&
      !stripped.endsWith("…)")
    ) {
      const rawVolume = volume.groups.number || volume.groups.cn_number;
      volumeNumber = parseNumber(rawVolume);
      const defaultVolume = volume.groups.cn_number ? `卷${rawVolume}` : `第${rawVolume}卷`;
      volumeTitle = cleanTitle(volume.groups.title, defaultVolume);
      continue;
    }
    const chapter = CHAPTER_RE.exec(line);
    const english = ENGLISH_RE.exec(line);
    const match = chapter || english;
    if (match) {
      const rawChapter = match.groups.number;
      const value = parseNumber(rawChapter);
      const rawTitle = chapter
        ? (chapter.groups.title !== undefined ? chapter.groups.title : chapter.groups.title_rs)
        : english.groups.title;
      const cleaned = (rawTitle || "").replace(TITLE_PREFIX_RE, "").trim();
      explicit.push({
        line: lineNumber,
        heading_kind: chapter ? "chapter" : "english",
        source_chapter: String(value),
        number_value: value,
        volume_number: volumeNumber,
        volume: volumeTitle,
        title: cleaned || `第${rawChapter}章`,
        bare_title: !cleaned,
      });
      continue;
    }
    const special = SPECIAL_RE.exec(line);
    if (special) {
      const label = special.groups.label;
      explicit.push({
        line: lineNumber,
        heading_kind: "special",
        source_chapter: label,
        number_value: null,
        volume_number: volumeNumber,
        volume: volumeTitle,
        title: cleanTitle(special.groups.title || "", label),
      });
      continue;
    }
    const numeric = NUMERIC_RE.exec(line);
    if (numeric) {
      const rawChapter = numeric.groups.number;
      const value = parseNumber(rawChapter);
      numericCandidates.push({
        line: lineNumber,
        heading_kind: "numeric",
        source_chapter: String(value),
        number_value: value,
        volume_number: volumeNumber,
        volume: volumeTitle,
        title: cleanTitle(numeric.groups.title, `第${rawChapter}章`),
      });
    }
  }
  return explicit.length ? explicit : numericCandidates;
}

function identityKey(candidate) {
  return `${candidate.volume_number === null || candidate.volume_number === undefined ? "" : candidate.volume_number}\0${String(candidate.source_chapter)}`;
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function dropLeadingToc(candidates) {
  if (candidates.length < 6) {
    return candidates;
  }
  const maxPrefix = Math.min(Math.floor(candidates.length / 2), 500);
  for (let prefixCount = maxPrefix; prefixCount > 2; prefixCount -= 1) {
    const prefix = candidates.slice(0, prefixCount);
    if (prefix[0].line > 200) {
      continue;
    }
    const gaps = [];
    for (let i = 1; i < prefix.length; i += 1) {
      gaps.push(prefix[i].line - prefix[i - 1].line);
    }
    if (!gaps.length || median(gaps) > 3) {
      continue;
    }
    const signatureLength = Math.min(8, prefixCount);
    const signature = prefix.slice(0, signatureLength).map(identityKey);
    for (let bodyStart = prefixCount; bodyStart <= candidates.length - signatureLength; bodyStart += 1) {
      let equal = true;
      for (let k = 0; k < signatureLength; k += 1) {
        if (identityKey(candidates[bodyStart + k]) !== signature[k]) {
          equal = false;
          break;
        }
      }
      if (equal && candidates[bodyStart].line - prefix[prefix.length - 1].line > 3) {
        return candidates.slice(bodyStart);
      }
    }
  }
  return candidates;
}

function dropAdjacentDuplicateHeadings(candidates, lines) {
  const deduplicated = [];
  for (const candidate of candidates) {
    if (deduplicated.length) {
      const previous = deduplicated[deduplicated.length - 1];
      const gap = candidate.line - previous.line;
      const between = lines.slice(previous.line, candidate.line - 1);
      if (
        candidate.number_value !== null &&
        candidate.number_value !== undefined &&
        previous.number_value !== null &&
        previous.number_value !== undefined &&
        gap >= 1 &&
        gap <= 3 &&
        between.every((line) => !line.trim())
      ) {
        const prevBare = Boolean(previous.bare_title);
        const candBare = Boolean(candidate.bare_title);
        if (identityKey(candidate) === identityKey(previous)) {
          if (prevBare && !candBare) {
            previous.title = candidate.title;
            previous.bare_title = false;
          }
          continue;
        }
        if (
          !prevBare &&
          candBare &&
          candidate.volume_number === previous.volume_number &&
          candidate.number_value !== previous.number_value + 1
        ) {
          continue;
        }
      }
    }
    deduplicated.push(candidate);
  }
  return deduplicated;
}

function collectNumberingAnomalies(candidates) {
  const anomalies = [];
  let previous = null;
  for (let i = 0; i < candidates.length; i += 1) {
    const position = i + 1;
    const candidate = candidates[i];
    const number = candidate.number_value;
    if (number === null || number === undefined || number === 0) {
      continue;
    }
    if (previous === null) {
      previous = candidate;
      continue;
    }
    if (candidate.volume_number === previous.volume_number) {
      const expected = previous.number_value + 1;
      if (number !== expected) {
        const kind = number <= previous.number_value ? "chapter_number_duplicate" : "chapter_number_gap";
        anomalies.push({
          kind,
          position,
          line: candidate.line,
          expected,
          actual: number,
        });
      }
    } else {
      const expected = previous.number_value + 1;
      if (number !== 1 && number !== expected) {
        anomalies.push({
          kind: "volume_chapter_number_invalid",
          position,
          line: candidate.line,
          expected: `1_or_${expected}`,
          actual: number,
        });
      }
    }
    previous = candidate;
  }
  return anomalies;
}

function normalizedChapterText(lines, startLine, endLine) {
  const selected = lines.slice(startLine - 1, endLine);
  while (selected.length && !selected[selected.length - 1].trim()) {
    selected.pop();
  }
  return selected.join("\n");
}

function foldLeadingSpecials(candidates) {
  const first = candidates.findIndex(
    (item) => item.number_value !== null && item.number_value !== undefined && item.number_value >= 1
  );
  if (first <= 0) {
    return [candidates, []];
  }
  const folded = candidates
    .slice(0, first)
    .map((item) => (item.number_value === null || item.number_value === undefined ? String(item.source_chapter) : "第0章"));
  const body = { ...candidates[first], line: candidates[0].line };
  return [[body, ...candidates.slice(first + 1)], folded];
}

const NO_HEADING_AUTHOR_MESSAGE =
  "原文认不出章节标题（如「第1章」「楔子」），能看一下开头格式吗？未分章文本建议改用短篇拆文；若确认按整篇长篇拆，请明确说明后继续。";

function buildBoundaries(text, locatorPath, sourceHash, foldPrologue = false, allowSingleChapter = false) {
  const lines = physicalLines(text);
  let candidates = dropAdjacentDuplicateHeadings(dropLeadingToc(headingCandidates(lines)), lines);
  if (!candidates.length) {
    if (allowSingleChapter && text.trim()) {
      const charCount = codepointLength(text.replace(/\s+/g, ""));
      const endLine = lines.length;
      return [[{
        chapter: 1,
        source_chapter: "1",
        volume: "",
        title: "全文",
        start_line: 1,
        end_line: endLine,
        char_count: charCount,
        source_locator: `${locatorPath}:L1-L${endLine}`,
        status: charCount ? "ok" : "empty",
        chapter_sha256: sha256(Buffer.from(normalizedChapterText(lines, 1, endLine), "utf8")),
        source_sha256: sourceHash,
        parser_version: PARSER_VERSION,
      }], [], []];
    }
    throw new RebuildMismatch("chapter_heading_not_found", NO_HEADING_AUTHOR_MESSAGE);
  }
  let folded = [];
  if (foldPrologue) {
    [candidates, folded] = foldLeadingSpecials(candidates);
  }
  const anomalies = collectNumberingAnomalies(candidates);
  const rows = [];
  for (let index = 0; index < candidates.length; index += 1) {
    const candidate = candidates[index];
    const startLine = candidate.line;
    const endLine = index + 1 < candidates.length ? candidates[index + 1].line - 1 : lines.length;
    if (endLine < startLine) {
      throw new Error(`chapter_boundary_invalid:position=${index + 1}`);
    }
    const body = lines.slice(startLine, endLine).join("\n");
    const charCount = codepointLength(body.replace(/\s+/g, ""));
    rows.push({
      chapter: index + 1,
      source_chapter: candidate.source_chapter,
      volume: candidate.volume,
      title: candidate.title,
      start_line: startLine,
      end_line: endLine,
      char_count: charCount,
      source_locator: `${locatorPath}:L${startLine}-L${endLine}`,
      status: charCount ? "ok" : "empty",
      chapter_sha256: sha256(Buffer.from(normalizedChapterText(lines, startLine, endLine), "utf8")),
      source_sha256: sourceHash,
      parser_version: PARSER_VERSION,
    });
  }
  return [rows, folded, anomalies];
}

function csvEscape(value) {
  const text = value === null || value === undefined ? "" : String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function formatCsv(columns, rows) {
  const lines = [columns.map(csvEscape).join(",")];
  for (const row of rows) {
    lines.push(columns.map((col) => csvEscape(row[col])).join(","));
  }
  return lines.join("\n") + "\n";
}

function csvPayload(rows) {
  const csvStr = formatCsv(CSV_COLUMNS, rows);
  return Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(csvStr, "utf8")]);
}

function parseCsvRecords(text) {
  const clean = text.startsWith("\uFEFF") ? text.slice(1) : text;
  const records = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  let hadQuotes = false;
  let lineNum = 1;
  let i = 0;
  const len = clean.length;

  while (i < len) {
    const ch = clean[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < len && clean[i + 1] === '"') {
          field += '"';
          i += 2;
        } else {
          inQuotes = false;
          i += 1;
        }
      } else {
        if (ch === "\r") {
          if (i + 1 < len && clean[i + 1] === "\n") {
            field += "\r\n";
            i += 2;
          } else {
            field += "\r";
            i += 1;
          }
          lineNum += 1;
        } else if (ch === "\n") {
          field += "\n";
          i += 1;
          lineNum += 1;
        } else {
          field += ch;
          i += 1;
        }
      }
    } else if (ch === '"' && field === "") {
      inQuotes = true;
      hadQuotes = true;
      i += 1;
    } else if (ch === ",") {
      row.push(field);
      field = "";
      hadQuotes = false;
      i += 1;
    } else if (ch === "\r" || ch === "\n") {
      if (row.length > 0 || field !== "" || hadQuotes) {
        row.push(field);
        records.push({ fields: row, lineNum });
        row = [];
        field = "";
        hadQuotes = false;
      }
      if (ch === "\r" && i + 1 < len && clean[i + 1] === "\n") {
        i += 2;
      } else {
        i += 1;
      }
      lineNum += 1;
    } else {
      field += ch;
      i += 1;
    }
  }
  if (inQuotes) {
    throw new Error("csv_unterminated_quote");
  }
  if (field !== "" || row.length > 0 || hadQuotes) {
    row.push(field);
    records.push({ fields: row, lineNum });
  }
  return records;
}

function parseCsvRows(text) {
  const records = parseCsvRecords(text);
  if (!records.length) {
    return { fieldnames: [], rows: [], numbered: [] };
  }
  const fieldnames = records[0].fields;
  const rows = [];
  const numbered = [];
  for (let i = 1; i < records.length; i += 1) {
    const rec = records[i];
    const obj = {};
    const mismatch = rec.fields.length !== fieldnames.length;
    for (let j = 0; j < fieldnames.length; j += 1) {
      obj[fieldnames[j]] = j < rec.fields.length ? rec.fields[j] : null;
    }
    rows.push(obj);
    numbered.push({ lineNum: rec.lineNum, row: obj, mismatch });
  }
  return { fieldnames, rows, numbered };
}

function readExisting(filePath) {
  const data = fs.readFileSync(filePath);
  const text = decodeUtf8Strict(data);
  const { fieldnames, rows } = parseCsvRows(text);
  if (!rows.length || !fieldnames.includes("chapter") || !fieldnames.includes("source_chapter")) {
    throw new Error("existing_index_invalid");
  }
  return [data, rows, fieldnames];
}

function parseStrictInt(value) {
  if (typeof value === "number" && Number.isInteger(value)) {
    return value;
  }
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!/^-?\d+$/.test(trimmed)) {
    return null;
  }
  return parseInt(trimmed, 10);
}

function reusableIndex(filePath, sourceHash, locatorPath) {
  let data;
  let rows;
  let fields;
  try {
    [data, rows, fields] = readExisting(filePath);
  } catch {
    return null;
  }
  if (fields.length !== CSV_COLUMNS.length || fields.some((col, idx) => col !== CSV_COLUMNS[idx])) {
    return null;
  }
  for (let i = 0; i < rows.length; i += 1) {
    const expected = i + 1;
    const row = rows[i];
    const chapter = parseStrictInt(row.chapter);
    const startLine = parseStrictInt(row.start_line);
    const endLine = parseStrictInt(row.end_line);
    const charCount = parseStrictInt(row.char_count);
    const validNumbers =
      chapter === expected &&
      startLine !== null && startLine >= 1 &&
      endLine !== null && endLine >= startLine &&
      charCount !== null && charCount >= 0;
    if (!validNumbers || !/^[0-9a-f]{64}$/.test(row.chapter_sha256 || "")) {
      return null;
    }
    if (row.source_sha256 !== sourceHash || row.parser_version !== PARSER_VERSION) {
      return null;
    }
    if (row.status !== "ok" && row.status !== "empty") {
      return null;
    }
    if (!String(row.source_locator || "").startsWith(locatorPath + ":L")) {
      return null;
    }
  }
  return [data, rows];
}

function mappingSignature(row) {
  return `${String(row.volume ?? "")}\0${String(row.source_chapter ?? "")}`;
}

class RebuildMismatch extends Error {
  constructor(code, authorMessage) {
    super(code);
    this.authorMessage = authorMessage;
  }
}

function indexWasFolded(oldRows, newRows, foldedRows = null) {
  const oldFirst = oldRows.length ? String(oldRows[0].source_chapter ?? "") : "";
  const newFirst = newRows.length ? String(newRows[0].source_chapter ?? "") : "";
  const headingShifted =
    isAsciiDigits(oldFirst) && parseInt(oldFirst, 10) >= 1 &&
    !(isAsciiDigits(newFirst) && parseInt(newFirst, 10) >= 1);
  if (!headingShifted) return false;
  if (Array.isArray(foldedRows)) {
    return foldedRows.length > 0 && oldRows[0].chapter_sha256 === foldedRows[0].chapter_sha256;
  }
  return true;
}

function compareRebuild(oldRows, newRows) {
  const shared = Math.min(oldRows.length, newRows.length);
  for (let position = 0; position < shared; position += 1) {
    const oldRow = oldRows[position];
    if (mappingSignature(oldRow) !== mappingSignature(newRows[position])) {
      throw new RebuildMismatch(
        `chapter_mapping_ambiguous:position=${position + 1}`,
        REBUILD_MISMATCH_MESSAGE.replace(
          "%s",
          `第${position + 1}章和上次的章节表对不上（上次是「${oldRow.title ?? ""}」，这次是「${newRows[position].title}」）`
        )
      );
    }
  }
  if (newRows.length < oldRows.length) {
    throw new RebuildMismatch(
      "chapter_mapping_ambiguous:index_would_shrink",
      REBUILD_MISMATCH_MESSAGE.replace("%s", "这次认出的章节比上次少")
    );
  }
  const pending = [];
  for (let i = 0; i < newRows.length; i += 1) {
    const position = i + 1;
    if (position > oldRows.length || oldRows[position - 1].chapter_sha256 !== newRows[i].chapter_sha256) {
      pending.push(position);
    }
  }
  return pending;
}

function printHelp() {
  process.stdout.write(
    "usage: build_chapter_index.js --source SOURCE --output OUTPUT [--locator-path LOCATOR_PATH] [--rebuild] [--fold-prologue] [--allow-single-chapter]\n\n" +
    "Build the mechanical, content-addressed chapter index.\n\n" +
    "options:\n" +
    "  --source SOURCE            Source novel text path\n" +
    "  --output OUTPUT            Output chapter_index.csv path\n" +
    "  --locator-path PATH        Relative locator path under 原文/\n" +
    "  --rebuild                  Explicitly rebuild an existing index\n" +
    "  --fold-prologue            merge 楔子/序章/第0章 before the first numbered chapter into it\n" +
    "  --allow-single-chapter     treat unchaptered source text as a single chapter when user insists\n" +
    "  -h, --help                 show this help message and exit\n"
  );
}

function parseArgs(argv) {
  const args = {
    source: null,
    output: null,
    locatorPath: null,
    rebuild: false,
    foldPrologue: false,
    allowSingleChapter: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const tok = argv[i];
    if (tok === "-h" || tok === "--help") {
      printHelp();
      return { help: true };
    }
    let flag = tok;
    let inlineVal = null;
    const eqIdx = tok.indexOf("=");
    if (tok.startsWith("--") && eqIdx !== -1) {
      flag = tok.slice(0, eqIdx);
      inlineVal = tok.slice(eqIdx + 1);
    }
    const nextVal = () => {
      if (inlineVal !== null) return inlineVal;
      if (i + 1 >= argv.length) {
        throw new Error(`missing_argument:${flag}`);
      }
      i += 1;
      return argv[i];
    };
    if (flag === "--source") {
      args.source = nextVal();
    } else if (flag === "--output") {
      args.output = nextVal();
    } else if (flag === "--locator-path") {
      args.locatorPath = nextVal();
    } else if (flag === "--rebuild") {
      args.rebuild = true;
    } else if (flag === "--fold-prologue") {
      args.foldPrologue = true;
    } else if (flag === "--allow-single-chapter") {
      args.allowSingleChapter = true;
    } else {
      throw new Error(`unknown_argument:${tok}`);
    }
  }
  if (!args.source || !args.output) {
    throw new Error("missing_required_arguments:--source and --output are required");
  }
  return args;
}

function fail(error, authorMessage = null) {
  const payload = { ok: false, error };
  if (authorMessage) {
    payload.author_message = authorMessage;
  }
  process.stdout.write(JSON.stringify(payload) + "\n");
  return 2;
}

function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = parseArgs(argv);
    if (args.help) {
      return 0;
    }
  } catch (err) {
    process.stderr.write(`error: ${err.message}\n`);
    return 2;
  }

  try {
    if (!isFile(args.source)) {
      throw new Error(`source_not_found:${args.source}`);
    }
    const raw = fs.readFileSync(args.source);
    const sourceHash = sha256(raw);
    const locatorPath = (args.locatorPath || `原文/${path.basename(args.source)}`).replace(/\\/g, "/");
    if (!locatorPath.startsWith("原文/") || locatorPath.split("/").includes("..")) {
      throw new Error("locator_path_must_stay_under_original");
    }
    if (existsPath(args.output) && !isFile(args.output)) {
      throw new Error(`output_is_not_file:${args.output}`);
    }
    if (isFile(args.output) && !args.rebuild) {
      const reusable = reusableIndex(args.output, sourceHash, locatorPath);
      if (reusable === null) {
        return fail(
          "existing_index_incompatible",
          "原文和上次建章节表时不一样了（内容、文件名或识别规则变了）。确认原文就是要拆的版本后，再重建章节表。"
        );
      }
      const [, existingRows] = reusable;
      process.stdout.write(JSON.stringify({
        ok: true,
        reused: true,
        parsed_source: false,
        chapters: existingRows.length,
        pending_chapters: [],
      }) + "\n");
      return 0;
    }
    const text = decodeSource(raw);
    let [rows, folded, anomalies] = buildBoundaries(text, locatorPath, sourceHash, args.foldPrologue, args.allowSingleChapter);
    let pending = rows.map((_, idx) => idx + 1);
    let oldCount = 0;
    if (isFile(args.output)) {
      const [, oldRows] = readExisting(args.output);
      oldCount = oldRows.length;
      if (!args.foldPrologue && indexWasFolded(oldRows, rows)) {
        const [foldedRows, foldedPrologue, foldedAnomalies] = buildBoundaries(
          text,
          locatorPath,
          sourceHash,
          true,
          args.allowSingleChapter
        );
        if (indexWasFolded(oldRows, rows, foldedRows)) {
          [rows, folded, anomalies] = [foldedRows, foldedPrologue, foldedAnomalies];
        }
      }
      pending = compareRebuild(oldRows, rows);
    } else {
      const { legacyMappingCheck } = require("./inspect_existing_assets.js");
      const mapping = legacyMappingCheck(path.dirname(args.output), rows);
      if (mapping) {
        return fail(
          `chapter_mapping_ambiguous:${mapping.code}:legacy_chapters=${mapping.legacy_chapters.join(",")}`,
          String(mapping.author_message)
        );
      }
    }
    const data = csvPayload(rows);
    if (!isFile(args.output) || !fs.readFileSync(args.output).equals(data)) {
      atomicWrite(args.output, data);
    }
    process.stdout.write(JSON.stringify({
      ok: true,
      reused: false,
      parsed_source: true,
      rebuilt: Boolean(oldCount),
      chapters: rows.length,
      empty_chapters: rows.filter((row) => row.status === "empty").length,
      pending_chapters: pending,
      unchanged_chapters: rows.length - pending.length,
      source_sha256: sourceHash,
      parser_version: PARSER_VERSION,
      folded_into_first_chapter: folded,
      numbering_anomalies: anomalies,
    }) + "\n");
    return 0;
  } catch (err) {
    if (err instanceof RebuildMismatch) {
      return fail(err.message, err.authorMessage);
    }
    return fail(err && err.message ? err.message : String(err));
  }
}

module.exports = {
  PARSER_VERSION,
  CSV_COLUMNS,
  sha256,
  isFile,
  existsPath,
  atomicWrite,
  decodeUtf8Strict,
  decodeSource,
  physicalLines,
  isAsciiDigits,
  parseNumber,
  parse_number: parseNumber,
  cleanTitle,
  headingCandidates,
  dropLeadingToc,
  dropAdjacentDuplicateHeadings,
  collectNumberingAnomalies,
  normalizedChapterText,
  foldLeadingSpecials,
  buildBoundaries,
  csvEscape,
  formatCsv,
  csvPayload,
  parseCsvRecords,
  parseCsvRows,
  parseStrictInt,
  readExisting,
  reusableIndex,
  indexWasFolded,
  compareRebuild,
  RebuildMismatch,
  main,
};

if (require.main === module) {
  process.exitCode = main();
}
