#!/usr/bin/env node
/**
 * Deterministic 细纲 structural verifier for story-long-write (synced to story-import).
 *
 * Usage:
 *   node scripts/check-outline-contract.js --json [--strict] <细纲路径...>
 *   node scripts/check-outline-contract.js --json [--strict] --project <书目录> --chapter N
 * Exit: 0 = pass (no hard failures; soft warnings allowed unless --strict),
 *       1 = blocking contract failures (or soft warnings under --strict),
 *       2 = invalid invocation.
 */

'use strict'

const fs = require('fs')
const path = require('path')
const {
  METRIC: CALIBER,
  parseTargetField: parseWordcountTarget,
  parseRangeField: parseWordcountRange,
  parseMetricField,
} = require('./wordcount_core.js')

const FIELD_NAMES = [
  ['核心事件'], ['字数目标'], ['属于哪段剧情', '单元ID/位置'], ['目标情绪'],
  ['主角目标/关键选择'], ['章首钩子'], ['爽点'],
]
const FIELDS = FIELD_NAMES.map((names) => names[0])
const SOFT_FIELD_NAMES = [
  ['核心事件'], ['属于哪段剧情', '单元ID/位置'], ['章首钩子'], ['爽点'],
]
const SOFT_FIELDS = SOFT_FIELD_NAMES.map((names) => names[0])
const SUBSECTION_NAMES = [['这章怎么走', '内容概括'], ['情节安排'], ['人物关系和出场顺序'], ['情节细化']]
const SUBSECTIONS = SUBSECTION_NAMES.map((names) => names[0])
const FIVE_ACT = ['起因', '发展', '转折', '高潮', '结尾']
const PLOT_HEADER_FIRST = /^(?:#|序号)$/
const INTENT_FIELDS = ['目标情绪', '主角目标/关键选择']
const REF_DIR_PREFIX = /^(?:设定|大纲|追踪|正文|读者笔记|对标)\//
const TEMPLATE_REFERENCES = ['references/flow-outline.md', 'references/outline-reverse-rules.md']
  .filter((rel) => fs.existsSync(path.join(__dirname, '..', rel)))

const parseWordcountCaliber = (text) => parseMetricField(text).ok

function fieldPattern(name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${escaped}\\*{0,2}\\s*[：:]`, 'm')
}

function readUtf8(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function makeCheck(id, ok, file, evidence, expected, repair, severity = 'blocking') {
  return { id, ok, severity, file, evidence, expected, references: TEMPLATE_REFERENCES, repair }
}

function parseTableRow(line) {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null
  return trimmed.slice(1, -1).split('|').map((cell) => cell.replace(/\*\*/g, '').replace(/`/g, '').trim())
}

function resolveBookRoot(file, projectRoot) {
  if (projectRoot) return path.resolve(projectRoot)
  const parent = path.dirname(path.resolve(file))
  return path.basename(parent) === '大纲' ? path.dirname(parent) : null
}

function hasExistingChapterProse(file, projectRoot) {
  const bookRoot = resolveBookRoot(file, projectRoot)
  const chMatch = path.basename(file).match(/^细纲_第0*(\d+)章.*\.md$/)
  if (!bookRoot || !chMatch) return false
  const wanted = Number(chMatch[1])
  if (!Number.isInteger(wanted) || wanted < 1) return false
  const proseDir = path.join(bookRoot, '正文')
  try {
    return fs.readdirSync(proseDir).some((entry) => {
      if (entry.includes('_原稿_')) return false
      const match = entry.match(/^第0*(\d+)章(?:[_\- 　].*)?\.md$/)
      if (!match || Number(match[1]) !== wanted) return false
      try { return fs.statSync(path.join(proseDir, entry)).isFile() } catch { return false }
    })
  } catch {
    return false
  }
}

