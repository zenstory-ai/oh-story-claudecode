#!/usr/bin/env node
"use strict";
/**
 * Inspect reusable long-analysis assets without changing user files.
 *
 * Only the upstream directory contract is recognized: `章节/第N章_摘要.md`,
 * golden-three-chapter analyses, and the aggregate files. Missing chapters are
 * reported exactly so a run only fills gaps.
 */

const fs = require("fs");
const path = require("path");
const { decodeUtf8Strict, parseCsvRows, parseStrictInt, isAsciiDigits } = require("./build_chapter_index.js");

const SUMMARY_RE = /^第0*(\d+)章_摘要\.md$/;
const GOLDEN_RE = /^第0*(\d+)章_深度拆解\.md$/;
const SCHEMA_RE = /schema_version\s*[：:]\s*v?(\d+)/i;
const TOTAL_RE = /总章数\s*(?:[：:]|\|)\s*(\d+)/;
const TOTAL_FALLBACK_RE = /总章数\s+(\d+)\s*章?/;
const TABLE_CHAPTER_TOTAL_RE = /\|\s*章节数\s*\|\s*(\d+)\s*(?:章)?\s*\|/;
const COVERAGE_TOTAL_RE = /(?:输入覆盖\s*[：:]\s*全文|精读覆盖\s*[：:]\s*第\s*1\s*[—–-]\s*)(\d+)\s*章/;
const FINAL_RE = /(?:最终状态|当前状态)\s*[：:]\s*([a-z0-9_]+)/i;
const SOURCE_HASH_RE = /(?:输入版本|SHA-256|source_sha256)\s*(?:[：:]|\|)\s*([0-9a-f]{64})/i;
const PROJECTION_RE = /<!--\s*story-long-analyze:projection\s+runtime=(?<runtime>[^\s]+)\s+source=(?<source>[^\s]+)(?:\s+[^>]*?)?\s*-->/;
const STATE_START = "<!-- story-long-analyze:runtime-state:start -->";
const STATE_END = "<!-- story-long-analyze:runtime-state:end -->";
const BOUNDARY_HEADING_RE = /^#{1,6}\s*章节边界/;
const TITLE_LABEL_RE = new RegExp(
  "^\\s*(?:第(?<number>[〇零一二三四五六七八九十百千万两0-9]+)章|第[〇零一二三四五六七八九十百千万两0-9]+[卷回节]" +
  "|卷[〇零一二三四五六七八九十百千万两0-9]+|Chapter\\s*(?<english>[0-9]+)|(?<numeric>[0-9]+)[.、](?![0-9])" +
  "|(?<special>楔子|序章|引子|前言|后记|尾声|番外[〇零一二三四五六七八九十百千万两0-9]*))",
  "i"
);
const TITLE_NOTE_RE = /[(\[【〔〖][^()\[\]【】〔〕〖〗]*[)\]】〕〗]\s*$/;
const TITLE_NOISE_RE = /[\s\-—:：、.,;!?\"“”'‘’《》「」『』()\[\]【】〔〕〖〗]+/g;

function toPosix(filePath) {
  return String(filePath).replace(/\\/g, "/");
}

function resolveReal(targetPath) {
  try {
    return fs.realpathSync(targetPath);
  } catch {
    return path.resolve(targetPath);
  }
}

function isDir(dirPath) {
  try {
    return fs.statSync(dirPath).isDirectory();
  } catch {
    return false;
  }
}

function nonempty(filePath) {
  try {
    const stat = fs.statSync(filePath);
    return stat.isFile() && stat.size > 0;
  } catch {
    return false;
  }
}

function anyNonempty(paths) {
  for (const p of paths) {
    if (nonempty(p)) return true;
  }
  return false;
}

function readText(filePath) {
  if (!nonempty(filePath)) {
    return null;
  }
  try {
    return decodeUtf8Strict(fs.readFileSync(filePath)).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  } catch {
    return null;
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

function readProgress(filePath) {
  const text = readText(filePath);
  if (text === null) {
    return [null, null, existsPath(filePath) ? "unreadable" : null];
  }
  const schemaMatch = SCHEMA_RE.exec(text);
  const totalMatch = TOTAL_RE.exec(text) || COVERAGE_TOTAL_RE.exec(text);
  const finalMatch = FINAL_RE.exec(text);
  return [
    schemaMatch ? parseInt(schemaMatch[1], 10) : null,
    totalMatch ? parseInt(totalMatch[1], 10) : null,
    finalMatch ? finalMatch[1].toLowerCase() : null,
  ];
}

function readDeclaredTotal(paths) {
  for (const p of paths) {
    const text = readText(p);
    if (text === null) continue;
    const match = TOTAL_RE.exec(text) || TOTAL_FALLBACK_RE.exec(text) || TABLE_CHAPTER_TOTAL_RE.exec(text);
    if (match && parseInt(match[1], 10) > 0) {
      return [parseInt(match[1], 10), toPosix(p)];
    }
  }
  return [null, null];
}

function readSourceHash(paths) {
  for (const p of paths) {
    const text = readText(p);
    if (text === null) continue;
    const match = SOURCE_HASH_RE.exec(text);
    if (match) {
      return [match[1].toLowerCase(), toPosix(p)];
    }
  }
  return [null, null];
}

function readIndexChapters(filePath) {
  if (!nonempty(filePath)) {
    return [[], []];
  }
  const errors = [];
  const chapters = [];
  try {
    const text = decodeUtf8Strict(fs.readFileSync(filePath));
    const { fieldnames, rows } = parseCsvRows(text);
    const required = ["chapter", "char_count", "source_locator", "status", "source_sha256"];
    const fieldSet = new Set(fieldnames);
    const missing = required.filter((col) => !fieldSet.has(col)).sort();
    if (missing.length) {
      return [[], [`chapter_index.csv 缺列：${missing.join(", ")}`]];
    }
    for (let i = 0; i < rows.length; i += 1) {
      const rowNumber = i + 2;
      const val = parseStrictInt(rows[i].chapter);
      if (val === null) {
        errors.push(`chapter_index.csv 第 ${rowNumber} 行章号无效`);
      } else {
        chapters.push(val);
      }
    }
  } catch (err) {
    return [[], [`chapter_index.csv 不可读：${err.message}`]];
  }
  const unique = Array.from(new Set(chapters)).sort((a, b) => a - b);
  if (chapters.length !== unique.length) {
    errors.push("chapter_index.csv 存在重复章号");
  }
  if (unique.length) {
    const maxCh = unique[unique.length - 1];
    let continuous = unique.length === maxCh;
    if (continuous) {
      for (let i = 0; i < unique.length; i += 1) {
        if (unique[i] !== i + 1) {
          continuous = false;
          break;
        }
      }
    }
    if (!continuous) {
      errors.push("chapter_index.csv 章号不连续");
    }
  }
  return [unique, errors];
}

function readIndexIdentities(filePath) {
  if (!nonempty(filePath)) {
    return [];
  }
  try {
    const text = decodeUtf8Strict(fs.readFileSync(filePath));
    return parseCsvRows(text).rows.map((row) => ({ ...row }));
  } catch {
    return [];
  }
}

function countOccurrences(haystack, needle) {
  let count = 0;
  let pos = 0;
  while (true) {
    const idx = haystack.indexOf(needle, pos);
    if (idx === -1) break;
    count += 1;
    pos = idx + needle.length;
  }
  return count;
}

function readManagedStages(text) {
  if (!text || countOccurrences(text, STATE_START) !== 1 || countOccurrences(text, STATE_END) !== 1) {
    return [false, {}];
  }
  const startIdx = text.indexOf(STATE_START);
  const endIdx = text.indexOf(STATE_END, startIdx + STATE_START.length);
  if (endIdx === -1) {
    return [false, {}];
  }
  const block = text.slice(startIdx + STATE_START.length, endIdx);
  const stages = {};
  let section = null;
  for (const line of block.split("\n")) {
    const stripped = line.trim();
    if (stripped === "### 阶段状态") {
      section = "stages";
      continue;
    }
    if (line.startsWith("### ")) {
      section = null;
      continue;
    }
    if (section !== "stages" || !line.trimStart().startsWith("|")) {
      continue;
    }
    const cells = stripped.replace(/^\|+|\|+$/g, "").split("|").map((cell) => cell.trim());
    if (cells.length >= 3 && cells[0] !== "阶段" && cells[0] !== "---") {
      stages[cells[0].toLowerCase()] = { status: cells[1].toLowerCase(), output: cells[2] };
    }
  }
  return [true, stages];
}

function collectNumberedFiles(directory, pattern) {
  const chapters = [];
  const sources = new Map();
  const duplicates = [];
  if (!isDir(directory)) {
    return [chapters, sources, duplicates];
  }
  const entries = fs.readdirSync(directory).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  for (const name of entries) {
    const match = pattern.exec(name);
    if (!match) continue;
    const fullPath = path.join(directory, name);
    if (!nonempty(fullPath)) continue;
    const chapter = parseInt(match[1], 10);
    if (sources.has(chapter)) {
      duplicates.push(`第${chapter}章：${toPosix(sources.get(chapter))} / ${toPosix(fullPath)}`);
      continue;
    }
    chapters.push(chapter);
    sources.set(chapter, fullPath);
  }
  chapters.sort((a, b) => a - b);
  return [chapters, sources, duplicates];
}

function compactRanges(chapters) {
  const values = Array.from(new Set(chapters)).sort((a, b) => a - b);
  if (!values.length) {
    return [];
  }
  const ranges = [];
  let start = values[0];
  let previous = values[0];
  for (let i = 1; i < values.length; i += 1) {
    const chapter = values[i];
    if (chapter === previous + 1) {
      previous = chapter;
      continue;
    }
    ranges.push(start === previous ? String(start) : `${start}-${previous}`);
    start = previous = chapter;
  }
  ranges.push(start === previous ? String(start) : `${start}-${previous}`);
  return ranges;
}

function relativePosix(root, targetPath) {
  try {
    const rel = path.relative(resolveReal(root), resolveReal(targetPath));
    if (rel !== ".." && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel)) {
      return toPosix(rel);
    }
  } catch {
    // fallback below
  }
  return toPosix(targetPath);
}

function summaryKind(filePath) {
  const text = readText(filePath) || "";
  return PROJECTION_RE.test(text.slice(0, 1000)) ? "three_script_projection" : "upstream_summary";
}

function readLegacyBoundaries(text) {
  if (!text) return [];
  const rows = [];
  let inSection = false;
  let header = null;
  for (const line of text.split("\n")) {
    const stripped = line.trim();
    if (stripped.startsWith("#")) {
      if (inSection && rows.length) {
        break;
      }
      inSection = BOUNDARY_HEADING_RE.test(stripped);
      header = null;
      continue;
    }
    if (!inSection || !stripped.startsWith("|")) {
      continue;
    }
    const cells = stripped.replace(/^\|+|\|+$/g, "").split("|").map((cell) => cell.trim());
    if (header === null) {
      if (cells.includes("章号")) {
        header = cells;
      }
      continue;
    }
    if (!cells.join("").replace(/^[-: ]+|[-: ]+$/g, "")) {
      continue;
    }
    const record = {};
    for (let i = 0; i < Math.min(header.length, cells.length); i += 1) {
      record[header[i]] = cells[i];
    }
    const numberMatch = /\d+/.exec(record["章号"] || "");
    const startMatch = /\d+/.exec(record["起始行"] || "");
    if (!numberMatch) continue;
    rows.push({
      chapter: parseInt(numberMatch[0], 10),
      title: record["标题"] || "",
      start_line: startMatch ? parseInt(startMatch[0], 10) : null,
    });
  }
  return rows;
}

function titleParts(title) {
  let text = String(title || "").normalize("NFKC").trim();
  let label = "";
  for (let i = 0; i < 3; i += 1) {
    const match = TITLE_LABEL_RE.exec(text);
    if (!match || !match[0].trim()) {
      break;
    }
    for (const group of ["number", "english", "numeric", "special"]) {
      if (match.groups && match.groups[group]) {
        label = match.groups[group];
      }
    }
    text = text.slice(match[0].length);
  }
  const strict = text.replace(TITLE_NOISE_RE, "");
  let loose = text;
  while (TITLE_NOTE_RE.test(loose)) {
    loose = loose.replace(TITLE_NOTE_RE, "");
  }
  return [label, strict, loose.replace(TITLE_NOISE_RE, "") || strict];
}

function labelMatches(label, row) {
  const source = String(row.source_chapter ?? "").trim();
  if (!label || !source) return false;
  if (label === source) return true;
  try {
    const { parseNumber } = require("./build_chapter_index.js");
    return isAsciiDigits(source) && parseNumber(label) === parseInt(source, 10);
  } catch {
    return false;
  }
}

function titleCandidates(title, indexRows) {
  const [label, strict, loose] = titleParts(title);
  if (strict) {
    const keys = indexRows.map((row) => [row, titleParts(String(row.title ?? ""))]);
    const strictTier = keys.filter(([, [, rowStrict]]) => rowStrict === strict).map(([row]) => row);
    if (strictTier.length) return strictTier;
    const looseTier = keys
      .filter(([, [, , rowLoose]]) => rowLoose && (rowLoose === loose || loose.includes(rowLoose) || rowLoose.includes(loose)))
      .map(([row]) => row);
    if (looseTier.length) return looseTier;
  }
  return indexRows.filter((row) => labelMatches(label, row));
}

function mapLegacyRow(old, indexRows) {
  const start = old.start_line;
  if (typeof start === "number" && Number.isInteger(start)) {
    for (const row of indexRows) {
      if (parseInt(row.start_line, 10) === start) {
        return parseInt(row.chapter, 10);
      }
    }
  }
  let matches = titleCandidates(String(old.title ?? ""), indexRows);
  if (typeof start !== "number" || !Number.isInteger(start)) {
    return matches.length === 1 ? parseInt(matches[0].chapter, 10) : null;
  }
  const [label, strict] = titleParts(String(old.title ?? ""));
  if (!matches.length && !label && !strict) {
    matches = indexRows.filter(
      (row) => parseInt(row.start_line, 10) <= start && start <= parseInt(row.end_line, 10)
    );
  }
  const distance = (row) => {
    const first = parseInt(row.start_line, 10);
    const last = parseInt(row.end_line, 10);
    return first <= start && start <= last ? 0 : Math.min(Math.abs(start - first), Math.abs(start - last));
  };
  const ranked = [...matches].sort((a, b) => distance(a) - distance(b));
  if (!ranked.length || (ranked.length > 1 && distance(ranked[0]) === distance(ranked[1]))) {
    return null;
  }
  return parseInt(ranked[0].chapter, 10);
}

function leadingSpecialLabels(indexRows) {
  const labels = [];
  for (const row of indexRows) {
    const source = String(row.source_chapter ?? "").trim();
    if (isAsciiDigits(source) && parseInt(source, 10) >= 1) {
      break;
    }
    labels.push(source === "0" ? "第0章" : source);
  }
  return labels;
}

function mappingAuthorMessage(detail, labels, done) {
  if (labels.length) {
    const prologue = labels.map((label) => `「${label}」`).join("、");
    return (
      `先停一下：${detail}。这次重新识别章节时，开头的${prologue}被算成了单独一章，` +
      `照这样续拆，旧文件会整体错开一章——${prologue}没人拆、有的章被拆两遍。请选一种：` +
      `① 按旧章号继续（推荐，旧拆文当时没把${prologue}算作一章时选这个）：${prologue}并进第一章，` +
      `已拆好的${done}原样复用，${prologue}不单独拆；` +
      `② ${prologue}单独算一章：这本书已有的拆文结果全部挪进备份目录（不删除），按新章号重拆；` +
      `③ 换一个新目录，整本重新拆。`
    );
  }
  return (
    `先停一下：${detail}，没法确认已拆好的${done}各对应哪一章。请选一种：` +
    `① 换一个新目录，整本重新拆（推荐）；② 如果原文换过版本或被改过，换回拆文时用的那份原文再续拆。`
  );
}

function legacyMappingCheck(root, indexRows) {
  if (!indexRows || !indexRows.length) {
    return null;
  }
  const progressText = readText(path.join(root, "_progress.md"));
  const boundaries = readLegacyBoundaries(progressText);
  const legacyProgress = progressText !== null && (boundaries.length > 0 || !progressText.includes(STATE_START));
  const [, summarySources] = collectNumberedFiles(path.join(root, "章节"), SUMMARY_RE);
  const oldChapters = new Set();
  for (const [chapter, filePath] of summarySources.entries()) {
    if (summaryKind(filePath) === "upstream_summary") {
      oldChapters.add(chapter);
    }
  }
  const oldKinds = oldChapters.size ? ["逐章摘要"] : [];
  if (legacyProgress) {
    const [golden] = collectNumberedFiles(path.join(root, "章节"), GOLDEN_RE);
    if (golden.length) {
      for (const ch of golden) oldChapters.add(ch);
      oldKinds.unshift("开头三章拆解");
    }
  }
  if (!oldChapters.size) {
    return null;
  }
  const rows = [...indexRows].sort((a, b) => parseInt(a.chapter, 10) - parseInt(b.chapter, 10));
  const labels = leadingSpecialLabels(rows);
  const done = oldKinds.join("、");
  let detail;
  let code;
  if (boundaries.length) {
    const byOld = new Map();
    let maxOld = 0;
    for (const row of boundaries) {
      byOld.set(row.chapter, row);
      if (row.chapter > maxOld) maxOld = row.chapter;
    }
    const sortedOld = Array.from(oldChapters).sort((a, b) => a - b);
    const inTable = sortedOld.filter((ch) => ch <= maxOld);
    const checked = inTable.length ? inTable : sortedOld;
    const shifted = [];
    const unknown = [];
    for (const chapter of checked) {
      const old = byOld.get(chapter);
      const mapped = old ? mapLegacyRow(old, rows) : null;
      if (mapped === null) {
        unknown.push(chapter);
      } else if (mapped !== chapter) {
        shifted.push([chapter, mapped]);
      }
    }
    if (!shifted.length && !unknown.length) {
      return null;
    }
    if (shifted.length) {
      const [oldNumber, newNumber] = shifted[0];
      const targetRow = rows.find((row) => parseInt(row.chapter, 10) === newNumber);
      const title = targetRow ? String(targetRow.title ?? "") : "";
      detail = `旧拆文的第${oldNumber}章「${title}」，在这次的章节表里是第${newNumber}章`;
    } else {
      detail = `旧进度里的章节表和原文对不上（第${compactRanges(unknown)[0]}章找不到）`;
    }
    code = shifted.length ? "legacy_boundary_shift" : "legacy_boundary_unmatched";
  } else {
    const firstSource = String(rows[0].source_chapter ?? "").trim();
    if (isAsciiDigits(firstSource) && parseInt(firstSource, 10) === 1) {
      return null;
    }
    detail = `原文开头是「${firstSource || "未知"}」，而旧拆文没有留下能核对章号的章节表`;
    code = "legacy_identity_unverifiable";
  }
  return {
    code,
    conflict: `旧拆文章号与当前索引不一致：${detail}`,
    author_message: mappingAuthorMessage(detail, labels, done),
    fold_prologue_available: labels.length > 0,
    legacy_chapters: Array.from(oldChapters).sort((a, b) => a - b),
  };
}

function listMdFiles(dirPath, recursive) {
  const results = [];
  if (!isDir(dirPath)) return results;
  const walk = (current) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (recursive) walk(full);
      } else if (entry.name.endsWith(".md")) {
        results.push(full);
      }
    }
  };
  walk(dirPath);
  return results;
}

