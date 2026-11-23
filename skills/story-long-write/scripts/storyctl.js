#!/usr/bin/env node
'use strict';
/**
 * Measure, checkpoint, check, and commit long-form story chapters.
 *
 * `chapter check --plain` 把同一份检查结果说成作者能懂的话（单章检查一条命令出白话结论），
 * 并报本章碎度两个数：短段占比与叙述句长中位数，附真人参照；碎度只提示、不拦。
 */

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const core = require('./wordcount_core.js');
const tracking = require('./tracking_commit.js');

const {
  MEASUREMENT_SCHEMA,
  METRIC,
  WordcountError,
  require: requireCondition,
  normalizeAuthorRange,
  invalidWordcountResult,
  measureWordcount,
  evaluateWordcount,
  checkpointWordcount,
  targetFromOutline,
  effectiveAuthorRange,
  resolveBookDir,
  readChapterOutline,
  readProjectChapter,
  readUtf8Strict,
  buildProjectWordcountRecord,
} = core;

const CHAPTER_CHECK_SCHEMA = 'story-chapter-check/v1';
const CHAPTER_ERROR_SCHEMA = 'story-chapter-error/v1';
const WORK_ROOT = ['.story', 'work'];

const SHORT_PARAGRAPH_CHARS = 20;
const LONG_PARAGRAPH_CHARS = 100;
const HUMAN_SHORT_PARAGRAPH_RATIO = 0.38;
const HUMAN_NARRATIVE_SENTENCE_MEDIAN = 23;
const HUMAN_SHORT_PARAGRAPH_RANGE = [0.16, 0.62];
const HUMAN_NARRATIVE_SENTENCE_RANGE = [15, 35];

const HUMAN_BODY_ACTION_SENTENCE_RATIO = 0.12;
const HUMAN_BODY_ACTION_SENTENCE_RANGE = [0.03, 0.23];
const HUMAN_THOUGHT_CAUSAL_SENTENCE_RATIO = 0.15;
const HUMAN_THOUGHT_CAUSAL_SENTENCE_RANGE = [0.04, 0.28];

const _STRUCTURAL_DIVIDER_RE = /^[-*_—─━=]{3,}$/;
const _FRONTMATTER_KEY_RE = /^[A-Za-z_\u3400-\u9FFF][^:\n]{0,80}:/;
const _QUOTED = /“[^”]*”|「[^」]*」|『[^』]*』|"[^"]*"/g;
const _BODY_ACTION_SENTENCE_RE =
  /指尖|指腹|手指|指节|手背|掌心|拳头|手腕|袖口|衣角|喉结|眼眶|眼底|眸光|目光|视线|眼神|眉头|嘴角|唇角|肩膀|呼吸|伸手|抬手|探手|拿起|拿过|取出|取过|掏出|摸出|抓起|攥住|攥紧|握住|握紧|捏住|按住|压住|扣住|拢住|摩挲|推开|拉开|打开|关上|放下|递给|挑开|掀开|扯开|转身|回头|抬头|低头|弯腰|俯身|走到|走向|坐下|站起|盯着|扫过|看向|望向/;
const _THOUGHT_CAUSAL_SENTENCE_RE =
  /因为|所以|既然|省得|免得|要不然|否则|怪不得|难怪|偏偏|明明|反正|横竖|索性|干脆|好在|幸亏|毕竟|本来|原本|其实|说白了|说到底|知道|明白|清楚|觉得|以为|盘算|寻思|估摸|琢磨|怀疑|担心|害怕|后悔|心想|暗想|暗道|暗骂|腹诽|犯不着|舍不得|懒得|巴不得/;

// 与 hooks（JS core DESLOP_SKIP_MARKER）同一语法：注释内只认 ASCII 空格/Tab，冒号全角半角都认。
const DESLOP_SKIP = /<!--[ \t]*去味[ \t]*(：|:)[ \t]*跳过[ \t]*-->/;

const NODE_REQUIRED =
  '质量检查（AI 句式、退化、标点、细纲照搬）要用 Node.js 运行，本机找不到 node。' +
  '安装 Node.js 18 或更高版本并确认 `node --version` 可用后重跑本命令；装好之前本章不能提交。';

const CHECK_EXIT_CODES = {
  ready: 0,
  review_required: 0,
  needs_decision: 0,
  blocked: 1,
  invalid: 1,
  tool_unavailable: 3,
};
const REVIEW_GUIDANCE =
  '重点复核：建议修改，如确认剧情需要保留请在 commit 时传 `--ack <rule-id>:<简短理由>`';
const ERROR_EXIT_CODES = { TOOL_UNAVAILABLE: 3 };
const ACCEPT_FLOOR_RATIO = 0.5;
const PLAIN_SHOWN = 8;

class CliArgumentError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CliArgumentError';
  }
}

