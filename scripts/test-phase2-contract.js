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

// 现行列名。新建项目必须用这一组，check-phase2-contract.js 的 currentHeader 分支。
const headers = [
  '结构段/五段功能', '主事件', '情节推进', '情绪', '人物/关系变化', '因果/逻辑链',
  '读者新获知什么', '结尾承接/钩子', '伏笔/物件', '场景形态', '对白作用', '目标字数',
]

// v0.7.8 及更早的项目落盘的旧列名；改名后仍须被接受（legacyHeader 分支）。
const legacyHeaders = headers.map(
  (name, index) => ({ 2: '子事件×3-5', 9: '动静', 10: '对话密度' }[index] || name)
)

const threeUnitProgression = (index) =>
  `主角发现线索${index}{发现}->对手阻拦行动${index}{冲突}->主角留下证据${index}{伏笔}`

function outlineRow(stage, index, hook, { legacy = false, progression = threeUnitProgression } = {}) {
  return [
    stage,
    `主角处理事件${index}`,
    progression(index),
    `疑惑→紧张${index}`,
    `关系压力上升${index}`,
    `发现异常${index} → 调查 → 受阻 → 决定继续`,
    `读者获知线索${index}`,
    hook,
    `旧钥匙${index}`,
    legacy ? (index % 2 ? '动' : '静') : (index % 2 ? '行动' : '证据核验'),
    legacy ? (index % 2 ? '高' : '中') : (index % 2 ? '推动策略' : '无对白，由物件推进'),
    '1000',
  ]
}

function validSettings(overrides = {}) {
  const values = {
    platform: '知乎盐选',
    genre: 'references/genre-styles/悬疑.md',
    moves: '日常违和切入；延迟剥洋葱；证物翻转',
    villain: '反派设计：不适用（冲突来自主角对自我记忆的误判）',
    reversalType: '信息反转',
    reversal: '反转位置：第 6 节 ÷ 共 8 节 = 75%',
    paywall: '付费点：第 4 节末',
    target: '8000',
    ...overrides,
  }
  return [
    '# 设定',
    '## 基本信息',
    `- 目标平台：${values.platform}`,
    `- 目标字数：${values.target} 字`,
    '## Phase 2 设计校验',
    `- 题材参考：\`${values.genre}\``,
    `- 核心招式：${values.moves}`,
    `- ${values.villain}`,
    `- 反转类型：${values.reversalType}`,
    `- ${values.reversal}`,
    `- ${values.paywall}`,
    '',
  ].join('\n')
}

