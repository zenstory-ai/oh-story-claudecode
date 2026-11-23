#!/usr/bin/env node
'use strict'

const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const repoRoot = path.resolve(__dirname, '..')
const verifier = path.join(repoRoot, 'skills/story-short-write/scripts/check-delivery-contract.js')
const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'delivery-contract-'))

const DEFAULT_LEAD = [
  '结婚三周年纪念日，我收到一份离婚协议。',
  '“签字吧，别拖着了。”',
  '我把转账记录拍在桌上，他瞬间白了脸。',
].join('\n')

// 生成精确可见字数的短篇测试正文块：每行 ≤15 字、对话占比 ≥35%、末尾落「字」。
function sectionChunk(totalChars) {
  const lines = []
  let rem = totalChars
  while (rem >= 27) {
    lines.push('“这事没完，你别想躲。”') // 12 visible chars (10 quoted)
    lines.push('她把协议拍在桌上没再看他一眼字') // 15 visible chars
    rem -= 27
  }
  if (rem > 0) lines.push('字'.repeat(rem))
  return lines.join('\n')
}

function body(charsPerSection = 1000, sections = 6, style = 'numeric', { includeLead = sections >= 2 } = {}) {
  const rows = []
  if (includeLead) rows.push(DEFAULT_LEAD)
  for (let index = 1; index <= sections; index++) {
    const marker = style === 'zhihu' ? `${index}.` : `###${index}.`
    rows.push(marker, sectionChunk(charsPerSection))
  }
  return `${rows.join('\n')}\n`
}

function writeCase(name, text) {
  const dir = path.join(tmpRoot, name)
  fs.mkdirSync(dir, { recursive: true })
  if (text !== null) fs.writeFileSync(path.join(dir, '正文.md'), text, 'utf8')
  return dir
}

function run(dir, values = ['6000', '8000', '6'], minSectionChars, checkContract = false, extraArgs = []) {
  const result = spawnSync(process.execPath, [
    verifier, '--json', ...extraArgs, '--min-chars', values[0], '--max-chars', values[1],
    '--sections', values[2], ...(minSectionChars === undefined ? [] : ['--min-section-chars', String(minSectionChars)]),
    ...(checkContract ? ['--check-contract'] : []), dir,
  ], { cwd: repoRoot, encoding: 'utf8' })
  const report = result.stdout.trim() ? JSON.parse(result.stdout) : null
  return { ...result, report }
}

function failureIds(result) {
  return result.report.failures.map((failure) => failure.id)
}
function hardIds(result) {
  return result.report.hard_failures.map((failure) => failure.id)
}
function softIds(result) {
  return result.report.soft_warnings.map((warning) => warning.id)
}

function assertSoftOnly(dir, expectedId, values = ['6000', '8000', '6'], minSectionChars) {
  const normal = run(dir, values, minSectionChars)
  assert.strictEqual(normal.status, 0, `${expectedId} normal: ${normal.stdout}${normal.stderr}`)
  assert.strictEqual(normal.report.ok, true)
  assert.strictEqual(normal.report.status, 'warn')
  assert.deepStrictEqual(hardIds(normal), [])
  assert.deepStrictEqual(failureIds(normal), [])
  assert(softIds(normal).includes(expectedId), `expected soft warning ${expectedId}, got ${JSON.stringify(softIds(normal))}`)
  assert(normal.report.findings.some((f) => f.id === expectedId && f.severity === 'advisory'))
  assert(normal.report.review_scope.some((f) => f.id === expectedId))

  const strict = run(dir, values, minSectionChars, false, ['--strict'])
  assert.strictEqual(strict.status, 1, `${expectedId} --strict should exit 1`)
  assert.strictEqual(strict.report.ok, false)
  assert.strictEqual(strict.report.strict, true)
  assert.strictEqual(strict.report.status, 'fail')
  assert.deepStrictEqual(hardIds(strict), [])
  assert(softIds(strict).includes(expectedId))
  assert(failureIds(strict).includes(expectedId))
  assert(strict.report.repair_scope.some((f) => f.id === expectedId))
  return { normal, strict }
}

