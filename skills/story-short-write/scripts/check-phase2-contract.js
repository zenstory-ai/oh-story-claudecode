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

// 小节大纲按列名找列，不按位置：新旧列名都认，老书的 小节大纲.md 不迁移也能继续写。
// 第一个名字是现行列名（workflow-design 的小节大纲模板），其余是旧名。
const OUTLINE_COLUMNS = [
  { role: 'stage', names: ['在全篇哪一段', '结构段/五段功能'] },
  { role: 'progress', names: ['这节发生的事', '情节推进', '子事件×3-5'] },
  { role: 'emotion', names: ['情绪'] },
  { role: 'hook', names: ['节尾停在哪', '结尾承接/钩子'] },
  { role: 'words', names: ['目标字数'] },
]
// 可选列：0.10 起小节大纲只要五列，下面这些写了照认、不写不拦（老书的十二列表头照样过）。
const OPTIONAL_COLUMNS = ['主事件', '人物/关系变化', '前因后果', '因果/逻辑链', '读者新获知什么', '伏笔/物件', '这节靠什么推进', '对话改变了什么', '场景形态', '对白作用', '动静', '对话密度']
const OUTLINE_HEADERS = OUTLINE_COLUMNS.map((column) => column.names[0])
const STAGE_NAMES = OUTLINE_COLUMNS[0].names

