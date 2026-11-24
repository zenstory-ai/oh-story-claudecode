#!/usr/bin/env node
'use strict';
/**
 * Small deterministic wordcount core shared by storyctl, tracking_commit,
 * check-outline-contract, build_writer_prompt, and build_outline_brief.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const WORDCOUNT_SCHEMA = 'story-wordcount-result/v1';
const MEASUREMENT_SCHEMA = 'story-wordcount-measurement/v1';
const CHECKPOINT_SCHEMA = 'story-wordcount-checkpoint/v1';
const METRIC = 'visible_chars_v1';
const RESOLUTIONS = new Set(['within_user_band', 'accepted_current_length']);

const _WHITE_SPACE_CODEPOINTS = new Set([
  0x0009, 0x000a, 0x000b, 0x000c, 0x000d,
  0x0020, 0x0085, 0x00a0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

const _FRONTMATTER_KEY_RE = /^[A-Za-z_\u3400-\u9FFF][^:\n]{0,80}:[ \t]*(?:.*)$/;
const _LEADING_BLANK_RE = /^[\u0009\u0020\u3000]*$/;
const _ATX_HEADING_RE = /^[\u0009\u0020]{0,3}#{1,6}[\u0009\u0020]+\S/;
const _POSITIVE_INTEGER_RE = /^[1-9]\d*$/;

// 细纲「字数目标」「字数范围」「字数口径」的唯一写法语法；check-outline-contract.js 直接复用本模块。
// 值里一个数字都没有的目标/范围行（「字数目标：按卷规划」）是说明文字，不参与取值。
const _NUMBER = '([1-9][0-9]{0,2}(?:[,，][0-9]{3})+|[1-9][0-9]*)';
const _NOTE = '(?:[（(][^（）()]*[）)])?';
const _TARGET_VALUE_RE = new RegExp(`^(?:约|大约)?[ \\t]*${_NUMBER}[ \\t]*字?(?:左右)?[ \\t]*${_NOTE}$`);
const _RANGE_VALUE_RE = new RegExp(
  `^${_NUMBER}[ \\t]*字?[ \\t]*(?:-|~|～|—|–|－|至|到)[ \\t]*${_NUMBER}[ \\t]*字?[ \\t]*${_NOTE}$`
);
const _METRIC_VALUE_RE = new RegExp(`^([A-Za-z0-9_-]+)[ \\t]*${_NOTE}$`);
const _HAS_DIGIT_RE = /[0-9０-９]/;

const BOOK_DIRS = ['设定', '大纲', '正文', '追踪'];
const _RECORD_FIELDS = new Set(['metric', 'target', 'actual', 'status', 'resolution', 'body_sha256']);

class WordcountError extends Error {
  constructor(message) {
    super(message);
    this.name = 'WordcountError';
  }
}

function requireCondition(condition, message) {
  if (!condition) {
    throw new WordcountError(message);
  }
}

function normalizeNewlines(value) {
  return value.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function stripBom(value) {
  return value.startsWith('\ufeff') ? value.slice(1) : value;
}

function _fieldValues(text, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(
    `^[ \\t>]*(?:[-*+][ \\t]*)?(?:\\*\\*)?${escaped}(?:\\*\\*)?[ \\t]*[:：][ \\t]*(.*?)[ \\t]*$`,
    'gm'
  );
  const values = [];
  let match;
  while ((match = pattern.exec(text)) !== null) {
    values.push(match[1].replace(/\*\*/g, '').trim());
  }
  return values;
}

function _numericFieldValues(text, label) {
  return _fieldValues(text, label).filter((raw) => _HAS_DIGIT_RE.test(raw));
}

function _number(raw) {
  return Number(raw.replace(/[,，]/g, ''));
}

function parseTargetField(text) {
  const raws = _numericFieldValues(stripBom(normalizeNewlines(text)), '字数目标');
  if (raws.length === 0) {
    return { status: 'missing', value: null, raw: raws };
  }
  const matches = raws.map((raw) => _TARGET_VALUE_RE.exec(raw));
  if (!matches.every(Boolean)) {
    return { status: 'invalid', value: null, raw: raws };
  }
  const values = [...new Set(matches.map((m) => _number(m[1])))].sort((a, b) => a - b);
  if (values.length !== 1) {
    return { status: 'conflict', value: null, raw: raws };
  }
  return { status: 'ok', value: values[0], raw: raws };
}

