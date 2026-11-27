#!/usr/bin/env node
"use strict";
/**
 * Plan, commit, split, and recover long-analysis batches.
 *
 * Runtime state lives only in the managed block of `_progress.md`. Plans are
 * printed as JSON and are never persisted. Batch caches are complete recovery
 * evidence, not a second state database. An existing chapter summary is never
 * overwritten: to redo a chapter, delete its summary and plan again.
 */

const fs = require("fs");
const path = require("path");
const {
  sha256,
  isFile,
  existsPath,
  atomicWrite,
  decodeUtf8Strict,
  parseCsvRows,
  parseStrictInt,
} = require("./build_chapter_index.js");
const {
  inspect,
  sortKeysDeep,
  listMdFiles,
  resolveReal,
  toPosix,
} = require("./inspect_existing_assets.js");

const STATE_START = "<!-- story-long-analyze:runtime-state:start -->";
const STATE_END = "<!-- story-long-analyze:runtime-state:end -->";
const CACHE_START = "<!-- story-long-analyze:cache:start -->";
const CACHE_END = "<!-- story-long-analyze:cache:end -->";
const MODEL_START = "<!-- MODEL_OUTPUT_START -->";
const MODEL_END = "<!-- MODEL_OUTPUT_END -->";
const CHAPTER_TOKEN_RE = /<!--\s*CHAPTER_(START|END):(\d+)\s*-->/g;
const CHAPTER_BLOCK_RE = /<!--\s*CHAPTER_START:(\d+)\s*-->\s*([\s\S]*?)\s*<!--\s*CHAPTER_END:\1\s*-->/g;
const BATCH_ID_RE = /^(RAW|REUSE)-(\d+)-(\d+)$/;
const COMPACT_FIELDS = [
  "概要", "因果", "关键行动", "局面结果", "涉及人物", "信息变化", "状态变化",
  "三维节奏", "章尾钩子", "证据",
];
const POINT_HEADER_RE = /^P(\d+)\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$/;
const POINT_TAG_RE = /^主题标签\s*[：:]?\s*([^|｜]*?)\s*[|｜]\s*基调\s*[：:]?\s*(.*?)\s*$/;
const THEMES = ["爱情", "亲情", "友情", "权力", "金钱", "成长", "复仇", "悬念", "搞笑", "热血", "日常", "其他"];
const TONES = ["紧张", "轻松", "悲伤", "热血", "爽", "甜", "温馨", "恐怖", "压抑", "其他"];
const POINT_TYPES = ["转折点", "信息揭示", "冲突", "解决", "铺垫", "行动", "对话", "状态变化"];
const THEME_ALIASES = { "恋爱": "爱情", "权谋": "权力", "政治": "权力", "幽默": "搞笑" };
const TONE_ALIASES = {
  "悲痛": "悲伤", "伤感": "悲伤", "悲愤": "悲伤", "痛快": "爽", "解气": "爽", "惊悚": "恐怖",
  "恐惧": "恐怖", "危险": "紧张", "危急": "紧张", "绝望": "压抑", "无力": "压抑", "释然": "轻松",
};
const POINT_ALIASES = {
  "揭示": "信息揭示", "转折": "转折点", "变化": "状态变化", "动作": "行动",
  "交谈": "对话", "化解": "解决",
};
const MIN_PLOT_POINTS = 6;
const MAX_PLOT_POINTS = 30;
const CHARS_PER_FLOOR_POINT = 350;
const CHARS_PER_CEILING_POINT = 120;
const PLACEHOLDER_TOKEN_RE = /\{[^{}\n]{1,80}\}/;
const QUOTED_SPAN_RE = /“[^”]*”|「[^」]*」|『[^』]*』|"[^"]*"|`[^`]*`/g;
const MAX_CHAPTERS = 3;
const MAX_CHARS = 25000;
const FINAL_STAGES = ["stage3", "stage4", "stage5", "stage6"];
const LEGACY_FINAL_RE = /^([ \t]*(?:[-*][ \t]*)?最终状态[ \t]*[：:][ \t]*)([A-Za-z0-9_]+)/m;
const OBS_START = "<!-- BATCH_OBSERVATIONS_START -->";
const OBS_END = "<!-- BATCH_OBSERVATIONS_END -->";
const SUMMARY_FIELDS = [
  "概要", "关键事件", "因果", "局面结果", "涉及", "信息变化", "状态变化",
  "三维节奏", "章尾钩子", "证据",
];
const BOM_UTF8 = Buffer.from([0xef, 0xbb, 0xbf]);

class RunError extends Error {
  constructor(code, detail, authorMessage = null) {
    super(detail);
    this.code = code;
    this.detail = detail;
    this.authorMessage = authorMessage;
  }
}

function normalized(text) {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function escapeRegExp(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

function isDir(dirPath) {
  try {
    return fs.statSync(dirPath).isDirectory();
  } catch {
    return false;
  }
}

function fileSize(filePath) {
  try {
    const st = fs.statSync(filePath);
    return st.isFile() ? st.size : 0;
  } catch {
    return 0;
  }
}

function relPosix(root, targetPath) {
  return toPosix(path.relative(root, targetPath));
}

function requireRoot(rootArg) {
  const root = resolveReal(rootArg);
  if (!existsPath(root)) {
    throw new RunError("root_not_found", String(root));
  }
  if (!isDir(root)) {
    throw new RunError("root_is_not_directory", String(root));
  }
  try {
    fs.readdirSync(root);
  } catch (err) {
    throw new RunError("root_unreadable", String(err.message || err));
  }
  return root;
}

function readIndex(root, indexArg = null) {
  const indexPath = indexArg ? resolveReal(indexArg) : path.join(root, "chapter_index.csv");
  if (!isFile(indexPath)) {
    const metaFallback = !indexArg ? path.join(root, "meta", "chapter_index.csv") : null;
    const hint = metaFallback && isFile(metaFallback)
      ? `在 ${indexPath} 未找到章节索引（检测到 ${metaFallback}，请将 build_chapter_index.js --output 指向 <root>/chapter_index.csv，或传 --index ${metaFallback}）。`
      : `在 ${indexPath} 未找到章节索引，请先运行 build_chapter_index.js --output <root>/chapter_index.csv（或传 --index PATH 指定索引路径）。`;
    throw new RunError("chapter_index_required", String(indexPath), hint);
  }
  const rows = [];
  let parsed;
  try {
    const text = decodeUtf8Strict(fs.readFileSync(indexPath));
    parsed = parseCsvRows(text);
  } catch (err) {
    throw new RunError("chapter_index_unreadable", String(err.message || err));
  }
  const required = ["chapter", "start_line", "end_line", "char_count", "source_locator", "chapter_sha256"];
  const fieldSet = new Set(parsed.fieldnames);
  const missing = required.filter((col) => !fieldSet.has(col)).sort();
  if (missing.length) {
    throw new RunError("chapter_index_invalid", `missing columns: ${missing.join(", ")}`);
  }
  for (const raw of parsed.rows) {
    const row = { ...raw };
    const chapter = parseStrictInt(row.chapter);
    const startLine = parseStrictInt(row.start_line);
    const endLine = parseStrictInt(row.end_line);
    const charCount = parseStrictInt(row.char_count);
    if (chapter === null || startLine === null || endLine === null || charCount === null) {
      throw new RunError("chapter_index_invalid", "numeric column invalid");
    }
    row.chapter = chapter;
    row.start_line = startLine;
    row.end_line = endLine;
    row.char_count = charCount;
    if (!/^[0-9a-f]{64}$/.test(String(row.chapter_sha256 || ""))) {
      throw new RunError("chapter_index_invalid", "chapter_sha256 invalid");
    }
    rows.push(row);
  }
  for (let i = 0; i < rows.length; i += 1) {
    if (rows[i].chapter !== i + 1) {
      throw new RunError("chapter_index_invalid", "chapter ids must be continuous from 1");
    }
  }
  return rows;
}

function rangeSha256(rows, start, end) {
  const selected = rows.filter((row) => row.chapter >= start && row.chapter <= end);
  if (selected.length !== end - start + 1) {
    throw new RunError("range_not_in_index", `${start}-${end}`);
  }
  for (let i = 0; i < selected.length; i += 1) {
    if (selected[i].chapter !== start + i) {
      throw new RunError("range_not_in_index", `${start}-${end}`);
    }
  }
  const payload = "range-v1\n" + selected.map((row) => `${row.chapter}:${row.chapter_sha256}\n`).join("");
  return sha256(Buffer.from(payload, "ascii"));
}

function decodeProgress(raw) {
  const bom = raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf;
  const text = decodeUtf8Strict(raw);
  const newline = text.includes("\r\n") ? "\r\n" : "\n";
  return [text, bom, newline];
}

function emptyState() {
  return { batches: {}, stages: {} };
}

function tableCells(line) {
  return line.trim().replace(/^\|+|\|+$/g, "").split("|").map((cell) => cell.trim());
}

function loadState(progressPath) {
  const raw = isFile(progressPath) ? fs.readFileSync(progressPath) : Buffer.alloc(0);
  const [text] = decodeProgress(raw);
  const state = emptyState();
  const startCount = countOccurrences(text, STATE_START);
  const endCount = countOccurrences(text, STATE_END);
  if (startCount !== endCount || startCount > 1) {
    throw new RunError(
      "progress_state_block_invalid",
      `expected zero or one complete managed state block; found start=${startCount} end=${endCount}`
    );
  }
  const startIdx = text.indexOf(STATE_START);
  if (startIdx === -1) {
    return [state, raw];
  }
  const endIdx = text.indexOf(STATE_END, startIdx + STATE_START.length);
  if (endIdx === -1) {
    return [state, raw];
  }
  const block = text.slice(startIdx + STATE_START.length, endIdx);
  let section = null;
  for (const line of block.split(/\r\n|\r|\n/)) {
    const trimmed = line.trim();
    if (trimmed === "### 批次状态") {
      section = "batches";
      continue;
    }
    if (trimmed === "### 阶段状态") {
      section = "stages";
      continue;
    }
    if (!line.trimStart().startsWith("|") || line.replace(/[|\-:]/g, "").trim() === "") {
      continue;
    }
    const cells = tableCells(line);
    if (section === "batches" && cells.length >= 7 && cells[0] !== "批次ID" && cells[0] !== "---") {
      const rangeParts = cells[1].split("-");
      if (rangeParts.length !== 2) continue;
      const start = parseStrictInt(rangeParts[0]);
      const end = parseStrictInt(rangeParts[1]);
      if (start === null || end === null) continue;
      state.batches[cells[0]] = {
        batch_id: cells[0],
        start,
        end,
        input_kind: cells[2],
        range_sha256: cells[3],
        status: cells[4],
        parent: cells[5] === "-" ? "" : cells[5],
        cache: cells[6] === "-" ? "" : cells[6],
      };
    } else if (section === "stages" && cells.length >= 3 && cells[0] !== "阶段" && cells[0] !== "---") {
      state.stages[cells[0]] = {
        status: cells[1],
        output: cells[2] === "-" ? "" : cells[2],
      };
    }
  }
  return [state, raw];
}

function finalStatus(stages) {
  const statuses = FINAL_STAGES.map((stage) => (stages[stage] ? stages[stage].status : undefined));
  if (statuses.every((s) => s === "completed" || s === "completed_with_errors")) {
    return statuses.includes("completed_with_errors") ? "completed_with_errors" : "completed";
  }
  return "pending";
}

function renderState(state, newline, finalLine = true) {
  const lines = [STATE_START, "## 长篇拆文运行状态", ""];
  if (finalLine && Object.keys(state.stages).length) {
    lines.push(`- 最终状态：${finalStatus(state.stages)}`, "");
  }
  lines.push(
    "### 批次状态",
    "| 批次ID | 章节范围 | 输入 | 原文范围hash | 状态 | 父批次 | 缓存 |",
    "|---|---|---|---|---|---|---|"
  );
  const batches = Object.values(state.batches).sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    if (a.end !== b.end) return a.end - b.end;
    return a.batch_id < b.batch_id ? -1 : a.batch_id > b.batch_id ? 1 : 0;
  });
  for (const row of batches) {
    lines.push(
      `| ${row.batch_id} | ${row.start}-${row.end} | ${row.input_kind} | ${row.range_sha256} | ${row.status} | ${row.parent || "-"} | ${row.cache || "-"} |`
    );
  }
  lines.push("", "### 阶段状态", "| 阶段 | 状态 | 产物 |", "|---|---|---|");
  for (const stage of Object.keys(state.stages).sort()) {
    const row = state.stages[stage];
    lines.push(`| ${stage} | ${row.status} | ${row.output || "-"} |`);
  }
  lines.push(STATE_END);
  return lines.join(newline);
}

