#!/usr/bin/env node
/**
 * Deterministic 细纲 structural verifier for story-long-write (synced to story-import).
 *
 * Usage:
 *   node scripts/check-outline-contract.js --json <细纲路径...>
 *   node scripts/check-outline-contract.js --json --project <书目录> --chapter N
 * Exit: 0 = pass, 1 = blocking contract failures, 2 = invalid invocation.
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
const SUBSECTION_NAMES = [['这章怎么走', '内容概括'], ['情节安排'], ['人物关系和出场顺序'], ['情节细化']]
const SUBSECTIONS = SUBSECTION_NAMES.map((names) => names[0])
const FIVE_ACT = ['起因', '发展', '转折', '高潮', '结尾']
const PLOT_HEADER_FIRST = /^(?:#|序号)$/
const INTENT_FIELDS = ['目标情绪', '主角目标/关键选择']
const REF_DIR_PREFIX = /^(?:设定|大纲|追踪|正文|读者笔记|对标)\//
const TEMPLATE_REFERENCES = ['references/outline-template.md', 'references/outline-reverse-rules.md']
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
    return makeCheck('outline.setting-refs-exist', true, name, '未能定位书目录，跳过', '细纲引用的项目内文件真实存在', '无需修复。')
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
    '修正引用路径，或先按新增物三级把缺的设定落档再引用。'
  )
}

function verify(file, projectRoot = null) {
  const name = path.basename(file)
  const read = readUtf8(file)
  const checks = [makeCheck(
    'outline.readable', read.ok, name,
    read.ok ? '文件存在且非空' : (read.error || '文件为空'),
    '细纲文件存在且非空', '只补建缺失的细纲文件，不改动同批其他章。'
  )]
  if (!read.ok) return report(file, checks)
  const text = read.text

  const missingFields = FIELD_NAMES.filter((names) => !names.some((f) => fieldPattern(f).test(text))).map((names) => names[0])
  checks.push(makeCheck(
    'outline.required-fields', missingFields.length === 0, name,
    missingFields.length ? `缺字段：${missingFields.join('、')}` : `${FIELDS.length} 个字段齐全`,
    `按权威模板列出全部字段：${FIELDS.join('、')}；值未知时写 [待补充]`,
    '只补报告里缺的字段行；确实还定不下来的写 [待补充]，不为补字段新增副线或人物关系。'
  ))

  const hollow = INTENT_FIELDS.filter((field) => {
    const match = text.match(new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${field.replace('/', '\\/')}\\*{0,2}\\s*[：:]\\s*(.*)$`, 'm'))
    if (!match) return false
    return match[1].replace(/\[待补充\]/g, '').replace(/[\s、，,。;；]/g, '').length === 0
  })
  checks.push(makeCheck(
    'outline.intent-fields-substantive', hollow.length === 0, name,
    hollow.length ? `只有占位符，没有实际内容：${hollow.join('、')}` : '目标情绪与主角目标/关键选择都写了实际内容',
    '目标情绪写清前状态→后状态；主角目标/关键选择写清本章要什么、必须做出的判断。这两项不接受 [待补充]',
    '只把这两个字段替换成本章的实际情绪变化与实际取舍；其余字段不动。'
  ))

  const missingSubs = SUBSECTION_NAMES
    .filter((names) => !names.some((sub) => new RegExp(`^#{3,4}\\s*${sub}`, 'm').test(text)))
    .map((names) => names[0])
  checks.push(makeCheck(
    'outline.subsections', missingSubs.length === 0, name,
    missingSubs.length ? `缺小节：${missingSubs.join('、')}` : '四个小节齐全',
    '包含 这章怎么走 / 情节安排 / 人物关系和出场顺序 / 情节细化 四个小节（旧名「内容概括」照认）',
    '只补缺失的小节标题及其条目，不重写已成立的内容。'
  ))

  const missingActs = FIVE_ACT.filter((act) => !fieldPattern(act).test(text))
  checks.push(makeCheck(
    'outline.five-act', missingActs.length === 0, name,
    missingActs.length ? `「这章怎么走」缺：${missingActs.join('、')}` : '「这章怎么走」五行齐全',
    '「这章怎么走」写全 起因 / 发展 / 转折 / 高潮 / 结尾',
    '只补缺的那一段，不改其余四段。'
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
    '情节细化使用表格：# / 情节点（谁做了什么） / 作用；需要时可加「分辨率」列，表末可加「分寸」列',
    '只把情节点序列改成这张表，逐点补作用；不增删情节点本身。'
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
    '只补字数目标、字数范围，或删掉写错的字数口径行，不调整情节安排。'
  ))

  return report(file, checks, {
    wordcount: { target, target_status: targetParse.status, range: rangeParse.value, range_status: rangeParse.status },
  })
}

function report(file, checks, extra = {}) {
  const failures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const advisories = checks.filter((check) => !check.ok && check.severity === 'advisory')
  return {
    schema_version: 1,
    verifier: 'story-long-write.outline-contract',
    file: path.resolve(file),
    ok: failures.length === 0,
    ...extra,
    checks,
    failures,
    advisories,
    repair_scope: failures.map(({ id, file: f, evidence, expected, references, repair }) => ({
      id, file: f, evidence, expected, references, repair,
    })),
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
  return hit ? { file: path.join(dir, hit) } : { error: `${dir} 下没有第 ${wanted} 章细纲` }
}

function parseArgs(argv) {
  const files = []
  let project = null
  let chapter = null
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (arg === '--json') continue
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
    return { project, chapter }
  }
  return files.length ? { files } : null
}

function main(argv) {
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write('用法: node scripts/check-outline-contract.js --json <细纲路径...> | --json --project <书目录> --chapter N\n')
    return 2
  }
  let targets = parsed.files
  if (!targets) {
    const resolved = resolveChapter(parsed.project, parsed.chapter)
    if (resolved.error) { process.stderr.write(`${resolved.error}\n`); return 2 }
    targets = [resolved.file]
  }
  const reports = targets.map((file) => verify(file, parsed.project || null))
  process.stdout.write(`${JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2)}\n`)
  return reports.every((entry) => entry.ok) ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { verify, parseWordcountTarget, parseWordcountRange, FIELDS, FIELD_NAMES, SUBSECTIONS, FIVE_ACT }
