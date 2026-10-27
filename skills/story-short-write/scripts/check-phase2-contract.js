#!/usr/bin/env node
/**
 * Phase 2 deterministic contract verifier for story-short-write.
 *
 * This script is intentionally mechanical: it checks whether the two Phase 2
 * artifacts expose the fields and table shape required by the skill. It does
 * not pretend to judge story quality or whether a reference was genuinely
 * understood.
 *
 * Usage: node scripts/check-phase2-contract.js --json [project-dir]
 * Exit: 0 = pass, 1 = blocking contract failures, 2 = invalid invocation.
 */

'use strict'

const fs = require('fs')
const path = require('path')

const OUTLINE_HEADERS = [
  '结构段/五段功能',
  '主事件',
  '情节推进',
  '情绪',
  '人物/关系变化',
  '因果/逻辑链',
  '读者新获知什么',
  '结尾承接/钩子',
  '伏笔/物件',
  '场景形态',
  '对白作用',
  '目标字数',
]

const LEGACY_OUTLINE_HEADERS = new Map([
  [2, '子事件×3-5'],
  [9, '动静'],
  [10, '对话密度'],
])

const FUNCTION_TAG = /\{(?:对话|冲突|伏笔|回忆|发现|递进)\}/g
const TEMPLATE_PLACEHOLDER = /\{[^}]*\}|\[待补充\]/