function writeState(progressPath, state) {
  const raw = isFile(progressPath) ? fs.readFileSync(progressPath) : Buffer.alloc(0);
  let [text, bom, newline] = decodeProgress(raw);
  const existingStart = text.indexOf(STATE_START);
  const existingEnd = existingStart !== -1 ? text.indexOf(STATE_END, existingStart + STATE_START.length) : -1;
  const hasExisting = existingStart !== -1 && existingEnd !== -1;
  let head = hasExisting ? text.slice(0, existingStart) : text;
  const legacy = LEGACY_FINAL_RE.exec(head);
  const status = finalStatus(state.stages);
  if (legacy && status !== "pending" && legacy[2] !== status) {
    const valStart = legacy.index + legacy[1].length;
    const valEnd = valStart + legacy[2].length;
    head = head.slice(0, valStart) + status + head.slice(valEnd);
    text = head + (hasExisting ? text.slice(existingStart) : "");
  }
  const block = renderState(state, newline, !legacy);
  let updated;
  if (hasExisting) {
    const curStart = text.indexOf(STATE_START);
    const curEnd = text.indexOf(STATE_END, curStart + STATE_START.length) + STATE_END.length;
    updated = text.slice(0, curStart) + block + text.slice(curEnd);
  } else {
    if (!text) {
      text = `# 深度拆解进度${newline}- schema_version: 2${newline}`;
    }
    const separator = text.endsWith(newline + newline) ? "" : text.endsWith(newline) ? newline : newline + newline;
    updated = text + separator + block + newline;
  }
  const bodyBuf = Buffer.from(updated, "utf8");
  const data = bom ? Buffer.concat([BOM_UTF8, bodyBuf]) : bodyBuf;
  if (data.equals(raw)) {
    return false;
  }
  atomicWrite(progressPath, data);
  return true;
}

function minPlotPoints(chapterChars) {
  if (chapterChars === null || chapterChars === undefined) {
    return MIN_PLOT_POINTS;
  }
  return Math.max(
    1,
    Math.min(MIN_PLOT_POINTS, Math.floor((chapterChars + Math.floor(CHARS_PER_FLOOR_POINT / 2)) / CHARS_PER_FLOOR_POINT))
  );
}

function maxPlotPoints(chapterChars) {
  if (chapterChars === null || chapterChars === undefined) {
    return MAX_PLOT_POINTS;
  }
  return Math.max(MAX_PLOT_POINTS, Math.floor(chapterChars / CHARS_PER_CEILING_POINT));
}

function charsByChapter(rows) {
  const map = {};
  for (const row of rows || []) {
    map[row.chapter] = row.char_count;
  }
  return map;
}

function summaryPath(root, chapter) {
  return path.join(root, "章节", `第${chapter}章_摘要.md`);
}

function cacheComplete(filePath) {
  let text;
  try {
    text = normalized(decodeUtf8Strict(fs.readFileSync(filePath)));
  } catch {
    return false;
  }
  return (
    text.trimEnd().endsWith(CACHE_END) &&
    countOccurrences(text, MODEL_START) === 1 &&
    countOccurrences(text, MODEL_END) === 1
  );
}

function cachePath(root, batchId) {
  return path.join(root, "_analysis_cache", `批次-${batchId}.md`);
}

function completedBatch(root, row, rows) {
  if (row.status !== "completed" && row.status !== "success") {
    return false;
  }
  for (let ch = row.start; ch <= row.end; ch += 1) {
    if (!isFile(summaryPath(root, ch))) return false;
  }
  const targetCache = row.cache ? path.join(root, row.cache) : cachePath(root, row.batch_id);
  if (!cacheComplete(targetCache)) {
    return false;
  }
  let metadata;
  try {
    metadata = parseCache(targetCache);
  } catch {
    return false;
  }
  if (metadata.batch_id !== row.batch_id || metadata.start !== row.start || metadata.end !== row.end) {
    return false;
  }
  if (metadata.range_sha256 !== row.range_sha256) {
    return false;
  }
  if (row.input_kind === "raw-original") {
    if (!rows) return false;
    try {
      return row.range_sha256 === rangeSha256(rows, row.start, row.end);
    } catch {
      return false;
    }
  }
  return true;
}

function compactRangesPairs(chapters) {
  const values = Array.from(new Set(chapters)).sort((a, b) => a - b);
  if (!values.length) return [];
  const result = [];
  let start = values[0];
  let previous = values[0];
  for (let i = 1; i < values.length; i += 1) {
    const value = values[i];
    if (value === previous + 1) {
      previous = value;
    } else {
      result.push([start, previous]);
      start = previous = value;
    }
  }
  result.push([start, previous]);
  return result;
}

function chunkRange(start, end, indexByChapter) {
  const result = [];
  let currentStart = start;
  let count = 0;
  let chars = 0;
  let previous = start - 1;
  for (let chapter = start; chapter <= end; chapter += 1) {
    const chapterChars = indexByChapter ? indexByChapter[chapter].char_count : 0;
    if (count && (count + 1 > MAX_CHAPTERS || chars + chapterChars > MAX_CHARS)) {
      result.push([currentStart, previous]);
      currentStart = chapter;
      count = 0;
      chars = 0;
    }
    count += 1;
    chars += chapterChars;
    previous = chapter;
  }
  result.push([currentStart, previous]);
  return result;
}

function invalidBatchTargets(root, rows, state) {
  const raw = new Set();
  const reuse = new Set();
  for (const batch of Object.values(state.batches)) {
    const pendingChild = Boolean(batch.parent) && batch.status === "planned";
    if (
      !pendingChild &&
      ((batch.status !== "completed" && batch.status !== "success") || completedBatch(root, batch, rows))
    ) {
      continue;
    }
    const target = batch.input_kind === "raw-original" ? raw : batch.input_kind === "existing-results" ? reuse : null;
    if (target) {
      for (let ch = batch.start; ch <= batch.end; ch += 1) target.add(ch);
    }
  }
  return [raw, reuse];
}

function listBatchCaches(root) {
  const cacheDir = path.join(root, "_analysis_cache");
  if (!isDir(cacheDir)) return [];
  return listMdFiles(cacheDir, false).filter((p) => path.basename(p).startsWith("批次-"));
}

function addRecoverableCaches(root, state, rows) {
  const recoverable = [];
  const covered = new Set();
  const charMap = charsByChapter(rows);
  for (const filePath of listBatchCaches(root)) {
    try {
      const metadata = parseCache(filePath);
      const batchId = metadata.batch_id;
      const [inputKind, start, end] = parseBatchId(batchId);
      if (metadata.input_kind !== inputKind) continue;
      const currentHash = metadata.range_sha256;
      if (inputKind === "raw-original") {
        if (!rows || currentHash !== rangeSha256(rows, start, end)) continue;
      }
      const records = parseModelOutput(metadata.model_output, start, end, inputKind, charMap);
      const missing = [];
      for (let ch = start; ch <= end; ch += 1) {
        if (!isFile(summaryPath(root, ch))) missing.push(ch);
      }
      if (missing.length && !missing.every((ch) => Object.prototype.hasOwnProperty.call(records, ch))) {
        continue;
      }
      for (let ch = start; ch <= end; ch += 1) covered.add(ch);
      const current = state.batches[batchId];
      const needsStateRepair = !current || !completedBatch(root, current, rows);
      if (missing.length || needsStateRepair) {
        recoverable.push({
          batch_id: batchId,
          cache: relPosix(root, filePath),
          missing_summary_chapters: missing,
          state_repair_required: needsStateRepair,
        });
        if (missing.length) continue;
      }
      const recovered = {
        batch_id: batchId,
        start,
        end,
        input_kind: inputKind,
        range_sha256: currentHash,
        status: "completed",
        parent: "",
        cache: relPosix(root, filePath),
      };
      if (!current || !completedBatch(root, current, rows)) {
        state.batches[batchId] = recovered;
      }
    } catch {
      continue;
    }
  }
  return [recoverable, covered];
}