function inspect(rootArg, expectedOverride) {
  const root = resolveReal(rootArg);
  const [schema, progressTotal, finalState] = readProgress(path.join(root, "_progress.md"));
  const progressText = readText(path.join(root, "_progress.md"));
  const [indexChapters, indexErrors] = readIndexChapters(path.join(root, "chapter_index.csv"));
  const indexIdentities = readIndexIdentities(path.join(root, "chapter_index.csv"));
  const [managedStatePresent, managedStages] = readManagedStages(progressText);

  const [summaries, summarySources, duplicateSummaries] = collectNumberedFiles(path.join(root, "章节"), SUMMARY_RE);
  const [golden, goldenSources, duplicateGolden] = collectNumberedFiles(path.join(root, "章节"), GOLDEN_RE);

  let preferredPaths = new Map();
  let preferredKinds = new Map();
  for (const [chapter, filePath] of summarySources.entries()) {
    preferredPaths.set(chapter, relativePosix(root, filePath));
    preferredKinds.set(chapter, summaryKind(filePath));
  }
  for (const [chapter, filePath] of goldenSources.entries()) {
    if (!preferredPaths.has(chapter)) {
      preferredPaths.set(chapter, relativePosix(root, filePath));
      preferredKinds.set(chapter, "golden_analysis");
    }
  }

  let expected = expectedOverride !== null && expectedOverride !== undefined ? expectedOverride : null;
  let expectedSource = expected !== null ? "argument" : null;
  if (expected === null && indexChapters.length && !indexErrors.length) {
    expected = indexChapters[indexChapters.length - 1];
    expectedSource = "chapter_index.csv";
  }
  if (expected === null && progressTotal !== null && (finalState === "completed" || finalState === "completed_with_errors")) {
    expected = progressTotal;
    expectedSource = "_progress.md";
  }
  if (expected === null) {
    const [declared, source] = readDeclaredTotal([
      path.join(root, "拆文报告.md"),
      path.join(root, "概要.md"),
      path.join(root, "快速预览.md"),
    ]);
    expected = declared;
    expectedSource = source ? path.basename(source) : null;
  }
  if (expected === null && progressTotal !== null) {
    expected = progressTotal;
    expectedSource = "_progress.md";
  }

  const expectedSet = new Set();
  if (expected) {
    for (let ch = 1; ch <= expected; ch += 1) expectedSet.add(ch);
  }
  const unionSemanticSet = new Set(preferredPaths.keys());
  const summarySet = new Set(summaries);
  const missingSemantic = Array.from(expectedSet).filter((ch) => !unionSemanticSet.has(ch)).sort((a, b) => a - b);
  const outOfRangeSemantic = expected ? Array.from(unionSemanticSet).filter((ch) => !expectedSet.has(ch)).sort((a, b) => a - b) : [];
  const missingSummaries = Array.from(expectedSet).filter((ch) => !summarySet.has(ch)).sort((a, b) => a - b);
  const outOfRangeSummaries = expected ? Array.from(summarySet).filter((ch) => !expectedSet.has(ch)).sort((a, b) => a - b) : [];

  const primary = {
    emotion_module: nonempty(path.join(root, "剧情", "情绪模块.md")),
    rhythm: nonempty(path.join(root, "剧情", "节奏.md")),
  };
  const plotDir = path.join(root, "剧情");
  const excludedPlotNames = new Set(["README.md", "故事线.md", "节奏.md", "情绪模块.md", "散落情节.md"]);
  const assets = {
    report: nonempty(path.join(root, "拆文报告.md")),
    style: nonempty(path.join(root, "文风.md")),
    storyline: nonempty(path.join(plotDir, "故事线.md")),
    plot_units: isDir(plotDir)
      ? anyNonempty(listMdFiles(plotDir, false).filter((p) => !excludedPlotNames.has(path.basename(p))))
      : false,
    characters: isDir(path.join(root, "角色"))
      ? anyNonempty(listMdFiles(path.join(root, "角色"), false).filter((p) => path.basename(p) !== "角色关系.md"))
      : false,
    settings: isDir(path.join(root, "设定"))
      ? anyNonempty(listMdFiles(path.join(root, "设定"), true))
      : false,
    batch_cache: isDir(path.join(root, "_analysis_cache"))
      ? anyNonempty(listMdFiles(path.join(root, "_analysis_cache"), false).filter((p) => path.basename(p).startsWith("批次-")))
      : false,
    chapter_index: nonempty(path.join(root, "chapter_index.csv")),
  };

  const hasAny =
    unionSemanticSet.size > 0 ||
    Object.values(assets).some(Boolean) ||
    Object.values(primary).some(Boolean) ||
    nonempty(path.join(root, "_progress.md"));

  const semanticCoverageComplete =
    unionSemanticSet.size > 0 &&
    ((expected !== null && !missingSemantic.length && !outOfRangeSemantic.length) ||
      (expected === null && (finalState === "completed" || finalState === "completed_with_errors")));
  const summaryCoverageComplete =
    summaries.length > 0 && expected !== null && !missingSummaries.length && !outOfRangeSummaries.length;
  const standardCoverageComplete =
    unionSemanticSet.size > 0 &&
    expected !== null &&
    unionSemanticSet.size === expectedSet.size &&
    Array.from(unionSemanticSet).every((ch) => expectedSet.has(ch));
  const legacyCore = assets.report && summaryCoverageComplete && (assets.storyline || assets.plot_units);
  const managedPipelineComplete = ["stage1", "stage2", "stage3", "stage4", "stage5", "stage6"].every(
    (stage) => managedStages[stage] && managedStages[stage].status === "completed"
  );
  const usableUpstreamComplete =
    Object.values(primary).every(Boolean) &&
    assets.report &&
    standardCoverageComplete &&
    (managedPipelineComplete ||
      ((finalState === "completed" || finalState === "completed_with_errors") && (assets.storyline || assets.plot_units)));

  if (expected) {
    preferredPaths = new Map(Array.from(preferredPaths.entries()).filter(([ch]) => expectedSet.has(ch)));
    preferredKinds = new Map(Array.from(preferredKinds.entries()).filter(([ch]) => expectedSet.has(ch)));
  }
  const semanticSet = new Set(preferredPaths.keys());

  const fullResultAvailable = usableUpstreamComplete || legacyCore;
  const mixedSources = new Set(preferredKinds.values()).size > 1;

  const mappingConflicts = [];
  let mappingBlockedChapters = [];
  const mapping = indexIdentities.length ? legacyMappingCheck(root, indexIdentities) : null;
  if (mapping) {
    const blockedSource = expectedSet.size ? expectedSet : new Set(indexChapters);
    mappingBlockedChapters = Array.from(blockedSource).sort((a, b) => a - b);
    mappingConflicts.push(String(mapping.conflict));
  }

  const stageRepairs = [];
  if (semanticCoverageComplete) {
    const legacyCompleted = finalState === "completed" || finalState === "completed_with_errors";
    if (!primary.emotion_module) stageRepairs.push("stage3_emotion");
    if (!primary.rhythm) stageRepairs.push("stage3_rhythm");
    if (!legacyCompleted && (!assets.characters || !assets.settings)) stageRepairs.push("stage4");
    if (!assets.report) stageRepairs.push("stage5");
    if (!assets.style) stageRepairs.push("stage6_style");
    for (const stage of ["stage3", "stage4", "stage5", "stage6"]) {
      const row = managedStages[stage];
      if (row && row.status !== "completed" && !stageRepairs.includes(stage)) {
        stageRepairs.push(stage);
      } else if (managedStatePresent && !legacyCompleted && !row) {
        if (!stageRepairs.includes(stage) && !stageRepairs.some((item) => item.startsWith(stage + "_"))) {
          stageRepairs.push(stage);
        }
      }
    }
  }

  let classification;
  let recommendedPath;
  if (!hasAny) {
    classification = "empty";
    recommendedPath = "new_analysis";
  } else if (usableUpstreamComplete) {
    classification = "current_complete";
    recommendedPath = stageRepairs.length ? "repair_stages" : "direct_use";
  } else if (legacyCore) {
    classification = "legacy_complete";
    recommendedPath = stageRepairs.length ? "repair_stages" : "direct_use";
  } else if (semanticCoverageComplete) {
    classification = "partial_or_mixed";
    recommendedPath = stageRepairs.length ? "repair_stages" : "enhance_existing";
  } else {
    classification = "partial_or_mixed";
    recommendedPath = expected && missingSemantic.length ? "continue_partial" : "enhance_existing";
  }

  const conflicts = [...indexErrors];
  for (const item of duplicateSummaries) conflicts.push(`重复摘要：${item}`);
  for (const item of duplicateGolden) conflicts.push(`重复黄金三章：${item}`);
  conflicts.push(...mappingConflicts);
  if (finalState === "completed" && !usableUpstreamComplete) {
    conflicts.push("进度标记 completed，但当前主产物或上游逐章覆盖不完整");
  }
  if (finalState === "completed_with_errors" && !semanticCoverageComplete) {
    conflicts.push("进度标记 completed_with_errors，需按失败与待核记录确认可用范围");
  }
  if (indexChapters.length && expected && indexChapters[indexChapters.length - 1] !== expected) {
    conflicts.push("机械索引章数与期望章数不一致");
  }

  const [sourceHash, sourceHashPath] = readSourceHash([path.join(root, "_progress.md")]);

  const preferredByChapterObj = {};
  for (const ch of Array.from(preferredKinds.keys()).sort((a, b) => a - b)) {
    preferredByChapterObj[String(ch)] = preferredKinds.get(ch);
  }
  const preferredPathsObj = {};
  for (const ch of Array.from(preferredPaths.keys()).sort((a, b) => a - b)) {
    preferredPathsObj[String(ch)] = preferredPaths.get(ch);
  }

  return {
    root: String(root),
    classification,
    recommended_path: recommendedPath,
    schema_version: schema,
    final_state: finalState,
    expected_chapters: expected,
    expected_chapters_source: expectedSource,
    completed_summary_chapters: summaries,
    missing_summary_chapters: missingSummaries,
    out_of_range_summary_chapters: outOfRangeSummaries,
    completed_semantic_chapters: Array.from(semanticSet).sort((a, b) => a - b),
    missing_semantic_chapters: missingSemantic,
    out_of_range_semantic_chapters: outOfRangeSemantic,
    semantic_coverage_complete: semanticCoverageComplete,
    full_result_available: fullResultAvailable,
    chapter_sources: {
      priority: ["upstream_summary", "three_script_projection", "golden_analysis"],
      upstream_summary: { chapters: summaries, ranges: compactRanges(summaries) },
      golden_analysis: { chapters: golden, ranges: compactRanges(golden) },
      preferred_by_chapter: preferredByChapterObj,
      preferred_paths: preferredPathsObj,
    },
    source_hash: sourceHash,
    source_hash_source: sourceHashPath,
    primary_artifacts: primary,
    reusable_assets: assets,
    legacy_capabilities: {
      benchmark_reference: fullResultAvailable || assets.report || assets.plot_units || semanticSet.size > 0,
      import_facts: semanticSet.size > 0,
      writing_style_reference: assets.style,
    },
    current_capabilities: {
      emotion_module_recall: primary.emotion_module,
      rhythm_reference_recall: primary.rhythm,
      source_location: assets.chapter_index,
    },
    mixed_sources: mixedSources,
    stage_repairs: stageRepairs,
    managed_stage_status: managedStages,
    chapter_mapping_conflicts: mappingConflicts,
    chapter_mapping_blocked_chapters: mappingBlockedChapters,
    chapter_mapping_author_message: mapping ? mapping.author_message : null,
    provenance_requires_review: mixedSources || (hasAny && schema === null),
    conflicts,
    notes: [
      "本检查只扫描传入书目目录中的上游标准路径，不扫描其他项目或磁盘。",
      "运行路由必须使用 completed_semantic_chapters；缺少逐章摘要文件不等于缺少语义成果。",
      "direct_use 表示默认直接复用；只有用户明确要求增强时才二次提取已有成果。",
      "整本重拆换一个新目录；本检查不提供就地重拆入口。",
    ],
  };
}

