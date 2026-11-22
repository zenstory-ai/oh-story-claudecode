#!/usr/bin/env node
'use strict';
/**
 * build_outline_brief.js — 拼出导入长篇「逐批反推细纲」的任务包。
 *
 * 用法:
 *   node build_outline_brief.js --project <书目录> --chapters A-B [--analysis <拆文库/导入书名>]
 * Exit: 0 = 已写出；2 = 参数错误、正文或卷纲缺失、长度测不出。
 */

const fs = require('node:fs');
const path = require('node:path');
const { isUnitCard, parse: parseVolume, unitChapterRange } = require('./outline_view.js');
const { METRIC, WordcountError, findChapterFile, measureWordcount, readUtf8Strict } = require('./wordcount_core.js');

const RULES = path.resolve(__dirname, '..', 'references', 'outline-reverse-rules.md');
const WORK_DIR = ['.story', 'work', '排纲'];
const MIN_BATCH = 10;
const MAX_BATCH = 20;
const LOAD_LIMIT = 25000;

const SUMMARY_FIELDS = [
  ['关键事件', []],
  ['因果', []],
  ['局面结果', []],
  ['涉及', ['涉及人物', '出场人物']],
  ['信息变化', []],
  ['状态变化', []],
  ['章尾钩子', ['卡点与伏笔']],
];
const SUMMARY_FIELD_MAP = Object.fromEntries(SUMMARY_FIELDS);
const FIELD_NAMES = SUMMARY_FIELDS.flatMap(([name, aliases]) => [name, ...aliases]).join('|');
const LABEL_RE = new RegExp(`^\\s*(?:[-*+]\\s*)?(?:\\*\\*([^*]+?)\\*\\*|(${FIELD_NAMES}))\\s*[：:（(]`);
const POINT_HEADER_RE = /^P(\d+)\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$/;
const POINT_TAG_RE = /^主题标签\s*[：:]?\s*[^|｜]*?\s*[|｜]\s*基调\s*[：:]?\s*(.*?)\s*$/;

class OutlineBriefError extends Error {}

function fail(message) {
  throw new OutlineBriefError(message);
}

function weight(text) {
  return text.replace(/\s/g, '').length;
}

function rstrip(str) {
  return str.replace(/\s+$/, '');
}

function pad3(n) {
  return String(n).padStart(3, '0');
}

function parseRange(value) {
  const match = /^\s*(\d+)\s*(?:-\s*(\d+))?\s*$/.exec(value || '');
  if (!match) {
    fail('ERROR: --chapters 写成 A-B，如 1-20');
  }
  const first = Number(match[1]);
  const last = Number(match[2] || match[1]);
  if (first < 1 || last < first) {
    fail('ERROR: --chapters 范围无效');
  }
  return [first, last];
}

function lastBodyChapter(project) {
  const proseDir = path.join(project, '正文');
  let entries;
  try {
    entries = fs.readdirSync(proseDir);
  } catch {
    return 0;
  }
  let max = 0;
  for (const name of entries) {
    if (!/^第.*章.*\.md$/.test(name) || name.includes('_原稿_')) continue;
    const m = /^第0*(\d+)章/.exec(name);
    if (m) {
      const n = Number(m[1]);
      if (n > max) max = n;
    }
  }
  return max;
}

function hasExistingOutlines(project, first, last) {
  const outlineDir = path.join(project, '大纲');
  try {
    if (!fs.statSync(outlineDir).isDirectory()) return false;
  } catch {
    return false;
  }
  for (let chapter = first; chapter <= last; chapter += 1) {
    try {
      findChapterFile(outlineDir, chapter, { outline: true });
    } catch (err) {
      if (err instanceof WordcountError) return false;
      throw err;
    }
  }
  return true;
}

function checkBatchSize(project, first, last, final) {
  const size = last - first + 1;
  if (size > MAX_BATCH) {
    fail(`ERROR: 一批细纲最多 ${MAX_BATCH} 章，拆成两批`);
  }
  if (size < MIN_BATCH && last < final && !hasExistingOutlines(project, first, last)) {
    fail(
      `ERROR: 一批细纲至少 ${MIN_BATCH} 章（全书最后一批或已有细纲返修除外），把范围扩到第${first}-${Math.min(final, first + MIN_BATCH - 1)}章`
    );
  }
}

