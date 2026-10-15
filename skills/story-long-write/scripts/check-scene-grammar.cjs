#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')

const FIELDS = [
  '压力', '危机层', '危机事实', '短线目标', '阻碍数', '阻碍',
  '收获类', '收获物', '展示对象', '旧认知', '展示落点', '章尾新坑',
]

const STRICT = new Set(['高压', '推进'])
const RELAXED = new Set(['低压', '修炼', '过场', '关系', '信息'])
const LAYERS = ['生理', '安全', '归属', '尊重', '自我实现']
const GAIN_TYPES = ['身份', '资源', '能力', '尊重', '认同']
const SHOW_RESULTS = ['改口', '收手', '不肯认', '换评价']
const GAIN_BANS = ['变强了', '感到欣慰', '众人震惊', '终于明白']
const HOOK_BANS = ['欣慰', '终于明白', '尘埃落定', '一切结束']
const PROSE_BANS = [
  '众人震惊', '全场寂静', '全场死寂', '整个大厅陷入死寂',
  '众人这才明白', '他终于明白', '他终于感受到',
]
const ENDING_BANS = ['感到欣慰', '终于明白', '尘埃落定', '一切都结束', '一切结束']
const GROUP_WORDS = ['众人', '全场', '所有人', '大家']

function hanCount(value) {
  const match = value.match(/[\u4e00-\u9fff]/g)
  return match ? match.length : 0
}

function isUnfilled(value) {
  if (value == null) return true
  const trimmed = value.trim()
  if (!trimmed) return true
  if (trimmed === '[待补充]') return true
  return /^\{[\s\S]+\}$/.test(trimmed)
}

function fieldValue(text, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = text.match(new RegExp(`^\\s*[-*+]\\s*\\*{0,2}${escaped}\\*{0,2}\\s*[：:]\\s*(.*)$`, 'm'))
  return match ? match[1].trim() : null
}

function makeCheck(id, ok, evidence, expected, repair, severity = 'blocking') {
  return { id, ok, severity, evidence, expected, repair }
}

function readUtf8(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    return { ok: text.trim().length > 0, text }
  } catch (error) {
    return { ok: false, text: '', error: error.message }
  }
}

function legacyFilled(text) {
  if (fieldValue(text, '危机层') != null) return false
  return ['危机', '收获', '展示', '章尾新坑'].some((label) => {
    const value = fieldValue(text, label)
    return value != null && !isUnfilled(value)
  })
}