function cleanCell(value) {
  return value.replace(/\*\*/g, '').replace(/`/g, '').trim()
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

  const platformMatch = settings.match(/目标平台\s*[：:]\s*(知乎(?:盐言|盐选)?|盐[言选]|七猫(?:短篇)?|黑岩|红果|小程序|点众|番茄(?:短篇)?|未定)/)
  checks.push(makeCheck(
    'phase2.platform-declared',
    Boolean(platformMatch),
    '设定.md',
    platformMatch ? `目标平台：${platformMatch[1]}` : '未找到可识别的目标平台字段',
    '写明“目标平台：知乎盐言 / 番茄 / 七猫 / 黑岩 / 红果 / 小程序”之一；作者没定平台写“未定”',
    ['references/submission-craft.md'],
    '只在 设定.md 的基本信息补目标平台。'
  ))

  // 题材：现行写题材名（「题材：追妻火葬场」，冷门写「题材：冷门：公式名」），由脚本对到 genre-styles；
  // 0.9.x 及更早写的是文件路径（「题材参考：`references/genre-styles/悬疑.md`」），照认。
  const genreLine = settings.match(/^[ \t]*[-*]?[ \t]*(?:题材参考|题材包|题材)[ \t]*[：:][ \t]*([^\n]*)$/m)
  const genreValue = genreLine ? genreLine[1].replace(/`/g, '').trim() : ''
  const genreDir = path.join(skillRoot, 'references', 'genre-styles')
  const genreNames = fs.existsSync(genreDir)
    ? fs.readdirSync(genreDir).filter((name) => name.endsWith('.md')).map((name) => name.slice(0, -3))
    : []
  let genreEvidence = '未找到「题材：」一行'
  let genreOk = false
  const pathMatch = genreValue.match(/references\/(?:genre-styles\/[^\s|]+\.md|genre-writing-formulas\.md)/)
  if (pathMatch) {
    const resolved = path.resolve(skillRoot, pathMatch[0])
    const insideSkill = resolved.startsWith(`${skillRoot}${path.sep}`)
    genreOk = insideSkill && fs.existsSync(resolved) && fs.statSync(resolved).isFile()
    genreEvidence = genreOk ? `题材：${pathMatch[0]}` : `题材对不到文件：${pathMatch[0]}`
  } else if (/^冷门/.test(genreValue)) {
    genreOk = fs.existsSync(path.join(skillRoot, 'references', 'genre-writing-formulas.md'))
    genreEvidence = `题材：${genreValue}（冷门题材公式）`
  } else if (genreValue) {
    const named = genreNames.filter((name) => genreValue.startsWith(name)).sort((a, b) => b.length - a.length)[0]
    genreOk = Boolean(named)
    genreEvidence = named ? `题材：${named}` : `题材「${genreValue}」不是现有题材包（${genreNames.join(' / ')}），冷门题材写「冷门：公式名」`
  }
  checks.push(makeCheck(
    'phase2.genre-reference-declared',
    genreOk,
    '设定.md',
    genreEvidence,
    `「构思要点」写「题材：题材包名」（${genreNames.join(' / ')} 之一）；冷门题材写「题材：冷门：所用公式名」`,
    ['references/workflow-design.md', 'references/short-craft.md'],
    '只补「题材：」一行与从该题材包选出的 2-3 个套路，不重写故事框架。'
  ))

  // 套路：现行写在「### 这篇用的套路」下，一条一行；旧书在设计校验区写「核心招式：a；b」，照认。
  const movesMatch = settings.match(/核心招式\s*[：:]\s*([^\n]+)/)
  let moves = []
  if (movesMatch) {
    moves = movesMatch[1].split(/[；;]|\s\/\s/).map((item) => item.trim()).filter(Boolean)
  } else {
    const section = settings.match(/^#{2,6}[ \t]*这篇用的套路[^\n]*\n([\s\S]*?)(?=^#{1,6}[ \t]|(?![\s\S]))/m)
    if (section) {
      moves = section[1].split(/\r?\n/)
        .map((line) => line.match(/^[ \t]*[-*][ \t]+(.+)$/))
        .filter(Boolean)
        .map((match) => match[1].trim())
        .filter((item) => item && item !== '[待补充]')
    }
  }
  checks.push(makeCheck(
    'phase2.genre-moves-declared',
    moves.length >= 2 && moves.length <= 3,
    '设定.md',
    moves.length ? `识别到 ${moves.length} 个套路` : '「这篇用的套路」下没有条目',
    '「这篇用的套路」下 2-3 条，一条一行（旧书的「核心招式：招式一；招式二」照认）',
    ['references/workflow-design.md'],
    '只补或收敛「这篇用的套路」到 2-3 条，并保持已选题材不变。'
  ))

  const villainSkipped = /反派(?:设计)?\s*[：:]\s*(?:无|不适用|没有)\s*[（(][^)）]+[)）]/.test(settings)
  const villainFields = ['身份', '动机', '作恶方式', '致命弱点', '报应']
  const missingVillainFields = villainFields.filter((field) => !new RegExp(`(?:^|\\n)\\s*[-*]?\\s*${field}\\s*[：:]`, 'm').test(settings))
  const villainOk = villainSkipped || missingVillainFields.length === 0
  checks.push(makeCheck(
    'phase2.villain-contract',
    villainOk,
    '设定.md',
    villainSkipped ? '已明确反派不适用' : (villainOk ? '反派五字段齐全' : `缺字段：${missingVillainFields.join('、')}`),
    '无反派时写“反派：没有（原因）”；有反派时填写身份、动机、作恶方式、致命弱点、报应',
    ['references/villain-and-reveal.md'],
    '只补反派缺失字段；若确无反派，改为「反派：没有（原因）」。'
  ))

  const placeholderFields = ['题材参考', '题材', '核心招式', '反派设计', '反派', '反转类型', '反转位置', '反转在', '付费点', '目标平台', '目标字数']
  const fieldLine = new RegExp(`^[ \\t]*[-*]?[ \\t]*(?:${placeholderFields.join('|')})[ \\t]*[：:]`)
  let inMoves = false
  const placeholderLines = []
  settings.split(/\r?\n/).forEach((text, index) => {
    if (/^#{1,6}[ \t]/.test(text)) inMoves = /这篇用的套路/.test(text)
    const watched = fieldLine.test(text) || (inMoves && /^[ \t]*[-*][ \t]/.test(text))
    if (watched && /\{[^}]*\}/.test(text)) placeholderLines.push({ line: index + 1, text })
  })
  checks.push(makeCheck(
    'phase2.no-template-placeholders',
    placeholderLines.length === 0,
    '设定.md',
    placeholderLines.length ? `仍是模板占位符的行：${placeholderLines.map((entry) => entry.line).join('、')}` : '构思要点与套路没有未填写的 {} 占位符',
    '构思要点与「这篇用的套路」写实际设计内容，不保留 {} 模板占位符',
    ['references/workflow-design.md'],
    '只把报告行的占位符替换成本篇的实际设计，不重写其他字段。'
  ))

  const lines = outline.split(/\r?\n/)
  let headerAt = -1
  let headerCells = null
  for (let index = 0; index < lines.length; index++) {
    const cells = parseTableLine(lines[index])
    if (cells && STAGE_NAMES.includes(cells[0])) {
      headerAt = index
      headerCells = cells
      break
    }
  }
  const column = {}
  const unknownCells = []
  const duplicateRoles = []
  if (headerCells) {
    headerCells.forEach((cell, index) => {
      const spec = OUTLINE_COLUMNS.find((item) => item.names.includes(cell))
      if (spec) {
        if (spec.role in column) duplicateRoles.push(cell)
        else column[spec.role] = index
      } else if (!OPTIONAL_COLUMNS.includes(cell)) {
        unknownCells.push(cell)
      }
    })
  }
  const missingColumns = OUTLINE_COLUMNS.filter((item) => !(item.role in column)).map((item) => item.names[0])
  const legacyHeader = Boolean(headerCells) && headerCells.some((cell) =>
    OUTLINE_COLUMNS.some((item) => item.names.indexOf(cell) > 0))
  const headerOk = Boolean(headerCells) && missingColumns.length === 0 && unknownCells.length === 0 && duplicateRoles.length === 0
  let headerEvidence = `未找到以“${STAGE_NAMES[0]}”开头的 Markdown 表格`
  if (headerCells) {
    const problems = []
    if (missingColumns.length) problems.push(`缺列：${missingColumns.join('、')}`)
    if (unknownCells.length) problems.push(`认不出的列：${unknownCells.join('、')}`)
    if (duplicateRoles.length) problems.push(`重复的列：${duplicateRoles.join('、')}`)
    headerEvidence = `表头 ${headerCells.length} 列：${headerCells.join(' | ')}` +
      (problems.length ? `；${problems.join('；')}` : (legacyHeader ? '（旧列名，照认）' : ''))
  }
  checks.push(makeCheck(
    'phase2.outline-header',
    headerOk,
    '小节大纲.md',
    headerEvidence,
    `表头含这五列：${OUTLINE_HEADERS.join(' | ')}；其余列可选`,
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
  const width = headerCells ? headerCells.length : 0
  const rowShapeFailures = rows.filter((row) => row.cells.length !== width)
  checks.push(makeCheck(
    'phase2.outline-data-rows',
    rows.length > 0 && rowShapeFailures.length === 0,
    '小节大纲.md',
    rows.length === 0 ? '表头下没有数据行' : (rowShapeFailures.length ? `列数错误行：${rowShapeFailures.map((row) => row.line).join('、')}` : `识别到 ${rows.length} 节，列数与表头一致`),
    '表头下至少一行数据，每节的列数与表头一致',
    ['references/workflow-design.md'],
    '只补缺失节或修复报告行的列错位。'
  ))

  const shapedRows = headerOk ? rows.filter((item) => item.cells.length === width) : []
  const cell = (row, role) => (role in column ? (row.cells[column[role]] || '') : '')
  const emptyProgress = shapedRows.filter((row) => !cell(row, 'progress').trim()).map((row) => row.line)
  checks.push(makeCheck(
    'phase2.outline-subevents',
    shapedRows.length > 0 && emptyProgress.length === 0,
    '小节大纲.md',
    emptyProgress.length
      ? `「这节发生的事」为空的行：${emptyProgress.join('、')}`
      : (shapedRows.length ? `所有 ${shapedRows.length} 节都写了这节发生的事` : '表头或列数有误，见前两项'),
    '每节写一句这节发生的事，不设数量',
    ['references/workflow-design.md'],
    '只补报告行的「这节发生的事」，不重写其他列或其他节；不要为数量补事件。'
  ))

  // 「约 1-1.3 万」「1.1万字」这类写法先换成整数再解析。
  const targetLine = (settings.match(/目标字数\s*[：:][^\n]*/) || [''])[0]
    .replace(/(\d+(?:\.\d+)?)\s*((?:[-–—~～]|到|至)\s*)(\d+(?:\.\d+)?)\s*万/g,
      (_, a, sep, b) => `${Math.round(Number(a) * 10000)}${sep}${Math.round(Number(b) * 10000)}`)
    .replace(/(\d+(?:\.\d+)?)\s*万/g, (_, a) => String(Math.round(Number(a) * 10000)))
  const targetMatch = targetLine.match(/目标字数\s*[：:]\s*(?:约\s*)?([\d,，]+)\s*(?:字)?\s*(?:[-–—~～]|到|至)\s*([\d,，]+)\s*字?/) ||
    targetLine.match(/目标字数\s*[：:]\s*(?:约\s*)?([\d,，]+)\s*字?/)
  const toNumber = (value) => Number(String(value).replace(/[,，]/g, ''))
  const targetLow = targetMatch ? toNumber(targetMatch[1]) : null
  const targetHigh = targetMatch && targetMatch[2] !== undefined ? toNumber(targetMatch[2]) : targetLow
  const statedTarget = targetLow
  const rowTargets = shapedRows.map((row) => {
    const match = cell(row, 'words').match(/([\d,，]+)/)
    return match ? Number(match[1].replace(/[,，]/g, '')) : null
  })
  const targetSum = rowTargets.every((value) => Number.isFinite(value))
    ? rowTargets.reduce((sum, value) => sum + value, 0)
    : null
  const isRange = targetHigh !== null && targetHigh !== targetLow
  const targetOk = statedTarget !== null && statedTarget >= 1000 && targetHigh <= 200000 &&
    targetHigh >= targetLow && shapedRows.length > 0 && shapedRows.length === rows.length && targetSum !== null &&
    (isRange
      ? targetSum >= targetLow && targetSum <= targetHigh
      : Math.abs(targetSum - statedTarget) <= statedTarget * 0.05)
  checks.push(makeCheck(
    'phase2.target-word-sum',
    targetOk,
    '设定.md、小节大纲.md',
    `设定目标：${statedTarget === null ? '未识别' : (isRange ? `${targetLow}-${targetHigh}` : statedTarget)}；大纲合计：${targetSum === null ? '有非数字目标字数' : targetSum}`,
    '设定.md 的目标字数为 1000-200000 的正整数或区间（用户明确范围优先，未指定时用所选平台的投稿区间，未定平台用 8000-12000）；大纲每行目标字数可解析，写区间时合计落在区间内，写单值时误差不超过 5%',
    ['references/workflow-design.md', 'references/submission-craft.md'],
    '只修目标字数字段或各节“目标字数”单元格，使合计匹配；不要用增删剧情绕过数字错误。'
  ))

  // 反转位置只核节号在不在大纲范围内；百分比只供核对，不是通过线（0.10 起旧写法里的算式不再核算）。
  const reversalMatch = settings.match(/反转(?:位置|在)\s*[：:]\s*第\s*(\d+)\s*节/)
  const noReversal = /反转类型\s*[：:]\s*无反转/.test(settings) &&
    /反转(?:位置|在)\s*[：:]\s*不适用\s*[（(][^)）]+[)）]/.test(settings)
  let reversalOk = false
  let reversalEvidence = '未找到“反转在：第 X 节（共 Y 节）”'
  if (noReversal) {
    reversalOk = true
    reversalEvidence = '反转类型为无反转，位置已带原因标为不适用'
  } else if (reversalMatch) {
    const reveal = Number(reversalMatch[1])
    reversalOk = reveal >= 1 && reveal <= rows.length
    reversalEvidence = `声明反转在第 ${reveal} 节；大纲识别 ${rows.length} 节`
  }
  checks.push(makeCheck(
    'phase2.reversal-position',
    reversalOk,
    '设定.md',
    reversalEvidence,
    '有反转时写“反转在：第 X 节（共 Y 节）”，X 在大纲节数之内；无反转时写“反转类型：无反转”和带原因的“反转在：不适用（…）”',
    ['references/workflow-design.md', 'references/short-reversal.md'],
    '只修正反转所在节号；位置好坏按 short-reversal.md 的误判与揭示后果判断，不为凑比例搬节。'
  ))

  const paywallMatch = settings.match(/付费点\s*[：:]\s*第?\s*(\d+)\s*节末/)
  const paywallSection = paywallMatch ? Number(paywallMatch[1]) : null
  const paywallRows = rows
    .map((row, index) => ({ section: index + 1, hook: cell(row, 'hook') }))
    .filter((row) => /付费点/.test(row.hook))
  const paywallOk = paywallSection !== null && paywallRows.length === 1 &&
    paywallRows[0].section === paywallSection
  let paywallEvidence = '设定.md 未按“付费点：第 X 节末”声明'
  if (paywallSection !== null && paywallRows.length === 0) {
    paywallEvidence = `设定.md 声明第 ${paywallSection} 节末；大纲“节尾停在哪”列未标出付费点`
  } else if (paywallSection !== null && paywallRows.length > 0) {
    paywallEvidence = `设定.md 声明第 ${paywallSection} 节末；大纲标在第 ${paywallRows.map((row) => row.section).join('、')} 节`
  }
  checks.push(makeCheck(
    'phase2.paywall-in-both',
    paywallOk,
    '设定.md、小节大纲.md',
    paywallEvidence,
    '设定.md 写“付费点：第 X 节末”，且小节大纲.md 第 X 行数据的“节尾停在哪”单元格只标一次“付费点”',
    ['references/submission-craft.md', 'references/workflow-design.md'],
    '只在缺失的文件补同一个付费断点，并确保它位于对应节的「节尾停在哪」单元格。'
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

module.exports = { OUTLINE_HEADERS, OPTIONAL_COLUMNS, verify }
