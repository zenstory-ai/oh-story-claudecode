#!/usr/bin/env node
/**
 * Deterministic 细纲 structural verifier for story-long-write.
 *
 * Usage:
 *   node scripts/check-outline-contract.js --json <细纲路径...>
 *   node scripts/check-outline-contract.js --json --project <书目录> --chapter N
 * Exit: 0 = pass, 1 = blocking contract failures, 2 = invalid invocation.
 *
 * Scope is structural only: it decides whether the blueprint carries the fields,
 * subsections and table shape the authoritative template names. It never judges
 * whether a value is good. The contract itself sets this granularity —
 * artifact-protocols.md 要求未知字段写 `[待补充]`，所以字段必须在场，值可以未知。
 */

'use strict'

const fs = require('fs')
const path = require('path')

// 权威模板：references/outline-template.md 的细纲模板（story-import 的副本对照 outline-reverse-rules.md）
// 必填只留有证据或事故撑腰的核心字段；阶段位置、松紧、结构公式、本章标价、闭环状态、
// 可以放开写的地方（旧名写手自由区）、有没有硬伤、镜头准入、信息差触发点与「分辨率」「分寸」列是可选的阅读体验字段——
// 写了照样消费，没写不拦（#383 隔离实验：只补目标情绪与主角目标就复现了补满全部字段的收益）。
// 0.10 起字段改白话：新名在前，旧名照认（老书细纲不必改）。「字数口径」不再必填：没写按默认口径。
// 「这章不能说破」（旧名本章禁止提前释放）可选：只有本章确有一件具体的事要压住时写一行，写了才查长度。
const FIELD_NAMES = [
  ['核心事件'], ['字数目标'], ['属于哪段剧情', '单元ID/位置'], ['目标情绪'],
  ['主角目标/关键选择'], ['章首钩子'], ['爽点'],
]
const FIELDS = FIELD_NAMES.map((names) => names[0])
const RELEASE_FIELDS = ['这章不能说破', '本章禁止提前释放']
const RELEASE_MAX_ITEMS = 3
// 小节名新名在前，旧名照认：「这章怎么走」旧叫「内容概括（五段式）」。
const SUBSECTION_NAMES = [['这章怎么走', '内容概括'], ['情节安排'], ['人物关系和出场顺序'], ['情节细化']]
const SUBSECTIONS = SUBSECTION_NAMES.map((names) => names[0])
const FIVE_ACT = ['起因', '发展', '转折', '高潮', '结尾']
const PLOT_HEADER_FIRST = /^(?:#|序号)$/
// 这两个字段实测直接影响正文质量，必须有实际内容
const INTENT_FIELDS = ['目标情绪', '主角目标/关键选择']
const CALIBER = 'visible_chars_v1'
// 可选字段「有没有硬伤」只收三档；值未知可写 [待补充]。旧名「契约风险」「风险等级」和旧档名照认，回报统一用新档名。
const CONTRACT_RISK_LEVELS = ['没问题', '要补', '有硬伤']
const LEGACY_RISK_LEVELS = { 契约安全: '没问题', 需补强: '要补', 契约破坏: '有硬伤' }

// 「字数目标」「字数范围」「字数口径」的写法语法与 wordcount_core.py 逐字同构（scripts/test-storyctl.py 双跑同一批写法），
// 细纲验收通过的写法，storyctl chapter check 不能再拒。值里一个数字都没有的目标/范围行是说明文字，不参与取值。
const NUMBER = '([1-9][0-9]{0,2}(?:[,，][0-9]{3})+|[1-9][0-9]*)'
const NOTE = '(?:[（(][^（）()]*[）)])?'
const TARGET_VALUE = new RegExp(`^(?:约|大约)?[ \\t]*${NUMBER}[ \\t]*字?(?:左右)?[ \\t]*${NOTE}$`)
const RANGE_VALUE = new RegExp(`^${NUMBER}[ \\t]*字?[ \\t]*(?:-|~|～|—|–|－|至|到)[ \\t]*${NUMBER}[ \\t]*字?[ \\t]*${NOTE}$`)
const METRIC_VALUE = new RegExp(`^([A-Za-z0-9_-]+)[ \\t]*${NOTE}$`)
const HAS_DIGIT = /[0-9０-９]/

function fieldValues(text, label) {
  const pattern = new RegExp(`^[ \\t>]*(?:[-*+][ \\t]*)?(?:\\*\\*)?${label}(?:\\*\\*)?[ \\t]*[:：][ \\t]*(.*?)[ \\t]*$`, 'gm')
  const values = []
  let match
  const normalized = text.replace(/\r\n?/g, '\n').replace(/^\uFEFF/, '')
  while ((match = pattern.exec(normalized)) !== null) values.push(match[1].replace(/\*\*/g, '').trim())
  return values
}

const numericFieldValues = (text, label) => fieldValues(text, label).filter((value) => HAS_DIGIT.test(value))
const toNumber = (raw) => Number(raw.replace(/[,，]/g, ''))

function parseWordcountTarget(text) {
  const raw = numericFieldValues(text, '字数目标')
  if (!raw.length) return { status: 'missing', value: null, raw }
  const matches = raw.map((value) => value.match(TARGET_VALUE))
  if (!matches.every(Boolean)) return { status: 'invalid', value: null, raw }
  const values = [...new Set(matches.map((match) => toNumber(match[1])))]
  if (values.length !== 1) return { status: 'conflict', value: null, raw }
  return { status: 'ok', value: values[0], raw }
}

function parseWordcountRange(text) {
  const raw = numericFieldValues(text, '字数范围')
  if (!raw.length) return { status: 'missing', value: null, raw }
  const matches = raw.map((value) => value.match(RANGE_VALUE))
  if (!matches.every(Boolean)) return { status: 'invalid', value: null, raw }
  const pairs = [...new Set(matches.map((match) => `${toNumber(match[1])}-${toNumber(match[2])}`))]
  if (pairs.length !== 1) return { status: 'invalid', value: null, raw }
  const [min, max] = pairs[0].split('-').map(Number)
  if (min > max) return { status: 'invalid', value: null, raw }
  return { status: 'ok', value: { min, max }, raw }
}

// 「字数口径」可不写（没写按默认口径）；写了就必须每行都是 visible_chars_v1。
function parseWordcountCaliber(text) {
  const raw = fieldValues(text, '字数口径')
  if (!raw.length) return true
  const matches = raw.map((value) => value.match(METRIC_VALUE))
  return matches.every(Boolean) && new Set(matches.map((match) => match[1])).size === 1 && matches[0][1] === CALIBER
}

function parseContractRisk(text) {
  let raw = []
  for (const label of ['有没有硬伤', '契约风险', '风险等级']) {
    raw = fieldValues(text, label)
    if (raw.length) break
  }
  if (!raw.length) return null
  const value = raw[raw.length - 1].replace(/`/g, '')
  if (/^\[待补充\]$/.test(value)) return { status: 'unknown', level: null, detail: '', raw: value }
  const written = [...CONTRACT_RISK_LEVELS, ...Object.keys(LEGACY_RISK_LEVELS)].find((name) => value.startsWith(name))
  if (!written) return { status: 'invalid', level: null, detail: '', raw: value }
  const level = LEGACY_RISK_LEVELS[written] || written
  const detail = value.slice(written.length).replace(/^[\s；;，,。：:—\-（(]+/, '').replace(/[）)]$/, '').trim()
  return { status: 'ok', level, detail, raw: value }
}

function fieldPattern(name) {
  // 允许 -/*/+ 项目符号、可选 ** 加粗、全角或半角冒号
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${escaped}\\*{0,2}\\s*[：:]`, 'm')
}

function readUtf8(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^﻿/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

// 回报里的模板出处只列本 skill 带着的文件：导入的副本没有 outline-template.md，细纲写法在 outline-reverse-rules.md
const TEMPLATE_REFERENCES = ['references/outline-template.md', 'references/outline-reverse-rules.md']
  .filter((rel) => fs.existsSync(path.join(__dirname, '..', rel)))

function makeCheck(id, ok, file, evidence, expected, repair, severity = 'blocking') {
  return {
    id,
    ok,
    severity,
    file,
    evidence,
    expected,
    references: TEMPLATE_REFERENCES,
    repair,
  }
}

function parseTableRow(line) {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null
  return trimmed.slice(1, -1).split('|').map((cell) => cell.replace(/\*\*/g, '').replace(/`/g, '').trim())
}

function resolveBookRoot(file, projectRoot) {
  if (projectRoot) return path.resolve(projectRoot)
  const parent = path.dirname(path.resolve(file))
  if (path.basename(parent) === '大纲') return path.dirname(parent)
  return null
}

// 项目引用须写目录路径；裸文件名可能指向 skill reference，不猜测其归属。
const REF_DIR_PREFIX = /^(?:设定|大纲|追踪|正文|读者笔记|对标)\//

function checkSettingRefs(text, name, file, projectRoot) {
  const bookRoot = resolveBookRoot(file, projectRoot)
  if (!bookRoot) {
    return makeCheck('outline.setting-refs-exist', true, name, '未能定位书目录（细纲不在 大纲/ 下且未传 --project），跳过', '细纲引用的项目内文件真实存在', '无需修复。')
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
    try {
      if (!fs.statSync(path.resolve(base, token)).isFile()) missing.push(token)
    } catch { missing.push(token) }
  }
  return makeCheck(
    'outline.setting-refs-exist',
    missing.length === 0,
    name,
    missing.length ? `引用的路径不是可用文件：${missing.join('、')}` : `${refs.size} 处项目内引用全部存在`,
    '细纲引用的每个项目内 .md 文件都真实存在——不许把槽位指向查无实据的权威文件',
    '修正引用路径；或按新增物三级先把缺的设定落档（补上并记下的直接补并登记，要问作者的写进排纲笔记「写纲前查缺」的提案），再在细纲引用。'
  )
}

function verify(file, projectRoot = null) {
  const name = path.basename(file)
  const read = readUtf8(file)
  const checks = []

  checks.push(makeCheck(
    'outline.readable',
    read.ok,
    name,
    read.ok ? '文件存在且非空' : (read.error || '文件为空'),
    '细纲文件存在且非空',
    '只补建缺失的细纲文件，不改动同批其他章。'
  ))
  if (!read.ok) return report(file, checks)
  const text = read.text

  const missingFields = FIELD_NAMES
    .filter((names) => !names.some((field) => fieldPattern(field).test(text)))
    .map((names) => names[0])
  checks.push(makeCheck(
    'outline.required-fields',
    missingFields.length === 0,
    name,
    missingFields.length ? `缺字段：${missingFields.join('、')}` : `${FIELDS.length} 个字段齐全`,
    `按权威模板列出全部字段：${FIELDS.join('、')}；值未知时写 [待补充]，不杜撰剧情`,
    '只补报告里缺的字段行；确实还定不下来的写 [待补充]，不为补字段新增副线或人物关系。'
  ))

  // 隔离实验（同章、同写作流程，只改细纲）：只补这两个字段就能复现补齐全部字段的收益，
  // 盲评 3/3 胜过不补；补满五个字段与只补这两个不可区分。所以这两个字段不接受占位符，
  // 其余字段仍按契约允许 [待补充]。
  const hollow = INTENT_FIELDS.filter((field) => {
    const match = text.match(new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${field.replace('/', '\\/')}\\*{0,2}\\s*[：:]\\s*(.*)$`, 'm'))
    if (!match) return false
    const value = match[1].replace(/\[待补充\]/g, '').replace(/[\s、，,。;；]/g, '')
    return value.length === 0
  })
  checks.push(makeCheck(
    'outline.intent-fields-substantive',
    hollow.length === 0,
    name,
    hollow.length ? `只有占位符，没有实际内容：${hollow.join('、')}` : '目标情绪与主角目标/关键选择都写了实际内容',
    '目标情绪写清前状态→后状态；主角目标/关键选择写清本章要什么、必须做出的判断。这两项不接受 [待补充]',
    '只把这两个字段替换成本章的实际情绪变化与实际取舍；其余字段不动。'
  ))

  const missingSubs = SUBSECTION_NAMES
    .filter((names) => !names.some((sub) => new RegExp(`^#{3,4}\\s*${sub}`, 'm').test(text)))
    .map((names) => names[0])
  checks.push(makeCheck(
    'outline.subsections',
    missingSubs.length === 0,
    name,
    missingSubs.length ? `缺小节：${missingSubs.join('、')}` : '四个小节齐全',
    '包含 这章怎么走 / 情节安排 / 人物关系和出场顺序 / 情节细化 四个小节（旧名「内容概括」照认）',
    '只补缺失的小节标题及其条目，不重写已成立的内容。'
  ))

  const missingActs = FIVE_ACT.filter((act) => !fieldPattern(act).test(text))
  checks.push(makeCheck(
    'outline.five-act',
    missingActs.length === 0,
    name,
    missingActs.length ? `「这章怎么走」缺：${missingActs.join('、')}` : '「这章怎么走」五行齐全',
    '「这章怎么走」写全 起因 / 发展 / 转折 / 高潮 / 结尾',
    '只补缺的那一段，不改其余四段。'
  ))

  const lines = text.split(/\r?\n/)
  let header = null
  for (const line of lines) {
    const cells = parseTableRow(line)
    // 现行模板默认三列（# / 情节点 / 作用）；需要时加「分辨率」列、表末加「分寸」列，三到五列都收。
    // 旧表头「功能标签」「执行边界（禁＋放）」照收：作用固定在第 3 列，分寸/执行边界只能在最后一列。
    if (cells && cells.length >= 3 && cells.length <= 5 && PLOT_HEADER_FIRST.test(cells[0])) {
      header = cells
      break
    }
  }
  const extraColumnsOk = (extra) => {
    // 第 4 列起只收「分辨率」「分寸/执行边界」各至多一列，分寸在最后；旧四列表的最后一列必须是执行边界/分寸。
    const kinds = extra.map((cell) => (/分辨率/.test(cell) ? 'res' : (/执行边界|分寸/.test(cell) ? 'bound' : null)))
    if (kinds.includes(null) || new Set(kinds).size !== kinds.length) return false
    return !kinds.includes('bound') || kinds[kinds.length - 1] === 'bound'
  }
  const headerOk = Boolean(header)
    && /功能标签|作用/.test(header[2])
    && extraColumnsOk(header.slice(3))
  checks.push(makeCheck(
    'outline.plotpoint-table',
    headerOk,
    name,
    header ? `表头：${header.join(' | ')}` : '未找到 | # | 情节点 | 作用 | 表头',
    '情节细化使用表格：# / 情节点（谁做了什么） / 作用；需要时可加「分辨率」列，某个点确实要限定写到什么程度时在表末加「分寸」列',
    '只把情节点序列改成这张表，逐点补作用；不增删情节点本身。'
  ))

  // 「放」半边只管旧表头「执行边界」：五列表或表头写明「禁＋放」的四列表，必须至少一个点解除限制，
  // 全是禁令的情节点表实测会把整章压成同一个温度（015 章十一个点全「不许」）。表头没写「禁＋放」的四列表不追溯；
  // 新表头「分寸」一句话写这一点放到什么程度，不再拆禁、放两半，不查这一项。
  if (headerOk && /执行边界/.test(header[header.length - 1]) && (header.length === 5 || /放/.test(header[header.length - 1]))) {
    const rows = []
    for (const line of lines) {
      const cells = parseTableRow(line)
      if (cells && cells.length === header.length && /^\d+$/.test(cells[0])) rows.push(cells)
    }
    if (rows.length) {
      const released = rows.filter((cells) => {
        const match = cells[cells.length - 1].match(/(?:^|[。；;\s])放\s*[：:]([^]*?)(?=(?:禁|放)\s*[：:]|$)/)
        if (!match) return false
        const value = match[1].replace(/[\s。；;，,、\[\]【】]/g, '')
        return value.length > 0 && !/^(?:无|暂无|待补充|待定|无缺口)$/.test(value)
      })
      checks.push(makeCheck(
        'outline.plotpoint-release',
        released.length > 0,
        name,
        `${rows.length} 个情节点里 ${released.length} 个写了「放」`,
        '执行边界写成「禁＋放」两半，每章至少一个点写了「放」——放行是解除限制，不是义务',
        '给最该出彩的一两个点补「放」半边（谁可以出声、谁可以失态、允不允许当场标价），不改情节点本身。'
      ))
      if (released.length > 0 && rows.length >= 3 && released.length * 3 < rows.length) {
        checks.push(makeCheck(
          'outline.plotpoint-release-ratio',
          false,
          name,
          `${rows.length} 个情节点里只有 ${released.length} 个写了「放」（不足三分之一）`,
          '建议至少三分之一的情节点写「放」半边，避免整章只剩禁令',
          '按人工判断酌情补「放」；本项不阻断。',
          'advisory'
        ))
      }
    }
  }

  // 「这章不能说破」可选，写了只写本章确要压住的一件事；条目过多多半是把全卷都压着的逐章复读了。
  const releaseMatch = RELEASE_FIELDS
    .map((label) => text.match(new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${label}\\*{0,2}\\s*[：:]\\s*(.*)$`, 'm')))
    .find(Boolean)
  if (releaseMatch) {
    const items = releaseMatch[1].split(/[、；;，,\/]/).map((s) => s.trim()).filter(Boolean)
    if (items.length > RELEASE_MAX_ITEMS) {
      checks.push(makeCheck(
        'outline.release-brevity',
        false,
        name,
        `这章不能说破列了 ${items.length} 条`,
        `只在这章确有一件具体的事要压住时写一行（至多 ${RELEASE_MAX_ITEMS} 条）；全卷都压着的写在卷纲「这卷先不能揭开、不能用上的」，不逐章复读`,
        '把和卷纲重复的条目删掉，只留这章确要压住的那件事；没有就整行删掉。本项不阻断。',
        'advisory'
      ))
    }
  }

  checks.push(checkSettingRefs(text, name, file, projectRoot))

  const targetParse = parseWordcountTarget(text)
  const rangeParse = parseWordcountRange(text)
  const target = targetParse.value
  const caliberOk = parseWordcountCaliber(text)
  const targetLabel = { ok: target, missing: '未识别', invalid: `写法认不出（${targetParse.raw.join('、')}）`, conflict: `多个不同的值（${targetParse.raw.join('、')}）` }[targetParse.status]
  const rangeLabel = rangeParse.status === 'invalid' ? `；字数范围写法不对（${rangeParse.raw.join('、')}）` : (rangeParse.value ? `；字数范围：${rangeParse.value.min}-${rangeParse.value.max}` : '')
  checks.push(makeCheck(
    'outline.wordcount-target',
    targetParse.status === 'ok' && target >= 500 && target <= 20000 && caliberOk && rangeParse.status !== 'invalid',
    name,
    `字数目标：${targetLabel}；字数口径（可不写，写了须是 ${CALIBER}）：${caliberOk}${rangeLabel}`,
    `字数目标为 500-20000 的正整数（可写「2300 字」「约 2300」「2,300」，可带括号备注）；字数口径不用写，写了只能是 ${CALIBER}；作者给了上下限时另写一行「字数范围：2000-2600」`,
    '只补字数目标、字数范围，或删掉写错的字数口径行，不调整情节安排。'
  ))

  const risk = parseContractRisk(text)
  if (risk) {
    checks.push(makeCheck(
      'outline.contract-risk',
      risk.status !== 'invalid',
      name,
      risk.status === 'invalid' ? `有没有硬伤写的是「${risk.raw}」` : `有没有硬伤：${risk.level || '[待补充]'}`,
      `有没有硬伤只写 ${CONTRACT_RISK_LEVELS.join(' / ')} 三档之一（要补时后面写怎么补），未定写 [待补充]`,
      '只把这一行改成三档之一，不改其他字段。'
    ))
  }

  return report(file, checks, {
    wordcount: {
      target,
      target_status: targetParse.status,
      range: rangeParse.value,
      range_status: rangeParse.status,
    },
    contract_risk: risk ? { level: risk.level, detail: risk.detail, status: risk.status } : null,
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
    repair_scope: failures.map((failure) => ({
      id: failure.id,
      file: failure.file,
      evidence: failure.evidence,
      expected: failure.expected,
      references: failure.references,
      repair: failure.repair,
    })),
  }
}

function resolveChapter(project, chapter) {
  const dir = path.join(project, '大纲')
  let entries
  try {
    entries = fs.readdirSync(dir)
  } catch (error) {
    return { error: `无法读取 ${dir}：${error.message}` }
  }
  const wanted = Number(chapter)
  const hit = entries.find((entry) => {
    const match = entry.match(/^细纲_第0*(\d+)章.*\.md$/)
    return match && Number(match[1]) === wanted
  })
  if (!hit) return { error: `${dir} 下没有第 ${wanted} 章细纲` }
  return { file: path.join(dir, hit) }
}

// --supply：批末验证「写纲前查缺」已落盘。新书写在书目录的隐藏目录 .story/排纲笔记/{单元ID}.md；
// 0.10 早期写在卷纲旁的 大纲/排纲笔记_{单元ID}.md，再老叫 排纲底稿_{单元ID}.md，更老的卷纲写在单元卡块内。
// 位置按这个顺序找，小节名新旧都认：写纲前查缺 / 供给自查。
const SUPPLY_HEADING = /^(?:写纲前查缺|供给自查)(?:\s|[（(<]|$)/

function stripTrailingComment(title) {
  return title.replace(/\s*<!--[\s\S]*?-->\s*$/, '').trim()
}

function hasSupplyHeading(text) {
  return text.split(/\r?\n/).some((line) => {
    const heading = line.replace(/\*\*/g, '').match(/^#{1,6}\s+(.+)$/)
    return Boolean(heading) && SUPPLY_HEADING.test(stripTrailingComment(heading[1]))
  })
}

function notesCandidates(volumeFile, unitId) {
  const outlineDir = path.dirname(path.resolve(volumeFile))
  const bookRoot = path.dirname(outlineDir)
  return [
    { file: path.join(bookRoot, '.story', '排纲笔记', `${unitId}.md`), label: '排纲笔记' },
    { file: path.join(outlineDir, `排纲笔记_${unitId}.md`), label: '排纲笔记' },
    { file: path.join(outlineDir, `排纲底稿_${unitId}.md`), label: '排纲底稿' },
  ]
}

function verifySupply(volumeFile, unitId) {
  for (const { file: draftFile, label } of notesCandidates(volumeFile, unitId)) {
    const draft = readUtf8(draftFile)
    if (!draft.ok) continue
    const ok = hasSupplyHeading(draft.text)
    return {
      schema_version: 1, verifier: 'story-long-write.outline-supply', file: path.resolve(draftFile), unit: unitId, ok,
      evidence: ok ? `${label}含「写纲前查缺」小节` : `${path.basename(draftFile)} 里没有「写纲前查缺」小节——每批出细纲前都要查一遍缺什么（没缺也写「无缺口」），见 workflow-outline.md「写纲前查缺」`,
    }
  }
  const read = readUtf8(volumeFile)
  if (!read.ok) {
    return { schema_version: 1, verifier: 'story-long-write.outline-supply', file: path.resolve(volumeFile), unit: unitId, ok: false, evidence: read.error || '卷纲文件为空' }
  }
  // 只检查目标单元内的标题，不把正文提及或代码示例当成小节。
  let fence = null
  const lines = read.text.split(/\r?\n/).map((line) => {
    const marker = line.match(/^\s{0,3}(`{3,}|~{3,})/)
    if (marker) {
      if (!fence) fence = marker[1]
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null
      return ''
    }
    return fence ? '' : line.replace(/\*\*/g, '')
  })
  const headings = []
  for (let index = 0; index < lines.length; index++) {
    const heading = lines[index].match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const comment = heading[2].match(/<!--\s*([\s\S]*?)\s*-->\s*$/)
      headings.push({ index, level: heading[1].length, title: stripTrailingComment(heading[2]), comment: comment ? comment[1] : null })
    }
  }
  const card = headings.find((heading) => {
    // 新写法：标题尾部注释写着单元编号（<!-- L1-01 -->）
    if (heading.comment) {
      const scope = heading.comment.split(/[｜|]/)[0].trim().replace(/^单元级\s+/, '')
      if (/^[A-Za-z]\d*[\w-]*$/.test(scope)) return scope === unitId
    }
    const id = heading.title.match(/剧情单元\s+([A-Za-z][\w-]*)/)
    if (id) return id[1] === unitId
    const end = headings.find((next) => next.index > heading.index)?.index ?? lines.length
    return lines.slice(heading.index + 1, end).some((line) => {
      const field = line.match(/^\s*[-*+]\s*单元ID\s*[：:]\s*([A-Za-z][\w-]*)\s*$/)
      return field?.[1] === unitId
    })
  })
  const end = card ? (headings.find((next) => next.index > card.index && next.level <= card.level)?.index ?? lines.length) : 0
  const ok = Boolean(card) && headings.some((heading) => heading.index > card.index && heading.index < end && SUPPLY_HEADING.test(heading.title))
  if (!card) {
    return { schema_version: 1, verifier: 'story-long-write.outline-supply', file: path.resolve(volumeFile), unit: unitId, ok: false, evidence: `卷纲中未找到剧情段 ${unitId}` }
  }
  return {
    schema_version: 1,
    verifier: 'story-long-write.outline-supply',
    file: path.resolve(volumeFile),
    unit: unitId,
    ok,
    evidence: ok ? '剧情段内含「写纲前查缺」小节' : `没有 .story/排纲笔记/${unitId}.md，剧情段 ${unitId} 里也没有「写纲前查缺」小节——每批出细纲前都要查一遍缺什么（没缺也写「无缺口」），见 workflow-outline.md「写纲前查缺」`,
  }
}

