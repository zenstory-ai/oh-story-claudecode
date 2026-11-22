#!/usr/bin/env node
'use strict'

const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const repoRoot = path.resolve(__dirname, '..')
const verifier = path.join(repoRoot, 'skills/story-long-write/scripts/check-outline-contract.js')
const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'outline-contract-'))

// 现行模板（0.10 白话字段名）；旧字段名的细纲另有一组用例（legacy-*）。
const FIELDS = [
  ['核心事件', '江晨拿到伴奏后决定去老兵家里听故事'],
  ['字数目标', '2300 字'],
  ['阶段位置', '收尾期 · 第2阶段第11章'],
  ['属于哪段剧情', '第三段剧情：老兵的铁盒，第一步：接下托付'],
  ['目标情绪', '踏实的期待 → 被托付的沉重'],
  ['主角目标/关键选择', '要真实素材；在报批与先去听故事之间选一个'],
  ['松紧', '推进'],
  ['本章结构公式', '接到邀约 + 上门 + 老兵开口 + 立下承诺'],
  ['章首钩子', '悬念前置 — 老人把铁盒推过来'],
  ['爽点', '无显性爽点，功能是把宏大叙事落到具体的人身上'],
  ['本章标价', '铁盒＝老兵一辈子唯一没交出去的东西；尺子在点1立好（他连勋章都捐了）'],
  ['闭环状态', '获得+使用，见效与估值扣住，第22章开奖'],
  ['这章不能说破', '铁盒里装的是什么先不露'],
  ['可以放开写的地方', '老兵讲故事的细节、屋内陈设、对话内容由写手自定'],
  ['有没有硬伤', '没问题'],
]
// 0.9.2 及以前的字段名、小节名：照样过检查。
const LEGACY_RENAMES = [
  ['- 属于哪段剧情：第三段剧情：老兵的铁盒，第一步：接下托付', '- 字数口径：visible_chars_v1\n- 单元ID/位置：L1-03；单元内第 1 拍'],
  ['- 这章不能说破：', '- 本章禁止提前释放：'],
  ['- 可以放开写的地方：', '- 写手自由区：'],
  ['- 有没有硬伤：没问题', '- 契约风险：契约安全'],
  ['#### 这章怎么走', '#### 内容概括（五段式）'],
]

function outline(overrides = {}) {
  const fields = FIELDS
    .filter(([name]) => overrides.dropField !== name)
    .map(([name, value]) => `- ${name}：${overrides.fieldValues?.[name] ?? value}`)
  // 现行模板默认三列（# / 情节点 / 作用）
  const table = overrides.plotTable ?? [
    '| # | 情节点（谁做了什么） | 作用 |',
    '|---|---|---|',
    '| 1 | 江晨接到邀约 | 铺垫 |',
    '| 2 | 老人推过铁盒，说这东西他留了几十年 | 高潮 |',
  ].join('\n')
  const acts = ['起因', '发展', '转折', '高潮', '结尾']
    .filter((act) => overrides.dropAct !== act)
    .map((act) => `- ${act}：本章${act}内容`)
  return [
    '## 细纲（第 21 章）',
    '',
    '### 第 21 章：新的伴奏',
    ...fields,
    '',
    '#### 这章怎么走',
    ...acts,
    '',
    '#### 情节安排（多线）',
    '- 主线推进：新作品素材来源确定',
    '- 辅线推进：无',
    '- 逻辑线：拿到伴奏 → 缺素材 → 接受邀约 → 背上承诺',
    '',
    '#### 人物关系和出场顺序',
    '- 出场顺序：江晨、赵大柱',
    '- 人物关系变化：陌生受访者 → 托付关系',
    '',
    '#### 情节细化',
    '- 情节点序列（逐行填下表）：',
    '',
    table,
    '',
  ].join('\n')
}

function writeCase(name, body) {
  const dir = path.join(tmpRoot, name, '大纲')
  fs.mkdirSync(dir, { recursive: true })
  if (body !== null) fs.writeFileSync(path.join(dir, '细纲_第021章.md'), body, 'utf8')
  return path.join(tmpRoot, name)
}

