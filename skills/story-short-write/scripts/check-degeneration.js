#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const USAGE = `Usage: node check-degeneration.js [--check] [--json] [--fail-on=blocking|all] <file...>

Detect model-degeneration fingerprints that a degrading model cannot self-report:
  - verbatim repetition (复读/打转): a long sentence repeated, or back-to-back identical lines
  - mid-sentence truncation (截断): file ends without terminal/closing punctuation
  - placeholder / refusal / meta leakage (元信息泄漏): 作为AI / 我无法继续 / 此处省略 / 乱码
  - engineering-word leakage (工程词泄漏): 细纲 / 情节点 / 本章 / 下一章 / 任务描述 漏进正文

Each finding carries severity: blocking (复读/截断/占位拒绝语/tier1 纯工程词，正文里永不合法，
命中即重写) 或 advisory (tier2 章节/歧义词、对话行里的工程词，只提示、交人/LLM 判)。
--fail-on=blocking 只在出现 blocking finding 时退出 1；默认 --fail-on=all 有任何 finding 即退出 1。

Report-only. The script never rewrites — the safe response is to regenerate the
affected unit (chapter / 摘要) with the finding fed back as a constraint, cap retries,
then surface the evidence to the user. Conservative by design: 通俗网文 deliberately
uses 排比/复沓/弹幕刷屏/重复台词 for rhythm, so short and dialogue repetition is exempt.`;

// 复读：长句（可见字数 ≥ REPEAT_MIN_LEN）出现 ≥ REPEAT_MIN_COUNT 次判为打转；
// 紧邻整行重复（可见字数 ≥ ADJACENT_MIN_LEN）判为即时循环。短句/弹幕/对话刷屏豁免。
const REPEAT_MIN_LEN = 12;
const REPEAT_MIN_COUNT = 3;
const ADJACENT_MIN_LEN = 8;

// hard = 任何行都判（正文里永不合法）；soft = 只在「非对话」叙述行判（角色台词里可能合法，
// 如「对不起，我无法答应你」是正常对话，不是模型拒绝语）。
const PLACEHOLDER_PATTERNS = [
  // 「作为AI」需在自指位置（其后是断句/我/无法… 或句末），避免误报「人工智能时代的产物」这类
  // 复合名词；并对对话行豁免（系统流/AI 伴侣题材里 AI 角色台词「作为AI，我会保护你」是合法对话）。
  // 型号后缀（AI语言模型/AI助手/人工智能语言模型/AI模型/AI大模型）必须可选吃掉：否则前视断言紧跟
  // 在「AI」后面看到的是「语」/「助」/「模」，最典型的退化开场整类漏检（与写后网 story_hook_core.js
  // SOFT_PATTERNS / story_codex_hook.py _NET_SOFT_PATTERNS 同语义）。
  { re: /作为(一个)?(AI|人工智能|大?语言模型|智能助手|聊天助手)(?:语言模型|大?模型|助手|机器人)?(?=[，,。、；;：:！!？?\s）)」』"】]|我|无法|不能|没法|$)/, label: '元信息泄漏（AI 自指）', hard: false },
  { re: /�/, label: '乱码（替换字符 �）', hard: true },
  { re: /^(Sure|Certainly|Here'?s|As an AI|I (?:cannot|can't|am unable|apologize))/, label: '元信息泄漏（英文 AI 腔）', hard: true },
  { re: /[（(](此处|以下|这里|下文|后续)?\s*(省略|略)(去|过)?[^）)]{0,10}[）)]/, label: '占位符（括号省略）', hard: true },
  { re: /(未完待续|TODO|占位符|placeholder)/, label: '占位符', hard: true },
  { re: /我(无法|不能)(继续(写|创作|生成|下去)|生成(内容|文本|正文)?|创作|续写|完成(这个|本)?(章|篇|创作|请求))/, label: '元信息泄漏（生成拒绝语）', hard: false },
];

const QUOTED_SPAN_PATTERNS = [
  /「[^」]*」/g,
  /『[^』]*』/g,
  /【[^】]*】/g,
  /“[^”]*”/g,
  // 单引号须成对；词内撇号（don't、O’Connor）不作为开闭引号。
  /(?<![A-Za-z0-9_])‘(?:[^’]|(?<=[A-Za-z0-9_])’(?=[A-Za-z0-9_]))*(?!(?<=[A-Za-z0-9_])’[A-Za-z0-9_])’/g,
  /"[^"]*"/g,
  /(?<![A-Za-z0-9_])'(?:[^']|(?<=[A-Za-z0-9_])'(?=[A-Za-z0-9_]))*(?!(?<=[A-Za-z0-9_])'[A-Za-z0-9_])'/g,
];

// 工程词泄漏（正文元信息扫描的确定性版）：弱模型把写作工程词漏进正文，破坏代入感
// （DeepSeek-v4 这类会在对话里冒「该到下一章了」）。漏词的模型自己发现不了，靠脚本兜。
// tier1 = 纯写作流水线术语，正文里几乎永不合法；tier2 = 章节结构/歧义词，角色在故事内
// 真实阅读/讨论「第X章」或故事内系统/界面用语时属例外（report-only，交人/LLM 判）。
const META_TIER1_RE = /细纲|情节点|卷纲|功能标签|目标情绪|字数目标|章首钩子|章尾钩子/;
const META_TIER2_RE = /第[一二三四五六七八九十百千万两0-9]+章|本章|这一章|上一章|下一章|上章|下章|前一章|后一章|前文|后文|伏笔|读者|任务描述/;

const options = { json: false, files: [], failOn: 'all' };

for (let i = 2; i < process.argv.length; i += 1) {
  const arg = process.argv[i];
  if (arg === '--check') {
    // Accepted for symmetry with the other detectors; detection is always check-only.
  } else if (arg === '--json') {
    options.json = true;
  } else if (arg.startsWith('--fail-on=')) {
    const v = arg.slice('--fail-on='.length);
    if (v !== 'blocking' && v !== 'all') die(`--fail-on must be 'blocking' or 'all'`);
    options.failOn = v;
  } else if (arg === '-h' || arg === '--help') {
    process.stdout.write(`${USAGE}\n`);
    process.exit(0);
  } else if (arg.startsWith('-')) {
    die(`Unknown option: ${arg}`);
  } else {
    options.files.push(arg);
  }
}

if (options.files.length === 0) {
  die('No files provided');
}

let failed = false;
const allFindings = [];

for (const file of options.files) {
  const fullPath = path.resolve(file);
  let input;
  try {
    input = fs.readFileSync(fullPath, 'utf8');
  } catch (error) {
    failed = true;
    if (!options.json) console.error(`${file}: unable to read (${error.message})`);
    continue;
  }
  const findings = scanDocument(input).map((finding) => ({ file, ...finding }));
  allFindings.push(...findings);
}

if (options.json) {
  process.stdout.write(`${JSON.stringify({ findings: allFindings }, null, 2)}\n`);
} else {
  for (const f of allFindings) {
    console.log(`${f.file}:${f.line}:${f.column}: [${f.severity}] ${f.type}: ${f.message} (${f.excerpt})`);
  }
}

if (failed) process.exit(2);
// --fail-on=blocking 只在出现 blocking finding 时退出 1（advisory 仅报告）；默认 all 沿用「有任何 finding 即 1」。
const hasBlocking = allFindings.some((f) => f.severity === 'blocking');
if (options.failOn === 'blocking' ? hasBlocking : allFindings.length > 0) process.exit(1);

function die(message) {
  console.error(message);
  console.error(USAGE.trimEnd());
  process.exit(2);
}

function scanDocument(input) {
  const lines = input.split(/\r?\n/);
  const content = []; // { text, trimmed, lineNo } for body lines outside front-matter/fences
  let fence = null;
  let inFrontMatter = hasYamlFrontMatter(lines);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (inFrontMatter) {
      if (index > 0 && trimmed === '---') inFrontMatter = false;
      continue;
    }
    const fenceMarker = /^(?:`{3,}|~{3,})/.exec(trimmed);
    if (fence) {
      if (fenceMarker && trimmed[0] === fence) fence = null;
      continue;
    }
    if (fenceMarker) {
      fence = trimmed[0];
      continue;
    }
    content.push({ text: line, trimmed, lineNo: index + 1 });
  }

  const findings = [];
  findings.push(...findRepetition(content));
  findings.push(...findTruncation(content));
  findings.push(...findPlaceholders(content));
  findings.push(...findMetaLeak(content));
  findings.sort((a, b) => a.line - b.line || a.column - b.column);
  return findings;
}