function shownPath(filePath, base) {
  const rel = path.relative(path.resolve(base), path.resolve(filePath));
  if (rel !== '..' && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel)) {
    return rel.split(path.sep).join('/');
  }
  return String(filePath);
}

function measure(project, chapter) {
  let body;
  let text;
  try {
    body = findChapterFile(path.join(project, '正文'), chapter, { outline: false });
    ({ text } = readUtf8Strict(body));
  } catch (err) {
    fail(`ERROR: 第${chapter}章正文读不到（${err.message}），先完成正文迁移`);
  }
  const result = measureWordcount(text, { chapter });
  if (result.status !== 'measured') {
    fail(`ERROR: 第${chapter}章长度测不出（${result.invalid_reason}）`);
  }
  return { body, text, actual: result.actual };
}

function labelBlocks(text) {
  const blocks = {};
  let current = null;
  for (const line of text.replace(/\r\n/g, '\n').split('\n')) {
    const stripped = line.trim();
    if (POINT_HEADER_RE.test(stripped) || stripped.startsWith('#')) {
      current = null;
      continue;
    }
    const match = LABEL_RE.exec(line);
    if (match) {
      current = (match[1] || match[2]).trim();
      const idx = line.search(/[：:]/);
      const rest = idx >= 0 ? line.slice(idx + 1) : '';
      if (!blocks[current]) blocks[current] = [];
      blocks[current].push(rest);
      continue;
    }
    if (current !== null) {
      blocks[current].push(line);
    }
  }
  const out = {};
  for (const [name, lines] of Object.entries(blocks)) {
    out[name] = lines.join('\n').trim();
  }
  return out;
}

function flatten(value) {
  const rows = value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  if (rows.length && rows.every((row) => row.startsWith('|'))) {
    const names = rows
      .slice(2)
      .map((row) => row.replace(/^\|+|\|+$/g, '').split('|')[0].trim())
      .filter(Boolean);
    return names.join('、');
  }
  return rows.map((row) => row.replace(/^(?:\d+[.、]|[-*+])\s*/, '')).join(' ');
}

function summaryPoints(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const points = [];
  for (let index = 0; index < lines.length; index += 1) {
    const header = POINT_HEADER_RE.exec(lines[index].trim());
    if (!header) continue;
    let kind = header[3].split(/[|｜]/)[0].trim();
    if (kind.startsWith('类型')) {
      kind = kind.slice(2).replace(/^[ ：:]+/, '');
    }
    let tone = '—';
    for (const follow of lines.slice(index + 1, index + 12)) {
      if (POINT_HEADER_RE.test(follow.trim())) break;
      const tag = POINT_TAG_RE.exec(follow.trim());
      if (tag) {
        tone = tag[1] || '—';
        break;
      }
    }
    points.push(`P${header[1]} ${header[2].trim()}｜${kind}｜${tone}`);
  }
  return points;
}

function summaryLines(text) {
  const blocks = labelBlocks(text);
  const out = [];
  for (const [name, aliases] of SUMMARY_FIELDS) {
    let raw = '';
    for (const key of [name, ...aliases]) {
      if (blocks[key]) {
        raw = blocks[key];
        break;
      }
    }
    out.push(`- ${name}：${flatten(raw) || '（摘要未写）'}`);
  }
  const points = summaryPoints(text);
  out.push(
    '- 情节点（标题｜类型｜基调）：' + (points.length ? points.join('；') : '（摘要里没有可读的情节点）')
  );
  return out;
}

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function previousHook(analysis, chapter) {
  const summary = path.join(analysis, '章节', `第${chapter - 1}章_摘要.md`);
  if (chapter <= 1 || !isFile(summary)) return null;
  const text = fs.readFileSync(summary, 'utf8').replace(/^\ufeff/, '');
  const blocks = labelBlocks(text);
  const keys = ['章尾钩子', ...SUMMARY_FIELD_MAP['章尾钩子']];
  for (const key of keys) {
    if (blocks[key]) return flatten(blocks[key]);
  }
  return null;
}