try {
  const validDir = writeCase('valid', body())
  const good = run(validDir)
  assert.strictEqual(good.status, 0, good.stdout + good.stderr)
  assert.strictEqual(good.report.ok, true)
  assert.strictEqual(good.report.status, 'pass')
  assert.deepStrictEqual(good.report.hard_failures, [])
  assert.deepStrictEqual(good.report.soft_warnings, [])
  assert.deepStrictEqual(good.report.findings, [])
  assert.strictEqual(good.report.contract.metric, 'non_whitespace_unicode_chars_v1')
  assert.strictEqual(run(validDir, ['6000', '8000', '6'], undefined, false, ['--strict']).status, 0)

  // SOFT: per-section floor (--min-section-chars) → soft_warnings (exit 0), --strict → exit 1.
  const lopsided = [
    DEFAULT_LEAD,
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${index === 1 ? sectionChunk(5950) : '字'}`),
  ].join('\n')
  const unbalanced = assertSoftOnly(writeCase('unbalanced', lopsided), 'delivery.section-min-chars', ['6000', '8000', '6'], 800)
  assert.deepStrictEqual(unbalanced.normal.report.soft_warnings.map((f) => f.section), [1, 3, 4, 5, 6])
  assert(unbalanced.normal.report.soft_warnings.every((f) => f.id === 'delivery.section-min-chars' && f.actual_chars === 1))
  assert.deepStrictEqual(unbalanced.strict.report.failures.map((f) => f.section), [1, 3, 4, 5, 6])

  for (const floor of [500, 800]) {
    for (const actual of [floor - 1, floor]) {
      const dir = writeCase(`floor-${floor}-${actual}`, body(actual, 1))
      const normal = run(dir, ['1', '2000', '1'], floor)
      assert.strictEqual(normal.status, 0, normal.stdout + normal.stderr)
      assert.strictEqual(normal.report.contract.min_section_chars, floor)
      const strict = run(dir, ['1', '2000', '1'], floor, false, ['--strict'])
      assert.strictEqual(strict.status, actual < floor ? 1 : 0, strict.stdout + strict.stderr)
      if (actual < floor) assert.strictEqual(normal.report.soft_warnings[0].actual_chars, actual)
    }
  }
  // Marker text and whitespace do not satisfy the body floor; Unicode code points do.
  const unicode = run(writeCase('unicode-floor', '###1.\n😀 甲\n'), ['1', '100', '1'], 2, false, ['--strict'])
  assert.strictEqual(unicode.status, 0, unicode.stdout + unicode.stderr)
  for (const value of ['0', '-1', '1.5', 'bad']) {
    const result = run(writeCase(`invalid-floor-${value}`, body()), undefined, value)
    assert.strictEqual(result.status, 2)
  }

  const goodZhihu = run(writeCase('valid-zhihu', body(1000, 6, 'zhihu')), ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(goodZhihu.status, 0, goodZhihu.stdout + goodZhihu.stderr)

  // SOFT: borderline wordcount (> max_chars and 50%-100% of min_chars) → exit 0 + soft_warnings, --strict → exit 1.
  assertSoftOnly(writeCase('too-long', body(1400)), 'delivery.visible-chars')
  assertSoftOnly(writeCase('borderline-short', body(600)), 'delivery.visible-chars')

  // HARD: catastrophic under-length (<50% of min_chars) → exit 1 + hard_failures.
  const catastrophic = run(writeCase('catastrophic-short', body(400)))
  assert.strictEqual(catastrophic.status, 1)
  assert.strictEqual(catastrophic.report.status, 'fail')
  assert.deepStrictEqual(hardIds(catastrophic), ['delivery.visible-chars'])
  assert(catastrophic.report.findings.some((f) => f.id === 'delivery.visible-chars' && f.severity === 'blocking'))

  // HARD: unfilled {} template placeholders in 正文.md → exit 1 + hard_failures.
  const withPlaceholder = run(writeCase('unfilled-placeholder', body().replace('字\n###2.', '字{待补动作}\n###2.')))
  assert.strictEqual(withPlaceholder.status, 1)
  assert.deepStrictEqual(hardIds(withPlaceholder), ['delivery.no-template-placeholders'])

  // SOFT: valid continuous sequence with different section count → soft_warnings (exit 0), --strict → exit 1.
  assertSoftOnly(writeCase('wrong-sections', body(1200, 5)), 'delivery.section-count')

  // SOFT: minor heading style mismatch → soft_warnings (exit 0), --strict → exit 1.
  const mixed = body().replace('###6.', '6.')
  assertSoftOnly(writeCase('mixed-style', mixed), 'delivery.section-style')

  // HARD: corrupted/duplicate section sequence → exit 1 + hard_failures.
  const duplicateMarker = run(writeCase('duplicate-marker', body().replace('###6.', '###5.')))
  assert.strictEqual(duplicateMarker.status, 1)
  assert.deepStrictEqual(hardIds(duplicateMarker), ['delivery.section-sequence'])

  // SOFT: paragraph spacing blank lines → soft_warnings (exit 0), --strict → exit 1.
  const blank = body().replace('字\n###2.', '字\n\n另一段\n###2.')
  assertSoftOnly(writeCase('blank-lines', blank), 'delivery.blank-lines')

  // 文件末尾的空行只是落盘习惯，不算段间空行（连 --strict 也通过）。
  const trailingBlank = run(writeCase('trailing-blank', `${body()}\n\n`), ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(trailingBlank.status, 0, trailingBlank.stdout + trailingBlank.stderr)
  assert.strictEqual(trailingBlank.report.ok, true)

  // SOFT: 短篇结构健康度（全部仅 advisory，不设标点/情绪词计数门禁）。
  // 1) delivery.short-para-rhythm：段长中位 >45 字或 >80 字段落占比 >10%
  const longParaChunk = Array.from({ length: 10 }, () => `“${'对白内容测试长句'.repeat(5)}”${'叙述补足长度凑够百字'.repeat(6)}`).join('\n')
  const longParaBody = [
    DEFAULT_LEAD,
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${longParaChunk}`),
  ].join('\n') + '\n'
  const paraWarn = assertSoftOnly(writeCase('short-long-paras', longParaBody), 'delivery.short-para-rhythm', ['5500', '8000', '6'])
  assert.deepStrictEqual(softIds(paraWarn.normal), ['delivery.short-para-rhythm'])

  // 2) delivery.short-dialogue-share：对话占比 <15%
  const noDialogueChunk = Array.from({ length: 50 }, () => '她走进屋里把门反锁又把灯关掉了。字').join('\n')
  const noDialogueBody = [
    '结婚三周年纪念日，我收到一份离婚协议。',
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${noDialogueChunk}`),
  ].join('\n') + '\n'
  const dialWarn = assertSoftOnly(writeCase('short-low-dialogue', noDialogueBody), 'delivery.short-dialogue-share', ['5000', '8000', '6'])
  assert.deepStrictEqual(softIds(dialWarn.normal), ['delivery.short-dialogue-share'])

  // 3) delivery.short-lead-present：缺少导语或导语 >500 字
  const noLeadWarn = assertSoftOnly(
    writeCase('short-no-lead', body(1000, 6, 'numeric', { includeLead: false })),
    'delivery.short-lead-present'
  )
  assert.deepStrictEqual(softIds(noLeadWarn.normal), ['delivery.short-lead-present'])

  const hugeLead = `${sectionChunk(540)}\n${body(1000, 6, 'numeric', { includeLead: false })}`
  const longLeadWarn = assertSoftOnly(
    writeCase('short-huge-lead', hugeLead),
    'delivery.short-lead-present'
  )
  assert.deepStrictEqual(softIds(longLeadWarn.normal), ['delivery.short-lead-present'])

  // 4) 仅标题/HTML 注释/分隔线放在首个小节标记前不能伪装成导语；HTML 注释也不计入正文段长。
  const titleOnlyBeforeMarker = `# 婚宴反杀\n<!-- 去味:跳过 -->\n---\n${body(1000, 6, 'numeric', { includeLead: false })}`
  const titleOnlyWarn = assertSoftOnly(
    writeCase('short-title-only-no-lead', titleOnlyBeforeMarker),
    'delivery.short-lead-present'
  )
  assert.deepStrictEqual(softIds(titleOnlyWarn.normal), ['delivery.short-lead-present'])
  assert.match(titleOnlyWarn.normal.report.soft_warnings[0].evidence, /缺少导语（0 字）/)

  const commentWithLead = `# 婚宴反杀\n<!-- ${'备注'.repeat(60)} -->\n${DEFAULT_LEAD}\n${body(1000, 6, 'numeric', { includeLead: false })}`
  const commentLeadPass = run(writeCase('short-comment-plus-lead', commentWithLead), ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(commentLeadPass.status, 0, commentLeadPass.stdout + commentLeadPass.stderr)

  // 前文已闭合的多行 HTML 注释即使后文出现未闭合 `<!--`，也不应重新暴露为导语或超长段落。
  const closedMultiPlusUnclosed = [
    '# 婚宴反杀',
    '<!-- 跨行注释第一行',
    '跨行注释第二行 -->',
    body(1000, 6, 'numeric', { includeLead: false }).trimEnd(),
    '<!-- 末尾忘记闭合的注释',
  ].join('\n') + '\n'
  const multiCommentWarn = assertSoftOnly(
    writeCase('short-closed-multiline-plus-unclosed', closedMultiPlusUnclosed),
    'delivery.short-lead-present'
  )
  assert.deepStrictEqual(softIds(multiCommentWarn.normal), ['delivery.short-lead-present'])
  assert.match(multiCommentWarn.normal.report.soft_warnings[0].evidence, /缺少导语（0 字）/)

  // HARD: missing 正文.md → exit 1 + hard_failures.
  const missing = run(writeCase('missing', null))
  assert.strictEqual(missing.status, 1)
  assert.deepStrictEqual(hardIds(missing), ['delivery.body-readable'])

  const impossible = run(writeCase('impossible', body()), ['1', '3000', '6'], 800)
  assert.strictEqual(impossible.status, 2)
  const preflightDir = writeCase('preflight', null)
  const preflight = run(preflightDir, ['6000', '8000', '6'], 800, true)
  assert.strictEqual(preflight.status, 0, preflight.stdout + preflight.stderr)
  assert.strictEqual(preflight.report.scope, 'parameters-only')
  assert.strictEqual(fs.existsSync(path.join(preflightDir, '正文.md')), false)
  assert.strictEqual(run(preflightDir, ['1', '3000', '6'], 800, true).status, 2)
  // Even the shortest permitted marker counts in the total: floor 800 + "1." = 802.
  const markerBudget = run(writeCase('impossible-marker-budget', body(800, 1)), ['1', '801', '1'], 800)
  assert.strictEqual(markerBudget.status, 2)

  // Marker characters consume the total budget even without an opt-in body floor.
  for (const [sections, markerChars] of [[6, 12], [10, 21]]) {
    const markersOnly = Array.from({ length: sections }, (_, index) => `${index + 1}.`).join('\n')
    const dir = writeCase(`default-marker-budget-${sections}`, markersOnly)
    for (const checkContract of [false, true]) {
      for (const maxChars of [markerChars - 1, markerChars]) {
        const result = run(dir, ['1', String(maxChars), String(sections)], undefined, checkContract)
        assert.strictEqual(result.status, maxChars < markerChars ? 2 : 0, result.stdout + result.stderr)
      }
    }
  }

  const invalid = spawnSync(process.execPath, [verifier, '--json', '--min-chars', '8000'], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  assert.strictEqual(invalid.status, 2)
  assert.match(invalid.stderr, /用法/)

  process.stdout.write('delivery-contract: all tests passed\n')
} finally {
  fs.rmSync(tmpRoot, { recursive: true, force: true })
}
