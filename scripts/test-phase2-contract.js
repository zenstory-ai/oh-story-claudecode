#!/usr/bin/env node
'use strict'

const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const repoRoot = path.resolve(__dirname, '..')
const verifier = path.join(repoRoot, 'skills/story-short-write/scripts/check-phase2-contract.js')
const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'phase2-contract-'))

// 现行列名（0.10 起，workflow-design 的小节大纲模板只要五列）。
const headers = ['在全篇哪一段', '这节发生的事', '情绪', '节尾停在哪', '目标字数']
// 0.10 早期草案的十列表头：多出的五列现在是可选列，照样通过。
const tenColumnHeaders = [
  '在全篇哪一段', '主事件', '这节发生的事', '情绪', '人物/关系变化', '前因后果',
  '读者新获知什么', '节尾停在哪', '伏笔/物件', '目标字数',
]
// 0.9.x 落盘的 12 列表头；改名后仍须被接受。
const v09Headers = [
  '结构段/五段功能', '主事件', '情节推进', '情绪', '人物/关系变化', '因果/逻辑链',
  '读者新获知什么', '结尾承接/钩子', '伏笔/物件', '场景形态', '对白作用', '目标字数',
]
// v0.7.8 及更早的项目落盘的旧列名。
const legacyHeaders = v09Headers.map(
  (name, index) => ({ 2: '子事件×3-5', 9: '动静', 10: '对话密度' }[index] || name)
)

// 按列名填格子，表头怎么排都能对上。
function outlineRow(stage, index, hook, { headerRow = headers, progression = (i) => `主角发现线索${i}，当场留下证据` } = {}) {
  const byName = {
    在全篇哪一段: stage, '结构段/五段功能': stage,
    这节发生的事: progression(index), 情节推进: progression(index), '子事件×3-5': progression(index),
    情绪: `疑惑→紧张${index}`,
    节尾停在哪: hook, '结尾承接/钩子': hook,
    目标字数: '1000',
    主事件: `主角处理事件${index}`,
    '人物/关系变化': `关系压力上升${index}`,
    前因后果: `发现异常${index}，决定继续查`, '因果/逻辑链': `发现异常${index}，决定继续查`,
    读者新获知什么: `读者获知线索${index}`,
    '伏笔/物件': `旧钥匙${index}`,
  }
  return headerRow.map((name) => byName[name] ?? (index % 2 ? '行动' : '证据核验'))
}

function validSettings(overrides = {}) {
  const values = {
    platform: '知乎盐言',
    genre: '题材：悬疑',
    moves: ['日常违和切入：第 1 节', '一层层揭开：第 3、5、6 节', '证物翻转：第 6 节'],
    villain: '反派：没有（冲突来自主角对自我记忆的误判）',
    reversalType: '信息反转',
    reversal: '反转在：第 6 节（共 8 节）',
    paywall: '付费点：第 4 节末',
    target: '8000',
    ...overrides,
  }
  return [
    '## 短篇核心框架',
    '### 基本信息',
    `- 目标平台：${values.platform}`,
    `- 目标字数：${values.target} 字`,
    '### 这篇用的套路',
    ...values.moves.map((move) => `- ${move}`),
    '### 文风约定',
    '- 无',
    '## 构思要点',
    `- ${values.genre}`,
    `- ${values.villain}`,
    `- 反转类型：${values.reversalType}`,
    `- ${values.reversal}`,
    `- ${values.paywall}`,
    '',
  ].join('\n')
}

// 0.9.x 的设计校验区写法：题材写文件路径、核心招式一行、反派设计、反转位置带算式。
function v09Settings(overrides = {}) {
  const values = {
    genre: 'references/genre-styles/悬疑.md',
    moves: '日常违和切入；延迟剥洋葱；证物翻转',
    villain: '反派设计：不适用（冲突来自主角对自我记忆的误判）',
    reversal: '反转位置：第 6 节 ÷ 共 8 节 = 75%',
    ...overrides,
  }
  return [
    '# 设定',
    '## 基本信息',
    '- 目标平台：知乎盐言',
    '- 目标字数：8000 字',
    '### 题材招式',
    '- 日常违和切入：第 1 节',
    '## Phase 2 设计校验',
    `- 题材参考：\`${values.genre}\``,
    `- 核心招式：${values.moves}`,
    `- ${values.villain}`,
    '- 反转类型：信息反转',
    `- ${values.reversal}`,
    '- 付费点：第 4 节末',
    '',
  ].join('\n')
}