function assessOutline(text) {
  if (legacyFilled(text)) {
    return [
      makeCheck(
        'scene.legacy',
        false,
        '场面仍是危机/收获/展示/章尾四行',
        '改成十二字段计数表',
        '删掉旧四行，按 scene-grammar.md 的字段重写；未知写 [待补充]。',
      ),
    ]
  }

  const values = Object.fromEntries(FIELDS.map((label) => [label, fieldValue(text, label)]))
  const present = FIELDS.filter((label) => values[label] != null)
  if (present.length === 0) {
    return [makeCheck('scene.absent', true, '没有场面块', '旧纲可以不写场面块', '无需修复。', 'advisory')]
  }
  if (FIELDS.every((label) => isUnfilled(values[label]))) {
    return [makeCheck('scene.blank', true, '场面十二字段都还是待补充', '未填的计数表通过', '无需修复。', 'advisory')]
  }

  const checks = []
  const pressure = values['压力']
  const mode = STRICT.has(pressure) ? 'strict' : RELAXED.has(pressure) ? 'relaxed' : null
  checks.push(makeCheck(
    'scene.pressure',
    mode !== null,
    mode ? `压力=${pressure}` : `压力无法计数：${pressure ?? '缺失'}`,
    '压力只能是高压、推进、低压、修炼、过场、关系、信息之一',
    '把压力改成七个词里的一个。',
  ))

  const layer = values['危机层']
  checks.push(makeCheck(
    'scene.crisis-layer',
    LAYERS.includes(layer),
    `危机层=${layer ?? '缺失'}`,
    '危机层恰好是生理、安全、归属、尊重、自我实现之一',
    '只留一个层名，把具体的事挪到危机事实。',
  ))

  const fact = values['危机事实']
  const factOk = !isUnfilled(fact) && hanCount(fact) >= 8 && !LAYERS.includes(fact)
  checks.push(makeCheck(
    'scene.crisis-fact',
    factOk,
    `危机事实=${fact ?? '缺失'}（汉字 ${hanCount(fact || '')}）`,
    '危机事实至少 8 个汉字，且不能只写层名',
    '写成谁在这一场失去或即将失去什么。',
  ))

  const goal = values['短线目标']
  checks.push(makeCheck(
    'scene.goal',
    !isUnfilled(goal) && hanCount(goal) >= 4 && !/[；;]/.test(goal),
    `短线目标=${goal ?? '缺失'}`,
    '短线目标只有 1 个，至少 4 个汉字，不含分号',
    '留这一场要办成的一件事。',
  ))

  const countRaw = values['阻碍数']
  const count = countRaw === '0' || countRaw === '1' || countRaw === '2' ? Number(countRaw) : null
  const countOk = count !== null && (mode === 'strict' ? count >= 1 : mode === 'relaxed' ? count <= 1 : false)
  checks.push(makeCheck(
    'scene.obstacle-count',
    countOk,
    `阻碍数=${countRaw ?? '缺失'}，压力=${pressure ?? '缺失'}`,
    '严门槛是 1 或 2；宽门槛是 0 或 1',
    '按压力改整数。低压类不要为了有戏写成 2。',
  ))

  const obstacle = values['阻碍']
  const obstacleOk = count === 0
    ? obstacle === '无'
    : count !== null && obstacle !== '无' && !isUnfilled(obstacle) && hanCount(obstacle) >= 8
  checks.push(makeCheck(
    'scene.obstacle',
    obstacleOk,
    `阻碍=${obstacle ?? '缺失'}`,
    '阻碍数为 0 时写「无」；否则至少 8 个汉字，写得手之前的那一次',
    '与阻碍数对齐。不新造细纲里没有的拦阻。',
  ))

  const gainType = values['收获类']
  const gainTypeOk = GAIN_TYPES.includes(gainType) || (mode === 'relaxed' && gainType === '无')
  checks.push(makeCheck(
    'scene.gain-type',
    gainTypeOk,
    `收获类=${gainType ?? '缺失'}`,
    '严门槛恰好一类；宽门槛可以写「无」',
    '从身份、资源、能力、尊重、认同里留一个。',
  ))

  const gain = values['收获物']
  const gainBanned = GAIN_BANS.find((phrase) => (gain || '').includes(phrase))
  const gainOk = gainType === '无'
    ? gain === '无'
    : gainTypeOk && !isUnfilled(gain) && hanCount(gain) >= 4 && !gainBanned
  checks.push(makeCheck(
    'scene.gain',
    gainOk,
    `收获物=${gain ?? '缺失'}`,
    '一件可见物，至少 4 个汉字；禁止变强了、感到欣慰、众人震惊、终于明白',
    '写成这一场拿到或失去的那样东西。收获类为无时写「无」。',
  ))

  const target = values['展示对象']
  const targetBlank = isUnfilled(target)
  const grouped = target && (GROUP_WORDS.some((word) => target.includes(word)) || splitPeople(target).length > 1)
  const targetOk = (mode === 'relaxed' && target === '无') || (!targetBlank && target !== '无' && !grouped)
  checks.push(makeCheck(
    'scene.show-target',
    targetOk,
    `展示对象=${target ?? '缺失'}`,
    '恰好 1 人；宽门槛可以写「无」',
    '留一个在场者的名字。不写众人、全场，也不把两个人写在一格。',
  ))

  const belief = values['旧认知']
  const beliefOk = target === '无' ? belief === '无' : !isUnfilled(belief) && hanCount(belief) >= 8
  checks.push(makeCheck(
    'scene.old-belief',
    beliefOk,
    `旧认知=${belief ?? '缺失'}`,
    '展示对象得手前的一句台词或动作，至少 8 个汉字',
    '写他说出或做出的判断。展示对象为无时写「无」。',
  ))

  const showResult = values['展示落点']
  const showOk = target === '无' ? showResult === '无' : SHOW_RESULTS.includes(showResult)
  checks.push(makeCheck(
    'scene.show-result',
    showOk,
    `展示落点=${showResult ?? '缺失'}`,
    '改口、收手、不肯认、换评价之一',
    '留一个看得见的落点。展示对象为无时写「无」。',
  ))

  const hook = values['章尾新坑']
  const hookBanned = HOOK_BANS.find((phrase) => (hook || '').includes(phrase))
  const hookOk = !isUnfilled(hook) && hanCount(hook) >= 8 && !hookBanned && (mode !== 'relaxed' || hook.includes('阶段'))
  checks.push(makeCheck(
    'scene.next-hook',
    hookOk,
    `章尾新坑=${hook ?? '缺失'}`,
    '至少 8 个汉字；宽门槛必须含「阶段」；禁止欣慰、终于明白、尘埃落定、一切结束',
    '严门槛写下一个麻烦。宽门槛写成「阶段：…」。',
  ))

  return checks
}

