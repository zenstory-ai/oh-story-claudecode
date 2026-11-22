#!/usr/bin/env node
/**
 * Deterministic delivery verifier for story-short-write.
 *
 * Usage:
 *   node scripts/check-delivery-contract.js --json [--strict] \
 *     --min-chars N --max-chars N --sections N [--min-section-chars N] [--check-contract] [project-dir]
 * --check-contract validates only parameters before writing; it is not delivery approval.
 * Exit: 0 = pass (no hard failures; soft warnings allowed unless --strict),
 *       1 = blocking delivery failures (or soft warnings under --strict),
 *       2 = invalid invocation.
 *
 * The verifier only checks user-visible size and shape. It does not score prose,
 * causality, emotion, or any other semantic quality dimension.
 */

'use strict'

const fs = require('fs')
const path = require('path')

const MARKERS = [
  { style: 'numeric-heading', pattern: /^###\s*\d+\.$/ },
  { style: 'chapter-heading', pattern: /^###\s*第[一二三四五六七八九十百千万两〇零0-9]+章$/ },
  { style: 'zhihu-numeric', pattern: /^\d+\.$/ },
]

function readBody(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function visibleChars(text) {
  return Array.from(text).filter((character) => !/\s/u.test(character)).length
}

function markerFor(line) {
  const trimmed = line.trim()
  return MARKERS.find((entry) => entry.pattern.test(trimmed)) || null
}

function makeCheck(id, ok, evidence, expected, repair, severity = 'blocking') {
  return {
    id,
    ok,
    severity,
    file: '正文.md',
    evidence,
    expected,
    references: ['references/short-format.md'],
    repair,
  }
}

function verify(projectDir, contract, options = {}) {
  const strict = Boolean(options && options.strict)
  const project = path.resolve(projectDir)
  const bodyFile = path.join(project, '正文.md')
  const bodyRead = readBody(bodyFile)
  const checks = []

  checks.push(makeCheck(
    'delivery.body-readable',
    bodyRead.ok,
    bodyRead.ok ? '正文.md 存在且非空' : (bodyRead.error || '正文.md 为空'),
    '项目目录下存在非空的 正文.md',
    '只补建或恢复 正文.md；不要改动设定与大纲。',
    'blocking'
  ))
  if (!bodyRead.ok) return report(project, contract, checks, { strict })

  const lines = bodyRead.text.replace(/\r\n?/g, '\n').replace(/\n+$/, '\n').split('\n')

  const placeholderLines = []
  lines.forEach((line, index) => {
    if (/\{[^}\n]*\}/.test(line)) placeholderLines.push(index + 1)
  })
  checks.push(makeCheck(
    'delivery.no-template-placeholders',
    placeholderLines.length === 0,
    placeholderLines.length ? `正文含未填写的 {} 占位符（行：${placeholderLines.join('、')}）` : '正文无未填写的 {} 占位符',
    '正文不得保留未填写的 {} 模板占位符',
    '只替换报告行中未填写的 {} 占位符，不改其余正文。',
    'blocking'
  ))

  const actual = visibleChars(bodyRead.text)
  const hardFloorChars = Math.ceil(contract.minChars * 0.5)
  const catastrophicUnderLength = actual < contract.minChars * 0.5
  const inRange = actual >= contract.minChars && actual <= contract.maxChars
  checks.push({
    ...makeCheck(
      'delivery.visible-chars',
      inRange,
      `非空白 Unicode 字符：${actual}` + (catastrophicUnderLength ? `（不足下限 50%：${hardFloorChars}）` : ''),
      `用户要求 ${contract.minChars}-${contract.maxChars} 个非空白字符（硬底线 ≥ ${hardFloorChars}）`,
      catastrophicUnderLength
        ? '正文严重不足目标下限的一半，需补全缺失情节与场次后再交付。'
        : (actual < contract.minChars
          ? '复核字数：若需达标，只扩写既有情节点的行动、后果或对话，不新增支线；若确属合理收束可向作者说明。'
          : '复核字数：若需压缩，只删重复解释、复述和无功能过场，不删关键证据或结算。'),
      catastrophicUnderLength ? 'blocking' : 'advisory'
    ),
    actual_chars: actual,
    hard_floor_chars: hardFloorChars,
  })

  const markers = lines
    .map((line, index) => ({ line: index + 1, marker: markerFor(line), text: line.trim() }))
    .filter((entry) => entry.marker)
  checks.push(makeCheck(
    'delivery.section-count',
    markers.length === contract.sections,
    `识别到 ${markers.length} 个小节标记：${markers.map((entry) => entry.text).join('、') || '无'}`,
    `建议正文为 ${contract.sections} 节`,
    '复核节数：若是漏标或多标小节标记则修正；若是创作中合理合节/分节且序号连贯，确认后可保留。',
    'advisory'
  ))

  if (contract.minSectionChars != null) {
    for (const [index, entry] of markers.entries()) {
      const end = index + 1 < markers.length ? markers[index + 1].line - 1 : lines.length
      const count = visibleChars(lines.slice(entry.line, end).join('\n'))
      checks.push({
        ...makeCheck(
          'delivery.section-min-chars',
          count >= contract.minSectionChars,
          `${entry.text} 正文非空白 Unicode 字符：${count}`,
          `建议每节正文至少 ${contract.minSectionChars} 个非空白字符（不含小节标记）`,
          `复核第 ${index + 1} 节篇幅：若写得太赶，补足既有情节点的行动、后果或对话；若是有意快节奏短节，确认后可保留。`,
          'advisory'
        ),
        section: index + 1,
        actual_chars: count,
      })
    }
  }
  const styles = new Set(markers.map((entry) => entry.marker.style))
  checks.push(makeCheck(
    'delivery.section-style',
    markers.length > 0 && styles.size === 1,
    markers.length ? `小节标记样式：${Array.from(styles).join('、')}` : '没有可识别的小节标记',
    '建议全文统一使用 short-format.md 允许的一种小节标记',
    '复核小节标记样式：一般应全文统一，只调整标记行，不改正文内容。',
    'advisory'
  ))

  const numericSequence = markers.map((entry) => {
    const match = entry.text.match(/\d+/)
    return match ? Number(match[0]) : null
  })
  const sequenceOk = markers.length > 0 && (
    numericSequence.every((number) => number !== null)
      ? numericSequence.every((number, index) => number === index + 1)
      : new Set(markers.map((entry) => entry.text)).size === markers.length
  )
  checks.push(makeCheck(
    'delivery.section-sequence',
    sequenceOk,
    `小节序列：${markers.map((entry) => entry.text).join('、') || '无'}`,
    '数字小节从 1 连续递增；中文章名不得重复',
    '只修正小节标记编号，不改正文内容。',
    'blocking'
  ))

  const markerLines = new Set(markers.map((entry) => entry.line - 1))
  const invalidBlankLines = []
  for (let index = 0; index < lines.length; index++) {
    if (lines[index].trim() !== '') continue
    const isEdge = index === 0 || index === lines.length - 1
    const touchesMarker = markerLines.has(index - 1) || markerLines.has(index + 1)
    if (!isEdge && !touchesMarker) invalidBlankLines.push(index + 1)
  }
  checks.push(makeCheck(
    'delivery.blank-lines',
    invalidBlankLines.length === 0,
    invalidBlankLines.length ? `正文段落间空行：${invalidBlankLines.join('、')}` : '正文段落间无空行',
    '建议只允许文件边缘或小节标记相邻处出现空行，正文段落之间紧密单换行',
    '复核报告行的段间空行：按目标平台格式需要时删去多余空行，若平台或场景转场有意留白可保留。',
    'advisory'
  ))

  return report(project, contract, checks, { strict })
}

function toScopeItem(item) {
  return {
    id: item.id,
    severity: item.severity,
    file: item.file,
    evidence: item.evidence,
    expected: item.expected,
    references: item.references,
    repair: item.repair,
    ...(item.section === undefined ? {} : { section: item.section, actual_chars: item.actual_chars }),
    ...(item.section === undefined && item.actual_chars !== undefined ? { actual_chars: item.actual_chars } : {}),
  }
}

function report(project, contract, checks, options = {}) {
  const strict = Boolean(options && options.strict)
  const hardFailures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const softWarnings = checks.filter((check) => !check.ok && check.severity === 'advisory')
  const findings = [...hardFailures, ...softWarnings]
  const failures = strict ? findings : hardFailures
  return {
    schema_version: 1,
    verifier: 'story-short-write.delivery-contract',
    scope: 'delivery',
    project,
    strict,
    contract: {
      metric: 'non_whitespace_unicode_chars_v1',
      min_chars: contract.minChars,
      max_chars: contract.maxChars,
      sections: contract.sections,
      min_section_chars: contract.minSectionChars ?? null,
    },
    ok: failures.length === 0,
    status: failures.length > 0 ? 'fail' : (softWarnings.length > 0 ? 'warn' : 'pass'),
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

function parsePositiveInteger(value) {
  if (!/^[1-9]\d*$/.test(value || '')) return null
  const number = Number(value)
  return Number.isSafeInteger(number) ? number : null
}

function parseArgs(argv) {
  const values = {}
  const positional = []
  let strict = false
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (arg === '--json' || arg === '--check-contract') continue
    if (arg === '--strict') { strict = true; continue }
    if (['--min-chars', '--max-chars', '--sections', '--min-section-chars'].includes(arg)) {
      if (index + 1 >= argv.length || argv[index + 1].startsWith('--')) return null
      values[arg] = parsePositiveInteger(argv[++index])
      if (values[arg] === null) return null
      continue
    }
    if (arg.startsWith('--')) return null
    positional.push(arg)
  }
  if (positional.length > 1) return null
  if (!values['--min-chars'] || !values['--max-chars'] || !values['--sections']) return null
  if (values['--min-chars'] > values['--max-chars']) return null
  // The shortest allowed markers are 1., 2., ...; they count even without a body floor.
  const sections = values['--sections']
  let minimum = sections * ((values['--min-section-chars'] ?? 0) + 1)
  for (let start = 1; start <= sections; start *= 10) minimum += sections - start + 1
  if (minimum > values['--max-chars']) return null
  return {
    project: positional[0] || '.',
    strict,
    contract: {
      minChars: values['--min-chars'],
      maxChars: values['--max-chars'],
      sections: values['--sections'],
      minSectionChars: values['--min-section-chars'] ?? null,
    },
  }
}

function main(argv) {
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write('参数缺失或范围不可同时满足。用法: node scripts/check-delivery-contract.js --json [--strict] --min-chars N --max-chars N --sections N [--min-section-chars N] [--check-contract] [project-dir]\n')
    return 2
  }
  const result = argv.includes('--check-contract')
    ? { ...report(path.resolve(parsed.project), parsed.contract, [], { strict: parsed.strict }), scope: 'parameters-only' }
    : verify(parsed.project, parsed.contract, { strict: parsed.strict })
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { markerFor, visibleChars, verify }