function parseChapterWindow(value) {
  if (!value) return null;
  const match = /^(\d+)(?:-(\d+))?$/.exec(value.trim());
  if (!match) {
    throw new RunError("invalid_chapter_window", value);
  }
  const start = parseInt(match[1], 10);
  const end = match[2] ? parseInt(match[2], 10) : start;
  if (start < 1 || end < start) {
    throw new RunError("invalid_chapter_window", value);
  }
  return [start, end];
}

function planCommand(args) {
  const root = requireRoot(args.root);
  const report = inspect(root, args.expectedChapters);
  const [state] = loadState(path.join(root, "_progress.md"));
  let indexRows = null;
  const indexPath = args.index ? resolveReal(args.index) : path.join(root, "chapter_index.csv");
  if (isFile(indexPath)) {
    indexRows = readIndex(root, indexPath);
  }
  const [recoverableCaches, cacheCovered] = addRecoverableCaches(root, state, indexRows);
  const expected = report.expected_chapters || (indexRows ? indexRows.length : null);
  if (!expected) {
    throw new RunError("expected_chapters_unknown", "build the chapter index or pass --expected-chapters");
  }
  const semantic = new Set(report.completed_semantic_chapters);
  const summaries = new Set(report.completed_summary_chapters);
  const allChapters = new Set();
  for (let ch = 1; ch <= expected; ch += 1) allChapters.add(ch);
  const [invalidRaw, invalidReuse] = invalidBatchTargets(root, indexRows, state);

  const rawTargets = new Set();
  for (const ch of allChapters) {
    if (!semantic.has(ch)) rawTargets.add(ch);
  }
  for (const ch of invalidRaw) rawTargets.add(ch);

  const reuseTargets = new Set();
  if (args.intent === "enhance") {
    for (const ch of semantic) {
      if (!rawTargets.has(ch)) reuseTargets.add(ch);
    }
    for (const ch of invalidReuse) reuseTargets.add(ch);
  } else {
    for (const ch of semantic) {
      if (!summaries.has(ch) && !rawTargets.has(ch)) reuseTargets.add(ch);
    }
    for (const ch of invalidReuse) {
      if (!rawTargets.has(ch)) reuseTargets.add(ch);
    }
  }
  for (const ch of cacheCovered) {
    rawTargets.delete(ch);
    reuseTargets.delete(ch);
  }

  const window = parseChapterWindow(args.chapters);
  if (window) {
    if (window[0] > expected) {
      throw new RunError("invalid_chapter_window", `${window[0]}-${window[1]} beyond ${expected} chapters`);
    }
    for (const set of [rawTargets, reuseTargets]) {
      for (const ch of Array.from(set)) {
        if (ch < window[0] || ch > window[1]) set.delete(ch);
      }
    }
  }
  if (rawTargets.size && indexRows === null) {
    throw new RunError("chapter_index_required", "raw-original work remains");
  }
  if (indexRows !== null) {
    const indexedChapters = new Set(indexRows.map((row) => row.chapter));
    const absent = Array.from(rawTargets).filter((ch) => !indexedChapters.has(ch)).sort((a, b) => a - b);
    if (absent.length) {
      throw new RunError("range_not_in_index", absent.join(","));
    }
  }
  const mappingBlocked = new Set(report.chapter_mapping_blocked_chapters || []);
  let blockedHit = false;
  for (const ch of rawTargets) if (mappingBlocked.has(ch)) blockedHit = true;
  for (const ch of reuseTargets) if (mappingBlocked.has(ch)) blockedHit = true;
  if (blockedHit) {
    throw new RunError(
      "chapter_mapping_ambiguous",
      (report.chapter_mapping_conflicts || []).join("; ") || "legacy chapter identity is unresolved",
      report.chapter_mapping_author_message
    );
  }

  const selected = [];
  const indexByChapter = {};
  for (const row of indexRows || []) indexByChapter[row.chapter] = row;
  const preferredPaths = report.chapter_sources.preferred_paths;
  for (const [kind, targets] of [["raw-original", rawTargets], ["existing-results", reuseTargets]]) {
    for (const [rangeStart, rangeEnd] of compactRangesPairs(targets)) {
      for (const [start, end] of chunkRange(rangeStart, rangeEnd, kind === "raw-original" ? indexByChapter : null)) {
        selected.push({ input_kind: kind, start, end });
      }
    }
  }

  const splitChildren = Object.values(state.batches).filter((row) => row.parent && row.status !== "superseded");
  for (const child of splitChildren) {
    for (let i = 0; i < selected.length; i += 1) {
      const item = selected[i];
      if (item.input_kind === child.input_kind && item.start <= child.start && child.end <= item.end) {
        selected.splice(i, 1);
        if (item.start < child.start) {
          selected.push({ input_kind: item.input_kind, start: item.start, end: child.start - 1 });
        }
        selected.push({ input_kind: child.input_kind, start: child.start, end: child.end });
        if (child.end < item.end) {
          selected.push({ input_kind: item.input_kind, start: child.end + 1, end: item.end });
        }
        break;
      }
    }
  }

  const committed = Object.values(state.batches).filter((row) => completedBatch(root, row, indexRows));
  const handoffCache = (start) => {
    const before = committed.filter((row) => row.end < start);
    if (!before.length) return null;
    before.sort((a, b) => (a.end !== b.end ? b.end - a.end : b.start - a.start));
    const row = before[0];
    return row.cache || relPosix(root, cachePath(root, row.batch_id));
  };

  selected.sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    if (a.end !== b.end) return a.end - b.end;
    return a.input_kind < b.input_kind ? -1 : a.input_kind > b.input_kind ? 1 : 0;
  });

  const batches = [];
  let rawReads = 0;
  let resultReads = 0;
  for (const item of selected) {
    const prefix = item.input_kind === "raw-original" ? "RAW" : "REUSE";
    const batchId = `${prefix}-${item.start}-${item.end}`;
    const currentRangeHash =
      item.input_kind === "raw-original" ? rangeSha256(indexRows, item.start, item.end) : "existing-results";
    const prior = state.batches[batchId];
    if (prior && completedBatch(root, prior, indexRows)) {
      continue;
    }
    let sources;
    if (item.input_kind === "raw-original") {
      sources = [];
      for (let ch = item.start; ch <= item.end; ch += 1) {
        sources.push(indexByChapter[ch].source_locator);
      }
      rawReads += sources.length;
    } else {
      const sourceSet = new Set();
      for (let ch = item.start; ch <= item.end; ch += 1) {
        const p = preferredPaths[String(ch)];
        if (p) sourceSet.add(p);
      }
      sources = Array.from(sourceSet).sort();
      resultReads += sources.length;
    }
    const chapterChars = [];
    if (item.input_kind === "raw-original") {
      for (let ch = item.start; ch <= item.end; ch += 1) {
        chapterChars.push(indexByChapter[ch].char_count);
      }
    }
    const minPoints = chapterChars.length
      ? chapterChars.map((c) => minPlotPoints(c))
      : Array(item.end - item.start + 1).fill(1);
    batches.push({
      batch_id: batchId,
      chapter_range: [item.start, item.end],
      input_kind: item.input_kind,
      range_sha256: currentRangeHash,
      source_files: sources,
      cache: `_analysis_cache/批次-${batchId}.md`,
      chapter_chars: chapterChars,
      min_plot_points: minPoints,
      input_file: `_analysis_cache/输入-${batchId}.md`,
      handoff_cache: handoffCache(item.start),
    });
  }

  let requiredStages = [...(report.stage_repairs || [])];
  if (batches.length || recoverableCaches.length) {
    requiredStages = Array.from(new Set([...requiredStages, "stage2"])).sort();
  }
  const summaryGaps = Array.from(allChapters).filter((ch) => !summaries.has(ch)).sort((a, b) => a - b);
  const payload = {
    ok: true,
    root: String(root),
    intent: args.intent,
    classification: report.classification,
    recommended_path: report.recommended_path,
    mixed_sources: report.mixed_sources,
    batches,
    remaining_batches: batches.length,
    recoverable_caches: recoverableCaches,
    summary_gaps: summaryGaps,
    read_counts: { raw_chapters: rawReads, existing_result_files: resultReads },
    required_stages: requiredStages,
    state_written: false,
  };
  if (window) {
    payload.chapter_window = [window[0], window[1]];
  }
  if (args.next !== null && args.next !== undefined) {
    if (args.next < 0) {
      throw new RunError("invalid_next", String(args.next));
    }
    payload.batches = batches.slice(0, args.next);
    payload.summary_gaps = compactRangesPairs(summaryGaps).map(([a, b]) => (a === b ? String(a) : `${a}-${b}`));
  }
  return payload;
}

function parseBatchId(batchId) {
  const match = BATCH_ID_RE.exec(batchId);
  if (!match) {
    throw new RunError("invalid_batch_id", batchId);
  }
  const start = parseInt(match[2], 10);
  const end = parseInt(match[3], 10);
  if (start < 1 || end < start) {
    throw new RunError("invalid_batch_range", batchId);
  }
  return [match[1] === "RAW" ? "raw-original" : "existing-results", start, end];
}

function compactField(body, name) {
  const re = new RegExp(`^\\*\\*${escapeRegExp(name)}\\*\\*\\s*[：:]\\s*(\\S.*)$`, "m");
  const match = re.exec(body);
  if (!match) {
    throw new RunError("chapter_schema_incomplete", `missing field: ${name}`);
  }
  const value = match[1].trim();
  const probe = name === "证据" ? value.replace(QUOTED_SPAN_RE, "") : value;
  if (PLACEHOLDER_TOKEN_RE.test(probe)) {
    throw new RunError("template_placeholder", name);
  }
  return value;
}