function parseRangeField(text) {
  const raws = _numericFieldValues(stripBom(normalizeNewlines(text)), '字数范围');
  if (raws.length === 0) {
    return { status: 'missing', value: null, raw: raws };
  }
  const matches = raws.map((raw) => _RANGE_VALUE_RE.exec(raw));
  if (!matches.every(Boolean)) {
    return { status: 'invalid', value: null, raw: raws };
  }
  const pairKeys = [...new Set(matches.map((m) => `${_number(m[1])}:${_number(m[2])}`))];
  if (pairKeys.length !== 1) {
    return { status: 'invalid', value: null, raw: raws };
  }
  const [low, high] = pairKeys[0].split(':').map(Number);
  if (low > high) {
    return { status: 'invalid', value: null, raw: raws };
  }
  return { status: 'ok', value: { min: low, max: high }, raw: raws };
}

function parseMetricField(text) {
  const raws = _fieldValues(stripBom(normalizeNewlines(text)), '字数口径');
  const matches = raws.map((raw) => _METRIC_VALUE_RE.exec(raw));
  const ok =
    raws.length === 0 ||
    (matches.every(Boolean) &&
      new Set(matches.map((m) => m[1])).size === 1 &&
      matches[0][1] === METRIC);
  return { ok, raw: raws };
}

function _isDir(targetPath) {
  try {
    return fs.statSync(targetPath).isDirectory();
  } catch {
    return false;
  }
}

function _isFile(targetPath) {
  try {
    return fs.statSync(targetPath).isFile();
  } catch {
    return false;
  }
}

function _realpathOrResolve(targetPath) {
  const resolved = path.resolve(targetPath);
  try {
    return fs.realpathSync(resolved);
  } catch {
    return resolved;
  }
}

function resolveBookDir(project) {
  const root = String(project);
  const marker = path.join(root, '.active-book');
  if (BOOK_DIRS.some((name) => _isDir(path.join(root, name))) || !_isFile(marker)) {
    return root;
  }
  const lines = fs.readFileSync(marker, 'utf8').split(/\r?\n/);
  const active = lines.length ? lines[0].trim() : '';
  const book = path.join(root, active);
  const realRoot = _realpathOrResolve(root);
  const realBook = _realpathOrResolve(book);
  const rel = path.relative(realRoot, realBook);
  const inside = rel === '' || (rel !== '..' && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel));
  requireCondition(
    Boolean(active) && inside && _isDir(book),
    `${marker} 没有指向工作区里的书目录（写的是「${active}」）；--project 直接传书目录`
  );
  return book;
}

function stripRecognizableFrontmatter(value) {
  const lines = value.split('\n');
  if (!lines.length || lines[0] !== '---') {
    return value;
  }
  const limit = Math.min(lines.length, 201);
  let closing = -1;
  for (let index = 1; index < limit; index += 1) {
    if (lines[index] === '---' || lines[index] === '...') {
      closing = index;
      break;
    }
  }
  if (closing < 2 || !lines.slice(1, closing).some((line) => _FRONTMATTER_KEY_RE.test(line))) {
    return value;
  }
  return lines.slice(closing + 1).join('\n');
}

function visibleBody(value) {
  if (typeof value !== 'string') {
    throw new TypeError('body must be a string');
  }
  let text = normalizeNewlines(value);
  if (text.startsWith('\ufeff')) {
    text = text.slice(1);
  }
  const lines = stripRecognizableFrontmatter(text).split('\n');
  while (lines.length && _LEADING_BLANK_RE.test(lines[0])) {
    lines.shift();
  }
  if (lines.length && _ATX_HEADING_RE.test(lines[0])) {
    lines.shift();
  }
  return lines.join('\n');
}

function countVisibleChars(value) {
  const body = visibleBody(value);
  let count = 0;
  for (const ch of body) {
    if (!_WHITE_SPACE_CODEPOINTS.has(ch.codePointAt(0))) {
      count += 1;
    }
  }
  return count;
}