function splitPeople(value) {
  return value.split(/[、,，]|和|与|及/).map((part) => part.trim()).filter((part) => hanCount(part) > 0)
}

function lastParagraph(text) {
  const parts = text.replace(/\r\n/g, '\n').split(/\n{2,}/).map((part) => part.trim()).filter(Boolean)
  return parts.length ? parts[parts.length - 1] : ''
}

function assessProse(text) {
  const checks = PROSE_BANS.map((phrase) => {
    const count = text.split(phrase).length - 1
    return makeCheck(
      `scene.prose.ban.${phrase}`,
      count === 0,
      count === 0 ? `${phrase}=0` : `${phrase}=${count}`,
      '集体反应或叙述者宣布的句子出现 0 次',
      '删掉这句，改成某一个在场者的动作或台词。',
    )
  })
  const ending = lastParagraph(text)
  const hit = ENDING_BANS.find((phrase) => ending.includes(phrase))
  checks.push(makeCheck(
    'scene.prose.ending',
    !hit,
    hit ? `章尾含「${hit}」` : '章尾不是感悟',
    '最后一个非空段不写欣慰、终于明白、尘埃落定、一切结束',
    '停在下一个麻烦，或低压章的阶段目标上。不另起一段感悟。',
  ))
  return checks
}

function report(file, mode, checks) {
  const failures = checks.filter((check) => !check.ok && check.severity === 'blocking')
  const advisories = checks.filter((check) => !check.ok && check.severity === 'advisory')
  return {
    schema_version: 1,
    verifier: 'story-long-write.scene-grammar',
    file,
    mode,
    ok: failures.length === 0,
    checks,
    failures,
    advisories,
    repair_scope: failures.map((failure) => ({
      id: failure.id,
      evidence: failure.evidence,
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

function verifyOutlineFile(file) {
  const read = readUtf8(file)
  if (!read.ok) {
    return report(path.resolve(file), 'outline', [
      makeCheck('scene.readable', false, read.error || '文件是空的', '细纲可读', '确认路径。'),
    ])
  }
  return report(path.resolve(file), 'outline', assessOutline(read.text))
}

function verifyProseFile(file) {
  const read = readUtf8(file)
  if (!read.ok) {
    return report(path.resolve(file), 'prose', [
      makeCheck('scene.readable', false, read.error || '文件是空的', '正文可读', '确认路径。'),
    ])
  }
  return report(path.resolve(file), 'prose', assessProse(read.text))
}

function parseArgs(argv) {
  let project = null
  let chapter = null
  let prose = null
  let selfTest = false
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--json') continue
    if (arg === '--self-test') {
      selfTest = true
      continue
    }
    if (arg === '--project' || arg === '--chapter' || arg === '--prose') {
      if (index + 1 >= argv.length || argv[index + 1].startsWith('--')) return null
      const value = argv[index + 1]
      index += 1
      if (arg === '--project') project = value
      else if (arg === '--chapter') chapter = value
      else prose = value
      continue
    }
    return null
  }
  if (selfTest) return project || chapter || prose ? null : { selfTest: true }
  if (prose) return project || chapter ? null : { prose }
  if (project || chapter) {
    if (!project || !chapter || !/^\d+$/.test(chapter)) return null
    return { project, chapter }
  }
  return null
}

function strictSample() {
  return [
    '- 压力：高压',
    '- 危机层：尊重',
    '- 危机事实：王婶当众说他私吞了铺租',
    '- 短线目标：把这个月的铺租要回来',
    '- 阻碍数：1',
    '- 阻碍：账房先咬定簿子上没有这笔',
    '- 收获类：资源',
    '- 收获物：要回四十吊铺租',
    '- 展示对象：王婶',
    '- 旧认知：王婶说他根本拿不出簿子',
    '- 展示落点：改口',
    '- 章尾新坑：账房连夜把印鉴换了一颗',
  ].join('\n')
}

function selfTest() {
  const cases = [
    ['absent', '', true],
    ['blank', FIELDS.map((label) => `- ${label}：[待补充]`).join('\n'), true],
    ['strict-ok', strictSample(), true],
    ['strict-no-obstacle', strictSample().replace('- 阻碍数：1', '- 阻碍数：0').replace('- 阻碍：账房先咬定簿子上没有这笔', '- 阻碍：无'), false],
    ['two-layers', strictSample().replace('- 危机层：尊重', '- 危机层：尊重和安全'), false],
    ['group', strictSample().replace('- 展示对象：王婶', '- 展示对象：众人'), false],
    ['two-people', strictSample().replace('- 展示对象：王婶', '- 展示对象：王婶和账房'), false],
    ['empty-gain', strictSample().replace('- 收获物：要回四十吊铺租', '- 收获物：变强了'), false],
    ['relaxed-ok', [
      '- 压力：低压', '- 危机层：安全', '- 危机事实：夜里铺门的锁被人换过',
      '- 短线目标：先看住这一夜', '- 阻碍数：0', '- 阻碍：无',
      '- 收获类：无', '- 收获物：无', '- 展示对象：无', '- 旧认知：无', '- 展示落点：无',
      '- 章尾新坑：阶段：天亮再去对锁匠',
    ].join('\n'), true],
    ['relaxed-no-stage', [
      '- 压力：低压', '- 危机层：安全', '- 危机事实：夜里铺门的锁被人换过',
      '- 短线目标：先看住这一夜', '- 阻碍数：0', '- 阻碍：无',
      '- 收获类：无', '- 收获物：无', '- 展示对象：无', '- 旧认知：无', '- 展示落点：无',
      '- 章尾新坑：他把门锁又检查了一遍',
    ].join('\n'), false],
    ['legacy', '- 危机：被人看不起\n- 收获：变强了\n- 展示：打脸\n- 章尾新坑：新的麻烦', false],
    ['legacy-blank', '- 危机：[待补充]\n- 收获：[待补充]\n- 展示：[待补充]\n- 章尾新坑：[待补充]', true],
  ]
  const proseOk = assessProse('王婶把簿子推回来。\n\n账房连夜出了门。').every((check) => check.ok)
  const proseBan = assessProse('众人震惊。\n\n他收起簿子。').some((check) => !check.ok)
  const proseEnd = assessProse('他收起簿子。\n\n他终于明白了一切。').some((check) => !check.ok)
  const failed = cases.filter((entry) => assessOutline(entry[1]).every((check) => check.ok || check.severity !== 'blocking') !== entry[2])
  if (!proseOk) failed.push(['prose-ok'])
  if (!proseBan) failed.push(['prose-ban'])
  if (!proseEnd) failed.push(['prose-end'])
  if (failed.length) {
    process.stderr.write(`scene grammar self-test failed: ${failed.map((entry) => entry[0]).join(', ')}\n`)
    return 1
  }
  process.stdout.write(`scene grammar self-test ok (${cases.length + 3})\n`)
  return 0
}

function main(argv) {
  const parsed = parseArgs(argv)
  if (!parsed) {
    process.stderr.write('用法: node scripts/check-scene-grammar.cjs --json --project <书目录> --chapter N | --json --prose <正文路径> | --self-test\n')
    return 2
  }
  if (parsed.selfTest) return selfTest()
  const result = parsed.prose
    ? verifyProseFile(parsed.prose)
    : (() => {
        const resolved = resolveChapter(parsed.project, parsed.chapter)
        if (resolved.error) {
          process.stderr.write(`${resolved.error}\n`)
          return null
        }
        return verifyOutlineFile(resolved.file)
      })()
  if (!result) return 2
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  return result.ok ? 0 : 1
}

if (require.main === module) process.exitCode = main(process.argv.slice(2))

module.exports = { assessOutline, assessProse, FIELDS, PROSE_BANS, ENDING_BANS }