function validOutline({ includePaywall = true, headerRow = headers, ...rowOpts } = {}) {
  const opts = { headerRow, ...rowOpts }
  const rows = [
    outlineRow('开头', 1, '她决定去查监控', opts),
    outlineRow('铺垫', 2, '她收到没有寄件人的照片', opts),
    outlineRow('铺垫', 3, '照片背后写着她的旧名', opts),
    outlineRow('升级', 4, includePaywall ? '门后传来自己的声音（付费点）' : '门后传来自己的声音', opts),
    outlineRow('升级', 5, '旧照片上的人动了', opts),
    outlineRow('反转', 6, '她发现记忆属于另一个人', opts),
    outlineRow('反转', 7, '真正的主人敲响房门', opts),
    outlineRow('结尾', 8, '她把钥匙留在门外', opts),
  ]
  return [
    '# 小节大纲',
    `| ${headerRow.join(' | ')} |`,
    `| ${headerRow.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${row.join(' | ')} |`),
    '',
  ].join('\n')
}

function writeCase(name, settings, outline) {
  const dir = path.join(tmpRoot, name)
  fs.mkdirSync(dir, { recursive: true })
  if (settings !== null) fs.writeFileSync(path.join(dir, '设定.md'), settings, 'utf8')
  if (outline !== null) fs.writeFileSync(path.join(dir, '小节大纲.md'), outline, 'utf8')
  return dir
}