function mapEnum(value, allowed, aliases, fallback = "其他") {
  const trimmed = value.trim();
  const tokens = [trimmed, ...trimmed.split(/[、/，,；;\s]+/)];
  for (const token of tokens) {
    if (allowed.includes(token)) return token;
    if (Object.prototype.hasOwnProperty.call(aliases, token)) return aliases[token];
    for (const item of allowed) {
      if (item !== "其他" && token.startsWith(item)) return item;
    }
  }
  return fallback;
}

function parsePlotPoints(body, chapter, minimum, maximum = MAX_PLOT_POINTS) {
  const match = /^\*\*情节点\*\*\s*[：:]\s*$/m.exec(body);
  if (!match) {
    throw new RunError("chapter_schema_incomplete", `chapter ${chapter} missing field: 情节点`);
  }
  const points = [];
  const tail = body.slice(match.index + match[0].length);
  for (const line of tail.split("\n")) {
    const stripped = line.trim();
    const header = POINT_HEADER_RE.exec(stripped);
    if (header) {
      const segments = header[3].split(/[|｜]/).map((item) => item.trim());
      const inline = segments.length >= 3 ? POINT_TAG_RE.exec(segments.slice(-2).join(" | ")) : null;
      const rest = inline ? segments.slice(1, -2) : segments.slice(1);
      if (!segments[0].startsWith("类型") || !rest.length || !rest[0]) {
        throw new RunError("plot_point_invalid", `chapter ${chapter} P${header[1]} needs 类型 and 白描`);
      }
      points.push({
        number: parseInt(header[1], 10),
        title: header[2].trim(),
        type: segments[0].slice(2).replace(/^[ ：:]+/, ""),
        rest,
        quote: [],
        tag: inline ? [inline[1], inline[2]] : null,
      });
      continue;
    }
    if (!stripped || stripped === "---") {
      continue;
    }
    if (!points.length || points[points.length - 1].tag !== null) {
      throw new RunError("plot_point_invalid", `chapter ${chapter}: unexpected line ${JSON.stringify(stripped.slice(0, 40))}`);
    }
    const tag = POINT_TAG_RE.exec(stripped);
    if (tag) {
      points[points.length - 1].tag = [tag[1], tag[2]];
    } else {
      points[points.length - 1].quote.push(stripped);
    }
  }
  for (let i = 0; i < points.length; i += 1) {
    if (points[i].number !== i + 1) {
      throw new RunError("plot_point_invalid", `chapter ${chapter}: points must be numbered P1..Pn`);
    }
  }
  if (points.length < minimum || points.length > maximum) {
    throw new RunError(
      "plot_point_count",
      `chapter ${chapter} has ${points.length} points; expected ${minimum}-${maximum}`
    );
  }
  for (const point of points) {
    if (point.tag === null) {
      throw new RunError("plot_point_invalid", `chapter ${chapter} P${point.number} missing 主题标签/基调 line`);
    }
    const probe = `${point.title} ${point.rest.join(" ").replace(QUOTED_SPAN_RE, "")}`;
    if (PLACEHOLDER_TOKEN_RE.test(probe)) {
      throw new RunError("template_placeholder", `chapter ${chapter} P${point.number}`);
    }
  }
  return points;
}

function tokensEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i][0] !== b[i][0] || a[i][1] !== b[i][1]) return false;
  }
  return true;
}

function parseModelOutput(rawText, start, end, inputKind, chapterChars = null) {
  const text = normalized(rawText);
  if (text.includes("BATCH_ERROR:")) {
    throw new RunError("extractor_reported_error", "model returned BATCH_ERROR");
  }
  for (const marker of [CACHE_START, CACHE_END, MODEL_START, MODEL_END]) {
    if (text.includes(marker)) {
      throw new RunError("reserved_marker_in_output", "model output contains a runtime cache marker");
    }
  }
  const expectedTokens = [];
  for (let ch = start; ch <= end; ch += 1) {
    expectedTokens.push(["START", ch], ["END", ch]);
  }
  const actualTokens = [];
  let lastSourceMarker = 0;
  for (const match of text.matchAll(CHAPTER_TOKEN_RE)) {
    actualTokens.push([match[1], parseInt(match[2], 10)]);
    lastSourceMarker = Math.max(lastSourceMarker, match.index + match[0].length);
  }
  if (inputKind === "raw-original" && !tokensEqual(actualTokens, expectedTokens)) {
    throw new RunError("chapter_marker_mismatch", `expected ${JSON.stringify(expectedTokens)}; received ${JSON.stringify(actualTokens)}`);
  }
  if (actualTokens.length && !tokensEqual(actualTokens, expectedTokens)) {
    throw new RunError("chapter_marker_mismatch", `expected ${JSON.stringify(expectedTokens)}; received ${JSON.stringify(actualTokens)}`);
  }

  const records = {};
  for (const match of text.matchAll(CHAPTER_BLOCK_RE)) {
    const chapter = parseInt(match[1], 10);
    const body = match[2].trim();
    const headingRe = new RegExp(`^##\\s+第${chapter}章(?:\\s+.*)?$`, "m");
    if (!headingRe.test(body)) {
      throw new RunError("chapter_schema_incomplete", `chapter ${chapter} heading missing`);
    }
    const fields = {};
    for (const name of COMPACT_FIELDS) {
      fields[name] = compactField(body, name);
    }
    const charCount = chapterChars && Object.prototype.hasOwnProperty.call(chapterChars, chapter) ? chapterChars[chapter] : null;
    const minimum = inputKind === "raw-original" ? minPlotPoints(charCount) : 1;
    const maximum = maxPlotPoints(charCount);
    fields["情节点"] = parsePlotPoints(body, chapter, minimum, maximum);
    records[chapter] = fields;
  }

  const expectedRangeSet = new Set();
  for (let ch = start; ch <= end; ch += 1) expectedRangeSet.add(ch);
  const recordKeys = Object.keys(records).map((k) => parseInt(k, 10));
  const matchesRange =
    recordKeys.length === expectedRangeSet.size && recordKeys.every((ch) => expectedRangeSet.has(ch));
  if (inputKind === "raw-original" && !matchesRange) {
    throw new RunError("chapter_block_missing", `${start}-${end}`);
  }
  if (recordKeys.length && !matchesRange) {
    throw new RunError("chapter_block_missing", "partial reuse projection is not allowed");
  }
  if (!recordKeys.length && inputKind === "existing-results") {
    const marker = /<!--\s*REUSED_CHAPTERS:(\d+)-(\d+)\s*-->/.exec(text);
    if (!marker || parseInt(marker[1], 10) !== start || parseInt(marker[2], 10) !== end) {
      throw new RunError("reused_range_mismatch", `${start}-${end}`);
    }
  }
  if (countOccurrences(text, OBS_START) !== 1 || countOccurrences(text, OBS_END) !== 1) {
    throw new RunError("batch_marker_mismatch", "one complete cross-chapter observation block is required");
  }
  const observationStart = text.indexOf(OBS_START);
  const observationEnd = text.indexOf(OBS_END);
  const reusedMarker = /<!--\s*REUSED_CHAPTERS:\d+-\d+\s*-->/.exec(text);
  if (reusedMarker) {
    lastSourceMarker = Math.max(lastSourceMarker, reusedMarker.index + reusedMarker[0].length);
  }
  if (observationStart < lastSourceMarker || observationEnd <= observationStart) {
    throw new RunError("batch_marker_order", "cross-chapter observations must follow source coverage");
  }
  return records;
}

function renderPlotPoint(point) {
  const pointType = mapEnum(point.type, POINT_TYPES, POINT_ALIASES, "行动");
  const theme = mapEnum(point.tag[0], THEMES, THEME_ALIASES);
  const tone = mapEnum(point.tag[1], TONES, TONE_ALIASES);
  const lines = [`P${point.number} **${point.title}**：${["类型" + pointType, ...point.rest].join(" | ")}`];
  lines.push(...point.quote);
  lines.push("", `主题标签${theme} | 基调：${tone}`);
  return lines.join("\n");
}

function renderSummary(chapter, fields, sourceKind, chapterHash, batchId) {
  const pointsBlock = fields["情节点"].map(renderPlotPoint).join("\n\n---\n\n");
  const text =
    `<!-- story-long-analyze:projection runtime=single-state-v1 source=${sourceKind} chapter_sha256=${chapterHash} batch=${batchId} -->\n` +
    `## 第${chapter}章\n\n` +
    `**概要**：${fields["概要"]}\n\n` +
    `**关键事件**：\n1. ${fields["关键行动"]}\n\n` +
    `**因果**：${fields["因果"]}\n\n` +
    `**局面结果**：${fields["局面结果"]}\n\n` +
    `**涉及**：${fields["涉及人物"]}\n\n` +
    `**信息变化**：${fields["信息变化"]}\n\n` +
    `**状态变化**：${fields["状态变化"]}\n\n` +
    `**三维节奏**：${fields["三维节奏"]}\n\n` +
    `**章尾钩子**：${fields["章尾钩子"]}\n\n` +
    `**证据**：${fields["证据"]}\n\n` +
    `**情节点**：\n\n${pointsBlock}\n`;
  return Buffer.from(text, "utf8");
}

function renderCache(batchId, start, end, inputKind, rangeHash, sourceFiles, modelOutput, projectionSchema = "compact-v3") {
  const text =
    `${CACHE_START}\n` +
    `# 批次 ${batchId}\n` +
    `- batch_id: ${batchId}\n` +
    `- chapters: ${start}-${end}\n` +
    `- input_kind: ${inputKind}\n` +
    `- range_sha256: ${rangeHash}\n` +
    `- projection_schema: ${projectionSchema}\n` +
    `- source_files: ${JSON.stringify(Array.from(sourceFiles))}\n` +
    `${MODEL_START}\n` +
    `${normalized(modelOutput).trim()}\n` +
    `${MODEL_END}\n` +
    `${CACHE_END}\n`;
  return Buffer.from(text, "utf8");
}

