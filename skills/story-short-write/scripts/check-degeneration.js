#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const USAGE = `Usage: node check-degeneration.js [--check] [--json] [--fail-on=blocking|review_required|all] <file...>

Detect model-degeneration fingerprints that a degrading model cannot self-report:
  - verbatim repetition (复读/打转): a long sentence repeated, back-to-back identical lines, or near-repeat (advisory)
  - mid-sentence truncation (截断): file ends without terminal/closing punctuation
  - placeholder / refusal / meta leakage (元信息泄漏): 作为AI / 我无法继续 / 此处省略 / 乱码 / Markdown **粗体**残留
  - censored-pinyin & opening author meta header (审查拼音替代 / 首 500 字作者元声明, review_required)
  - engineering-word leakage (工程词泄漏): 细纲 / 情节点 / 本章 / 下一章 / 任务描述 漏进正文

Each finding carries severity: blocking (复读/截断/占位拒绝语/Markdown粗体/tier1 纯工程词，正文里永不合法，
命中即重写)、review_required (审查拼音残片/开篇作者元声明，需人工清理或确认) 或 advisory (近距复读/tier2 章节歧义词/对话内工程词，只提示、交人/LLM 判)。
--fail-on=blocking 只在出现 blocking finding 时退出 1；--fail-on=review_required 在 blocking 或 review_required 时退出 1；默认 --fail-on=all 有任何 finding 即退出 1。