function parseArgs(argv) {
  const files = []
  let project = null
  let chapter = null
  let supply = null
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (arg === '--json') continue
    if (arg === '--supply') {
      if (index + 2 >= argv.length) return null
      supply = { volumeFile: argv[++index], unitId: argv[++index] }
      continue
    }
    if (arg === '--project' || arg === '--chapter') {
      if (index + 1 >= argv.length || argv[index + 1].startsWith('--')) return null
      const value = argv[++index]
      if (arg === '--project') project = value
      else chapter = value
      continue
    }
    if (arg.startsWith('--')) return null
    files.push(arg)
  }
  if (supply) {
    if (project || chapter || files.length) return null
    return { supply }
  }
  if (project || chapter) {
    if (!project || !chapter || files.length || !/^\d+$/.test(chapter)) return null
    return { project, chapter }
  }
  if (!files.length) return null
  return { files }
}

function main(argv) {
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write('用法: node scripts/check-outline-contract.js --json <细纲路径...> | --json --project <书目录> --chapter N | --json --supply <卷纲路径> <单元ID>\n')
    return 2
  }
  if (parsed.supply) {
    const supplyReport = verifySupply(parsed.supply.volumeFile, parsed.supply.unitId)
    process.stdout.write(`${JSON.stringify(supplyReport, null, 2)}\n`)
    return supplyReport.ok ? 0 : 1
  }
  let targets = parsed.files
  if (!targets) {
    const resolved = resolveChapter(parsed.project, parsed.chapter)
    if (resolved.error) {
      process.stderr.write(`${resolved.error}\n`)
      return 2
    }
    targets = [resolved.file]
  }
  const reports = targets.map((file) => verify(file, parsed.project || null))
  const ok = reports.every((entry) => entry.ok)
  process.stdout.write(`${JSON.stringify(reports.length === 1 ? reports[0] : reports, null, 2)}\n`)
  return ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { verify, parseWordcountTarget, parseWordcountRange, parseContractRisk, FIELDS, FIELD_NAMES, SUBSECTIONS, FIVE_ACT }
