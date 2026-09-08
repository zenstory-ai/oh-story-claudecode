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

// 权威模板：references/workflow-setup.md「细纲（全书每章）」
const FIELDS = [
  '核心事件', '字数目标', '字数口径', '阶段位置', '单元ID/位置', '目标情绪',
  '主角目标/关键选择', '章节定位', '本章结构公式', '章首钩子', '爽点',
  '本章标价', '闭环状态', '本章禁止提前释放', '写手自由区', '契约风险',
]
const SUBSECTIONS = ['内容概括', '情节安排', '人物关系和出场顺序', '情节细化']
const FIVE_ACT = ['起因', '发展', '转折', '高潮', '结尾']
const PLOT_HEADER_FIRST = /^(?:#|序号)$/
// 这两个字段实测直接影响正文质量，必须有实际内容
const INTENT_FIELDS = ['目标情绪', '主角目标/关键选择']
const CALIBER = 'visible_chars_v1'

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

function makeCheck(id, ok, file, evidence, expected, repair, severity = 'blocking') {
  return {
    id,
    ok,
    severity,
    file,
    evidence,
    expected,
    references: ['references/workflow-setup.md', 'references/artifact-protocols.md'],
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
    '修正引用路径；或按「创作自主权分级」先把缺的设定落档（B 级直接补、C 级进《供给单》提案），再在细纲引用。'
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

  const missingFields = FIELDS.filter((field) => !fieldPattern(field).test(text))
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

  const missingSubs = SUBSECTIONS.filter((sub) => !new RegExp(`^#{3,4}\\s*${sub}`, 'm').test(text))
  checks.push(makeCheck(
    'outline.subsections',
    missingSubs.length === 0,
    name,
    missingSubs.length ? `缺小节：${missingSubs.join('、')}` : '四个小节齐全',
    '包含 内容概括 / 情节安排 / 人物关系和出场顺序 / 情节细化 四个小节',
    '只补缺失的小节标题及其条目，不重写已成立的内容。'
  ))

  const missingActs = FIVE_ACT.filter((act) => !fieldPattern(act).test(text))
  checks.push(makeCheck(
    'outline.five-act',
    missingActs.length === 0,
    name,
    missingActs.length ? `五段式缺：${missingActs.join('、')}` : '五段式齐全',
    '内容概括写全 起因 / 发展 / 转折 / 高潮 / 结尾',
    '只补缺的那一段，不改其余四段。'
  ))

  const lines = text.split(/\r?\n/)
  let header = null
  for (const line of lines) {
    const cells = parseTableRow(line)
    // 四列是旧表（# / 情节点 / 功能标签 / 执行边界），五列是现行模板（中间多一列「分辨率」）。
    // 两种都收：功能标签固定在第 3 列，执行边界一律取最后一列，旧细纲不因加列而失效。
    if (cells && (cells.length === 4 || cells.length === 5) && PLOT_HEADER_FIRST.test(cells[0])) {
      header = cells
      break
    }
  }
  const headerOk = Boolean(header)
    && header[2].includes('功能标签')
    && header[header.length - 1].includes('执行边界')
    && (header.length === 4 || header[3].includes('分辨率'))
  checks.push(makeCheck(
    'outline.plotpoint-table',
    headerOk,
    name,
    header ? `表头：${header.join(' | ')}` : '未找到 | # | 情节点 | 功能标签 | [分辨率] | 执行边界 | 表头',
    '情节细化使用五列表格：# / 情节点（谁做了什么） / 功能标签 / 分辨率 / 执行边界（四列旧表仍收，但新建细纲按五列模板走）',
    '只把情节点序列改成五列表格，逐点补功能标签、分辨率与执行边界；不增删情节点本身。'
  ))

  // 「放」半边：五列表的执行边界必须至少一个点解除限制（模板既有要求），
  // 全是禁令的情节点表实测会把整章压成同一个温度（015 章十一个点全「不许」）。
  if (headerOk && header.length === 5) {
    const rows = []
    for (const line of lines) {
      const cells = parseTableRow(line)
      if (cells && cells.length === 5 && /^\d+$/.test(cells[0])) rows.push(cells)
    }
    if (rows.length) {
      const released = rows.filter((cells) => {
        const match = cells[4].match(/(?:^|[。；;\s])放\s*[：:]([^]*?)(?=(?:禁|放)\s*[：:]|$)/)
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

  // 章级「禁止提前释放」只写本章特有的三五条；条目过多多半是把卷级常任禁忌逐章复读了。
  const releaseMatch = text.match(/^\s*[-*+]\s*\*{0,2}本章禁止提前释放\*{0,2}\s*[：:]\s*(.*)$/m)
  if (releaseMatch) {
    const items = releaseMatch[1].split(/[、；;，,\/]/).map((s) => s.trim()).filter(Boolean)
    if (items.length > 5) {
      checks.push(makeCheck(
        'outline.release-brevity',
        false,
        name,
        `本章禁止提前释放列了 ${items.length} 条`,
        '章级只写本章特有的三五条；卷级常任禁忌写在卷纲「本卷禁碰的终局底牌」，不逐章复读',
        '把与卷纲常任重复的条目删掉，只留本章特有；本项不阻断。',
        'advisory'
      ))
    }
  }

  checks.push(checkSettingRefs(text, name, file, projectRoot))

  const targetMatch = text.match(/字数目标\s*[：:]\s*(?:约\s*)?([\d,，]+)/)
  const target = targetMatch ? Number(targetMatch[1].replace(/[,，]/g, '')) : null
  const caliberOk = new RegExp(`字数口径\\s*[：:]\\s*${CALIBER}`).test(text)
  checks.push(makeCheck(
    'outline.wordcount-target',
    Boolean(target) && Number.isFinite(target) && target >= 500 && target <= 20000 && caliberOk,
    name,
    `字数目标：${target === null ? '未识别' : target}；字数口径 ${CALIBER}：${caliberOk}`,
    `字数目标为 500-20000 的正整数，并声明 字数口径：${CALIBER}`,
    '只补字数目标或字数口径行，不调整情节安排。'
  ))

  return report(file, checks)
}

function report(file, checks) {
  const failures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const advisories = checks.filter((check) => !check.ok && check.severity === 'advisory')
  return {
    schema_version: 1,
    verifier: 'story-long-write.outline-contract',
    file: path.resolve(file),
    ok: failures.length === 0,
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

// --supply：批末验证《供给单》已落卷纲——定位单元卡块，确认其中有「供给自查」小节。
function verifySupply(volumeFile, unitId) {
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
    if (heading) headings.push({ index, level: heading[1].length, title: heading[2] })
  }
  const card = headings.find((heading) => {
    const id = heading.title.match(/剧情单元\s+([A-Za-z][\w-]*)/)
    if (id) return id[1] === unitId
    const end = headings.find((next) => next.index > heading.index)?.index ?? lines.length
    return lines.slice(heading.index + 1, end).some((line) => {
      const field = line.match(/^\s*[-*+]\s*单元ID\s*[：:]\s*([A-Za-z][\w-]*)\s*$/)
      return field?.[1] === unitId
    })
  })
  const end = card ? (headings.find((next) => next.index > card.index && next.level <= card.level)?.index ?? lines.length) : 0
  const ok = Boolean(card) && headings.some((heading) => heading.index > card.index && heading.index < end && /^供给自查(?:\s|[（(]|$)/.test(heading.title))
  if (!card) {
    return { schema_version: 1, verifier: 'story-long-write.outline-supply', file: path.resolve(volumeFile), unit: unitId, ok: false, evidence: `卷纲中未找到剧情单元 ${unitId}` }
  }
  return {
    schema_version: 1,
    verifier: 'story-long-write.outline-supply',
    file: path.resolve(volumeFile),
    unit: unitId,
    ok,
    evidence: ok ? '单元卡含「供给自查」小节' : `剧情单元 ${unitId} 的卡内没有「供给自查」小节——每批出细纲前须产出《供给单》（含「无缺口」情形），见 workflow-setup.md「按剧情批出细纲」步骤 3`,
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

module.exports = { verify, FIELDS, SUBSECTIONS, FIVE_ACT }