function parseTarget(value) {
  const raw = value === null || value === undefined ? '' : String(value);
  if (!_POSITIVE_INTEGER_RE.test(raw)) {
    throw new WordcountError('target must be a positive integer');
  }
  const big = BigInt(raw);
  requireCondition(big <= BigInt(Number.MAX_SAFE_INTEGER), 'target exceeds Number.MAX_SAFE_INTEGER');
  return Number(big);
}

function normalizeAuthorRange(value) {
  if (value === null || value === undefined) {
    return null;
  }
  requireCondition(
    typeof value === 'object' &&
      !Array.isArray(value) &&
      Object.keys(value).length === 2 &&
      Object.prototype.hasOwnProperty.call(value, 'min') &&
      Object.prototype.hasOwnProperty.call(value, 'max'),
    'author range must be {min, max}'
  );
  const { min: low, max: high } = value;
  requireCondition(
    Number.isInteger(low) && low >= 1 && Number.isInteger(high) && high >= 1,
    'author range bounds must be positive integers'
  );
  requireCondition(low <= high, 'author range min must not exceed max');
  return { min: low, max: high };
}

function computeWordcountBands(value, authorRange = null) {
  const target = parseTarget(value);
  const author = normalizeAuthorRange(authorRange);
  if (author !== null) {
    return { internal: { ...author }, user: { ...author } };
  }
  const bigTarget = BigInt(target);
  return {
    internal: {
      min: Number((bigTarget * 88n + 99n) / 100n),
      max: Number((bigTarget * 112n) / 100n),
    },
    user: {
      min: Number((bigTarget * 85n + 99n) / 100n),
      max: Number((bigTarget * 115n) / 100n),
    },
  };
}

function invalidWordcountResult(reason, opts = {}) {
  const { chapter = null, caseId = null, target = null, actual = null } = opts;
  return {
    schema: WORDCOUNT_SCHEMA,
    metric: METRIC,
    chapter,
    case_id: caseId,
    target,
    actual,
    internal_band: null,
    user_band: null,
    signed_error_pct: null,
    absolute_error_pct: null,
    band_source: null,
    status: 'invalid',
    invalid_reason: reason,
  };
}

function measureWordcount(value, opts = {}) {
  const { chapter = null, caseId = null } = opts;
  let actual;
  try {
    actual = countVisibleChars(value);
  } catch {
    return {
      schema: MEASUREMENT_SCHEMA,
      metric: METRIC,
      chapter,
      case_id: caseId,
      actual: null,
      status: 'invalid',
      invalid_reason: 'INVALID_BODY',
    };
  }
  return {
    schema: MEASUREMENT_SCHEMA,
    metric: METRIC,
    chapter,
    case_id: caseId,
    actual,
    status: 'measured',
    invalid_reason: null,
  };
}

function evaluateWordcount(value, targetValue, opts = {}) {
  const { chapter = null, caseId = null, authorRange = null } = opts;
  let target;
  try {
    target = parseTarget(targetValue);
  } catch {
    return invalidWordcountResult('INVALID_TARGET', { chapter, caseId });
  }
  let author;
  try {
    author = normalizeAuthorRange(authorRange);
  } catch {
    return invalidWordcountResult('INVALID_RANGE', { chapter, caseId, target });
  }
  let actual;
  try {
    actual = countVisibleChars(value);
  } catch {
    return invalidWordcountResult('INVALID_BODY', { chapter, caseId, target });
  }
  if (actual === 0) {
    return invalidWordcountResult('EMPTY_BODY', { chapter, caseId, target, actual });
  }
  const bands = computeWordcountBands(target, author);
  const internalPass = bands.internal.min <= actual && actual <= bands.internal.max;
  const userPass = bands.user.min <= actual && actual <= bands.user.max;
  const status = internalPass
    ? 'internal_pass'
    : userPass
      ? 'borderline'
      : actual < bands.user.min
        ? 'under'
        : 'over';
  const signedError = (actual - target) / target;
  return {
    schema: WORDCOUNT_SCHEMA,
    metric: METRIC,
    chapter,
    case_id: caseId,
    target,
    actual,
    internal_band: { ...bands.internal, status: internalPass ? 'pass' : 'fail' },
    user_band: { ...bands.user, status: userPass ? 'pass' : 'fail' },
    signed_error_pct: signedError,
    absolute_error_pct: Math.abs(signedError),
    band_source: author ? 'author' : 'default',
    status,
    invalid_reason: null,
  };
}