function run(dir, extraArgs = []) {
  const result = spawnSync(process.execPath, [verifier, '--json', ...extraArgs, dir], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  let report = null
  if (result.stdout.trim()) report = JSON.parse(result.stdout)
  return { ...result, report }
}

function failureIds(result) {
  return result.report.failures.map((failure) => failure.id)
}

try {
  const good = run(writeCase('valid', validSettings(), validOutline()))
  assert.strictEqual(good.status, 0, good.stdout + good.stderr)
  assert.strictEqual(good.report.ok, true)
  assert.deepStrictEqual(good.report.failures, [])

  // 平台表六个平台都要识别；旧项目写的「知乎盐选」「盐选」「番茄短篇」继续通过；作者没定平台写「未定」。
  for (const platform of ['番茄', '七猫', '黑岩', '红果', '小程序', '点众', '盐言', '知乎盐选', '盐选', '番茄短篇', '未定']) {
    const named = run(writeCase(`platform-${platform}`, validSettings({ platform }), validOutline()))
    assert.strictEqual(named.status, 0, named.stdout + named.stderr)
    assert.strictEqual(
      named.report.checks.find((check) => check.id === 'phase2.platform-declared').evidence,
      `目标平台：${platform}`
    )
  }
  const unknownPlatform = run(writeCase('platform-unknown', validSettings({ platform: '起点' }), validOutline()))
  assert.strictEqual(unknownPlatform.status, 1)
  assert.deepStrictEqual(failureIds(unknownPlatform), ['phase2.platform-declared'])

  // 老书不迁移也能继续写：0.9.x 的设定写法和 12 列表头、v0.7.8 的旧列名都要通过。
  for (const [name, headerRow] of [['v09', v09Headers], ['legacy', legacyHeaders]]) {
    const old = run(writeCase(`old-book-${name}`, v09Settings(), validOutline({ headerRow })))
    assert.strictEqual(old.status, 0, old.stdout + old.stderr)
    assert.match(old.report.checks.find((check) => check.id === 'phase2.outline-header').evidence, /旧列名/)
  }
  // 旧写法里算错的百分比不再拦（只核节号在大纲之内）。
  const oldMath = run(writeCase('old-reversal-math', v09Settings({ reversal: '反转位置：第 6 节 ÷ 共 8 节 = 60%' }), validOutline()))
  assert.strictEqual(oldMath.status, 0, oldMath.stdout)

  // 可选列加进来照样通过（十列草案、对话两列）；认不出的列、缺列都判表头错。
  for (const [name, headerRow] of [
    ['ten-columns', tenColumnHeaders],
    ['dialogue-columns', [...headers.slice(0, 4), '这节靠什么推进', '对话改变了什么', '目标字数']],
  ]) {
    const withOptional = run(writeCase(`optional-${name}`, validSettings(), validOutline({ headerRow })))
    assert.strictEqual(withOptional.status, 0, withOptional.stdout + withOptional.stderr)
  }
  const missingColumn = run(writeCase('missing-column', validSettings(), validOutline({ headerRow: headers.filter((name) => name !== '情绪') })))
  assert.strictEqual(missingColumn.status, 1)
  assert(failureIds(missingColumn).includes('phase2.outline-header'))
  const unknownColumn = run(writeCase(
    'unknown-column',
    validSettings(),
    validOutline({ headerRow: headers.map((name, index) => (index === 2 ? '随便一列' : name)) })
  ))
  assert.strictEqual(unknownColumn.status, 1)
  assert(failureIds(unknownColumn).includes('phase2.outline-header'))

  // 「这节发生的事」不要功能标签，但不能留空。
  const emptyProgression = run(writeCase(
    'empty-progression',
    validSettings(),
    validOutline({ progression: () => '' })
  ))
  assert.strictEqual(emptyProgression.status, 1)
  assert(failureIds(emptyProgression).includes('phase2.outline-subevents'))

  const explicitShortTarget = run(writeCase(
    'explicit-short-target',
    validSettings({ target: '6000' }),
    validOutline().replaceAll('| 1000 |', '| 750 |')
  ))
  assert.strictEqual(explicitShortTarget.status, 0, explicitShortTarget.stdout + explicitShortTarget.stderr)

  // 用户给的是字数区间时，大纲合计落在区间内即通过。
  const rangeTarget = run(writeCase(
    'range-target',
    validSettings({ target: '6000-8000 字' }),
    validOutline().replaceAll('| 1000 |', '| 900 |')
  ))
  assert.strictEqual(rangeTarget.status, 0, rangeTarget.stdout + rangeTarget.stderr)
  assert.strictEqual(rangeTarget.report.ok, true)

  const rangeTargetOutside = run(writeCase(
    'range-target-outside',
    validSettings({ target: '6000-8000 字' }),
    validOutline().replaceAll('| 1000 |', '| 500 |')
  ))
  assert.strictEqual(rangeTargetOutside.status, 1)
  assert.deepStrictEqual(failureIds(rangeTargetOutside), ['phase2.target-word-sum'])
  assert.match(rangeTargetOutside.report.failures[0].evidence, /6000-8000/)

  // 按「万」写的目标字数换算成整数再比对。
  for (const [name, target] of [['wan-range', '约 0.75-0.9 万'], ['wan-single', '0.8万']]) {
    const wan = run(writeCase(name, validSettings({ target }), validOutline()))
    assert.strictEqual(wan.status, 0, wan.stdout + wan.stderr)
  }

  // 未填写的模板占位符不算完成设计。
  const placeholders = run(writeCase(
    'unfilled-placeholders',
    validSettings({
      moves: ['{套路名}：{本篇怎么用}', '{套路名}：{落在哪几节}'],
      reversalType: '{身份/视角/动机/时间线/信息/认知/无反转}',
    }),
    validOutline()
  ))
  assert.strictEqual(placeholders.status, 1)
  assert(failureIds(placeholders).includes('phase2.no-template-placeholders'))

  const missingSettings = run(writeCase('missing-settings', null, validOutline()))
  assert.strictEqual(missingSettings.status, 1)
  assert(failureIds(missingSettings).includes('phase2.settings-readable'))

  // 题材只写题材名，脚本对到 genre-styles；冷门写「冷门：公式名」；旧写法的文件路径照认、路径错照拦。
  for (const genre of ['题材：追妻火葬场（古代变体）', '题材：冷门：职场逆袭', '题材参考：`references/genre-writing-formulas.md`']) {
    const ok = run(writeCase(`genre-${genre.length}`, validSettings({ genre }), validOutline()))
    assert.strictEqual(ok.status, 0, ok.stdout + ok.stderr)
  }
  for (const [name, settings] of [
    ['bad-genre-name', validSettings({ genre: '题材：不存在' })],
    ['bad-genre-path', v09Settings({ genre: 'references/genre-styles/不存在.md' })],
  ]) {
    const bad = run(writeCase(name, settings, validOutline()))
    assert.strictEqual(bad.status, 1)
    assert.deepStrictEqual(failureIds(bad), ['phase2.genre-reference-declared'])
    assert.match(bad.report.failures[0].evidence, /不存在/)
  }

  // 旧写法「核心招式」一行里，招式说明的顿号/逗号属于招式内部描述，只有分号才是分隔符。
  const movesWithInnerPunctuation = run(writeCase(
    'moves-with-inner-punctuation',
    v09Settings({ moves: '白月光触发链（旧物、旧地、旧称呼三连触发）；信物翻转，从定情物变成证据；火葬场预告' }),
    validOutline()
  ))
  assert.strictEqual(movesWithInnerPunctuation.status, 0, movesWithInnerPunctuation.stdout + movesWithInnerPunctuation.stderr)

  for (const [name, settings] of [
    ['too-few-moves', validSettings({ moves: ['只有一个套路'] })],
    ['too-few-moves-v09', v09Settings({ moves: '只有一个招式' })],
  ]) {
    const few = run(writeCase(name, settings, validOutline()))
    assert.strictEqual(few.status, 1)
    assert.deepStrictEqual(failureIds(few), ['phase2.genre-moves-declared'])
  }

  for (const villain of ['反派：没有', '反派设计：不适用']) {
    const noReason = run(writeCase(`villain-no-reason-${villain.length}`, validSettings({ villain }), validOutline()))
    assert.strictEqual(noReason.status, 1)
    assert(failureIds(noReason).includes('phase2.villain-contract'))
  }

  // 反转只核节号在大纲之内；早于一半也是描述，不拦。
  const outOfRange = run(writeCase('reversal-out-of-range', validSettings({ reversal: '反转在：第 9 节（共 8 节）' }), validOutline()))
  assert.strictEqual(outOfRange.status, 1)
  assert.deepStrictEqual(failureIds(outOfRange), ['phase2.reversal-position'])

  const earlyReversalIsDescriptive = run(writeCase(
    'early-reversal-is-descriptive',
    validSettings({ reversal: '反转在：第 3 节（共 8 节）' }),
    validOutline()
  ))
  assert.strictEqual(earlyReversalIsDescriptive.status, 0, earlyReversalIsDescriptive.stdout)

  for (const reversal of ['反转在：不适用（采用报应兑现，不硬塞认知翻转）', '反转位置：不适用（采用报应兑现）']) {
    const noReversal = run(writeCase(
      `no-reversal-${reversal.length}`,
      validSettings({ reversalType: '无反转', reversal }),
      validOutline()
    ))
    assert.strictEqual(noReversal.status, 0, noReversal.stdout)
  }

  const brokenOutline = validOutline().replace(
    /\| 结尾 \| 主角发现线索8[^\n]+\| 1000 \|/,
    (line) => line.replace(/\| 1000 \|$/, '|')
  )
  const badColumns = run(writeCase('bad-columns', validSettings(), brokenOutline))
  assert.strictEqual(badColumns.status, 1)
  assert(failureIds(badColumns).includes('phase2.outline-data-rows'))

  const badTargetSum = run(writeCase(
    'bad-target-sum',
    validSettings(),
    validOutline().replace('| 1000 |', '| 500 |')
  ))
  assert.strictEqual(badTargetSum.status, 1)
  assert.deepStrictEqual(failureIds(badTargetSum), ['phase2.target-word-sum'])

  // Targeted repair loop: only paywall fails; changing that exact hook makes the
  // same artifacts pass without touching any already-valid field.
  const repairDir = writeCase('targeted-repair', validSettings(), validOutline({ includePaywall: false }))
  const beforeRepair = run(repairDir)
  assert.strictEqual(beforeRepair.status, 1)
  assert.deepStrictEqual(failureIds(beforeRepair), ['phase2.paywall-in-both'])
  assert.strictEqual(beforeRepair.report.repair_scope.length, 1)
  assert.match(beforeRepair.report.repair_scope[0].repair, /只在缺失的文件/)
  const repairedOutline = fs.readFileSync(path.join(repairDir, '小节大纲.md'), 'utf8')
    .replace('门后传来自己的声音 |', '门后传来自己的声音（付费点） |')
  fs.writeFileSync(path.join(repairDir, '小节大纲.md'), repairedOutline, 'utf8')
  const afterRepair = run(repairDir)
  assert.strictEqual(afterRepair.status, 0, afterRepair.stdout + afterRepair.stderr)
  assert.strictEqual(afterRepair.report.ok, true)

  const mismatchedPaywall = run(writeCase(
    'mismatched-paywall',
    validSettings({ paywall: '付费点：第 3 节末' }),
    validOutline()
  ))
  assert.strictEqual(mismatchedPaywall.status, 1)
  assert.deepStrictEqual(failureIds(mismatchedPaywall), ['phase2.paywall-in-both'])
  assert.match(mismatchedPaywall.report.failures[0].evidence, /声明第 3 节末；大纲标在第 4 节/)

  const invalidInvocation = spawnSync(process.execPath, [verifier, '--unknown'], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  assert.strictEqual(invalidInvocation.status, 2)
  assert.match(invalidInvocation.stderr, /用法/)

  process.stdout.write('phase2-contract: all tests passed\n')
} finally {
  fs.rmSync(tmpRoot, { recursive: true, force: true })
}