Report-only. The script never rewrites — the safe response is to regenerate the
affected unit (chapter / 摘要) with the finding fed back as a constraint, cap retries,
then surface the evidence to the user. Conservative by design: 通俗网文 deliberately
uses 排比/复沓/弹幕刷屏/重复台词 for rhythm, so short and dialogue repetition is exempt.`;

// 复读：长句（可见字数 ≥ REPEAT_MIN_LEN）出现 ≥ REPEAT_MIN_COUNT 次判为打转；
// 紧邻整行重复（可见字数 ≥ ADJACENT_MIN_LEN）判为即时循环。短句/弹幕/对话刷屏豁免。
const REPEAT_MIN_LEN = 12;
const REPEAT_MIN_COUNT = 3;
const ADJACENT_MIN_LEN = 8;
const NEAR_REPEAT_WINDOW = 20;
const NEAR_REPEAT_MIN_LEN = 16;
const NEAR_REPEAT_SHORT_SKIP_LINES = 35;
const MARKDOWN_BOLD_RE = /\*\*[^*\n]{2,80}\*\*/;

// hard = 任何行都判（正文里永不合法）；soft = 只在「非对话」叙述行判（角色台词里可能合法，
// 如「对不起，我无法答应你」是正常对话，不是模型拒绝语）。
const PLACEHOLDER_PATTERNS = [
  // 「作为AI」需在自指位置（其后是断句/我/无法… 或句末），避免误报「人工智能时代的产物」这类
  // 复合名词；并对对话行豁免（系统流/AI 伴侣题材里 AI 角色台词「作为AI，我会保护你」是合法对话）。
  // 型号后缀（AI语言模型/AI助手/人工智能语言模型/AI模型/AI大模型）必须可选吃掉：否则前视断言紧跟
  // 在「AI」后面看到的是「语」/「助」/「模」，最典型的退化开场整类漏检（与写后网 story_hook_core.js
  // SOFT_PATTERNS 同语义）。
  { re: /作为(一个)?(AI|人工智能|大?语言模型|智能助手|聊天助手)(?:语言模型|大?模型|助手|机器人)?(?=[，,。、；;：:！!？?\s）)」』"】]|我|无法|不能|没法|$)/, label: '元信息泄漏（AI 自指）', hard: false },
  { re: /�/, label: '乱码（替换字符 �）', hard: true },
  { re: /^(Sure|Certainly|Here'?s|As an AI|I (?:cannot|can't|am unable|apologize))/, label: '元信息泄漏（英文 AI 腔）', hard: true },
  { re: /[（(](?:(?:此处|以下|这里|下文|后续)\s*(?:省略|略(?:去|过)?)|(?:省略|略去|略过|下略)|略(?=[）)]|[\s。，,、]))[^）)]{0,12}[）)]/, label: '占位符（括号省略）', hard: true },
  { re: /(未完待续|TODO|占位符|placeholder|待补充|此处待填|此处待补)/, label: '占位符', hard: true },
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
// 细纲字段名改白话后（0.10），新旧字段名都算工程词；「分寸」「作用」是常用词，不收；穿书常见词「剧情节点」不收。短篇小节大纲的节尾列新旧名同收。
const META_TIER1_RE = /细纲|(?<!剧)情节点|卷纲|功能标签|目标情绪|字数目标|字数口径|章首钩子|章尾钩子|这章不能说破|本章禁止提前释放|排纲笔记|排纲底稿|节尾停在哪|结尾承接/;
const META_TIER2_RE = /第[一二三四五六七八九十百千万两0-9]+章|本章|这一章|上一章|下一章|上章|下章|前一章|后一章|(?<![天日月年周秒此目之])(?<!小时|分钟)前文(?!创|物|件|化|字|书|学|章|稿|档|艺|博|旅)|(?<![往以日之然随而最背太皇课餐术婚战雨午夜])后文(?!创|物|件|化|字|书|学|章|稿|档|艺|博|旅|远|武|官|人|明|士|臣|脉|房|雅|静|弱|秀|华|昌|轩|渊)|伏笔|读者|任务描述|(?<![男女])主角|(?<!大)男主(?!人|角)|(?<!大)女主(?!播|持|唱|厨|任|治|委|管|编|笔|席|讲|人|角)|反派/;
const BOOK_WORLD_CTX_RE = /穿书|快穿|穿成|原书|原著|原剧情|话本|攻略|弹幕|系统|剧本|炮灰|救赎任务|暴君|霸总|甜宠文|虐文|爽文|书里/;
const BOOK_WORLD_EXEMPT_META_RE = /^(?:主角|反派|男主|女主|读者|第[零〇一二三四五六七八九十百千万两0-9]+章)$/;
// 日常现实语境里的「主角/反派」（如今晚的主角、庆功宴主角、拍卖会主角、热搜稿换个主角、短剧反派女二）属正常中文，不报 meta-leak。
const REAL_WORLD_ROLE_CTX_RE = /(?:今晚|今夜|今天|今日|全场|聚会|宴会|庆功宴|拍卖会|婚礼|寿宴|话题|热搜|绯闻|八卦|传闻|新闻|报道|采访|镜头|舞台|电影|短剧|戏剧|剧组|演戏|拍戏|戏里|故事|小说|世界|众星捧月|上面|绝对|真正|唯一|换个|当个|成了|成为|就是)[^，。！？!?\n]{0,8}(?:主角|反派|男主|女主)|(?:主角|反派)(?:光环|模板|待遇|戏份|人设|女二|男二|角色|演出|演技|戏|正是)/;
const CHAPTER_HEADING_PREFIX_RE = /^第\s*[零〇一二三四五六七八九十百千万两0-9]+\s*[章节回]/;
const END_SIGNOFF_RE = /^[-—~～＜<【\[（(《\s]*(?:全文完|正文完|全书完|本卷完|完结|完|END|The\s+End)[-—~～＞>】\]）)》.。！!\s]*$/i;

// 审查拼音替代残片（review_required）：仅收明确「中文+小写拼音」审查替代组合，
// 强制区分大小写且要求边界不接 ASCII 字母数字，严禁误伤 VIP/CEO/AI/PDF/NPC/HP/3cm/A4/5G/Lv5/iPhone/OK 等正常英文缩写与单位。
const CENSORED_PINYIN_RE = /(?:身ti|亲wen|大tui|小tui|胸kou|胸bu|裤dang|屁gu|腰zhi|锁gu|肚qi|大xiong|小fu|私chu|下ti|敏gan|诱huo|娇chuan|喘xi|暧mei|缠mian|情yu|欲wang|性gan|裸lu|春guang|赤luo|失shen|破chu|怀yun|流chan|堕tai|强bao|强jian|猥xie|轮jian|嫖chang|卖yin|杀si|杀ren|杀lu|自sha|死wang|死shi|尸ti|血xing|鲜xue|血rou|暴li|虐dai|毒pin|吸du|赌bo|诈pian|走si|贪wu|贿lu|黑bang|枪zhi|子dan|炸dan|军huo|政zhi|官chang|造fan|谋fan|反pan|腐bai|警cha|法ting|监yu|看shou所|脑can|傻bi|妈de|草ni|滚dan|贱ren|婊zi|狗ri|卧cao|他ma|两sui|三sui|几sui)(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])(?:sha人|sha死|si亡|shi体|xue腥|qin吻|shen体|xiong口|da腿|ku裆|pi股|qiang奸|qiang暴|zi杀|du品|qiang支|zha弹|sha逼|wo草|ta妈)(?=[\u4e00-\u9fff，,。！？!?、；;：:\s]|$)/;

// 开篇作者元声明（review_required，仅扫正文首 500 可见字内）：拦截脑子寄存处、作者有话说、求好评/催更、本书又名等非正文头注。
const AUTHOR_META_HEADER_RE = /脑子寄存处|大脑寄存处|交出你的大脑|作者有话说|作者说[:：]|(?:^|[【\[（(])作者说(?=\s|$)|作者菌|求(?:五星|一点)?好评|求催更|求(?:推荐票|月票|打赏|收藏|追读)|本书又名|新书求(?:支持|收藏|追读)|评分刚出|不爱看就划走|介意者?慎入|避个雷[，,。！!]?\s*(?:不爱看|介意|慎入)/;
const AUTHOR_META_HEADER_MAX_CHARS = 500;

const options = { json: false, files: [], failOn: 'all' };

for (let i = 2; i < process.argv.length; i += 1) {
  const arg = process.argv[i];
  if (arg === '--check') {
    // Accepted for symmetry with the other detectors; detection is always check-only.
  } else if (arg === '--json') {
    options.json = true;
  } else if (arg === '--fail-on') {
    const v = process.argv[i + 1];
    if (v !== 'blocking' && v !== 'review_required' && v !== 'all') die(`--fail-on must be 'blocking', 'review_required', or 'all'`);
    options.failOn = v;
    i += 1;
  } else if (arg.startsWith('--fail-on=')) {
    const v = arg.slice('--fail-on='.length);
    if (v !== 'blocking' && v !== 'review_required' && v !== 'all') die(`--fail-on must be 'blocking', 'review_required', or 'all'`);
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
// 用 process.exitCode 而非 process.exit(1)，确保 >64KB JSON 管道输出完整刷出后再退出。
const hasBlocking = allFindings.some((f) => f.severity === 'blocking');
const hasReviewRequired = allFindings.some((f) => f.severity === 'blocking' || f.severity === 'review_required');
const shouldFail =
  options.failOn === 'blocking'
    ? hasBlocking
    : options.failOn === 'review_required'
      ? hasReviewRequired
      : allFindings.length > 0;
if (shouldFail) process.exitCode = 1;

function die(message) {
  console.error(message);
  console.error(USAGE.trimEnd());
  process.exit(2);
}

function scanDocument(input) {
  // 剥离零宽不可见字符，防从网页/飞书/微信粘贴夹带 \u200b 绕过机械检测
  const lines = String(input || '').replace(/[\u200B-\u200D\uFEFF]/g, '').split(/\r?\n/);
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
  findings.push(...findMarkdownLeak(content));
  findings.push(...findCensoredPinyin(content));
  findings.push(...findAuthorMetaHeader(content));
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
  const flaggedAll = new Set();
  for (const [s, entry] of counts) {
    if (entry.count >= REPEAT_MIN_COUNT) {
      flagged.add(s);
      flaggedAll.add(s);
    }
  }
  const reportedLines = new Set();
  for (const f of findings) reportedLines.add(f.line);
  if (flagged.size) {
    for (const { trimmed, lineNo } of body) {
      for (const sentence of stripQuoted(trimmed).split(/[。！？!?]/)) {
        const s = sentence.trim();
        if (flaggedAll.has(s)) reportedLines.add(lineNo);
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

  // (3) non-adjacent near-repeat within NEAR_REPEAT_WINDOW body lines (advisory only).
  // Catches 2x copy-paste loops missed by adjacent (distance 1) and 3x sentence repeat,
  // while skipping pure dialogue, system panels, short-form lead callbacks (first 35 body lines),
  // and lines already flagged above.
  const isShortDoc = body.length > 100 && body.some((b) => /^(?:###\s*\d+\.?|\d+\.)\s*$/.test(b.trimmed));
  const normVis = (s) => (s.match(/[一-鿿Ａ-ｚA-Za-z0-9]/g) || []).join('');
  const bigrams = (s) => {
    const set = new Set();
    for (let k = 0; k < s.length - 1; k += 1) set.add(s.slice(k, k + 2));
    return set;
  };
  const jaccard = (a, b) => {
    if (a.size === 0 || b.size === 0) return 0;
    let inter = 0;
    for (const x of a) if (b.has(x)) inter += 1;
    return inter / (a.size + b.size - inter);
  };
  const norms = body.map((b) => {
    const trimmed = b.trimmed;
    if (/^[-—─=*·•.~～…\s]+$/.test(trimmed) || trimmed.startsWith('【')) return null;
    if (visibleLength(stripQuoted(trimmed)) < ADJACENT_MIN_LEN) return null;
    const n = normVis(trimmed);
    if (n.length < NEAR_REPEAT_MIN_LEN) return null;
    return { norm: n, bg: bigrams(n) };
  });
  for (let i = 2; i < body.length; i += 1) {
    if (reportedLines.has(body[i].lineNo)) continue;
    const cur = norms[i];
    if (!cur) continue;
    const startIdx = Math.max(0, i - NEAR_REPEAT_WINDOW);
    for (let j = i - 2; j >= startIdx; j -= 1) {
      if (isShortDoc && j < NEAR_REPEAT_SHORT_SKIP_LINES) continue;
      if (reportedLines.has(body[j].lineNo)) continue;
      const prev = norms[j];
      if (!prev) continue;
      if (cur.norm === prev.norm || jaccard(cur.bg, prev.bg) >= 0.85) {
        findings.push({
          line: body[i].lineNo,
          column: 1,
          type: 'near-repeat',
          severity: 'advisory',
          message: `近距复读（与第 ${body[j].lineNo} 行高度重复）：疑似中段复制打转，确认非刻意回扣则改写推进。`,
          excerpt: compact(body[i].trimmed),
        });
        reportedLines.add(body[i].lineNo);
        break;
      }
    }
  }

  return findings;
}

function findTruncation(content) {
  const body = content.filter((c) => isContent(c.trimmed) && !END_SIGNOFF_RE.test(c.trimmed));
  if (body.length === 0) return [];
  const last = body[body.length - 1];
  // a finished chapter ends on terminal/closing punctuation (aligned with story_hook_core TERMINAL); otherwise it was cut off.
  if (/[。！？!?…~～—”"’'』」）)】］\]}》.]$/.test(last.trimmed)) return [];
  return [{
    line: last.lineNo,
    column: last.trimmed.length,
    type: 'truncated',
    severity: 'blocking',
    message: '疑似截断：正文末尾未以句末/收尾标点结束，可能被模型中途切断；补完结尾或重写收尾。',
    excerpt: compact(last.trimmed.slice(-24)),
  }];
}

function findMarkdownLeak(content) {
  const findings = [];
  for (const { trimmed, lineNo } of content) {
    if (!isContent(trimmed)) continue;
    if (/^[*-\s]+$/.test(trimmed)) continue;
    const m = MARKDOWN_BOLD_RE.exec(trimmed);
    if (m) {
      findings.push({
        line: lineNo,
        column: m.index + 1,
        type: 'markdown-leak',
        severity: 'blocking',
        message: 'Markdown 粗体残留：正文非标题行出现 **...** 装饰符，去掉星号回归纯文本正文。',
        excerpt: compact(trimmed.slice(Math.max(0, m.index - 4), m.index + m[0].length + 8)),
      });
    }
  }
  return findings;
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

function findCensoredPinyin(content) {
  const findings = [];
  for (const { trimmed, lineNo } of content) {
    if (!isContent(trimmed)) continue;
    const m = CENSORED_PINYIN_RE.exec(trimmed);
    if (m) {
      findings.push({
        line: lineNo,
        column: m.index + 1,
        type: 'censored-pinyin-leak',
        severity: 'review_required',
        message: `审查拼音泄漏：「${m[0]}」疑似规避审查的拼音替代残片，改为正常中文表达或自然动作/意象替代。`,
        excerpt: compact(trimmed.slice(Math.max(0, m.index - 6), m.index + m[0].length + 12)),
      });
    }
  }
  return findings;
}

function findAuthorMetaHeader(content) {
  const findings = [];
  let scannedChars = 0;
  for (const { trimmed, lineNo } of content) {
    if (!isContent(trimmed)) continue;
    if (scannedChars >= AUTHOR_META_HEADER_MAX_CHARS) break;
    const m = AUTHOR_META_HEADER_RE.exec(trimmed);
    if (m) {
      findings.push({
        line: lineNo,
        column: m.index + 1,
        type: 'author-meta-header',
        severity: 'review_required',
        message: `开篇作者元声明泄漏：「${m[0]}」属于作者碎碎念/脑子寄存处/求好评头注，不应留在正文首 500 字内；移至简介或作话，正文直接进场景。`,
        excerpt: compact(trimmed.slice(Math.max(0, m.index - 6), m.index + m[0].length + 16)),
      });
    }
    scannedChars += visibleLength(trimmed);
  }
  return findings;
}

function isChapterHeading(trimmed, lineNo) {
  if (!CHAPTER_HEADING_PREFIX_RE.test(trimmed)) return false;
  if (trimmed.length > 60) return false;
  const rest = trimmed.replace(CHAPTER_HEADING_PREFIX_RE, '');
  if (rest === '') return true;
  if (/^[\s_：:——\-]+/.test(rest)) {
    const title = rest.replace(/^[\s_：:——\-]+/, '');
    if (!title) return true;
    // 文件首两行的纯文本章标题行（如「第37章 你们有的我都要。但是钱只能…」「第89章 难道这是。。夫妻相？」）允许标点
    if (lineNo <= 2) return true;
    const body = title.replace(/[。！？!?）)\s]+$/, '');
    return !/[。；;]/.test(body);
  }
  // 无空格紧贴章标题（如「第304章传授手艺」「第275章夫君在…？（29）」）：
  // 排除正文叙述常用起头词与多句结构。
  if (/^[里中写提讲说开末尾前后时已就才都也还有没]/.test(rest)) return false;
  const body = rest.replace(/[。！？!?）)\s\d(（]+$/, '');
  if (/[。；;]/.test(body)) return false;
  if (lineNo > 2 && /[，,]/.test(body)) return false;
  return true;
}

function findMetaLeak(content) {
  const findings = [];
  const fullBody = content.filter((c) => isContent(c.trimmed)).map((c) => c.trimmed).join('\n');
  const hasBookWorldCtx = BOOK_WORLD_CTX_RE.test(fullBody);
  const tier2Global = new RegExp(META_TIER2_RE.source, 'g');
  for (const { trimmed, lineNo } of content) {
    if (!isContent(trimmed)) continue;
    // 独立成行的章/节标题（含首行、无空格紧贴与句号结尾标题，无 ## 前缀时也算）属结构标记，不算正文泄漏
    if (isChapterHeading(trimmed, lineNo)) continue;
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
    // 弹幕/心声/系统播报【…】内讨论「主角/男主/女主/反派」属穿书/脑洞常态，跳过 tier2 扫描
    const outsideDanmu = trimmed.replace(/【[^】\n]*】/g, (seg) => ' '.repeat(seg.length));
    tier2Global.lastIndex = 0;
    let tier2Hit = null;
    while ((m = tier2Global.exec(outsideDanmu)) !== null) {
      const word = m[0];
      if (hasBookWorldCtx && BOOK_WORLD_EXEMPT_META_RE.test(word)) continue;
      // 对话引号内与日常现实语境（今晚的主角/热搜稿换个主角/短剧反派女二）的角色称谓属自然中文，豁免。
      if (word === '主角' || word === '反派' || word === '男主' || word === '女主') {
        if (outsideQuotes[m.index] === ' ') continue;
        const win = trimmed.slice(Math.max(0, m.index - 12), m.index + word.length + 10);
        if (REAL_WORLD_ROLE_CTX_RE.test(win)) continue;
      }
      tier2Hit = m;
      break;
    }
    if (tier2Hit) {
      findings.push({
        line: lineNo,
        column: tier2Hit.index + 1,
        type: 'meta-leak',
        severity: 'advisory',
        message: `元信息泄漏：「${tier2Hit[0]}」疑似工程/章节结构词混入正文；改成角色当下可感知的事件锚点或相对时间。例外：角色在故事内真实阅读/讨论「第X章」、真身为作者/读者、穿书/快穿或故事内系统/界面用语。`,
        excerpt: compact(trimmed.slice(Math.max(0, tier2Hit.index - 6), tier2Hit.index + 18)),
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