function checkpointWordcount(value, targetValue, opts = {}) {
  const { chapter = null, caseId = null, authorRange = null } = opts;
  const target = parseTarget(targetValue);
  const actual = countVisibleChars(value);
  const author = normalizeAuthorRange(authorRange);
  const user = computeWordcountBands(target, author).user;
  return {
    schema: CHECKPOINT_SCHEMA,
    metric: METRIC,
    chapter,
    case_id: caseId,
    target,
    actual,
    user_band: user,
    band_source: author ? 'author' : 'default',
    remaining_user_range: {
      min: Math.max(0, user.min - actual),
      max: Math.max(0, user.max - actual),
    },
  };
}

const _FIELD_ERRORS = {
  missing: 'is missing',
  invalid: 'is not a recognizable number (write e.g. 2300 字 / 约 2300 / 2,300)',
  conflict: 'has conflicting values',
};

function targetFromOutline(value) {
  const text = stripBom(normalizeNewlines(value));
  const parsed = parseTargetField(text);
  requireCondition(
    parsed.status === 'ok',
    `字数目标 ${_FIELD_ERRORS[parsed.status] || ''}: ${JSON.stringify(parsed.raw)}`
  );
  requireCondition(parseMetricField(text).ok, `字数口径 must be ${METRIC} when written`);
  return parseTarget(parsed.value);
}

function rangeFromOutline(value) {
  const parsed = parseRangeField(value);
  if (parsed.status === 'missing') {
    return null;
  }
  requireCondition(
    parsed.status === 'ok',
    `字数范围 must be one min-max pair with min <= max: ${JSON.stringify(parsed.raw)}`
  );
  return parsed.value;
}

const _SINGLE_OUTLINE_RE = /^细纲_第(\d+)章.*\.md$/;
const _RANGE_OUTLINE_RE = /^细纲_第(\d+)[-–—~～至到]第?(\d+)章.*\.md$/;
const _BODY_CHAPTER_RE = /^第(\d+)章(?:[_\- 　].*)?\.md$/;
const _CHAPTER_SLICE_HEADING_RE = /^#{2,3}[ \t]*第[ \t]*(\d+)[ \t]*章(?:[：:\s]|$)/;

function _chapterNumberFromName(name, { outline }) {
  if (name.includes('_原稿_')) {
    return null;
  }
  const pattern = outline ? _SINGLE_OUTLINE_RE : _BODY_CHAPTER_RE;
  const match = pattern.exec(name);
  if (!match) return null;
  const num = Number(match[1]);
  return Number.isInteger(num) && num >= 1 ? num : null;
}

function _outlineRangeFromName(name) {
  if (name.includes('_原稿_')) {
    return null;
  }
  const match = _RANGE_OUTLINE_RE.exec(name);
  if (!match) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || start > end) {
    return null;
  }
  return { start, end };
}

function extractChapterSlice(text, chapter) {
  const lines = stripBom(normalizeNewlines(text)).split('\n');
  let start = -1;
  for (let i = 0; i < lines.length; i += 1) {
    const match = _CHAPTER_SLICE_HEADING_RE.exec(lines[i]);
    if (match && Number(match[1]) === chapter) {
      start = i;
      break;
    }
  }
  if (start === -1) return null;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i += 1) {
    if (_CHAPTER_SLICE_HEADING_RE.test(lines[i])) {
      end = i;
      break;
    }
  }
  return lines.slice(start, end).join('\n');
}