function chapterBlock(project, analysis, chapter, first) {
  const { body, text: bodyText, actual } = measure(project, chapter);
  const projectParent = path.dirname(project);
  const head = [
    `### 第${chapter}章`,
    '',
    `- 正文：\`${shownPath(body, projectParent)}\`；字数目标 ${actual}（${METRIC}）`,
  ];
  const hook = chapter === first ? previousHook(analysis, chapter) : null;
  if (hook) {
    head.push(`- 上一章（第${chapter - 1}章）章尾钩子：${hook}`);
  }
  const summary = path.join(analysis, '章节', `第${chapter}章_摘要.md`);
  if (isFile(summary)) {
    const summaryText = fs.readFileSync(summary, 'utf8').replace(/^\ufeff/, '');
    const lines = [
      `- 摘要要点（抽自 \`${shownPath(summary, projectParent)}\`）：`,
      ...summaryLines(summaryText).map((line) => `  ${line}`),
    ];
    return { block: [...head, ...lines].join('\n'), actual, extra: 0, absent: false };
  }
  const note = '- 摘要：未找到，读该章正文反推，证据不足处写 [待补充]';
  return { block: [...head, note].join('\n'), actual, extra: weight(bodyText), absent: true };
}

function unitCards(project, first, last) {
  const dir = path.join(project, '大纲');
  let volumes = [];
  try {
    volumes = fs
      .readdirSync(dir)
      .filter((name) => /^卷纲_第.*卷\.md$/.test(name))
      .sort()
      .map((name) => path.join(dir, name));
  } catch {
    volumes = [];
  }
  if (!volumes.length) {
    fail('ERROR: 大纲/ 下没有卷纲，先在结构迁移时刻写定卷纲');
  }
  const out = [];
  const projectName = path.basename(project);
  for (const volumePath of volumes) {
    const volumeName = path.basename(volumePath);
    const content = fs.readFileSync(volumePath, 'utf8').replace(/^\ufeff/, '');
    const { lines, sections } = parseVolume(content);
    for (const sec of sections) {
      if (!isUnitCard(sec) || sec.status === '已退役') continue;
      const span = unitChapterRange([sec], sec.unit);
      if (span === null || span[0] > last || span[1] < first) continue;
      const nextSame = sections.find((other) => other.start > sec.start && other.level <= sec.level);
      const end = nextSame ? nextSame.start : lines.length;
      out.push(`来源：\`${projectName}/大纲/${volumeName}\``, '', ...lines.slice(sec.start, end), '');
    }
  }
  if (!out.length) {
    fail(
      `ERROR: 卷纲里找不到章节范围覆盖第${first}-${last}章的剧情段卡（卡标题末尾写单元编号注释` +
        '如「### 第一段剧情：退婚风波 <!-- L1-01 -->」，卡里写「- 章节范围：第A-B章」），先补卷纲，' +
        '再用 outline_view.js --check --strict 核对'
    );
  }
  return out;
}

function render(project, first, last, blocks) {
  const projectName = path.basename(project);
  const projectParent = path.dirname(project);
  const head =
    `# 任务包：反推第${first}-${last}章细纲（导入）\n\n` +
    `只交付 \`${projectName}/大纲/细纲_第${pad3(first)}章.md\` 到 \`细纲_第${pad3(last)}章.md\`，每章一个文件（已有的同名文件按本包重写覆盖）；` +
    '不改正文、卷纲和 `设定/`，不建 `追踪/`。证据用下方每章的摘要要点，不整读拆文库摘要；某个字段要点里没有、' +
    `又必须写实际内容时，只回看该章正文的相关段落。作者已定的事在 \`${projectName}/.story/work/导入记录.md\`；` +
    '不要另读本包以外的写作技法文件。交付后只回：写了哪些文件、每章一句核心事件、' +
    '证据不足标了 [待补充] 的要点（没有写「无」）。\n\n' +
    '包里提到的检查由主会话在你交付后跑，你不执行命令；需要的测量结果已放进包里。';
  const rulesText = fs.readFileSync(RULES, 'utf8').replace(/^\ufeff/, '').trim();
  const parts = [
    head,
    `\n## 本批章节\n\n路径相对项目根（\`${projectParent}\`）。\n\n${blocks.join('\n\n')}`,
    `\n## 卷纲剧情单元（覆盖本批）\n\n${rstrip(unitCards(project, first, last).join('\n'))}`,
    `\n---\n\n<!-- 资料：outline-reverse-rules.md -->\n\n${rulesText}`,
  ];
  return `${parts.join('\n')}\n`;
}