function checkSettingRefs(text, name, file, projectRoot) {
  const bookRoot = resolveBookRoot(file, projectRoot)
  if (!bookRoot) {
    return makeCheck('outline.setting-refs-exist', true, name, '未能定位书目录，跳过', '细纲引用的项目内文件真实存在', '无需修复。', 'advisory')
  }
  const refs = new Set()
  const pattern = /`([^`\n]+?\.md)[^`\n]*`/g
  let match
  while ((match = pattern.exec(text)) !== null) {
    const token = match[1].trim().replace(/\\/g, '/')
    if (token.includes('{') || token.includes('}')) continue
    if (REF_DIR_PREFIX.test(token) || /^\.{1,2}\//.test(token)) refs.add(token)
  }
  const missing = []
  for (const token of refs) {
    const base = /^\.{1,2}\//.test(token) ? path.dirname(path.resolve(file)) : bookRoot
    try { if (!fs.statSync(path.resolve(base, token)).isFile()) missing.push(token) } catch { missing.push(token) }
  }
  return makeCheck(
    'outline.setting-refs-exist', missing.length === 0, name,
    missing.length ? `引用的路径不是可用文件：${missing.join('、')}` : `${refs.size} 处项目内引用全部存在`,
    '细纲引用的每个项目内 .md 文件都真实存在',
    '复核引用路径：若是已定设定，先按新增物三级补建或修正路径；若仅是暂定构思可先保留。',
    'advisory'
  )
}

function extractChapterSlice(text, chapter) {
  const lines = text.split(/\r?\n/)
  const targetRe = new RegExp(`^#{2,3}\\s*第\\s*0*${chapter}\\s*章(?:[：:\\s]|$)`)
  const anyChapterRe = /^#{2,3}\s*第\s*\d+\s*章(?:[：:\s]|$)/
  const start = lines.findIndex((line) => targetRe.test(line))
  if (start === -1) return null
  let end = lines.length
  for (let i = start + 1; i < lines.length; i += 1) {
    if (anyChapterRe.test(lines[i])) {
      end = i
      break
    }
  }
  return lines.slice(start, end).join('\n')
}

function verify(file, projectRoot = null, options = {}) {
  const strict = Boolean(options && options.strict)
  const chapter = options && options.chapter ? Number(options.chapter) : null
  const name = path.basename(file)
  const read = readUtf8(file)
  const checks = [makeCheck(
    'outline.readable', read.ok, name,
    read.ok ? '文件存在且非空' : (read.error || '文件为空'),
    '细纲文件存在且非空', '只补建缺失的细纲文件，不改动同批其他章。',
    'blocking'
  )]
  if (!read.ok) return report(file, checks, {}, { strict })
  let text = read.text
  if (chapter && options.fromRangeFile) {
    const slice = extractChapterSlice(read.text, chapter)
    if (slice === null) {
      checks.push(makeCheck(
        'outline.chapter-slice-found', false, name,
        `范围细纲 ${name} 中未找到第 ${chapter} 章小节`,
        `范围细纲须包含「## 第 ${chapter} 章」或「### 第 ${chapter} 章」小节`,
        `在 ${name} 中补齐第 ${chapter} 章小节，或改建单章文件 细纲_第${String(chapter).padStart(3, '0')}章.md。`,
        'blocking'
      ))
      return report(file, checks, {}, { strict })
    }
    text = slice
  }

  const missingSoftFields = SOFT_FIELD_NAMES.filter((names) => !names.some((f) => fieldPattern(f).test(text))).map((names) => names[0])
  checks.push(makeCheck(
    'outline.required-fields', missingSoftFields.length === 0, name,
    missingSoftFields.length ? `缺可选/常规字段：${missingSoftFields.join('、')}` : `${SOFT_FIELDS.length} 个常规字段齐全`,
    `建议按权威模板补齐常规字段：${SOFT_FIELDS.join('、')}；值未知时可写 [待补充]`,
    '复核缺漏字段：需要时补齐或写 [待补充]；若本章结构刻意省略，确认后可保留。',
    'advisory'
  ))

  const missingIntent = []
  const hollowIntent = []
  for (const field of INTENT_FIELDS) {
    const match = text.match(new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${field.replace('/', '\\/')}\\*{0,2}\\s*[：:]\\s*(.*)$`, 'm'))
    if (!match) {
      missingIntent.push(field)
    } else if (match[1].replace(/\[待补充\]|\{[^}]*\}/g, '').replace(/[\s、，,。;；]/g, '').length === 0) {
      hollowIntent.push(field)
    }
  }
  const intentProblems = []
  if (missingIntent.length) intentProblems.push(`缺核心意图字段：${missingIntent.join('、')}`)
  if (hollowIntent.length) intentProblems.push(`只有占位符，没有实际内容：${hollowIntent.join('、')}`)
  checks.push(makeCheck(
    'outline.intent-fields-substantive', intentProblems.length === 0, name,
    intentProblems.length ? intentProblems.join('；') : '目标情绪与主角目标/关键选择都写了实际内容',
    '目标情绪写清前状态→后状态；主角目标/关键选择写清本章要什么、必须做出的判断。这两项必填且不接受 [待补充]',
    '补齐并把这两个字段替换成本章的实际情绪变化与实际取舍；其余字段不动。',
    'blocking'
  ))

  const missingSubs = SUBSECTION_NAMES
    .filter((names) => !names.some((sub) => new RegExp(`^#{3,4}\\s*${sub}`, 'm').test(text)))
    .map((names) => names[0])
  checks.push(makeCheck(
    'outline.subsections', missingSubs.length === 0, name,
    missingSubs.length ? `缺小节：${missingSubs.join('、')}` : '四个小节齐全',
    '建议包含 这章怎么走 / 情节安排 / 人物关系和出场顺序 / 情节细化 四个小节（旧名「内容概括」照认）',
    '复核是否遗漏了必要信息；若仅是自定义小节标题且信息完整，确认后可保留。',
    'advisory'
  ))

  const missingActs = FIVE_ACT.filter((act) => !fieldPattern(act).test(text))
  checks.push(makeCheck(
    'outline.five-act', missingActs.length === 0, name,
    missingActs.length ? `「这章怎么走」缺：${missingActs.join('、')}` : '「这章怎么走」五行齐全',
    '建议在「这章怎么走」写全 起因 / 发展 / 转折 / 高潮 / 结尾',
    '复核章节推进是否完整；过渡章或日常章确不需要严格五段时可保留。',
    'advisory'
  ))

  let header = null
  for (const line of text.split(/\r?\n/)) {
    const cells = parseTableRow(line)
    if (cells && cells.length >= 3 && cells.length <= 5 && PLOT_HEADER_FIRST.test(cells[0])) {
      header = cells
      break
    }
  }
  const extraColumnsOk = (extra) => {
    const kinds = extra.map((cell) => (/分辨率/.test(cell) ? 'res' : (/执行边界|分寸/.test(cell) ? 'bound' : null)))
    return !kinds.includes(null) && new Set(kinds).size === kinds.length && (!kinds.includes('bound') || kinds[kinds.length - 1] === 'bound')
  }
  const headerOk = Boolean(header) && /功能标签|作用/.test(header[2]) && extraColumnsOk(header.slice(3))
  checks.push(makeCheck(
    'outline.plotpoint-table', headerOk, name,
    header ? `表头：${header.join(' | ')}` : '未找到 | # | 情节点 | 作用 | 表头',
    '情节细化建议使用表格：# / 情节点（谁做了什么） / 作用；需要时可加「分辨率」列，表末可加「分寸」列',
    '复核情节点是否清晰可执行；需要规范时改成三列表，若现有写法已够清晰可保留。',
    'advisory'
  ))

  checks.push(checkSettingRefs(text, name, file, projectRoot))

  const hasProse = hasExistingChapterProse(file, projectRoot)
  const [minTarget, maxTarget] = hasProse ? [1, 500000] : [500, 20000]
  const targetParse = parseWordcountTarget(text)
  const rangeParse = parseWordcountRange(text)
  const target = targetParse.value
  const caliberOk = parseWordcountCaliber(text)
  const targetLabel = {
    ok: target, missing: '未识别',
    invalid: `写法认不出（${targetParse.raw.join('、')}）`,
    conflict: `多个不同的值（${targetParse.raw.join('、')}）`,
  }[targetParse.status]
  const rangeLabel = rangeParse.status === 'invalid'
    ? `；字数范围写法不对（${rangeParse.raw.join('、')}）`
    : (rangeParse.value ? `；字数范围：${rangeParse.value.min}-${rangeParse.value.max}` : '')
  checks.push(makeCheck(
    'outline.wordcount-target',
    targetParse.status === 'ok' && target >= minTarget && target <= maxTarget && caliberOk && rangeParse.status !== 'invalid',
    name,
    `字数目标：${targetLabel}；字数口径（可不写，写了须是 ${CALIBER}）：${caliberOk}${rangeLabel}`,
    `字数目标为 ${minTarget}-${maxTarget} 的正整数；字数口径不用写，写了只能是 ${CALIBER}；作者给了上下限时另写一行「字数范围：2000-2600」`,
    '只补字数目标、字数范围，或删掉写错的字数口径行，不调整情节安排。',
    'blocking'
  ))

  return report(file, checks, {
    wordcount: { target, target_status: targetParse.status, range: rangeParse.value, range_status: rangeParse.status },
  }, { strict })
}

function toScopeItem({ id, severity, file, evidence, expected, references, repair }) {
  return { id, severity, file, evidence, expected, references, repair }
}

function report(file, checks, extra = {}, options = {}) {
  const strict = Boolean(options && options.strict)
  const hardFailures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const softWarnings = checks.filter((check) => !check.ok && check.severity === 'advisory')
  const findings = [...hardFailures, ...softWarnings]
  const failures = strict ? findings : hardFailures
  return {
    schema_version: 1,
    verifier: 'story-long-write.outline-contract',
    file: path.resolve(file),
    strict,
    ok: failures.length === 0,
    status: failures.length > 0 ? 'fail' : (softWarnings.length > 0 ? 'warn' : 'pass'),
    ...extra,
    checks,
    hard_failures: hardFailures,
    soft_warnings: softWarnings,
    findings,
    failures,
    advisories: softWarnings,
    repair_scope: failures.map(toScopeItem),
    review_scope: softWarnings.map(toScopeItem),
  }
}

function resolveChapter(project, chapter) {
  const dir = path.join(project, '大纲')
  let entries
  try { entries = fs.readdirSync(dir) } catch (error) { return { error: `无法读取 ${dir}：${error.message}` } }
  const wanted = Number(chapter)
  const hit = entries.find((entry) => {
    const match = entry.match(/^细纲_第0*(\d+)章.*\.md$/)
    return match && Number(match[1]) === wanted
  })
  if (hit) return { file: path.join(dir, hit), fromRangeFile: false }
  const rangeHit = entries.find((entry) => {
    const match = entry.match(/^细纲_第0*(\d+)[-–—~～至到]第?0*(\d+)章.*\.md$/)
    if (!match) return false
    const start = Number(match[1])
    const end = Number(match[2])
    return Number.isInteger(start) && Number.isInteger(end) && start <= wanted && wanted <= end
  })
  return rangeHit
    ? { file: path.join(dir, rangeHit), fromRangeFile: true }
    : { error: `${dir} 下没有第 ${wanted} 章细纲` }
}

function parseArgs(argv) {
  const files = []
  let project = null
  let chapter = null
  let strict = false
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (arg === '--json') continue
    if (arg === '--strict') { strict = true; continue }
    if (arg === '--project' || arg === '--chapter') {
      if (index + 1 >= argv.length || argv[index + 1].startsWith('--')) return null
      if (arg === '--project') project = argv[++index]
      else chapter = argv[++index]
      continue
    }
    if (arg.startsWith('--')) return null
    files.push(arg)
  }
  if (project || chapter) {
    if (!project || !chapter || files.length || !/^\d+$/.test(chapter)) return null
    return { project, chapter, strict }
  }
  return files.length ? { files, strict } : null
}

const USAGE = '用法: node scripts/check-outline-contract.js --json [--strict] <细纲路径...> | --json [--strict] --project <书目录> --chapter N\n'

function main(argv) {
  if (argv.includes('--help') || argv.includes('-h')) {
    process.stdout.write(USAGE)
    return 0
  }
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write(USAGE)
    return 2
  }
  let targets = parsed.files
  let fromRangeFile = false
  if (!targets) {
    const resolved = resolveChapter(parsed.project, parsed.chapter)
    if (resolved.error) { process.stderr.write(`${resolved.error}\n`); return 2 }
    targets = [resolved.file]
    fromRangeFile = Boolean(resolved.fromRangeFile)
  }
  const reports = targets.map((file) =>
    verify(file, parsed.project || null, { strict: parsed.strict, chapter: parsed.chapter, fromRangeFile })
  )
  process.stdout.write(`${JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2)}\n`)
  return reports.every((entry) => entry.ok) ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { verify, parseWordcountTarget, parseWordcountRange, FIELDS, FIELD_NAMES, SOFT_FIELDS, SOFT_FIELD_NAMES, SUBSECTIONS, FIVE_ACT }