function validOutline({ includePaywall = true, headerRow = headers, ...rowOpts } = {}) {
  const rows = [
    outlineRow('开头', 1, '她决定去查监控', rowOpts),
    outlineRow('铺垫', 2, '她收到没有寄件人的照片', rowOpts),
    outlineRow('铺垫', 3, '照片背后写着她的旧名', rowOpts),
    outlineRow('升级', 4, includePaywall ? '门后传来自己的声音（付费点）' : '门后传来自己的声音', rowOpts),
    outlineRow('升级', 5, '旧照片上的人动了', rowOpts),
    outlineRow('反转', 6, '她发现记忆属于另一个人', rowOpts),
    outlineRow('反转', 7, '真正的主人敲响房门', rowOpts),
    outlineRow('结尾', 8, '她把钥匙留在门外', rowOpts),
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

  // 旧项目落盘的三个旧列名必须继续通过（legacyHeader 兼容分支）。
  const legacyHeaderOutline = run(writeCase(
    'legacy-headers',
    validSettings(),
    validOutline({ headerRow: legacyHeaders, legacy: true })
  ))
  assert.strictEqual(legacyHeaderOutline.status, 0, legacyHeaderOutline.stdout + legacyHeaderOutline.stderr)
  assert.strictEqual(legacyHeaderOutline.report.ok, true)
  assert.match(
    legacyHeaderOutline.report.checks.find((check) => check.id === 'phase2.outline-12-columns').evidence,
    /兼容旧项目/
  )

  // 新旧列名混搭不是有效表头，currentHeader 和 legacyHeader 都不该接受。
  const mixedHeaderOutline = run(writeCase(
    'mixed-headers',
    validSettings(),
    validOutline({ headerRow: headers.map((name, index) => (index === 2 ? '子事件×3-5' : name)) })
  ))
  assert.strictEqual(mixedHeaderOutline.status, 1)
  assert(failureIds(mixedHeaderOutline).includes('phase2.outline-12-columns'))

  // 去掉「3-5 个子事件」配额后，每节只有一个真实推进也应通过。
  const singleUnit = run(writeCase(
    'single-progression-unit',
    validSettings(),
    validOutline({ progression: (index) => `主角当场亮出证据${index}{发现}` })
  ))
  assert.strictEqual(singleUnit.status, 0, singleUnit.stdout + singleUnit.stderr)
  assert.strictEqual(singleUnit.report.ok, true)

  // 「不设数量下限」不等于允许留空或漏功能标签。
  const emptyProgression = run(writeCase(
    'empty-progression',
    validSettings(),
    validOutline({ progression: () => '' })
  ))
  assert.strictEqual(emptyProgression.status, 1)
  assert(failureIds(emptyProgression).includes('phase2.outline-subevents'))

  const untaggedProgression = run(writeCase(
    'untagged-progression',
    validSettings(),
    validOutline({ progression: (index) => `主角当场亮出证据${index}` })
  ))
  assert.strictEqual(untaggedProgression.status, 1)
  assert(failureIds(untaggedProgression).includes('phase2.outline-subevents'))

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

  // 未填写的模板占位符不算完成设计。
  const placeholders = run(writeCase(
    'unfilled-placeholders',
    validSettings({
      moves: '{招式一}；{招式二}；{招式三}',
      reversalType: '{身份/视角/动机/时间线/信息/认知/无反转}',
    }),
    validOutline()
  ))
  assert.strictEqual(placeholders.status, 1)
  assert(failureIds(placeholders).includes('phase2.no-template-placeholders'))

  const missingSettings = run(writeCase('missing-settings', null, validOutline()))
  assert.strictEqual(missingSettings.status, 1)
  assert(failureIds(missingSettings).includes('phase2.settings-readable'))

  const badGenre = run(writeCase(
    'bad-genre-reference',
    validSettings({ genre: 'references/genre-styles/不存在.md' }),
    validOutline()
  ))
  assert.strictEqual(badGenre.status, 1)
  assert.deepStrictEqual(failureIds(badGenre), ['phase2.genre-reference-declared'])
  assert.match(badGenre.report.failures[0].evidence, /不存在\.md/)

  // 招式说明里的顿号/逗号属于招式内部描述，只有分号才是招式分隔符。
  const movesWithInnerPunctuation = run(writeCase(
    'moves-with-inner-punctuation',
    validSettings({ moves: '白月光触发链（旧物、旧地、旧称呼三连触发）；信物翻转，从定情物变成证据；火葬场预告' }),
    validOutline()
  ))
  assert.strictEqual(movesWithInnerPunctuation.status, 0, movesWithInnerPunctuation.stdout + movesWithInnerPunctuation.stderr)
  assert.strictEqual(movesWithInnerPunctuation.report.ok, true)

  const tooFewMoves = run(writeCase(
    'too-few-moves',
    validSettings({ moves: '只有一个招式' }),
    validOutline()
  ))
  assert.strictEqual(tooFewMoves.status, 1)
  assert.deepStrictEqual(failureIds(tooFewMoves), ['phase2.genre-moves-declared'])

  const noReason = run(writeCase(
    'villain-no-reason',
    validSettings({ villain: '反派设计：不适用' }),
    validOutline()
  ))
  assert.strictEqual(noReason.status, 1)
  assert(failureIds(noReason).includes('phase2.villain-contract'))

  const badReversal = run(writeCase(
    'bad-reversal-math',
    validSettings({ reversal: '反转位置：第 6 节 ÷ 共 8 节 = 60%' }),
    validOutline()
  ))
  assert.strictEqual(badReversal.status, 1)
  assert.deepStrictEqual(failureIds(badReversal), ['phase2.reversal-position'])

  const earlyReversalIsDescriptive = run(writeCase(
    'early-reversal-is-descriptive',
    validSettings({ reversal: '反转位置：第 3 节 ÷ 共 8 节 = 37.5%' }),
    validOutline()
  ))
  assert.strictEqual(earlyReversalIsDescriptive.status, 0, earlyReversalIsDescriptive.stdout)
  assert.strictEqual(earlyReversalIsDescriptive.report.ok, true)

  const noReversal = run(writeCase(
    'no-reversal',
    validSettings({
      reversalType: '无反转',
      reversal: '反转位置：不适用（采用报应兑现，不硬塞认知翻转）',
    }),
    validOutline()
  ))
  assert.strictEqual(noReversal.status, 0, noReversal.stdout)
  assert.strictEqual(noReversal.report.ok, true)

  const brokenOutline = validOutline().replace(
    /\| 结尾 \| 主角处理事件8[^\n]+\| 1000 \|/,
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