function compactPayload(payload) {
  const result = { ...payload };
  const semantic = result.completed_semantic_chapters;
  const missing = result.missing_semantic_chapters;
  delete result.completed_semantic_chapters;
  delete result.missing_semantic_chapters;
  result.semantic_coverage = {
    completed_count: semantic.length,
    completed_ranges: compactRanges(semantic),
    missing_count: missing.length,
    missing_ranges: compactRanges(missing),
  };
  delete result.completed_summary_chapters;
  delete result.missing_summary_chapters;
  delete result.out_of_range_summary_chapters;
  delete result.out_of_range_semantic_chapters;
  const sourceInfo = { ...result.chapter_sources };
  delete sourceInfo.preferred_by_chapter;
  delete sourceInfo.preferred_paths;
  for (const key of ["upstream_summary", "golden_analysis"]) {
    const entry = { ...sourceInfo[key] };
    entry.count = entry.chapters.length;
    delete entry.chapters;
    sourceInfo[key] = entry;
  }
  result.chapter_sources = sourceInfo;
  return result;
}

function sortKeysDeep(value) {
  if (Array.isArray(value)) {
    return value.map(sortKeysDeep);
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value).sort()) {
      out[key] = sortKeysDeep(value[key]);
    }
    return out;
  }
  return value;
}