function findChapterFile(directory, chapter, { outline }) {
  requireCondition(Number.isInteger(chapter) && chapter >= 1, 'chapter must be >= 1');
  requireCondition(_isDir(directory), `chapter directory is missing: ${directory}`);
  const entries = fs.readdirSync(directory).sort();
  const matches = [];
  for (const name of entries) {
    const fullPath = path.join(directory, name);
    if (_isFile(fullPath) && _chapterNumberFromName(name, { outline }) === chapter) {
      matches.push(fullPath);
    }
  }
  const label = outline ? 'outline' : 'body';
  if (matches.length === 1) {
    return matches[0];
  }
  if (outline && matches.length === 0) {
    const rangeMatches = [];
    for (const name of entries) {
      const fullPath = path.join(directory, name);
      if (!_isFile(fullPath)) continue;
      const range = _outlineRangeFromName(name);
      if (range && range.start <= chapter && chapter <= range.end) {
        rangeMatches.push(fullPath);
      }
    }
    requireCondition(rangeMatches.length === 1, `chapter ${chapter} must have exactly one ${label} file`);
    return rangeMatches[0];
  }
  requireCondition(false, `chapter ${chapter} must have exactly one ${label} file`);
}

function readUtf8Strict(filePath) {
  const rawBytes = fs.readFileSync(filePath);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  return { rawBytes, text: decoder.decode(rawBytes) };
}

function readChapterOutline(project, chapter) {
  const outlinePath = findChapterFile(path.join(path.resolve(String(project)), '大纲'), chapter, { outline: true });
  let text;
  try {
    ({ text } = readUtf8Strict(outlinePath));
  } catch (err) {
    throw new WordcountError(`unable to read outline: ${err.message}`);
  }
  const baseName = path.basename(outlinePath);
  const isRangeFile =
    _chapterNumberFromName(baseName, { outline: true }) === null && _outlineRangeFromName(baseName) !== null;
  if (isRangeFile) {
    const slice = extractChapterSlice(text, chapter);
    requireCondition(
      slice !== null,
      `range outline ${baseName} does not contain chapter ${chapter} section`
    );
    return { outlinePath, outline: slice, fromRangeFile: true };
  }
  return { outlinePath, outline: text, fromRangeFile: false };
}

function effectiveAuthorRange(outline, authorRange = null) {
  return authorRange !== null && authorRange !== undefined
    ? normalizeAuthorRange(authorRange)
    : rangeFromOutline(outline);
}

function readProjectChapter(project, chapter, authorRange = null) {
  const { outlinePath, outline } = readChapterOutline(project, chapter);
  const bodyPath = findChapterFile(path.join(path.resolve(String(project)), '正文'), chapter, { outline: false });
  return {
    outlinePath,
    bodyPath,
    target: targetFromOutline(outline),
    authorRange: effectiveAuthorRange(outline, authorRange),
  };
}

function buildProjectWordcountRecord(project, chapter, { resolution, authorRange = null }) {
  requireCondition(RESOLUTIONS.has(resolution), `unsupported wordcount resolution: ${resolution}`);
  const { bodyPath, target, authorRange: author } = readProjectChapter(project, chapter, authorRange);
  let rawBytes;
  let body;
  try {
    ({ rawBytes, text: body } = readUtf8Strict(bodyPath));
  } catch (err) {
    throw new WordcountError(`unable to read chapter files: ${err.message}`);
  }
  const result = evaluateWordcount(body, target, { chapter, authorRange: author });
  requireCondition(result.status !== 'invalid', `invalid chapter wordcount: ${result.invalid_reason}`);
  const inUserBand = result.status === 'internal_pass' || result.status === 'borderline';
  requireCondition(
    (resolution === 'within_user_band' && inUserBand) ||
      (resolution === 'accepted_current_length' && !inUserBand),
    'wordcount resolution does not match the current length'
  );
  const record = {
    metric: METRIC,
    target: result.target,
    actual: result.actual,
    status: result.status,
    resolution,
    body_sha256: crypto.createHash('sha256').update(rawBytes).digest('hex'),
  };
  if (author !== null) {
    record.author_range = { ...author };
  }
  return record;
}

