#!/usr/bin/env node
'use strict';
/**
 * Maintain evidence-backed author preferences and deterministic Markdown views.
 *
 * The language model supplies compact semantic transactions. This tool validates
 * and applies them in memory, renders every derived view, and writes the JSON state
 * last as the commit point. Author memory lives in two kinds of store: the
 * project-level store under the workspace holds global / genre / workflow items
 * (`AP` ids); each book keeps its own book-level store under the book directory
 * (`BP` ids) so memory travels with the book. When the book root is the workspace
 * itself, the book-level store moves into a `书级/` subdirectory so the two never
 * share a file.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');

const _SLEEP_ARR = new Int32Array(new SharedArrayBuffer(4));

function sleepMs(ms) {
  Atomics.wait(_SLEEP_ARR, 0, 0, ms);
}

const INPUT_SCHEMA_VERSION = 1;
const STATE_SCHEMA_VERSION = 1;
const STATE_MAX_BYTES = 2 * 1024 * 1024;
const VIEW_HARD_CAP_BYTES = 65536;
const PROFILE_MAX_BYTES = 12288;
const JOURNAL_MAX_BYTES = 24576;
const QUERY_MAX_BYTES = 2048;
const ASSERTION_MAX_BYTES = 120;
const LEGACY_ASSERTION_MAX_BYTES = 768;

const QUERY_COMBOS = {
  '正文初稿/续写': ['prose_style', 'story_design'],
  '去AI味/改写': ['prose_style'],
  '设定/大纲': ['story_design', 'workflow', 'interaction'],
  审稿: ['delivery', 'interaction', 'prose_style'],
};

const KINDS = ['prose_style', 'story_design', 'workflow', 'delivery', 'interaction'];
const KIND_TITLES = {
  prose_style: '文风与表达',
  story_design: '故事设计',
  workflow: '创作流程',
  delivery: '交付格式',
  interaction: '协作方式',
};
const SCOPE_LEVELS = ['global', 'genre', 'book', 'workflow'];
const STATUSES = ['active', 'pending', 'conflict', 'rejected', 'superseded'];
const LEGACY_LIVE_STATUSES = ['pending', 'conflict'];
const LEGACY_PENDING_VIEW = '待确认.md';
const CONFIDENCE_LEVELS = ['low', 'medium', 'high'];
const IMPORTANCE_LEVELS = ['low', 'medium', 'high'];
const SOURCES = [
  'explicit_user',
  'accepted_suggestion',
  'repeated_correction',
  'inferred_pattern',
  'manual',
];
const WRITE_SOURCES = ['explicit_user', 'accepted_suggestion', 'manual'];
const RANK = { low: 0, medium: 1, high: 2 };

const STORE_PREFIX = { project: 'AP', book: 'BP' };
const ID_PREFIXES = Object.values(STORE_PREFIX);
const SINGLE_ROOT_BOOK_DIR = '书级';
const MIGRATE_PREFIX = 'migrate:';

const NO_CANDIDATES =
  '作者记忆只记作者确认过的习惯，不再记待确认或冲突候选：范围或说法含糊时先问作者一句，' +
  '确认了再记；与已有习惯相反时用 replace 换掉旧条；拿不准就只照做、不记';

class AuthorMemoryError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AuthorMemoryError';
  }
}

function requireCondition(condition, message) {
  if (!condition) {
    throw new AuthorMemoryError(message);
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

function requireKnownKeys(mapping, allowed, label) {
  const unknown = Object.keys(mapping).filter((k) => !allowed.has(k)).sort();
  requireCondition(unknown.length === 0, `${label} contains unsupported fields: ${unknown.join(', ')}`);
}

function utf8Bytes(str) {
  return Buffer.byteLength(str, 'utf8');
}

function cleanText(value, label, { maxBytes = 768, hardMaxBytes = null } = {}) {
  requireCondition(typeof value === 'string', `${label} must be a string`);
  const cleaned = value.replace(/\|/g, '｜').trim().replace(/\s+/g, ' ');
  requireCondition(Boolean(cleaned), `${label} must not be empty`);
  const cap = hardMaxBytes !== null ? hardMaxBytes : maxBytes;
  if (cap !== null) {
    requireCondition(utf8Bytes(cleaned) <= cap, `${label} exceeds ${cap} bytes`);
  }
  return cleaned;
}

function optionalText(value, label, { maxBytes = 768 } = {}) {
  if (value === null || value === undefined) {
    return null;
  }
  return cleanText(value, label, { maxBytes });
}

function choice(value, allowed, label) {
  requireCondition(typeof value === 'string' && allowed.includes(value), `${label} must be one of: ${allowed.join(', ')}`);
  return value;
}

function isItemId(value) {
  if (typeof value !== 'string' || value.length < 3) return false;
  if (!ID_PREFIXES.includes(value.slice(0, 2))) return false;
  const digits = value.slice(2);
  return /^\d+$/.test(digits) && Number(digits) >= 1;
}

function idNumber(itemId) {
  return Number(itemId.slice(2));
}

function idStore(itemId) {
  return itemId.startsWith(STORE_PREFIX.book) ? 'book' : 'project';
}

function cleanIdList(value, label, { maximum = 32 } = {}) {
  const raw = asList(value, label);
  requireCondition(raw.length <= maximum, `${label} may contain at most ${maximum} items`);
  const result = [];
  for (let index = 0; index < raw.length; index += 1) {
    const itemId = cleanText(raw[index], `${label}[${index}]`, { maxBytes: 32 });
    requireCondition(isItemId(itemId), `${label}[${index}] is not an author-memory id`);
    if (!result.includes(itemId)) {
      result.push(itemId);
    }
  }
  return result;
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

function emit(document, { error = false } = {}) {
  const payload = `${JSON.stringify(sortKeysDeep(document))}\n`;
  const stream = error ? process.stderr : process.stdout;
  stream.write(payload);
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

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
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

function readJson(filePath) {
  try {
    const st = fs.statSync(filePath);
    requireCondition(st.size <= STATE_MAX_BYTES, `${filePath} exceeds ${STATE_MAX_BYTES} bytes`);
    const raw = fs.readFileSync(filePath);
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    return JSON.parse(text);
  } catch (err) {
    if (err instanceof AuthorMemoryError) throw err;
    throw new AuthorMemoryError(`unable to read JSON ${filePath}: ${err.message}`);
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
    throw new AuthorMemoryError(`unable to create temporary file for ${filePath}`);
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
      // Ignore chmod issues on filesystems without POSIX mode support
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

function writeIfChanged(filePath, payload) {
  try {
    if (fs.readFileSync(filePath, 'utf8') === payload) {
      return;
    }
  } catch (err) {
    if (!err || err.code !== 'ENOENT') throw err;
  }
  atomicWriteText(filePath, payload);
}

function withStoreWriteLock(store, fn, { timeoutSeconds = 10.0 } = {}) {
  fs.mkdirSync(store.root, { recursive: true });
  const lockPath = path.join(store.root, '.author-memory.lock');
  const deadline = performance.now() + timeoutSeconds * 1000;
  let fd = null;
  while (fd === null) {
    try {
      fd = fs.openSync(lockPath, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, 0o644);
    } catch (err) {
      if (err && err.code === 'EEXIST') {
        if (performance.now() >= deadline) {
          throw new AuthorMemoryError(
            `author memory lock is busy or stale; retry, or remove ${lockPath} after confirming no write is running`
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

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

class Store {
  constructor(kind, root, book) {
    this.kind = kind;
    this.root = root;
    this.book = book;
  }

  get prefix() {
    return STORE_PREFIX[this.kind];
  }

  get statePath() {
    return path.join(this.root, '_author-memory-state.json');
  }

  get label() {
    return this.kind === 'project' ? '项目级' : `书级（${this.book}）`;
  }
}

function realOrResolve(p) {
  const abs = path.resolve(String(p));
  try {
    return fs.realpathSync(abs);
  } catch {
    return abs;
  }
}

function projectStore(workspace) {
  return new Store('project', path.join(realOrResolve(workspace), '.story', '作者记忆'), null);
}

function peekBookName(statePath) {
  if (!exists(statePath)) return null;
  const document = readJson(statePath);
  const name = isPlainObject(document) ? document.book : null;
  return typeof name === 'string' && name.trim() ? name : null;
}

function enclosingWorkspace(workspace) {
  const resolved = realOrResolve(workspace);
  const parentDir = path.dirname(resolved);
  if (parentDir !== resolved && ['长篇', '短篇'].includes(path.basename(parentDir))) {
    return path.dirname(parentDir);
  }
  const own = projectStore(resolved).statePath;
  const ownsProjectStore = exists(own) && peekBookName(own) === null;
  let prev = resolved;
  let ancestor = path.dirname(resolved);
  while (ancestor !== prev) {
    if (exists(path.join(ancestor, '.active-book'))) {
      return ancestor;
    }
    if (!ownsProjectStore) {
      const statePath = projectStore(ancestor).statePath;
      let document = null;
      if (isFile(statePath)) {
        try {
          document = readJson(statePath);
        } catch {
          document = null;
        }
      }
      if (isPlainObject(document) && !Object.prototype.hasOwnProperty.call(document, 'book')) {
        return ancestor;
      }
    }
    prev = ancestor;
    ancestor = path.dirname(ancestor);
  }
  return null;
}

function sameDirectory(first, second) {
  if (exists(first) && exists(second)) {
    try {
      const s1 = fs.statSync(first, { bigint: true });
      const s2 = fs.statSync(second, { bigint: true });
      if (s1.ino !== 0n && s2.ino !== 0n) {
        return s1.dev === s2.dev && s1.ino === s2.ino;
      }
    } catch {
      // fall through
    }
  }
  return realOrResolve(first).toLowerCase() === realOrResolve(second).toLowerCase() &&
    (process.platform === 'win32' || process.platform === 'darwin'
      ? realOrResolve(first).toLowerCase() === realOrResolve(second).toLowerCase()
      : realOrResolve(first) === realOrResolve(second));
}

function isSingleRoot(workspace, bookRoot) {
  if (!bookRoot || !sameDirectory(bookRoot, workspace)) {
    return false;
  }
  const outer = enclosingWorkspace(workspace);
  requireCondition(
    outer === null,
    `${workspace} 是创作工作区 ${outer} 里的一本书，不是单书工作区：--workspace 应传 ${outer}，这个目录放 --book-root`
  );
  return true;
}

function bookMemoryRoot(workspace, bookRoot) {
  const root = path.join(realOrResolve(bookRoot), '.story', '作者记忆');
  return isSingleRoot(workspace, bookRoot) ? path.join(root, SINGLE_ROOT_BOOK_DIR) : root;
}

function soleLegacyBookName(project) {
  if (!exists(project.statePath)) return null;
  const document = readJson(project.statePath);
  const items = isPlainObject(document) ? document.items : null;
  const names = new Map();
  if (isPlainObject(items)) {
    for (const item of Object.values(items)) {
      const scope = isPlainObject(item) ? item.scope : null;
      if (
        isPlainObject(scope) &&
        scope.level === 'book' &&
        typeof scope.value === 'string' &&
        scope.value.trim() &&
        ['active', 'pending', 'conflict'].includes(item.status)
      ) {
        const key = scope.value.toLowerCase();
        if (!names.has(key)) names.set(key, scope.value);
      }
    }
  }
  return names.size === 1 ? [...names.values()][0] : null;
}

function bookStore(workspace, bookRoot, book) {
  requireCondition(isDir(bookRoot), `book root does not exist: ${bookRoot}`);
  const resolved = realOrResolve(bookRoot);
  const root = bookMemoryRoot(workspace, bookRoot);
  let name = optionalText(book, 'book', { maxBytes: 180 });
  const stored = peekBookName(path.join(root, '_author-memory-state.json'));
  if (name === null) {
    name = stored;
  } else if (stored !== null) {
    requireCondition(
      name.toLowerCase() === stored.toLowerCase(),
      `--book「${name}」与 ${root} 里记录的书「${stored}」不一致`
    );
  }
  if (name === null && isSingleRoot(workspace, bookRoot)) {
    name = soleLegacyBookName(projectStore(workspace));
  }
  if (name === null) {
    name = cleanText(path.basename(resolved), 'book root name', { maxBytes: 180 });
  }
  return new Store('book', root, name);
}

function relocateMisplacedBookState(workspace, bookRoot) {
  if (!isSingleRoot(workspace, bookRoot)) return;
  const project = projectStore(workspace);
  const misplaced = peekBookName(project.statePath);
  if (misplaced === null) return;
  const target = new Store('book', bookMemoryRoot(workspace, bookRoot), misplaced);
  requireCondition(
    !exists(target.statePath),
    `${project.statePath} 与 ${target.statePath} 都是书级 state，无法自动归位；` +
      `保留修订较新的一份移到 ${target.statePath}，另一份备份后移走再重跑`
  );
  const state = validateState(readJson(project.statePath), { store: target });
  fs.mkdirSync(target.root, { recursive: true });
  fs.renameSync(project.statePath, target.statePath);
  writeSnapshot(target, state);
  writeSnapshot(project, emptyState());
}

function resolveTargetStore(kind, workspace, bookRoot, book) {
  if (kind === 'project') {
    return projectStore(workspace);
  }
  requireCondition(
    bookRoot !== null && bookRoot !== undefined,
    'book 级条目须传 --book-root {书目录}——记忆随书存放在 {书}/.story/作者记忆/，不再写进工作区的项目级 store'
  );
  return bookStore(workspace, bookRoot, book);
}

function emptyState(book = null) {
  const state = {
    schema_version: STATE_SCHEMA_VERSION,
    state_revision: 0,
    next_item_number: 1,
    items: {},
    journal: [],
    applied_transactions: {},
  };
  if (book !== null) {
    state.book = book;
  }
  return state;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function normalizeScope(value, label) {
  const scope = asMapping(value, label);
  requireKnownKeys(scope, new Set(['level', 'value']), label);
  const level = choice(scope.level, SCOPE_LEVELS, `${label}.level`);
  const rawValue = scope.value;
  let normalizedValue;
  if (level === 'global') {
    requireCondition(rawValue === null || rawValue === undefined, `${label}.value must be null for global scope`);
    normalizedValue = null;
  } else {
    normalizedValue = cleanText(rawValue, `${label}.value`, { maxBytes: 180 });
  }
  return { level, value: normalizedValue };
}

function normalizeEvidence(value, label) {
  const evidence = asMapping(value, label);
  requireKnownKeys(evidence, new Set(['quote', 'source_ref']), label);
  return {
    quote: cleanText(evidence.quote, `${label}.quote`, { maxBytes: 768 }),
    source_ref: optionalText(evidence.source_ref, `${label}.source_ref`, { maxBytes: 240 }),
  };
}

function normalizeItem(value, label) {
  const item = asMapping(value, label);
  const allowed = new Set([
    'id', 'kind', 'scope', 'assertion', 'confidence', 'importance', 'status', 'source',
    'reason', 'conflicts_with', 'confirmation_count', 'evidence', 'created_revision',
    'updated_revision', 'superseded_by',
  ]);
  requireKnownKeys(item, allowed, label);
  const itemId = cleanText(item.id, `${label}.id`, { maxBytes: 32 });
  requireCondition(isItemId(itemId), `${label}.id is invalid`);
  const evidence = asList(item.evidence, `${label}.evidence`).map((entry, idx) =>
    normalizeEvidence(entry, `${label}.evidence[${idx}]`)
  );
  requireCondition(evidence.length > 0, `${label}.evidence must not be empty`);
  const status = choice(item.status, STATUSES, `${label}.status`);
  const conflicts = cleanIdList(item.conflicts_with, `${label}.conflicts_with`);
  const supersededBy = optionalText(item.superseded_by, `${label}.superseded_by`, { maxBytes: 32 });
  if (supersededBy !== null) {
    requireCondition(isItemId(supersededBy), `${label}.superseded_by is invalid`);
  }
  return {
    id: itemId,
    kind: choice(item.kind, KINDS, `${label}.kind`),
    scope: normalizeScope(item.scope, `${label}.scope`),
    assertion: cleanText(item.assertion, `${label}.assertion`, { maxBytes: LEGACY_ASSERTION_MAX_BYTES }),
    confidence: choice(item.confidence, CONFIDENCE_LEVELS, `${label}.confidence`),
    importance: choice(item.importance, IMPORTANCE_LEVELS, `${label}.importance`),
    status,
    source: choice(item.source, SOURCES, `${label}.source`),
    reason: cleanText(item.reason, `${label}.reason`, { maxBytes: 480 }),
    conflicts_with: conflicts,
    confirmation_count: asInt(item.confirmation_count, `${label}.confirmation_count`, { minimum: 1 }),
    evidence,
    created_revision: asInt(item.created_revision, `${label}.created_revision`, { minimum: 1 }),
    updated_revision: asInt(item.updated_revision, `${label}.updated_revision`, { minimum: 1 }),
    superseded_by: supersededBy,
  };
}

function scopeFitsStore(scope, book) {
  if (book === null) return true;
  return scope.level === 'book' && (scope.value || '').toLowerCase() === book.toLowerCase();
}

function validateState(value, { store }) {
  const state = asMapping(value, 'state');
  const allowed = new Set([
    'schema_version', 'state_revision', 'next_item_number', 'items', 'journal', 'applied_transactions', 'book',
  ]);
  requireKnownKeys(state, allowed, 'state');
  requireCondition(
    state.schema_version === STATE_SCHEMA_VERSION,
    `state.schema_version must be ${STATE_SCHEMA_VERSION}`
  );
  let book = null;
  if (store.kind === 'book') {
    book = cleanText(state.book, 'state.book', { maxBytes: 180 });
    requireCondition(
      store.book !== null && book.toLowerCase() === store.book.toLowerCase(),
      `state.book「${book}」与目标书「${store.book}」不一致`
    );
  } else {
    requireCondition(
      !Object.prototype.hasOwnProperty.call(state, 'book'),
      'project-level state must not carry state.book：这份其实是书级 state。--workspace 指到了' +
        '长篇/、短篇/ 下的书目录时，改传创作工作区根、书目录放 --book-root；只有书根就是工作区' +
        '（单书布局）时，带 --book-root {工作区} 重跑任一命令即自动移进 .story/作者记忆/书级/'
    );
  }
  const revision = asInt(state.state_revision, 'state.state_revision');
  const nextNumber = asInt(state.next_item_number, 'state.next_item_number', { minimum: 1 });
  const rawItems = asMapping(state.items, 'state.items');
  const items = {};
  let maxNumber = 0;
  for (const [rawId, rawItem] of Object.entries(rawItems)) {
    const normalized = normalizeItem(rawItem, `state.items.${rawId}`);
    requireCondition(rawId === normalized.id, `state.items key ${rawId} does not match item id`);
    requireCondition(
      rawId.startsWith(store.prefix),
      `state.items.${rawId} does not belong to the ${store.label} store（前缀应为 ${store.prefix}）`
    );
    requireCondition(
      scopeFitsStore(normalized.scope, book),
      `state.items.${rawId} scope does not belong to book「${book}」`
    );
    maxNumber = Math.max(maxNumber, idNumber(rawId));
    requireCondition(
      normalized.created_revision <= normalized.updated_revision && normalized.updated_revision <= revision,
      `state.items.${rawId} revision is ahead of state`
    );
    items[rawId] = normalized;
  }
  requireCondition(nextNumber > maxNumber, 'state.next_item_number must be greater than every allocated item id');
  for (const [itemId, item] of Object.entries(items)) {
    for (const conflictId of item.conflicts_with) {
      requireCondition(
        Object.prototype.hasOwnProperty.call(items, conflictId) && conflictId !== itemId,
        `state.items.${itemId} has an invalid conflict id`
      );
    }
    if (item.superseded_by !== null) {
      requireCondition(
        Object.prototype.hasOwnProperty.call(items, item.superseded_by) && item.superseded_by !== itemId,
        `state.items.${itemId} has an invalid superseded_by id`
      );
    }
    if (item.status === 'active') {
      requireCondition(item.conflicts_with.length === 0, `active item ${itemId} cannot retain conflicts`);
    }
    if (item.status === 'pending') {
      requireCondition(item.conflicts_with.length === 0, `pending item ${itemId} cannot retain conflicts`);
    }
    if (item.status === 'conflict') {
      requireCondition(item.conflicts_with.length > 0, `conflict item ${itemId} must reference an active item`);
      requireCondition(
        item.conflicts_with.every((cid) => items[cid].status === 'active'),
        `conflict item ${itemId} must reference only active items`
      );
    }
    if (item.status !== 'superseded') {
      requireCondition(item.superseded_by === null, `only superseded item ${itemId} may set superseded_by`);
    }
  }
  const journal = asList(state.journal, 'state.journal');
  requireCondition(journal.length === revision, 'state.journal length must equal state.state_revision');
  const journalRevisions = new Map();
  for (let index = 0; index < journal.length; index += 1) {
    const mapping = asMapping(journal[index], `state.journal[${index}]`);
    requireKnownKeys(
      mapping,
      new Set(['revision', 'transaction_id', 'committed_at', 'summaries']),
      `state.journal[${index}]`
    );
    const entryRevision = asInt(mapping.revision, `state.journal[${index}].revision`, { minimum: 1 });
    requireCondition(entryRevision === index + 1, `state.journal[${index}].revision must be ${index + 1}`);
    const transactionId = cleanText(mapping.transaction_id, `state.journal[${index}].transaction_id`, { maxBytes: 128 });
    requireCondition(!journalRevisions.has(transactionId), `state.journal repeats transaction_id ${transactionId}`);
    journalRevisions.set(transactionId, entryRevision);
    cleanText(mapping.committed_at, `state.journal[${index}].committed_at`, { maxBytes: 64 });
    const summaries = asList(mapping.summaries, `state.journal[${index}].summaries`);
    requireCondition(summaries.length > 0, `state.journal[${index}].summaries must not be empty`);
    for (let sIdx = 0; sIdx < summaries.length; sIdx += 1) {
      cleanText(summaries[sIdx], `state.journal[${index}].summaries[${sIdx}]`, { maxBytes: 768 });
    }
  }
  const transactions = asMapping(state.applied_transactions, 'state.applied_transactions');
  const txKeys = Object.keys(transactions);
  requireCondition(
    txKeys.length === journalRevisions.size && txKeys.every((k) => journalRevisions.has(k)),
    'state.applied_transactions must match state.journal transaction ids'
  );
  for (const [transactionId, record] of Object.entries(transactions)) {
    cleanText(transactionId, 'state.applied_transactions key', { maxBytes: 128 });
    const mapping = asMapping(record, `state.applied_transactions.${transactionId}`);
    requireKnownKeys(mapping, new Set(['revision', 'digest', 'item_ids']), `state.applied_transactions.${transactionId}`);
    const txRevision = asInt(mapping.revision, `state.applied_transactions.${transactionId}.revision`, { minimum: 1 });
    requireCondition(
      txRevision === journalRevisions.get(transactionId),
      `state.applied_transactions.${transactionId}.revision does not match journal`
    );
    const digest = cleanText(mapping.digest, `state.applied_transactions.${transactionId}.digest`, { maxBytes: 64 });
    requireCondition(
      /^[0-9a-f]{64}$/.test(digest),
      `state.applied_transactions.${transactionId}.digest is invalid`
    );
    const itemIds = cleanIdList(mapping.item_ids, `state.applied_transactions.${transactionId}.item_ids`);
    requireCondition(itemIds.length > 0, `state.applied_transactions.${transactionId}.item_ids must not be empty`);
    requireCondition(
      itemIds.every((id) => Object.prototype.hasOwnProperty.call(items, id)),
      `state.applied_transactions.${transactionId}.item_ids references an unknown item`
    );
  }
  const result = {
    schema_version: STATE_SCHEMA_VERSION,
    state_revision: revision,
    next_item_number: nextNumber,
    items,
    journal: deepClone(journal),
    applied_transactions: deepClone(transactions),
  };
  if (book !== null) {
    result.book = book;
  }
  return result;
}

function loadState(store) {
  if (!exists(store.statePath)) return null;
  return validateState(readJson(store.statePath), { store });
}

function normalizePreference(value, label, { allowStatus }) {
  const preference = asMapping(value, label);
  const allowed = new Set([
    'kind', 'scope', 'assertion', 'quote', 'source_ref', 'source', 'confidence', 'importance', 'reason',
  ]);
  if (allowStatus) {
    allowed.add('status');
    allowed.add('conflicts_with');
  }
  requireKnownKeys(preference, allowed, label);
  const rawSource = preference.source;
  requireCondition(
    rawSource !== 'repeated_correction' && rawSource !== 'inferred_pattern',
    `${label}.source「${rawSource}」已不再写入：作者记忆只记作者明确表达的偏好，` +
      '不从重复修改或成稿轨迹推断；作者原话说的用 explicit_user'
  );
  const source = choice(rawSource, WRITE_SOURCES, `${label}.source`);
  const status = allowStatus && preference.status !== undefined ? preference.status : 'active';
  requireCondition(status === 'active', `${label}.status「${status}」：${NO_CANDIDATES}`);
  const conflicts =
    allowStatus && preference.conflicts_with !== undefined
      ? cleanIdList(preference.conflicts_with, `${label}.conflicts_with`)
      : [];
  requireCondition(conflicts.length === 0, `${label}.conflicts_with：${NO_CANDIDATES}`);
  return {
    kind: choice(preference.kind, KINDS, `${label}.kind`),
    scope: normalizeScope(preference.scope, `${label}.scope`),
    assertion: cleanText(preference.assertion, `${label}.assertion`, { maxBytes: LEGACY_ASSERTION_MAX_BYTES }),
    quote: cleanText(preference.quote, `${label}.quote`, { maxBytes: 768 }),
    source_ref: optionalText(preference.source_ref, `${label}.source_ref`, { maxBytes: 240 }),
    source,
    confidence: choice(preference.confidence, CONFIDENCE_LEVELS, `${label}.confidence`),
    importance: choice(preference.importance, IMPORTANCE_LEVELS, `${label}.importance`),
    status,
    reason: cleanText(preference.reason, `${label}.reason`, { maxBytes: 480 }),
    conflicts_with: conflicts,
  };
}

function normalizeTransaction(value) {
  const transaction = asMapping(value, 'transaction');
  requireKnownKeys(
    transaction,
    new Set(['schema_version', 'transaction_id', 'expected_state_revision', 'operations']),
    'transaction'
  );
  requireCondition(
    transaction.schema_version === INPUT_SCHEMA_VERSION,
    `transaction.schema_version must be ${INPUT_SCHEMA_VERSION}`
  );
  const transactionId = cleanText(transaction.transaction_id, 'transaction.transaction_id', { maxBytes: 128 });
  const operations = asList(transaction.operations, 'transaction.operations');
  requireCondition(
    operations.length >= 1 && operations.length <= 32,
    'transaction.operations must contain 1-32 operations'
  );
  const normalizedOperations = [];
  for (let index = 0; index < operations.length; index += 1) {
    const label = `transaction.operations[${index}]`;
    const operation = asMapping(operations[index], label);
    const action = operation.action;
    if (action === 'remember') {
      requireKnownKeys(operation, new Set(['action', 'preference']), label);
      normalizedOperations.push({
        action,
        preference: normalizePreference(operation.preference, `${label}.preference`, { allowStatus: true }),
      });
    } else if (action === 'decide') {
      throw new AuthorMemoryError(`${label}.action decide 已移除：${NO_CANDIDATES}`);
    } else if (action === 'replace') {
      requireKnownKeys(operation, new Set(['action', 'old_ids', 'preference']), label);
      const oldIds = cleanIdList(operation.old_ids, `${label}.old_ids`);
      requireCondition(oldIds.length > 0, `${label}.old_ids must not be empty`);
      normalizedOperations.push({
        action,
        old_ids: oldIds,
        preference: normalizePreference(operation.preference, `${label}.preference`, { allowStatus: false }),
      });
    } else if (action === 'forget') {
      requireKnownKeys(operation, new Set(['action', 'item_id', 'quote', 'reason']), label);
      normalizedOperations.push({
        action,
        item_id: cleanIdList([operation.item_id], `${label}.item_id`, { maximum: 1 })[0],
        quote: cleanText(operation.quote, `${label}.quote`, { maxBytes: 768 }),
        reason: cleanText(operation.reason, `${label}.reason`, { maxBytes: 480 }),
      });
    } else {
      throw new AuthorMemoryError(`${label}.action must be one of: remember, replace, forget`);
    }
  }
  return {
    schema_version: INPUT_SCHEMA_VERSION,
    transaction_id: transactionId,
    expected_state_revision: asInt(transaction.expected_state_revision, 'transaction.expected_state_revision'),
    operations: normalizedOperations,
  };
}

function normalizeRecordEvent(value) {
  const event = asMapping(value, 'event');
  requireKnownKeys(event, new Set(['schema_version', 'event_id', 'operation']), 'event');
  requireCondition(event.schema_version === INPUT_SCHEMA_VERSION, `event.schema_version must be ${INPUT_SCHEMA_VERSION}`);
  const eventId = cleanText(event.event_id, 'event.event_id', { maxBytes: 120 });
  const normalized = normalizeTransaction({
    schema_version: INPUT_SCHEMA_VERSION,
    transaction_id: `record:${eventId}`,
    expected_state_revision: 0,
    operations: [event.operation],
  });
  return { event_id: eventId, operation: normalized.operations[0] };
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

function scopeStoreKind(scope) {
  return scope.level === 'book' ? 'book' : 'project';
}

function storeKindLabel(kind) {
  return kind === 'book' ? '书级（BP）' : '项目级（AP）';
}

function operationStoreKind(operation, label) {
  const action = operation.action;
  if (action === 'forget') {
    return idStore(operation.item_id);
  }
  const preference = operation.preference;
  const kind = scopeStoreKind(preference.scope);
  if (action === 'remember') {
    return kind;
  }
  for (const oldId of operation.old_ids) {
    requireCondition(
      idStore(oldId) === kind,
      `${label} replace 不能跨 store：${oldId} 在${storeKindLabel(idStore(oldId))}，新条目范围属于${storeKindLabel(kind)}；` +
        '跨 store 改版拆成 forget＋remember，存量 book 条目先 migrate'
    );
  }
  return kind;
}

function transactionStoreKind(transaction) {
  const kinds = new Set(
    transaction.operations.map((op, index) => operationStoreKind(op, `transaction.operations[${index}]`))
  );
  requireCondition(
    kinds.size === 1,
    '一份事务只能写一个 store：项目级（global/genre/workflow 范围或 AP 编号）与书级（book 范围或 BP 编号）的操作要分开提交'
  );
  return [...kinds][0];
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

function transactionDigest(transaction) {
  const canonical = JSON.stringify(sortKeysDeep(transaction));
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

function fingerprint(preference) {
  const scope = preference.scope;
  const value = {
    kind: preference.kind,
    scope: { level: scope.level, value: scope.value === null ? null : scope.value.toLowerCase() },
    assertion: preference.assertion.toLowerCase(),
  };
  return JSON.stringify(sortKeysDeep(value));
}

function checkNewItemAssertion(preference, warnings) {
  const size = utf8Bytes(preference.assertion);
  if (size > ASSERTION_MAX_BYTES) {
    warnings.push(
      `新条目的 assertion ${size} 字节，超出建议上限 ${ASSERTION_MAX_BYTES} 字节（不影响本次写入；` +
        '建议后续精简为一句话，背景写进 reason；若是对已有条目的重申，原样使用该条目的 assertion 即可强化）。'
    );
  }
}

function requireScopeFitsStore(state, scope) {
  const book = state.book ?? null;
  if (book === null) {
    requireCondition(
      scope.level !== 'book',
      'book 级条目须传 --book-root {书目录}——记忆随书存放在 {书}/.story/作者记忆/，不再写进工作区的项目级 store'
    );
  } else {
    requireCondition(
      scopeFitsStore(scope, book),
      `book 条目的范围「${scope.value}」与本书 store「${book}」不一致——只有这本书的条目才住在这个书目录`
    );
  }
}

function nextItemId(state) {
  const prefix = state.book !== undefined && state.book !== null ? STORE_PREFIX.book : STORE_PREFIX.project;
  const itemId = `${prefix}${String(state.next_item_number).padStart(3, '0')}`;
  state.next_item_number += 1;
  return itemId;
}

function allocateItem(state, preference, revision, warnings = []) {
  checkNewItemAssertion(preference, warnings);
  requireScopeFitsStore(state, preference.scope);
  return {
    id: nextItemId(state),
    kind: preference.kind,
    scope: deepClone(preference.scope),
    assertion: preference.assertion,
    confidence: preference.confidence,
    importance: preference.importance,
    status: preference.status,
    source: preference.source,
    reason: preference.reason,
    conflicts_with: [...preference.conflicts_with],
    confirmation_count: 1,
    evidence: [{ quote: preference.quote, source_ref: preference.source_ref }],
    created_revision: revision,
    updated_revision: revision,
    superseded_by: null,
  };
}

function bestLevel(first, second) {
  return RANK[first] >= RANK[second] ? first : second;
}

function addEvidence(item, quote, sourceRef) {
  const existsEntry = item.evidence.some((e) => e.quote === quote && e.source_ref === sourceRef);
  if (!existsEntry) {
    item.evidence.push({ quote, source_ref: sourceRef });
  }
}

function requireItem(state, itemId, label) {
  requireCondition(Object.prototype.hasOwnProperty.call(state.items, itemId), `${label} references unknown item ${itemId}`);
  return state.items[itemId];
}

function applyRemember(state, preference, revision, warnings = []) {
  requireScopeFitsStore(state, preference.scope);
  const prefFp = fingerprint(preference);
  for (const item of Object.values(state.items)) {
    if (!['active', ...LEGACY_LIVE_STATUSES].includes(item.status) || fingerprint(item) !== prefFp) {
      continue;
    }
    requireCondition(item.status !== 'conflict', `旧版冲突候选 ${item.id} 要用 replace 换掉它冲突的旧条，或 forget 掉它`);
    addEvidence(item, preference.quote, preference.source_ref);
    item.confirmation_count += 1;
    item.confidence = bestLevel(item.confidence, preference.confidence);
    item.importance = bestLevel(item.importance, preference.importance);
    item.updated_revision = revision;
    item.reason = preference.reason;
    item.status = 'active';
    return `强化 ${item.id}：${item.assertion}`;
  }
  const item = allocateItem(state, preference, revision, warnings);
  state.items[item.id] = item;
  return `新增 ${item.id}（${item.status}）：${item.assertion}`;
}

function releaseConflicts(state, removedIds, revision) {
  let released = 0;
  for (const candidate of Object.values(state.items)) {
    if (candidate.status !== 'conflict') continue;
    const retained = candidate.conflicts_with.filter((id) => !removedIds.has(id));
    if (retained.length === candidate.conflicts_with.length) continue;
    candidate.conflicts_with = retained;
    candidate.updated_revision = revision;
    if (retained.length === 0) {
      candidate.status = 'pending';
      released += 1;
    }
  }
  return released;
}

function applyReplace(state, operation, revision, warnings = []) {
  const oldItems = operation.old_ids.map((itemId) => requireItem(state, itemId, 'replace'));
  for (const item of oldItems) {
    requireCondition(
      ['active', 'conflict', 'pending'].includes(item.status),
      `replace target ${item.id} is already ${item.status}`
    );
  }
  const replacement = allocateItem(state, operation.preference, revision, warnings);
  replacement.status = 'active';
  replacement.conflicts_with = [];
  state.items[replacement.id] = replacement;
  for (const item of oldItems) {
    item.status = 'superseded';
    item.superseded_by = replacement.id;
    item.updated_revision = revision;
  }
  const released = releaseConflicts(state, new Set(oldItems.map((i) => i.id)), revision);
  const replaced = oldItems.map((i) => i.id).join(', ');
  const suffix = released ? `；${released} 个其他冲突候选退回待确认` : '';
  return `用 ${replacement.id} 替代 ${replaced}：${replacement.assertion}${suffix}`;
}

function applyForget(state, operation, revision) {
  const item = requireItem(state, operation.item_id, 'forget');
  requireCondition(
    ['active', 'pending', 'conflict'].includes(item.status),
    `forget target ${item.id} is already ${item.status}`
  );
  item.status = 'superseded';
  item.superseded_by = null;
  item.reason = operation.reason;
  item.updated_revision = revision;
  addEvidence(item, operation.quote, null);
  const released = releaseConflicts(state, new Set([item.id]), revision);
  const suffix = released ? `；${released} 个冲突候选退回待确认` : '';
  return `忘记 ${item.id}：${item.assertion}${suffix}`;
}

function committedNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00');
}

function sealTransaction(updated, transactionId, digest, summaries, { store }) {
  const revision = updated.state_revision + 1;
  updated.state_revision = revision;
  updated.journal.push({
    revision,
    transaction_id: transactionId,
    committed_at: committedNow(),
    summaries,
  });
  const itemIds = Object.entries(updated.items)
    .filter(([, item]) => item.updated_revision === revision)
    .map(([id]) => id)
    .sort((a, b) => idNumber(a) - idNumber(b));
  requireCondition(itemIds.length > 0, 'transaction did not update any author-memory item');
  updated.applied_transactions[transactionId] = {
    revision,
    digest,
    item_ids: itemIds,
  };
  return validateState(updated, { store });
}

function applyTransaction(state, transaction, digest, { store }) {
  const applied = state.applied_transactions[transaction.transaction_id];
  if (applied !== undefined) {
    requireCondition(applied.digest === digest, 'transaction_id was already used with different content');
    return {
      updated: state,
      summaries: [`事务已应用于修订 ${applied.revision}，本次为幂等重放`],
      replayed: true,
      txWarnings: [],
    };
  }
  requireCondition(
    transaction.expected_state_revision === state.state_revision,
    `stale state revision: expected ${transaction.expected_state_revision}, current ${state.state_revision}`
  );
  const updated = deepClone(state);
  const revision = updated.state_revision + 1;
  const summaries = [];
  const txWarnings = [];
  for (const operation of transaction.operations) {
    if (operation.action === 'remember') {
      summaries.push(applyRemember(updated, operation.preference, revision, txWarnings));
    } else if (operation.action === 'replace') {
      summaries.push(applyReplace(updated, operation, revision, txWarnings));
    } else {
      summaries.push(applyForget(updated, operation, revision));
    }
  }
  return {
    updated: sealTransaction(updated, transaction.transaction_id, digest, summaries, { store }),
    summaries,
    replayed: false,
    txWarnings,
  };
}

// ---------------------------------------------------------------------------
// Derived views
// ---------------------------------------------------------------------------

function scopeLabel(scope) {
  if (scope.level === 'global') return '全局';
  const labels = { genre: '题材', book: '本书', workflow: '流程' };
  return `${labels[scope.level]}：${scope.value}`;
}

function storeCaption(state) {
  const book = state.book ?? null;
  if (book === null) {
    return '项目级记忆（全局、题材、流程）；各书的书级记忆住在各自书目录的 .story/作者记忆/。';
  }
  return `本书「${book}」的书级记忆；全局、题材、流程记忆住在工作区的 .story/作者记忆/。`;
}

function renderProfile(state) {
  const lines = [
    '# 作者画像',
    '',
    '<!-- 由 author_memory_commit.js 生成，请勿手改；修改请提交事务。 -->',
    '',
    `> 状态修订：${state.state_revision}。${storeCaption(state)}仅列出已确认偏好；当前明确要求、本书设定与硬性门禁优先。`,
    '',
  ];
  const active = Object.values(state.items).filter((item) => item.status === 'active');
  for (const kind of KINDS) {
    lines.push(`## ${KIND_TITLES[kind]}`, '');
    const items = active
      .filter((item) => item.kind === kind)
      .sort((a, b) => idNumber(a.id) - idNumber(b.id));
    if (!items.length) {
      lines.push('- 暂无', '');
      continue;
    }
    for (const item of items) {
      lines.push(
        `- **${item.id}**〔${scopeLabel(item.scope)}｜重要 ${item.importance}` +
          `｜把握 ${item.confidence}｜确认 ${item.confirmation_count} 次〕${item.assertion}`
      );
    }
    lines.push('');
  }
  return `${lines.join('\n').replace(/\s+$/, '')}\n`;
}

function renderJournal(state) {
  const lines = [
    '# 作者记忆变更记录',
    '',
    '<!-- 由 author_memory_commit.js 生成，请勿手改；最近记录在前。 -->',
    '',
    `> ${storeCaption(state)}`,
    '',
  ];
  if (!state.journal.length) {
    lines.push('暂无变更。', '');
  }
  const recent = state.journal.slice(-100).reverse();
  for (const entry of recent) {
    lines.push(`## r${entry.revision} · ${entry.committed_at}`, '', `- 事务：\`${entry.transaction_id}\``);
    for (const summary of entry.summaries) {
      lines.push(`- ${summary}`);
    }
    lines.push('');
  }
  return `${lines.join('\n').replace(/\s+$/, '')}\n`;
}

function renderViews(state) {
  const views = {
    '作者画像.md': renderProfile(state),
    '变更记录.md': renderJournal(state),
  };
  const softTargets = { '作者画像.md': PROFILE_MAX_BYTES, '变更记录.md': JOURNAL_MAX_BYTES };
  const viewWarnings = [];
  for (const [name, payload] of Object.entries(views)) {
    const size = utf8Bytes(payload);
    requireCondition(
      size <= VIEW_HARD_CAP_BYTES,
      `${name} (${size} bytes) exceeds hard cap of ${VIEW_HARD_CAP_BYTES} bytes; consolidate old memory first`
    );
    if (size > softTargets[name]) {
      viewWarnings.push(
        `${name} 当前 ${size} 字节，超出建议上限 ${softTargets[name]} 字节（不影响本次写入；说「整理作者记忆」可合并旧条目）`
      );
    }
  }
  return { views, viewWarnings };
}

function writeSnapshot(store, state) {
  const { views, viewWarnings } = renderViews(state);
  const statePayload = jsonPayload(state);
  requireCondition(
    utf8Bytes(statePayload) <= STATE_MAX_BYTES,
    `_author-memory-state.json exceeds ${STATE_MAX_BYTES} bytes`
  );
  for (const [name, payload] of Object.entries(views)) {
    writeIfChanged(path.join(store.root, name), payload);
  }
  const legacyView = path.join(store.root, LEGACY_PENDING_VIEW);
  if (isFile(legacyView)) {
    fs.unlinkSync(legacyView);
  }
  writeIfChanged(store.statePath, statePayload);
  return viewWarnings;
}

// ---------------------------------------------------------------------------
// Query & budget
// ---------------------------------------------------------------------------

function sameScopeValue(itemValue, requested) {
  return (
    requested !== null &&
    requested !== undefined &&
    itemValue !== null &&
    itemValue !== undefined &&
    itemValue.toLowerCase() === requested.toLowerCase()
  );
}

function summarizeAssertion(assertion, limit = 14) {
  const chars = Array.from(assertion);
  return chars.length <= limit ? assertion : `${chars.slice(0, limit).join('')}…`;
}

function compactItem(item) {
  return { id: item.id, kind: item.kind, scope: item.scope, assertion: item.assertion };
}

function renderLine(item) {
  return `- ${item.assertion}（${item.id}）`;
}

function lineBytes(item) {
  return utf8Bytes(`${renderLine(item)}\n`);
}

const SCOPE_RANK = { book: 0, genre: 1, workflow: 2, global: 3 };

function compareQueryItems(a, b) {
  const aKey = [
    -RANK[a.importance],
    SCOPE_RANK[a.scope.level],
    -a.updated_revision,
    -a.confirmation_count,
    idNumber(a.id),
  ];
  const bKey = [
    -RANK[b.importance],
    SCOPE_RANK[b.scope.level],
    -b.updated_revision,
    -b.confirmation_count,
    idNumber(b.id),
  ];
  for (let i = 0; i < aKey.length; i += 1) {
    if (aKey[i] !== bKey[i]) return aKey[i] - bKey[i];
  }
  return 0;
}

function fitItems(sortedItems, revision, extra = null) {
  const kept = [];
  const dropped = [];
  let used = 0;
  for (const item of sortedItems) {
    const size = lineBytes(item);
    if (used + size > QUERY_MAX_BYTES) {
      dropped.push(item);
      continue;
    }
    kept.push(item);
    used += size;
  }
  const omittedSummaries = {};
  const omittedImportance = {};
  for (const item of dropped) {
    omittedSummaries[item.id] = summarizeAssertion(item.assertion);
    omittedImportance[item.id] = item.importance;
  }
  const result = {
    ok: true,
    command: 'query',
    initialized: true,
    revision,
    items: kept.map(compactItem),
    lines: kept.map(renderLine),
    omitted: dropped.length,
    omitted_ids: dropped.map((item) => item.id),
    omitted_summaries: omittedSummaries,
    omitted_importance: omittedImportance,
    ...(extra || {}),
  };
  return { result, omittedIds: result.omitted_ids };
}

function buildQueryResult(candidates, projectState, bookState) {
  const extra = {};
  if (bookState !== null) {
    extra.book_revision = bookState.state_revision;
  }
  const revision = projectState !== null ? projectState.state_revision : 0;
  return fitItems(candidates, revision, extra);
}

function activeOfKinds(state, kinds) {
  if (state === null) return [];
  const kindSet = kinds instanceof Set ? kinds : new Set(kinds);
  return Object.values(state.items).filter((item) => item.status === 'active' && kindSet.has(item.kind));
}

function mergedQuery(projectState, bookState, kinds, requestedScopes) {
  const relevant = (item) => {
    if (item.status !== 'active' || !kinds.has(item.kind)) return false;
    const level = item.scope.level;
    if (level === 'global') return true;
    return level !== 'book' && sameScopeValue(item.scope.value, requestedScopes[level]);
  };
  const candidates = [];
  if (projectState !== null) {
    for (const item of Object.values(projectState.items)) {
      if (relevant(item)) candidates.push(item);
    }
  }
  if (bookState !== null) {
    candidates.push(...activeOfKinds(bookState, kinds));
  }
  candidates.sort(compareQueryItems);
  return buildQueryResult(candidates, projectState, bookState);
}

function sliceWeight(items) {
  return items.reduce((acc, item) => acc + lineBytes(item), 0);
}

function worstCaseItems(projectState, bookState, kinds) {
  const pool = activeOfKinds(projectState, kinds).filter((item) => item.scope.level !== 'book');
  const worst = pool.filter((item) => item.scope.level === 'global');
  const slices = { genre: new Map(), workflow: new Map() };
  for (const item of pool) {
    const level = item.scope.level;
    if (level !== 'global') {
      const key = (item.scope.value || '').toLowerCase();
      if (!slices[level].has(key)) slices[level].set(key, []);
      slices[level].get(key).push(item);
    }
  }
  for (const level of ['genre', 'workflow']) {
    if (slices[level].size > 0) {
      let heaviest = null;
      let maxWeight = -1;
      for (const group of slices[level].values()) {
        const w = sliceWeight(group);
        if (w > maxWeight) {
          maxWeight = w;
          heaviest = group;
        }
      }
      if (heaviest) worst.push(...heaviest);
    }
  }
  worst.push(...activeOfKinds(bookState, kinds));
  worst.sort(compareQueryItems);
  return worst;
}

function legacyBookItems(projectState) {
  if (projectState === null) return [];
  return Object.values(projectState.items).filter(
    (item) => item.scope.level === 'book' && ['active', 'pending', 'conflict'].includes(item.status)
  );
}

function queryBudgetWarnings(projectState, bookState) {
  const warnings = [];
  for (const [task, kinds] of Object.entries(QUERY_COMBOS)) {
    const worst = worstCaseItems(projectState, bookState, kinds);
    const { omittedIds } = buildQueryResult(worst, projectState, bookState);
    if (!omittedIds.length) continue;
    const assertions = Object.fromEntries(worst.map((item) => [item.id, item.assertion]));
    const shown = omittedIds
      .slice(0, 3)
      .map((id) => `${id}「${summarizeAssertion(assertions[id])}」`)
      .join('；');
    const more = omittedIds.length > 3 ? ` 等 ${omittedIds.length} 条` : '';
    warnings.push(
      `「${task}」最坏查询装不下 ${omittedIds.length} 条，它们不会进入 prompt：` +
        `${shown}${more}——超出 ${QUERY_MAX_BYTES} 字节注入预算。` +
        '说「整理作者记忆」可合并同义条、退役过时条。'
    );
  }
  return warnings;
}

function visibleStates(store, updated, workspace, bookRoot, book) {
  try {
    if (store.kind === 'project') {
      const other = bookRoot ? loadState(bookStore(workspace, bookRoot, book)) : null;
      return { projectState: updated, bookState: other, loadWarnings: [] };
    }
    return { projectState: loadState(projectStore(workspace)), bookState: updated, loadWarnings: [] };
  } catch (err) {
    if (!(err instanceof AuthorMemoryError)) throw err;
    const otherLabel = store.kind === 'project' ? '书级' : '项目级';
    const notice = `已写入${store.label} store；但${otherLabel} store 读取失败，本次预算提醒没算上它：${err.message}`;
    return store.kind === 'project'
      ? { projectState: updated, bookState: null, loadWarnings: [notice] }
      : { projectState: null, bookState: updated, loadWarnings: [notice] };
  }
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function prepareWorkspace(workspace, bookRoot = null) {
  requireCondition(isDir(workspace), `workspace does not exist: ${workspace}`);
  relocateMisplacedBookState(workspace, bookRoot);
}

function storeFields(store) {
  const fields = { store: store.kind, root: store.root };
  if (store.book !== null) {
    fields.book = store.book;
  }
  return fields;
}

function commandInit(workspace, bookRoot, book) {
  prepareWorkspace(workspace, bookRoot);
  const store = bookRoot ? bookStore(workspace, bookRoot, book) : projectStore(workspace);
  return withStoreWriteLock(store, () => {
    let state = loadState(store);
    if (state === null) {
      state = emptyState(store.book);
    }
    const viewWarnings = writeSnapshot(store, state);
    const out = { ok: true, command: 'init', revision: state.state_revision, ...storeFields(store) };
    if (viewWarnings.length) out.warnings = viewWarnings;
    return out;
  });
}

function commandCommit(workspace, bookRoot, book, inputPath) {
  prepareWorkspace(workspace, bookRoot);
  const transaction = normalizeTransaction(readJson(inputPath));
  const store = resolveTargetStore(transactionStoreKind(transaction), workspace, bookRoot, book);
  requireCondition(exists(store.statePath), `${store.label} author memory is not initialized; run init first`);
  return withStoreWriteLock(store, () => {
    requireCondition(exists(store.statePath), `${store.label} author memory is not initialized; run init first`);
    const state = loadState(store);
    const digest = transactionDigest(transaction);
    const { updated, summaries, replayed, txWarnings } = applyTransaction(state, transaction, digest, { store });
    const viewWarnings = writeSnapshot(store, updated);
    const { projectState, bookState, loadWarnings } = visibleStates(store, updated, workspace, bookRoot, book);
    return {
      ok: true,
      command: 'commit',
      revision: updated.state_revision,
      transaction_id: transaction.transaction_id,
      replayed,
      item_ids: updated.applied_transactions[transaction.transaction_id].item_ids,
      summaries,
      warnings: [...txWarnings, ...viewWarnings, ...loadWarnings, ...queryBudgetWarnings(projectState, bookState)],
      ...storeFields(store),
    };
  });
}

function commandRecord(workspace, bookRoot, book, inputPath) {
  prepareWorkspace(workspace, bookRoot);
  const event = normalizeRecordEvent(readJson(inputPath));
  const store = resolveTargetStore(operationStoreKind(event.operation, 'event.operation'), workspace, bookRoot, book);
  return withStoreWriteLock(store, () => {
    let state = loadState(store);
    if (state === null) {
      state = emptyState(store.book);
    }
    const transactionId = `record:${event.event_id}`;
    const applied = state.applied_transactions[transactionId];
    const expectedRevision = applied !== undefined ? applied.revision - 1 : state.state_revision;
    const transaction = {
      schema_version: INPUT_SCHEMA_VERSION,
      transaction_id: transactionId,
      expected_state_revision: expectedRevision,
      operations: [event.operation],
    };
    const digest = transactionDigest(transaction);
    const { updated, summaries, replayed, txWarnings } = applyTransaction(state, transaction, digest, { store });
    const viewWarnings = writeSnapshot(store, updated);
    const record = updated.applied_transactions[transactionId];
    const itemIds = record.item_ids;
    const receipt = `Author Memory Receipt: r${record.revision} · ${itemIds.join(', ')}`;
    const { projectState, bookState, loadWarnings } = visibleStates(store, updated, workspace, bookRoot, book);
    return {
      ok: true,
      command: 'record',
      revision: updated.state_revision,
      applied_revision: record.revision,
      event_id: event.event_id,
      replayed,
      item_ids: itemIds,
      receipt,
      summaries,
      warnings: [...txWarnings, ...viewWarnings, ...loadWarnings, ...queryBudgetWarnings(projectState, bookState)],
      ...storeFields(store),
    };
  });
}

function commandQuery(workspace, bookRoot, kinds, book, genre, workflow) {
  prepareWorkspace(workspace, bookRoot);
  requireCondition(
    Array.isArray(kinds) && kinds.length > 0,
    'query 必须显式传 --kind（按调用方 skill 写好的 query 命令选类型，对照见 references/author-memory.md「查询」），不再默认返回全部类型'
  );
  const projectState = loadState(projectStore(workspace));
  const bookState = bookRoot ? loadState(bookStore(workspace, bookRoot, book)) : null;
  if (projectState === null && bookState === null) {
    return {
      ok: true,
      command: 'query',
      initialized: false,
      revision: 0,
      items: [],
      lines: [],
      omitted: 0,
      omitted_ids: [],
      omitted_summaries: {},
      omitted_importance: {},
    };
  }
  const requestedScopes = {
    genre: optionalText(genre, 'query.genre', { maxBytes: 180 }),
    workflow: optionalText(workflow, 'query.workflow', { maxBytes: 180 }),
  };
  const { result } = mergedQuery(projectState, bookState, new Set(kinds), requestedScopes);
  const totalBytes = result.lines.reduce((acc, line) => acc + utf8Bytes(`${line}\n`), 0);
  requireCondition(totalBytes <= QUERY_MAX_BYTES, 'query lines exceed their fixed byte budget');
  return result;
}

function checkStore(store, { strict = false } = {}) {
  const state = loadState(store);
  requireCondition(state !== null, `${store.label} author memory is not initialized`);
  const { views, viewWarnings } = renderViews(state);
  const driftWarnings = [];
  for (const [name, expected] of Object.entries(views)) {
    const viewPath = path.join(store.root, name);
    if (!exists(viewPath)) {
      if (strict) {
        throw new AuthorMemoryError(`missing derived view: ${viewPath}`);
      }
      driftWarnings.push({
        store: store.kind,
        type: 'missing_view',
        file: name,
        path: viewPath,
        message: `missing derived view: ${viewPath}（请询问作者：是否按 _author-memory-state.json 重建派生视图？）`,
        prompt: '请询问作者：按 _author-memory-state.json 重建派生视图，还是补充对应事务？',
      });
      continue;
    }
    if (fs.readFileSync(viewPath, 'utf8').replace(/\r\n/g, '\n') !== expected) {
      if (strict) {
        throw new AuthorMemoryError(`derived view is stale or edited: ${viewPath}`);
      }
      driftWarnings.push({
        store: store.kind,
        type: 'view_drift',
        file: name,
        path: viewPath,
        message:
          `derived view is stale or edited: ${viewPath}（检测到手工修改或未同步视图；` +
          '请询问作者：要将手工改动通过事务吸回作者记忆，还是按 _author-memory-state.json 重建？）',
        prompt: '请询问作者：将手工改动吸回 _author-memory-state.json，还是按 JSON 重建派生视图？',
      });
    }
  }
  const counts = {};
  for (const status of STATUSES) {
    counts[status] = Object.values(state.items).filter((item) => item.status === status).length;
  }
  return { revision: state.state_revision, counts, driftWarnings, viewWarnings };
}

function commandCheck(workspace, bookRoot, book, { strict = false } = {}) {
  prepareWorkspace(workspace, bookRoot);
  const project = projectStore(workspace);
  const result = { ok: true, command: 'check' };
  const driftWarnings = [];
  const viewWarnings = [];
  if (bookRoot) {
    const store = bookStore(workspace, bookRoot, book);
    const checked = checkStore(store, { strict });
    result.book = { name: store.book, root: store.root, revision: checked.revision, counts: checked.counts };
    driftWarnings.push(...checked.driftWarnings);
    viewWarnings.push(...checked.viewWarnings);
    if (exists(project.statePath)) {
      const projChecked = checkStore(project, { strict });
      result.project = { root: project.root, revision: projChecked.revision, counts: projChecked.counts };
      driftWarnings.push(...projChecked.driftWarnings);
      viewWarnings.push(...projChecked.viewWarnings);
    }
  } else {
    const projChecked = checkStore(project, { strict });
    result.project = { root: project.root, revision: projChecked.revision, counts: projChecked.counts };
    driftWarnings.push(...projChecked.driftWarnings);
    viewWarnings.push(...projChecked.viewWarnings);
  }
  const primary = result.project || result.book;
  result.revision = primary.revision;
  result.counts = primary.counts;
  result.drift_warnings = driftWarnings;
  if (viewWarnings.length) {
    result.warnings = viewWarnings;
  }
  return result;
}

function migrationDigest(item) {
  return transactionDigest({
    id: item.id,
    kind: item.kind,
    scope: item.scope,
    assertion: item.assertion,
  });
}

function migratedItem(source, newId, revision, idMap) {
  const item = deepClone(source);
  item.id = newId;
  item.created_revision = revision;
  item.updated_revision = revision;
  item.superseded_by = null;
  item.conflicts_with = source.conflicts_with.filter((old) => Object.prototype.hasOwnProperty.call(idMap, old)).map((old) => idMap[old]);
  if (item.status === 'conflict' && item.conflicts_with.length === 0) {
    item.status = 'pending';
  }
  return item;
}

function migrationRecords(state) {
  const records = {};
  for (const [transactionId, record] of Object.entries(state.applied_transactions)) {
    if (transactionId.startsWith(MIGRATE_PREFIX)) {
      const sourceId = transactionId.slice(MIGRATE_PREFIX.length);
      if (isItemId(sourceId)) {
        records[sourceId] = record.item_ids[0];
      }
    }
  }
  return records;
}

function applySingle(state, transactionId, digest, mutate, summaries, { store }) {
  const updated = deepClone(state);
  mutate(updated, updated.state_revision + 1);
  return sealTransaction(updated, transactionId, digest, summaries, { store });
}

function commandMigrate(workspace, bookRoot, book) {
  prepareWorkspace(workspace, bookRoot);
  requireCondition(
    bookRoot !== null && bookRoot !== undefined,
    'migrate 须传 --book-root {书目录}：书名到书目录的映射由调用方给出'
  );
  const project = projectStore(workspace);
  const store = bookStore(workspace, bookRoot, book);
  if (!exists(project.statePath)) {
    const bookState = loadState(store);
    return {
      ok: true,
      command: 'migrate',
      migrated: [],
      project_revision: 0,
      revision: bookState !== null ? bookState.state_revision : 0,
      warnings: queryBudgetWarnings(null, bookState),
      ...storeFields(store),
    };
  }
  return withStoreWriteLock(project, () => {
    let projectState = loadState(project);
    const buildResult = (migrated, bookState) => ({
      ok: true,
      command: 'migrate',
      migrated,
      project_revision: projectState !== null ? projectState.state_revision : 0,
      revision: bookState !== null ? bookState.state_revision : 0,
      warnings: queryBudgetWarnings(projectState, bookState),
      ...storeFields(store),
    });

    if (projectState === null) return buildResult([], loadState(store));
    const legacy = legacyBookItems(projectState)
      .filter((item) => sameScopeValue(item.scope.value, store.book))
      .sort((a, b) => idNumber(a.id) - idNumber(b.id));
    if (!exists(store.statePath) && !legacy.length) {
      return buildResult([], null);
    }
    return withStoreWriteLock(store, () => {
      let bookState = loadState(store);
      if (bookState === null) {
        if (!legacy.length) return buildResult([], null);
        bookState = emptyState(store.book);
      }
      const idMap = migrationRecords(bookState);

      for (const item of legacy) {
        if (Object.prototype.hasOwnProperty.call(idMap, item.id)) continue;
        const transactionId = `${MIGRATE_PREFIX}${item.id}`;
        const newId = `${STORE_PREFIX.book}${String(bookState.next_item_number).padStart(3, '0')}`;
        const preview = migratedItem(item, newId, 1, idMap);
        bookState = applySingle(
          bookState,
          transactionId,
          migrationDigest(item),
          (updated, revision) => {
            updated.next_item_number += 1;
            updated.items[newId] = migratedItem(item, newId, revision, idMap);
          },
          [`迁移 ${item.id} → ${newId}（${preview.status}）：${item.assertion}`],
          { store }
        );
        idMap[item.id] = newId;
      }
      writeSnapshot(store, bookState);

      const migrated = legacy.map((item) => ({ from: item.id, to: idMap[item.id] }));
      if (legacy.length) {
        const transactionId = `${MIGRATE_PREFIX}${store.book.toLowerCase()}:r${projectState.state_revision + 1}`;
        const digest = transactionDigest({ transaction_id: transactionId, migrated });
        const summaries = migrated.map(
          (pair) => `迁出 ${pair.from} → ${pair.to}：${projectState.items[pair.from].assertion}`
        );
        projectState = applySingle(
          projectState,
          transactionId,
          digest,
          (updated, revision) => {
            for (const item of legacy) {
              const target = updated.items[item.id];
              target.status = 'superseded';
              target.superseded_by = null;
              target.conflicts_with = [];
              target.reason = `已迁移到书级 store「${store.book}」：${idMap[item.id]}`;
              target.updated_revision = revision;
            }
            releaseConflicts(updated, new Set(Object.keys(idMap)), revision);
          },
          summaries,
          { store: project }
        );
        writeSnapshot(project, projectState);
      }
      return buildResult(migrated, bookState);
    });
  });
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

function parseCliArgs(argv) {
  if (!argv.length || argv[0] === '-h' || argv[0] === '--help') {
    return { help: !argv.length ? false : true, error: !argv.length ? 'command is required' : null };
  }
  const command = argv[0];
  if (!['init', 'commit', 'record', 'query', 'migrate', 'check'].includes(command)) {
    return { error: `invalid command: ${command}` };
  }
  const args = {
    command,
    workspace: null,
    bookRoot: null,
    book: null,
    input: null,
    kind: [],
    genre: null,
    workflow: null,
    strict: false,
  };
  for (let i = 1; i < argv.length; i += 1) {
    const token = argv[i];
    const readVal = (flag) => {
      if (token.includes('=')) return token.slice(token.indexOf('=') + 1);
      if (i + 1 >= argv.length) throw new Error(`${flag} requires a value`);
      return argv[++i];
    };
    try {
      if (token === '--workspace' || token.startsWith('--workspace=')) {
        args.workspace = readVal('--workspace');
      } else if (token === '--book-root' || token.startsWith('--book-root=')) {
        args.bookRoot = readVal('--book-root');
      } else if (token === '--book' || token.startsWith('--book=')) {
        args.book = readVal('--book');
      } else if ((command === 'commit' || command === 'record') && (token === '--input' || token.startsWith('--input='))) {
        args.input = readVal('--input');
      } else if (command === 'check' && token === '--strict') {
        args.strict = true;
      } else if (command === 'query' && (token === '--kind' || token.startsWith('--kind='))) {
        const val = readVal('--kind');
        if (!KINDS.includes(val)) {
          return { error: `invalid --kind: ${val} (choose from ${KINDS.join(', ')})` };
        }
        args.kind.push(val);
      } else if (command === 'query' && (token === '--genre' || token.startsWith('--genre='))) {
        args.genre = readVal('--genre');
      } else if (command === 'query' && (token === '--workflow' || token.startsWith('--workflow='))) {
        args.workflow = readVal('--workflow');
      } else {
        return { error: `unrecognized argument: ${token}` };
      }
    } catch (err) {
      return { error: err.message };
    }
  }
  if (!args.workspace) return { error: 'missing required --workspace' };
  if ((command === 'commit' || command === 'record') && !args.input) {
    return { error: 'missing required --input' };
  }
  return args;
}

function main(argv = process.argv.slice(2)) {
  const args = parseCliArgs(argv);
  if (args.help) {
    process.stdout.write(
      'usage: node author_memory_commit.js {init,commit,record,query,migrate,check} --workspace DIR [--book-root DIR] [--book NAME] [--input FILE] [--kind KIND ...] [--strict]\n'
    );
    return 0;
  }
  if (args.error) {
    process.stderr.write(`error: ${args.error}\n`);
    return 2;
  }
  try {
    let result;
    if (args.command === 'init') {
      result = commandInit(args.workspace, args.bookRoot, args.book);
    } else if (args.command === 'commit') {
      result = commandCommit(args.workspace, args.bookRoot, args.book, args.input);
    } else if (args.command === 'record') {
      result = commandRecord(args.workspace, args.bookRoot, args.book, args.input);
    } else if (args.command === 'query') {
      result = commandQuery(
        args.workspace,
        args.bookRoot,
        args.kind.length ? args.kind : null,
        args.book,
        args.genre,
        args.workflow
      );
    } else if (args.command === 'migrate') {
      result = commandMigrate(args.workspace, args.bookRoot, args.book);
    } else {
      result = commandCheck(args.workspace, args.bookRoot, args.book, { strict: args.strict });
    }
    emit(result);
    return 0;
  } catch (err) {
    if (err instanceof AuthorMemoryError) {
      emit({ ok: false, error: err.message }, { error: true });
      return 2;
    }
    throw err;
  }
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  KINDS,
  QUERY_COMBOS,
  QUERY_MAX_BYTES,
  ASSERTION_MAX_BYTES,
  AuthorMemoryError,
  compactItem,
  lineBytes,
  compareQueryItems,
  fitItems,
  mergedQuery,
  sliceWeight,
  queryBudgetWarnings,
  commandInit,
  commandCommit,
  commandRecord,
  commandQuery,
  commandMigrate,
  commandCheck,
  withStoreWriteLock,
  projectStore,
  bookStore,
  main,
};