function printHelp() {
  process.stdout.write(
    "usage: inspect_existing_assets.js --root ROOT [--expected-chapters N] [--compact]\n\n" +
    "Inspect reusable long-analysis assets without changing user files.\n\n" +
    "options:\n" +
    "  --root ROOT                拆文库/{书名} 目录\n" +
    "  --expected-chapters N      已知总章数；省略时按标准路径优先推断\n" +
    "  --compact                  省略逐章数组，输出适合运行路由读取的范围摘要\n" +
    "  -h, --help                 show this help message and exit\n"
  );
}

function parseArgs(argv) {
  const args = { root: null, expectedChapters: null, compact: false };
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
      if (i + 1 >= argv.length) throw new Error(`missing_argument:${flag}`);
      i += 1;
      return argv[i];
    };
    if (flag === "--root") {
      args.root = nextVal();
    } else if (flag === "--expected-chapters") {
      const raw = nextVal();
      const parsed = parseStrictInt(raw);
      if (parsed === null) throw new Error(`invalid_int:${raw}`);
      args.expectedChapters = parsed;
    } else if (flag === "--compact") {
      args.compact = true;
    } else {
      throw new Error(`unknown_argument:${tok}`);
    }
  }
  if (!args.root) {
    throw new Error("--root is required");
  }
  if (args.expectedChapters !== null && args.expectedChapters < 1) {
    throw new Error("--expected-chapters 必须大于 0");
  }
  return args;
}

function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = parseArgs(argv);
    if (args.help) return 0;
  } catch (err) {
    process.stderr.write(`error: ${err.message}\n`);
    return 2;
  }
  try {
    if (!existsPath(args.root)) {
      throw new Error(`root_not_found:${args.root}`);
    }
    if (!isDir(args.root)) {
      throw new Error(`root_is_not_directory:${args.root}`);
    }
    // Force a directory read here so an unreadable path fails before it can
    // be mistaken for an empty new-analysis project.
    fs.readdirSync(args.root);
    let payload = inspect(args.root, args.expectedChapters);
    if (args.compact) {
      payload = compactPayload(payload);
    }
    process.stdout.write(JSON.stringify(sortKeysDeep(payload), null, 2) + "\n");
    return 0;
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: err && err.message ? err.message : String(err) }) + "\n");
    return 2;
  }
}

module.exports = {
  inspect,
  compactPayload,
  legacyMappingCheck,
  legacy_mapping_check: legacyMappingCheck,
  sortKeysDeep,
  listMdFiles,
  resolveReal,
  toPosix,
  main,
};

if (require.main === module) {
  process.exitCode = main();
}