function normalizeWordcountRecord(value) {
  requireCondition(
    value !== null && typeof value === 'object' && !Array.isArray(value),
    'wordcount record must be an object'
  );
  const keys = Object.keys(value);
  const validKeys =
    (keys.length === _RECORD_FIELDS.size && keys.every((k) => _RECORD_FIELDS.has(k))) ||
    (keys.length === _RECORD_FIELDS.size + 1 &&
      keys.every((k) => _RECORD_FIELDS.has(k) || k === 'author_range') &&
      Object.prototype.hasOwnProperty.call(value, 'author_range'));
  requireCondition(validKeys, 'wordcount record fields are invalid');
  requireCondition(value.metric === METRIC, 'wordcount metric is unsupported');
  const target = parseTarget(value.target);
  const author = normalizeAuthorRange(value.author_range);
  const actual = value.actual;
  requireCondition(Number.isInteger(actual) && actual >= 1, 'wordcount actual is invalid');
  const expected = evaluateWordcount('字'.repeat(actual), target, { authorRange: author });
  requireCondition(value.status === expected.status, 'wordcount status does not match target and actual');
  const resolution = value.resolution;
  requireCondition(RESOLUTIONS.has(resolution), 'wordcount resolution is unsupported');
  const inUserBand = expected.status === 'internal_pass' || expected.status === 'borderline';
  requireCondition((resolution === 'within_user_band') === inUserBand, 'wordcount resolution does not match status');
  const digest = value.body_sha256;
  requireCondition(typeof digest === 'string' && /^[0-9a-f]{64}$/.test(digest), 'body_sha256 is invalid');
  const out = {
    metric: value.metric,
    target: value.target,
    actual: value.actual,
    status: value.status,
    resolution: value.resolution,
    body_sha256: value.body_sha256,
  };
  if (Object.prototype.hasOwnProperty.call(value, 'author_range')) {
    out.author_range = value.author_range === null ? null : { ...author };
  }
  return out;
}

function wordcountRecordDrift(project, chapter, value) {
  const record = normalizeWordcountRecord(value);
  const root = path.resolve(String(project));
  const { outline } = readChapterOutline(root, chapter);
  const bodyPath = findChapterFile(path.join(root, '正文'), chapter, { outline: false });
  let bodyBytes;
  try {
    bodyBytes = fs.readFileSync(bodyPath);
  } catch (err) {
    throw new WordcountError(`unable to read chapter files: ${err.message}`);
  }
  const drift = [];
  if (crypto.createHash('sha256').update(bodyBytes).digest('hex') !== record.body_sha256) {
    drift.push('正文');
  }
  if (targetFromOutline(outline) !== record.target) {
    drift.push('字数目标');
  }
  return drift;
}

function _recordsEqual(a, b) {
  const aKeys = Object.keys(a).sort();
  const bKeys = Object.keys(b).sort();
  if (aKeys.length !== bKeys.length) return false;
  for (let i = 0; i < aKeys.length; i += 1) {
    const k = aKeys[i];
    if (k !== bKeys[i]) return false;
    const av = a[k];
    const bv = b[k];
    if (av && typeof av === 'object' && bv && typeof bv === 'object') {
      if (av.min !== bv.min || av.max !== bv.max) return false;
    } else if (av !== bv) {
      return false;
    }
  }
  return true;
}

function validateCurrentWordcountRecord(project, chapter, value) {
  const record = normalizeWordcountRecord(value);
  const current = buildProjectWordcountRecord(project, chapter, {
    resolution: record.resolution,
    authorRange: record.author_range ?? null,
  });
  requireCondition(_recordsEqual(record, current), 'wordcount record is stale for the current body or target');
  return record;
}

module.exports = {
  WORDCOUNT_SCHEMA,
  MEASUREMENT_SCHEMA,
  CHECKPOINT_SCHEMA,
  METRIC,
  RESOLUTIONS,
  BOOK_DIRS,
  WordcountError,
  require: requireCondition,
  normalizeNewlines,
  stripRecognizableFrontmatter,
  visibleBody,
  countVisibleChars,
  parseTarget,
  normalizeAuthorRange,
  computeWordcountBands,
  invalidWordcountResult,
  measureWordcount,
  evaluateWordcount,
  checkpointWordcount,
  parseTargetField,
  parseRangeField,
  parseMetricField,
  targetFromOutline,
  rangeFromOutline,
  effectiveAuthorRange,
  resolveBookDir,
  extractChapterSlice,
  findChapterFile,
  readChapterOutline,
  readProjectChapter,
  readUtf8Strict,
  buildProjectWordcountRecord,
  normalizeWordcountRecord,
  wordcountRecordDrift,
  validateCurrentWordcountRecord,
};
