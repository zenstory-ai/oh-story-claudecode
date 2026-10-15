#!/usr/bin/env node
'use strict'

const fs = require('node:fs')

const PHRASES = [
  '一抹浅笑', '一丝苦笑', '红了一瞬', '瞳孔骤然一缩', '瞳孔地震',
  '百感交集', '五味杂陈', '心猛地一沉', '心头一颤', '涌上心口',
  '不禁红了眼眶', '泪如雨下', '说不出的', '莫名的情绪',
  '空气仿佛凝固', '凝固了空气', '时间仿佛凝固', '空气中飘荡着',
  '氛围感', '画面感', '构成了一幅', '难以捉摸的', '轮廓分明', '轮廓柔和',
  '指节分明', '描绘着', '跃动着', '守候着', '铭记着', '一丝凉意', '悄然地',
  '看不透', '意味深长地', '从这一刻起', '人生将', '嗓音低沉', '标志着',
  '退后了半步', '折了开来',
]

const TIME_LINE = /^(?:第)?[0-9０-９一二三四五六七八九十百千万两]+(?:个)?(?:秒钟|秒|分钟|分|刻钟|刻|小时|天|年|日|夜|更|点钟|点|息|下)[。！？…]*$/
const SOUND_LINE = /^[嗡砰啪咚哗咔嘶轰嘭当锵吱嘎嗒嚓啊噢哼—\-～~。！？…]+$/
const NEGATION_LINE = /^(?:不是|没有|并非|难道)[\u4e00-\u9fff]{0,6}[。！？]?$/
const SINGLE_NEGATION = /^(?:不|没)[。！？]$/
const TITLE_LINE = /^(?:#{1,6}\s|第[0-9０-９一二三四五六七八九十百千万两]+章)/
const DIVIDER_LINE = /^[-—*_]{3,}$/

function hanCount(value) {
  const match = value.match(/[\u4e00-\u9fff]/g)
  return match ? match.length : 0
}

function stripQuotes(value) {
  return value
    .replace(/「[^」]*」/g, '')
    .replace(/『[^』]*』/g, '')
    .replace(/“[^”]*”/g, '')
    .replace(/"[^"]*"/g, '')
}

function makeCheck(id, ok, evidence, expected, repair) {
  return { id, ok, severity: 'blocking', evidence, expected, repair }
}

function assessProse(text, options = {}) {
  const allowNi = options.allowNi === true
  const source = String(text || '').replace(/^\uFEFF/, '')
  const checks = []

  for (const phrase of PHRASES) {
    const hits = source.split(phrase).length - 1
    checks.push(makeCheck(
      `surface.phrase.${phrase}`,
      hits === 0,
      hits === 0 ? '0' : `${phrase} × ${hits}`,
      '0',
      `删掉「${phrase}」，改成这句里已经有的动作或物件。`,
    ))
  }

  const lines = source.split(/\r?\n/)
  let niHits = 0
  let niExcerpt = ''
  const shortFailures = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || DIVIDER_LINE.test(trimmed) || TITLE_LINE.test(trimmed)) continue
    const outside = stripQuotes(trimmed)
    if (!allowNi) {
      const found = outside.match(/你/g)
      if (found) {
        niHits += found.length
        if (!niExcerpt) niExcerpt = trimmed.slice(0, 40)
      }
    }
    const han = hanCount(trimmed)
    if (han === 0 || han > 10) continue
    if (hanCount(outside) === 0) continue
    if (TIME_LINE.test(outside.trim()) || SOUND_LINE.test(outside.trim())) continue
    if (NEGATION_LINE.test(outside.trim()) || SINGLE_NEGATION.test(outside.trim())) continue
    shortFailures.push(trimmed.slice(0, 40))
  }

  if (!allowNi) {
    checks.push(makeCheck(
      'surface.ni',
      niHits === 0,
      niHits === 0 ? '0' : `引号外「你」 × ${niHits}：${niExcerpt}`,
      '0',
      '引号外的「你」改成名字或「他 / 她」。引号里的话不动。',
    ))
  }

  checks.push(makeCheck(
    'surface.short',
    shortFailures.length === 0,
    shortFailures.length === 0 ? '0' : shortFailures.slice(0, 5).join(' | '),
    '0',
    '不足 11 个汉字的动作段写成时间、拟声、否定顿，或补成完整句。短台词留在引号里。',
  ))

  return checks
}

function summarize(checks) {
  const failures = checks.filter((item) => !item.ok)
  return {
    schema_version: 1,
    verifier: 'story-long-write.prose-surface',
    mode: 'prose',
    ok: failures.length === 0,
    failures,
    repair_scope: failures.map((item) => item.id),
  }
}

function verifyProse(text, options) {
  return summarize(assessProse(text, options))
}

function readUtf8(file) {
  try {
    return { ok: true, text: fs.readFileSync(file, 'utf8') }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function assertCase(name, text, options, expectOk) {
  const result = verifyProse(text, options)
  if (result.ok !== expectOk) {
    throw new Error(`${name}: expected ok=${expectOk}, got ${JSON.stringify(result.failures.map((item) => item.id))}`)
  }
}

function selfTest() {
  const clean = [
    '林述把伞收了，伞骨在台阶上磕出一声。',
    '「你先走。」她说，眼睛仍看着雨。',
    '一秒。',
    '嗡——',
    '不是巧合。',
    '「嗯。」',
    '# 第三章 雨',
  ].join('\n')
  assertCase('clean', clean, {}, true)
  assertCase('phrase', `${clean}\n她露出一抹浅笑。`, {}, false)
  assertCase('ni', `${clean}\n林述看着你，没有再把那句话说完。`, {}, false)
  assertCase('allow-ni', `${clean}\n林述看着你，没有再把那句话说完。`, { allowNi: true }, true)
  assertCase('short-action', `${clean}\n他没停。`, {}, false)
  assertCase('quoted-ni', '「你倒是说说看。」她把杯子放下，水沿着桌沿走了一小段。', {}, true)
  assertCase('phrase-zero-on-bare', '窗外有一丝风，她没有一抹眼泪。', {}, true)
  const bad = verifyProse('他没停。\n她露出一抹浅笑，然后看着你。')
  const ids = bad.failures.map((item) => item.id)
  if (!ids.includes('surface.phrase.一抹浅笑') || !ids.includes('surface.ni') || !ids.includes('surface.short')) {
    throw new Error(`combined: ${ids.join(',')}`)
  }
  if (PHRASES.length !== 39) throw new Error(`phrase count ${PHRASES.length}`)
  process.stdout.write('prose surface self-test ok (8)\n')
  return 0
}

function parseArgs(argv) {
  const parsed = { prose: '', allowNi: false, selfTest: false, json: false }
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index]
    if (token === '--json') parsed.json = true
    else if (token === '--self-test') parsed.selfTest = true
    else if (token === '--allow-ni') parsed.allowNi = true
    else if (token === '--prose') parsed.prose = argv[++index] || ''
    else return { error: `未知参数 ${token}` }
  }
  return parsed
}

function main(argv) {
  const parsed = parseArgs(argv)
  if (parsed.error || (!parsed.selfTest && !parsed.prose)) {
    process.stderr.write('用法: node scripts/check-prose-surface.cjs --json --prose <正文路径> [--allow-ni] | --self-test\n')
    return 2
  }
  if (parsed.selfTest) return selfTest()
  const file = readUtf8(parsed.prose)
  if (!file.ok) {
    process.stderr.write(`${file.error}\n`)
    return 2
  }
  const result = verifyProse(file.text, { allowNi: parsed.allowNi })
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { assessProse, verifyProse, PHRASES }