function parseCache(filePath) {
  const text = normalized(decodeUtf8Strict(fs.readFileSync(filePath)));
  if (!text.trimEnd().endsWith(CACHE_END)) {
    throw new RunError("cache_incomplete", String(filePath));
  }
  const metadata = {};
  for (const key of ["batch_id", "chapters", "input_kind", "range_sha256", "projection_schema"]) {
    const match = new RegExp(`^- ${key}:\\s*(.+)$`, "m").exec(text);
    if (!match) {
      throw new RunError("cache_invalid", `missing ${key}`);
    }
    metadata[key] = match[1].trim();
  }
  const chParts = metadata.chapters.split("-");
  if (chParts.length !== 2) {
    throw new RunError("cache_invalid", `chapters: ${metadata.chapters}`);
  }
  const start = parseStrictInt(chParts[0]);
  const end = parseStrictInt(chParts[1]);
  if (start === null || end === null) {
    throw new RunError("cache_invalid", `chapters: ${metadata.chapters}`);
  }
  const modelRe = new RegExp(`${escapeRegExp(MODEL_START)}\\n([\\s\\S]*?)\\n${escapeRegExp(MODEL_END)}`);
  const modelMatch = modelRe.exec(text);
  if (!modelMatch) {
    throw new RunError("cache_invalid", "model output markers missing");
  }
  metadata.start = start;
  metadata.end = end;
  metadata.model_output = modelMatch[1];
  return metadata;
}

function commitFromCache(root, metadata, cacheFile, indexRows) {
  const batchId = metadata.batch_id;
  const [inputKind, idStart, idEnd] = parseBatchId(batchId);
  const start = metadata.start;
  const end = metadata.end;
  if (start !== idStart || end !== idEnd || inputKind !== metadata.input_kind) {
    throw new RunError("cache_invalid", "batch metadata mismatch");
  }
  let currentHash;
  if (inputKind === "raw-original") {
    if (!indexRows) {
      throw new RunError("chapter_index_required", batchId);
    }
    currentHash = rangeSha256(indexRows, start, end);
    if (metadata.range_sha256 !== currentHash) {
      throw new RunError("range_hash_mismatch", batchId);
    }
  } else {
    currentHash = metadata.range_sha256;
  }
  const records = parseModelOutput(metadata.model_output, start, end, inputKind, charsByChapter(indexRows));
  const hashes = {};
  for (const row of indexRows || []) hashes[row.chapter] = row.chapter_sha256;
  const created = [];
  const kept = [];
  const recordChapters = Object.keys(records).map((k) => parseInt(k, 10)).sort((a, b) => a - b);
  for (const chapter of recordChapters) {
    const fields = records[chapter];
    const targetPath = summaryPath(root, chapter);
    if (existsPath(targetPath)) {
      kept.push(chapter);
      continue;
    }
    const chapterHash = hashes[chapter] || "0".repeat(64);
    atomicWrite(targetPath, renderSummary(chapter, fields, inputKind, chapterHash, batchId));
    created.push(relPosix(root, targetPath));
    const failureAfter = process.env.STORY_ANALYZE_FAIL_AFTER_SUMMARIES;
    if (failureAfter && created.length >= parseInt(failureAfter, 10)) {
      throw new Error(`injected_failure_after_${failureAfter}_summaries`);
    }
  }
  const missing = [];
  for (let ch = start; ch <= end; ch += 1) {
    if (!isFile(summaryPath(root, ch))) missing.push(ch);
  }
  if (missing.length) {
    throw new RunError("summary_projection_missing", missing.join(","));
  }
  const [state] = loadState(path.join(root, "_progress.md"));
  state.batches[batchId] = {
    batch_id: batchId,
    start,
    end,
    input_kind: inputKind,
    range_sha256: currentHash,
    status: "completed",
    parent: "",
    cache: relPosix(root, cacheFile),
  };
  const changed = writeState(path.join(root, "_progress.md"), state);
  return {
    batch_id: batchId,
    created_summaries: created,
    kept_existing_summary_chapters: kept,
    progress_updated: changed,
  };
}

function commitCommand(args) {
  const root = requireRoot(args.root);
  const [inputKind, start, end] = parseBatchId(args.batchId);
  if (end - start + 1 > MAX_CHAPTERS) {
    throw new RunError("batch_too_large", `${args.batchId} exceeds ${MAX_CHAPTERS} chapters`);
  }
  const text = decodeUtf8Strict(fs.readFileSync(args.input));
  const indexCandidate = args.index || path.join(root, "chapter_index.csv");
  const indexRows = inputKind === "raw-original" || isFile(indexCandidate) ? readIndex(root, args.index) : null;
  const records = parseModelOutput(text, start, end, inputKind, charsByChapter(indexRows));
  if (inputKind === "raw-original" && end > start) {
    const totalChars = indexRows
      .filter((row) => row.chapter >= start && row.chapter <= end)
      .reduce((acc, row) => acc + row.char_count, 0);
    if (totalChars > MAX_CHARS) {
      throw new RunError("batch_too_large", `${args.batchId} exceeds ${MAX_CHARS} characters`);
    }
  }
  const currentHash = inputKind === "raw-original" ? rangeSha256(indexRows, start, end) : "existing-results";
  if (inputKind === "raw-original" && !args.rangeSha256) {
    throw new RunError("range_hash_required", "pass the value printed by plan");
  }
  if (args.rangeSha256 && args.rangeSha256 !== currentHash) {
    throw new RunError("range_hash_mismatch", args.batchId);
  }
  const targetCache = cachePath(root, args.batchId);
  const data = renderCache(args.batchId, start, end, inputKind, currentHash, args.sourceFiles, text);
  if (!isFile(targetCache) || !fs.readFileSync(targetCache).equals(data)) {
    if (isFile(targetCache)) {
      const oldData = fs.readFileSync(targetCache);
      const stem = path.basename(targetCache, path.extname(targetCache));
      const history = path.join(root, "_analysis_cache", "legacy", `${stem}.${sha256(oldData).slice(0, 12)}.md`);
      if (!existsPath(history)) {
        atomicWrite(history, oldData);
      }
    }
    atomicWrite(targetCache, data);
  }
  if (process.env.STORY_ANALYZE_FAIL_AFTER_CACHE === "1") {
    throw new Error("injected_failure_after_cache");
  }
  const metadata = parseCache(targetCache);
  const result = commitFromCache(root, metadata, targetCache, indexRows);
  return {
    ...result,
    ok: true,
    cache: relPosix(root, targetCache),
    validated_chapters: Object.keys(records).map((k) => parseInt(k, 10)).sort((a, b) => a - b),
  };
}

function repairCommand(args) {
  const root = requireRoot(args.root);
  const indexCandidate = args.index || path.join(root, "chapter_index.csv");
  const indexRows = isFile(indexCandidate) ? readIndex(root, args.index) : null;
  const paths = args.batchId ? [cachePath(root, args.batchId)] : listBatchCaches(root);
  const [state] = loadState(path.join(root, "_progress.md"));
  const repaired = [];
  const skipped = [];
  const errors = [];
  for (const filePath of paths) {
    const stem = path.basename(filePath, path.extname(filePath));
    const batchId = stem.startsWith("批次-") ? stem.slice("批次-".length) : "";
    if (BATCH_ID_RE.test(batchId)) {
      const [, start, end] = parseBatchId(batchId);
      const covered = new Set();
      for (const other of Object.values(state.batches)) {
        if (other.batch_id !== batchId && completedBatch(root, other, indexRows)) {
          for (let ch = other.start; ch <= other.end; ch += 1) covered.add(ch);
        }
      }
      let allCovered = true;
      for (let ch = start; ch <= end; ch += 1) {
        if (!covered.has(ch)) {
          allCovered = false;
          break;
        }
      }
      if ((state.batches[batchId] && state.batches[batchId].status === "superseded") || allCovered) {
        skipped.push({ cache: relPosix(root, filePath), reason: "superseded" });
        continue;
      }
    }
    try {
      const metadata = parseCache(filePath);
      repaired.push(commitFromCache(root, metadata, filePath, indexRows));
    } catch (err) {
      errors.push({
        cache: toPosix(filePath),
        error: err instanceof RunError ? err.code : String(err.message || err),
        detail: String(err.message || err),
      });
    }
  }
  return { ok: errors.length === 0, repaired, skipped, errors };
}

function splitCommand(args) {
  const root = requireRoot(args.root);
  const [inputKind, start, end] = parseBatchId(args.batchId);
  if (start >= end) {
    throw new RunError("batch_not_splittable", args.batchId);
  }
  const indexRows = inputKind === "raw-original" ? readIndex(root, args.index) : null;
  let splitAt = args.at;
  if (splitAt === null || splitAt === undefined) {
    if (indexRows) {
      const counts = {};
      for (const row of indexRows) counts[row.chapter] = row.char_count;
      let total = 0;
      for (let ch = start; ch <= end; ch += 1) total += counts[ch];
      let running = 0;
      splitAt = start;
      for (let ch = start; ch < end; ch += 1) {
        running += counts[ch];
        splitAt = ch;
        if (running >= total / 2) break;
      }
    } else {
      splitAt = Math.floor((start + end) / 2);
    }
  }
  if (splitAt < start || splitAt >= end) {
    throw new RunError("invalid_split_point", String(splitAt));
  }
  const [state] = loadState(path.join(root, "_progress.md"));
  const parentHash = indexRows ? rangeSha256(indexRows, start, end) : "existing-results";
  state.batches[args.batchId] = {
    batch_id: args.batchId,
    start,
    end,
    input_kind: inputKind,
    range_sha256: parentHash,
    status: "superseded",
    parent: "",
    cache: "",
  };
  const prefix = inputKind === "raw-original" ? "RAW" : "REUSE";
  const children = [];
  for (const [childStart, childEnd] of [[start, splitAt], [splitAt + 1, end]]) {
    const childId = `${prefix}-${childStart}-${childEnd}`;
    const childHash = indexRows ? rangeSha256(indexRows, childStart, childEnd) : "existing-results";
    const existing = state.batches[childId];
    if (!existing || (existing.status !== "completed" && existing.status !== "success")) {
      state.batches[childId] = {
        batch_id: childId,
        start: childStart,
        end: childEnd,
        input_kind: inputKind,
        range_sha256: childHash,
        status: "planned",
        parent: args.batchId,
        cache: "",
      };
    }
    children.push(childId);
  }
  writeState(path.join(root, "_progress.md"), state);
  return { ok: true, parent: args.batchId, status: "superseded", children };
}