function isContent(trimmed) {
  return trimmed && !trimmed.startsWith('#') && !/^-{3,}$/.test(trimmed);
}

// 等长遮住成对引号内的内容以保留列号；未闭合引号不豁免。
function maskQuotedSpans(text) {
  let masked = text;
  for (const pattern of QUOTED_SPAN_PATTERNS) {
    masked = masked.replace(pattern, (match) => ' '.repeat(match.length));
  }
  return masked;
}

// 去掉成对引号内的片段（台词/系统词/引用物件），只留引号外叙述。复读判定用：重复台词是体裁
// 手法（豁免），但「叙述 + 引号内物件/短台词」混合行里引号外叙述的复读仍是退化，不能整行豁免。
function stripQuoted(text) {
  let stripped = text;
  for (const pattern of QUOTED_SPAN_PATTERNS) {
    stripped = stripped.replace(pattern, '');
  }
  return stripped;
}

function visibleLength(text) {
  const m = text.match(/[一-鿿Ａ-ｚA-Za-z0-9]/g);
  return m ? m.length : 0;
}

function findRepetition(content) {
  const findings = [];
  const body = content.filter((c) => isContent(c.trimmed));

  // (1) back-to-back identical lines (immediate loop). 纯台词/弹幕复沓（引号外叙述很短）豁免；
  // 「叙述 + 引号内物件」混合行的整行复读仍判（去引号后叙述够长）。
  for (let i = 1; i < body.length; i += 1) {
    if (
      body[i].trimmed === body[i - 1].trimmed &&
      visibleLength(stripQuoted(body[i].trimmed)) >= ADJACENT_MIN_LEN
    ) {
      findings.push({
        line: body[i].lineNo,
        column: 1,
        type: 'verbatim-repeat',
        severity: 'blocking',
        message: '逐行复读（紧邻整行重复）：疑似模型打转，重写本段、删掉重复。',
        excerpt: compact(body[i].trimmed),
      });
    }
  }

  // (2) any long sentence repeated >= REPEAT_MIN_COUNT times across the file.
  // 只豁免引号内台词（体裁手法），引号外叙述句仍参与复读计数（含「叙述+引号内物件」混合行）。
  const counts = new Map();
  for (const { trimmed } of body) {
    for (const sentence of stripQuoted(trimmed).split(/[。！？!?]/)) {
      const s = sentence.trim();
      if (visibleLength(s) < REPEAT_MIN_LEN) continue;
      const entry = counts.get(s) || { count: 0, firstLine: null };
      entry.count += 1;
      counts.set(s, entry);
    }
  }
  // record first line for repeated sentences
  const flagged = new Set();
  for (const [s, entry] of counts) {
    if (entry.count >= REPEAT_MIN_COUNT) flagged.add(s);
  }
  if (flagged.size) {
    for (const { trimmed, lineNo } of body) {
      for (const sentence of stripQuoted(trimmed).split(/[。！？!?]/)) {
        const s = sentence.trim();
        if (flagged.has(s)) {
          findings.push({
            line: lineNo,
            column: 1,
            type: 'verbatim-repeat',
            severity: 'blocking',
            message: `长句复读（同句出现 ${counts.get(s).count} 次）：疑似模型打转，重写、保留一处。`,
            excerpt: compact(s),
          });
          flagged.delete(s); // report each repeated sentence once, at its first occurrence
        }
      }
    }
  }

  return findings;
}

