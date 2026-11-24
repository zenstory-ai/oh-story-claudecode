#!/usr/bin/env node
'use strict';
/**
 * Maintain one structured story state and its deterministic Markdown views.
 *
 * The language model supplies compact semantic JSON. This tool validates and
 * merges that input in memory, renders every derived view, then atomically writes
 * `_tracking-state.json` last as the single commit point. Per-project locking
 * serializes concurrent writers before revision and wordcount checks.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');

const wordcountCore = require('./wordcount_core.js');

const INPUT_SCHEMA_VERSION = 1;
const TRACKING_SCHEMA_VERSION = 4;
const VIEW_HARD_CAP_BYTES = 65536;
const DELTA_TARGET_BYTES = 2048;
const DELTA_MAX_BYTES = 3584;
const CONTEXT_TARGET_BYTES = 8192;
const CONTEXT_MAX_BYTES = 12288;
const SNAPSHOT_TARGET_BYTES = 16384;
const SNAPSHOT_MAX_BYTES = VIEW_HARD_CAP_BYTES;
const SNAPSHOT_ITEM_MAX_BYTES = 600;
const DRAFT_INLINE_SNAPSHOTS_MAX_BYTES = 16384;
const ACTIVE_CHARACTER_MAX = 20;

const CONTEXT_HEADINGS = [
  '## 当前位置',
  '## 长期约束',
  '## 核心角色状态',
  '## 活跃伏笔',
  '## 近三章速记',
  '## 下一章承诺',
  '## 连贯性风险',
];
const FORESHADOW_STATUSES = ['已埋', '已回收', '已过期', '放弃'];
const FORESHADOW_IMPORTANCE = ['高', '中', '低'];
const REVEAL_STATUSES = ['未揭示', '部分揭示', '已揭示'];

const ACTION_ALIASES = {
  add: 'upsert', new: 'upsert', create: 'upsert', update: 'upsert', plant: 'upsert',
  advance: 'upsert', resolve: 'upsert', insert: 'upsert',
  新增: 'upsert', 埋设: 'upsert', 更新: 'upsert', 推进: 'upsert', 回收: 'upsert',
  remove: 'delete', 删除: 'delete',
};
const FORESHADOW_ACTION_STATUS = {
  resolve: '已回收', 回收: '已回收',
  advance: '已埋', 推进: '已埋',
};
const FORESHADOW_KEY_ALIASES = {
  planned_chapter: 'planned_resolution_chapter',
  planned_payoff_chapter: 'planned_resolution_chapter',
  payoff_chapter: 'planned_resolution_chapter',
  resolution_chapter: 'planned_resolution_chapter',
  resolve_chapter: 'planned_resolution_chapter',
  plant_chapter: 'planted_chapter',
  planted: 'planted_chapter',
  description: 'summary',
  content: 'summary',
};
const TIMELINE_KEY_ALIASES = {
  time: 'story_time',
  fact: 'objective_fact',
  reveal: 'reveal_status',
};
const INVALID_FILE_CHARS = /[<>:"/\\|?*\x00-\x1f]/;
const FORESHADOW_ID = /^F\d{3,}$/;
const SNAPSHOT_TEXT_FIELDS = ['identity', 'location', 'goal', 'state'];
const SNAPSHOT_LIST_FIELDS = ['abilities_resources', 'relationships', 'knowledge', 'open_threads'];
const EVENT_ID = /^E\d{3,}$/;
const WINDOWS_RESERVED_NAMES = new Set([
  'CON', 'PRN', 'AUX', 'NUL',
  'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
  'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
]);
const RETIRED_TRACKING_PATHS = [
  '_tracking-meta.json',
  '阶段摘要.md',
  '角色状态.md',
  '时间线.md',
  '摘要',
  '时间线/事件库.json',
];
const RETIRED_ARCHIVE_DIR = '_旧追踪存档';

const RECOUNT_HINT =
  '修订请用 story-long-write 的 storyctl.js chapter commit（带外用 chapter accept-current-length）' +
  '提交同一份事务，它会重新计数并清理本章工作目录';

const DRAFT_LIMITS = {
  'delta.result': 160,
  'character_changes[].change': 120,
  'foreshadow_changes[].summary': 120,
  'timeline_events[].objective_fact / reader_knowledge': 160,
  'context.position.story_time / scene': 80,
  'character_snapshots.*.identity / location': 80,
  'character_snapshots.*.goal / state': 100,
  'character_snapshots.*.四个列表单项': 200,
  角色快照单文件: 21500,
  逐章记录目标字数: 682,
  逐章记录总量: 1194,
};

const RECORD_SECTIONS = {
  角色变化: 'character_changes',
  伏笔变化: 'foreshadow_changes',
  时间与揭示: 'timeline_events',
  连贯性约束: 'constraints',
  本章退役登记: 'retired',
};

const _SLEEP_ARR = new Int32Array(new SharedArrayBuffer(4));
function sleepMs(ms) {
  Atomics.wait(_SLEEP_ARR, 0, 0, ms);
}

class TrackingError extends Error {
  constructor(message) {
    super(message);
    this.name = 'TrackingError';
  }
}

function requireCondition(condition, message) {
  if (!condition) {
    throw new TrackingError(message);
  }
}

function wordcountValue(fn, ...args) {
  try {
    return fn(...args);
  } catch (err) {
    if (err instanceof wordcountCore.WordcountError) {
      throw new TrackingError(err.message);
    }
    throw err;
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function asMapping(value, label) {
  requireCondition(isPlainObject(value), `${label} must be a JSON object`);
  return value;
}

function asList(value, label) {
  requireCondition(Array.isArray(value), `${label} must be a JSON array`);
  return value;
}

function asInt(value, label, { minimum = 0 } = {}) {
  requireCondition(Number.isInteger(value), `${label} must be an integer`);
  requireCondition(value >= minimum, `${label} must be >= ${minimum}`);
  return value;
}

function asChapter(value, label, { minimum = 1 } = {}) {
  let candidate = value;
  if (typeof candidate === 'string') {
    const trimmed = candidate.trim();
    if (/^[0-9０-９]+$/.test(trimmed)) {
      const ascii = trimmed.replace(/[０-９]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xfee0));
      candidate = Number(ascii);
    }
  }
  return asInt(candidate, label, { minimum });
}

function withAliases(row, aliases) {
  const out = { ...row };
  for (const [alias, canonical] of Object.entries(aliases)) {
    if (Object.prototype.hasOwnProperty.call(out, alias) && !Object.prototype.hasOwnProperty.call(out, canonical)) {
      out[canonical] = out[alias];
      delete out[alias];
    }
  }
  return out;
}

function byteSize(text) {
  return Buffer.byteLength(text, 'utf8');
}

function charLen(text) {
  return Array.from(text).length;
}

let _softWarnings = null;

function addSoftWarning(message) {
  if (_softWarnings !== null && !_softWarnings.includes(message)) {
    _softWarnings.push(message);
  }
}

function lengthHint(label, text, maxBytes) {
  const size = byteSize(text);
  const chars = charLen(text);
  const allowed = Math.max(1, Math.floor((maxBytes * chars) / size));
  return `${label} exceeds ${maxBytes} bytes（现 ${chars} 字，建议上限约 ${allowed} 字，不影响本次提交）`;
}

function cleanText(value, label, { allowEmpty = false, maxBytes = 768, hardMaxBytes = null } = {}) {
  requireCondition(typeof value === 'string', `${label} must be a string`);
  const cleaned = value.replace(/\|/g, '｜').trim().replace(/\s+/g, ' ');
  requireCondition(allowEmpty || Boolean(cleaned), `${label} must not be empty`);
  if (hardMaxBytes !== null) {
    requireCondition(byteSize(cleaned) <= hardMaxBytes, `${label} exceeds hard cap of ${hardMaxBytes} bytes`);
  }
  if (maxBytes !== null && byteSize(cleaned) > maxBytes) {
    addSoftWarning(lengthHint(label, cleaned, maxBytes));
  }
  return cleaned;
}

function normalizeAction(value, label, { allowDelete }) {
  let action = cleanText(value, label, { maxBytes: 24 });
  const lowered = action.toLowerCase();
  action = ACTION_ALIASES[lowered] || lowered;
  const allowed = allowDelete ? ['upsert', 'delete'] : ['upsert'];
  requireCondition(allowed.includes(action), `${label} is invalid: use ${allowed.join(' or ')}`);
  return action;
}

function requireKnownKeys(mapping, allowed, label) {
  const unknown = Object.keys(mapping).filter((k) => !allowed.has(k)).sort();
  requireCondition(
    unknown.length === 0,
    `${label} contains unsupported fields: ${unknown.join(', ')}（只收 ${[...allowed].sort().join(', ')}）`
  );
}

function cleanStringList(value, label, { maximum = null, itemMaxBytes = 384 } = {}) {
  const values = asList(value, label);
  if (maximum !== null && values.length > maximum) {
    addSoftWarning(`${label} has ${values.length} items（建议最多 ${maximum} 项，不影响本次提交）`);
  }
  return values.map((item, index) => cleanText(item, `${label}[${index}]`, { maxBytes: itemMaxBytes }));
}

function safeFileComponent(value, label) {
  const name = cleanText(value, label, { maxBytes: 180, hardMaxBytes: 180 }).normalize('NFC');
  requireCondition(!INVALID_FILE_CHARS.test(name), `${label} contains an invalid filename character`);
  requireCondition(name !== '.' && name !== '..' && !name.endsWith('.') && !name.endsWith(' '), `${label} is not a safe filename`);
  const stem = name.split('.')[0].toUpperCase();
  requireCondition(!WINDOWS_RESERVED_NAMES.has(stem), `${label} is reserved on Windows`);
  return name;
}

function portableNameKey(name) {
  return name.normalize('NFC').toLowerCase();
}

function emit(text, { error = false } = {}) {
  const stream = error ? process.stderr : process.stdout;
  stream.write(`${text}\n`);
}

function sortKeysDeep(value) {
  if (Array.isArray(value)) {
    return value.map(sortKeysDeep);
  }
  if (isPlainObject(value)) {
    const out = {};
    for (const key of Object.keys(value).sort()) {
      out[key] = sortKeysDeep(value[key]);
    }
    return out;
  }
  return value;
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function readJson(filePath) {
  try {
    const raw = fs.readFileSync(filePath);
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    return JSON.parse(text);
  } catch (err) {
    throw new TrackingError(`unable to read JSON ${filePath}: ${err.message}`);
  }
}

function jsonPayload(document) {
  return `${JSON.stringify(sortKeysDeep(document), null, 2)}\n`;
}

function exists(filePath) {
  try {
    fs.statSync(filePath);
    return true;
  } catch {
    return false;
  }
}

function isDir(filePath) {
  try {
    return fs.statSync(filePath).isDirectory();
  } catch {
    return false;
  }
}

function atomicWriteText(filePath, payload) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  let mode = 0o644;
  try {
    mode = fs.statSync(filePath).mode & 0o777;
  } catch {
    mode = 0o644;
  }
  const base = path.basename(filePath);
  let tmpPath = null;
  let fd = null;
  for (let attempt = 0; attempt < 32; attempt += 1) {
    const suffix = crypto.randomBytes(6).toString('hex');
    const candidate = path.join(dir, `.${base}.${suffix}.tmp`);
    try {
      fd = fs.openSync(candidate, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, 0o600);
      tmpPath = candidate;
      break;
    } catch (err) {
      if (err && err.code === 'EEXIST') continue;
      throw err;
    }
  }
  if (fd === null || tmpPath === null) {
    throw new TrackingError(`unable to create temporary file for ${filePath}`);
  }
  try {
    const normalized = payload.replace(/\r\n/g, '\n');
    fs.writeSync(fd, Buffer.from(normalized, 'utf8'));
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = null;
    try {
      fs.chmodSync(tmpPath, mode);
    } catch {
      // ignore on Windows
    }
    fs.renameSync(tmpPath, filePath);
    tmpPath = null;
  } finally {
    if (fd !== null) {
      try {
        fs.closeSync(fd);
      } catch {
        // ignore
      }
    }
    if (tmpPath !== null) {
      try {
        fs.rmSync(tmpPath, { force: true });
      } catch {
        // ignore
      }
    }
  }
}

const _hooks = { atomicWriteText };

function writeIfChanged(filePath, payload) {
  try {
    if (fs.readFileSync(filePath, 'utf8') === payload) {
      return;
    }
  } catch (err) {
    if (!err || err.code !== 'ENOENT') throw err;
  }
  _hooks.atomicWriteText(filePath, payload);
}

function trackingRoot(project) {
  return path.join(path.resolve(String(project)), '追踪');
}

function statePath(project) {
  return path.join(trackingRoot(project), '_tracking-state.json');
}

function withProjectWriteLock(project, fn, { timeoutSeconds = 10.0 } = {}) {
  const tracking = trackingRoot(project);
  fs.mkdirSync(tracking, { recursive: true });
  const lockPath = path.join(tracking, '.tracking-commit.lock');
  const deadline = performance.now() + timeoutSeconds * 1000;
  let fd = null;
  while (fd === null) {
    try {
      fd = fs.openSync(lockPath, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, 0o644);
    } catch (err) {
      if (err && err.code === 'EEXIST') {
        if (performance.now() >= deadline) {
          throw new TrackingError(
            'tracking commit lock is busy or stale; retry, or remove 追踪/.tracking-commit.lock after confirming no commit is running'
          );
        }
        sleepMs(50);
        continue;
      }
      throw err;
    }
  }
  try {
    fs.writeSync(fd, Buffer.from(`pid=${process.pid}\n`, 'ascii'));
    fs.fsyncSync(fd);
    return fn();
  } finally {
    try {
      fs.closeSync(fd);
    } catch {
      // ignore
    }
    try {
      fs.unlinkSync(lockPath);
    } catch (err) {
      if (!err || err.code !== 'ENOENT') {
        // ignore
      }
    }
  }
}

function padChapter(chapter) {
  const s = String(chapter);
  return s.padStart(Math.max(3, s.length), '0');
}

function deltaPath(tracking, chapter) {
  return path.join(tracking, '逐章记录', `第${padChapter(chapter)}章.md`);
}

function chapterWorkDir(project, chapter) {
  return path.join(String(project), '.story', 'work', `第${padChapter(chapter)}章`);
}

function findRetiredTrackingPaths(tracking) {
  const found = RETIRED_TRACKING_PATHS.filter((rel) => exists(path.join(tracking, rel)));
  if (isDir(tracking)) {
    const baselines = fs
      .readdirSync(tracking)
      .filter((name) => /^基线_截至第.*章\.md$/.test(name))
      .sort();
    found.push(...baselines);
  }
  return found;
}

function requireNoRetiredTrackingPaths(tracking) {
  const found = findRetiredTrackingPaths(tracking);
  requireCondition(found.length === 0, `retired tracking files are not supported: ${found.join(', ')}`);
}

function findPreexistingTrackingEntries(tracking) {
  if (!isDir(tracking)) return [];
  return fs
    .readdirSync(tracking)
    .filter((name) => name !== RETIRED_ARCHIVE_DIR && name !== '.tracking-commit.lock' && !name.endsWith('.lock'))
    .sort();
}

function archiveRetiredTrackingPaths(tracking) {
  const preexisting = findPreexistingTrackingEntries(tracking);
  if (!preexisting.length) return [];
  const archive = path.join(tracking, RETIRED_ARCHIVE_DIR);
  for (const relative of preexisting) {
    requireCondition(
      !exists(path.join(archive, relative)),
      `追踪/${RETIRED_ARCHIVE_DIR}/${relative} already exists; move it away before initializing`
    );
  }
  for (const relative of preexisting) {
    const target = path.join(archive, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.renameSync(path.join(tracking, relative), target);
  }
  return preexisting;
}

function bothBlank(position) {
  return ['story_time', 'scene'].every(
    (key) => typeof position[key] === 'string' && position[key].trim() === ''
  );
}

function validatePosition(value, label = 'context.position') {
  const position = asMapping(value, label);
  requireKnownKeys(position, new Set(['volume', 'volume_start_chapter', 'story_time', 'scene']), label);
  requireCondition(
    !bothBlank(position),
    `${label}.story_time and ${label}.scene must not be empty: fill where this chapter ends`
  );
  return {
    volume: safeFileComponent(position.volume, `${label}.volume`),
    volume_start_chapter: asInt(position.volume_start_chapter, `${label}.volume_start_chapter`, { minimum: 1 }),
    story_time: cleanText(position.story_time, `${label}.story_time`, { maxBytes: 240 }),
    scene: cleanText(position.scene, `${label}.scene`, { maxBytes: 240 }),
  };
}

function joinedText(value) {
  if (Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'string')) {
    return value.join('；');
  }
  return value;
}

function asTextList(value) {
  return typeof value === 'string' && value.trim() ? [value] : value;
}

function normalizeSnapshot(value, label) {
  const raw = asMapping(value, label);
  const snapshot = {};
  for (const [key, item] of Object.entries(raw)) {
    if (SNAPSHOT_TEXT_FIELDS.includes(key)) {
      snapshot[key] = joinedText(item);
    } else if (SNAPSHOT_LIST_FIELDS.includes(key)) {
      snapshot[key] = asTextList(item);
    } else {
      snapshot[key] = item;
    }
  }
  requireKnownKeys(
    snapshot,
    new Set(['identity', 'location', 'goal', 'state', 'abilities_resources', 'relationships', 'knowledge', 'open_threads']),
    label
  );
  return {
    identity: cleanText(snapshot.identity, `${label}.identity`, { maxBytes: 240 }),
    location: cleanText(snapshot.location, `${label}.location`, { maxBytes: 240 }),
    goal: cleanText(snapshot.goal, `${label}.goal`, { maxBytes: 300 }),
    state: cleanText(snapshot.state, `${label}.state`, { maxBytes: 300 }),
    abilities_resources: cleanStringList(snapshot.abilities_resources ?? [], `${label}.abilities_resources`, {
      itemMaxBytes: SNAPSHOT_ITEM_MAX_BYTES,
    }),
    relationships: cleanStringList(snapshot.relationships ?? [], `${label}.relationships`, {
      itemMaxBytes: SNAPSHOT_ITEM_MAX_BYTES,
    }),
    knowledge: cleanStringList(snapshot.knowledge ?? [], `${label}.knowledge`, {
      itemMaxBytes: SNAPSHOT_ITEM_MAX_BYTES,
    }),
    open_threads: cleanStringList(snapshot.open_threads ?? [], `${label}.open_threads`, {
      itemMaxBytes: SNAPSHOT_ITEM_MAX_BYTES,
    }),
  };
}

function normalizeSnapshots(value, label = 'character_snapshots') {
  const snapshots = asMapping(value, label);
  const normalized = {};
  const portableNames = new Set();
  for (const [rawName, rawSnapshot] of Object.entries(snapshots)) {
    const name = safeFileComponent(rawName, `${label} character name`);
    const key = portableNameKey(name);
    requireCondition(!portableNames.has(key), `${label} contains a cross-platform duplicate character ${name}`);
    portableNames.add(key);
    normalized[name] = normalizeSnapshot(rawSnapshot, `${label}.${name}`);
  }
  return normalized;
}

function renderSnapshot(name, snapshot, throughChapter, revision) {
  const section = (title, values) => [
    `## ${title}`,
    ...(values.length ? values : ['无']).map((item) => `- ${item}`),
    '',
  ];
  const lines = [
    `# ${name}｜当前状态`,
    '',
    `- 状态修订：${revision}`,
    `- 截至章节：第${throughChapter}章`,
    `- 身份：${snapshot.identity}`,
    `- 位置：${snapshot.location}`,
    `- 当前目标：${snapshot.goal}`,
    `- 身心状态：${snapshot.state}`,
    '',
    ...section('能力与资源', snapshot.abilities_resources),
    ...section('关键关系', snapshot.relationships),
    ...section('已知信息', snapshot.knowledge),
    ...section('未结事项', snapshot.open_threads),
  ];
  const payload = `${lines.join('\n').replace(/\s+$/, '')}\n`;
  const size = byteSize(payload);
  if (size > SNAPSHOT_MAX_BYTES) {
    const chars = charLen(payload);
    const allowed = Math.max(1, Math.floor((SNAPSHOT_MAX_BYTES * chars) / size));
    const counts = [
      ['能力与资源', snapshot.abilities_resources],
      ['关键关系', snapshot.relationships],
      ['已知信息', snapshot.knowledge],
      ['未结事项', snapshot.open_threads],
    ]
      .map(([title, values]) => `${title} ${values.length} 项`)
      .join('、');
    throw new TrackingError(
      `character snapshot ${name} (${size} bytes) exceeds hard cap of ${SNAPSHOT_MAX_BYTES} bytes` +
        `（现 ${chars} 字，上限约 ${allowed} 字，至少精简 ${chars - allowed} 字；` +
        `当前：${counts}。逐章经过已留在 逐章记录/，快照只保留截至当前章仍有效的状态与条目）`
    );
  }
  return payload;
}

function normalizeForeshadowChange(value, label, { allowDelete, throughChapter }) {
  const row = withAliases(asMapping(value, label), FORESHADOW_KEY_ALIASES);
  requireKnownKeys(
    row,
    new Set(['action', 'id', 'summary', 'planted_chapter', 'planned_resolution_chapter', 'status', 'importance']),
    label
  );
  const rawAction = row.action !== undefined ? row.action : 'upsert';
  const action = normalizeAction(rawAction, `${label}.action`, { allowDelete });
  const identifier = cleanText(row.id, `${label}.id`, { maxBytes: 24 });
  requireCondition(FORESHADOW_ID.test(identifier), `${label}.id must look like F001`);
  if (action === 'delete') {
    return { action, id: identifier };
  }
  const impliedKey = String(rawAction).trim().replace(/\s+/g, ' ').toLowerCase();
  const implied = FORESHADOW_ACTION_STATUS[impliedKey];
  if (implied !== undefined) {
    if (row.status === undefined || row.status === null || row.status === '') {
      row.status = implied;
    }
    const right = implied === '已回收' ? '回收了就写 status=已回收' : '只是推进、还没回收就写 status=已埋';
    requireCondition(
      row.status === implied,
      `${label}.action=${rawAction} 与 status=${row.status} 矛盾：${right}；` +
        '不是这个意思就把 action 改成 upsert 并写实际状态'
    );
  }
  const plantedChapter = asChapter(row.planted_chapter, `${label}.planted_chapter`);
  requireCondition(plantedChapter <= throughChapter, `${label}.planted_chapter cannot be in the future`);
  const plannedRaw = row.planned_resolution_chapter;
  const plannedChapter =
    plannedRaw === undefined || plannedRaw === null || plannedRaw === ''
      ? null
      : asChapter(plannedRaw, `${label}.planned_resolution_chapter`);
  requireCondition(
    plannedChapter === null || plannedChapter >= plantedChapter,
    `${label}.planned_resolution_chapter cannot precede planted_chapter`
  );
  const status = cleanText(row.status, `${label}.status`, { maxBytes: 24 });
  const importance = cleanText(row.importance, `${label}.importance`, { maxBytes: 12 });
  requireCondition(
    FORESHADOW_STATUSES.includes(status),
    `${label}.status must be one of (${FORESHADOW_STATUSES.map((s) => `'${s}'`).join(', ')})`
  );
  requireCondition(
    FORESHADOW_IMPORTANCE.includes(importance),
    `${label}.importance must be one of (${FORESHADOW_IMPORTANCE.map((s) => `'${s}'`).join(', ')})`
  );
  return {
    action,
    id: identifier,
    summary: cleanText(row.summary, `${label}.summary`, { maxBytes: 360 }),
    planted_chapter: plantedChapter,
    planned_resolution_chapter: plannedChapter,
    status,
    importance,
  };
}

function normalizeForeshadowState(value, lastChapter) {
  const rows = asMapping(value, 'tracking state.foreshadow');
  const normalized = {};
  for (const [rawId, rawRow] of Object.entries(rows)) {
    const identifier = cleanText(rawId, 'tracking state.foreshadow ID', { maxBytes: 24 });
    const row = asMapping(rawRow, `tracking state.foreshadow.${identifier}`);
    requireKnownKeys(
      row,
      new Set(['id', 'summary', 'planted_chapter', 'planned_resolution_chapter', 'status', 'importance', 'updated_chapter']),
      `tracking state.foreshadow.${identifier}`
    );
    requireCondition(row.id === identifier, `tracking state.foreshadow.${identifier}.id does not match its key`);
    const payload = { action: 'upsert' };
    for (const [k, v] of Object.entries(row)) {
      if (k !== 'updated_chapter') payload[k] = v;
    }
    const change = normalizeForeshadowChange(payload, `tracking state.foreshadow.${identifier}`, {
      allowDelete: false,
      throughChapter: lastChapter,
    });
    delete change.action;
    const updated = asInt(row.updated_chapter, `tracking state.foreshadow.${identifier}.updated_chapter`, { minimum: 1 });
    requireCondition(updated <= lastChapter, `foreshadow ${identifier} updates after current chapter`);
    change.updated_chapter = updated;
    normalized[identifier] = change;
  }
  return normalized;
}

function renderForeshadow(rows, revision) {
  const lines = [
    '# 伏笔当前状态',
    '',
    `> 状态修订：${revision}。每个 ID 只保留一行当前状态；历史变化见 \`逐章记录/\`。`,
    '',
    '| ID | 内容 | 埋设章 | 计划回收章 | 状态 | 重要度 | 最近变更章 |',
    '|---|---|---:|---:|---|---|---:|',
  ];
  for (const identifier of Object.keys(rows).sort()) {
    const row = rows[identifier];
    const planned = row.planned_resolution_chapter ? `第${row.planned_resolution_chapter}章` : '—';
    lines.push(
      `| ${identifier} | ${row.summary} | 第${row.planted_chapter}章 | ${planned} | ` +
        `${row.status} | ${row.importance} | 第${row.updated_chapter}章 |`
    );
  }
  const payload = `${lines.join('\n')}\n`;
  const size = byteSize(payload);
  requireCondition(
    size <= VIEW_HARD_CAP_BYTES,
    `foreshadow view (${size} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes`
  );
  return payload;
}

function normalizeTimelineChange(value, label, { allowDelete, throughChapter }) {
  const event = withAliases(asMapping(value, label), TIMELINE_KEY_ALIASES);
  requireKnownKeys(
    event,
    new Set(['action', 'id', 'story_time', 'objective_fact', 'reader_knowledge', 'reveal_status', 'reveal_chapter', 'characters']),
    label
  );
  const action = normalizeAction(event.action !== undefined ? event.action : 'upsert', `${label}.action`, { allowDelete });
  const identifier = cleanText(event.id, `${label}.id`, { maxBytes: 24 });
  requireCondition(EVENT_ID.test(identifier), `${label}.id must look like E001`);
  if (action === 'delete') {
    return { action, id: identifier };
  }
  const revealStatus = cleanText(event.reveal_status, `${label}.reveal_status`, { maxBytes: 24 });
  requireCondition(
    REVEAL_STATUSES.includes(revealStatus),
    `${label}.reveal_status must be one of (${REVEAL_STATUSES.map((s) => `'${s}'`).join(', ')})`
  );
  const revealRaw = event.reveal_chapter;
  const revealChapter =
    revealRaw === undefined || revealRaw === null || revealRaw === ''
      ? null
      : asChapter(revealRaw, `${label}.reveal_chapter`);
  if (revealStatus === '未揭示') {
    requireCondition(
      revealChapter === null,
      `${label} must not put a future reveal chapter in established timeline facts`
    );
  } else {
    requireCondition(revealChapter !== null, `${label}.reveal_chapter is required once revealed`);
    requireCondition(revealChapter <= throughChapter, `${label}.reveal_chapter cannot be in the future`);
  }
  return {
    action,
    id: identifier,
    story_time: cleanText(event.story_time, `${label}.story_time`, { maxBytes: 240 }),
    objective_fact: cleanText(event.objective_fact, `${label}.objective_fact`, { maxBytes: 480 }),
    reader_knowledge: cleanText(event.reader_knowledge, `${label}.reader_knowledge`, { maxBytes: 480 }),
    reveal_status: revealStatus,
    reveal_chapter: revealChapter,
    characters: cleanStringList(event.characters ?? [], `${label}.characters`, { maximum: 12, itemMaxBytes: 120 }),
  };
}

function normalizeTimelineState(value, lastChapter) {
  const events = asMapping(value, 'tracking state.timeline');
  const normalized = {};
  for (const [rawId, rawEvent] of Object.entries(events)) {
    const identifier = cleanText(rawId, 'tracking state.timeline ID', { maxBytes: 24 });
    const event = asMapping(rawEvent, `tracking state.timeline.${identifier}`);
    requireKnownKeys(
      event,
      new Set([
        'id', 'story_time', 'objective_fact', 'reader_knowledge', 'reveal_status', 'reveal_chapter',
        'characters', 'first_recorded_chapter', 'updated_chapter',
      ]),
      `tracking state.timeline.${identifier}`
    );
    requireCondition(event.id === identifier, `tracking state.timeline.${identifier}.id does not match its key`);
    const payload = { action: 'upsert' };
    for (const [k, v] of Object.entries(event)) {
      if (k !== 'first_recorded_chapter' && k !== 'updated_chapter') payload[k] = v;
    }
    const change = normalizeTimelineChange(payload, `tracking state.timeline.${identifier}`, {
      allowDelete: false,
      throughChapter: lastChapter,
    });
    delete change.action;
    const first = asInt(event.first_recorded_chapter, `tracking state.timeline.${identifier}.first_recorded_chapter`, { minimum: 1 });
    const updated = asInt(event.updated_chapter, `tracking state.timeline.${identifier}.updated_chapter`, { minimum: 1 });
    requireCondition(first <= lastChapter, `timeline event ${identifier} starts after current chapter`);
    requireCondition(updated <= lastChapter, `timeline event ${identifier} updates after current chapter`);
    change.first_recorded_chapter = first;
    change.updated_chapter = updated;
    normalized[identifier] = change;
  }
  return normalized;
}

function renderTimelineViews(events, revision) {
  const authorLines = [
    '# 作者真相时间线',
    '',
    `> 状态修订：${revision}。客观事实与读者认知的权威对照；未来揭示计划仍留在大纲。`,
    '',
    '| ID | 首次登记章 | 故事时间 | 客观事实 | 读者当前认知 | 揭示状态 | 实际揭示章 |',
    '|---|---:|---|---|---|---|---:|',
  ];
  const readerLines = [
    '# 读者已知时间线',
    '',
    `> 状态修订：${revision}。只呈现读者截至当前章节已经知道或相信的内容，不泄露作者侧客观真相。`,
    '',
    '| ID | 读者当前认知 | 认知截至章 |',
    '|---|---|---:|',
  ];
  for (const identifier of Object.keys(events).sort()) {
    const event = events[identifier];
    const reveal = event.reveal_chapter ? `第${event.reveal_chapter}章` : '—';
    const characters = (event.characters || []).join('、');
    const objective = event.objective_fact + (characters ? `（涉及：${characters}）` : '');
    authorLines.push(
      `| ${identifier} | 第${event.first_recorded_chapter}章 | ${event.story_time} | ${objective} | ` +
        `${event.reader_knowledge} | ${event.reveal_status} | ${reveal} |`
    );
    readerLines.push(`| ${identifier} | ${event.reader_knowledge} | 第${event.updated_chapter}章 |`);
  }
  const author = `${authorLines.join('\n')}\n`;
  const reader = `${readerLines.join('\n')}\n`;
  requireCondition(
    byteSize(author) <= VIEW_HARD_CAP_BYTES,
    `author timeline view (${byteSize(author)} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes`
  );
  requireCondition(
    byteSize(reader) <= VIEW_HARD_CAP_BYTES,
    `reader timeline view (${byteSize(reader)} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes`
  );
  return { author, reader };
}

function validateContextInput(value, { includeInitialFields }) {
  const context = asMapping(value, 'context');
  const allowed = new Set(['position', 'long_term_constraints', 'active_character_names', 'continuity_risks']);
  if (includeInitialFields) {
    allowed.add('recent_chapters');
    allowed.add('next_chapter_commitments');
  }
  requireKnownKeys(context, allowed, 'context');
  const activeNames = asList(context.active_character_names ?? [], 'context.active_character_names').map(
    (name, idx) => safeFileComponent(name, `context.active_character_names[${idx}]`)
  );
  const normalized = {
    position: validatePosition(context.position),
    long_term_constraints: cleanStringList(context.long_term_constraints ?? [], 'context.long_term_constraints', {
      maximum: 6,
    }),
    active_character_names: activeNames,
    continuity_risks: cleanStringList(context.continuity_risks ?? [], 'context.continuity_risks', { maximum: 5 }),
  };
  if (normalized.active_character_names.length > ACTIVE_CHARACTER_MAX) {
    addSoftWarning(
      `context.active_character_names has ${normalized.active_character_names.length} names` +
        `（建议最多 ${ACTIVE_CHARACTER_MAX} 人，不影响本次提交）`
    );
  }
  const keySet = new Set(normalized.active_character_names.map(portableNameKey));
  requireCondition(
    keySet.size === normalized.active_character_names.length,
    'context.active_character_names contains cross-platform duplicates'
  );
  if (includeInitialFields) {
    const recent = asList(context.recent_chapters ?? [], 'context.recent_chapters').map((rawItem, idx) => {
      const item = asMapping(rawItem, `context.recent_chapters[${idx}]`);
      requireKnownKeys(item, new Set(['chapter', 'summary']), `context.recent_chapters[${idx}]`);
      return {
        chapter: asInt(item.chapter, `context.recent_chapters[${idx}].chapter`, { minimum: 1 }),
        summary: cleanText(item.summary, `context.recent_chapters[${idx}].summary`, { maxBytes: 360 }),
      };
    });
    if (recent.length > 3) {
      addSoftWarning(`context.recent_chapters has ${recent.length} items（建议最多 3 项，不影响本次提交）`);
    }
    normalized.recent_chapters = recent;
    normalized.next_chapter_commitments = cleanStringList(
      context.next_chapter_commitments ?? [],
      'context.next_chapter_commitments',
      { maximum: 5 }
    );
  }
  return normalized;
}

function activeForeshadowLines(rows) {
  const importance = Object.fromEntries(FORESHADOW_IMPORTANCE.map((v, i) => [v, i]));
  const candidates = Object.values(rows).filter((row) => row.status === '已埋');
  candidates.sort((a, b) => {
    const imp = importance[a.importance] - importance[b.importance];
    if (imp !== 0) return imp;
    const pa = a.planned_resolution_chapter || 1e12;
    const pb = b.planned_resolution_chapter || 1e12;
    if (pa !== pb) return pa - pb;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  return candidates.slice(0, 8).map((row) => {
    const planned = row.planned_resolution_chapter ? `第${row.planned_resolution_chapter}章` : '回收章未定';
    return `${row.id}｜${row.summary}｜埋第${row.planted_chapter}章｜${planned}｜${row.importance}`;
  });
}

function renderContext(state) {
  const context = state.context;
  const position = context.position;
  const currentChapter = state.last_committed_chapter === 0 ? '尚未开篇' : `第${state.last_committed_chapter}章`;
  const characterLines = context.active_character_names.map(
    (name) =>
      `${name}｜${state.characters[name].identity}｜${state.characters[name].state}｜目标：${state.characters[name].goal}`
  );
  const sections = [
    [
      '## 当前位置',
      [
        `当前章：${currentChapter}`,
        `卷：${position.volume}（始于第${position.volume_start_chapter}章）`,
        `故事时间：${position.story_time}`,
        `场景：${position.scene}`,
      ],
    ],
    ['## 长期约束', context.long_term_constraints],
    ['## 核心角色状态', characterLines],
    ['## 活跃伏笔', activeForeshadowLines(state.foreshadow)],
    ['## 近三章速记', context.recent_chapters.map((item) => `第${item.chapter}章｜${item.summary}`)],
    ['## 下一章承诺', context.next_chapter_commitments],
    ['## 连贯性风险', context.continuity_risks],
  ];
  const lines = [
    `# 写作连续性上下文 — ${state.book_title}`,
    '',
    `> 状态修订：${state.state_revision}。截至当前章的续写状态卡，只放下一章真正需要的连续性状态。`,
    '',
  ];
  for (const [heading, values] of sections) {
    lines.push(heading);
    for (const val of values.length ? values : ['无']) {
      lines.push(`- ${val}`);
    }
    lines.push('');
  }
  const payload = `${lines.join('\n').replace(/\s+$/, '')}\n`;
  const headings = payload.split('\n').filter((line) => line.startsWith('## '));
  const headingsMatch =
    headings.length === CONTEXT_HEADINGS.length && headings.every((h, idx) => h === CONTEXT_HEADINGS[idx]);
  requireCondition(headingsMatch, 'generated context headings do not match the seven-section schema');
  const contextSize = byteSize(payload);
  requireCondition(
    contextSize <= VIEW_HARD_CAP_BYTES,
    `hot context (${contextSize} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes`
  );
  return payload;
}

function normalizeDelta(value, { throughChapter, snapshots, existingCoreNames }) {
  const delta = asMapping(value, 'delta');
  requireKnownKeys(
    delta,
    new Set([
      'result', 'character_changes', 'foreshadow_changes', 'timeline_events', 'constraints',
      'next_chapter_commitments', 'retired_context_items', 'retired_characters',
    ]),
    'delta'
  );
  const retiredCharacters = asList(delta.retired_characters ?? [], 'delta.retired_characters').map((name, idx) =>
    safeFileComponent(name, `delta.retired_characters[${idx}]`)
  );
  const retiredKeys = retiredCharacters.map(portableNameKey);
  requireCondition(
    retiredKeys.length === new Set(retiredKeys).size,
    'delta.retired_characters contains duplicate characters'
  );
  const retiring = new Set(retiredKeys);
  const characterChanges = [];
  const rawChanges = asList(delta.character_changes ?? [], 'delta.character_changes');
  for (let index = 0; index < rawChanges.length; index += 1) {
    const change = asMapping(rawChanges[index], `delta.character_changes[${index}]`);
    requireKnownKeys(change, new Set(['name', 'change']), `delta.character_changes[${index}]`);
    const name = safeFileComponent(change.name, `delta.character_changes[${index}].name`);
    const existing = existingCoreNames.get(portableNameKey(name));
    const isCore = Object.prototype.hasOwnProperty.call(snapshots, name) || existing !== undefined;
    requireCondition(
      !isCore || Object.prototype.hasOwnProperty.call(snapshots, name) || retiring.has(portableNameKey(name)),
      `core character ${name} changed but has no current snapshot: 把 draft 输出 current_snapshots` +
        `（或 snapshot_files 里的 ${name}.json）中「${name}」的快照整份改成本章结束时的状态，放进 character_snapshots`
    );
    characterChanges.push({
      name,
      change: cleanText(change.change, `delta.character_changes[${index}].change`, { maxBytes: 360 }),
    });
  }
  const charKeys = characterChanges.map((item) => portableNameKey(item.name));
  requireCondition(
    charKeys.length === new Set(charKeys).size,
    'delta.character_changes contains duplicate characters'
  );
  const foreshadowChanges = asList(delta.foreshadow_changes ?? [], 'delta.foreshadow_changes').map((raw, idx) =>
    normalizeForeshadowChange(raw, `delta.foreshadow_changes[${idx}]`, { allowDelete: true, throughChapter })
  );
  const timelineEvents = asList(delta.timeline_events ?? [], 'delta.timeline_events').map((raw, idx) =>
    normalizeTimelineChange(raw, `delta.timeline_events[${idx}]`, { allowDelete: true, throughChapter })
  );
  requireCondition(
    new Set(foreshadowChanges.map((item) => item.id)).size === foreshadowChanges.length,
    'delta.foreshadow_changes contains duplicate IDs'
  );
  requireCondition(
    new Set(timelineEvents.map((item) => item.id)).size === timelineEvents.length,
    'delta.timeline_events contains duplicate IDs'
  );
  const changedNames = new Set(characterChanges.map((item) => item.name));
  requireCondition(
    Object.keys(snapshots).every((name) => changedNames.has(name)),
    'character_snapshots must contain exactly the core characters changed by this transaction'
  );
  return {
    result: cleanText(delta.result, 'delta.result', { maxBytes: 480 }),
    character_changes: characterChanges,
    foreshadow_changes: foreshadowChanges,
    timeline_events: timelineEvents,
    constraints: cleanStringList(delta.constraints ?? [], 'delta.constraints', { maximum: 6 }),
    next_chapter_commitments: cleanStringList(delta.next_chapter_commitments ?? [], 'delta.next_chapter_commitments', {
      maximum: 5,
    }),
    retired_context_items: cleanStringList(delta.retired_context_items ?? [], 'delta.retired_context_items', {
      maximum: 11,
    }),
    retired_characters: retiredCharacters,
  };
}

function renderCommitments(commitments) {
  if (commitments.some((item) => item.includes('；'))) {
    return ['- 下一章承诺：', ...commitments.map((item) => `  - ${item}`)];
  }
  return [`- 下一章承诺：${commitments.join('；') || '无'}`];
}

function renderDelta(chapter, title, delta, coreNames) {
  const lines = [
    `# 第${padChapter(chapter)}章 · ${title}`,
    `- 结果：${delta.result}`,
    ...renderCommitments(delta.next_chapter_commitments),
    '',
    '## 角色变化',
  ];
  if (delta.character_changes.length) {
    for (const item of delta.character_changes) {
      lines.push(`- ${item.name}｜${coreNames.has(item.name) ? '核心' : '临时'}｜${item.change}`);
    }
  } else {
    lines.push('- 无');
  }
  lines.push('', '## 伏笔变化');
  if (delta.foreshadow_changes.length) {
    for (const item of delta.foreshadow_changes) {
      if (item.action === 'delete') {
        lines.push(`- ${item.id}｜删除当前登记`);
      } else {
        const planned = item.planned_resolution_chapter ? `第${item.planned_resolution_chapter}章` : '未定';
        lines.push(`- ${item.id}｜${item.status}｜${item.summary}｜回收${planned}`);
      }
    }
  } else {
    lines.push('- 无');
  }
  lines.push('', '## 时间与揭示');
  if (delta.timeline_events.length) {
    for (const item of delta.timeline_events) {
      if (item.action === 'delete') {
        lines.push(`- ${item.id}｜删除当前登记`);
      } else {
        lines.push(
          `- ${item.id}｜${item.story_time}｜事实：${item.objective_fact}｜` +
            `读者：${item.reader_knowledge}｜${item.reveal_status}`
        );
      }
    }
  } else {
    lines.push('- 无');
  }
  lines.push('', '## 连贯性约束');
  if (delta.constraints.length) {
    for (const item of delta.constraints) lines.push(`- ${item}`);
  } else {
    lines.push('- 无');
  }
  const retired = [
    ...(delta.retired_context_items || []),
    ...(delta.retired_characters || []).map((name) => `角色状态：${name}`),
  ];
  if (retired.length) {
    lines.push('', '## 本章退役登记');
    for (const item of retired) lines.push(`- ${item}`);
  }
  const payload = `${lines.join('\n')}\n`;
  const size = byteSize(payload);
  if (size > VIEW_HARD_CAP_BYTES) {
    const longest = lines
      .filter((line) => line.startsWith('- '))
      .sort((a, b) => charLen(b) - charLen(a))
      .slice(0, 3);
    const chars = charLen(payload);
    const allowed = Math.floor((VIEW_HARD_CAP_BYTES * chars) / size);
    const summary = longest
      .map((line) => `${Array.from(line).slice(2, 18).join('')}…（${charLen(line) - 2} 字）`)
      .join('；');
    throw new TrackingError(
      `chapter delta (${size} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes（逐章记录现 ${chars} 字，` +
        `安全上限约 ${allowed} 字，至少压缩 ${chars - allowed} 字；最长几项：${summary}）`
    );
  }
  return payload;
}

function normalizeWordcountRecords(value, lastChapter) {
  const records = asMapping(value, 'tracking state.wordcount_records');
  const normalized = {};
  for (const [rawChapter, rawRecord] of Object.entries(records)) {
    requireCondition(/^[1-9]\d*$/.test(rawChapter), 'wordcount record chapter key is invalid');
    const chapter = Number(rawChapter);
    requireCondition(chapter <= lastChapter, 'wordcount record exceeds last committed chapter');
    normalized[rawChapter] = wordcountValue(wordcountCore.normalizeWordcountRecord, rawRecord);
  }
  return normalized;
}

function normalizeState(document) {
  const root = asMapping(document, 'tracking state');
  requireKnownKeys(
    root,
    new Set([
      'schema_version', 'book_title', 'last_committed_chapter', 'imported_through_chapter',
      'state_revision', 'context', 'characters', 'foreshadow', 'timeline', 'wordcount_records',
    ]),
    'tracking state'
  );
  requireCondition(root.schema_version === TRACKING_SCHEMA_VERSION, 'tracking state schema is unsupported');
  const lastChapter = asInt(root.last_committed_chapter, 'tracking state.last_committed_chapter');
  const importedThrough = asInt(root.imported_through_chapter, 'tracking state.imported_through_chapter');
  requireCondition(importedThrough <= lastChapter, 'imported chapter cutoff exceeds current chapter');
  const context = validateContextInput(root.context, { includeInitialFields: true });
  requireCondition(
    context.position.volume_start_chapter <= Math.max(1, lastChapter),
    'context.position.volume_start_chapter is after the current writing position'
  );
  const recentNumbers = context.recent_chapters.map((item) => item.chapter);
  const sortedRecent = [...recentNumbers].sort((a, b) => a - b);
  requireCondition(
    recentNumbers.every((n, i) => n === sortedRecent[i]),
    'context.recent_chapters must be ordered'
  );
  requireCondition(new Set(recentNumbers).size === recentNumbers.length, 'context.recent_chapters contains duplicates');
  requireCondition(
    recentNumbers.every((ch) => ch <= lastChapter),
    'context.recent_chapters cannot include future chapters'
  );
  const characters = normalizeSnapshots(root.characters ?? {}, 'tracking state.characters');
  for (const name of context.active_character_names) {
    requireCondition(
      Object.prototype.hasOwnProperty.call(characters, name),
      `active core character ${name} has no current snapshot`
    );
  }
  const foreshadow = normalizeForeshadowState(root.foreshadow ?? {}, lastChapter);
  const timeline = normalizeTimelineState(root.timeline ?? {}, lastChapter);
  if (lastChapter === 0) {
    requireCondition(Object.keys(foreshadow).length === 0, 'a chapter-0 project cannot have planted foreshadow facts');
    requireCondition(Object.keys(timeline).length === 0, 'a chapter-0 project cannot have established timeline facts');
  }
  const stateRevision = asInt(root.state_revision, 'tracking state.state_revision');
  const wordcountRecords = normalizeWordcountRecords(root.wordcount_records ?? {}, lastChapter);
  return {
    schema_version: TRACKING_SCHEMA_VERSION,
    book_title: cleanText(root.book_title, 'tracking state.book_title', { maxBytes: 240 }),
    last_committed_chapter: lastChapter,
    imported_through_chapter: importedThrough,
    state_revision: stateRevision,
    context,
    characters,
    foreshadow,
    timeline,
    wordcount_records: wordcountRecords,
  };
}

function loadState(project) {
  const filePath = statePath(project);
  requireCondition(exists(filePath), 'tracking state is missing; run init first');
  return normalizeState(readJson(filePath));
}

function normalizeInitialDocument(document, warningsOut = null) {
  _softWarnings = [];
  let stateDoc;
  let warnings;
  try {
    stateDoc = _normalizeInitialDocument(document);
  } finally {
    warnings = _softWarnings;
    _softWarnings = null;
  }
  if (warningsOut) warningsOut.push(...warnings);
  return normalizeState(stateDoc);
}

function _normalizeInitialDocument(document) {
  const root = asMapping(document, 'init input');
  requireKnownKeys(
    root,
    new Set([
      'schema_version', 'book_title', 'last_chapter', 'context', 'character_snapshots', 'foreshadow', 'timeline_events',
    ]),
    'init input'
  );
  requireCondition(root.schema_version === INPUT_SCHEMA_VERSION, 'init input schema_version is unsupported');
  const lastChapter = asInt(root.last_chapter, 'last_chapter');
  const bookTitle = cleanText(root.book_title, 'book_title', { maxBytes: 240 });
  const context = validateContextInput(root.context, { includeInitialFields: true });
  const snapshots = normalizeSnapshots(root.character_snapshots ?? {});
  const foreshadow = {};
  const rawForeshadow = asList(root.foreshadow ?? [], 'foreshadow');
  for (let index = 0; index < rawForeshadow.length; index += 1) {
    const row = normalizeForeshadowChange(rawForeshadow[index], `foreshadow[${index}]`, {
      allowDelete: false,
      throughChapter: lastChapter,
    });
    requireCondition(!Object.prototype.hasOwnProperty.call(foreshadow, row.id), `duplicate foreshadow ID ${row.id}`);
    delete row.action;
    row.updated_chapter = Math.max(1, lastChapter);
    foreshadow[row.id] = row;
  }
  const timeline = {};
  const rawTimeline = asList(root.timeline_events ?? [], 'timeline_events');
  for (let index = 0; index < rawTimeline.length; index += 1) {
    const event = normalizeTimelineChange(rawTimeline[index], `timeline_events[${index}]`, {
      allowDelete: false,
      throughChapter: lastChapter,
    });
    requireCondition(!Object.prototype.hasOwnProperty.call(timeline, event.id), `duplicate timeline event ID ${event.id}`);
    delete event.action;
    event.first_recorded_chapter = Math.max(1, lastChapter);
    event.updated_chapter = Math.max(1, lastChapter);
    timeline[event.id] = event;
  }
  return {
    schema_version: TRACKING_SCHEMA_VERSION,
    book_title: bookTitle,
    last_committed_chapter: lastChapter,
    imported_through_chapter: lastChapter,
    state_revision: 0,
    context,
    characters: snapshots,
    foreshadow,
    timeline,
    wordcount_records: {},
  };
}

function recountRevisedChapter(project, chapter, previous, drift) {
  const resolutions = ['within_user_band'];
  if (previous.resolution === 'accepted_current_length') {
    resolutions.push('accepted_current_length');
  }
  for (const resolution of resolutions) {
    try {
      return wordcountCore.buildProjectWordcountRecord(project, chapter, {
        resolution,
        authorRange: previous.author_range ?? null,
      });
    } catch (err) {
      if (err instanceof wordcountCore.WordcountError) continue;
      throw err;
    }
  }
  throw new TrackingError(`第${chapter}章${drift.join('和')}已改，字数出了作者范围；${RECOUNT_HINT}`);
}

function normalizeTransaction(project, state, document, { allowGap = false, warningsOut = null } = {}) {
  _softWarnings = [];
  let transaction;
  let warnings;
  try {
    transaction = _normalizeTransaction(project, state, document, { allowGap });
  } finally {
    warnings = _softWarnings;
    _softWarnings = null;
  }
  if (warningsOut) warningsOut.push(...warnings);
  return transaction;
}

function _normalizeTransaction(project, state, document, { allowGap = false } = {}) {
  const root = asMapping(document, 'transaction');
  requireKnownKeys(
    root,
    new Set([
      'schema_version', 'mode', 'chapter', 'chapter_title', 'expected_state_revision',
      'delta', 'context', 'character_snapshots', 'wordcount',
    ]),
    'transaction'
  );
  requireCondition(root.schema_version === INPUT_SCHEMA_VERSION, 'transaction schema_version is unsupported');
  const mode = cleanText(root.mode, 'mode', { maxBytes: 24 });
  requireCondition(mode === 'append' || mode === 'revision', 'mode must be append or revision');
  const chapter = asInt(root.chapter, 'chapter', { minimum: 1 });
  const expectedRevision = asInt(root.expected_state_revision, 'expected_state_revision');
  const wordcountInput = root.wordcount;
  requireCondition(expectedRevision === state.state_revision, 'tracking state changed since this transaction was prepared');
  const last = state.last_committed_chapter;
  if (mode === 'append') {
    if (allowGap) {
      if (chapter > last + 1) {
        const skippedRange = chapter - 1 > last + 1 ? `第${last + 1}-${chapter - 1}章` : `第${last + 1}章`;
        addSoftWarning(
          `跳章提交：当前最后提交章为第${last}章，本次直接提交第${chapter}章（跳过${skippedRange}）`
        );
      } else if (chapter <= last) {
        const targetDelta = deltaPath(trackingRoot(project), chapter);
        requireCondition(
          chapter > state.imported_through_chapter && !exists(targetDelta),
          `chapter ${chapter} is already committed; use mode=revision`
        );
        addSoftWarning(`补交跳过章节：当前最后提交章为第${last}章，本次补交第${chapter}章`);
      }
    } else {
      requireCondition(
        chapter === last + 1,
        `append chapter must be ${last + 1}, got ${chapter}（如有意跳章提交，请加 --allow-gap）`
      );
    }
  } else {
    requireCondition(chapter <= last, `cannot revise unwritten chapter ${chapter}; last committed chapter is ${last}`);
  }
  const context = validateContextInput(root.context, { includeInitialFields: false });
  const snapshots = normalizeSnapshots(root.character_snapshots ?? {});
  const existingNames = new Map();
  for (const name of Object.keys(state.characters)) {
    existingNames.set(portableNameKey(name), name);
  }
  for (const name of Object.keys(snapshots)) {
    const existing = existingNames.get(portableNameKey(name));
    requireCondition(
      existing === undefined || existing === name,
      `character ${name} conflicts with existing character ${existing}`
    );
  }
  const throughChapter = mode === 'append' ? Math.max(chapter, last) : last;
  const delta = normalizeDelta(root.delta, {
    throughChapter,
    snapshots,
    existingCoreNames: existingNames,
  });
  let wordcount = null;
  if (wordcountInput !== undefined && wordcountInput !== null) {
    wordcount = wordcountValue(wordcountCore.validateCurrentWordcountRecord, project, chapter, wordcountInput);
  } else if (mode === 'revision' && Object.prototype.hasOwnProperty.call(state.wordcount_records, String(chapter))) {
    const previous = state.wordcount_records[String(chapter)];
    let drift;
    try {
      drift = wordcountCore.wordcountRecordDrift(project, chapter, previous);
    } catch (err) {
      if (err instanceof wordcountCore.WordcountError) {
        throw new TrackingError(`第${chapter}章的字数记录无法核对（${err.message}）；${RECOUNT_HINT}`);
      }
      throw err;
    }
    if (drift.length) {
      wordcount = recountRevisedChapter(project, chapter, previous, drift);
    }
  }
  return {
    mode,
    chapter,
    title: cleanText(root.chapter_title, 'chapter_title', { maxBytes: 240 }),
    delta,
    context,
    snapshots,
    wordcount,
  };
}

function checkpointRecord(change, chapter, previous, { keepFirstChapter = false } = {}) {
  const current = {};
  for (const [k, v] of Object.entries(change)) {
    if (k !== 'action') current[k] = v;
  }
  current.updated_chapter = Math.max(previous ? previous.updated_chapter : chapter, chapter);
  if (keepFirstChapter) {
    current.first_recorded_chapter = previous ? previous.first_recorded_chapter : chapter;
  }
  return current;
}

function mergeTransaction(state, transaction) {
  const nextState = deepClone(state);
  const chapter = transaction.chapter;
  if (transaction.mode === 'append') {
    nextState.last_committed_chapter = Math.max(state.last_committed_chapter, chapter);
  }
  nextState.state_revision += 1;
  Object.assign(nextState.characters, transaction.snapshots);
  if (transaction.wordcount !== null) {
    nextState.wordcount_records[String(chapter)] = transaction.wordcount;
  }

  const nextContext = transaction.context;
  const isRevision = transaction.mode === 'revision';
  requireCondition(
    !(isRevision && transaction.delta.retired_characters.length > 0),
    'retired_characters must be committed in an append transaction, not a revision'
  );
  for (const name of transaction.delta.retired_characters) {
    requireCondition(
      Object.prototype.hasOwnProperty.call(nextState.characters, name),
      `retired character ${name} has no current snapshot`
    );
    requireCondition(
      !Object.prototype.hasOwnProperty.call(transaction.snapshots, name),
      `character ${name} cannot be retired and updated in the same transaction`
    );
    requireCondition(
      !nextContext.active_character_names.includes(name),
      `retired character ${name} is still listed in context.active_character_names`
    );
    delete nextState.characters[name];
  }

  const previousItems = new Set([
    ...state.context.long_term_constraints,
    ...state.context.continuity_risks,
  ]);
  const kept = new Set([
    ...nextContext.long_term_constraints,
    ...nextContext.continuity_risks,
  ]);
  const dropped = [...previousItems].filter((item) => !kept.has(item)).sort();
  const stillListed = [...new Set(transaction.delta.retired_context_items)].filter((item) => kept.has(item)).sort();
  requireCondition(
    stillListed.length === 0,
    'delta.retired_context_items lists items that are still in context; remove them from context: ' +
      stillListed.join('；')
  );
  const retiredSet = new Set(transaction.delta.retired_context_items);
  const undeclared = dropped.filter((item) => !retiredSet.has(item)).sort();
  requireCondition(
    undeclared.length === 0,
    'context items were dropped without being declared in delta.retired_context_items: ' + undeclared.join('；')
  );
  transaction.delta.retired_context_items = dropped;

  for (const change of transaction.delta.foreshadow_changes) {
    if (change.action === 'delete') {
      delete nextState.foreshadow[change.id];
    } else {
      nextState.foreshadow[change.id] = checkpointRecord(change, chapter, nextState.foreshadow[change.id] || null);
    }
  }
  for (const change of transaction.delta.timeline_events) {
    if (change.action === 'delete') {
      delete nextState.timeline[change.id];
    } else {
      nextState.timeline[change.id] = checkpointRecord(change, chapter, nextState.timeline[change.id] || null, {
        keepFirstChapter: true,
      });
    }
  }

  const recentByChapter = new Map(state.context.recent_chapters.map((item) => [item.chapter, item]));
  if (recentByChapter.has(chapter) || transaction.mode === 'append') {
    recentByChapter.set(chapter, { chapter, summary: transaction.delta.result });
  }
  const recent = [...recentByChapter.values()].sort((a, b) => a.chapter - b.chapter).slice(-3);
  const currentLast = nextState.last_committed_chapter;
  const nextCommitments =
    (transaction.mode === 'append' && chapter >= currentLast) || chapter === currentLast
      ? transaction.delta.next_chapter_commitments
      : state.context.next_chapter_commitments;
  nextState.context = {
    ...nextContext,
    recent_chapters: recent,
    next_chapter_commitments: nextCommitments,
  };
  return normalizeState(nextState);
}

function renderViews(state) {
  const revision = state.state_revision;
  const views = {
    '上下文.md': renderContext(state),
    '伏笔.md': renderForeshadow(state.foreshadow, revision),
  };
  const { author, reader } = renderTimelineViews(state.timeline, revision);
  views['时间线/作者真相.md'] = author;
  views['时间线/读者已知.md'] = reader;
  for (const [name, snapshot] of Object.entries(state.characters)) {
    views[`角色状态/${name}.md`] = renderSnapshot(name, snapshot, state.last_committed_chapter, revision);
  }
  return views;
}

function writeViews(tracking, views) {
  writeIfChanged(path.join(tracking, '上下文.md'), views['上下文.md']);
  for (const relative of Object.keys(views).filter((p) => p !== '上下文.md').sort()) {
    writeIfChanged(path.join(tracking, relative), views[relative]);
  }
  const expectedCharFiles = new Set(
    Object.keys(views)
      .filter((rel) => rel.startsWith('角色状态/'))
      .map((rel) => path.basename(rel))
  );
  const charDir = path.join(tracking, '角色状态');
  fs.mkdirSync(charDir, { recursive: true });
  for (const name of fs.readdirSync(charDir)) {
    if (name.endsWith('.md') && !expectedCharFiles.has(name)) {
      fs.unlinkSync(path.join(charDir, name));
    }
  }
}

function emitWarning(message, warningsOut = null) {
  if (warningsOut && !warningsOut.includes(message)) {
    warningsOut.push(message);
  }
  emit(`WARNING: ${message}`, { error: true });
}

function warnSizes(views, deltaPayload = null, warningsOut = null) {
  if (deltaPayload !== null) {
    const deltaSize = byteSize(deltaPayload);
    if (deltaSize > DELTA_MAX_BYTES) {
      emitWarning(
        `chapter delta is ${deltaSize} bytes; target is <= ${DELTA_TARGET_BYTES} bytes（约 682 字），recommended cap is <= ${DELTA_MAX_BYTES} bytes（约 1194 字，不影响本次提交，建议后续精简）`,
        warningsOut
      );
    } else if (deltaSize > DELTA_TARGET_BYTES) {
      emitWarning(
        `chapter delta is ${deltaSize} bytes; target is <= ${DELTA_TARGET_BYTES} bytes（约 682 字，软上限 ${DELTA_MAX_BYTES} 字节 / 约 1194 字）`,
        warningsOut
      );
    }
  }
  const contextSize = byteSize(views['上下文.md']);
  if (contextSize > CONTEXT_MAX_BYTES) {
    emitWarning(
      `hot context is ${contextSize} bytes; recommended cap is <= ${CONTEXT_MAX_BYTES} bytes（不影响本次提交，建议精简活跃角色或状态行）`,
      warningsOut
    );
  } else if (contextSize > CONTEXT_TARGET_BYTES) {
    emitWarning(`hot context is ${contextSize} bytes; target is <= ${CONTEXT_TARGET_BYTES}`, warningsOut);
  }
  for (const [relative, payload] of Object.entries(views)) {
    if (!relative.startsWith('角色状态/')) continue;
    const size = byteSize(payload);
    if (size > SNAPSHOT_TARGET_BYTES) {
      const chars = charLen(payload);
      const targetChars = Math.max(1, Math.floor((SNAPSHOT_TARGET_BYTES * chars) / size));
      const stem = path.basename(relative, '.md');
      emitWarning(
        `character snapshot ${stem} is ${size} bytes; target is <= ${SNAPSHOT_TARGET_BYTES}` +
          `（现 ${chars} 字，建议目标约 ${targetChars} 字；不影响本次提交，` +
          '后续更新时可将已了结事项或已被新状态取代的旧阶段归并为当前值）',
        warningsOut
      );
    }
  }
}

function warnEmptiedSnapshots(previousCharacters, updatedSnapshots, warningsOut = null) {
  const labels = {
    abilities_resources: '能力与资源',
    relationships: '关键关系',
    knowledge: '已知信息',
  };
  for (const [name, updated] of Object.entries(updatedSnapshots)) {
    const previous = previousCharacters[name];
    if (!previous) continue;
    const emptied = [];
    for (const [key, label] of Object.entries(labels)) {
      if (previous[key] && previous[key].length && (!updated[key] || !updated[key].length)) {
        emptied.push(`${label}（原有 ${previous[key].length} 项）`);
      }
    }
    if (emptied.length) {
      emitWarning(
        `角色快照「${name}」把 ${emptied.join('、')}` +
          ' 清空成了空列表；character_snapshots 提交的是角色完整当前状态，不是只写本章新增。' +
          '若非有意清空，请从 draft 的 snapshot_files 读回完整快照修改后重提。',
        warningsOut
      );
    }
  }
}

function warnEmptiedRecord(chapter, previous, delta, warningsOut = null) {
  const labels = {
    character_changes: '角色变化',
    foreshadow_changes: '伏笔变化',
    timeline_events: '时间与揭示',
    constraints: '连贯性约束',
    next_chapter_commitments: '下一章承诺',
  };
  const emptied = [];
  for (const [key, label] of Object.entries(labels)) {
    if (previous[key] && previous[key].length && (!delta[key] || !delta[key].length)) {
      emptied.push(`${label}（原有 ${previous[key].length} 项）`);
    }
  }
  if (emptied.length) {
    emitWarning(
      `第${chapter}章修订把逐章记录的 ${emptied.join('、')}` +
        ' 清空了；修订的 delta 是本章完整记录，不是只写改动。不是有意删除就用 draft 重新预填后再提交。',
      warningsOut
    );
  }
}

function initializeLocked(project, document, { warningsOut = null } = {}) {
  const tracking = trackingRoot(project);
  requireCondition(!exists(statePath(project)), 'tracking state already exists; init never overwrites project state');
  const softWarnings = [];
  const state = normalizeInitialDocument(document, softWarnings);
  const views = renderViews(state);
  const statePayload = jsonPayload(state);
  const archived = archiveRetiredTrackingPaths(tracking);
  for (const sub of ['逐章记录', '角色状态', '时间线']) {
    fs.mkdirSync(path.join(tracking, sub), { recursive: true });
  }
  writeViews(tracking, views);
  _hooks.atomicWriteText(statePath(project), statePayload);
  for (const msg of softWarnings) emitWarning(msg, warningsOut);
  warnSizes(views, null, warningsOut);
  if (archived.length) {
    emit(
      `NOTE: 旧追踪结构已原样移入 追踪/${RETIRED_ARCHIVE_DIR}/：${archived.join(', ')}；` +
        '当前状态以本次 init 输入为准，旧文件不参与解析。',
      { error: true }
    );
  }
  return state;
}

function initialize(project, document, options = {}) {
  return withProjectWriteLock(project, () => initializeLocked(project, document, options));
}

function parseChapterRecord(filePath) {
  let text;
  try {
    ({ text } = wordcountCore.readUtf8Strict(filePath));
  } catch {
    return null;
  }
  const record = {
    title: '',
    result: '',
    next_chapter_commitments: [],
    character_changes: [],
    foreshadow_changes: [],
    timeline_events: [],
    constraints: [],
    retired: [],
  };
  let section = null;
  let inCommitments = false;
  for (const line of text.replace(/\r\n/g, '\n').split('\n')) {
    const heading = /^# 第\d+章 · (.+)$/.exec(line);
    if (heading && !record.title) {
      record.title = heading[1].trim();
      continue;
    }
    if (line.startsWith('## ')) {
      section = RECORD_SECTIONS[line.slice(3).trim()] || null;
      inCommitments = false;
      continue;
    }
    if (inCommitments && line.startsWith('  - ')) {
      record.next_chapter_commitments.push(line.slice(4));
      continue;
    }
    inCommitments = false;
    if (!line.startsWith('- ')) continue;
    const item = line.slice(2);
    if (section === null) {
      if (item.startsWith('结果：')) {
        record.result = item.slice('结果：'.length);
      } else if (item.startsWith('下一章承诺：')) {
        const value = item.slice('下一章承诺：'.length);
        inCommitments = value === '';
        record.next_chapter_commitments = value === '无' || value === '' ? [] : value.split('；');
      }
      continue;
    }
    if (item === '无' && section !== 'retired') continue;
    record[section].push(item);
  }
  return record;
}

function applyTransactionLocked(project, document, { allowGap = false, warningsOut = null } = {}) {
  const tracking = trackingRoot(project);
  requireNoRetiredTrackingPaths(tracking);
  const state = loadState(project);
  const softWarnings = [];
  const transaction = normalizeTransaction(project, state, document, { allowGap, warningsOut: softWarnings });
  const nextState = mergeTransaction(state, transaction);
  const filePath = deltaPath(tracking, transaction.chapter);
  const previousRecord = transaction.mode === 'revision' ? parseChapterRecord(filePath) : null;
  if (previousRecord !== null) {
    const mergedRetired = [...previousRecord.retired];
    for (const item of transaction.delta.retired_context_items) {
      if (!mergedRetired.includes(item)) mergedRetired.push(item);
    }
    transaction.delta.retired_context_items = mergedRetired;
  }
  const coreNames = new Set([
    ...Object.keys(nextState.characters),
    ...transaction.delta.retired_characters,
  ]);
  const deltaPayload = renderDelta(transaction.chapter, transaction.title, transaction.delta, coreNames);
  const views = renderViews(nextState);
  const nextStatePayload = jsonPayload(nextState);
  if (transaction.mode === 'append' && exists(filePath)) {
    requireCondition(
      fs.readFileSync(filePath, 'utf8').replace(/\r\n/g, '\n') === deltaPayload,
      `chapter delta ${transaction.chapter} already exists with different content`
    );
  }
  writeIfChanged(filePath, deltaPayload);
  writeViews(tracking, views);
  _hooks.atomicWriteText(statePath(project), nextStatePayload);
  for (const msg of softWarnings) emitWarning(msg, warningsOut);
  warnSizes(views, deltaPayload, warningsOut);
  warnEmptiedSnapshots(state.characters, transaction.snapshots, warningsOut);
  if (previousRecord !== null) {
    warnEmptiedRecord(transaction.chapter, previousRecord, transaction.delta, warningsOut);
  }
  return nextState;
}

function applyTransaction(project, document, options = {}) {
  return withProjectWriteLock(project, () => applyTransactionLocked(project, document, options));
}

function checkProject(project, { strict = false, warningsOut = null, driftWarningsOut = null } = {}) {
  const tracking = trackingRoot(project);
  requireNoRetiredTrackingPaths(tracking);
  const state = loadState(project);
  const lastChapter = state.last_committed_chapter;
  const requiredDeltaStart = state.imported_through_chapter + 1;
  const driftWarnings = driftWarningsOut || [];
  for (let chapter = requiredDeltaStart; chapter <= lastChapter; chapter += 1) {
    if (!exists(deltaPath(tracking, chapter))) {
      if (strict) {
        throw new TrackingError(`chapter delta ${chapter} is missing`);
      }
      const message = `chapter delta ${chapter} is missing（可能为跳章提交或手工删除；请询问作者是否需要补交该章记录）`;
      driftWarnings.push({
        type: 'missing_delta',
        chapter,
        file: `逐章记录/第${padChapter(chapter)}章.md`,
        message,
        prompt: '请询问作者：该章是否为有意跳章，或需要补交该章记录？',
      });
      emit(`WARNING: ${message}`, { error: true });
    }
  }
  const lastSnapshotUpdateByChar = new Map();
  for (const name of state.context.active_character_names) {
    lastSnapshotUpdateByChar.set(name, state.imported_through_chapter);
  }
  const deltaDir = path.join(tracking, '逐章记录');
  if (isDir(deltaDir)) {
    for (const name of fs.readdirSync(deltaDir).sort()) {
      if (!/^第.*章\.md$/.test(name)) continue;
      const fullPath = path.join(deltaDir, name);
      const match = /^第(\d+)章\.md$/.exec(name);
      requireCondition(match !== null, `chapter delta has an invalid filename: ${name}`);
      const chapter = asInt(Number(match[1]), `chapter delta ${name}`, { minimum: 1 });
      requireCondition(
        path.resolve(fullPath) === path.resolve(deltaPath(tracking, chapter)),
        `chapter delta ${chapter} filename is not canonical`
      );
      requireCondition(chapter <= lastChapter, `chapter delta ${chapter} exceeds last_committed_chapter`);
      const deltaBytes = fs.statSync(fullPath).size;
      requireCondition(
        deltaBytes <= VIEW_HARD_CAP_BYTES,
        `chapter delta ${chapter} (${deltaBytes} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes`
      );
      if (deltaBytes > DELTA_MAX_BYTES) {
        emitWarning(
          `chapter delta ${chapter} is ${deltaBytes} bytes; recommended cap is <= ${DELTA_MAX_BYTES} bytes`,
          warningsOut
        );
      }
      const parsedRecord = parseChapterRecord(fullPath);
      if (parsedRecord && parsedRecord.character_changes.length) {
        for (const changeLine of parsedRecord.character_changes) {
          const idx1 = changeLine.indexOf('｜');
          if (idx1 <= 0) continue;
          const idx2 = changeLine.indexOf('｜', idx1 + 1);
          const charName = changeLine.slice(0, idx1);
          const role = idx2 > idx1 ? changeLine.slice(idx1 + 1, idx2) : '';
          if (role === '核心' && lastSnapshotUpdateByChar.has(charName)) {
            lastSnapshotUpdateByChar.set(charName, Math.max(lastSnapshotUpdateByChar.get(charName), chapter));
          }
        }
      }
    }
  }
  for (const name of state.context.active_character_names) {
    const lastUpdated = lastSnapshotUpdateByChar.get(name) ?? state.imported_through_chapter;
    const staleChapters = new Set();
    for (const ev of Object.values(state.timeline)) {
      if (!ev || !Array.isArray(ev.characters) || !ev.characters.includes(name)) continue;
      if (Number.isInteger(ev.first_recorded_chapter) && ev.first_recorded_chapter > lastUpdated) {
        staleChapters.add(ev.first_recorded_chapter);
      }
      if (Number.isInteger(ev.updated_chapter) && ev.updated_chapter > lastUpdated) {
        staleChapters.add(ev.updated_chapter);
      }
    }
    if (staleChapters.size >= 2) {
      const chaptersList = [...staleChapters].sort((a, b) => a - b).map((c) => `第${c}章`).join('、');
      emitWarning(
        `stale character snapshot: active character ${name} appeared in timeline_events across ${staleChapters.size} chapters (${chaptersList}) without a snapshot update（上次更新：第${lastUpdated}章）`,
        warningsOut
      );
    }
  }
  const expectedViews = renderViews(state);
  for (const [relative, expected] of Object.entries(expectedViews)) {
    const filePath = path.join(tracking, relative);
    if (!exists(filePath)) {
      if (strict) {
        throw new TrackingError(`derived view is missing: ${relative}`);
      }
      const message = `derived view is missing: ${relative}（请询问作者：是否按 _tracking-state.json 重建派生视图？）`;
      driftWarnings.push({
        type: 'missing_view',
        file: relative,
        message,
        prompt: '请询问作者：按 _tracking-state.json 重建缺失视图，还是补充对应修订事务？',
      });
      emit(`WARNING: ${message}`, { error: true });
      continue;
    }
    if (fs.readFileSync(filePath, 'utf8').replace(/\r\n/g, '\n') !== expected) {
      if (strict) {
        throw new TrackingError(`derived view differs from _tracking-state.json: ${relative}`);
      }
      const message =
        `derived view differs from _tracking-state.json: ${relative}` +
        '（检测到手工修改或未同步视图；请询问作者：要将手工改动吸回 _tracking-state.json，还是按 JSON 重建？）';
      driftWarnings.push({
        type: 'view_drift',
        file: relative,
        message,
        prompt: '请询问作者：将手工改动吸回 _tracking-state.json（提交 mode=revision 事务），还是按 JSON 重建？',
      });
      emit(`WARNING: ${message}`, { error: true });
    }
  }
  const expectedCharFiles = new Set(
    Object.keys(expectedViews)
      .filter((rel) => rel.startsWith('角色状态/'))
      .map((rel) => path.basename(rel))
  );
  const charDir = path.join(tracking, '角色状态');
  const actualCharFiles = new Set(isDir(charDir) ? fs.readdirSync(charDir).filter((n) => n.endsWith('.md')) : []);
  const sameFiles =
    actualCharFiles.size === expectedCharFiles.size &&
    [...actualCharFiles].every((name) => expectedCharFiles.has(name));
  if (!sameFiles) {
    if (strict) {
      throw new TrackingError('character snapshot files differ from tracking state');
    }
    const extraFiles = [...actualCharFiles].filter((name) => !expectedCharFiles.has(name)).sort();
    const missingFiles = [...expectedCharFiles].filter((name) => !actualCharFiles.has(name)).sort();
    const message =
      'character snapshot files differ from tracking state' +
      `（多余：${extraFiles.join('、') || '无'}；缺失：${missingFiles.join('、') || '无'}；` +
      '请询问作者：要吸回手工改动还是按 _tracking-state.json 重建？）';
    driftWarnings.push({
      type: 'character_files_drift',
      extra_files: extraFiles,
      missing_files: missingFiles,
      message,
      prompt: '请询问作者：将手工新增/修改的角色视图吸回状态，还是按 _tracking-state.json 重建？',
    });
    emit(`WARNING: ${message}`, { error: true });
  }
  return state;
}

function recordPrefill(state, record) {
  const notes = [];
  const changes = [];
  for (const line of record.character_changes) {
    const idx1 = line.indexOf('｜');
    if (idx1 < 0) continue;
    const idx2 = line.indexOf('｜', idx1 + 1);
    if (idx2 < 0) continue;
    changes.push({ name: line.slice(0, idx1), change: line.slice(idx2 + 1) });
  }
  const snapshots = {};
  for (const item of changes) {
    if (Object.prototype.hasOwnProperty.call(state.characters, item.name)) {
      snapshots[item.name] = deepClone(state.characters[item.name]);
    }
  }

  const rows = (lines, current, label) => {
    const prefilled = [];
    for (const line of lines) {
      const parts = line.split('｜');
      const identifier = parts[0];
      if (parts.length > 1 && parts[1] === '删除当前登记') {
        if (Object.prototype.hasOwnProperty.call(current, identifier)) {
          notes.push(`${label} ${identifier} 本章删过、后来又登记了，没有预填删除，确需删除自行加回`);
        } else {
          prefilled.push({ action: 'delete', id: identifier });
        }
      } else if (Object.prototype.hasOwnProperty.call(current, identifier)) {
        const entry = { action: 'upsert' };
        for (const [k, v] of Object.entries(current[identifier])) {
          if (k !== 'updated_chapter' && k !== 'first_recorded_chapter') {
            entry[k] = deepClone(v);
          }
        }
        prefilled.push(entry);
      } else {
        notes.push(`${label} ${identifier} 已在后续章节删除，没有预填`);
      }
    }
    return prefilled;
  };

  const delta = {
    result: record.result,
    character_changes: changes,
    foreshadow_changes: rows(record.foreshadow_changes, state.foreshadow, '伏笔'),
    timeline_events: rows(record.timeline_events, state.timeline, '时间线事件'),
    constraints: [...record.constraints],
    next_chapter_commitments: [...record.next_chapter_commitments],
    retired_context_items: [],
  };
  return { delta, snapshots, notes };
}

function entryShapes(chapter) {
  const snapshotShape = {};
  for (const k of SNAPSHOT_TEXT_FIELDS) snapshotShape[k] = '一句话';
  for (const k of SNAPSHOT_LIST_FIELDS) snapshotShape[k] = ['一条一句'];
  return {
    'delta.character_changes[]': { name: '角色名', change: '一句话：本章起了什么变化' },
    'delta.foreshadow_changes[]': {
      action: 'upsert（撤掉整条写 delete，只带 id）',
      id: 'F007',
      summary: '伏笔一句话',
      planted_chapter: chapter,
      planned_resolution_chapter: '计划回收章的整数，未定写 null',
      status: FORESHADOW_STATUSES.join('|'),
      importance: FORESHADOW_IMPORTANCE.join('|'),
    },
    'delta.timeline_events[]': {
      action: 'upsert（撤掉整条写 delete，只带 id）',
      id: 'E012',
      story_time: '故事内时间',
      objective_fact: '客观发生了什么',
      reader_knowledge: '读者此刻知道/以为什么',
      reveal_status: REVEAL_STATUSES.join('|'),
      reveal_chapter: `已揭示或部分揭示时写揭示章的整数（不晚于 ${chapter}），未揭示写 null`,
      characters: ['角色名'],
    },
    'character_snapshots.{角色名}': snapshotShape,
  };
}

function draftTransaction(project, chapter, { state = null, allowGap = false } = {}) {
  const st = state || loadState(project);
  const last = st.last_committed_chapter;
  if (allowGap) {
    requireCondition(chapter >= 1, `draft chapter must be >= 1`);
  } else {
    requireCondition(
      chapter >= 1 && chapter <= last + 1,
      `draft chapter must be between 1 and ${last + 1}（如有意跳章可加 --allow-gap）`
    );
  }
  const mode =
    chapter > last ||
    (allowGap && chapter > st.imported_through_chapter && !exists(deltaPath(trackingRoot(project), chapter)))
      ? 'append'
      : 'revision';
  let title = '';
  const titleRe = new RegExp(`^#{1,4}\\s*第\\s*0*${chapter}\\s*章\\s*[：:]\\s*(.+?)\\s*$`, 'm');
  try {
    const { outline } = wordcountCore.readChapterOutline(project, chapter);
    const match = titleRe.exec(outline);
    if (match) title = match[1].trim();
  } catch {
    const outlineDir = path.join(String(project), '大纲');
    if (isDir(outlineDir)) {
      const outlineRe = /^细纲_第(\d+)章/;
      const candidates = fs
        .readdirSync(outlineDir)
        .filter((n) => {
          const m = outlineRe.exec(n);
          return m && Number(m[1]) === chapter && n.endsWith('.md');
        })
        .sort();
      for (const name of candidates) {
        const match = titleRe.exec(fs.readFileSync(path.join(outlineDir, name), 'utf8'));
        if (match) {
          title = match[1].trim();
          break;
        }
      }
    }
  }
  const context = deepClone(st.context);
  const previousPosition = { story_time: context.position.story_time, scene: context.position.scene };
  let delta = {
    result: '',
    character_changes: [],
    foreshadow_changes: [],
    timeline_events: [],
    constraints: [],
    next_chapter_commitments: [],
    retired_context_items: [],
  };
  let snapshotsPrefill = {};
  let notes = [];
  let prefilled = false;
  if (mode === 'append') {
    delta.retired_characters = [];
    context.position.story_time = '';
    context.position.scene = '';
  } else {
    const record = parseChapterRecord(deltaPath(trackingRoot(project), chapter));
    if (record !== null) {
      prefilled = true;
      ({ delta, snapshots: snapshotsPrefill, notes } = recordPrefill(st, record));
      title = title || record.title;
      if (chapter === last) {
        delta.next_chapter_commitments = [...st.context.next_chapter_commitments];
      }
    }
  }
  const document = {
    schema_version: INPUT_SCHEMA_VERSION,
    mode,
    chapter,
    chapter_title: title,
    expected_state_revision: st.state_revision,
    delta,
    context: {
      position: context.position,
      long_term_constraints: context.long_term_constraints,
      active_character_names: context.active_character_names,
      continuity_risks: context.continuity_risks,
    },
    character_snapshots: snapshotsPrefill,
  };
  const snapshots = {};
  for (const name of context.active_character_names) {
    if (Object.prototype.hasOwnProperty.call(st.characters, name)) {
      snapshots[name] = st.characters[name];
    }
  }
  const extra = mode === 'revision' ? { notes, prefilled } : previousPosition;
  return { document, snapshots, extra };
}

function rebuildStaleDraft(document, existing, append, currentCharacters = []) {
  const items = (value) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []);
  const norm = (item) => item.replace(/\|/g, '｜').trim().replace(/\s+/g, ' ');
  const notes = [
    `修订号已变：context 按当前状态重建，本章已填的 delta${append ? '、新增与退役的约束、结尾位置' : ''}已合并`,
  ];
  for (const key of ['delta', 'character_snapshots']) {
    if (isPlainObject(existing[key])) {
      document[key] = existing[key];
    }
  }
  if (existing.chapter_title) {
    document.chapter_title = existing.chapter_title;
  }
  const oldContext = isPlainObject(existing.context) ? existing.context : {};
  const delta = isPlainObject(document.delta) ? document.delta : {};
  const context = document.context;
  const retired = new Set(items(delta.retired_context_items).map(norm));
  const leftOut = [];
  for (const key of ['long_term_constraints', 'continuity_risks']) {
    const current = new Set(context[key].map(norm));
    const extra = [];
    for (const item of items(oldContext[key])) {
      const k = norm(item);
      if (!current.has(k)) {
        current.add(k);
        extra.push(item);
      }
    }
    if (append) {
      context[key] = [...context[key].filter((item) => !retired.has(norm(item))), ...extra];
    } else {
      context[key] = context[key].filter((item) => !retired.has(norm(item)));
      leftOut.push(...extra);
    }
  }
  const snapshots = isPlainObject(document.character_snapshots) ? document.character_snapshots : {};
  let names = context.active_character_names;
  for (const name of items(oldContext.active_character_names)) {
    if (names.includes(name)) continue;
    if (append && Object.prototype.hasOwnProperty.call(snapshots, name)) {
      names.push(name);
    } else {
      leftOut.push(`在场角色 ${name}`);
    }
  }
  const retiredChars = new Set(items(delta.retired_characters));
  names = names.filter((name) => !retiredChars.has(name));
  context.active_character_names = names;
  const known = new Set(currentCharacters);
  for (const name of Object.keys(snapshots)) {
    if (!known.has(name) && !names.includes(name)) {
      delete snapshots[name];
      leftOut.push(`角色快照 ${name}`);
    }
  }
  if (leftOut.length) {
    notes.push(
      '草稿里有、当前状态没有的条目没有自动带回（可能已被别的提交退役），本章确实需要就加回：' + leftOut.join('；')
    );
  }
  const oldPosition = isPlainObject(oldContext.position) ? oldContext.position : {};
  const position = context.position;
  if (append) {
    for (const key of ['story_time', 'scene']) {
      if (typeof oldPosition[key] === 'string' && oldPosition[key].trim()) {
        position[key] = oldPosition[key];
      }
    }
  }
  const differs = [];
  for (const key of ['volume', 'volume_start_chapter']) {
    if (Object.prototype.hasOwnProperty.call(oldPosition, key) && oldPosition[key] !== position[key]) {
      differs.push(`${key}：草稿写的是「${oldPosition[key]}」，当前状态是「${position[key]}」`);
    }
  }
  if (differs.length) {
    notes.push(`卷信息与当前状态不同，已取当前状态，本章确实换卷就改回（${differs.join('；')}）`);
  }
  const snapNames = Object.keys(snapshots);
  if (snapNames.length) {
    notes.push(`带过来的角色快照（${snapNames.join('、')}）可能被中间的提交改过，逐个对照 current_snapshots 或 snapshot_files 重核`);
  }
  return notes.join('；');
}

function prepareDraftSnapshots(project, chapter, allCharacters, activeNames) {
  const snapshotsDir = path.join(chapterWorkDir(project, chapter), 'snapshots');
  const expectedFiles = new Set(Object.keys(allCharacters).map((name) => `${name}.json`));
  if (isDir(snapshotsDir)) {
    for (const entry of fs.readdirSync(snapshotsDir)) {
      if (entry.endsWith('.json') && !expectedFiles.has(entry)) {
        fs.unlinkSync(path.join(snapshotsDir, entry));
      }
    }
    if (Object.keys(allCharacters).length === 0) {
      try {
        fs.rmdirSync(snapshotsDir);
      } catch {
        // ignore
      }
    }
  }
  const snapshotFiles = {};
  for (const [name, snap] of Object.entries(allCharacters)) {
    const target = path.join(snapshotsDir, `${name}.json`);
    writeIfChanged(target, jsonPayload(snap));
    snapshotFiles[name] = target;
  }
  const inline = {};
  const omitted = [];
  let usedBytes = 2;
  for (const name of [...new Set(activeNames)]) {
    if (!Object.prototype.hasOwnProperty.call(allCharacters, name)) continue;
    const entryBytes = byteSize(JSON.stringify({ [name]: allCharacters[name] }));
    if (usedBytes + entryBytes <= DRAFT_INLINE_SNAPSHOTS_MAX_BYTES) {
      inline[name] = allCharacters[name];
      usedBytes += entryBytes;
    } else {
      omitted.push(name);
    }
  }
  return { inline, snapshotFiles, omitted };
}

function parseCliArgs(argv) {
  if (!argv.length || argv[0] === '-h' || argv[0] === '--help') {
    return { help: argv.length > 0, error: argv.length === 0 ? 'command is required' : null };
  }
  const command = argv[0];
  if (!['init', 'commit', 'check', 'draft'].includes(command)) {
    return { error: `invalid command: ${command}` };
  }
  const args = {
    command,
    project: null,
    input: null,
    chapter: null,
    out: null,
    force: false,
    strict: false,
    allowGap: false,
  };
  for (let i = 1; i < argv.length; i += 1) {
    const token = argv[i];
    const readVal = (flag) => {
      if (token.includes('=')) return token.slice(token.indexOf('=') + 1);
      if (i + 1 >= argv.length) throw new Error(`${flag} requires a value`);
      return argv[++i];
    };
    try {
      if (token === '--project' || token.startsWith('--project=')) {
        args.project = readVal('--project');
      } else if ((command === 'init' || command === 'commit') && (token === '--input' || token.startsWith('--input='))) {
        args.input = readVal('--input');
      } else if (command === 'draft' && (token === '--chapter' || token.startsWith('--chapter='))) {
        const raw = readVal('--chapter');
        if (!/^-?\d+$/.test(raw)) return { error: `invalid --chapter: ${raw}` };
        args.chapter = Number(raw);
      } else if (command === 'draft' && (token === '--out' || token.startsWith('--out='))) {
        args.out = readVal('--out');
      } else if (command === 'draft' && token === '--force') {
        args.force = true;
      } else if (command === 'check' && token === '--strict') {
        args.strict = true;
      } else if ((command === 'commit' || command === 'draft') && token === '--allow-gap') {
        args.allowGap = true;
      } else {
        return { error: `unrecognized argument: ${token}` };
      }
    } catch (err) {
      return { error: err.message };
    }
  }
  if (!args.project) return { error: 'missing required --project' };
  if ((command === 'init' || command === 'commit') && !args.input) {
    return { error: 'missing required --input' };
  }
  if (command === 'draft' && args.chapter === null) {
    return { error: 'missing required --chapter' };
  }
  return args;
}

function main(argv = process.argv.slice(2)) {
  const args = parseCliArgs(argv);
  if (args.help) {
    process.stdout.write(
      'usage: node tracking_commit.js {init,commit,check,draft} --project DIR [--input FILE] [--chapter N] [--out FILE] [--force] [--strict] [--allow-gap]\n'
    );
    return 0;
  }
  if (args.error) {
    emit(`ERROR: ${args.error}`, { error: true });
    return 2;
  }
  let result;
  const warnings = [];
  const driftWarnings = [];
  try {
    let project;
    try {
      project = wordcountCore.resolveBookDir(args.project);
    } catch (err) {
      if (err instanceof wordcountCore.WordcountError) throw new TrackingError(err.message);
      throw err;
    }
    if (args.command === 'draft') {
      const state = loadState(project);
      let { document, extra } = draftTransaction(project, args.chapter, { state, allowGap: args.allowGap });
      const allCharacters = state.characters;
      const previousPosition = document.mode === 'append' ? extra : {};
      const prefillNotes = document.mode === 'revision' ? extra.notes || [] : [];
      const recordPrefilled = document.mode === 'revision' ? Boolean(extra.prefilled) : false;
      const out = args.out || path.join(chapterWorkDir(project, args.chapter), 'tracking.json');
      fs.mkdirSync(path.dirname(out), { recursive: true });
      let refreshed = '';
      if (exists(out) && !args.force) {
        const existing = readJson(out);
        requireCondition(
          isPlainObject(existing) && existing.chapter === document.chapter && existing.mode === document.mode,
          `${out} already holds a draft for a different chapter or mode; pass --force to replace it`
        );
        if (existing.expected_state_revision === document.expected_state_revision) {
          document = existing;
          refreshed = '已有草稿且修订号未变，原样保留';
        } else {
          refreshed = rebuildStaleDraft(
            document,
            existing,
            Object.keys(previousPosition).length > 0,
            Object.keys(allCharacters)
          );
        }
      }
      atomicWriteText(out, `${JSON.stringify(document, null, 1)}\n`);
      const rawActive = isPlainObject(document.context) ? document.context.active_character_names : [];
      const activeNames = Array.isArray(rawActive) ? rawActive.filter((n) => typeof n === 'string') : [];
      const { inline: snapshots, snapshotFiles, omitted: omittedSnapshots } = prepareDraftSnapshots(
        project,
        args.chapter,
        allCharacters,
        activeNames
      );
      let fill;
      if (document.mode === 'revision' && !recordPrefilled) {
        fill =
          `这是修订，但本章逐章记录缺失或读不了（追踪/逐章记录/第${padChapter(args.chapter)}章.md），delta 没有预填：` +
          '按修订后正文把本章完整记录整份写上（结果、承诺、角色变化、伏笔、时间线、约束），没写的项不会进记录。' +
          '角色快照、伏笔、时间线写截至最新已写章的当前值（已有核心角色的当前快照见 snapshot_files）；已兑现的长期约束/连贯性风险可从 context 删掉并把原文放进 delta.retired_context_items（角色退役仍仅限 append）。' +
          '正文改过就用 story-long-write 的 storyctl.js chapter commit 提交（重新计数并清理本章工作目录）。' +
          '不要从脚本源码或 state 文件里另找格式。';
      } else if (document.mode === 'revision') {
        fill =
          '这是修订：delta 是修订后本章的完整记录，已按本章现有逐章记录预填（伏笔与时间线取当前值，' +
          '记录里的核心角色快照已放进 character_snapshots，其他核心角色当前快照见 snapshot_files）。对照修订后正文逐项改：仍成立的原样保留，' +
          '被推翻的删掉或改写，新增的补上；不要清空后只写改动，没写的项会从本章记录里消失。' +
          '角色快照、伏笔、时间线改成截至最新已写章的当前值；已兑现的长期约束/连贯性风险可从 context 删掉并把原文放进 delta.retired_context_items（角色退役仍仅限 append）。' +
          '正文改过就用 story-long-write 的 storyctl.js chapter commit 提交（重新计数并清理本章工作目录）。' +
          '不要从脚本源码或 state 文件里另找格式。';
        if (prefillNotes.length) {
          fill += `没能预填：${prefillNotes.join('；')}。`;
        }
      } else {
        fill =
          '只填 delta 里本章的变化；context 其余字段已是当前值，要撤下的长期约束或连贯性风险从 context 删掉并把原文放进 ' +
          'delta.retired_context_items；本章有变化的核心角色从 current_snapshots（未内联的大快照或久别回归角色读 snapshot_files 对应 JSON）' +
          '取当前快照整份改好放进 character_snapshots，并在 character_changes 写一句变化。每类条目照 shapes 的形状写，不要从脚本源码或 state 文件里另找格式。';
      }
      if (omittedSnapshots.length) {
        fill =
          `在场角色（${omittedSnapshots.join('、')}）快照较大未内联到 stdout，本章若有变化先读取 snapshot_files 对应 JSON 在其基础上修改，勿凭空重写以免丢失既有条目。` +
          fill;
      }
      const blank = !(document.context.position.story_time || document.context.position.scene);
      if (Object.keys(previousPosition).length > 0 && blank) {
        fill =
          'context.position 的 story_time 与 scene 留空，填本章结束时的故事时间与场景（上一章结束时见 ' +
          'previous_position；换卷时连同 volume 与 volume_start_chapter 一起改）。' +
          fill;
      }
      const payload = {
        draft: out,
        mode: document.mode,
        expected_state_revision: document.expected_state_revision,
        fill: `${refreshed ? `${refreshed}；要从头生成加 --force。` : ''}${fill}`,
        limits_chars: DRAFT_LIMITS,
        shapes: entryShapes(args.chapter),
        current_snapshots: snapshots,
        snapshot_files: snapshotFiles,
      };
      if (omittedSnapshots.length) {
        payload.omitted_active_snapshots = omittedSnapshots;
      }
      if (Object.keys(previousPosition).length > 0) {
        payload.previous_position = previousPosition;
      }
      emit(JSON.stringify(payload));
      return 0;
    }
    if (args.command === 'init') {
      result = initialize(project, readJson(args.input), { warningsOut: warnings });
    } else if (args.command === 'commit') {
      result = applyTransaction(project, readJson(args.input), {
        allowGap: args.allowGap,
        warningsOut: warnings,
      });
    } else {
      result = checkProject(project, {
        strict: args.strict,
        warningsOut: warnings,
        driftWarningsOut: driftWarnings,
      });
    }
  } catch (err) {
    if (err instanceof TrackingError || (err && typeof err.code === 'string')) {
      emit(`ERROR: ${err.message}`, { error: true });
      return 2;
    }
    throw err;
  }
  const output = {
    last_committed_chapter: result.last_committed_chapter,
    state_revision: result.state_revision,
    warnings,
  };
  if (args.command === 'check') {
    output.drift_warnings = driftWarnings;
  }
  emit(JSON.stringify(output));
  return 0;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  FORESHADOW_STATUSES,
  FORESHADOW_IMPORTANCE,
  REVEAL_STATUSES,
  CONTEXT_HEADINGS,
  TrackingError,
  _hooks,
  loadState,
  initialize,
  applyTransaction,
  checkProject,
  draftTransaction,
  main,
};
