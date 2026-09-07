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

function body(charsPerSection = 1000, sections = 6, style = 'numeric') {
  const rows = []
  for (let index = 1; index <= sections; index++) {
    const marker = style === 'zhihu' ? `${index}.` : `###${index}.`
    rows.push(marker, '字'.repeat(charsPerSection))
  }
  return `${rows.join('\n')}\n`
}

function writeCase(name, text) {
  const dir = path.join(tmpRoot, name)
  fs.mkdirSync(dir, { recursive: true })
  if (text !== null) fs.writeFileSync(path.join(dir, '正文.md'), text, 'utf8')
  return dir
}

function run(dir, values = ['6000', '8000', '6'], minSectionChars, checkContract = false) {
  const result = spawnSync(process.execPath, [
    verifier, '--json', '--min-chars', values[0], '--max-chars', values[1],
    '--sections', values[2], ...(minSectionChars === undefined ? [] : ['--min-section-chars', String(minSectionChars)]),
    ...(checkContract ? ['--check-contract'] : []), dir,
  ], { cwd: repoRoot, encoding: 'utf8' })
  const report = result.stdout.trim() ? JSON.parse(result.stdout) : null
  return { ...result, report }
}

function failureIds(result) {
  return result.report.failures.map((failure) => failure.id)
}

try {
  const good = run(writeCase('valid', body()))
  assert.strictEqual(good.status, 0, good.stdout + good.stderr)
  assert.strictEqual(good.report.ok, true)
  assert.strictEqual(good.report.contract.metric, 'non_whitespace_unicode_chars_v1')

  const lopsided = Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${'字'.repeat(index === 1 ? 5980 : 1)}`).join('\n')
  const unbalanced = run(writeCase('unbalanced', lopsided), undefined, 800)
  assert.strictEqual(unbalanced.status, 1, unbalanced.stdout + unbalanced.stderr)
  assert.deepStrictEqual(unbalanced.report.failures.map((f) => f.section), [1, 3, 4, 5, 6])
  assert(unbalanced.report.failures.every((f) => f.id === 'delivery.section-min-chars' && f.actual_chars === 1))

  for (const floor of [500, 800]) {
    for (const actual of [floor - 1, floor]) {
      const result = run(writeCase(`floor-${floor}-${actual}`, body(actual, 1)), ['1', '2000', '1'], floor)
      assert.strictEqual(result.status, actual < floor ? 1 : 0, result.stdout + result.stderr)
      assert.strictEqual(result.report.contract.min_section_chars, floor)
      if (actual < floor) assert.strictEqual(result.report.failures[0].actual_chars, actual)
    }
  }
  // Marker text and whitespace do not satisfy the body floor; Unicode code points do.
  const unicode = run(writeCase('unicode-floor', '###1.\n😀 甲\n'), ['1', '100', '1'], 2)
  assert.strictEqual(unicode.status, 0, unicode.stdout + unicode.stderr)
  for (const value of ['0', '-1', '1.5', 'bad']) {
    const result = run(writeCase(`invalid-floor-${value}`, body()), undefined, value)
    assert.strictEqual(result.status, 2)
  }

  const goodZhihu = run(writeCase('valid-zhihu', body(1000, 6, 'zhihu')))
  assert.strictEqual(goodZhihu.status, 0, goodZhihu.stdout + goodZhihu.stderr)

  const tooLong = run(writeCase('too-long', body(1400)))
  assert.strictEqual(tooLong.status, 1)
  assert.deepStrictEqual(failureIds(tooLong), ['delivery.visible-chars'])

  const wrongSections = run(writeCase('wrong-sections', body(1200, 5)))
  assert.strictEqual(wrongSections.status, 1)
  assert(failureIds(wrongSections).includes('delivery.section-count'))

  const mixed = body().replace('###6.', '6.')
  const mixedStyle = run(writeCase('mixed-style', mixed))
  assert.strictEqual(mixedStyle.status, 1)
  assert.deepStrictEqual(failureIds(mixedStyle), ['delivery.section-style'])

  const duplicateMarker = run(writeCase('duplicate-marker', body().replace('###6.', '###5.')))
  assert.strictEqual(duplicateMarker.status, 1)
  assert.deepStrictEqual(failureIds(duplicateMarker), ['delivery.section-sequence'])

  const blank = body().replace('字\n###2.', '字\n\n另一段\n###2.')
  const blankLines = run(writeCase('blank-lines', blank))
  assert.strictEqual(blankLines.status, 1)
  assert(failureIds(blankLines).includes('delivery.blank-lines'))

  // 文件末尾的空行只是落盘习惯，不算段间空行。
  const trailingBlank = run(writeCase('trailing-blank', `${body()}\n\n`))
  assert.strictEqual(trailingBlank.status, 0, trailingBlank.stdout + trailingBlank.stderr)
  assert.strictEqual(trailingBlank.report.ok, true)

  const missing = run(writeCase('missing', null))
  assert.strictEqual(missing.status, 1)
  assert.deepStrictEqual(failureIds(missing), ['delivery.body-readable'])

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