function findTruncation(content) {
  const body = content.filter((c) => isContent(c.trimmed));
  if (body.length === 0) return [];
  const last = body[body.length - 1];
  // a finished chapter ends on terminal/closing punctuation; otherwise it was cut off.
  if (/[。！？!?…”"』」）)】]$/.test(last.trimmed)) return [];
  return [{
    line: last.lineNo,
    column: last.trimmed.length,
    type: 'truncated',
    severity: 'blocking',
    message: '疑似截断：正文末尾未以句末/收尾标点结束，可能被模型中途切断；补完结尾或重写收尾。',
    excerpt: compact(last.trimmed.slice(-24)),
  }];
}

function findPlaceholders(content) {
  const findings = [];
  for (const { trimmed, lineNo } of content) {
    if (!isContent(trimmed)) continue;
    const outsideQuotes = maskQuotedSpans(trimmed);
    for (const { re, label, hard } of PLACEHOLDER_PATTERNS) {
      // hard 信号仍扫描整行；soft 自指/拒绝语只扫描成对引号外，且遮罩等长以保留列号。
      const m = re.exec(hard ? trimmed : outsideQuotes);
      if (m) {
        const index = m.index || 0;
        findings.push({
          line: lineNo,
          column: index + 1,
          type: 'placeholder-leak',
          severity: 'blocking',
          message: `${label}：正文混入元信息/拒绝语/占位符，重写本段干净落地。`,
          excerpt: compact(trimmed.slice(Math.max(0, index - 4), index + 20)),
        });
        break; // one finding per line is enough
      }
    }
  }
  return findings;
}

function findMetaLeak(content) {
  const findings = [];
  let firstContentSeen = false;
  for (const { trimmed, lineNo } of content) {
    if (!isContent(trimmed)) continue;
    if (!firstContentSeen) {
      firstContentSeen = true;
      // 标题行（第N章 章名，无 ## 前缀时也算）属「标题行以外的正文」之外，排除
      if (/^第[一二三四五六七八九十百千万两0-9]+章/.test(trimmed)) continue;
    }
    const outsideQuotes = maskQuotedSpans(trimmed);
    let m = META_TIER1_RE.exec(outsideQuotes);
    let quotedTier1 = false;
    if (!m) {
      m = META_TIER1_RE.exec(trimmed);
      quotedTier1 = Boolean(m);
    }
    if (m) {
      // tier1 纯工程词正文里几乎永不合法→blocking；但写手/编剧题材里角色在故事内真讨论创作，
      // 且命中实际位于成对引号内时可能合法，降级为 advisory。同一行别处出现引号不影响判定。
      findings.push({
        line: lineNo,
        column: m.index + 1,
        type: 'meta-leak',
        severity: quotedTier1 ? 'advisory' : 'blocking',
        message: `工程词泄漏：「${m[0]}」是写作流水线术语，正文里不该出现；改成角色/场景内表达。${quotedTier1 ? '例外：角色为作者/编剧、在故事内真实讨论创作时，台词里可能合法。' : ''}`,
        excerpt: compact(trimmed.slice(Math.max(0, m.index - 6), m.index + 18)),
      });
      continue; // tier1 命中即可，不再叠 tier2
    }
    m = META_TIER2_RE.exec(trimmed);
    if (m) {
      findings.push({
        line: lineNo,
        column: m.index + 1,
        type: 'meta-leak',
        severity: 'advisory',
        message: `元信息泄漏：「${m[0]}」疑似工程/章节结构词混入正文；改成角色当下可感知的事件锚点或相对时间。例外：角色在故事内真实阅读/讨论「第X章」、真身为作者/读者、或故事内系统/界面用语。`,
        excerpt: compact(trimmed.slice(Math.max(0, m.index - 6), m.index + 18)),
      });
    }
  }
  return findings;
}

function hasYamlFrontMatter(lines) {
  if (!lines[0] || lines[0].trim() !== '---') return false;
  let sawYamlField = false;
  for (let i = 1; i < Math.min(lines.length, 40); i += 1) {
    const trimmed = lines[i].trim();
    if (trimmed === '---') return sawYamlField;
    if (/^[A-Za-z0-9_-]+:\s*/.test(trimmed)) sawYamlField = true;
  }
  return false;
}

function compact(text) {
  const normalized = text.replace(/\s+/g, ' ').trim();
  return normalized.length > 80 ? `${normalized.slice(0, 77)}...` : normalized;
}
