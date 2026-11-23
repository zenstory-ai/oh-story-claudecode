#!/usr/bin/env node
'use strict';
/**
 * build_architect_brief.js — 把定设定、出卷纲、出一批细纲要用的 flow 手册、模板、流派包与卷纲取段拼成 story-architect 任务包。
 *
 * 用法:
 *   node build_architect_brief.js --project <书目录> --task world|volume|outline [--volume N] [--chapters A-B] [--rules-only]
 * Exit: 0 = 已写出；2 = 参数或资料缺失。
 */

const fs = require('node:fs');
const path = require('node:path');
const { parse: parseVolume, sliceArc, stripRetired, unitChapterRange } = require('./outline_view.js');

const SKILL_ROOT = path.resolve(__dirname, '..');
const REFERENCES = path.join(SKILL_ROOT, 'references');
const GENRE_STYLE_DIR = path.join(REFERENCES, 'genre-styles');
const FALLBACK_STYLE = path.join(GENRE_STYLE_DIR, '通用长篇.md');
const WORK_DIR = ['.story', 'work', '排纲'];
const FENCE_OPEN_RE = /^[ ]{0,3}(`{3,}|~{3,})([^\n]*)$/;
const FENCE_TAG_RE = /(?:^|\s)template=(\S+)/;

const BENCHMARK_REF = ['benchmark-recall.md', null, '`设定/题材定位.md`「对标登记」有对标书或 ≥2 本对标'];
const CONDITIONAL = {
  world: [BENCHMARK_REF],
  volume: [BENCHMARK_REF],
  outline: [BENCHMARK_REF],
};
const TEMPLATE_TARGETS = {
  题材定位: '设定/题材定位.md',
  全书梗概: '设定/全书梗概.md',
  关系: '设定/关系.md',
  主角卡: '设定/角色/{名}.md（主角）',
  配角卡: '设定/角色/{名}.md（配角）',
  大纲: '大纲/大纲.md',
  卷纲: '大纲/卷纲_第X卷.md',
  细纲: '大纲/细纲_第XXX章.md',
  排纲笔记: '.story/排纲笔记/{剧情段编号}.md',
};
const NEW_ADDITION_TIERS =
  '**新增物三级**（缺东西时三种处理；只看下一章需不需要知道它存在过）：\n' +
  '- **直接写**：微连接、路人、器物、地名细部、一次性对话、现场细节；不申报。\n' +
  '- **补上并记下**：具名配角、势力、复用地点属性、能力形态、规矩、刻度、新伏笔、新关系或承诺；' +
  '排纲先落设定档再引用，写正文照写并进申报表。\n' +
  '- **先问作者**：新主线事件或反转、金手指规则与力量档位、真相或伏笔结算、经济锚点、读者期待、' +
  '提前写后续章、改变细纲已定结果或人物决定、卷纲新增主线或故事线、碰这卷主打的线或后面才揭开的东西、' +
  '与既有规矩或承诺冲突；写正文时不写，排纲时挂起列候选，由主会话问作者。\n' +
  '拿不准：写时按补上并记下，处置时按先问作者。';

class BriefError extends Error {}

function fail(message) {
  throw new BriefError(message);
}

function readUtf8IfFile(filePath) {
  try {
    if (!fs.statSync(filePath).isFile()) return null;
    return fs.readFileSync(filePath, 'utf8').replace(/^\ufeff/, '').replace(/\r\n/g, '\n');
  } catch {
    return null;
  }
}

function readReference(name) {
  const filePath = path.join(REFERENCES, name);
  const text = readUtf8IfFile(filePath);
  if (text === null) {
    fail(`ERROR: 缺少 reference：${filePath}`);
  }
  return text;
}

function headings(text) {
  const found = [];
  let fence = null;
  const lines = text.split('\n');
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const marker = /^\s{0,3}(`{3,}|~{3,})/.exec(line);
    if (marker) {
      const value = marker[1];
      if (fence === null) {
        fence = value;
      } else if (value[0] === fence[0] && value.length >= fence.length) {
        fence = null;
      }
      continue;
    }
    if (!fence) {
      const match = /^(#{1,6})\s+(.*\S)\s*$/.exec(line);
      if (match) {
        found.push([index, match[1].length, match[2]]);
      }
    }
  }
  return found;
}