function build(project, analysis, first, last) {
  if (!isFile(RULES)) {
    fail(`ERROR: 缺少 reference：${RULES}`);
  }
  const fixed = weight(render(project, first, last, []));
  const blocks = [];
  const lengths = {};
  const missing = [];
  let load = fixed;
  let extraReading = 0;
  for (let chapter = first; chapter <= last; chapter += 1) {
    const { block, actual, extra, absent } = chapterBlock(project, analysis, chapter, first);
    const cost = weight(block) + extra;
    if (blocks.length && load + cost > LOAD_LIMIT) {
      break;
    }
    blocks.push(block);
    lengths[chapter] = actual;
    load += cost;
    extraReading += extra;
    if (absent) missing.push(chapter);
  }
  const end = first + blocks.length - 1;
  const text = render(project, first, end, blocks);
  return {
    text,
    end,
    lengths,
    missing,
    chars: weight(text) + extraReading,
  };
}

function parseCliArgs(argv) {
  const args = { project: null, chapters: null, analysis: null };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--project') {
      if (i + 1 >= argv.length) return { error: '--project requires a value' };
      args.project = argv[++i];
    } else if (token.startsWith('--project=')) {
      args.project = token.slice('--project='.length);
    } else if (token === '--chapters') {
      if (i + 1 >= argv.length) return { error: '--chapters requires a value' };
      args.chapters = argv[++i];
    } else if (token.startsWith('--chapters=')) {
      args.chapters = token.slice('--chapters='.length);
    } else if (token === '--analysis') {
      if (i + 1 >= argv.length) return { error: '--analysis requires a value' };
      args.analysis = argv[++i];
    } else if (token.startsWith('--analysis=')) {
      args.analysis = token.slice('--analysis='.length);
    } else {
      return { error: `unrecognized argument: ${token}` };
    }
  }
  if (!args.project) return { error: 'missing required --project' };
  if (!args.chapters) return { error: 'missing required --chapters' };
  return args;
}

function main(argv = process.argv.slice(2)) {
  const args = parseCliArgs(argv);
  if (args.error) {
    process.stderr.write(`ERROR: ${args.error}\n`);
    return 2;
  }
  let project;
  let first;
  let final;
  let result;
  try {
    try {
      project = fs.realpathSync(path.resolve(args.project));
    } catch {
      project = path.resolve(args.project);
    }
    let isDir = false;
    try {
      isDir = fs.statSync(project).isDirectory();
    } catch {
      isDir = false;
    }
    if (!isDir) {
      fail(`ERROR: 书目录不存在：${args.project}`);
    }
    const [f, last] = parseRange(args.chapters);
    first = f;
    final = lastBodyChapter(project);
    if (last > final) {
      fail(`ERROR: 正文只迁到第${final}章，范围超出`);
    }
    checkBatchSize(project, first, last, final);
    const analysis = path.resolve(args.analysis || path.join(path.dirname(project), '拆文库', path.basename(project)));
    result = build(project, analysis, first, last);
  } catch (err) {
    if (err instanceof OutlineBriefError) {
      process.stderr.write(`${err.message}\n`);
      return 2;
    }
    throw err;
  }
  const end = result.end;
  const outDir = path.join(project, ...WORK_DIR);
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, `导入细纲_第${pad3(first)}-${pad3(end)}章.md`);
  fs.writeFileSync(out, result.text, 'utf8');
  const lengthsObj = {};
  for (const [k, v] of Object.entries(result.lengths)) {
    lengthsObj[String(k)] = v;
  }
  process.stdout.write(
    `${JSON.stringify({
      brief: out,
      chapters: `${first}-${end}`,
      next: end < final ? end + 1 : null,
      chars: result.chars,
      limit: LOAD_LIMIT,
      metric: METRIC,
      lengths: lengthsObj,
      missing_summaries: result.missing,
    })}\n`
  );
  return 0;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { build, parseRange, labelBlocks, flatten, summaryPoints, summaryLines, main };