class ChapterRefused extends WordcountError {
  constructor(code, message, details = null) {
    super(message);
    this.name = 'ChapterRefused';
    this.code = code;
    this.details = details;
  }
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function charLen(str) {
  return Array.from(str).length;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function round3(value) {
  return Number(value.toFixed(3));
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

function _stripLeadingFrontmatter(text) {
  const normalized = text.replace(/\r\n?/g, '\n');
  const lines = normalized.split('\n');
  if (!lines.length || lines[0].trim() !== '---') return normalized;
  const limit = Math.min(lines.length, 201);
  for (let i = 1; i < limit; i += 1) {
    if (lines[i].trim() === '---') {
      const block = lines.slice(1, i);
      if (block.some((line) => _FRONTMATTER_KEY_RE.test(line.trim()))) {
        return lines.slice(i + 1).join('\n');
      }
      break;
    }
  }
  return normalized;
}

function _narrativeSentences(text) {
  const withoutFrontmatter = _stripLeadingFrontmatter(text.replace(/^\ufeff/, ''));
  const cleaned = stripHtmlComments(withoutFrontmatter);
  const lines = cleaned.split(/\r?\n/).map((line) => line.trim());
  const paragraphs = lines.filter((line) => line && !line.startsWith('#') && !_STRUCTURAL_DIVIDER_RE.test(line));
  const sentences = [];
  for (const line of paragraphs) {
    const stripped = line.replace(_QUOTED, '');
    for (const part of stripped.split(/[。！？!?…]+/)) {
      const compact = part.replace(/\s/g, '');
      if (compact) sentences.push(compact);
    }
  }
  return { paragraphs, sentences };
}

function fragmentation(text) {
  const { paragraphs, sentences } = _narrativeSentences(text);
  const paraLengths = paragraphs.map((line) => charLen(line.replace(/\s/g, '')));
  const short = paraLengths.filter((len) => len < SHORT_PARAGRAPH_CHARS).length;
  const over100 = paraLengths.filter((len) => len > LONG_PARAGRAPH_CHARS).length;
  const lengths = sentences.map((sentence) => charLen(sentence));
  return {
    paragraphs: paragraphs.length,
    short_paragraphs: short,
    short_paragraph_ratio: paragraphs.length ? round3(short / paragraphs.length) : null,
    paragraph_median_chars: median(paraLengths),
    paragraphs_over_100: over100,
    narrative_sentences: lengths.length,
    narrative_sentence_median: median(lengths),
    human_reference: {
      short_paragraph_ratio: HUMAN_SHORT_PARAGRAPH_RATIO,
      narrative_sentence_median: HUMAN_NARRATIVE_SENTENCE_MEDIAN,
      short_paragraph_range: [...HUMAN_SHORT_PARAGRAPH_RANGE],
      narrative_sentence_range: [...HUMAN_NARRATIVE_SENTENCE_RANGE],
    },
  };
}

function proseBalance(text) {
  const { sentences } = _narrativeSentences(text);
  const total = sentences.length;
  const actHits = sentences.filter((s) => _BODY_ACTION_SENTENCE_RE.test(s)).length;
  const thoughtHits = sentences.filter((s) => _THOUGHT_CAUSAL_SENTENCE_RE.test(s)).length;
  return {
    narrative_sentences: total,
    body_action_sentences: actHits,
    body_action_sentence_ratio: total ? round3(actHits / total) : null,
    thought_causal_sentences: thoughtHits,
    thought_causal_sentence_ratio: total ? round3(thoughtHits / total) : null,
    human_reference: {
      body_action_sentence_ratio: HUMAN_BODY_ACTION_SENTENCE_RATIO,
      body_action_sentence_range: [...HUMAN_BODY_ACTION_SENTENCE_RANGE],
      thought_causal_sentence_ratio: HUMAN_THOUGHT_CAUSAL_SENTENCE_RATIO,
      thought_causal_sentence_range: [...HUMAN_THOUGHT_CAUSAL_SENTENCE_RANGE],
    },
  };
}

function trackingCall(fn, ...args) {
  try {
    return fn(...args);
  } catch (err) {
    if (err instanceof tracking.TrackingError || (err && err.name === 'TrackingError')) {
      throw new WordcountError(err.message);
    }
    throw err;
  }
}

function jsonLine(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function textLines(lines) {
  process.stdout.write(`${lines.join('\n')}\n`);
}

function readJsonObject(filePath, label) {
  let value;
  try {
    const { text } = readUtf8Strict(filePath);
    value = JSON.parse(text);
  } catch (err) {
    throw new WordcountError(`unable to read ${label}: ${err.message}`);
  }
  requireCondition(value !== null && typeof value === 'object' && !Array.isArray(value), `${label} must be an object`);
  return value;
}

function chapterWorkDir(project, chapter) {
  const s = String(chapter);
  const padded = s.padStart(Math.max(3, s.length), '0');
  return path.join(path.resolve(String(project)), ...WORK_ROOT, `第${padded}章`);
}

function unlinkSymlink(targetPath) {
  try {
    fs.unlinkSync(targetPath);
  } catch (err) {
    if (err && (err.code === 'EPERM' || err.code === 'EISDIR')) {
      fs.rmdirSync(targetPath);
      return;
    }
    throw err;
  }
}

function removeChapterWorkDir(project, chapter) {
  const dirPath = chapterWorkDir(project, chapter);
  let lst;
  try {
    lst = fs.lstatSync(dirPath);
  } catch {
    return null;
  }
  if (lst.isSymbolicLink()) {
    unlinkSymlink(dirPath);
  } else if (lst.isDirectory()) {
    fs.rmSync(dirPath, { recursive: true, force: true });
  } else {
    return null;
  }
  for (const parent of [path.dirname(dirPath), path.dirname(path.dirname(dirPath))]) {
    try {
      fs.rmdirSync(parent);
    } catch {
      break;
    }
  }
  return [...WORK_ROOT, path.basename(dirPath)].join('/');
}

function jsonFindings(output) {
  let value;
  try {
    value = JSON.parse(output);
  } catch {
    return null;
  }
  const findings = value && typeof value === 'object' && !Array.isArray(value) ? value.findings : null;
  if (!Array.isArray(findings) || !findings.every((row) => row && typeof row === 'object' && !Array.isArray(row))) {
    return null;
  }
  return findings;
}

function semanticAdvisories(advisories) {
  return advisories.filter((row) => row.review !== 'mechanical').length;
}

function deslopSkipped(bodyPath) {
  const text = fs.readFileSync(bodyPath, 'utf8').replace(/^\ufeff/, '');
  const head = text.split(/\r?\n/).slice(0, 6).join('\n');
  return DESLOP_SKIP.test(head);
}

function runNodeScript(scriptPath, args) {
  return spawnSync(process.execPath, [scriptPath, ...args], {
    encoding: 'utf8',
    windowsHide: true,
  });
}

const _hooks = { runNodeScript, checkBlockingQuality: null };

function checkBlockingQuality(outline, body) {
  const root = __dirname;
  const exempt = deslopSkipped(body);
  const blocking = [];
  const reviewRequired = [];
  const advisories = [];
  const toolErrors = [];

  for (const [name, script] of [
    ['ai-pattern', 'check-ai-patterns.js'],
    ['degeneration', 'check-degeneration.js'],
  ]) {
    const scriptPath = path.join(root, script);
    if (!isFile(scriptPath)) {
      toolErrors.push({ type: 'TOOL_UNAVAILABLE', tool: script, message: `missing ${script}` });
      continue;
    }
    const completed = _hooks.runNodeScript(scriptPath, ['--check', '--json', '--fail-on=blocking', String(body)]);
    const findings = jsonFindings(completed.stdout || '');
    if (findings === null || (completed.status !== 0 && completed.status !== 1)) {
      toolErrors.push({
        type: 'TOOL_ERROR',
        tool: script,
        source: name,
        message: (completed.stderr || '').trim() || `${script} exited ${completed.status} without JSON findings`,
      });
      continue;
    }
    for (const finding of findings) {
      const row = { source: name, ...finding };
      if (name === 'degeneration' && row.review === undefined) {
        row.review = 'mechanical';
      }
      if (
        exempt &&
        name === 'ai-pattern' &&
        (finding.severity === 'blocking' || finding.severity === 'review_required')
      ) {
        advisories.push({ ...row, severity: 'advisory', exempted: '去味:跳过' });
        continue;
      }
      if (finding.severity === 'blocking') {
        blocking.push(row);
      } else if (finding.severity === 'review_required') {
        reviewRequired.push({ ...row, rule_id: finding.type });
      } else {
        advisories.push(row);
      }
    }
  }

  const punctuation = path.join(root, 'normalize-punctuation.js');
  if (!isFile(punctuation)) {
    toolErrors.push({
      type: 'TOOL_UNAVAILABLE',
      tool: 'normalize-punctuation.js',
      message: 'missing normalize-punctuation.js',
    });
  } else {
    const completed = _hooks.runNodeScript(punctuation, ['--check', String(body)]);
    if (completed.status === 1) {
      const rawOut = (completed.stdout || completed.stderr || '').trim();
      const lines = rawOut
        ? rawOut
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter(Boolean)
        : [];
      // 标准 `——` 在 normalize-punctuation.js 中已默认保留不报错；
      // 其余输出（未闭合 HTML 注释、非标省略号、畸形破折号 —/———/——……、双连字符、分隔线等）均属确定性标点错误，一律硬阻断。
      blocking.push({
        type: 'PUNCTUATION_NOT_NORMALIZED',
        message: lines.length ? lines.join('\n') : rawOut,
      });
    } else if (completed.status !== 0) {
      toolErrors.push({
        type: 'TOOL_ERROR',
        tool: 'normalize-punctuation.js',
        message: (completed.stderr || '').trim() || `exited ${completed.status}`,
      });
    }
  }

  const outlineCopy = path.join(root, 'check-outline-copy.js');
  if (!isFile(outlineCopy)) {
    toolErrors.push({
      type: 'TOOL_UNAVAILABLE',
      tool: 'check-outline-copy.js',
      message: 'missing check-outline-copy.js',
    });
  } else {
    const completed = _hooks.runNodeScript(outlineCopy, ['--outline', String(outline), String(body)]);
    if (completed.status === 1) {
      advisories.push({
        source: 'outline-copy',
        type: 'OUTLINE_COPY_REVIEW',
        review: 'semantic',
        message: (completed.stdout || '').trim(),
      });
    } else if (completed.status !== 0) {
      toolErrors.push({
        type: 'TOOL_ERROR',
        tool: 'check-outline-copy.js',
        message: (completed.stderr || '').trim() || `exited ${completed.status}`,
      });
    }
  }

  return {
    status: toolErrors.length
      ? 'unavailable'
      : blocking.length
        ? 'fail'
        : reviewRequired.length
          ? 'review_required'
          : 'pass',
    blocking_findings: blocking,
    review_required_items: reviewRequired,
    advisories,
    semantic_advisories: semanticAdvisories(advisories),
    tool_errors: toolErrors,
  };
}
_hooks.checkBlockingQuality = checkBlockingQuality;

function checkStatus(length, quality) {
  if (quality.status === 'unavailable') return 'tool_unavailable';
  if (quality.status === 'fail') return 'blocked';
  if (length.status === 'invalid') return 'invalid';
  if (quality.status === 'review_required') return 'review_required';
  return length.status === 'internal_pass' || length.status === 'borderline' ? 'ready' : 'needs_decision';
}

function chapterCheck(project, chapter, authorRange = null) {
  const { outlinePath, bodyPath, target, authorRange: effectiveRange } = readProjectChapter(
    project,
    chapter,
    authorRange
  );
  let body;
  try {
    ({ text: body } = readUtf8Strict(bodyPath));
  } catch (err) {
    throw new WordcountError(`unable to read body: ${err.message}`);
  }
  const length = evaluateWordcount(body, target, { chapter, authorRange: effectiveRange });
  const quality = _hooks.checkBlockingQuality(outlinePath, bodyPath);
  const reviewItems = quality.review_required_items || [];
  const status = checkStatus(length, quality);
  let actions;
  if (status === 'ready') {
    actions = ['commit'];
  } else if (status === 'review_required') {
    if (length.status === 'over') {
      actions = ['compress-once', 'accept-current-length', 'revise-outline-or-target', 'discard'];
    } else if (length.status === 'under') {
      actions = ['accept-current-length', 'revise-outline-or-target', 'discard'];
    } else {
      actions = ['revise', 'commit-with-ack'];
    }
  } else if (status !== 'needs_decision') {
    actions = [];
  } else if (length.status === 'over') {
    actions = ['compress-once', 'accept-current-length', 'revise-outline-or-target', 'discard'];
  } else {
    actions = ['accept-current-length', 'revise-outline-or-target', 'discard'];
  }
  const state = trackingCall(tracking.loadState, project);
  let compression = null;
  if (length.status === 'over' && (quality.status === 'pass' || quality.status === 'review_required')) {
    const actual = length.actual;
    compression = {
      mode: 'single_pass_remove_only',
      remove_to_internal_band: {
        min: actual - length.internal_band.max,
        max: actual - length.internal_band.min,
      },
      remove_to_user_band: {
        min: actual - length.user_band.max,
        max: actual - length.user_band.min,
      },
    };
  }
  const payload = {
    schema: CHAPTER_CHECK_SCHEMA,
    status,
    chapter,
    length,
    quality,
    review_required_items: reviewItems,
    fragmentation: fragmentation(body),
    prose_balance: proseBalance(body),
    compression,
    state_revision: state.state_revision,
    tracking_committed: state.last_committed_chapter >= chapter,
    next_chapter_started: state.last_committed_chapter > chapter,
    available_actions: actions,
  };
  if (reviewItems.length) {
    payload.review_guidance = REVIEW_GUIDANCE;
  }
  return payload;
}

function fixPunctuation(project, chapter, authorRange = null) {
  const { bodyPath } = readProjectChapter(project, chapter, authorRange);
  const script = path.join(__dirname, 'normalize-punctuation.js');
  if (!isFile(script)) return false;
  const before = fs.readFileSync(bodyPath);
  _hooks.runNodeScript(script, [String(bodyPath)]);
  const after = fs.readFileSync(bodyPath);
  return !before.equals(after);
}

function requireAcceptableLength(checked, { force }) {
  if (force) return;
  const length = checked.length;
  if (length.status === 'under' && length.actual < length.target * ACCEPT_FLOOR_RATIO) {
    throw new ChapterRefused(
      'BELOW_ACCEPT_FLOOR',
      `本章 ${length.actual} 字，不到字数目标 ${length.target} 的一半，不能直接按当前长度接受；` +
        '先补细纲或改字数目标，作者明确要这个长度时加 --force'
    );
  }
}

function parseAckArg(raw) {
  const str = String(raw || '');
  const idx = str.search(/[:：]/);
  if (idx <= 0) {
    throw new CliArgumentError(`argument --ack: expected <rule-id>:<reason>, got '${str}'`);
  }
  const ruleId = str.slice(0, idx).trim();
  const reason = str.slice(idx + 1).trim();
  if (!ruleId || !reason) {
    throw new CliArgumentError(`argument --ack: both rule-id and reason must be non-empty, got '${str}'`);
  }
  return { ruleId, reason };
}

function chapterCommit(
  project,
  chapter,
  inputPath,
  { acceptCurrentLength, authorRange = null, force = false, acks = [], ackAll = null, allowGap = false }
) {
  const checked = chapterCheck(project, chapter, authorRange);
  if (checked.status === 'tool_unavailable') {
    const msg = checked.quality.tool_errors.map((item) => item.message).join('；') || NODE_REQUIRED;
    throw new ChapterRefused('TOOL_UNAVAILABLE', msg);
  }
  if (checked.quality.status === 'fail') {
    throw new ChapterRefused('QUALITY_BLOCKED', 'blocking quality findings must be fixed before commit');
  }
  const ackMap = new Map();
  for (const entry of acks || []) {
    ackMap.set(entry.ruleId, entry.reason);
  }
  const reviewItems = checked.quality.review_required_items || [];
  const requiredRules = [...new Set(reviewItems.map((item) => item.rule_id || item.type))];
  const unacknowledged = ackAll ? [] : requiredRules.filter((rule) => !ackMap.has(rule));
  if (unacknowledged.length > 0) {
    const cliHints = unacknowledged.map((rule) => `--ack ${rule}:<简短理由>`).join(' ');
    throw new ChapterRefused(
      'REVIEW_ACK_REQUIRED',
      `有 ${unacknowledged.length} 类风格项待复核确认（${unacknowledged.join('、')}）：` +
        `建议修改；如确认剧情需要保留，请重新 commit 并传 ${cliHints}（或 --ack-all <简短理由>）`,
      {
        unacknowledged_rules: unacknowledged,
        review_required_items: reviewItems.filter((item) => unacknowledged.includes(item.rule_id || item.type)),
      }
    );
  }
  const acknowledgedReviews = [];
  for (const rule of requiredRules) {
    const matched = reviewItems.filter((item) => (item.rule_id || item.type) === rule);
    acknowledgedReviews.push({
      rule_id: rule,
      reason: ackMap.get(rule) || ackAll,
      count: matched.length,
      lines: matched.map((item) => item.line).filter((line) => line !== undefined && line !== null),
    });
  }

  const lengthStatus = checked.length.status;
  const inUserBand = lengthStatus === 'internal_pass' || lengthStatus === 'borderline';
  const lengthAckReason = ackMap.get('length') || null;
  let resolution;
  if (acceptCurrentLength) {
    requireCondition(
      lengthStatus === 'under' || lengthStatus === 'over',
      'accept-current-length requires a valid out-of-band chapter'
    );
    requireAcceptableLength(checked, { force });
    resolution = 'accepted_current_length';
    if (lengthAckReason) {
      acknowledgedReviews.push({
        rule_id: 'length',
        reason: lengthAckReason,
        actual: checked.length.actual,
        target: checked.length.target,
        status: lengthStatus,
      });
    }
  } else if (lengthAckReason) {
    if (!inUserBand) {
      requireCondition(lengthStatus === 'under' || lengthStatus === 'over', 'chapter length is invalid');
      requireAcceptableLength(checked, { force });
      resolution = 'accepted_current_length';
    } else {
      resolution = 'within_user_band';
    }
    acknowledgedReviews.push({
      rule_id: 'length',
      reason: lengthAckReason,
      actual: checked.length.actual,
      target: checked.length.target,
      status: lengthStatus,
    });
  } else {
    if (!inUserBand) {
      throw new ChapterRefused(
        'LENGTH_OUT_OF_BAND',
        'chapter length is outside the user band; use --ack length:<reason>, accept-current-length, or revise it'
      );
    }
    resolution = 'within_user_band';
  }
  const document = readJsonObject(inputPath, 'tracking transaction');
  requireCondition(document.chapter === chapter, 'tracking transaction chapter does not match command');
  requireCondition(
    !Object.prototype.hasOwnProperty.call(document, 'wordcount'),
    'tracking transaction must not provide wordcount'
  );
  document.wordcount = buildProjectWordcountRecord(project, chapter, { resolution, authorRange });
  const state = trackingCall(tracking.applyTransaction, project, document, { allowGap });
  checked.state_revision = state.state_revision;
  checked.tracking_committed = state.last_committed_chapter >= chapter;
  checked.next_chapter_started = state.last_committed_chapter > chapter;
  checked.wordcount = state.wordcount_records[String(chapter)] || null;
  checked.mode = document.mode;
  checked.acknowledged_reviews = acknowledgedReviews;
  try {
    checked.work_dir_removed = removeChapterWorkDir(project, chapter);
  } catch (err) {
    checked.work_dir_removed = null;
    checked.work_dir_cleanup_error = err.message;
  }
  return checked;
}

function findingLine(row) {
  const where = row.line ? `第 ${row.line} 行` : '全章';
  const excerpt = String(row.excerpt || '').trim();
  const message = String(row.message || row.type || '').trim();
  const excerptPart = excerpt ? `「${Array.from(excerpt).slice(0, 40).join('')}」` : '';
  return `- ${where}${excerptPart}：${message}`;
}

function reviewRequiredLine(row) {
  const where = row.line ? `第 ${row.line} 行` : '全章';
  const ruleId = row.rule_id || row.type || 'unknown';
  const excerpt = String(row.excerpt || '').trim();
  const message = String(row.message || '').trim();
  const excerptPart = excerpt ? `「${Array.from(excerpt).slice(0, 40).join('')}」` : '';
  return `- [${ruleId}] ${where}${excerptPart}：${message}`;
}

function plainReport(result) {
  const chapter = result.chapter;
  const status = result.status;
  const length = result.length;
  const quality = result.quality;
  const reviewItems = quality.review_required_items || result.review_required_items || [];
  const lines = [];
  let verdict = {
    ready: `第 ${chapter} 章检查完了，可以提交。`,
    review_required: `第 ${chapter} 章没有硬伤，但有 ${reviewItems.length} 处风格项需要重点复核。`,
    needs_decision: `第 ${chapter} 章没有必须改的，但字数不在范围里，要请作者定。`,
    blocked: `第 ${chapter} 章有必须改的地方，改完再查一次。`,
    invalid: `第 ${chapter} 章正文是空的或读不出字数，先把正文写进去再查。`,
    tool_unavailable: `第 ${chapter} 章这次没查完：检查工具没跑起来，不能提交。`,
  }[status];
  if (result.punctuation_fixed) {
    verdict += '标点已顺手整理过。';
  }
  lines.push(verdict);
  const actual = length.actual;
  const band = length.user_band || null;
  if (actual !== null && actual !== undefined && band) {
    const span = `${band.min} 到 ${band.max} 字`;
    if (length.status === 'under') {
      lines.push(
        `字数：约 ${actual} 字，比范围（${span}）少了约 ${band.min - actual} 字。欠的不补写，请作者选：收下现在的长度、改细纲或目标后重写、或不要这章。`
      );
    } else if (length.status === 'over') {
      lines.push(`字数：约 ${actual} 字，比范围（${span}）多了约 ${actual - band.max} 字。`);
      const compression = result.compression;
      if (compression) {
        const remove = compression.remove_to_internal_band;
        lines.push(
          `先做一次只删不加的压缩：删掉 ${Math.max(remove.min, 0)} 到 ${remove.max} 字（删重复解释、装饰排比、没用的小动作，情节点和钩子都留着），删完再查；还超就请作者选。`
        );
      }
    } else {
      lines.push(`字数：约 ${actual} 字，在范围里（${span}）。`);
    }
  }
  for (const error of quality.tool_errors || []) {
    lines.push(`- 没跑起来：${error.message || error.tool}`);
  }
  const blocking = quality.blocking_findings || [];
  if (blocking.length) {
    lines.push(`必须改的 ${blocking.length} 处：`);
    for (const row of blocking) lines.push(findingLine(row));
  }
  if (reviewItems.length) {
    lines.push(`${REVIEW_GUIDANCE}（共 ${reviewItems.length} 处）：`);
    for (const row of reviewItems) lines.push(reviewRequiredLine(row));
  }
  const advisories = quality.advisories || [];
  if (advisories.length) {
    const outlineCopyCount = advisories.filter((row) => row.source === 'outline-copy').length;
    const aiSemanticCount = advisories.filter((row) => row.source !== 'outline-copy' && row.review === 'semantic').length;
    const detailParts = [];
    if (aiSemanticCount) detailParts.push(`像 AI 腔、要读原文判断的 ${aiSemanticCount} 处`);
    if (outlineCopyCount) detailParts.push(`与细纲重合待复核的 ${outlineCopyCount} 处`);
    const detailText = detailParts.length ? `（其中${detailParts.join('，')}；确属问题才改）` : '（确属问题才改）';
    lines.push(`建议看看的 ${advisories.length} 处${detailText}：`);
    for (const row of advisories.slice(0, PLAIN_SHOWN)) lines.push(findingLine(row));
    if (advisories.length > PLAIN_SHOWN) {
      lines.push(`- 另有 ${advisories.length - PLAIN_SHOWN} 处，见 chapter check 的完整结果`);
    }
  }
  if (!blocking.length && !reviewItems.length && !advisories.length && (status === 'ready' || status === 'needs_decision')) {
    lines.push('没发现 AI 腔或写坏的地方。');
  }
  const frag = result.fragmentation || {};
  const ratio = frag.short_paragraph_ratio;
  const med = frag.narrative_sentence_median;
  const paraMed = frag.paragraph_median_chars;
  const over100 = frag.paragraphs_over_100;
  if (
    (ratio !== null && ratio !== undefined) ||
    (med !== null && med !== undefined) ||
    (paraMed !== null && paraMed !== undefined)
  ) {
    const parts = [];
    const [low, high] = HUMAN_SHORT_PARAGRAPH_RANGE;
    if (ratio !== null && ratio !== undefined) {
      parts.push(
        `不到 ${SHORT_PARAGRAPH_CHARS} 字的短段占 ${Math.round(ratio * 100)}%` +
          `（真人平均约 ${Math.round(HUMAN_SHORT_PARAGRAPH_RATIO * 100)}%，多数章在 ${Math.round(low * 100)}%–${Math.round(high * 100)}%）`
      );
    }
    if (paraMed !== null && paraMed !== undefined) {
      parts.push(
        `段长中位数 ${paraMed} 字` +
          (typeof over100 === 'number' ? `，超过 ${LONG_PARAGRAPH_CHARS} 字的长段 ${over100} 段` : '')
      );
    }
    const [shortest, longest] = HUMAN_NARRATIVE_SENTENCE_RANGE;
    if (med !== null && med !== undefined) {
      parts.push(
        `叙述句长中位数 ${med} 字（真人平均约 ${HUMAN_NARRATIVE_SENTENCE_MEDIAN} 字，多数章在 ${shortest}–${longest} 字）`
      );
    }
    const choppy =
      (ratio !== null && ratio !== undefined && ratio > high) ||
      (med !== null && med !== undefined && med < shortest);
    const tail = choppy ? '。偏碎：同一个动作或同一层意思的几句可以接成一句、并成一段。' : '。';
    lines.push(`这章碎不碎（只作参考，不拦）：${parts.join('，')}${tail}`);
  }
  const balance = result.prose_balance || {};
  const actRatio = balance.body_action_sentence_ratio;
  const thoughtRatio = balance.thought_causal_sentence_ratio;
  const totalSentences = balance.narrative_sentences || 0;
  if (actRatio !== null && actRatio !== undefined && thoughtRatio !== null && thoughtRatio !== undefined) {
    const [actLow, actHigh] = HUMAN_BODY_ACTION_SENTENCE_RANGE;
    const [thLow, thHigh] = HUMAN_THOUGHT_CAUSAL_SENTENCE_RANGE;
    const bParts = [
      `带肢体或手眼动作的叙述句占 ${Math.round(actRatio * 100)}%` +
        `（真人平均约 ${Math.round(HUMAN_BODY_ACTION_SENTENCE_RATIO * 100)}%，多数章在 ${Math.round(actLow * 100)}%–${Math.round(actHigh * 100)}%）`,
      `带盘算或因果的叙述句占 ${Math.round(thoughtRatio * 100)}%` +
        `（真人平均约 ${Math.round(HUMAN_THOUGHT_CAUSAL_SENTENCE_RATIO * 100)}%，多数章在 ${Math.round(thLow * 100)}%–${Math.round(thHigh * 100)}%）`,
    ];
    const actionHeavy =
      totalSentences >= 8 && (actRatio > 0.29 || (actRatio > actHigh && thoughtRatio < 0.08));
    const bTail = actionHeavy
      ? '。动作偏密、心里账偏少：删掉不改局面的手眼或道具小动作，把角色为什么这么选、图什么直接写出来。'
      : '。';
    lines.push(`动作和心里话（只作参考，不拦）：${bParts.join('，')}${bTail}`);
  }
  return lines;
}

const PLAIN_ERRORS = [
  [/chapter (\d+) must have exactly one outline file/, (m) => `第 ${m[1]} 章没有细纲，或者细纲不止一份`],
  [/chapter (\d+) must have exactly one body file/, (m) => `第 ${m[1]} 章没有正文，或者正文不止一份`],
  [/chapter directory is missing: .*[/\\](\S+)$/, (m) => `书里没有「${m[1]}」这个目录`],
  [/字数目标/, () => '细纲的字数目标没写或写法不对（写成「字数目标：2500 字」）'],
  [/字数范围/, () => '细纲的字数范围写法不对（写成「字数范围：2000-2600」）'],
];

function plainError(message) {
  for (const [pattern, formatter] of PLAIN_ERRORS) {
    const match = pattern.exec(message);
    if (match) {
      return [`这次没查成：${formatter(match)}。`];
    }
  }
  return [`这次没查成：${message}`];
}

function parseIntArg(raw, flag) {
  if (!/^-?\d+$/.test(raw)) {
    throw new CliArgumentError(`argument ${flag}: invalid int value: '${raw}'`);
  }
  return Number(raw);
}

function parseCliArgs(argv) {
  if (argv.length < 2) {
    throw new CliArgumentError('the following arguments are required: command, subcommand');
  }
  const command = argv[0];
  const sub = argv[1];
  const args = {
    command,
    subcommand: sub,
    file: null,
    chapter: null,
    caseId: null,
    target: null,
    minChars: null,
    maxChars: null,
    project: null,
    input: null,
    fixPunctuation: false,
    plain: false,
    force: false,
    acks: [],
    ackAll: null,
    allowGap: false,
  };
  if (command === 'wordcount') {
    if (!['measure', 'check', 'checkpoint'].includes(sub)) {
      throw new CliArgumentError(`invalid wordcount command: ${sub}`);
    }
    for (let i = 2; i < argv.length; i += 1) {
      const token = argv[i];
      const readVal = (flag) => {
        if (token.includes('=')) return token.slice(token.indexOf('=') + 1);
        if (i + 1 >= argv.length) throw new CliArgumentError(`argument ${flag}: expected one argument`);
        return argv[++i];
      };
      if (token === '--file' || token.startsWith('--file=')) {
        args.file = readVal('--file');
      } else if (token === '--chapter' || token.startsWith('--chapter=')) {
        args.chapter = readVal('--chapter');
      } else if (token === '--case-id' || token.startsWith('--case-id=')) {
        args.caseId = readVal('--case-id');
      } else if (sub !== 'measure' && (token === '--target' || token.startsWith('--target='))) {
        args.target = readVal('--target');
      } else if (sub !== 'measure' && (token === '--min-chars' || token.startsWith('--min-chars='))) {
        args.minChars = parseIntArg(readVal('--min-chars'), '--min-chars');
      } else if (sub !== 'measure' && (token === '--max-chars' || token.startsWith('--max-chars='))) {
        args.maxChars = parseIntArg(readVal('--max-chars'), '--max-chars');
      } else if (sub === 'checkpoint' && (token === '--project' || token.startsWith('--project='))) {
        args.project = readVal('--project');
      } else {
        throw new CliArgumentError(`unrecognized arguments: ${token}`);
      }
    }
    if (args.file === null) {
      throw new CliArgumentError('the following arguments are required: --file');
    }
    if (sub === 'check' && args.target === null) {
      throw new CliArgumentError('the following arguments are required: --target');
    }
    return args;
  }
  if (command === 'chapter') {
    if (!['check', 'commit', 'accept-current-length'].includes(sub)) {
      throw new CliArgumentError(`invalid chapter command: ${sub}`);
    }
    for (let i = 2; i < argv.length; i += 1) {
      const token = argv[i];
      const readVal = (flag) => {
        if (token.includes('=')) return token.slice(token.indexOf('=') + 1);
        if (i + 1 >= argv.length) throw new CliArgumentError(`argument ${flag}: expected one argument`);
        return argv[++i];
      };
      if (token === '--project' || token.startsWith('--project=')) {
        args.project = readVal('--project');
      } else if (token === '--chapter' || token.startsWith('--chapter=')) {
        args.chapter = parseIntArg(readVal('--chapter'), '--chapter');
      } else if (token === '--min-chars' || token.startsWith('--min-chars=')) {
        args.minChars = parseIntArg(readVal('--min-chars'), '--min-chars');
      } else if (token === '--max-chars' || token.startsWith('--max-chars=')) {
        args.maxChars = parseIntArg(readVal('--max-chars'), '--max-chars');
      } else if (sub !== 'check' && (token === '--input' || token.startsWith('--input='))) {
        args.input = readVal('--input');
      } else if (sub === 'check' && token === '--fix-punctuation') {
        args.fixPunctuation = true;
      } else if (sub === 'check' && token === '--plain') {
        args.plain = true;
      } else if (sub !== 'check' && token === '--force') {
        args.force = true;
      } else if (sub !== 'check' && token === '--allow-gap') {
        args.allowGap = true;
      } else if (sub !== 'check' && (token === '--ack' || token.startsWith('--ack='))) {
        args.acks.push(parseAckArg(readVal('--ack')));
      } else if (sub !== 'check' && (token === '--ack-all' || token.startsWith('--ack-all='))) {
        const reason = readVal('--ack-all').trim();
        if (!reason) throw new CliArgumentError('argument --ack-all: reason must be non-empty');
        args.ackAll = reason;
      } else {
        throw new CliArgumentError(`unrecognized arguments: ${token}`);
      }
    }
    if (args.project === null) throw new CliArgumentError('the following arguments are required: --project');
    if (args.chapter === null) throw new CliArgumentError('the following arguments are required: --chapter');
    if (sub !== 'check' && args.input === null) {
      throw new CliArgumentError('the following arguments are required: --input');
    }
    return args;
  }
  throw new CliArgumentError(`invalid choice: '${command}' (choose from 'wordcount', 'chapter')`);
}

function cliAuthorRange(args) {
  const { minChars: low, maxChars: high } = args;
  if (low === null && high === null) return null;
  if (low === null || high === null) {
    throw new CliArgumentError('--min-chars and --max-chars must be given together');
  }
  try {
    return normalizeAuthorRange({ min: low, max: high });
  } catch (err) {
    if (err instanceof WordcountError) throw new CliArgumentError(err.message);
    throw err;
  }
}

function wordcountCommand(args, initialAuthorRange) {
  let authorRange = initialAuthorRange;
  let body;
  try {
    ({ text: body } = readUtf8Strict(args.file));
  } catch {
    const result =
      args.subcommand === 'measure'
        ? {
            schema: MEASUREMENT_SCHEMA,
            metric: METRIC,
            chapter: args.chapter,
            case_id: args.caseId,
            actual: null,
            status: 'invalid',
            invalid_reason: 'INVALID_FILE',
          }
        : invalidWordcountResult('INVALID_FILE', { chapter: args.chapter, caseId: args.caseId });
    jsonLine(result);
    return 2;
  }
  let result;
  if (args.subcommand === 'measure') {
    result = measureWordcount(body, { chapter: args.chapter, caseId: args.caseId });
  } else if (args.subcommand === 'checkpoint') {
    let target = args.target;
    if (args.project !== null) {
      try {
        if (!/^\d+$/.test(String(args.chapter || ''))) {
          throw new WordcountError('invalid chapter');
        }
        const chapter = Number(args.chapter);
        const { outline } = readChapterOutline(resolveBookDir(args.project), chapter);
        if (target === null) {
          target = targetFromOutline(outline);
        }
        authorRange = effectiveAuthorRange(outline, authorRange);
      } catch {
        jsonLine(invalidWordcountResult('INVALID_OUTLINE', { chapter: args.chapter, caseId: args.caseId }));
        return 2;
      }
    }
    if (target === null) {
      jsonLine(
        invalidWordcountResult('INVALID_ARGUMENT', {
          chapter: args.chapter,
          caseId: '--target or --project is required',
        })
      );
      return 2;
    }
    try {
      result = checkpointWordcount(body, target, {
        chapter: args.chapter,
        caseId: args.caseId,
        authorRange,
      });
    } catch (err) {
      if (err instanceof WordcountError) {
        result = invalidWordcountResult('INVALID_TARGET', { chapter: args.chapter, caseId: args.caseId });
      } else {
        throw err;
      }
    }
  } else {
    result = evaluateWordcount(body, args.target, {
      chapter: args.chapter,
      caseId: args.caseId,
      authorRange,
    });
  }
  jsonLine(result);
  return result.status === 'invalid' ? 2 : 0;
}

const USAGE = [
  'Usage:',
  '  node storyctl.js wordcount measure --file FILE [--chapter N] [--case-id ID]',
  '  node storyctl.js wordcount check --file FILE --target N [--chapter N] [--min-chars N --max-chars N] [--case-id ID]',
  '  node storyctl.js wordcount checkpoint --file FILE (--target N | --project DIR --chapter N) [--min-chars N --max-chars N]',
  '  node storyctl.js chapter check --project DIR --chapter N [--min-chars N --max-chars N] [--fix-punctuation] [--plain]',
  '  node storyctl.js chapter (commit|accept-current-length) --project DIR --chapter N --input FILE [--min-chars N --max-chars N] [--force] [--allow-gap] [--ack RULE:REASON ...] [--ack-all REASON]',
].join('\n');

function main(argv = process.argv.slice(2)) {
  if (argv.includes('--help') || argv.includes('-h')) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }
  let args;
  let authorRange;
  try {
    args = parseCliArgs(argv);
    authorRange = cliAuthorRange(args);
  } catch (err) {
    if (err instanceof CliArgumentError) {
      const payload =
        argv[0] === 'chapter'
          ? { schema: CHAPTER_ERROR_SCHEMA, status: 'error', error_code: 'INVALID_ARGUMENT', message: err.message }
          : invalidWordcountResult('INVALID_ARGUMENT', { caseId: err.message });
      jsonLine(payload);
      return 2;
    }
    throw err;
  }
  if (args.command === 'wordcount') {
    return wordcountCommand(args, authorRange);
  }
  let result;
  try {
    const project = resolveBookDir(args.project);
    if (args.subcommand === 'check') {
      const fixed = args.fixPunctuation ? fixPunctuation(project, args.chapter, authorRange) : null;
      result = chapterCheck(project, args.chapter, authorRange);
      if (fixed !== null) {
        result.punctuation_fixed = fixed;
      }
    } else {
      result = chapterCommit(project, args.chapter, args.input, {
        acceptCurrentLength: args.subcommand === 'accept-current-length',
        authorRange,
        force: args.force,
        acks: args.acks,
        ackAll: args.ackAll,
        allowGap: args.allowGap,
      });
    }
  } catch (err) {
    if (err instanceof WordcountError || (err && typeof err.code === 'string')) {
      const code = err instanceof ChapterRefused ? err.code : 'CHECK_FAILED';
      if (args.plain) {
        textLines(plainError(err.message));
      } else {
        jsonLine({
          schema: CHAPTER_ERROR_SCHEMA,
          status: 'error',
          error_code: code,
          message: err.message,
          ...(err instanceof ChapterRefused && err.details ? err.details : {}),
        });
      }
      return ERROR_EXIT_CODES[code] ?? 2;
    }
    throw err;
  }
  if (args.plain) {
    textLines(plainReport(result));
  } else {
    jsonLine(result);
  }
  if (args.subcommand !== 'check') return 0;
  return CHECK_EXIT_CODES[result.status];
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  DESLOP_SKIP,
  CHAPTER_CHECK_SCHEMA,
  CHAPTER_ERROR_SCHEMA,
  CHECK_EXIT_CODES,
  _hooks,
  fragmentation,
  proseBalance,
  deslopSkipped,
  checkBlockingQuality,
  checkStatus,
  chapterCheck,
  chapterCommit,
  plainReport,
  main,
};
