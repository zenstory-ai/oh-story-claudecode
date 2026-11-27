#!/usr/bin/env node
'use strict';
/**
 * build_writer_prompt.js — 确定性组装 narrative-writer 的 spawn prompt 骨架。
 *
 * 用法:
 *   node build_writer_prompt.js --project <书目录> --chapter N [--out [<文件>]]
 * `--out` 不带路径时留档到 `<书目录>/.story/work/第NNN章/writer_prompt.md`。
 * stdout 分两区：`===` 分隔线以上为 prompt 正文，以下为核对报告（不进 prompt）。
 * Exit: 0 = 骨架已输出；2 = 必在输入缺失或无效。
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  CHAPTER_UNIT_FIELDS,
  UNIT_FIELD_NAMES: UNIT_CARD_FIELDS,
  chapterUnitInVolume,
  isUnitCard,
  parse: parseVolume,
} = require('./outline_view.js');
const { WordcountError, resolveBookDir } = require('./wordcount_core.js');

const OUTLINE_MUST = {
  目标情绪: ['目标情绪', '这一章要让读者感到什么'],
  '主角目标/关键选择': ['主角目标/关键选择', '主角目标／关键选择', '主角这一章想要什么，做了什么选择'],
};
const PLACEHOLDER_RE = /^[{｛].*[}｝]$|^\[?待补充\]?$|^(?:无|待定|todo|TODO|…+|\.{3,})$/;
const UNIT_FIELD_NAMES = [...CHAPTER_UNIT_FIELDS, '单元ID／位置', '所属剧情段', '单元ID'];
const ENGINE_FIELD_NAMES = UNIT_CARD_FIELDS['单元情绪引擎'];
const TEMPO_FIELD_NAMES = [...UNIT_CARD_FIELDS['单元节拍/章功能分配'], '单元节拍'];
const TAIL_CHARS = 400;
const TIMELINE_ANCHOR_MAX_EVENTS = 5;
const TIMELINE_ANCHOR_MAX_CHARS = 180;
const TIMELINE_ANCHOR_MIN_FACT_CHARS = 6;
const STATE_SECTIONS = ['当前位置', '长期约束', '核心角色状态', '活跃伏笔', '近三章速记', '下一章承诺', '连贯性风险'];
const SLOT_MARK = '［主会话填］';
const AUTHOR_DECIDED_CHARS = 600;
const WORK_ROOT = ['.story', 'work'];
const MEMORY_KINDS = ['prose_style', 'story_design'];
const IMPORTANCE_RANK = { low: 1, medium: 2, high: 3 };
const MISSED_SHOWN = 8;
const LONG_WRITE_WORKFLOWS = new Set([
  '长篇', '长篇写作', '写长篇', '长篇连载', '长篇网文', '长篇正文', 'story-long-write',
]);
const WORKSPACE_MARKERS = ['.active-book', '长篇', '短篇', '拆文库'];
const GENRE_CARD_DIR = path.resolve(__dirname, '..', 'references', 'genre-styles');
const FALLBACK_CARD = path.join(GENRE_CARD_DIR, '通用长篇.md');

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function isDir(p) {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function exists(p) {
  try {
    fs.statSync(p);
    return true;
  } catch {
    return false;
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

function pad3(n) {
  return String(n).padStart(3, '0');
}

function chapterWorkDir(project, chapter) {
  const s = String(chapter);
  const padded = s.padStart(Math.max(3, s.length), '0');
  return path.join(project, ...WORK_ROOT, `第${padded}章`);
}

function readText(filePath) {
  try {
    const raw = fs.readFileSync(filePath);
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    return text.replace(/^\ufeff/, '').replace(/\r\n/g, '\n');
  } catch {
    return null;
  }
}

function substantive(text) {
  if (!text) return false;
  let body = text.replace(/^#{1,6}[^\n]*/gm, '');
  body = body.replace(/待补充|待办|待定|暂无|TODO|TBD/gi, '');
  return Boolean(body.replace(/[\s_#*\[\]【】{}。，；:：-]/g, ''));
}

function stripHtmlComments(text) {
  const src = text || '';
  let out = '';
  let cursor = 0;
  while (cursor < src.length) {
    const start = src.indexOf('<!--', cursor);
    if (start === -1) {
      out += src.slice(cursor);
      break;
    }
    out += src.slice(cursor, start);
    const end = src.indexOf('-->', start + 4);
    if (end === -1) {
      out += src.slice(start);
      break;
    }
    cursor = end + 3;
  }
  return out;
}

function hasCustomStyle(text) {
  return substantive(stripHtmlComments(text));
}

function escapeRegExp(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function findChapterFile(directory, chapter, prefix) {
  if (!isDir(directory)) return null;
  const pattern = new RegExp(`^${escapeRegExp(prefix)}第0*${chapter}章.*\\.md$`);
  for (const name of fs.readdirSync(directory).sort()) {
    const full = path.join(directory, name);
    if (isFile(full) && pattern.test(name) && !name.includes('_原稿_')) {
      return full;
    }
  }
  return null;
}

const RANGE_OUTLINE_RE = /^细纲_第(\d+)[-–—~～至到]第?(\d+)章.*\.md$/;

function extractChapterSlice(text, chapter) {
  const lines = text.split(/\r?\n/);
  const targetRe = new RegExp(`^#{2,3}\\s*第\\s*0*${chapter}\\s*章(?:[：:\\s]|$)`);
  const anyChapterRe = /^#{2,3}\s*第\s*\d+\s*章(?:[：:\s]|$)/;
  const start = lines.findIndex((line) => targetRe.test(line));
  if (start === -1) return null;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i += 1) {
    if (anyChapterRe.test(lines[i])) {
      end = i;
      break;
    }
  }
  return lines.slice(start, end).join('\n');
}

function findOutlineFile(outlineDir, chapter) {
  const direct = findChapterFile(outlineDir, chapter, '细纲_');
  if (direct) return { file: direct, fromRangeFile: false };
  if (!isDir(outlineDir)) return null;
  for (const name of fs.readdirSync(outlineDir).sort()) {
    const full = path.join(outlineDir, name);
    if (!isFile(full) || name.includes('_原稿_')) continue;
    const match = RANGE_OUTLINE_RE.exec(name);
    if (!match) continue;
    const start = Number(match[1]);
    const end = Number(match[2]);
    if (Number.isInteger(start) && Number.isInteger(end) && start <= chapter && chapter <= end) {
      return { file: full, fromRangeFile: true };
    }
  }
  return null;
}

function extractField(outlineText, field) {
  const lines = outlineText.split(/\r?\n/);
  const pattern = new RegExp(`^([ \\t]*)[-*+]\\s+\\*{0,2}${escapeRegExp(field)}\\*{0,2}[ \\t]*[：:][ \\t]*(.*)$`);
  for (let index = 0; index < lines.length; index += 1) {
    const match = pattern.exec(lines[index]);
    if (!match) continue;
    const values = [match[2]];
    for (const following of lines.slice(index + 1)) {
      const bullet = /^([ \t]*)[-*+]\s/.exec(following);
      if (/^#{1,6}\s/.test(following) || (bullet && bullet[1].length <= match[1].length)) {
        break;
      }
      values.push(following);
    }
    return values.join('\n').trim();
  }
  return null;
}

function extractAny(text, names) {
  for (const name of names) {
    const value = extractField(text, name);
    if (value !== null) return value;
  }
  return null;
}

function outlineGaps(outlineText) {
  const missing = [];
  for (const [name, labels] of Object.entries(OUTLINE_MUST)) {
    const raw = (extractAny(outlineText, labels) || '').replace(/\*\*/g, '');
    const cleaned = raw.replace(/\s+/g, ' ').trim();
    if (!cleaned || PLACEHOLDER_RE.test(cleaned)) {
      missing.push(name);
    }
  }
  return missing;
}

function unitIdFrom(field) {
  const match =
    /[A-Za-z]+\d+(?:-\d+)+/.exec(field) ||
    /^([A-Za-z0-9-]+)/.exec(field) ||
    /(第[一二三四五六七八九十百\d]+段)/.exec(field);
  return match ? match[1] || match[0] : null;
}

function ownNames(project) {
  const names = new Set([path.basename(project)]);
  const text = stripHtmlComments(readText(path.join(project, '设定', '题材定位.md')));
  const match = /^[ \t]*[-*+]?[ \t]*\**书名\**[ \t]*[：:][ \t]*(.+)$/m.exec(text);
  if (match && !match[1].includes('{')) {
    const cleaned = match[1].replace(/[（(][^）)]*[）)]/g, '').trim().replace(/^《+|》+$/g, '');
    if (cleaned) names.add(cleaned);
  }
  return new Set([...names].filter(Boolean));
}

function benchmarkRegistry(project) {
  const text = stripHtmlComments(readText(path.join(project, '设定', '题材定位.md')));
  const values = [];
  for (const label of ['主对标书', '对标']) {
    const re = new RegExp(`^[ \\t>]*(?:[-*+][ \\t]*)?\\**${label}\\**[ \\t]*[：:][ \\t]*(.*)$`, 'gm');
    let m;
    while ((m = re.exec(text)) !== null) {
      const v = m[1].trim();
      if (v && !v.startsWith('{') && !v.startsWith('｛')) {
        values.push(v);
      }
    }
  }
  if (values.some((v) => /^(无|不对标|都不用|没有)/.test(v))) {
    return 'none';
  }
  const secMatch = /^##[ \t]*对标登记[^\n]*\n([\s\S]*?)(?=^##[ \t]|$(?![\r\n]))/m.exec(text);
  const rows = [];
  if (secMatch) {
    for (const line of secMatch[1].split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('|')) continue;
      const cells = trimmed.replace(/^\|+|\|+$/g, '').split('|').map((c) => c.trim());
      if (
        cells.length &&
        cells[0] &&
        cells[0] !== '书名' &&
        !/^[-:\s]+$/.test(cells[0]) &&
        !cells[0].startsWith('{')
      ) {
        rows.push(cells[0]);
      }
    }
  }
  return values.length || rows.length ? 'registered' : 'missing';
}

