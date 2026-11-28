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
  // 1) delivery.short-para-rhythm：段长中位 >30 字或 >80 字段落占比 >3%
  const longParaChunk = Array.from({ length: 10 }, () => `“${'对白内容测试长句'.repeat(5)}”${'叙述补足长度凑够百字'.repeat(6)}`).join('\n')
  const longParaBody = [
    DEFAULT_LEAD,
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${longParaChunk}`),
  ].join('\n') + '\n'
  const paraWarn = assertSoftOnly(writeCase('short-long-paras', longParaBody), 'delivery.short-para-rhythm', ['5500', '8000', '6'])
  assert.deepStrictEqual(softIds(paraWarn.normal), ['delivery.short-para-rhythm'])

  // 收紧边界：段长中位 35 字（>30）即触发 advisory
  const mid35Chunk = Array.from({ length: 30 }, () => '“你现在把合同签了，别再拖。”她把印章推过桌面，目光一动不动盯着他。').join('\n') // 34 visible chars
  const mid35Body = [
    DEFAULT_LEAD,
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${mid35Chunk}`),
  ].join('\n') + '\n'
  const mid35Warn = assertSoftOnly(writeCase('short-median-35', mid35Body), 'delivery.short-para-rhythm', ['5500', '8000', '6'])
  assert.deepStrictEqual(softIds(mid35Warn.normal), ['delivery.short-para-rhythm'])

  // 收紧边界：>80 字段落占比 5%（>3%）即触发 advisory
  const brickLine = `“${'别再跟我装无辜了。'.repeat(2)}”${'她把那叠流水账单和录音笔一并推到长桌中央，满屋子亲戚顿时鸦雀无声，二婶手里的茶杯停在半空半晌没敢落下去。'.repeat(2)}`
  const over3PctChunk = [
    ...Array.from({ length: 19 }, (_, idx) => (idx % 2 === 0 ? '“这事没完，你别想躲。”' : '她把协议拍在桌上没再看他一眼字')),
    brickLine,
  ].join('\n') // 1/20 = 5% > 3%
  const over3PctBody = [
    DEFAULT_LEAD,
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${over3PctChunk}`),
  ].join('\n') + '\n'
  const over3PctWarn = assertSoftOnly(writeCase('short-over80-5pct', over3PctBody), 'delivery.short-para-rhythm', ['2000', '8000', '6'])
  assert.deepStrictEqual(softIds(over3PctWarn.normal), ['delivery.short-para-rhythm'])

  // 2) delivery.short-dialogue-share：对话/心声弹幕占比 <15%
  const noDialogueChunk = Array.from({ length: 50 }, () => '她走进屋里把门反锁又把灯关掉了。字').join('\n')
  const noDialogueBody = [
    '结婚三周年纪念日，我收到一份离婚协议。',
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${noDialogueChunk}`),
  ].join('\n') + '\n'
  const dialWarn = assertSoftOnly(writeCase('short-low-dialogue', noDialogueBody), 'delivery.short-dialogue-share', ['5000', '8000', '6'])
  assert.deepStrictEqual(softIds(dialWarn.normal), ['delivery.short-dialogue-share'])

  // 【】心声/弹幕应并入 short-dialogue-share 并透明报告，且引号内嵌套【】不重复计字
  const danmuChunk = Array.from({ length: 40 }, () => [
    '【弹幕：快跑！他手里那份根本是假遗嘱！】',
    '她低头翻过账本最后一页，没露声色。',
  ].join('\n')).join('\n')
  const danmuBody = [
    '我抬头看见头顶飘过一行弹幕。',
    '“怎么不说话了？”',
    ...Array.from({ length: 6 }, (_, index) => `###${index + 1}.\n${danmuChunk}`),
  ].join('\n') + '\n'
  const danmuPass = run(writeCase('short-danmu-dialogue', danmuBody), ['6000', '10000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(danmuPass.status, 0, danmuPass.stdout + danmuPass.stderr)
  const danmuCheck = danmuPass.report.checks.find((c) => c.id === 'delivery.short-dialogue-share')
  assert.match(danmuCheck.evidence, /【】心声\/弹幕/)

  const nestedBracketBody = [
    DEFAULT_LEAD,
    '###1.',
    ...Array.from({ length: 20 }, () => '“【系统提示】别动！”她看着眼前空荡荡的房间，把门反锁后坐回椅中，慢慢核对着昨晚记下的那几笔账目明细。'),
  ].join('\n') + '\n'
  const nestedRes = run(writeCase('short-nested-bracket', nestedBracketBody), ['500', '3000', '1'])
  const nestedCheck = nestedRes.report.checks.find((c) => c.id === 'delivery.short-dialogue-share')
  assert.doesNotMatch(nestedCheck.evidence, /【】心声\/弹幕/, 'nested 【】 inside quotes must not double-count as separate bracket chars')

  // 独立单行切镜/番外标头（如【邓承宇视角】、【沈知行视角（五年前）】、【番外】）不计入【】心声/弹幕
  const povHeaderBody = [
    DEFAULT_LEAD,
    '###1.',
    '【邓承宇视角】',
    sectionChunk(400),
    '【沈知行视角（五年前）】',
    sectionChunk(300),
    '【男主番外】',
    sectionChunk(300),
  ].join('\n') + '\n'
  const povRes = run(writeCase('short-pov-header', povHeaderBody), ['800', '2000', '1'])
  const povCheck = povRes.report.checks.find((c) => c.id === 'delivery.short-dialogue-share')
  assert.doesNotMatch(povCheck.evidence, /【】心声\/弹幕/, 'standalone 【XX视角/番外】 header must not count as danmu/inner-thought')

  // 黑岩/七猫真实格式：###第1章 首节内嵌导语以行末 …… 或 ... 结尾，自动识别为 ch1-top-embedded
  for (const [tag, tail] of [['cn-ell', '……'], ['ascii-dots', '...']]) {
    const inlineLeadText = [
      '###第1章 婚宴反杀',
      `结婚第三年，他在家宴上当众把股权质押章递给新来的秘书，我笑着推回离婚协议，转身发出了四十八小时抽贷函${tail}`,
      sectionChunk(950),
      '###第2章 抽薪清算',
      sectionChunk(1000),
    ].join('\n') + '\n'
    const inlineRes = run(writeCase(`inline-lead-${tag}`, inlineLeadText), ['1800', '3000', '2'], 800, false, ['--strict'])
    assert.strictEqual(inlineRes.status, 0, `${tag}: ${inlineRes.stdout}${inlineRes.stderr}`)
    assert.strictEqual(inlineRes.report.lead_placement, 'ch1-top-embedded')
    assert.strictEqual(inlineRes.report.body_verified, true)
  }

  // 3) delivery.short-lead-present：缺少导语或导语 >500 字
  const noLeadWarn = assertSoftOnly(
    writeCase('short-no-lead', body(1000, 6, 'numeric', { includeLead: false })),
    'delivery.short-lead-present'
  )
  assert.deepStrictEqual(softIds(noLeadWarn.normal), ['delivery.short-lead-present'])

  const hugeLead = `${'“当年这笔账你打算怎么算？”\n我把账本摊开，逐条念给满堂亲戚听。\n'.repeat(19)}${body(1000, 6, 'numeric', { includeLead: false })}`
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

  // 5) 导语与第 1 节首 400 字连续 ≥12 字原句倒带复述 → soft warning；正常承接 → strict PASS；中文中点 `······` 内嵌导语可识别。
  const rewindLead = [
    '结婚三周年纪念日，我不顾一切冲进火场救出未婚夫，他父母感动安排我们成婚。',
    '后来白月光回国，他把我的哮喘药换成维生素。',
  ].join('\n')
  const rewindBody = [
    rewindLead,
    '###1.',
    '那天我不顾一切冲进火场救出未婚夫，他父母感动安排我们成婚，现在我重生了。',
    sectionChunk(960),
    ...Array.from({ length: 5 }, (_, i) => `###${i + 2}.\n${sectionChunk(1000)}`),
  ].join('\n') + '\n'
  const rewindWarn = assertSoftOnly(writeCase('short-lead-rewind', rewindBody), 'delivery.short-lead-rewind')
  assert.deepStrictEqual(softIds(rewindWarn.normal), ['delivery.short-lead-rewind'])
  assert.match(rewindWarn.normal.report.soft_warnings[0].evidence, /连续原句倒带复述/)

  const middotEmbedded = [
    '###1.',
    '选美决赛当天他扔下一笔钱离场，八年后顶流重逢却发疯求复合。',
    '······',
    sectionChunk(970),
    ...Array.from({ length: 5 }, (_, i) => `###${i + 2}.\n${sectionChunk(1000)}`),
  ].join('\n') + '\n'
  const middotPass = run(writeCase('short-middot-embedded-lead', middotEmbedded), ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(middotPass.status, 0, middotPass.stdout + middotPass.stderr)
  assert.strictEqual(middotPass.report.lead_placement, 'ch1-top-embedded')

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
  assert.strictEqual(preflight.report.body_verified, false)
  assert.match(preflight.report.note, /未扫描/)
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

  // 6) ### 导语 与 【XX视角】 切镜标头相邻空行豁免，不误报 delivery.blank-lines（--strict 也通过）。
  const exemptBlankBody = [
    '### 导语',
    '',
    DEFAULT_LEAD,
    '',
    '###1.',
    sectionChunk(1000),
    '###2.',
    sectionChunk(1000),
    '###3.',
    '',
    '【程景川视角】',
    '',
    sectionChunk(1000),
    '###4.',
    sectionChunk(1000),
    '###5.',
    sectionChunk(1000),
    '###6.',
    sectionChunk(1000),
  ].join('\n') + '\n'
  const exemptBlankPass = run(writeCase('exempt-lead-pov-blanks', exemptBlankBody), ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(exemptBlankPass.status, 0, exemptBlankPass.stdout + exemptBlankPass.stderr)
  assert.strictEqual(exemptBlankPass.report.ok, true)
  assert.strictEqual(exemptBlankPass.report.raw_visible_chars, exemptBlankPass.report.total_chars)
  assert(exemptBlankPass.report.body_chars > 0 && exemptBlankPass.report.body_chars < exemptBlankPass.report.raw_visible_chars)

  // 7) delivery.short-paywall-ratio：按设定/大纲付费节统计正文累计占比（30%-45% 通过，偏离给纯 advisory）。
  const paywallOkDir = writeCase('paywall-ratio-ok', body(1000, 8))
  fs.writeFileSync(path.join(paywallOkDir, '设定.md'), '- 付费点：第 3 节末\n', 'utf8')
  const paywallOkRes = run(paywallOkDir, ['7500', '9000', '8'], undefined, false, ['--strict'])
  assert.strictEqual(paywallOkRes.status, 0, paywallOkRes.stdout + paywallOkRes.stderr)
  const paywallOkCheck = paywallOkRes.report.checks.find((c) => c.id === 'delivery.short-paywall-ratio')
  assert.match(paywallOkCheck.evidence, /实际累计正文/)

  const paywallDriftDir = writeCase('paywall-ratio-drift', body(1000, 8))
  fs.writeFileSync(path.join(paywallDriftDir, '题材与大纲.md'), '- 付费点：第 5 节末\n', 'utf8')
  const paywallDrift = assertSoftOnly(paywallDriftDir, 'delivery.short-paywall-ratio', ['7500', '9000', '8'])
  assert.deepStrictEqual(softIds(paywallDrift.normal), ['delivery.short-paywall-ratio'])

  // 8) --counts --json 保留 total_chars 并增补 body_chars / raw_visible_chars
  const countsRes = spawnSync(process.execPath, [verifier, '--counts', '--json', validDir], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  assert.strictEqual(countsRes.status, 0, countsRes.stdout + countsRes.stderr)
  const countsJson = JSON.parse(countsRes.stdout)
  assert.strictEqual(countsJson.raw_visible_chars, countsJson.total_chars)
  assert(countsJson.body_chars > 0 && countsJson.body_chars < countsJson.raw_visible_chars)

  // 9) R050 回归：###1. 外层分节 + 首节内嵌导语以独立行 1. 分隔（七猫/黑岩/点众常见形态）不误报样式混用或编号重复；
  //    同时 section_counts 剔除 HTML 注释，与 body_chars 口径一致。
  const numericEmbeddedLead = [
    '###1.',
    DEFAULT_LEAD,
    '1.',
    '<!-- 内部批注不应计入节字数 -->',
    sectionChunk(1000),
    '###2.',
    sectionChunk(1000),
    '###3.',
    sectionChunk(1000),
    '###4.',
    sectionChunk(1000),
    '###5.',
    sectionChunk(1000),
    '###6.',
    sectionChunk(1000),
  ].join('\n') + '\n'
  const numEmbDir = writeCase('numeric-embedded-lead-1dot', numericEmbeddedLead)
  const numEmbRes = run(numEmbDir, ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(numEmbRes.status, 0, numEmbRes.stdout + numEmbRes.stderr)
  assert.strictEqual(numEmbRes.report.ok, true)
  assert.strictEqual(numEmbRes.report.lead_placement, 'ch1-top-embedded')
  assert.strictEqual(numEmbRes.report.section_counts.length, 6)
  const sec1NoComment = numEmbRes.report.section_counts[0].chars
  const numEmbNoCommentBody = numericEmbeddedLead.replace('<!-- 内部批注不应计入节字数 -->\n', '')
  const numEmbRef = run(writeCase('numeric-embedded-lead-ref', numEmbNoCommentBody), ['6000', '8000', '6'], undefined, false, ['--strict'])
  assert.strictEqual(sec1NoComment, numEmbRef.report.section_counts[0].chars)

  // 10) R086 回归：
  //   a) --counts --json 返回 paywall_preview_ratio / median_para_chars / long_dialogue_45_ratio
  //   b) delivery.short-long-dialogue 仅对 ≥45 字长对白占比 >35% 报纯 advisory（--strict 退出 1）
  //   c) delivery.visible-chars 证据明示 raw_visible_chars 与 body_chars
  //   d) 与 measure-short-metrics.js 付费点累计字数与百分比口径完全一致
  const speechBloatLine = '“我今天就把这三年四十六笔银行流水和婚前全款房产证原件全部摊在客厅桌上，你们老郭家少一分钱我都按不当得利起诉冻结账户。”' // 59 quoted chars >= 45
  const speechBloatChunk = [
    ...Array.from({ length: 12 }, () => speechBloatLine),
    ...Array.from({ length: 18 }, () => '她垂下眼没搭话，把单子折齐放回包里。'),
  ].join('\n')
  const speechBloatBody = [
    DEFAULT_LEAD,
    ...Array.from({ length: 6 }, (_, i) => `###${i + 1}.\n${speechBloatChunk}`),
  ].join('\n') + '\n'
  const speechWarn = assertSoftOnly(
    writeCase('short-long-dialogue-bloat', speechBloatBody),
    'delivery.short-long-dialogue',
    ['4000', '9000', '6']
  )
  assert.deepStrictEqual(softIds(speechWarn.normal), ['delivery.short-long-dialogue'])
  const visCheck = speechWarn.normal.report.checks.find((c) => c.id === 'delivery.visible-chars')
  assert.match(visCheck.evidence, /raw_visible_chars=\d+/)
  assert.match(visCheck.evidence, /body_chars=\d+/)

  const midDraftDir = writeCase('mid-draft-counts', body(1100, 3))
  fs.writeFileSync(path.join(midDraftDir, '设定.md'), '- 目标字数：8400 字\n- 付费点：第 3 节末\n', 'utf8')
  const midCountsRes = spawnSync(process.execPath, [verifier, '--counts', '--json', midDraftDir], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  assert.strictEqual(midCountsRes.status, 0, midCountsRes.stdout + midCountsRes.stderr)
  const midCounts = JSON.parse(midCountsRes.stdout)
  assert.strictEqual(typeof midCounts.median_para_chars, 'number')
  assert.strictEqual(typeof midCounts.long_dialogue_45_ratio, 'number')
  assert(midCounts.paywall_preview_ratio > 0.35 && midCounts.paywall_preview_ratio < 0.45, `mid-draft paywall preview should divide by target_chars, got ${midCounts.paywall_preview_ratio}`)

  // Cross-script paywall ratio parity between check-delivery-contract.js and measure-short-metrics.js
  const metricsScript = path.join(repoRoot, 'skills/story-short-analyze/scripts/measure-short-metrics.js')
  const parityDir = writeCase('paywall-parity', `《测试书名》\n${body(1000, 8)}`)
  fs.writeFileSync(path.join(parityDir, '设定.md'), '- 目标字数：8000 字\n- 付费点：第 3 节末\n', 'utf8')
  const parityDeliv = run(parityDir, ['7500', '9000', '8'], undefined, false, ['--strict'])
  assert.strictEqual(parityDeliv.status, 0, parityDeliv.stdout + parityDeliv.stderr)
  const parityMetricsRes = spawnSync(process.execPath, [metricsScript, '--json', '--paywall-section', '3', path.join(parityDir, '正文.md')], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  assert.strictEqual(parityMetricsRes.status, 0, parityMetricsRes.stdout + parityMetricsRes.stderr)
  const parityMetrics = JSON.parse(parityMetricsRes.stdout)
  assert.strictEqual(parityDeliv.report.body_chars, parityMetrics.total_chars)
  const delivPwCheck = parityDeliv.report.checks.find((c) => c.id === 'delivery.short-paywall-ratio')
  const expectedPct = `${(parityMetrics.paywall.char_ratio * 100).toFixed(1)}%`
  assert(
    delivPwCheck.evidence.includes(`${parityMetrics.paywall.cumulative_chars} / ${parityMetrics.total_chars} 字（${expectedPct}）`),
    `paywall parity mismatch: delivery="${delivPwCheck.evidence}" vs metrics=${parityMetrics.paywall.cumulative_chars}/${parityMetrics.total_chars} (${expectedPct})`
  )

  // Standalone onomatopoeia lines (e.g. 砰——！ / 轰——！) must not count as narration em-dashes
  const onoBody = [
    DEFAULT_LEAD,
    '###1.',
    '砰——！',
    sectionChunk(1000),
    '###2.',
    '咚——！',
    sectionChunk(1000),
    '###3.',
    '轰——！',
    sectionChunk(1000),
    '###4.',
    sectionChunk(1000),
  ].join('\n') + '\n'
  const onoRes = run(writeCase('short-onomatopoeia-em-dash', onoBody), ['3500', '5500', '4'], undefined, false, ['--strict'])
  assert.strictEqual(onoRes.status, 0, onoRes.stdout + onoRes.stderr)
  const onoCheck = onoRes.report.checks.find((c) => c.id === 'delivery.short-em-dash')
  assert.match(onoCheck.evidence, /0 处/)

  // Parity: measure-short-metrics.js must also exempt standalone onomatopoeia em-dashes
  const onoMetrics = JSON.parse(spawnSync(process.execPath, [metricsScript, '--json', path.join(tmpRoot, 'short-onomatopoeia-em-dash', '正文.md')], {
    cwd: repoRoot,
    encoding: 'utf8',
  }).stdout)
  assert.strictEqual(onoMetrics.punctuation.em_dash_narration_count, 0)

  // Parity: embedded-lead section[0].chars excludes …… separator (matching measure-short-metrics.js & body_chars)
  const embParityBody = [
    '###第1章 开场',
    DEFAULT_LEAD,
    '……',
    sectionChunk(1000),
    '###第2章 续接',
    sectionChunk(1000),
  ].join('\n') + '\n'
  const embDir = writeCase('embedded-sec1-parity', embParityBody)
  const embCounts = JSON.parse(spawnSync(process.execPath, [verifier, '--counts', '--json', embDir], { cwd: repoRoot, encoding: 'utf8' }).stdout)
  const embMetrics = JSON.parse(spawnSync(process.execPath, [metricsScript, '--json', path.join(embDir, '正文.md')], { cwd: repoRoot, encoding: 'utf8' }).stdout)
  assert.strictEqual(embCounts.sections[0].chars, embMetrics.sections[0].chars)
  assert.strictEqual(embCounts.sections.reduce((s, x) => s + x.chars, 0), embCounts.body_chars)

  // Spaceless ###导语 heading must be treated as structural non-prose (excluded from lead_chars & body_chars)
  const spacelessLeadDir = writeCase('spaceless-lead-heading', `###导语\n${DEFAULT_LEAD}\n###1.\n${sectionChunk(1000)}\n###2.\n${sectionChunk(1000)}\n`)
  const spacedLeadDir = writeCase('spaced-lead-heading', `### 导语\n${DEFAULT_LEAD}\n###1.\n${sectionChunk(1000)}\n###2.\n${sectionChunk(1000)}\n`)
  const spacelessCounts = JSON.parse(spawnSync(process.execPath, [verifier, '--counts', '--json', spacelessLeadDir], { cwd: repoRoot, encoding: 'utf8' }).stdout)
  const spacedCounts = JSON.parse(spawnSync(process.execPath, [verifier, '--counts', '--json', spacedLeadDir], { cwd: repoRoot, encoding: 'utf8' }).stdout)
  assert.strictEqual(spacelessCounts.lead_chars, spacedCounts.lead_chars)
  assert.strictEqual(spacelessCounts.body_chars, spacedCounts.body_chars)

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