function rstrip(str) {
  return str.replace(/\s+$/, '');
}

function section(text, ...names) {
  const lines = text.split('\n');
  const marks = headings(text);
  const parts = [];
  for (const name of names) {
    const hit = marks.findIndex(([, , title]) => title.startsWith(name));
    if (hit < 0) {
      fail(`ERROR: reference 里找不到小节「${name}」`);
    }
    const [start, level] = marks[hit];
    const nextMark = marks.slice(hit + 1).find(([, lv]) => lv <= level);
    const end = nextMark ? nextMark[0] : lines.length;
    parts.push(rstrip(lines.slice(start, end).join('\n')));
  }
  return parts.join('\n\n');
}

function stripSubsection(text, name) {
  const lines = text.split('\n');
  const marks = headings(text);
  const hit = marks.findIndex(([, , title]) => title.startsWith(name));
  if (hit < 0) return text;
  const [start, level] = marks[hit];
  const nextMark = marks.slice(hit + 1).find(([, lv]) => lv <= level);
  const end = nextMark ? nextMark[0] : lines.length;
  return rstrip([...lines.slice(0, start), ...lines.slice(end)].join('\n'));
}

function escapeRegExp(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function templateBlock(text, tag, source = '参考文件') {
  const lines = text.replace(/^\ufeff/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const hits = [];
  let index = 0;
  while (index < lines.length) {
    const opened = FENCE_OPEN_RE.exec(lines[index]);
    if (!opened || (opened[1][0] === '`' && opened[2].includes('`'))) {
      index += 1;
      continue;
    }
    const marker = opened[1];
    const found = FENCE_TAG_RE.exec(opened[2]);
    const closeRe = new RegExp(`^[ ]{0,3}${escapeRegExp(marker[0])}{${marker.length},}[ \\t]*$`);
    let end = lines.length;
    for (let row = index + 1; row < lines.length; row += 1) {
      if (closeRe.test(lines[row])) {
        end = row;
        break;
      }
    }
    if (found && found[1] === tag) {
      hits.push(lines.slice(index + 1, end).join('\n'));
    }
    index = end + 1;
  }
  if (hits.length !== 1) {
    const reason = !hits.length ? `找不到模板「${tag}」` : `模板「${tag}」出现了 ${hits.length} 次`;
    fail(`ERROR: ${source} 里${reason}`);
  }
  return hits[0];
}

function templates(name, ...tags) {
  const text = readReference(name);
  const blocks = ['模板里的小节名、字段名照抄，不改名：写正文的脚本和别的 skill 按名读取。'];
  for (const tag of tags) {
    const body = templateBlock(text, tag, name);
    blocks.push(`### ${TEMPLATE_TARGETS[tag] || tag}\n\n\`\`\`markdown\n${body.trim()}\n\`\`\``);
  }
  return blocks.join('\n\n');
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

function matchPrimaryGenreStyle(project) {
  if (!project) return null;
  const text = stripHtmlComments(readUtf8IfFile(path.join(project, '设定', '题材定位.md')));
  if (!text) return null;
  const match = /^[ \t]*[-*+]?[ \t]*\**题材(?:类型)?\**[ \t]*[：:](.*)$/m.exec(text);
  const raw = !match || match[1].includes('{') ? '' : match[1].trim().toLowerCase();
  if (!raw) return null;
  let entries;
  try {
    entries = fs.readdirSync(GENRE_STYLE_DIR).filter((n) => n.endsWith('.md')).sort();
  } catch {
    return null;
  }
  const rank = { high: 0, medium: 1, low: 2 };
  const spans = [];
  for (const file of entries) {
    const full = path.join(GENRE_STYLE_DIR, file);
    const content = readUtf8IfFile(full) || '';
    const head = content.split('---');
    const meta = head.length > 2 ? head[1] : '';
    if (/^fallback:\s*true\s*$/m.test(meta)) continue;
    const genre = /^genre:\s*(.+)$/m.exec(meta);
    const aliases = /^aliases:\s*\[(.*)\]/m.exec(meta);
    const confidence = /^confidence:\s*(\w+)/m.exec(meta);
    const level = confidence ? confidence[1] : 'low';
    const baseName = genre ? genre[1].trim() : path.basename(file, '.md');
    const aliasList = aliases
      ? aliases[1].split(',').map((a) => a.trim().replace(/^['"]|['"]$/g, ''))
      : [];
    const names = new Set([baseName, ...aliasList].filter(Boolean).map((n) => n.toLowerCase()));
    for (const name of names) {
      let pos = 0;
      while (pos <= raw.length) {
        const idx = raw.indexOf(name, pos);
        if (idx < 0) break;
        spans.push([idx, idx + name.length, full, level]);
        pos = idx + name.length || idx + 1;
      }
    }
  }
  const best = new Map();
  const compareKey = (a, b) => {
    for (let i = 0; i < 3; i += 1) {
      if (a[i] !== b[i]) return a[i] - b[i];
    }
    return a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0;
  };
  for (const [start, end, card, level] of spans) {
    const dominated = spans.some(([s, e, c]) => c !== card && s <= start && end <= e && e - s > end - start);
    if (dominated) continue;
    const key = [start, -(end - start), rank[level] ?? 2, path.basename(card)];
    if (!best.has(card) || compareKey(key, best.get(card)[0]) < 0) {
      best.set(card, [key, level]);
    }
  }
  const hits = [...best.entries()]
    .map(([card, [key]]) => ({ key, card }))
    .sort((a, b) => compareKey(a.key, b.key));
  if (hits.length) return hits[0].card;
  return readUtf8IfFile(FALLBACK_STYLE) ? FALLBACK_STYLE : null;
}

function conditionalReads(task) {
  const lines = [
    '下面几份在包外，只在条件满足时读；条件不满足不读。流程提到而这里没列的参考文件不用找，对标资料缺了就停下说清缺哪份：',
  ];
  for (const [name, part, when] of CONDITIONAL[task]) {
    const text = readReference(name);
    if (part) {
      section(text, part);
    }
    lines.push(
      `- ${when}：读 \`agent-references/${name}\` ${part ? `「${part}」一节` : '整份'}`
    );
  }
  return lines.join('\n');
}

function render(sections, chosen, span, preamble) {
  const out = preamble && preamble.length ? [rstrip(stripRetired(preamble, false).join('\n'))] : [];
  for (const sec of sections) {
    if (!chosen.has(sec)) continue;
    const body =
      sec.title.includes('情绪弧线') || sec.title.includes('排班')
        ? sliceArc(sec, span)
        : sec.lines;
    out.push(rstrip(stripRetired(body, false).join('\n')));
  }
  return `${out.join('\n\n')}\n`;
}

function compress(numbers) {
  const spans = [];
  let start = numbers[0];
  for (let i = 0; i < numbers.length; i += 1) {
    const prev = numbers[i];
    const cur = i + 1 < numbers.length ? numbers[i + 1] : null;
    if (cur !== prev + 1) {
      spans.push(start !== prev ? `${start}-${prev}` : `${start}`);
      start = cur;
    }
  }
  return spans.join('、');
}

function listVolumeFiles(project) {
  const dir = path.join(project, '大纲');
  let entries;
  try {
    entries = fs.readdirSync(dir);
  } catch {
    return [];
  }
  return entries
    .filter((name) => /^卷纲_.*\.md$/.test(name))
    .sort()
    .map((name) => path.join(dir, name));
}

function unitClosures(project, first, last) {
  const found = [];
  const covered = new Set();
  const undeclared = [];
  for (const volumePath of listVolumeFiles(project)) {
    const volumeName = path.basename(volumePath);
    const { lines, sections } = parseVolume(fs.readFileSync(volumePath, 'utf8').replace(/^\ufeff/, ''));
    for (const s of sections) {
      if (s.scope === null && s.unit && (s.title.includes('剧情单元') || s.title.includes('段剧情'))) {
        undeclared.push(`${volumeName}「${s.title.trim()}」`);
      }
    }
    if (sections.some((s) => s.scope && (s.kind === null || (s.kind !== '卷级常任' && s.unit === null)))) {
      fail(`ERROR: ${volumeName} 标题注释（或旧的作用域行）写得不对，先跑 outline_view.js --check 修正`);
    }
    const active = sections.filter((s) => s.status !== '已退役');
    const shared = active.filter((s) => s.kind === '卷级常任' || s.scope === null);
    const units = [...new Set(active.filter((s) => s.unit && s.kind === '单元级').map((s) => s.unit))].sort();
    let given = false;
    for (const unit of units) {
      const span = unitChapterRange(active, unit);
      if (!(span && span[0] <= last && span[1] >= first)) continue;
      for (let ch = span[0]; ch <= span[1]; ch += 1) covered.add(ch);
      const live = active.filter((s) => s.unit === unit && s.kind === '单元级');
      let text;
      if (given) {
        text = `（全卷段同上一段，不重复。）\n\n${render(sections, new Set(live), span, null)}`;
      } else {
        text = render(
          sections,
          new Set([...shared, ...live]),
          span,
          sections.length ? lines.slice(0, sections[0].start) : null
        );
      }
      given = true;
      found.push([
        `${volumeName} · 剧情段 ${unit}（第${span[0]}-${span[1]}章；排纲笔记写 .story/排纲笔记/${unit}.md）`,
        text,
      ]);
    }
  }
  const missing = [];
  for (let n = first; n <= last; n += 1) {
    if (!covered.has(n)) missing.push(n);
  }
  if (missing.length) {
    const hint = undeclared.length
      ? `；这些剧情段的标题末尾缺单元编号注释（如 <!-- L1-01 -->）：${undeclared.join('、')}`
      : '（每段剧情的标题末尾写单元编号注释，如「### 第一段剧情：退婚风波 <!-- L1-01 -->」，卡里写「章节范围：第A-B章」）';
    const where = !found.length ? '找不到覆盖' : '剧情段只覆盖了一部分，缺覆盖';
    fail(
      `ERROR: 卷纲里${where}第${compress(missing)}章的剧情段${hint}，先补卷纲` +
        '（`outline_view.js --check --strict` 列出全部问题）'
    );
  }
  return found;
}

function pad3(n) {
  return String(n).padStart(3, '0');
}

function build(task, volume, chapters, project = null, rulesOnly = false) {
  const outside = '写作技法只读本包，外加包末「按条件可读」里条件满足的项。';
  const matchedPack = matchPrimaryGenreStyle(project);
  let head;
  let parts;
  if (task === 'world') {
    head =
      '# 任务包：出核心设定提案\n\n' +
      '按下面「核心设定方法」与模板，把核心设定写成文件：`设定/题材定位.md`（在定方向时已写的部分上补全，「题材框架」留到出卷纲补，不删作者已定的内容）、' +
      '`设定/全书梗概.md`、`设定/关系.md`、主角与关键角色的 `设定/角色/{名}.md`、影响全书的 `设定/世界观/{主题}.md`。' +
      '作者定下的话都在 `设定/题材定位.md`，先读它；物价、收入、力量档位这类全书刻度按下附「新增物三级」属问作者，只给 1–2 个候选。' +
      `不出卷纲、不写正文。${outside}交付后只回：写了哪些文件、主角与核心冲突各一句、要作者定的事（没有写「无」）。`;
    const opening = readReference('flow-opening-plan.md');
    parts = [
      ['flow-opening-plan.md（核心设定方法）', section(opening, '核心设定方法')],
      [
        'flow-opening-plan.md（设定与角色模板）',
        templates('flow-opening-plan.md', '题材定位', '全书梗概', '关系', '主角卡', '配角卡'),
      ],
    ];
  } else if (task === 'volume') {
    const label = volume ? `第${volume}卷` : '本卷';
    head =
      `# 任务包：出${label}卷纲\n\n` +
      `只交付 \`大纲/大纲.md\` 的分卷表（已有只补本卷行）、\`大纲/卷纲_第${volume || 'X'}卷.md\`，` +
      '并补齐 `设定/题材定位.md`「题材框架」的「关键转折节点」（标题写 `## 题材框架`，其余小节不动）；' +
      '不出细纲、不写正文、不建 `追踪/`。本书方向、设定与作者已定的事读 `设定/`。' +
      `${outside}交付后只回：写了哪些文件、四个排纲问题的结论、要作者定的事（没有写「无」）。`;
    const opening = readReference('flow-opening-plan.md');
    parts = [
      ['flow-opening-plan.md（排纲方法）', section(opening, '排纲方法（卷纲）')],
      ['flow-opening-plan.md（大纲与卷纲模板）', templates('flow-opening-plan.md', '大纲', '卷纲')],
    ];
  } else {
    const [first, last] = chapters;
    head =
      `# 任务包：出第${first}-${last}章细纲\n\n` +
      `只交付 \`大纲/细纲_第${pad3(first)}章\` 到第${pad3(last)}章，以及排纲笔记（\`.story/排纲笔记/{剧情段编号}.md\`）与必要的设定补全，` +
      '不写正文、不建 `追踪/`。本批涉及的卷纲剧情段附在包末（已按段取好），卷纲本身不整读；设定从 `设定/` 定点读；' +
      `${outside}交付后只回：写了哪些文件、每章一句核心事件、要作者定的事（没有写「无」）。`;
    const outlineDoc = readReference('flow-outline.md');
    let methodBlock = section(outlineDoc, '排纲方法');
    let methodLabel = 'flow-outline.md（排纲方法·含黄金三章）';
    if (first > 3) {
      methodBlock = stripSubsection(methodBlock, '黄金三章规划');
      methodLabel = 'flow-outline.md（排纲方法）';
    }
    parts = [
      [methodLabel, methodBlock],
      ['flow-outline.md（细纲与排纲笔记模板）', section(outlineDoc, '细纲与排纲笔记白话模板')],
      ['flow-opening-plan.md（主角卡、配角卡模板）', templates('flow-opening-plan.md', '主角卡', '配角卡')],
    ];
    if (!rulesOnly) {
      for (const [name, text] of unitClosures(project, first, last)) {
        parts.push([`卷纲取段：${name}`, text]);
      }
    }
  }
  if (matchedPack) {
    const packText = readUtf8IfFile(matchedPack);
    if (packText) {
      parts.push([`genre-styles/${path.basename(matchedPack)}`, packText]);
    }
  }
  parts.push(['SKILL.md（新增物三级）', NEW_ADDITION_TIERS]);
  parts.push(['按条件可读（包外）', conditionalReads(task)]);
  const body = [
    head +
      '\n\n包里流程写到的脚本命令（取段、`--check`、`check-outline-contract.js`）由主会话在你交付后跑，你不执行命令；需要的取段结果已放进包里。',
  ];
  for (const [name, text] of parts) {
    body.push(`\n---\n\n<!-- 资料：${name} -->\n\n${text.trim()}\n`);
  }
  return { text: body.join('\n'), included: parts.map(([name]) => name) };
}

function parseRange(value) {
  const match = /^\s*(\d+)\s*(?:-\s*(\d+))?\s*$/.exec(value || '');
  if (!match) {
    fail('ERROR: --chapters 写成 A-B，如 1-10');
  }
  const first = Number(match[1]);
  const last = Number(match[2] || match[1]);
  if (first < 1 || last < first) {
    fail('ERROR: --chapters 范围无效');
  }
  return [first, last];
}

const USAGE =
  'Usage: node build_architect_brief.js --project DIR --task (world|volume|outline) [--volume N] [--chapters A-B] [--rules-only]\n';

function parseCliArgs(argv) {
  const args = { project: null, task: null, volume: null, chapters: null, rulesOnly: false, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--help' || token === '-h') {
      return { help: true };
    } else if (token === '--project') {
      if (i + 1 >= argv.length) return { error: '--project requires a value' };
      args.project = argv[++i];
    } else if (token.startsWith('--project=')) {
      args.project = token.slice('--project='.length);
    } else if (token === '--task') {
      if (i + 1 >= argv.length) return { error: '--task requires a value' };
      args.task = argv[++i];
    } else if (token.startsWith('--task=')) {
      args.task = token.slice('--task='.length);
    } else if (token === '--volume') {
      if (i + 1 >= argv.length) return { error: '--volume requires an integer' };
      const raw = argv[++i];
      if (!/^-?\d+$/.test(raw)) return { error: `invalid --volume: ${raw}` };
      args.volume = Number(raw);
    } else if (token.startsWith('--volume=')) {
      const raw = token.slice('--volume='.length);
      if (!/^-?\d+$/.test(raw)) return { error: `invalid --volume: ${raw}` };
      args.volume = Number(raw);
    } else if (token === '--chapters') {
      if (i + 1 >= argv.length) return { error: '--chapters requires a value' };
      args.chapters = argv[++i];
    } else if (token.startsWith('--chapters=')) {
      args.chapters = token.slice('--chapters='.length);
    } else if (token === '--rules-only') {
      args.rulesOnly = true;
    } else {
      return { error: `unrecognized argument: ${token}` };
    }
  }
  if (!args.project) return { error: 'missing required --project' };
  if (!['world', 'volume', 'outline'].includes(args.task)) {
    return { error: 'missing or invalid --task (expected world|volume|outline)' };
  }
  return args;
}

function main(argv = process.argv.slice(2)) {
  const args = parseCliArgs(argv);
  if (args.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (args.error) {
    process.stderr.write(`ERROR: ${args.error}\n`);
    return 2;
  }
  let text;
  let included;
  let chapters = null;
  try {
    let isDir = false;
    try {
      isDir = fs.statSync(args.project).isDirectory();
    } catch {
      isDir = false;
    }
    if (!isDir) {
      fail(`ERROR: 书目录不存在：${args.project}`);
    }
    chapters = args.task === 'outline' ? parseRange(args.chapters) : null;
    if (args.task === 'outline' && chapters[1] - chapters[0] >= 10) {
      fail('ERROR: 一批细纲最多 10 章，拆成两批');
    }
    ({ text, included } = build(args.task, args.volume, chapters, args.project, args.rulesOnly));
  } catch (err) {
    if (err instanceof BriefError) {
      process.stderr.write(`${err.message}\n`);
      return 2;
    }
    throw err;
  }
  const outDir = path.join(args.project, ...WORK_DIR);
  fs.mkdirSync(outDir, { recursive: true });
  const name =
    args.task === 'world'
      ? '核心设定.md'
      : args.task === 'volume'
        ? args.volume
          ? `卷纲_第${args.volume}卷.md`
          : '卷纲.md'
        : `细纲_第${pad3(chapters[0])}-${pad3(chapters[1])}章.md`;
  const out = path.join(outDir, name);
  fs.writeFileSync(out, text, 'utf8');
  process.stdout.write(
    `${JSON.stringify({ brief: out, chars: text.replace(/\s/g, '').length, includes: included })}\n`
  );
  return 0;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { build, templateBlock, parseRange, main };