function cleanCell(value) {
  return value.replace(/\*\*/g, '').replace(/`/g, '').trim()
}

function readSettingFields(text) {
  return text.split(/\r?\n/).map((line, index) => {
    const match = cleanCell(line).match(/^(?:[-*+]\s*)?([^：:]+?)\s*[：:]\s*(.*)$/)
    return match ? { line: index + 1, name: match[1].trim(), value: match[2].trim() } : null
  }).filter(Boolean)
}

function parseTableLine(line) {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null
  return trimmed.slice(1, -1).split('|').map(cleanCell)
}

function isSeparatorRow(cells) {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function readUtf8(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function makeCheck(id, ok, file, evidence, expected, references, repair) {
  return { id, ok, severity: 'blocking', file, evidence, expected, references, repair }
}

function verify(projectDir) {
  const project = path.resolve(projectDir)
  const skillRoot = path.resolve(__dirname, '..')
  const settingsFile = path.join(project, '设定.md')
  const outlineFile = path.join(project, '小节大纲.md')
  const settingsRead = readUtf8(settingsFile)
  const outlineRead = readUtf8(outlineFile)
  const checks = []

  checks.push(makeCheck(
    'phase2.settings-readable',
    settingsRead.ok,
    '设定.md',
    settingsRead.ok ? '文件存在且非空' : (settingsRead.error || '文件为空'),
    '项目目录下存在非空的 设定.md',
    ['references/workflow-design.md'],
    '只补建或补全 设定.md，不改动已通过的 小节大纲.md。'
  ))
  checks.push(makeCheck(
    'phase2.outline-readable',
    outlineRead.ok,
    '小节大纲.md',
    outlineRead.ok ? '文件存在且非空' : (outlineRead.error || '文件为空'),
    '项目目录下存在非空的 小节大纲.md',
    ['references/workflow-design.md'],
    '只补建或补全 小节大纲.md，不改动已通过的 设定.md。'
  ))

  if (!settingsRead.ok || !outlineRead.ok) return report(project, checks)

  const settings = settingsRead.text
  const outline = outlineRead.text
  const fields = readSettingFields(settings)
  const fieldValue = (name) => fields.find((entry) => entry.name === name)?.value || ''

  const platformMatch = fieldValue('目标平台').match(/^(知乎(?:盐言|盐选)?|盐[言选]|七猫(?:短篇)?|黑岩|红果|小程序|点众|番茄(?:短篇)?|未定)/)
  checks.push(makeCheck(
    'phase2.platform-declared',
    Boolean(platformMatch),
    '设定.md',
    platformMatch ? `目标平台：${platformMatch[1]}` : '未找到可识别的目标平台字段',
    '写明“目标平台：知乎盐言 / 番茄 / 七猫 / 黑岩 / 红果 / 小程序”之一；作者没定平台写“未定”',
    ['references/submission-craft.md'],
    '只在 设定.md 的基本信息或 Phase 2 设计校验区补目标平台。'
  ))

  const genreMatch = (fieldValue('题材参考') || fieldValue('题材包')).match(/^(references\/(?:genre-styles\/[^`\s|]+\.md|genre-writing-formulas\.md))/)
  let genreEvidence = '未找到题材参考路径'
  let genreOk = false
  if (genreMatch) {
    const resolved = path.resolve(skillRoot, genreMatch[1])
    const insideSkill = resolved.startsWith(`${skillRoot}${path.sep}`)
    genreOk = insideSkill && fs.existsSync(resolved) && fs.statSync(resolved).isFile()
    genreEvidence = genreOk ? `题材参考：${genreMatch[1]}` : `题材参考不可读：${genreMatch[1]}`
  }
  checks.push(makeCheck(
    'phase2.genre-reference-declared',
    genreOk,
    '设定.md',
    genreEvidence,
    '写明一个真实存在的 references/genre-styles/{题材}.md；冷门题材写 references/genre-writing-formulas.md',
    ['references/workflow-design.md', 'references/short-craft.md'],
    '只补题材参考路径与从该参考选出的 2-3 个核心招式，不重写故事框架。'
  ))

  const moves = fieldValue('核心招式').split(/[；;]|\s\/\s/)
    .map((item) => item.trim()).filter(Boolean)
  checks.push(makeCheck(
    'phase2.genre-moves-declared',
    moves.length >= 2 && moves.length <= 3,
    '设定.md',
    moves.length ? `识别到 ${moves.length} 个核心招式` : '未找到核心招式字段',
    '“核心招式：招式一；招式二[；招式三]”，共 2-3 个',
    ['references/workflow-design.md'],
    '只补或收敛核心招式字段到 2-3 个，并保持已选题材参考不变。'
  ))

  const skipReason = (fieldValue('反派设计') || fieldValue('反派')).match(/^(?:无|不适用)\s*[（(][ \t]*([^)）]+)[)）]/)
  const villainSkipped = Boolean(skipReason && skipReason[1].trim() && !TEMPLATE_PLACEHOLDER.test(skipReason[1]))
  const villainFields = ['身份', '动机', '作恶方式', '致命弱点', '报应']
  const missingVillainFields = villainFields.filter((field) => {
    const value = fieldValue(field)
    return !value || TEMPLATE_PLACEHOLDER.test(value)
  })
  const villainOk = villainSkipped || missingVillainFields.length === 0
  checks.push(makeCheck(
    'phase2.villain-contract',
    villainOk,
    '设定.md',
    villainSkipped ? '已明确反派不适用' : (villainOk ? '反派五字段齐全' : `缺失或未填写：${missingVillainFields.join('、')}`),
    '无反派时写“反派设计：不适用（原因）”；有反派时填写身份、动机、作恶方式、致命弱点、报应',
    ['references/villain-and-reveal.md'],
    '只补反派缺失字段；若确无反派，改为带原因的不适用声明。'
  ))

  const placeholderFields = ['题材参考', '题材包', '核心招式', '反派设计', '反派', '反转类型', '反转位置', '付费点', '目标平台', '目标字数', ...villainFields]
  const placeholderLines = fields
    .filter((entry) => placeholderFields.includes(entry.name))
    .filter((entry) => TEMPLATE_PLACEHOLDER.test(entry.value))
  checks.push(makeCheck(
    'phase2.no-template-placeholders',
    placeholderLines.length === 0,
    '设定.md',
    placeholderLines.length ? `仍是模板占位符的行：${placeholderLines.map((entry) => entry.line).join('、')}` : '契约字段没有未填写的占位符',
    'Phase 2 契约字段写实际设计内容，不保留 {} 或 [待补充] 占位符',
    ['references/workflow-design.md'],
    '只把报告行的占位符替换成本篇的实际设计，不重写其他字段。'
  ))

  const lines = outline.split(/\r?\n/)
  let headerAt = -1
  let headerCells = null
  for (let index = 0; index < lines.length; index++) {
    const cells = parseTableLine(lines[index])
    if (cells && cells[0] === OUTLINE_HEADERS[0]) {
      headerAt = index
      headerCells = cells
      break
    }
  }
  const currentHeader = Boolean(headerCells) && headerCells.length === OUTLINE_HEADERS.length &&
    headerCells.every((cell, index) => cell === OUTLINE_HEADERS[index])
  const legacyHeader = Boolean(headerCells) && headerCells.length === OUTLINE_HEADERS.length &&
    headerCells.every((cell, index) => cell === (LEGACY_OUTLINE_HEADERS.get(index) || OUTLINE_HEADERS[index]))
  const headerOk = currentHeader || legacyHeader
  checks.push(makeCheck(
    'phase2.outline-12-columns',
    headerOk,
    '小节大纲.md',
    headerCells
      ? `表头 ${headerCells.length} 列：${headerCells.join(' | ')}${legacyHeader ? '（兼容旧项目；新建项目使用现行列名）' : ''}`
      : '未找到以“结构段/五段功能”开头的 Markdown 表格',
    `使用固定 12 列表头：${OUTLINE_HEADERS.join(' | ')}`,
    ['references/workflow-design.md'],
    '只修表头和错位单元格，不改动各节已经成立的剧情内容。'
  ))

  const rows = []
  if (headerAt >= 0) {
    for (let index = headerAt + 1; index < lines.length; index++) {
      const cells = parseTableLine(lines[index])
      if (!cells) {
        if (rows.length) break
        continue
      }
      if (isSeparatorRow(cells)) continue
      rows.push({ line: index + 1, cells })
    }
  }
  const rowShapeFailures = rows.filter((row) => row.cells.length !== OUTLINE_HEADERS.length)
  checks.push(makeCheck(
    'phase2.outline-data-rows',
    rows.length > 0 && rowShapeFailures.length === 0,
    '小节大纲.md',
    rows.length === 0 ? '固定表头下没有数据行' : (rowShapeFailures.length ? `列数错误行：${rowShapeFailures.map((row) => row.line).join('、')}` : `识别到 ${rows.length} 节，均为 12 列`),
    '固定表头下至少一行数据，且每节恰好 12 列',
    ['references/workflow-design.md'],
    '只补缺失节或修复报告行的列错位。'
  ))

  const progressionFailures = []
  const progressionRows = rows.filter((item) => item.cells.length === OUTLINE_HEADERS.length)
  for (const row of progressionRows) {
    const progression = row.cells[2].split(/\s*(?:->|→)\s*/).filter(Boolean)
    if (progression.length < 1 || progression.some((item) => {
      const action = item.replace(FUNCTION_TAG, '')
      return action === item || action.replace(/[\s、，,。；;：:]/g, '').length === 0
    })) {
      progressionFailures.push(row.line)
    }
  }
  checks.push(makeCheck(
    'phase2.outline-subevents',
    rows.length > 0 && progressionFailures.length === 0,
    '小节大纲.md',
    progressionFailures.length
      ? `情节推进为空或功能标签错误行：${progressionFailures.join('、')}`
      : (progressionRows.length === rows.length
          ? `所有 ${rows.length} 节均有至少一个带功能标签的真实推进`
          : `已检查 ${progressionRows.length}/${rows.length} 行；其余行由 phase2.outline-data-rows 报告列错位`),
    '每节至少一个真实推进；有先后关系时以 -> 连接，每个含 {对话/冲突/伏笔/回忆/发现/递进} 标签之一，不设固定数量',
    ['references/workflow-design.md', 'references/short-craft.md'],
    '只修报告行的“情节推进”单元格，不重写其他列或其他节；不要为数量补事件。'
  ))

  // 「约 1-1.3 万」「1.1万字」这类写法先换成整数再解析。
  const targetLine = ('目标字数：' + fieldValue('目标字数'))
    .replace(/(\d+(?:\.\d+)?)\s*((?:[-–—~～]|到|至)\s*)(\d+(?:\.\d+)?)\s*万/g,
      (_, a, sep, b) => `${Math.round(Number(a) * 10000)}${sep}${Math.round(Number(b) * 10000)}`)
    .replace(/(\d+(?:\.\d+)?)\s*万/g, (_, a) => String(Math.round(Number(a) * 10000)))
  const targetMatch = targetLine.match(/目标字数\s*[：:]\s*(?:约\s*)?([\d,，]+)\s*(?:字)?\s*(?:[-–—~～]|到|至)\s*([\d,，]+)\s*字?/) ||
    targetLine.match(/目标字数\s*[：:]\s*(?:约\s*)?([\d,，]+)\s*字?/)
  const toNumber = (value) => Number(String(value).replace(/[,，]/g, ''))
  const targetLow = targetMatch ? toNumber(targetMatch[1]) : null
  const targetHigh = targetMatch && targetMatch[2] !== undefined ? toNumber(targetMatch[2]) : targetLow
  const statedTarget = targetLow
  const rowTargets = progressionRows.map((row) => {
    const match = row.cells[11].match(/^(?:约|大约)?\s*([1-9][0-9]{0,2}(?:[,，][0-9]{3})+|[1-9][0-9]*)\s*字?(?:左右)?\s*(?:[（(][^（）()]*[）)])?$/)
    return match ? toNumber(match[1]) : null
  })
  const targetSum = rowTargets.every((value) => Number.isSafeInteger(value) && value > 0)
    ? rowTargets.reduce((sum, value) => sum + value, 0)
    : null
  const isRange = targetHigh !== null && targetHigh !== targetLow
  const targetOk = statedTarget !== null && statedTarget >= 1000 && targetHigh <= 200000 &&
    targetHigh >= targetLow && progressionRows.length === rows.length && targetSum !== null &&
    (isRange
      ? targetSum >= targetLow && targetSum <= targetHigh
      : Math.abs(targetSum - statedTarget) <= statedTarget * 0.05)
  checks.push(makeCheck(
    'phase2.target-word-sum',
    targetOk,
    '设定.md、小节大纲.md',
    `设定目标：${statedTarget === null ? '未识别' : (isRange ? `${targetLow}-${targetHigh}` : statedTarget)}；大纲合计：${targetSum === null ? '有无效的逐节目标字数' : targetSum}`,
    '设定.md 的目标字数为 1000-200000 的正整数或区间（用户明确范围优先，未指定时用所选平台的投稿区间，未定平台用 8000-12000）；大纲每行目标字数须完整写成正整数，写区间时合计落在区间内，写单值时误差不超过 5%',
    ['references/workflow-design.md', 'references/submission-craft.md'],
    '只修目标字数字段或各节“目标字数”单元格，使合计匹配；不要用增删剧情绕过数字错误。'
  ))

  const reversalMatch = fieldValue('反转位置').match(/^第?\s*(\d+)\s*节?\s*(?:÷|\/)\s*(?:共|全文)?\s*(\d+)\s*节?\s*=\s*(\d+(?:\.\d+)?)\s*%/)
  const noReversal = /^无反转/.test(fieldValue('反转类型')) &&
    /^不适用\s*[（(][^)）]+[)）]/.test(fieldValue('反转位置'))
  let reversalOk = false
  let reversalEvidence = '未找到“反转位置：第 X 节 ÷ 共 Y 节 = Z%”'
  if (noReversal) {
    reversalOk = true
    reversalEvidence = '反转类型为无反转，位置已带原因标为不适用'
  } else if (reversalMatch) {
    const reveal = Number(reversalMatch[1])
    const total = Number(reversalMatch[2])
    const stated = Number(reversalMatch[3])
    const calculated = total > 0 ? (reveal / total) * 100 : NaN
    reversalOk = reveal >= 1 && reveal <= total && total === rows.length &&
      Math.abs(stated - calculated) <= 0.6
    reversalEvidence = `声明第 ${reveal} 节 ÷ 共 ${total} 节 = ${stated}%；大纲识别 ${rows.length} 节`
  }
  checks.push(makeCheck(
    'phase2.reversal-position',
    reversalOk,
    '设定.md',
    reversalEvidence,
    '有反转时写明揭穿节号、全文总节数和计算百分比；总节数须与大纲一致，计算误差不超过 0.6%。无反转时写明“反转类型：无反转”和带原因的“反转位置：不适用（…）”',
    ['references/workflow-design.md', 'references/short-reversal.md'],
    '只修正反转位置计算或对应节次；位置质量按 short-reversal.md 的误判决策与揭示后果功能链判断，不为跨过固定百分比而搬节。'
  ))

  const paywallMatch = fieldValue('付费点').match(/^第?\s*(\d+)\s*节末/)
  const paywallSection = paywallMatch ? Number(paywallMatch[1]) : null
  const paywallRows = rows
    .map((row, index) => ({ section: index + 1, hook: row.cells[7] || '' }))
    .filter((row) => /付费点/.test(row.hook))
  const paywallOk = paywallSection !== null && paywallRows.length === 1 &&
    paywallRows[0].section === paywallSection
  let paywallEvidence = '设定.md 未按“付费点：第 X 节末”声明'
  if (paywallSection !== null && paywallRows.length === 0) {
    paywallEvidence = `设定.md 声明第 ${paywallSection} 节末；大纲“结尾承接/钩子”列未标出付费点`
  } else if (paywallSection !== null && paywallRows.length > 0) {
    paywallEvidence = `设定.md 声明第 ${paywallSection} 节末；大纲标在第 ${paywallRows.map((row) => row.section).join('、')} 节`
  }
  checks.push(makeCheck(
    'phase2.paywall-in-both',
    paywallOk,
    '设定.md、小节大纲.md',
    paywallEvidence,
    '设定.md 写“付费点：第 X 节末”，且小节大纲.md 第 X 行数据的“结尾承接/钩子”单元格只标一次“付费点”',
    ['references/submission-craft.md', 'references/workflow-design.md'],
    '只在缺失的文件补同一个付费断点，并确保它位于对应节末的钩子单元格。'
  ))

  return report(project, checks)
}

function report(project, checks) {
  const failures = checks.filter((check) => !check.ok)
  return {
    schema_version: 1,
    verifier: 'story-short-write.phase2-contract',
    project,
    ok: failures.length === 0,
    checks,
    failures,
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

function main(argv) {
  const args = argv.filter((arg) => arg !== '--json')
  if (args.length > 1 || args.some((arg) => arg.startsWith('--'))) {
    process.stderr.write('用法: node scripts/check-phase2-contract.js --json [project-dir]\n')
    return 2
  }
  const result = verify(args[0] || '.')
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { OUTLINE_HEADERS, verify }