function extractTitle(outlineText, chapter) {
  const match = new RegExp(`^#{1,4}\\s*第\\s*0*${chapter}\\s*章\\s*[：:]\\s*(.+?)\\s*$`, 'm').exec(outlineText);
  return match ? match[1].trim() : null;
}

function extractUnitBlock(volumeText, unitId) {
  const { lines, sections } = parseVolume(volumeText);
  for (const sec of sections) {
    if (sec.unit !== unitId || !isUnitCard(sec) || sec.status === '已退役') continue;
    const nextSame = sections.find((o) => o.start > sec.start && o.level <= sec.level);
    const end = nextSame ? nextSame.start : lines.length;
    return lines.slice(sec.start, end).join('\n').trim();
  }
  return null;
}

function extractStateSections(stateText) {
  const found = {};
  for (const sec of STATE_SECTIONS) {
    const re = new RegExp(`^##\\s*${escapeRegExp(sec)}\\s*$([\\s\\S]*?)(?=^##\\s|$(?![\\r\\n]))`, 'm');
    const match = re.exec(stateText);
    if (match && match[1].trim()) {
      found[sec] = match[1].trim();
    }
  }
  return found;
}

function truncateChars(text, maxChars) {
  const chars = Array.from(String(text || '').trim().replace(/\s+/g, ' '));
  if (chars.length <= maxChars) return chars.join('');
  return maxChars > 1 ? `${chars.slice(0, maxChars - 1).join('')}…` : chars.slice(0, maxChars).join('');
}