function stageRequiredOutputs(root, stage) {
  if (stage === "stage1") {
    const expected = inspect(root, null).expected_chapters || 3;
    const required = [];
    for (let ch = 1; ch <= Math.min(3, expected); ch += 1) {
      required.push(`章节/第${ch}章_深度拆解.md`);
    }
    required.push("快速预览.md");
    if (existsPath(path.join(root, "_style-sample.txt"))) {
      required.push("_style-sample.txt");
    }
    return required;
  }
  if (stage === "stage2") {
    const expected = inspect(root, null).expected_chapters;
    if (!expected) {
      throw new RunError("expected_chapters_unknown", "Stage 2 completion requires a known chapter count");
    }
    const required = [];
    for (let ch = 1; ch <= expected; ch += 1) {
      required.push(`章节/第${ch}章_摘要.md`);
    }
    return required;
  }
  if (stage === "stage3") {
    return ["剧情/情绪模块.md", "剧情/节奏.md"];
  }
  if (stage === "stage4") {
    const characterFiles = listMdFiles(path.join(root, "角色"), false).filter(
      (p) => path.basename(p) !== "角色关系.md" && fileSize(p) > 0
    );
    const settingFiles = listMdFiles(path.join(root, "设定"), true).filter((p) => fileSize(p) > 0);
    const missing = [];
    if (!characterFiles.length) missing.push("角色/*.md");
    if (!settingFiles.length) missing.push("设定/**/*.md");
    if (missing.length) {
      throw new RunError("stage_output_missing", missing.join(","));
    }
    return [relPosix(root, characterFiles[0]), relPosix(root, settingFiles[0])];
  }
  if (stage === "stage5") {
    return ["拆文报告.md"];
  }
  if (stage === "stage6") {
    return ["文风.md"];
  }
  throw new RunError("stage_unknown", stage);
}

function markStageCommand(args) {
  const root = requireRoot(args.root);
  if (args.prepare) {
    if (args.stage !== "stage5") {
      throw new RunError("prepare_stage_unsupported", args.stage);
    }
    const reportPath = path.join(root, "拆文报告.md");
    const backupPath = path.join(root, "_analysis_cache", "legacy", "拆文报告.md");
    let created = false;
    let selectedBackup = backupPath;
    if (isFile(reportPath)) {
      const reportData = fs.readFileSync(reportPath);
      if (existsPath(backupPath) && !fs.readFileSync(backupPath).equals(reportData)) {
        selectedBackup = path.join(path.dirname(backupPath), `拆文报告.${sha256(reportData).slice(0, 12)}.md`);
      }
      if (!existsPath(selectedBackup)) {
        atomicWrite(selectedBackup, reportData);
        created = true;
      }
    }
    return {
      ok: true,
      stage: args.stage,
      prepared: true,
      legacy_report_backup: isFile(selectedBackup) ? relPosix(root, selectedBackup) : null,
      backup_created: created,
      progress_updated: false,
    };
  }

  const requiredOutputs = args.status === "completed" ? stageRequiredOutputs(root, args.stage) : [];
  const missingRequired = requiredOutputs.filter((name) => fileSize(path.join(root, name)) === 0);
  if (missingRequired.length) {
    throw new RunError("stage_output_missing", missingRequired.join(","));
  }
  let relativeOutput = "";
  if (args.output) {
    const outPath = path.isAbsolute(args.output) ? args.output : path.join(root, args.output);
    if (args.status === "completed" && fileSize(outPath) === 0) {
      throw new RunError("stage_output_missing", String(outPath));
    }
    const resolvedOut = resolveReal(outPath);
    const rel = path.relative(root, resolvedOut);
    if (rel === ".." || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
      throw new RunError("stage_output_outside_root", String(outPath));
    }
    relativeOutput = toPosix(rel);
  } else if (requiredOutputs.length) {
    relativeOutput = requiredOutputs.join(";");
  }
  const [state] = loadState(path.join(root, "_progress.md"));
  state.stages[args.stage] = { status: args.status, output: relativeOutput };
  const changed = writeState(path.join(root, "_progress.md"), state);
  const result = { ok: true, stage: args.stage, status: args.status, progress_updated: changed };
  if (
    args.stage === "stage1" &&
    args.status === "completed" &&
    isFile(path.join(root, "chapter_index.csv")) &&
    fileSize(path.join(root, "_style-sample.txt")) === 0
  ) {
    result.missing_recommended_outputs = ["_style-sample.txt"];
    result.warnings = [
      "_style-sample.txt 缺失或为空：原文可用时请在 Stage 1 摘录 2–3 段 200–300 字连续原文语感切片落盘",
    ];
  }
  return result;
}

function digestCaches(root) {
  const [state] = loadState(path.join(root, "_progress.md"));
  const chosen = new Map();
  for (const row of Object.values(state.batches)) {
    if (row.status !== "completed" && row.status !== "success") continue;
    const p = row.cache ? path.join(root, row.cache) : cachePath(root, row.batch_id);
    if (cacheComplete(p)) {
      chosen.set(row.batch_id, [row.start, row.end, row.batch_id, p]);
    }
  }
  if (!chosen.size) {
    for (const p of listBatchCaches(root)) {
      const stem = path.basename(p, path.extname(p));
      const batchId = stem.slice("批次-".length);
      try {
        const [, start, end] = parseBatchId(batchId);
        if (cacheComplete(p)) {
          chosen.set(stem, [start, end, batchId, p]);
        }
      } catch {
        continue;
      }
    }
  }
  return Array.from(chosen.values()).sort((a, b) => {
    if (a[0] !== b[0]) return a[0] - b[0];
    if (a[1] !== b[1]) return a[1] - b[1];
    if (a[2] !== b[2]) return a[2] < b[2] ? -1 : 1;
    return a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0;
  });
}

function summaryField(text, name) {
  if (name === "关键事件") {
    const match = /^\*\*关键事件\*\*\s*[：:]\s*\n([\s\S]*?)(?=^\*\*|(?![\s\S]))/m.exec(text);
    if (!match) return "";
    return match[1].split("\n").map((line) => line.trim()).filter(Boolean).join(" ");
  }
  const re = new RegExp(`^\\*\\*${escapeRegExp(name)}\\*\\*\\s*[：:]\\s*(\\S.*)$`, "m");
  const match = re.exec(text);
  return match ? match[1].trim() : "";
}

function summaryPoints(text, mode) {
  const lines = text.split("\n");
  const points = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const header = POINT_HEADER_RE.exec(line.trim());
    if (!header) continue;
    const segments = header[3].split(/[|｜]/).map((item) => item.trim());
    let tone = "";
    for (let j = i + 1; j < Math.min(i + 8, lines.length); j += 1) {
      const follow = lines[j].trim();
      const tag = POINT_TAG_RE.exec(follow);
      if (tag) {
        tone = tag[2];
        break;
      }
      if (POINT_HEADER_RE.test(follow)) {
        break;
      }
    }
    const pointType = segments[0].startsWith("类型") ? segments[0].slice(2).replace(/^[ ：:]+/, "") : segments[0];
    if (mode === "brief") {
      points.push(`P${header[1]} ${header[2].trim()}｜${pointType}｜${tone || "—"}`);
    } else {
      points.push(`${line.trim()} ｜基调：${tone || "—"}`);
    }
  }
  return points;
}