function run(project, chapter = '21') {
  const result = spawnSync(process.execPath, [verifier, '--json', '--project', project, '--chapter', chapter], {
    cwd: repoRoot,
    encoding: 'utf8',
  })
  let report = null
  if (result.stdout.trim()) report = JSON.parse(result.stdout)
  return { ...result, report }
}

const failureIds = (result) => result.report.failures.map((failure) => failure.id)

try {
  // 模板齐全的细纲必须通过 —— 这是误报防线，先测它。
  const good = run(writeCase('valid', outline()))
  assert.strictEqual(good.status, 0, good.stdout + good.stderr)
  assert.strictEqual(good.report.ok, true)
  assert.deepStrictEqual(good.report.failures, [])

  // 加粗字段名与半角冒号也要认，否则会误伤正常写法。
  const boldHalfWidth = outline().replace('- 目标情绪：', '- **目标情绪**: ')
  const bold = run(writeCase('bold-halfwidth', boldHalfWidth))
  assert.strictEqual(bold.status, 0, bold.stdout + bold.stderr)

  // 目标情绪 / 主角目标·关键选择 实测直接影响正文，不接受占位符……
  const hollowIntent = run(writeCase('hollow-intent', outline({
    fieldValues: { 目标情绪: '[待补充]' },
  })))
  assert.strictEqual(hollowIntent.status, 1)
  assert(failureIds(hollowIntent).includes('outline.intent-fields-substantive'))
  assert.match(hollowIntent.report.failures.find((f) => f.id === 'outline.intent-fields-substantive').evidence, /目标情绪/)

  const hollowGoal = run(writeCase('hollow-goal', outline({
    fieldValues: { '主角目标/关键选择': '[待补充]' },
  })))
  assert.strictEqual(hollowGoal.status, 1)
  assert(failureIds(hollowGoal).includes('outline.intent-fields-substantive'))

  // ……但其余字段仍按契约允许 [待补充]，不能因此判失败。
  const hollowOther = run(writeCase('hollow-other', outline({
    fieldValues: { 有没有硬伤: '[待补充]', 松紧: '[待补充]', 属于哪段剧情: '[待补充]' },
  })))
  assert.strictEqual(hollowOther.status, 0, hollowOther.stdout + hollowOther.stderr)
  assert.strictEqual(hollowOther.report.ok, true)

  const dropped = run(writeCase('missing-field', outline({ dropField: '目标情绪' })))
  assert.strictEqual(dropped.status, 1)
  assert.deepStrictEqual(failureIds(dropped), ['outline.required-fields'])
  assert.match(dropped.report.failures[0].evidence, /目标情绪/)
  assert.strictEqual(dropped.report.repair_scope.length, 1)
  assert.match(dropped.report.repair_scope[0].repair, /\[待补充\]/)

  const noAct = run(writeCase('missing-act', outline({ dropAct: '转折' })))
  assert.strictEqual(noAct.status, 1)
  assert.deepStrictEqual(failureIds(noAct), ['outline.five-act'])

  // 情节点写成编号列表（当前最常见的偏离）必须被判出来。
  const listStyle = run(writeCase('plot-as-list', outline({
    plotTable: '1. 江晨接到邀约【铺垫】\n2. 老人推过铁盒【高潮】',
  })))
  assert.strictEqual(listStyle.status, 1)
  assert.deepStrictEqual(failureIds(listStyle), ['outline.plotpoint-table'])

  // 三列表是现行默认；旧表头「功能标签」的三列表同样收。
  const threeCol = run(writeCase('plot-three-col', outline({
    plotTable: '| # | 情节点 | 功能标签 |\n|---|---|---|\n| 1 | 江晨接到邀约 | 铺垫 |',
  })))
  assert.strictEqual(threeCol.status, 0, threeCol.stdout + threeCol.stderr)
  // 两列、或第三列不是「作用」的表仍是偏离。
  const twoCol = run(writeCase('plot-two-col', outline({
    plotTable: '| # | 情节点 |\n|---|---|\n| 1 | 江晨接到邀约 |',
  })))
  assert.deepStrictEqual(failureIds(twoCol), ['outline.plotpoint-table'])
  const wrongThird = run(writeCase('plot-wrong-third', outline({
    plotTable: '| # | 情节点 | 字数 |\n|---|---|---|\n| 1 | 江晨接到邀约 | 300 |',
  })))
  assert.deepStrictEqual(failureIds(wrongThird), ['outline.plotpoint-table'])
  // 加了「分寸」「分辨率」列的四列、五列表都收；「分寸」不在最后一列判偏离。
  for (const header of ['| # | 情节点 | 作用 | 分寸 |', '| # | 情节点 | 作用 | 分辨率 |', '| # | 情节点 | 作用 | 分辨率 | 分寸 |']) {
    const cols = header.split('|').length - 2
    const body = `${header}\n|${'---|'.repeat(cols)}\n| 1 | 江晨接到邀约 | 铺垫 |${' 疏 |'.repeat(cols - 3)}`
    const result = run(writeCase(`plot-cols-${Buffer.from(header).toString('hex').slice(0, 24)}-${cols}`, outline({ plotTable: body })))
    assert.strictEqual(result.status, 0, header + result.stdout)
  }
  const boundFirst = run(writeCase('plot-bound-first', outline({
    plotTable: '| # | 情节点 | 作用 | 分寸 | 分辨率 |\n|---|---|---|---|---|\n| 1 | 江晨接到邀约 | 铺垫 | 只给邀约 | 疏 |',
  })))
  assert.deepStrictEqual(failureIds(boundFirst), ['outline.plotpoint-table'])

  // 旧字段名（字数口径、单元ID/位置、本章禁止提前释放、契约风险）与旧表头照样过——老书细纲不必改。
  const legacyBody = LEGACY_RENAMES.reduce((text, [from, to]) => text.replace(from, to), outline({ plotTable: [
    '| # | 情节点（谁做了什么） | 功能标签 | 分辨率 | 执行边界 |',
    '|---|---|---|---|---|',
    '| 1 | 江晨接到邀约 | 铺垫 | 疏 | 禁：不提铁盒。放：无 |',
    '| 2 | 老人推过铁盒 | 高潮 | 密 | 禁：不评价当下。放：允许老人当场说出这东西他留了几十年 |',
  ].join('\n') }))
  assert.match(legacyBody, /本章禁止提前释放/)
  assert.match(legacyBody, /内容概括（五段式）/)
  const legacy = run(writeCase('legacy-field-names', legacyBody))
  assert.strictEqual(legacy.status, 0, legacy.stdout + legacy.stderr)
  // 「这章不能说破」可选：没写不拦。
  const noRelease = run(writeCase('missing-release', outline({ dropField: '这章不能说破' })))
  assert.strictEqual(noRelease.status, 0, noRelease.stdout + noRelease.stderr)
  assert.deepStrictEqual(noRelease.report.advisories, [])
  // 小节新旧名都没有才算缺：报新名。
  const noRoute = run(writeCase('missing-route', outline().replace('#### 这章怎么走\n', '')))
  assert.deepStrictEqual(failureIds(noRoute), ['outline.subsections'])
  assert.match(noRoute.report.failures[0].evidence, /这章怎么走/)
  // 字数口径可不写；写了就只能是 visible_chars_v1。
  assert.doesNotMatch(outline(), /字数口径/)
  const badCaliber = run(writeCase('bad-caliber', outline() + '\n- 字数口径：chars\n'))
  assert.deepStrictEqual(failureIds(badCaliber), ['outline.wordcount-target'])

  // 加「分辨率」列之前的四列旧表仍然收——既有项目的细纲不因模板加列而失效。
  const legacyFourCol = run(writeCase('plot-legacy-four-col', outline({
    plotTable: [
      '| # | 情节点（谁做了什么） | 功能标签 | 执行边界 |',
      '|---|---|---|---|',
      '| 1 | 江晨接到邀约 | 铺垫 | 只给邀约，不提铁盒 |',
    ].join('\n'),
  })))
  assert.strictEqual(legacyFourCol.status, 0, legacyFourCol.stdout + legacyFourCol.stderr)
  assert.strictEqual(legacyFourCol.report.ok, true)

  // 阅读体验字段可选：只写核心字段的细纲也过（#383 隔离实验只证明了目标情绪与主角目标的收益）。
  const OPTIONAL = ['阶段位置', '松紧', '本章结构公式', '本章标价', '闭环状态', '可以放开写的地方', '有没有硬伤', '这章不能说破']
  const coreOnly = outline({ plotTable: [
    '| # | 情节点（谁做了什么） | 功能标签 | 执行边界（禁＋放） |',
    '|---|---|---|---|',
    '| 1 | 江晨接到邀约 | 铺垫 | 禁：不提铁盒。放：无 |',
    '| 2 | 老人推过铁盒 | 高潮 | 禁：不评价当下。放：允许老人当场说出这东西他留了几十年 |',
  ].join('\n') }).split('\n').filter((line) => !OPTIONAL.some((name) => line.startsWith(`- ${name}：`))).join('\n')
  const core = run(writeCase('core-fields-only', coreOnly))
  assert.strictEqual(core.status, 0, core.stdout + core.stderr)

  // 新表头「分寸」和旧表头「执行边界（禁＋放）」的四列表只验结构，不查禁放字眼。
  const newFourCol = run(writeCase('plot-new-four-col', outline({ plotTable: [
    '| # | 情节点（谁做了什么） | 作用 | 分寸 |',
    '|---|---|---|---|',
    '| 1 | 江晨接到邀约 | 铺垫 | 只给邀约 |',
  ].join('\n') })))
  assert.strictEqual(newFourCol.status, 0, newFourCol.stdout + newFourCol.stderr)

  // 五列但中间那列不是分辨率，判偏离——防止随便加一列就算数。
  const wrongFifth = run(writeCase('plot-wrong-fifth', outline({
    plotTable: [
      '| # | 情节点（谁做了什么） | 功能标签 | 字数 | 执行边界 |',
      '|---|---|---|---|---|',
      '| 1 | 江晨接到邀约 | 铺垫 | 300 | 只给邀约 |',
    ].join('\n'),
  })))
  assert.strictEqual(wrongFifth.status, 1)
  assert.deepStrictEqual(failureIds(wrongFifth), ['outline.plotpoint-table'])

  const badTarget = run(writeCase('bad-target', outline({ fieldValues: { 字数目标: '很多字' } })))
  assert.strictEqual(badTarget.status, 1)
  assert(failureIds(badTarget).includes('outline.wordcount-target'))

  // 字数目标与 storyctl 同一语法：常见作者写法都收，取值进 JSON；写成区间不再被静默读成下限。
  assert.deepStrictEqual(good.report.wordcount, { target: 2300, target_status: 'ok', range: null, range_status: 'missing' })
  const approxTarget = run(writeCase('target-approx', outline({ fieldValues: { 字数目标: '约 2,300 字（本章偏短）' } })))
  assert.strictEqual(approxTarget.status, 0, approxTarget.stdout)
  assert.strictEqual(approxTarget.report.wordcount.target, 2300)
  const rangeAsTarget = run(writeCase('target-as-range', outline({ fieldValues: { 字数目标: '2000-2600' } })))
  assert.strictEqual(rangeAsTarget.status, 1)
  assert.deepStrictEqual(failureIds(rangeAsTarget), ['outline.wordcount-target'])
  const authorRange = run(writeCase('author-range', outline() + '\n- 字数范围：2000-2600 字\n'))
  assert.strictEqual(authorRange.status, 0, authorRange.stdout)
  assert.deepStrictEqual(authorRange.report.wordcount.range, { min: 2000, max: 2600 })
  const badRange = run(writeCase('author-range-reversed', outline() + '\n- 字数范围：2600-2000\n'))
  assert.strictEqual(badRange.status, 1)
  assert.deepStrictEqual(failureIds(badRange), ['outline.wordcount-target'])

  // 导入历史章节常有 <500 字短楔子或 >20000 字合章：未写正文的新章继续阻断，同章正文已落盘时自动放行 1-500000。
  for (const [label, wc] of [['short-wedge', '320 字'], ['merged-chapter', '45000 字']]) {
    const project = writeCase(`hist-${label}`, outline({ fieldValues: { 字数目标: wc } }))
    const strictRes = run(project)
    assert.strictEqual(strictRes.status, 1, label)
    assert.deepStrictEqual(failureIds(strictRes), ['outline.wordcount-target'])
    fs.mkdirSync(path.join(project, '正文'), { recursive: true })
    fs.writeFileSync(path.join(project, '正文', '第021章_旧稿.md'), '# 第21章 旧稿\n\n已有历史正文。\n', 'utf8')
    const histRes = run(project)
    assert.strictEqual(histRes.status, 0, histRes.stdout + histRes.stderr)
  }

  // 细纲引用了不存在的设定文件必须被判出来——「数字照 X.md」而 X 查无实据的排纲事故。
  const ghostRefBody = outline() + '\n#### 结尾设定和钩子\n- 结尾设定：数字口径照 `设定/世界观/经济与用度.md`，收束于关门\n'
  const ghostRef = run(writeCase('ghost-ref', ghostRefBody))
  assert.strictEqual(ghostRef.status, 1)
  assert(failureIds(ghostRef).includes('outline.setting-refs-exist'))

  // 同一引用在文件真实存在时必须通过（含裸文件名引用）。
  const realRefProject = writeCase('real-ref', outline() + '\n#### 结尾设定和钩子\n- 结尾设定：数字口径照 `设定/世界观/经济与用度.md`、行市见 `经济与用度.md`\n')
  fs.mkdirSync(path.join(realRefProject, '设定', '世界观'), { recursive: true })
  fs.writeFileSync(path.join(realRefProject, '设定', '世界观', '经济与用度.md'), '# 经济与用度\n', 'utf8')
  const realRef = run(realRefProject)
  assert.strictEqual(realRef.status, 0, realRef.stdout + realRef.stderr)

  const skillRef = run(writeCase('skill-ref', outline() + '\n见 `writing-craft.md` 与 `references/anti-ai-writing.md`'))
  assert.strictEqual(skillRef.status, 0, skillRef.stdout)
  for (const ref of ['../设定/工钱.md', '设定\\工钱.md', './工钱.md']) {
    const project = writeCase(`relative-${Buffer.from(ref).toString('hex')}`, outline() + `\n见 \`${ref}\``)
    assert(failureIds(run(project)).includes('outline.setting-refs-exist'))
    const target = path.resolve(project, '大纲', ref.replace(/\\/g, '/').startsWith('设定/') ? '../' + ref.replace(/\\/g, '/') : ref)
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.mkdirSync(target)
    assert(failureIds(run(project)).includes('outline.setting-refs-exist'))
    fs.rmdirSync(target)
    fs.writeFileSync(target, '# 工钱\n一日十文')
    assert.strictEqual(run(project).status, 0)
  }

  const missingFile = run(writeCase('missing-file', null))
  assert.strictEqual(missingFile.status, 2)
  assert.match(missingFile.stderr, /没有第 21 章细纲/)

  const invalid = spawnSync(process.execPath, [verifier, '--unknown'], { cwd: repoRoot, encoding: 'utf8' })
  assert.strictEqual(invalid.status, 2)
  assert.match(invalid.stderr, /用法/)

  process.stdout.write('outline-contract: all tests passed\n')
} finally {
  fs.rmSync(tmpRoot, { recursive: true, force: true })
}
