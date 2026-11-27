#!/usr/bin/env node
'use strict';
/**
 * 卷纲取段器 —— 让「不整读卷纲」成立（同步到 story-import）。
 *
 * 用法：
 *   node outline_view.js --toc   卷纲.md
 *   node outline_view.js --unit D1-03 卷纲.md
 *   node outline_view.js --chapter 12 卷纲.md
 *   node outline_view.js --contract 卷纲.md
 *   node outline_view.js --check [--strict] 卷纲.md
 */

const fs = require('node:fs');

const HEADING = /^(#{2,4})\s+(.*\S)\s*$/;
const SCOPE = /^>\s*作用域[：:]\s*(.+?)\s*$/;
const TRAILING = /^(.*?)\s*<!--\s*(.*?)\s*-->\s*$/;
const RETIRED_LINE = /^\s*(?:[-*]\s*)?⊘|^\s*\|\s*⊘/;
const UNIT_IN_TITLE = /(?<![A-Za-z0-9_-])([LD]\d+-\d+|U\d+)(?![A-Za-z0-9_-])/;
const PLAIN_UNIT_TITLE = /^(第[一二三四五六七八九十百\d]+段)(?:[：:\s（(]|$)/;
const CH_RANGE = /章节范围[：:]\s*第\s*(\d+)\s*[-–—~至]\s*(\d+)\s*章/;
const TITLE_CH_RANGE = /[（(]\s*第?\s*(\d+)\s*[-–—~～至]\s*第?\s*(\d+)\s*章\s*[）)]/;
const ARC_ROW = /^\|\s*第?\s*(\d+)\s*章?\s*\|/;
const UNIT_ID = /(?<![A-Za-z0-9_-])([A-Za-z]\d+-\d+|U\d+)(?![A-Za-z0-9_-])/;

// 卷纲、细纲按名读取字段的新旧叫法（新名在前，旧名照认）。
const UNIT_FIELD_NAMES = {
  单元情绪引擎: ['这段让读者图什么', '单元情绪引擎'],
  '单元节拍/章功能分配': ['这段怎么排', '这段怎么走', '单元节拍/章功能分配', '单元节拍／章功能分配'],
};
const CHAPTER_UNIT_FIELDS = ['属于哪段剧情', '单元ID/位置'];

function escapeRegExp(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function classify(section) {
  const parts = section.scope.split(/[｜|]/).map((part) => part.trim());
  const head = parts[0];
  if (head === '卷级常任' || head === '全卷') {
    section.kind = '卷级常任';
  } else if (/^单元级(?:\s+[A-Za-z][\w-]*)?$/.test(head)) {
    section.kind = '单元级';
    const found = /^单元级\s+([A-Za-z][\w-]*)$/.exec(head);
    if (found) {
      section.unit = found[1];
    }
  } else if (section.inline && /^[A-Za-z][\w-]*$/.test(head) && new RegExp(`^${UNIT_ID.source}$`).test(head)) {
    section.kind = '单元级';
    section.unit = head;
  }
  if (parts.some((part) => part.includes('已退役'))) {
    section.status = '已退役';
  }
}

function isUnitCard(section) {
  if (section.kind !== '单元级' || section.inherited) {
    return false;
  }
  return (
    section.title.includes('剧情单元') ||
    section.title.includes('段剧情') ||
    PLAIN_UNIT_TITLE.test(section.title) ||
    section.lines.some((line) => CH_RANGE.test(line))
  );
}

function fieldValue(text, names) {
  const src = text || '';
  for (const name of names) {
    const pattern = new RegExp(
      `^[ \\t>]*[-*+][ \\t]*\\*{0,2}${escapeRegExp(name)}\\*{0,2}[ \\t]*[：:][ \\t]*(.*)$`,
      'm'
    );
    const match = pattern.exec(src);
    if (match) {
      return match[1].trim();
    }
  }
  return null;
}

function unitIdOf(value) {
  if (!value) return null;
  const found = UNIT_ID.exec(value);
  return found ? found[1] : null;
}

function chapterUnit(outlineText) {
  return unitIdOf(fieldValue(outlineText, CHAPTER_UNIT_FIELDS));
}

function unitForChapter(sections, chapter) {
  for (const section of sections) {
    if (section.status === '已退役' || !section.unit || !isUnitCard(section)) {
      continue;
    }
    let matchedLine = false;
    for (const line of section.lines) {
      const found = CH_RANGE.exec(line);
      if (found) {
        matchedLine = true;
        if (Number(found[1]) <= chapter && chapter <= Number(found[2])) {
          return section.unit;
        }
        break;
      }
    }
    if (!matchedLine) {
      const titleRange = TITLE_CH_RANGE.exec(section.title);
      if (titleRange && Number(titleRange[1]) <= chapter && chapter <= Number(titleRange[2])) {
        return section.unit;
      }
    }
  }
  return null;
}

function chapterUnitInVolume(volumeText, chapter) {
  try {
    const { sections } = parse(volumeText || '');
    return unitForChapter(sections, chapter);
  } catch {
    return null;
  }
}

function readUtf8Sig(filePath) {
  const raw = fs.readFileSync(filePath);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  return decoder.decode(raw).replace(/^\ufeff/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

class Section {
  constructor(level, title, start) {
    this.level = level;
    this.title = title;
    this.start = start;
    this.end = null;
    this.scope = null;
    this.kind = null; // 卷级常任 / 单元级
    this.unit = null;
    this.status = '在用';
    this.lines = [];
    this.inline = false;
    this.inherited = false;
  }
}

function parse(text) {
  const normalized = String(text).replace(/^\ufeff/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = normalized.split('\n');
  const sections = [];
  let fence = null;
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
    if (fence) {
      continue;
    }
    const match = HEADING.exec(line);
    if (match) {
      if (sections.length) {
        sections[sections.length - 1].end = index;
      }
      sections.push(new Section(match[1].length, match[2], index));
    }
  }
  if (sections.length) {
    sections[sections.length - 1].end = lines.length;
  }

  for (const section of sections) {
    section.lines = lines.slice(section.start, section.end);
    const trailing = TRAILING.exec(section.title);
    if (trailing && trailing[2]) {
      section.title = trailing[1].trim() || section.title;
      section.scope = trailing[2];
      section.inline = true;
    } else {
      for (const candidate of section.lines.slice(1)) {
        if (!candidate.trim()) continue;
        const scopeMatch = SCOPE.exec(candidate);
        if (scopeMatch) {
          section.scope = scopeMatch[1];
        }
        break;
      }
    }
    if (section.scope) {
      classify(section);
    }
    if (section.unit === null) {
      const found = /剧情单元\s+([A-Za-z][\w-]*)/.exec(section.title) || UNIT_IN_TITLE.exec(section.title);
      if (found) {
        section.unit = found[1];
      }
    }
    if (section.unit === null && section.scope === null) {
      for (const line of section.lines.slice(1)) {
        const field = /^\s*[-*+]\s*单元ID\s*[：:]\s*([A-Za-z][\w-]*)\s*$/.exec(line.replace(/\*\*/g, ''));
        if (field) {
          section.unit = field[1];
          break;
        }
      }
    }
    if (section.unit === null && section.scope === null) {
      const plainMatch = PLAIN_UNIT_TITLE.exec(section.title);
      if (plainMatch && (TITLE_CH_RANGE.test(section.title) || section.lines.some((line) => CH_RANGE.test(line)))) {
        section.unit = plainMatch[1];
        section.kind = '单元级';
      }
    }
  }

  const stack = [];
  for (const section of sections) {
    while (stack.length && stack[stack.length - 1].level >= section.level) {
      stack.pop();
    }
    const parent = stack.length ? stack[stack.length - 1] : null;
    if (section.scope === null && parent !== null && parent.inline && parent.kind === '单元级' && parent.unit) {
      section.scope = parent.scope;
      section.kind = parent.kind;
      section.unit = parent.unit;
      section.status = parent.status;
      section.inline = true;
      section.inherited = true;
    }
    stack.push(section);
  }

  if (sections.some((section) => section.inline)) {
    for (const section of sections) {
      if (section.scope === null && section.unit === null) {
        section.scope = '全卷';
        section.inline = true;
        classify(section);
      }
    }
  }
  return { lines, sections };
}

function stripRetired(blockLines, keepHistory) {
  return keepHistory ? blockLines : blockLines.filter((line) => !RETIRED_LINE.test(line));
}

function unitChapterRange(sections, unit) {
  for (const section of sections) {
    if (section.unit === unit && isUnitCard(section)) {
      for (const line of section.lines) {
        const found = CH_RANGE.exec(line);
        if (found) {
          return [Number(found[1]), Number(found[2])];
        }
      }
      const titleRange = TITLE_CH_RANGE.exec(section.title);
      if (titleRange) {
        return [Number(titleRange[1]), Number(titleRange[2])];
      }
    }
  }
  return null;
}

function sliceArc(section, span) {
  if (span === null || span === undefined) {
    return section.lines;
  }
  const [low, high] = span;
  return section.lines.filter((line) => {
    const row = ARC_ROW.exec(line);
    if (!row) return true;
    const ch = Number(row[1]);
    return low <= ch && ch <= high;
  });
}

function rstrip(str) {
  return str.replace(/\s+$/, '');
}

function emitView(sections, chosen, span, keepHistory, note, preamble) {
  const out = preamble && preamble.length ? [rstrip(stripRetired(preamble, keepHistory).join('\n'))] : [];
  for (const section of sections) {
    if (!chosen.has(section)) continue;
    const body =
      section.title.includes('情绪弧线') || section.title.includes('排班')
        ? sliceArc(section, span)
        : section.lines;
    out.push(rstrip(stripRetired(body, keepHistory).join('\n')));
  }
  process.stdout.write(`${out.join('\n\n')}\n`);
  if (note) {
    process.stderr.write(`${note}\n`);
  }
}

function padRight(value, width) {
  const s = String(value);
  return s.length >= width ? s : s + ' '.repeat(width - s.length);
}

function cmdToc(sections) {
  process.stdout.write(
    `${padRight('#', 3)} ${padRight('行', 6)} ${padRight('作用域', 9)} ${padRight('单元', 8)} ${padRight('段', 46)} 字符\n`
  );
  sections.forEach((section, idx) => {
    const size = section.lines.reduce((acc, line) => acc + line.length + 1, 0);
    const unitLabel = (section.unit || '-') + (section.status === '已退役' ? '(退)' : '');
    process.stdout.write(
      `${padRight(idx + 1, 3)} ${padRight(section.start + 1, 6)} ${padRight(section.kind || '**未声明**', 9)} ${padRight(unitLabel, 8)} ${padRight(section.title.slice(0, 44), 46)} ${size}\n`
    );
  });
}

function cmdCheck(sections, strict = false) {
  const problems = [];
  const warnings = [];
  for (const section of sections) {
    const where = `第${section.start + 1}行「${section.title.slice(0, 36)}」`;
    if (section.scope === null) {
      (strict ? problems : warnings).push([
        strict ? 'E1' : 'W2',
        where,
        '标题没标是全卷还是哪段剧情：标题末尾加 <!-- 全卷 --> 或 <!-- 单元编号 -->；旧段保守纳入',
      ]);
      continue;
    }
    if (section.kind === null) {
      problems.push(['E2', where, `标题注释不认识：${section.scope}（只认 全卷 / 单元编号）`]);
    }
    if (section.kind === '单元级' && section.unit === null) {
      problems.push(['E3', where, '剧情段没写单元编号']);
    }
  }
  for (const [code, where, message] of [...problems, ...warnings]) {
    process.stdout.write(`${code} ${where} ${message}\n`);
  }
  process.stdout.write('---\n');
  process.stdout.write(
    `段 ${sections.length} ／ 问题 ${problems.length} ／ 告警 ${warnings.length}（告警不阻断，逐条人工判断）\n`
  );
  return problems.length ? 1 : 0;
}

function printHelp(stream = process.stdout) {
  stream.write(
    'usage: node outline_view.js [--toc | --unit UNIT | --chapter N | --contract | --check] [--history] [--strict] path\n'
  );
}

function parseCliArgs(argv) {
  const args = {
    path: null,
    toc: false,
    unit: null,
    chapter: null,
    contract: false,
    check: false,
    history: false,
    strict: false,
    help: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '-h' || token === '--help') {
      args.help = true;
    } else if (token === '--toc') {
      args.toc = true;
    } else if (token === '--contract') {
      args.contract = true;
    } else if (token === '--check') {
      args.check = true;
    } else if (token === '--history') {
      args.history = true;
    } else if (token === '--strict') {
      args.strict = true;
    } else if (token === '--unit') {
      if (i + 1 >= argv.length) return { error: '--unit requires a value' };
      args.unit = argv[++i];
    } else if (token.startsWith('--unit=')) {
      args.unit = token.slice('--unit='.length);
    } else if (token === '--chapter') {
      if (i + 1 >= argv.length) return { error: '--chapter requires an integer' };
      const raw = argv[++i];
      if (!/^-?\d+$/.test(raw)) return { error: `invalid --chapter value: ${raw}` };
      args.chapter = Number(raw);
    } else if (token.startsWith('--chapter=')) {
      const raw = token.slice('--chapter='.length);
      if (!/^-?\d+$/.test(raw)) return { error: `invalid --chapter value: ${raw}` };
      args.chapter = Number(raw);
    } else if (token.startsWith('-')) {
      return { error: `unrecognized argument: ${token}` };
    } else if (args.path === null) {
      args.path = token;
    } else {
      return { error: `unexpected positional argument: ${token}` };
    }
  }
  return args;
}

function main(argv = process.argv.slice(2)) {
  const args = parseCliArgs(argv);
  if (args.error) {
    process.stderr.write(`error: ${args.error}\n`);
    return 2;
  }
  if (args.help) {
    printHelp(process.stdout);
    return 0;
  }
  if (!args.path) {
    printHelp(process.stderr);
    return 2;
  }

  let lines;
  let sections;
  try {
    ({ lines, sections } = parse(readUtf8Sig(args.path)));
  } catch (err) {
    process.stderr.write(`无法读取卷纲：${err.message}\n`);
    return 2;
  }
  if (!sections.length) {
    process.stderr.write('卷纲里没有 ## 段，路径对不对？\n');
    return 2;
  }

  if (args.toc) {
    cmdToc(sections);
    return 0;
  }
  if (args.check) {
    return cmdCheck(sections, args.strict);
  }

  const invalid = sections.filter(
    (s) => s.scope && (s.kind === null || (s.kind !== '卷级常任' && s.unit === null))
  );
  if (invalid.length) {
    process.stderr.write('标题注释（或旧的作用域行）写得不对，先运行 --check 修正\n');
    return 1;
  }
  const active = sections.filter((s) => args.history || s.status !== '已退役');
  const permanent = active.filter((s) => s.kind === '卷级常任');
  const undeclared = active.filter((s) => s.scope === null);
  const note = undeclared.length
    ? `${undeclared.length} 段没标全卷或单元编号，已保守纳入；用 --check 查看`
    : null;
  const preamble = lines.slice(0, sections[0].start);

  if (args.contract) {
    emitView(sections, new Set([...permanent, ...undeclared]), null, args.history, note, preamble);
    return 0;
  }

  if (args.chapter !== null && !args.unit) {
    args.unit = unitForChapter(active, args.chapter);
    if (!args.unit) {
      process.stderr.write(
        `卷纲里没有哪段剧情的章节范围覆盖第 ${args.chapter} 章 —— 不静默降级。核对剧情段的「章节范围」，或先补卷纲。\n`
      );
      return 1;
    }
    process.stderr.write(`第 ${args.chapter} 章属于剧情段 ${args.unit}\n`);
  }

  if (args.unit) {
    const owned = active.filter((s) => s.unit === args.unit);
    if (!owned.length) {
      process.stderr.write(`找不到单元 ${args.unit} —— 不静默降级。核对单元编号，或先补卷纲。\n`);
      return 1;
    }
    const live = owned.filter((s) => s.kind === '单元级');
    emitView(
      sections,
      new Set([...permanent, ...live, ...undeclared]),
      unitChapterRange(active, args.unit),
      args.history,
      note,
      preamble
    );
    return 0;
  }

  printHelp(process.stdout);
  return 2;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = {
  HEADING,
  SCOPE,
  TRAILING,
  RETIRED_LINE,
  UNIT_IN_TITLE,
  CH_RANGE,
  ARC_ROW,
  UNIT_ID,
  UNIT_FIELD_NAMES,
  CHAPTER_UNIT_FIELDS,
  Section,
  classify,
  isUnitCard,
  fieldValue,
  unitIdOf,
  chapterUnit,
  unitForChapter,
  chapterUnitInVolume,
  readUtf8Sig,
  parse,
  stripRetired,
  unitChapterRange,
  sliceArc,
  main,
};