function digestCommand(args) {
  const root = requireRoot(args.root);
  const window = parseChapterWindow(args.chapters);
  const parts = [];
  if (args.part === "observations") {
    for (const [start, end, batchId, p] of digestCaches(root)) {
      if (window && (end < window[0] || start > window[1])) continue;
      const model = parseCache(p).model_output;
      if (!model.includes(OBS_START) || !model.includes(OBS_END)) continue;
      let body = model.split(OBS_START)[1].split(OBS_END)[0].trim();
      body = body.replace(/^##\s*跨章观察\s*\n/gm, "").trim();
      parts.push(`## ${batchId}（第${start}-${end}章）\n\n${body}`);
    }
  } else {
    const fields = (args.fields || "").split(",").map((item) => item.trim()).filter(Boolean);
    const unknown = fields.filter((item) => !SUMMARY_FIELDS.includes(item));
    if (unknown.length) {
      throw new RunError("unknown_summary_field", unknown.join(","));
    }
    if (!fields.length && args.points === "none") {
      throw new RunError("digest_empty_request", "pass --fields and/or --points");
    }
    const chapterDir = path.join(root, "章节");
    const chapterFiles = new Map();
    if (isDir(chapterDir)) {
      for (const name of fs.readdirSync(chapterDir).sort()) {
        const match = /^第(\d+)章_摘要\.md$/.exec(name);
        if (!match) continue;
        const chapter = parseInt(match[1], 10);
        const filePath = path.join(chapterDir, name);
        if (!chapterFiles.has(chapter) || name === `第${chapter}章_摘要.md`) {
          chapterFiles.set(chapter, { chapter, filePath });
        }
      }
    }
    const chapters = Array.from(chapterFiles.values()).sort((a, b) => a.chapter - b.chapter);
    for (const { chapter, filePath } of chapters) {
      if (window && (chapter < window[0] || chapter > window[1])) continue;
      const text = normalized(decodeUtf8Strict(fs.readFileSync(filePath)));
      const lines = [`### 第${chapter}章`];
      for (const name of fields) {
        lines.push(`- ${name}：${summaryField(text, name) || "未提供"}`);
      }
      if (args.points !== "none") {
        lines.push(...summaryPoints(text, args.points));
      }
      parts.push(lines.join("\n"));
    }
  }
  if (!parts.length) {
    throw new RunError("digest_nothing_found", "no committed batch caches or summaries in range");
  }
  return { ok: true, text: parts.join("\n\n") + "\n" };
}

const CHAPTER_HEADING_RE = /^(?:#{1,6}\s+)?(?:正文(?:卷)?\s+)?(?:第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章回节卷部集]|序章|楔子|引子|番外|后记|Chapter\s*\d+|\d+[.．、]\s*)/i;
const AUTHOR_NOTE_START_RE = /^(?:【\s*(?:作者有话说|作者说|PS|非水文|排雷|求票|求收藏|求书架)|作者有话说\s*[：:]?|作者说\s*[：:]|PS\s*[：:])/i;
const DIALOGUE_SPAN_RE = /“[^”\n]+”|「[^」\n]+」|『[^』\n]+』|"[^"\n]+"/g;
const PURE_DIALOGUE_RE = /^(?:“[^”\n]+”|「[^」\n]+」|『[^』\n]+』|"[^"\n]+")$/;
const DIVIDER_LINE_RE = /^[—\-─━_=*~·…\s]{4,}$/;

function round1(value) {
  return Math.round(value * 10) / 10;
}

function calcMedian(nums) {
  if (!nums.length) return 0;
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : round1((sorted[mid - 1] + sorted[mid]) / 2);
}

function countSentencesInParagraph(para) {
  const trimmed = para.trim();
  if (!trimmed) return 0;
  const probe = PURE_DIALOGUE_RE.test(trimmed)
    ? trimmed.slice(1, -1)
    : trimmed.replace(DIALOGUE_SPAN_RE, "X");
  const matches = probe.match(/[。！？!?]+/g);
  return matches ? matches.length : 1;
}

function cleanSampleLines(rawLines) {
  const out = [];
  let inFence = false;
  for (const raw of rawLines) {
    const t = raw.trim();
    if (/^```/.test(t)) {
      inFence = !inFence;
      continue;
    }
    if (!inFence && (/^<!--[\s\S]*-->$/.test(t) || /^#{1,6}\s+/.test(t) || /^(?:source_locator|基调|示范点|出处)\s*[：:]/.test(t))) {
      continue;
    }
    out.push(raw);
  }
  return out;
}

function extractBodyParagraphs(rawLines, options = {}) {
  const expanded = [];
  for (const line of rawLines) {
    const parts = String(line || "").replace(/<br\s*\/?>/gi, "\n").split("\n");
    for (const part of parts) {
      const trimmed = part.trim();
      if (trimmed) expanded.push(trimmed);
    }
  }
  let lines = expanded;
  if (options.stripTitle && lines.length && (CHAPTER_HEADING_RE.test(lines[0]) || (options.title && lines[0].includes(options.title)))) {
    lines = lines.slice(1);
  }
  let authorNoteLines = 0;
  const kept = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (AUTHOR_NOTE_START_RE.test(line)) {
      if (i >= Math.floor(lines.length * 0.7)) {
        authorNoteLines += lines.length - i;
        break;
      }
      authorNoteLines += 1;
      continue;
    }
    kept.push(line);
  }
  return { paragraphs: kept, authorNoteLines };
}

function computeProseMetrics(paragraphs, authorNoteLines = 0) {
  const paraLens = paragraphs.map((p) => p.replace(/\s+/g, "").length).filter((n) => n > 0);
  const paraCount = paraLens.length;
  const charCount = paraLens.reduce((sum, n) => sum + n, 0);
  let le30 = 0;
  let le50 = 0;
  let gt80 = 0;
  let singleSentence = 0;
  let dialogueChars = 0;
  let exclaimCount = 0;
  let questionCount = 0;
  let emDashCount = 0;
  let ellipsisCount = 0;
  let firstDialoguePos = null;
  let cumulativeChars = 0;
  let firstPersonCount = 0;
  let thirdPersonCount = 0;

  for (const para of paragraphs) {
    const compact = para.replace(/\s+/g, "");
    const len = compact.length;
    if (!len) continue;
    if (len <= 30) le30 += 1;
    if (len <= 50) le50 += 1;
    if (len > 80) gt80 += 1;
    if (countSentencesInParagraph(para) <= 1) singleSentence += 1;

    DIALOGUE_SPAN_RE.lastIndex = 0;
    let m;
    while ((m = DIALOGUE_SPAN_RE.exec(compact)) !== null) {
      const inner = m[0].slice(1, -1).trim();
      const isQuotedOnomatopoeia =
        inner.length > 0 &&
        inner.length <= 2 &&
        /^[滴啪砰咚咔哒哐哗吱嘎叮咚叮当噗咕咕哝嗡嘭嚓轰嚓嗒吱呀咯噔哐当哗啦叮铃嗡嗡咕咚咚咚啪嗒咔嚓咔哒]+$/.test(inner);
      if (firstDialoguePos === null && inner.length > 0 && !isQuotedOnomatopoeia) {
        firstDialoguePos = cumulativeChars + m.index + 1;
      }
      dialogueChars += m[0].length;
    }

    const nonDialogue = compact.replace(DIALOGUE_SPAN_RE, "");
    const fpMatches = nonDialogue.match(/我/g);
    const tpMatches = nonDialogue.match(/[他她]/g);
    if (fpMatches) firstPersonCount += fpMatches.length;
    if (tpMatches) thirdPersonCount += tpMatches.length;

    const ex = compact.match(/[！!]/g);
    const qu = compact.match(/[？?]/g);
    if (ex) exclaimCount += ex.length;
    if (qu) questionCount += qu.length;
    if (!DIVIDER_LINE_RE.test(para)) {
      const dashes = compact.match(/——/g);
      if (dashes) emDashCount += dashes.length;
    }
    const ell = compact.match(/……|\.{3,}/g);
    if (ell) ellipsisCount += ell.length;

    cumulativeChars += len;
  }

  const per1k = charCount > 0 ? 1000 / charCount : 0;
  const per10k = charCount > 0 ? 10000 / charCount : 0;
  const pronounTotal = firstPersonCount + thirdPersonCount;
  const firstPersonRatioPct = pronounTotal > 0 ? round1((firstPersonCount / pronounTotal) * 100) : 0;
  const povGuess = firstPersonCount >= 3 && firstPersonCount > thirdPersonCount ? "第一人称" : "第三人称";

  return {
    char_count: charCount,
    para_count: paraCount,
    para_median_chars: calcMedian(paraLens),
    para_le_30_pct: paraCount ? round1((le30 / paraCount) * 100) : 0,
    para_le_50_pct: paraCount ? round1((le50 / paraCount) * 100) : 0,
    para_gt_80_pct: paraCount ? round1((gt80 / paraCount) * 100) : 0,
    single_sentence_para_pct: paraCount ? round1((singleSentence / paraCount) * 100) : 0,
    dialogue_ratio_pct: charCount ? round1((dialogueChars / charCount) * 100) : 0,
    exclaim_per_1k: round1(exclaimCount * per1k),
    question_per_1k: round1(questionCount * per1k),
    exclaim_question_per_1k: round1((exclaimCount + questionCount) * per1k),
    em_dash_per_10k: round1(emDashCount * per10k),
    ellipsis_per_1k: round1(ellipsisCount * per1k),
    first_para_chars: paraLens[0] || 0,
    first_dialogue_pos: firstDialoguePos,
    pov_guess: povGuess,
    first_person_ratio_pct: firstPersonRatioPct,
    has_author_note: authorNoteLines > 0,
    author_note_lines: authorNoteLines,
  };
}

function formatProseStatsMarkdown(payload) {
  const agg = payload.aggregate;
  const chChars = payload.chapters.length
    ? payload.chapters.map((c) => `Ch${c.chapter}: ${c.char_count}`).join(" / ")
    : `${agg.char_count} 字（样本文件）`;
  const lines = [
    "| 指标 | 实测值 |",
    "|---|---|",
    `| 篇幅字数 | ${chChars} |`,
    `| 段长中位数 | ${agg.para_median_chars} 字 |`,
    `| ≤30 字 / ≤50 字 / >80 字段占比 | ${agg.para_le_30_pct}% / ${agg.para_le_50_pct}% / ${agg.para_gt_80_pct}% |`,
    `| 单句成段率 / 对话占比 | ${agg.single_sentence_para_pct}% / ${agg.dialogue_ratio_pct}% |`,
    `| 人称估计 / ！+？（/千字） | ${agg.pov_guess}（第一人称代词占比 ${agg.first_person_ratio_pct}%） / ${agg.exclaim_question_per_1k}（！${agg.exclaim_per_1k} + ？${agg.question_per_1k}） |`,
    `| 破折号（/万字） / 省略号（/千字） | ${agg.em_dash_per_10k} / ${agg.ellipsis_per_1k} |`,
    `| 首段字数 / 首句对话字位 | ${agg.first_para_chars} 字 / ${agg.first_dialogue_pos === null ? "无对话" : `第 ${agg.first_dialogue_pos} 字`} |`,
  ];
  if (payload.author_note_warnings && payload.author_note_warnings.length) {
    lines.push("", `> 提示：已自动剥离作者有话说段落（${payload.author_note_warnings.join("；")}）`);
  }
  return lines.join("\n") + "\n";
}

function proseStatsCommand(args) {
  if (args.file) {
    const baseRoot = args.root ? requireRoot(args.root) : null;
    const targetPath = path.isAbsolute(args.file)
      ? args.file
      : baseRoot
        ? path.join(baseRoot, args.file)
        : path.resolve(args.file);
    if (!isFile(targetPath)) {
      throw new RunError("file_not_found", String(targetPath));
    }
    const rawText = normalized(decodeUtf8Strict(fs.readFileSync(targetPath)));
    const cleaned = cleanSampleLines(rawText.split("\n"));
    const { paragraphs, authorNoteLines } = extractBodyParagraphs(cleaned, { stripTitle: false });
    const metrics = computeProseMetrics(paragraphs, authorNoteLines);
    const warnings = authorNoteLines ? [`${path.basename(targetPath)} 含 ${authorNoteLines} 行作者有话说`] : [];
    const payload = {
      ok: true,
      mode: "file",
      file: baseRoot ? relPosix(baseRoot, targetPath) : toPosix(targetPath),
      chapters: [],
      aggregate: metrics,
      author_note_warnings: warnings,
    };
    payload.markdown_table = formatProseStatsMarkdown(payload);
    return payload;
  }

  const root = requireRoot(args.root);
  const indexRows = readIndex(root, args.index);
  const window = parseChapterWindow(args.chapters || "1-3");
  const selected = indexRows.filter((row) => row.chapter >= window[0] && row.chapter <= window[1]);
  if (!selected.length) {
    throw new RunError("range_not_in_index", `${window[0]}-${window[1]}`);
  }

  const fileLinesCache = new Map();
  const loadLines = (locator) => {
    const filePart = String(locator || "").split(/:L\d+-L\d+$/)[0] || "原文/原文.txt";
    const fullPath = path.isAbsolute(filePart) ? filePart : path.join(root, filePart);
    if (!fileLinesCache.has(fullPath)) {
      if (!isFile(fullPath)) {
        throw new RunError("source_file_not_found", String(fullPath));
      }
      const text = normalized(decodeUtf8Strict(fs.readFileSync(fullPath)));
      fileLinesCache.set(fullPath, text.split("\n"));
    }
    return fileLinesCache.get(fullPath);
  };

  const chapters = [];
  const pooledParagraphs = [];
  let totalAuthorNoteLines = 0;
  const authorNoteWarnings = [];

  for (const row of selected) {
    const allLines = loadLines(row.source_locator);
    const slice = allLines.slice(Math.max(0, row.start_line - 1), row.end_line);
    const { paragraphs, authorNoteLines } = extractBodyParagraphs(slice, {
      stripTitle: true,
      title: row.title || "",
    });
    const metrics = computeProseMetrics(paragraphs, authorNoteLines);
    chapters.push({
      chapter: row.chapter,
      title: row.title || "",
      source_locator: row.source_locator,
      ...metrics,
    });
    pooledParagraphs.push(...paragraphs);
    totalAuthorNoteLines += authorNoteLines;
    if (authorNoteLines > 0) {
      authorNoteWarnings.push(`第${row.chapter}章含 ${authorNoteLines} 行作者有话说`);
    }
  }

  const aggregate = computeProseMetrics(pooledParagraphs, totalAuthorNoteLines);
  if (chapters.length) {
    aggregate.first_para_chars = chapters[0].first_para_chars;
    aggregate.first_dialogue_pos = chapters[0].first_dialogue_pos;
  }
  const payload = {
    ok: true,
    mode: "chapters",
    root: String(root),
    chapter_window: [selected[0].chapter, selected[selected.length - 1].chapter],
    chapters,
    aggregate,
    author_note_warnings: authorNoteWarnings,
  };
  payload.markdown_table = formatProseStatsMarkdown(payload);
  return payload;
}

const SUBCOMMAND_HELP = {
  plan:
    "usage: manage_analysis_run.js plan --root DIR [--index PATH] [--expected-chapters N] [--intent continue|enhance] [--next N] [--chapters A-B]\n\n" +
    "Compute remaining analysis batches without mutating state.\n",
  commit:
    "usage: manage_analysis_run.js commit --root DIR --batch-id ID --input FILE [--range-sha256 SHA] [--source-file PATH ...]\n\n" +
    "Validate and atomically commit one extraction batch into chapter summaries and _progress.md.\n",
  split:
    "usage: manage_analysis_run.js split --root DIR --batch-id ID [--at CHAPTER]\n\n" +
    "Split an oversized batch (at CHAPTER or auto-midpoint by char count) and persist the split boundary.\n",
  "repair-progress":
    "usage: manage_analysis_run.js repair-progress --root DIR [--batch-id ID]\n\n" +
    "Rebuild or recover _progress.md runtime state from existing verified summaries and caches.\n",
  "mark-stage":
    "usage: manage_analysis_run.js mark-stage --root DIR --stage stage1..stage6 [--status completed|completed_with_errors] [--output PATH] [--prepare]\n\n" +
    "Verify required outputs for a stage and record stage completion in _progress.md.\n",
  digest:
    "usage: manage_analysis_run.js digest --root DIR --part observations|chapters [--chapters A-B] [--fields LIST] [--points none|brief|full]\n\n" +
    "Emit compact observations or chapter summaries for downstream synthesis.\n",
  "prose-stats":
    "usage: manage_analysis_run.js prose-stats (--root DIR [--index PATH] [--chapters A-B] | --file PATH) [--format json|markdown]\n\n" +
    "Measure deterministic prose metrics (char count, paragraph median, dialogue ratio, punctuation, POV) with author-note stripping. Defaults to <root>/chapter_index.csv when --root is used.\n",
};

function printHelp(command = null) {
  if (command && SUBCOMMAND_HELP[command]) {
    process.stdout.write(SUBCOMMAND_HELP[command]);
    return;
  }
  process.stdout.write(
    "usage: manage_analysis_run.js {plan,commit,split,repair-progress,mark-stage,digest,prose-stats} ...\n\n" +
    "Plan, commit, split, recover, and measure prose stats for long-analysis batches.\n" +
    "Run `manage_analysis_run.js <subcommand> --help` for subcommand flags.\n"
  );
}

function parseArgs(argv) {
  if (!argv.length) {
    throw new Error("command is required (choose from: plan, commit, split, repair-progress, mark-stage, digest, prose-stats)");
  }
  if (argv[0] === "-h" || argv[0] === "--help") {
    printHelp();
    return { help: true };
  }
  const command = argv[0];
  const rest = argv.slice(1);
  if (!["plan", "commit", "split", "repair-progress", "mark-stage", "digest", "prose-stats"].includes(command)) {
    throw new Error(`unknown_command:${command}`);
  }
  const args = {
    command,
    root: null,
    index: null,
    expectedChapters: null,
    intent: "continue",
    next: null,
    chapters: null,
    input: null,
    batchId: null,
    rangeSha256: null,
    sourceFiles: [],
    at: null,
    stage: null,
    status: "completed",
    output: null,
    prepare: false,
    part: null,
    fields: null,
    points: "none",
    file: null,
    format: "json",
  };

  for (let i = 0; i < rest.length; i += 1) {
    const tok = rest[i];
    if (tok === "-h" || tok === "--help") {
      printHelp(command);
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
      if (i + 1 >= rest.length) throw new Error(`missing_argument:${flag}`);
      i += 1;
      return rest[i];
    };
    const nextInt = () => {
      const raw = nextVal();
      const v = parseStrictInt(raw);
      if (v === null) throw new Error(`invalid_int:${flag}:${raw}`);
      return v;
    };

    if (flag === "--root") args.root = nextVal();
    else if (flag === "--index") args.index = nextVal();
    else if (flag === "--expected-chapters" && command === "plan") args.expectedChapters = nextInt();
    else if (flag === "--intent" && command === "plan") {
      const v = nextVal();
      if (v !== "continue" && v !== "enhance") throw new Error(`invalid_intent:${v}`);
      args.intent = v;
    } else if (flag === "--next" && command === "plan") args.next = nextInt();
    else if (flag === "--chapters" && (command === "plan" || command === "digest" || command === "prose-stats")) args.chapters = nextVal();
    else if (flag === "--file" && command === "prose-stats") args.file = nextVal();
    else if (flag === "--format" && command === "prose-stats") {
      const v = nextVal();
      if (v !== "json" && v !== "markdown") throw new Error(`invalid_format:${v}`);
      args.format = v;
    } else if (flag === "--input" && command === "commit") args.input = nextVal();
    else if (flag === "--batch-id" && (command === "commit" || command === "split" || command === "repair-progress")) args.batchId = nextVal();
    else if (flag === "--range-sha256" && command === "commit") args.rangeSha256 = nextVal();
    else if (flag === "--source-file" && command === "commit") args.sourceFiles.push(nextVal());
    else if (flag === "--at" && command === "split") args.at = nextInt();
    else if (flag === "--stage" && command === "mark-stage") {
      const v = nextVal();
      if (!["stage1", "stage2", "stage3", "stage4", "stage5", "stage6"].includes(v)) throw new Error(`invalid_stage:${v}`);
      args.stage = v;
    } else if (flag === "--status" && command === "mark-stage") {
      const v = nextVal();
      if (v !== "completed" && v !== "completed_with_errors") throw new Error(`invalid_status:${v}`);
      args.status = v;
    } else if (flag === "--output" && command === "mark-stage") args.output = nextVal();
    else if (flag === "--prepare" && command === "mark-stage") args.prepare = true;
    else if (flag === "--part" && command === "digest") {
      const v = nextVal();
      if (v !== "observations" && v !== "chapters") throw new Error(`invalid_part:${v}`);
      args.part = v;
    } else if (flag === "--fields" && command === "digest") args.fields = nextVal();
    else if (flag === "--points" && command === "digest") {
      const v = nextVal();
      if (!["none", "brief", "full"].includes(v)) throw new Error(`invalid_points:${v}`);
      args.points = v;
    } else {
      throw new Error(`unknown_argument:${tok}`);
    }
  }

  if (!args.root && !(command === "prose-stats" && args.file)) throw new Error("--root is required");
  if (command === "commit" && (!args.input || !args.batchId)) throw new Error("--input and --batch-id are required");
  if (command === "split" && !args.batchId) throw new Error("--batch-id is required");
  if (command === "mark-stage" && !args.stage) throw new Error("--stage is required");
  if (command === "digest" && !args.part) throw new Error("--part is required");
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

  const handlers = {
    plan: planCommand,
    commit: commitCommand,
    split: splitCommand,
    "repair-progress": repairCommand,
    "mark-stage": markStageCommand,
    digest: digestCommand,
    "prose-stats": proseStatsCommand,
  };

  try {
    const payload = handlers[args.command](args);
    if (args.command === "digest") {
      process.stdout.write(payload.text);
      return 0;
    }
    if (args.command === "prose-stats" && args.format === "markdown") {
      process.stdout.write(payload.markdown_table);
      return 0;
    }
    process.stdout.write(JSON.stringify(sortKeysDeep(payload), null, 2) + "\n");
    return payload.ok === false ? 2 : 0;
  } catch (err) {
    const payload = {
      ok: false,
      error: err instanceof RunError ? err.code : "io_error",
      detail: err && err.message ? err.message : String(err),
    };
    if (err instanceof RunError && err.authorMessage) {
      payload.author_message = err.authorMessage;
    }
    process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
    return 2;
  }
}

module.exports = {
  RunError,
  planCommand,
  commitCommand,
  splitCommand,
  repairCommand,
  markStageCommand,
  digestCommand,
  proseStatsCommand,
  computeProseMetrics,
  main,
};

if (require.main === module) {
  process.exitCode = main();
}
