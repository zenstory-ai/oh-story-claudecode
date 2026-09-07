#!/usr/bin/env node
/**
 * Deterministic delivery verifier for story-short-write.
 *
 * Usage:
 *   node scripts/check-delivery-contract.js --json \
 *     --min-chars N --max-chars N --sections N [--min-section-chars N] [--check-contract] [project-dir]
 * --check-contract validates only parameters before writing; it is not delivery approval.
 * Exit: 0 = pass, 1 = blocking delivery failures, 2 = invalid invocation.
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

function makeCheck(id, ok, evidence, expected, repair) {
  return {
    id,
    ok,
    severity: 'blocking',
    file: '正文.md',
    evidence,
    expected,
    references: ['references/short-format.md'],
    repair,
  }
}

function verify(projectDir, contract) {
  const project = path.resolve(projectDir)
  const bodyFile = path.join(project, '正文.md')
  const bodyRead = readBody(bodyFile)
  const checks = []

  checks.push(makeCheck(
    'delivery.body-readable',
    bodyRead.ok,
    bodyRead.ok ? '正文.md 存在且非空' : (bodyRead.error || '正文.md 为空'),
    '项目目录下存在非空的 正文.md',
    '只补建或恢复 正文.md；不要改动设定与大纲。'
  ))
  if (!bodyRead.ok) return report(project, contract, checks)

  const actual = visibleChars(bodyRead.text)
  checks.push(makeCheck(
    'delivery.visible-chars',
    actual >= contract.minChars && actual <= contract.maxChars,
    `非空白 Unicode 字符：${actual}`,
    `用户要求 ${contract.minChars}-${contract.maxChars} 个非空白字符`,
    actual < contract.minChars
      ? '只扩写既有情节点的行动、后果或对话，不新增支线。'
      : '只压缩重复解释、复述和无功能过场，不删关键证据或结算。'
  ))

  const lines = bodyRead.text.replace(/\r\n?/g, '\n').replace(/\n+$/, '\n').split('\n')
  const markers = lines
    .map((line, index) => ({ line: index + 1, marker: markerFor(line), text: line.trim() }))
    .filter((entry) => entry.marker)
  checks.push(makeCheck(
    'delivery.section-count',
    markers.length === contract.sections,
    `识别到 ${markers.length} 个小节标记：${markers.map((entry) => entry.text).join('、') || '无'}`,
    `正文恰好 ${contract.sections} 节`,
    '只校正缺失、多余或误写的小节标记；不要为凑节数新开支线。'
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
          `每节正文至少 ${contract.minSectionChars} 个非空白字符（不含小节标记）`,
          `只补足第 ${index + 1} 节既有情节点的行动、后果或对话，不新增支线。`
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
    '全文统一使用 short-format.md 允许的一种小节标记',
    '只统一小节标记的样式，不改正文内容。'
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
    '只修正小节标记编号，不改正文内容。'
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
    '只允许文件边缘或小节标记相邻处出现空行，正文段落之间紧密单换行',
    '只删除报告行的多余空行。'
  ))

  return report(project, contract, checks)
}

function report(project, contract, checks) {
  const failures = checks.filter((check) => !check.ok)
  return {
    schema_version: 1,
    verifier: 'story-short-write.delivery-contract',
    scope: 'delivery',
    project,
    contract: {
      metric: 'non_whitespace_unicode_chars_v1',
      min_chars: contract.minChars,
      max_chars: contract.maxChars,
      sections: contract.sections,
      min_section_chars: contract.minSectionChars ?? null,
    },
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
      ...(failure.section === undefined ? {} : { section: failure.section, actual_chars: failure.actual_chars }),
    })),
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
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (arg === '--json' || arg === '--check-contract') continue
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
    process.stderr.write('参数缺失或范围不可同时满足。用法: node scripts/check-delivery-contract.js --json --min-chars N --max-chars N --sections N [--min-section-chars N] [--check-contract] [project-dir]\n')
    return 2
  }
  const result = argv.includes('--check-contract')
    ? { ...report(path.resolve(parsed.project), parsed.contract, []), scope: 'parameters-only' }
    : verify(parsed.project, parsed.contract)
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { markerFor, visibleChars, verify }