function recentTimelineAnchors(project) {
  const stateFile = path.join(project, '追踪', '_tracking-state.json');
  if (!isFile(stateFile)) return null;
  const raw = readText(stateFile);
  if (!raw) return { error: '追踪/_tracking-state.json 为空或不可读，请先修复或重新 /story-import，不能带着损毁状态继续写正文' };
  let state;
  try {
    state = JSON.parse(raw);
  } catch (err) {
    return { error: `追踪/_tracking-state.json 无法解析（${err.message}），请先修复或重新 /story-import，不能带着损毁状态继续写正文` };
  }
  if (!state || typeof state !== 'object' || Array.isArray(state)) {
    return { error: '追踪/_tracking-state.json 顶层不是合法对象，请先修复或重新 /story-import' };
  }
  let events = [];
  if (state.timeline && typeof state.timeline === 'object' && !Array.isArray(state.timeline)) {
    events = Object.values(state.timeline);
  } else if (Array.isArray(state.timeline_events)) {
    events = state.timeline_events;
  }
  const valid = events
    .filter((ev) => ev && typeof ev === 'object' && typeof ev.story_time === 'string' && ev.story_time.trim())
    .map((ev) => {
      const ch = Number.isInteger(ev.reveal_chapter) && ev.reveal_chapter >= 1
        ? ev.reveal_chapter
        : Number.isInteger(ev.first_recorded_chapter) && ev.first_recorded_chapter >= 1
          ? ev.first_recorded_chapter
          : Number.isInteger(ev.updated_chapter)
            ? ev.updated_chapter
            : 0;
      const id = typeof ev.id === 'string' ? ev.id.trim() : '';
      const storyTime = ev.story_time.trim().replace(/\s+/g, ' ');
      const unrevealed = ev.reveal_status === '未揭示';
      const rawFact = unrevealed
        ? (typeof ev.reader_knowledge === 'string' ? ev.reader_knowledge : '')
        : (typeof ev.objective_fact === 'string' && ev.objective_fact.trim()
            ? ev.objective_fact
            : (typeof ev.reader_knowledge === 'string' ? ev.reader_knowledge : ''));
      return { id, ch, storyTime, fact: rawFact.trim().replace(/\s+/g, ' ') };
    })
    .sort((a, b) => (a.ch !== b.ch ? a.ch - b.ch : a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  if (!valid.length) return null;

  const recent = valid.slice(-TIMELINE_ANCHOR_MAX_EVENTS);
  const posTime =
    state.context &&
    state.context.position &&
    typeof state.context.position.story_time === 'string'
      ? state.context.position.story_time.trim().replace(/\s+/g, ' ')
      : '';
  const lastCh = Number.isInteger(state.last_committed_chapter) ? state.last_committed_chapter : 0;
  const headerPrefix = posTime
    ? `当前(${lastCh > 0 ? `第${lastCh}章末` : '起点'})：${truncateChars(posTime, 24)}`
    : '';

  const picked = [];
  let used = Array.from(headerPrefix).length;
  for (let i = recent.length - 1; i >= 0; i -= 1) {
    const ev = recent[i];
    const baseTag = `${ev.id ? `${ev.id}` : ''}(${ev.ch > 0 ? `第${ev.ch}章揭·` : ''}${truncateChars(ev.storyTime, 22)})`;
    const sepLen = picked.length > 0 ? 1 : 0;
    const baseLen = Array.from(baseTag).length;
    if (ev.fact) {
      const fullFact = truncateChars(ev.fact, 10);
      const withFact = `${baseTag}${fullFact}`;
      const withFactLen = Array.from(withFact).length;
      const availForFact = TIMELINE_ANCHOR_MAX_CHARS - used - sepLen - baseLen;
      if (used + sepLen + withFactLen <= TIMELINE_ANCHOR_MAX_CHARS) {
        picked.push(withFact);
        used += sepLen + withFactLen;
      } else if (availForFact >= TIMELINE_ANCHOR_MIN_FACT_CHARS) {
        const fitted = `${baseTag}${truncateChars(ev.fact, availForFact)}`;
        picked.push(fitted);
        used += sepLen + Array.from(fitted).length;
      } else if (picked.length === 0) {
        const budget = Math.max(8, TIMELINE_ANCHOR_MAX_CHARS - used - sepLen);
        picked.push(truncateChars(withFact, budget));
        used = TIMELINE_ANCHOR_MAX_CHARS;
        break;
      } else {
        break;
      }
    } else if (used + sepLen + baseLen <= TIMELINE_ANCHOR_MAX_CHARS) {
      picked.push(baseTag);
      used += sepLen + baseLen;
    } else if (picked.length === 0) {
      const budget = Math.max(8, TIMELINE_ANCHOR_MAX_CHARS - used - sepLen);
      picked.push(truncateChars(baseTag, budget));
      used = TIMELINE_ANCHOR_MAX_CHARS;
      break;
    } else {
      break;
    }
  }
  picked.reverse();
  const body = headerPrefix ? `${headerPrefix}\n${picked.join('；')}` : picked.join('；');
  return { text: body, count: picked.length };
}

function previousChapterTail(project, chapter) {
  const prev = findChapterFile(path.join(project, '正文'), chapter - 1, '');
  const text = prev ? readText(prev) : null;
  if (!text) return { prev, tail: null };
  const nonEmpty = text.replace(/\s+$/, '').split(/\r?\n/).filter((ln) => ln.trim());
  const picked = [];
  let total = 0;
  for (let i = nonEmpty.length - 1; i >= 0; i -= 1) {
    picked.push(nonEmpty[i]);
    total += Array.from(nonEmpty[i]).length;
    if (total >= TAIL_CHARS) break;
  }
  return { prev, tail: picked.reverse().join('\n') };
}

function scopedMemoryValues(workspace) {
  const values = { genre: new Set(), workflow: new Set() };
  const state = readText(path.join(workspace, '.story', '作者记忆', '_author-memory-state.json'));
  let items = [];
  try {
    const parsed = state ? JSON.parse(state) : {};
    if (parsed && typeof parsed === 'object' && parsed.items && typeof parsed.items === 'object') {
      items = Object.values(parsed.items);
    }
  } catch {
    return values;
  }
  for (const item of items) {
    if (!item || typeof item !== 'object') continue;
    const scope = item.scope && typeof item.scope === 'object' ? item.scope : {};
    if (
      item.status === 'active' &&
      MEMORY_KINDS.includes(item.kind) &&
      Object.prototype.hasOwnProperty.call(values, scope.level) &&
      scope.value
    ) {
      values[scope.level].add(scope.value);
    }
  }
  return values;
}

function memoryStateKind(directory) {
  const text = readText(path.join(directory, '.story', '作者记忆', '_author-memory-state.json'));
  if (!text) return null;
  let document;
  try {
    document = JSON.parse(text);
  } catch {
    return null;
  }
  if (!document || typeof document !== 'object' || Array.isArray(document)) return null;
  return typeof document.book === 'string' && document.book.trim() ? 'book' : 'project';
}

function ancestors(dirPath) {
  const list = [];
  let prev = dirPath;
  let cur = path.dirname(dirPath);
  while (cur !== prev) {
    list.push(cur);
    prev = cur;
    cur = path.dirname(cur);
  }
  return list;
}

function findWorkspace(project) {
  const resolved = realOrResolve(project);
  const chain = [resolved, ...ancestors(resolved)];
  const deployed = chain.find((d) => isFile(path.join(d, '.story-deployed')));
  if (deployed) return { workspace: deployed, recognised: true };
  const parent = path.dirname(resolved);
  if (parent !== resolved && ['长篇', '短篇'].includes(path.basename(parent))) {
    return { workspace: path.dirname(parent), recognised: true };
  }
  if (memoryStateKind(resolved) === 'project' || isDir(path.join(resolved, '.story', '作者记忆', '书级'))) {
    return { workspace: resolved, recognised: true };
  }
  let home = null;
  try {
    home = realOrResolve(os.homedir());
  } catch {
    home = null;
  }
  for (const ancestor of ancestors(resolved)) {
    if (home && ancestor === home) break;
    if (
      WORKSPACE_MARKERS.some((marker) => exists(path.join(ancestor, marker))) ||
      memoryStateKind(ancestor) === 'project'
    ) {
      return { workspace: ancestor, recognised: true };
    }
  }
  return { workspace: resolved, recognised: false };
}

function genreLine(project) {
  const text = stripHtmlComments(readText(path.join(project, '设定', '题材定位.md')));
  const labels = ['题材参考包', '题材类型', '流派', '题材', '主类型', '子类型'];
  const parts = [];
  for (const label of labels) {
    const re = new RegExp(`^[ \\t]*[-*+]?[ \\t]*\\**${label}\\**[ \\t]*[：:](.*)$`, 'gm');
    let m;
    while ((m = re.exec(text)) !== null) {
      const val = m[1].trim();
      if (val && !val.includes('{') && !val.includes('｛') && !parts.includes(val)) {
        parts.push(val);
      }
    }
  }
  return parts.join(' / ');
}

function bookGenres(project) {
  return new Set(
    genreLine(project)
      .split(/[^\p{L}\p{N}]+|[丨×]+/u)
      .filter(Boolean)
      .map((w) => w.toLowerCase())
  );
}

const BL_GENRE_CARDS = new Set(['双男主.md']);
const DUAL_CHANNEL_GENRE_CARDS = new Set(['悬疑灵异.md']);
const FEMALE_GENRE_CARDS = new Set([
  '幻想言情仙侠.md', '古言宅斗重生.md', '豪门虐恋追妻.md',
  '现言脑洞快穿.md', '年代种田经商.md', '青春甜宠文娱.md',
  '女频年代军婚.md', '女频末世天灾囤货.md',
]);
const MALE_GENRE_CARDS = new Set([
  '传统玄幻仙侠.md', '玄幻脑洞反套路.md', '都市高武异能.md', '都市脑洞系统.md',
  '都市日常神豪.md', '历史架空权谋.md', '动漫男频衍生.md', '官场商战职场.md', '男频年代乡村.md',
  '末世规则科幻.md', '西幻游戏同人.md',
]);

function detectChannelAffinity(profileText, rawGenre) {
  const readerMatch = /^[ \t]*[-*+]?[ \t]*\**(?:目标读者|频道)\**[ \t]*[：:](.*)$/m.exec(profileText || '');
  const readerText = readerMatch && !readerMatch[1].includes('{') ? readerMatch[1] : '';
  const readerFemale = /女频|女生/.test(readerText);
  const readerMale = /男频|男生/.test(readerText);
  if (readerFemale && !readerMale) return 'female';
  if (readerMale && !readerFemale) return 'male';
  const raw = rawGenre || '';
  const rawFemale = /女频|幻想言情|军婚|随军|天灾囤货|空间囤货/.test(raw);
  const rawMale = /男频|传统玄幻/.test(raw);
  if (rawFemale && !rawMale) return 'female';
  if (rawMale && !rawFemale) return 'male';
  return 'neutral';
}

const STRICT_BL_ALIAS_RE = /双男主|耽美|^(?:bl|abo)$/i;
const BG_CHANNEL_CUE_RE = /言情|女频|现言|古言|男频|男女/;
const CHANNEL_EXCLUSIVE_FALLBACK_BLOCK_RE = /年代|军婚|随军|天灾囤货|空间囤货|末世|玄幻|仙侠|宅斗|宫斗|豪门|总裁|虐恋|追妻/;

function genreChannelTier(cardBasename, affinity, isStrictBl = false) {
  if (BL_GENRE_CARDS.has(cardBasename)) {
    if (isStrictBl) return 0;
    if (affinity === 'female' || affinity === 'male') return 3;
    return 2;
  }
  if (affinity === 'female') {
    if (DUAL_CHANNEL_GENRE_CARDS.has(cardBasename) || FEMALE_GENRE_CARDS.has(cardBasename)) return 1;
    if (MALE_GENRE_CARDS.has(cardBasename)) return 3;
    return 2;
  }
  if (affinity === 'male') {
    if (DUAL_CHANNEL_GENRE_CARDS.has(cardBasename) || MALE_GENRE_CARDS.has(cardBasename)) return 1;
    if (FEMALE_GENRE_CARDS.has(cardBasename)) return 3;
    return 2;
  }
  return 2;
}

const UMBRELLA_ALIASES = new Set(['幻想言情', '现代言情', '古代言情']);

function matchGenreCards(project) {
  const profileText = stripHtmlComments(readText(path.join(project, '设定', '题材定位.md')));
  const raw = genreLine(project).toLowerCase();
  const affinity = detectChannelAffinity(profileText, raw);
  const hasBgCue = affinity === 'female' || affinity === 'male' || BG_CHANNEL_CUE_RE.test(raw);
  const fallback = isFile(FALLBACK_CARD) ? [[FALLBACK_CARD, 'low']] : [];
  if (!raw || !isDir(GENRE_CARD_DIR)) return fallback;
  const rank = { high: 0, medium: 1, low: 2 };
  const spans = [];
  const cards = fs
    .readdirSync(GENRE_CARD_DIR)
    .filter((n) => n.endsWith('.md'))
    .sort()
    .map((n) => path.join(GENRE_CARD_DIR, n));
  for (const card of cards) {
    const head = (readText(card) || '').split('---');
    const meta = head.length > 2 ? head[1] : '';
    if (/^fallback:\s*true\s*$/m.test(meta)) continue;
    const genre = /^genre:\s*(.+)$/m.exec(meta);
    const aliases = /^aliases:\s*\[(.*)\]/m.exec(meta);
    const confidence = /^confidence:\s*(\w+)/m.exec(meta);
    const level = confidence ? confidence[1] : 'low';
    const baseName = genre ? genre[1].trim() : path.basename(card, '.md');
    const aliasList = aliases
      ? aliases[1].split(',').map((a) => a.trim().replace(/^['"]|['"]$/g, ''))
      : [];
    const cardBase = path.basename(card);
    const isBlCard = BL_GENRE_CARDS.has(cardBase);
    const names = new Set([baseName, ...aliasList].filter(Boolean).map((n) => n.toLowerCase()));
    for (const name of names) {
      if (isBlCard && name === '纯爱' && hasBgCue) continue;
      const isStrictBl = isBlCard && (STRICT_BL_ALIAS_RE.test(name) || (name === '纯爱' && !hasBgCue));
      let pos = 0;
      while (pos <= raw.length) {
        const idx = raw.indexOf(name, pos);
        if (idx < 0) break;
        spans.push([idx, idx + name.length, card, level, UMBRELLA_ALIASES.has(name) ? 1 : 0, isStrictBl]);
        pos = idx + name.length || idx + 1;
      }
    }
  }
  const best = new Map();
  const compareKey = (a, b) => {
    for (let i = 0; i < 5; i += 1) {
      if (a[i] !== b[i]) return a[i] - b[i];
    }
    return a[5] < b[5] ? -1 : a[5] > b[5] ? 1 : 0;
  };
  for (const [start, end, card, level, isUmbrella, isStrictBl] of spans) {
    const dominated = spans.some(([s, e, c]) => c !== card && s <= start && end <= e && e - s > end - start);
    if (dominated) continue;
    const base = path.basename(card);
    const key = [genreChannelTier(base, affinity, isStrictBl), isUmbrella, start, -(end - start), rank[level] ?? 2, base];
    if (!best.has(card) || compareKey(key, best.get(card)[0]) < 0) {
      best.set(card, [key, level]);
    }
  }
  const hits = [...best.entries()]
    .map(([card, [key, level]]) => ({ key, card, level }))
    .sort((a, b) => compareKey(a.key, b.key));
  const rawExplicitOpposite =
    (affinity === 'female' && /男频|传统玄幻/.test(raw)) ||
    (affinity === 'male' && /女频|言情/.test(raw));
  let filtered = hits.length && affinity !== 'neutral' && !rawExplicitOpposite
    ? hits.filter((h) => h.key[0] < 3)
    : hits;
  if (!filtered.length && hits.length && !CHANNEL_EXCLUSIVE_FALLBACK_BLOCK_RE.test(raw)) {
    const fallbackCandidate = hits.find((h) => !BL_GENRE_CARDS.has(path.basename(h.card)));
    if (fallbackCandidate) filtered = [fallbackCandidate];
  }
  if (filtered.length > 1 && BL_GENRE_CARDS.has(path.basename(filtered[0].card))) {
    filtered = [filtered[0], ...filtered.slice(1).filter((h) => !FEMALE_GENRE_CARDS.has(path.basename(h.card)))];
  }
  return filtered.length ? filtered.slice(0, 2).map((h) => [h.card, h.level]) : fallback;
}

function benchmarkSearchRoots(project) {
  const { workspace } = findWorkspace(project);
  const roots = [
    path.join(project, '对标'),
    path.join(project, '拆文库'),
    path.join(path.dirname(project), '拆文库'),
  ];
  const workspaceLibrary = path.join(workspace, '拆文库');
  if (!roots.includes(workspaceLibrary)) {
    roots.push(workspaceLibrary);
  }
  return roots;
}

function benchmarkNameCandidates(raw) {
  const full = String(raw || '')
    .replace(/[（(][^）)]*[）)]/g, '')
    .trim()
    .replace(/^《+|》+$/g, '')
    .trim();
  const candidates = [];
  if (full) candidates.push(full);
  const splitFirst = full
    .split(/[、,，/｜|]/)[0]
    .trim()
    .replace(/^《+|》+$/g, '')
    .trim();
  if (splitFirst && splitFirst !== full) candidates.push(splitFirst);
  return candidates;
}

function rawPrimaryBenchmarkValues(project) {
  const text = stripHtmlComments(readText(path.join(project, '设定', '题材定位.md')));
  const explicit = /^[ \t>]*(?:[-*+][ \t]*)?\**主对标书\**[ \t]*[：:][ \t]*(.*)$/m.exec(text);
  if (explicit) {
    const v = explicit[1].trim();
    if (/^(无|不对标|都不用|没有)/.test(v)) {
      return [];
    }
    if (v && !v.startsWith('{') && !v.startsWith('｛')) {
      return [v];
    }
  }
  const values = [];
  const secMatch = /^##[ \t]*对标登记[^\n]*\n([\s\S]*?)(?=^##[ \t]|$(?![\r\n]))/m.exec(text);
  if (secMatch) {
    let strengthCol = -1;
    let sawHeader = false;
    for (const line of secMatch[1].split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('|')) continue;
      const cells = trimmed.replace(/^\|+|\|+$/g, '').split('|').map((c) => c.trim());
      if (!cells.length || !cells[0] || /^[-:\s]+$/.test(cells[0])) continue;
      if (!sawHeader && (cells[0] === '书名' || cells.some((c) => /强度/.test(c)))) {
        sawHeader = true;
        strengthCol = cells.findIndex((c) => /强度/.test(c));
        continue;
      }
      if (cells[0] === '书名' || cells[0].startsWith('{')) continue;
      if (strengthCol >= 0) {
        const strength = cells[strengthCol] || '';
        if (!/^主/.test(strength)) continue;
      } else if (cells.length >= 3) {
        const fallbackStrength = cells[2] || '';
        if (/^(?:辅|副|参考)/.test(fallbackStrength)) continue;
      }
      values.push(cells[0]);
    }
  }
  return values;
}

function findPrimaryBenchmarkName(project) {
  const mine = ownNames(project);
  const roots = benchmarkSearchRoots(project);
  let fallbackName = null;
  for (const raw of rawPrimaryBenchmarkValues(project)) {
    const candidates = benchmarkNameCandidates(raw).filter((name) => name && !mine.has(name));
    if (!candidates.length) continue;
    for (const name of candidates) {
      if (roots.some((root) => isDir(path.join(root, name)))) {
        return name;
      }
    }
    if (!fallbackName) fallbackName = candidates[0];
  }
  return fallbackName;
}

function findBenchmarkStyleFile(project) {
  const mine = ownNames(project);
  const roots = benchmarkSearchRoots(project);
  for (const raw of rawPrimaryBenchmarkValues(project)) {
    const candidates = benchmarkNameCandidates(raw).filter((name) => name && !mine.has(name));
    for (const name of candidates) {
      for (const root of roots) {
        const file = path.join(root, name, '文风.md');
        if (isFile(file)) return { file, name };
      }
    }
  }
  return null;
}

function scoreSliceForGenre(title, body, genreHint) {
  if (!genreHint) return 0;
  const hint = String(genreHint).toLowerCase();
  const titleLower = title.toLowerCase();
  const text = `${title}\n${body.slice(0, 120)}`.toLowerCase();
  let score = 0;
  // 正向子类词命中（2–4 字中文词/英文词；4 字纯中文复合词同步拆双字子词，避免「商战职场」「实业崛起」全 0 分）
  const tokens = [...new Set(hint.split(/[\s/／、,，+＋|｜:：（）()【】\[\]]+/).filter((t) => t.length >= 2))];
  const subTokens = new Set();
  for (const tok of tokens) {
    if (titleLower.includes(tok)) score += 6;
    else if (text.includes(tok)) score += 2;
    if (/^[\u4e00-\u9fff]{4}$/.test(tok)) {
      subTokens.add(tok.slice(0, 2));
      subTokens.add(tok.slice(2, 4));
    }
  }
  for (const sub of subTokens) {
    if (tokens.includes(sub)) continue;
    if (titleLower.includes(sub)) score += 3;
    else if (text.includes(sub)) score += 1;
  }
  // 高频防串台加减分（抗战谍战 vs 古代权谋；无CP vs 恋爱；退宗仙侠 vs 烤红薯迪化；星际向哨 vs 现代丧尸；实业商战 vs 官场）
  if (/无cp|无感情线|搞事业|纯破案/.test(hint)) {
    if (/无cp|破案|查案|直播|事业|算账|兽语|刑侦/.test(text)) score += 5;
    if (/恋爱|暧昧|甜宠|霸总|追妻|吻|心动|告白|婚/.test(title)) score -= 6;
  }
  if (/谍战|抗战|民国|特工|军统/.test(hint)) {
    if (/谍战|抗战|民国|电台|特工|暗杀|密电/.test(text)) score += 6;
    if (/古代|退婚|金銮|朝堂|王爷|皇帝|嫡女/.test(title)) score -= 6;
  }
  if (/退宗|宗门|修仙|剑修|长生/.test(hint)) {
    if (/退宗|宗门|修仙|剑|筑基|灵根|长老/.test(text)) score += 4;
    if (/烤红薯|种田|美食|摆摊/.test(text)) score -= 4;
  }
  if (/星际|向哨|哨兵|向导|精神海|荒星/.test(hint)) {
    if (/星际|向哨|哨兵|向导|精神海|精神体|抑制剂|荒星|星舰|污染/.test(text)) score += 6;
    if (/丧尸|房车|防盗门|小区|亲戚/.test(title)) score -= 2;
  }
  if (/商战|实业|职场|技改|工厂|国企|制造业|机床|重工|市场部|策划/.test(hint)) {
    if (/实业|技改|工厂|机床|母机|专利|商战|收购|产线|报价|车间|订单|股权|职场|市场部|策划|方案|博弈/.test(text)) score += 6;
    if (/官场|仕途|县长|政绩|纪委/.test(title) && !/官场|仕途/.test(hint)) score -= 2;
  }
  if (/神仙婆婆|大院互助|婆母/.test(hint)) {
    if (/婆婆|婆母|大院|小姑子|护短|政治处/.test(text)) score += 4;
  }
  return score;
}

function stripLeadingYamlFrontmatter(text) {
  const src = String(text || '').replace(/^\ufeff/, '').replace(/\r\n/g, '\n');
  if (!src.startsWith('---\n')) return src;
  const end = src.indexOf('\n---\n', 4);
  if (end === -1) return src;
  return src.slice(end + 5);
}

/**
 * 按 5 段标准题材包结构（## 1. 故事线设计 … ## 5. 案例片段）精准切片：
 * - 保留 YAML 后的 # 标题与 > 导语，以及编号在 wantedNums 中的 ## 节；
 * - 若遇非标准/旧自定义包（不含 `## 1. 故事线设计`），优雅回退全文（sliced: false）。
 */
function sliceGenrePack(rawText, wantedNums = [1, 2, 3], options = {}) {
  const src = String(rawText || '').replace(/^\ufeff/, '').replace(/\r\n/g, '\n');
  const includeHeader = options.includeHeader !== false;
  const body = stripLeadingYamlFrontmatter(src);
  const lines = body.split('\n');
  let fence = null;
  const h2Marks = [];
  for (let i = 0; i < lines.length; i += 1) {
    const ln = lines[i];
    const mFence = /^\s{0,3}(`{3,}|~{3,})/.exec(ln);
    if (mFence) {
      if (fence === null) fence = mFence[1];
      else if (mFence[1][0] === fence[0] && mFence[1].length >= fence.length) fence = null;
      continue;
    }
    if (fence) continue;
    const mH2 = /^##\s+(.*\S)\s*$/.exec(ln);
    if (mH2) {
      const title = mH2[1].trim();
      const mNum = /^(\d+)\.\s*(.*)$/.exec(title);
      h2Marks.push({ index: i, title, num: mNum ? Number(mNum[1]) : null });
    }
  }
  const isStandardV5 = h2Marks.some((h) => /^1\.\s*故事线设计$/.test(h.title));
  if (!isStandardV5) {
    return { text: src, sliced: false };
  }
  const wanted = new Set(wantedNums);
  const parts = [];
  if (includeHeader && h2Marks.length) {
    const preamble = lines.slice(0, h2Marks[0].index).join('\n').trim();
    if (preamble) parts.push(preamble);
  }
  for (let idx = 0; idx < h2Marks.length; idx += 1) {
    const mark = h2Marks[idx];
    if (!wanted.has(mark.num)) continue;
    const end = idx + 1 < h2Marks.length ? h2Marks[idx + 1].index : lines.length;
    const chunk = lines.slice(mark.index, end).join('\n').trim();
    if (chunk) parts.push(chunk);
  }
  if (!parts.length) {
    return { text: src, sliced: false };
  }
  return { text: parts.join('\n\n'), sliced: true };
}

function extractGenreProseTechniques(rawText) {
  const res = sliceGenrePack(rawText, [4], { includeHeader: false });
  if (!res.sliced) return null;
  const lines = res.text.split('\n');
  const body = /^##\s+4\.\s*正文技巧/.test(lines[0] || '') ? lines.slice(1).join('\n').trim() : res.text.trim();
  return body || null;
}

function collectProseSlices(text) {
  if (!text) return [];
  const lines = text.split('\n');
  const slices = [];
  let i = 0;
  while (i < lines.length) {
    const h = /^###\s+(.+)$/.exec(lines[i]);
    if (h && /(?:切片|片段|原文|锚点)/.test(h[1])) {
      const title = h[1].trim();
      let j = i + 1;
      const fencedLines = [];
      const plainLines = [];
      let inFence = false;
      let sawFence = false;
      while (j < lines.length && (inFence || !/^#{1,3}\s+/.test(lines[j]))) {
        const ln = lines[j];
        if (/^\s*```/.test(ln)) {
          inFence = !inFence;
          sawFence = true;
          j += 1;
          continue;
        }
        if (inFence) {
          fencedLines.push(ln);
        } else if (!sawFence) {
          plainLines.push(ln);
        }
        j += 1;
      }
      const rawLines = sawFence
        ? fencedLines
        : plainLines.filter((ln) => !/^\s*\*{0,2}(?:出处|示范点|来源|基调)\*{0,2}\s*[：:]/.test(ln));
      const cleaned = rawLines
        .map((ln) => ln.replace(/^>\s?/, ''))
        .join('\n')
        .trim();
      if (cleaned) {
        slices.push({ title, body: cleaned });
      }
      i = j;
      continue;
    }
    i += 1;
  }
  if (!slices.length) {
    // 兼容导入书/本书 设定/文风.md 使用 `## 原文语感锚点切片` + ```text 代码块
    let k = 0;
    while (k < lines.length) {
      const h2 = /^##\s+(.+)$/.exec(lines[k]);
      if (h2 && /(?:切片|片段|原文|锚点|示例)/.test(h2[1])) {
        const title = h2[1].trim();
        let j = k + 1;
        let inFence = false;
        let current = [];
        let blockIdx = 0;
        while (j < lines.length && (inFence || !/^##\s+/.test(lines[j]))) {
          const ln = lines[j];
          if (/^\s*```/.test(ln)) {
            if (inFence) {
              const cleaned = current.map((x) => x.replace(/^>\s?/, '')).join('\n').trim();
              if (cleaned) {
                blockIdx += 1;
                slices.push({ title: blockIdx === 1 ? title : `${title}（${blockIdx}）`, body: cleaned });
              }
              current = [];
            }
            inFence = !inFence;
          } else if (inFence) {
            current.push(ln);
          }
          j += 1;
        }
        k = j;
        continue;
      }
      k += 1;
    }
  }
  if (!slices.length) {
    // 兼容无二级/三级切片小节头、直接放 ```text 代码块的 设定/文风.md
    let inFence = false;
    let current = [];
    let blockIdx = 0;
    for (let j = 0; j < lines.length; j += 1) {
      const ln = lines[j];
      if (/^\s*```/.test(ln)) {
        if (inFence) {
          const cleaned = current.map((x) => x.replace(/^>\s?/, '')).join('\n').trim();
          if (cleaned) {
            blockIdx += 1;
            slices.push({ title: `原文语感切片${blockIdx}`, body: cleaned });
          }
          current = [];
        }
        inFence = !inFence;
      } else if (inFence) {
        current.push(ln);
      }
    }
  }
  return slices;
}

function extractProseSlices(text, chapter = 1, maxSlices = 2, genreHint = '') {
  const slices = collectProseSlices(text);
  if (!slices.length) return null;
  let picked;
  if (slices.length <= maxSlices) {
    picked = slices;
  } else if (genreHint) {
    const start = (Math.max(1, Number(chapter) || 1) - 1) % slices.length;
    const ranked = slices
      .map((s, idx) => ({
        s,
        score: scoreSliceForGenre(s.title, s.body, genreHint),
        rot: (idx - start + slices.length) % slices.length,
      }))
      .sort((a, b) => (b.score - a.score) || (a.rot - b.rot));
    picked = ranked.slice(0, maxSlices).map((x) => x.s);
  } else {
    const start = (Math.max(1, Number(chapter) || 1) - 1) % slices.length;
    picked = [];
    for (let k = 0; k < maxSlices; k += 1) {
      picked.push(slices[(start + k) % slices.length]);
    }
  }
  return picked.map((s) => `【${s.title}】\n${s.body}`).join('\n\n');
}

function authorDecided(project) {
  const text = stripHtmlComments(readText(path.join(project, '设定', '题材定位.md')));
  const match = /^##[ \t]*作者已定[^\n]*\n([\s\S]*?)(?=^#{1,2}[ \t]|$(?![\r\n]))/m.exec(text);
  if (!match) return { decided: null, cut: false };
  const lines = match[1]
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+$/, ''))
    .filter((line) => line.trim() && !/^\s*[-*+]?\s*\{.*\}\s*$/.test(line));
  const kept = [];
  let used = 0;
  let cut = false;
  for (const line of lines) {
    const size = Array.from(line.replace(/\s/g, '')).length;
    if (used + size > AUTHOR_DECIDED_CHARS) {
      cut = true;
      break;
    }
    kept.push(line);
    used += size;
  }
  return { decided: kept.join('\n'), cut };
}

function queryAuthorMemory(project) {
  const { workspace, recognised } = findWorkspace(project);
  const scriptPath = path.join(__dirname, 'author_memory_commit.js');
  if (!isFile(scriptPath)) {
    return { lines: null, missed: [], skipped: {}, error: 'author_memory_commit.js 缺失' };
  }
  if (!recognised && memoryStateKind(project) === 'book') {
    return {
      lines: null,
      missed: [],
      skipped: {},
      error:
        '认不出创作工作区（书目录及祖先都没有 .active-book、长篇/、短篇/、拆文库/ 或项目级作者记忆），' +
        '书目录里却是本书的记忆；先按 author-memory.md「存放与路由」定好 --workspace',
    };
  }
  let authorMemory;
  try {
    authorMemory = require(scriptPath);
  } catch (err) {
    return { lines: null, missed: [], skipped: {}, error: err.message || 'query 失败' };
  }
  const scoped = scopedMemoryValues(workspace);
  const book = bookGenres(project);
  const matchedGenres = [...scoped.genre].filter((v) => book.has(v.toLowerCase())).sort();
  const genres = matchedGenres.length ? matchedGenres : [null];
  const longLower = new Set([...LONG_WRITE_WORKFLOWS].map((w) => w.toLowerCase()));
  const workflows = [...scoped.workflow].filter((v) => longLower.has(v.toLowerCase())).sort();
  const skipped = {
    genre: [...scoped.genre].filter((v) => !genres.includes(v)).sort(),
    workflow: [...scoped.workflow].filter((v) => !workflows.includes(v)).sort(),
  };
  const lines = [];
  const omitted = [];
  const summaries = {};
  const importance = {};
  const seen = new Set();
  for (const genre of genres) {
    for (const workflow of workflows.length ? workflows : [null]) {
      let result;
      try {
        result = authorMemory.commandQuery(workspace, project, MEMORY_KINDS, null, genre, workflow);
      } catch (err) {
        return { lines: null, missed: [], skipped: {}, error: err.message || 'query 失败' };
      }
      if (!result || !result.ok) {
        return { lines: null, missed: [], skipped: {}, error: (result && result.error) || 'query 失败' };
      }
      const items = result.items || [];
      const rendered = result.lines || [];
      if (items.length !== rendered.length) {
        return {
          lines: null,
          missed: [],
          skipped: {},
          error: 'query 输出缺 lines（作者记忆脚本与组装脚本版本不一致）',
        };
      }
      for (let i = 0; i < items.length; i += 1) {
        const id = items[i].id;
        if (!seen.has(id)) {
          seen.add(id);
          lines.push(rendered[i]);
        }
      }
      for (const id of result.omitted_ids || []) {
        if (!omitted.includes(id)) omitted.push(id);
      }
      Object.assign(summaries, result.omitted_summaries || {});
      Object.assign(importance, result.omitted_importance || {});
    }
  }
  const omittedFiltered = omitted.filter((id) => !seen.has(id));
  const ranked = [...omittedFiltered].sort((a, b) => {
    const rankDiff = (IMPORTANCE_RANK[importance[b]] || 0) - (IMPORTANCE_RANK[importance[a]] || 0);
    if (rankDiff !== 0) return rankDiff;
    return omitted.indexOf(a) - omitted.indexOf(b);
  });
  const nonEmptySkipped = {};
  for (const [k, v] of Object.entries(skipped)) {
    if (v.length) nonEmptySkipped[k] = v;
  }
  return {
    lines,
    missed: ranked.map((id) => [id, summaries[id] || '']),
    skipped: nonEmptySkipped,
    error: null,
  };
}

function learnHeadingForm(project, chapter, title) {
  const body = path.join(project, '正文');
  if (!isDir(body)) {
    return {
      headingLine: null,
      how: chapter === 1 ? '首章尚无前文标题参照，按默认格式写' : '正文/ 目录不存在',
    };
  }
  const pattern = /^(#*)([ \t　]*)第(0*\d+)章([ \t　]*)(.*)$/;
  let best = null;
  for (const name of fs.readdirSync(body).filter((n) => n.endsWith('.md')).sort()) {
    const num = /^第(\d+)章/.exec(name);
    if (!num || Number(num[1]) === chapter) continue;
    const chNum = Number(num[1]);
    const content = (readText(path.join(body, name)) || '').trimStart();
    const firstLine = content ? content.split(/\r?\n/)[0].trim() : '';
    const hit = firstLine ? pattern.exec(firstLine) : null;
    if (hit && chNum < chapter && (best === null || chNum > best[0])) {
      best = [chNum, hit];
    }
  }
  if (best === null) {
    return { headingLine: null, how: '正文/ 下没有可解析标题行的既有章，写手按自身规则处理' };
  }
  const hit = best[1];
  const [, level, gap1, digits, gap2] = hit;
  const padded = digits.startsWith('0');
  const number = padded ? String(chapter).padStart(digits.length, '0') : String(chapter);
  const how = padded ? `${digits.length} 位补零` : '不补零';
  const levelPrefix = level ? `${level}${gap1}` : '';
  const levelLabel = level || '无 #';
  return {
    headingLine: `${levelPrefix}第${number}章${gap2 || ' '}${title}`,
    how: `照既有章形态（${levelLabel} ＋ 章号${how}）`,
  };
}

function build(project, chapter, report) {
  const errors = [];
  const outlineDir = path.join(project, '大纲');
  const outlineHit = findOutlineFile(outlineDir, chapter);
  if (outlineHit === null) {
    return { prompt: null, errors: [`必在块缺失：${outlineDir} 下没有第 ${chapter} 章细纲`] };
  }
  const outlineFile = outlineHit.file;
  const rawOutlineText = readText(outlineFile);
  if (!rawOutlineText || !rawOutlineText.trim()) {
    return { prompt: null, errors: [`必在块缺失：${outlineFile} 为空`] };
  }
  let outlineText = rawOutlineText;
  if (outlineHit.fromRangeFile) {
    const slice = extractChapterSlice(rawOutlineText, chapter);
    if (slice === null) {
      return { prompt: null, errors: [`必在块缺失：范围细纲 ${outlineFile} 中未找到第 ${chapter} 章小节`] };
    }
    outlineText = slice;
  }

  const title = extractTitle(outlineText, chapter);
  if (!title) {
    return { prompt: null, errors: [`细纲缺章名：${outlineFile}，需要 ### 第 N 章：章名`] };
  }
  if (title.includes('/') || title.includes('\\')) {
    return { prompt: null, errors: ['章名不能包含路径分隔符'] };
  }

  const parts = [
    `本次任务：写第 ${chapter} 章，全章一次写完。开始前先按「参考文件体系」逐行独立判定命中并读取，命中即必读，未命中不预加载；交付摘要里报出读了哪几个。`,
    `项目目录：${project}`,
    `章节：第 ${chapter} 章`,
    `最终输出路径：${path.join(project, '正文', `第${pad3(chapter)}章_${title}.md`)}`,
  ];
  const { headingLine, how } = learnHeadingForm(project, chapter, title);
  if (headingLine) {
    parts.push(`标题行（逐字照抄，勿按通用规则推导）：${headingLine}`);
    report.push(`标题行：${headingLine}　${how}`);
  } else {
    report.push(`标题行：未注入——${how}`);
  }
  parts.push(`细纲文件（动笔前完整读到 EOF）：${outlineFile}`);

  const stateFile = path.join(project, '追踪', '上下文.md');
  const stateText = readText(stateFile);
  if (!stateText) {
    errors.push(`必在块缺失：读不到 ${stateFile}`);
  } else {
    const sections = extractStateSections(stateText);
    const missing = STATE_SECTIONS.filter((s) => !Object.prototype.hasOwnProperty.call(sections, s));
    if (missing.length) {
      errors.push(`必在块缺失：${stateFile} 缺栏目 ${missing.join('、')}（先用 tracking_commit.js 修派生视图）`);
    } else {
      report.push('续写状态：七栏已校验，主会话按本章需要筛选到「本节速记」');
    }
  }

  const styleFile = path.join(project, '设定', '文风.md');
  const customStyle = hasCustomStyle(readText(styleFile));
  const registry = benchmarkRegistry(project);
  const mine = ownNames(project);
  let hasBooks = false;
  for (const base of benchmarkSearchRoots(project)) {
    if (!isDir(base)) continue;
    for (const entry of fs.readdirSync(base)) {
      if (isDir(path.join(base, entry)) && !mine.has(entry)) {
        hasBooks = true;
        break;
      }
    }
    if (hasBooks) break;
  }
  const matchedCards = matchGenreCards(project);
  const primaryGenreName =
    matchedCards.length && matchedCards[0][1] === 'high' && path.basename(matchedCards[0][0]) !== '通用长篇.md'
      ? path.basename(matchedCards[0][0], '.md')
      : null;
  const noBenchmark = registry === 'none' || (registry === 'missing' && !hasBooks);
  if (customStyle) {
    parts.push(`文风：读 ${styleFile} 全文（本书文风；表达与通用写法冲突时按它写，不覆盖细纲事实与信息边界）`);
    report.push('文风：本书有 设定/文风.md，已给路径');
  } else if (noBenchmark) {
    if (primaryGenreName) {
      parts.push(`文风：本书没有 设定/文风.md，也不对标——按作者这次的要求和本书流派包（${primaryGenreName}）语感写`);
    } else {
      parts.push('文风：本书没有 设定/文风.md，也不对标——按作者这次的要求和通用写法写');
    }
    report.push(`文风：无文风文件、无对标${registry === 'none' ? '（作者登记了不对标）' : ''}`);
  } else {
    parts.push(`——— 文风 ———\n${SLOT_MARK} 本书没有 设定/文风.md：按 benchmark-recall.md 取主对标文风，填路径与要点`);
    report.push('文风：无文风文件、有对标——主对标文风归主会话填');
  }

  if (chapter > 1) {
    const { prev: prevFile, tail } = previousChapterTail(project, chapter);
    if (prevFile === null || !tail) {
      errors.push(`必在块缺失：找不到或读不到第 ${chapter - 1} 章正文（如有意跳章写作且前章未落盘，提交时请配合 --allow-gap）`);
    } else {
      parts.push(`——— 上一章结尾（承接用，不重写；不给全章路径）———\n${tail}`);
      report.push(`上一章结尾：${path.basename(prevFile)} 末 ${Array.from(tail).length} 字（按整行回退）`);
    }
  }

  const unitField = extractAny(outlineText, UNIT_FIELD_NAMES);
  const volumeFiles = isDir(outlineDir)
    ? fs
        .readdirSync(outlineDir)
        .filter((n) => /^卷纲_.*\.md$/.test(n))
        .sort()
        .map((n) => path.join(outlineDir, n))
    : [];
  const volumes = volumeFiles.map((v) => readText(v) || '');
  const candidates = [unitField ? unitIdFrom(unitField) : null, ...volumes.map((t) => chapterUnitInVolume(t, chapter))];
  let unitId = null;
  let unitBlock = null;
  for (const candidate of candidates) {
    if (!candidate) continue;
    const block = volumes.map((t) => extractUnitBlock(t, candidate)).find(Boolean) || null;
    if (block) {
      unitId = candidate;
      unitBlock = block;
      break;
    }
  }

  const gaps = outlineGaps(outlineText);
  if (gaps.length) {
    report.push(
      `细纲两行：缺 ${gaps.join('、')}——不拒写：按卷纲本段剧情补出这两行写回细纲、汇报里说「补了这两行」，再重跑本脚本；卷纲里也没有本章内容就停下问作者`
    );
  } else {
    report.push('细纲两行：目标情绪、主角目标/关键选择都有');
  }

  const targetEmotion = extractAny(outlineText, OUTLINE_MUST['目标情绪']);
  const legacyCardPath = path.join(project, '设定', '题材正文提示卡.md');
  const cardText = readText(legacyCardPath);
  const hasLegacyCard = substantive(cardText);
  const engine = extractAny(unitBlock || '', ENGINE_FIELD_NAMES);
  const tempo = extractAny(unitBlock || '', TEMPO_FIELD_NAMES);
  const needs = {
    目标情绪: targetEmotion,
    这段让读者图什么: engine,
    这段怎么排: tempo,
  };
  const why = Object.entries(needs)
    .filter(([, value]) => !substantive(value))
    .map(([name]) => `${name}缺有效内容`);
  if (!matchedCards.length && !hasLegacyCard) {
    why.unshift('流派包缺失');
  }
  if (!customStyle && !noBenchmark) {
    why.push('custom_style=false');
  }

  let slotRecall;
  if (!why.length) {
    const lines = [
      'selected_emotion_module：降档（来源：细纲「目标情绪」＋本段剧情「这段让读者图什么」）',
      `  细纲目标情绪：${targetEmotion}`,
      ...(engine ? [`  这段让读者图什么：${engine}`] : []),
      'rhythm_reference：降档（来源：本段剧情「这段怎么排」）',
      ...(tempo ? [`  ${tempo}`] : []),
    ];
    slotRecall = `——— 情绪与节奏召回 ———\n${lines.join('\n')}`;
    report.push(
      `召回降档：成立，${noBenchmark && !customStyle ? '无对标，' : '文风、'}流派包、目标情绪和剧情段 ${unitId} 情绪/节拍均可用`
    );
  } else {
    slotRecall = `——— 情绪与节奏召回 ———\n${SLOT_MARK} 降档不成立（${why.join('、')}），按 benchmark-recall.md 走全量召回后填此槽`;
    report.push(`召回降档：不成立（${why.join('、')}）—— 全量召回归主会话`);
  }

  const { workspace: wsRoot } = findWorkspace(project);
  const isDeployedPack = (base) => {
    const deployedRel = `agent-references/genre-styles/${base}`;
    return [
      path.join(wsRoot, '.claude', deployedRel),
      path.join(wsRoot, '.agents', deployedRel),
      path.join(wsRoot, '.codex', deployedRel),
      path.join(wsRoot, '.opencode', deployedRel),
      path.join(wsRoot, deployedRel),
    ].some((p) => isFile(p));
  };
  let genreProseTech = null;
  let genreProseTechName = null;
  if (matchedCards.length) {
    const primaryCard = matchedCards[0][0];
    const primaryRaw = readText(primaryCard);
    const tech = primaryRaw ? extractGenreProseTechniques(primaryRaw) : null;
    if (tech) {
      genreProseTech = tech;
      genreProseTechName = path.basename(primaryCard, '.md');
    }
  }

  const genrePackLines = matchedCards.length
    ? matchedCards
        .map(
          ([card, level], i) => {
            const base = path.basename(card);
            const deployed = isDeployedPack(base);
            const sectionHint =
              i === 0
                ? (genreProseTech ? '（仅读 4. 正文技巧 与 5. 案例片段；已注入下方）' : '（写正文只看正文技巧与案例片段）')
                : '（主读主流派包，辅包仅跨题材冲突时按需对照 4–5 节）';
            const undeployedHint = deployed ? '' : '（未部署环境若读不到此相对路径，按主会话核对报告里的本机路径或直接依下方已注入正文技巧与案例片段执行）';
            return `${i === 0 ? '主' : '辅'}流派包：agent-references/genre-styles/${base}（置信度 ${level}）${sectionHint}${undeployedHint}`;
          }
        )
        .join('\n')
    : `${SLOT_MARK} 未匹配到流派包，请检查 agent-references/genre-styles/`;

  const sliceGenreHint = [genreLine(project), authorDecided(project).decided || ''].filter(Boolean).join(' ');
  let proseSliceText = null;
  let proseSliceSource = null;
  if (customStyle) {
    const ownSlices = extractProseSlices(readText(styleFile), chapter, 2, sliceGenreHint);
    if (ownSlices) {
      proseSliceText = ownSlices;
      proseSliceSource = `本书文风（${styleFile}）原文锚点`;
    }
  }
  if (!proseSliceText && !noBenchmark) {
    const bench = findBenchmarkStyleFile(project);
    if (bench) {
      const benchSlices = extractProseSlices(readText(bench.file), chapter, 2, sliceGenreHint);
      if (benchSlices) {
        proseSliceText = benchSlices;
        proseSliceSource = `主对标「${bench.name}」文风原文锚点（${bench.file}）`;
      }
    }
  }
  if (!proseSliceText && matchedCards.length) {
    const primaryCard = matchedCards[0][0];
    const primarySlices = collectProseSlices(readText(primaryCard));
    const secondaryCard = matchedCards.length > 1 ? matchedCards[1][0] : null;
    const secondarySlices = secondaryCard ? collectProseSlices(readText(secondaryCard)) : [];
    if (primarySlices.length && secondarySlices.length && sliceGenreHint) {
      const bestPrim = primarySlices
        .map((s) => ({ s, score: scoreSliceForGenre(s.title, s.body, sliceGenreHint) }))
        .sort((a, b) => b.score - a.score);
      const bestSec = secondarySlices
        .map((s) => ({ s, score: scoreSliceForGenre(s.title, s.body, sliceGenreHint) }))
        .sort((a, b) => b.score - a.score);
      if (bestSec[0].score > (bestPrim[1] ? bestPrim[1].score : -1)) {
        proseSliceText = [bestPrim[0].s, bestSec[0].s].map((s) => `【${s.title}】\n${s.body}`).join('\n\n');
        proseSliceSource = `主流派包「${path.basename(primaryCard, '.md')}」＋辅流派包「${path.basename(secondaryCard, '.md')}」子类匹配切片`;
      }
    }
    if (!proseSliceText) {
      const packSlices = extractProseSlices(readText(primaryCard), chapter, 2, sliceGenreHint);
      if (packSlices) {
        proseSliceText = packSlices;
        proseSliceSource = `流派包「${path.basename(primaryCard, '.md')}」内置原文切片`;
      }
    }
  }
  if (genreProseTech) {
    report.push(`流派正文技巧：已注入「${genreProseTechName}」4. 正文技巧（跳过 1–3 节大纲设计）`);
  }
  if (proseSliceText) {
    report.push(`语感锚点：已注入（来源：${proseSliceSource}，召回降档亦必传）`);
  } else {
    report.push('语感锚点：未抽到可用原文切片（请按 benchmark-recall.md 手动补 1-2 段 200-300 字原文锚点）');
  }

  const timelineAnchorRaw = recentTimelineAnchors(project);
  let timelineAnchor = null;
  if (timelineAnchorRaw && timelineAnchorRaw.error) {
    errors.push(`追踪状态异常：${timelineAnchorRaw.error}`);
    report.push(`追踪状态：错误（${timelineAnchorRaw.error}）`);
  } else if (timelineAnchorRaw) {
    timelineAnchor = timelineAnchorRaw;
    report.push(`近期时间锚点：已注入 ${timelineAnchor.count} 条（≤${TIMELINE_ANCHOR_MAX_CHARS} 字，防相对时间跨日漂移）`);
  }

  parts.push(
    `——— 本章意图（一句话）———\n${SLOT_MARK}`,
    `——— 作者本轮要求 ———\n${SLOT_MARK} 本轮字数范围、必发生、禁发生、停笔点与章尾要求；无写「无」。`,
    slotRecall,
    `——— 本章流派包 ———\n${genrePackLines}`,
    ...(genreProseTech
      ? [
          `——— 流派正文技巧（${genreProseTechName} · 4. 正文技巧）———\n${genreProseTech}`,
        ]
      : []),
    ...(proseSliceText
      ? [
          `——— 语感锚点切片（只学口语连接、句长断行与对话推进感，严禁照抄人名/台词/桥段）———\n${proseSliceText}`,
        ]
      : []),
    ...(timelineAnchor
      ? [
          `——— 近期时间锚点（相对时间如「昨晚/昨天」须对照此表与当前故事时间）———\n${timelineAnchor.text}`,
        ]
      : []),
    `——— 本节速记 ———\n${SLOT_MARK} 筛自 \`追踪/上下文.md\`：在场角色状态、下章承诺、连贯性风险、活跃伏笔（只给禁令，不下放作者侧真相）、本章相关卷级禁忌、久别角色是否补读快照。`,
    `——— 涉及角色 ———\n${SLOT_MARK} 列出本章要读的角色卡（本节速记已给全状态者不列）。`
  );

  if (matchedCards.length) {
    const named = matchedCards
      .map(([card, level], i) => `${i === 0 ? '主' : '辅'}题材 ${card}（置信度 ${level}）`)
      .join('；');
    const howCard = matchedCards[0][0] === FALLBACK_CARD ? '（流派无匹配，使用通用长篇兜底包）' : '';
    report.push(`流派包：已匹配 ${named}${howCard}`);
  } else {
    report.push('流派包：流派包目录缺失——重跑 /story-setup 或重装本 skill');
  }
  if (hasLegacyCard) {
    parts.push(
      `——— 兼容旧版题材正文提示卡（可选补充）———\n本书已有 ${legacyCardPath}，可按需作补充校准；与本章流派包冲突时以作者本轮要求和本书 设定/文风.md 为准。`
    );
  }
  parts.push(
    `——— 必读设定 ———\n${SLOT_MARK} 直接写出本章用到的设定原句（细纲显式引用 + 隐含术语/程序/数字锚）；无写「无」。`
  );

  const { decided, cut } = authorDecided(project);
  if (decided) {
    const note = cut
      ? `\n（超过 ${AUTHOR_DECIDED_CHARS} 字已截断，其余见 ${path.join(project, '设定', '题材定位.md')}「作者已定」，动笔前读完）`
      : '';
    parts.push(
      `——— 作者已定（本书的决定，高于作者记忆，与细纲冲突以细纲为准并在交付摘要里说明）———\n${decided}${note}`
    );
    report.push(`作者已定：已注入${cut ? '（超长截断，写手需回原文读完）' : ''}`);
  } else {
    report.push('作者已定：题材定位里没有或为空，未注入');
  }

  const { lines: memLines, missed, skipped, error: memoryError } = queryAuthorMemory(project);
  let memoryBlock;
  if (memoryError) {
    memoryBlock = `${SLOT_MARK} 组装脚本查询作者记忆失败（${memoryError}），按 author-memory.md 手动 query prose_style + story_design 后填入；无写「无」`;
    report.push(`作者记忆：脚本查询失败——${memoryError}，归主会话手动查询；手查有没带上的，章末照模板用原话说`);
  } else {
    memoryBlock = memLines.length ? memLines.join('\n') : '无';
    report.push(
      memLines.length || missed.length ? `作者记忆：已注入 ${memLines.length} 条` : '作者记忆：无相关 active 条目'
    );
  }
  if (missed.length) {
    const shown = missed
      .slice(0, MISSED_SHOWN)
      .map(([itemId, summary]) => `「${summary || itemId}」`)
      .join('');
    const more = missed.length > MISSED_SHOWN ? '等' : '';
    report.push(
      `作者记忆：装不下、这章没带上 ${missed.length} 条（${missed.map(([i]) => i).join('、')}），章末汇报原样说这句——` +
        `你记下的写作习惯这章有 ${missed.length} 条没带上：${shown}${more}；说「整理作者记忆」可以合并相近的、调低不常用的。`
    );
  }
  if (Object.keys(skipped).length && !memoryError) {
    const named = Object.entries(skipped)
      .map(([k, v]) => `${k === 'genre' ? '题材' : '流程'}：${v.join('、')}`)
      .join('；');
    memoryBlock += `\n${SLOT_MARK} 另有限定范围的作者记忆未代查（${named}）：适用则带 --genre／--workflow 补查后填入`;
    report.push(`作者记忆：限定范围未代查（${named}），归主会话判断是否适用`);
  }
  parts.push(
    `——— 作者偏好（作者记下的写作习惯，低优先级倾向，不逐条追求命中）———\n${memoryBlock}`,
    '——— 写作硬底线 ———\n' +
      '1. 叙述保人物内心盘算与口语因果连接，严禁抽干内心写成主谓宾摄像头分镜电报体。\n' +
      '2. 对白净白短打直接交锋，严禁每句台词捆绑端杯、摸袖口、看表盘等道具微动作。\n' +
      '3. 刀子物件原则：只留改局势或露破绽的实证物，删无功能材质/服饰/天气光影/声效贴纸；反派须按私心反咬设阻，禁走打卡过场。',
    '检查分工：写手负责编排、内容覆盖和格式自检；主会话质量阶段负责语义去味及最终文件扫描，写手不重复整轮去味。',
    '本次照你的铁律 1-8 与被调用协议执行（细纲边界、正文形状、新增物三级、交付三附件均以你的定义为准）。',
    `字数目标按细纲执行；整章一次写完，直接写到最终输出路径（临时文件只放 ${chapterWorkDir(project, chapter)}，不写 /tmp）；不拆逐点配额、不自测字数。`
  );

  if (errors.length) {
    return { prompt: null, errors };
  }
  return { prompt: `${parts.join('\n\n')}\n`, errors: [] };
}

const USAGE = 'Usage: node build_writer_prompt.js --project DIR --chapter N [--out [FILE]]\n';

function parseCliArgs(argv) {
  const args = { project: null, chapter: null, out: null, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--help' || token === '-h') {
      return { help: true };
    } else if (token === '--project') {
      if (i + 1 >= argv.length) return { error: '--project requires a value' };
      args.project = argv[++i];
    } else if (token.startsWith('--project=')) {
      args.project = token.slice('--project='.length);
    } else if (token === '--chapter') {
      if (i + 1 >= argv.length) return { error: '--chapter requires an integer' };
      const raw = argv[++i];
      if (!/^-?\d+$/.test(raw)) return { error: `invalid --chapter: ${raw}` };
      args.chapter = Number(raw);
    } else if (token.startsWith('--chapter=')) {
      const raw = token.slice('--chapter='.length);
      if (!/^-?\d+$/.test(raw)) return { error: `invalid --chapter: ${raw}` };
      args.chapter = Number(raw);
    } else if (token === '--out') {
      if (i + 1 < argv.length && !argv[i + 1].startsWith('-')) {
        args.out = argv[++i];
      } else {
        args.out = '';
      }
    } else if (token.startsWith('--out=')) {
      args.out = token.slice('--out='.length);
    } else {
      return { error: `unrecognized argument: ${token}` };
    }
  }
  if (!args.project) return { error: 'missing required --project' };
  if (args.chapter === null) return { error: 'missing required --chapter' };
  return args;
}

function main(argv = process.argv.slice(2)) {
  const args = parseCliArgs(argv);
  if (args.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (args.error) {
    process.stderr.write(`error: ${args.error}\n`);
    return 2;
  }
  if (args.chapter < 1) {
    process.stderr.write('error: --chapter 必须大于 0\n');
    return 2;
  }
  let project = realOrResolve(args.project);
  if (!isDir(project)) {
    process.stderr.write(`项目目录不存在：${project}\n`);
    return 2;
  }
  try {
    project = resolveBookDir(project);
  } catch (err) {
    if (err instanceof WordcountError) {
      process.stderr.write(`${err.message}\n`);
      return 2;
    }
    throw err;
  }

  const report = [];
  const { prompt, errors } = build(project, args.chapter, report);
  if (prompt === null) {
    process.stderr.write('组装中止，先修数据再重跑（这不是回落手拼的理由）：\n');
    for (const item of errors) {
      process.stderr.write(`  - ${item}\n`);
    }
    return 2;
  }

  const outlineHit = findOutlineFile(path.join(project, '大纲'), args.chapter);
  const rawOutline = outlineHit ? readText(outlineHit.file) || '' : '';
  const slicedOutline = outlineHit && outlineHit.fromRangeFile ? extractChapterSlice(rawOutline, args.chapter) || '' : rawOutline;
  const title = outlineHit ? extractTitle(slicedOutline, args.chapter) : null;
  if (title) {
    const proseDir = path.join(project, '正文');
    const ownChapterRe = new RegExp(`^第0*${args.chapter}章`);
    const clashes = isDir(proseDir)
      ? fs
          .readdirSync(proseDir)
          .filter((n) => n.endsWith(`_${title}.md`) && !ownChapterRe.test(n))
          .sort()
      : [];
    report.push(`标题预检：《${title}》${clashes.length ? `与既有章重名 → ${clashes.join('、')}` : '无重名'}`);
  }

  if (args.out !== null) {
    const out = args.out ? args.out : path.join(chapterWorkDir(project, args.chapter), 'writer_prompt.md');
    try {
      fs.mkdirSync(path.dirname(out), { recursive: true });
      fs.writeFileSync(out, prompt.replace(/\r\n/g, '\n'), 'utf8');
    } catch (err) {
      process.stderr.write(`留档写入失败：${out}（${err.message}）\n`);
      return 2;
    }
    report.push(`留档：${out}`);
  }

  process.stdout.write(prompt);
  process.stdout.write(`\n${'='.repeat(60)}\n`);
  process.stdout.write('以上是 prompt 正文（空槽以外一字不改，照抄）。以下不进 prompt：\n\n');
  for (const item of report) {
    process.stdout.write(`- ${item}\n`);
  }
  const slotCount = prompt.split(SLOT_MARK).length - 1;
  process.stdout.write(`- 待填槽位：${slotCount} 个（搜 ${SLOT_MARK}）\n`);
  process.stdout.write(`- 骨架长度：${Array.from(prompt).length} 字符\n`);
  return 0;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { build, genreLine, matchGenreCards, queryAuthorMemory, sliceGenrePack, extractGenreProseTechniques, main };
