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

const FIELDS = [
  ['核心事件', '江晨拿到伴奏后决定去老兵家里听故事'],
  ['字数目标', '2300 字'],
  ['字数口径', 'visible_chars_v1'],
  ['阶段位置', '收尾期 · 第2阶段第11章'],
  ['单元ID/位置', 'U03；单元内第 1 拍'],
  ['目标情绪', '踏实的期待 → 被托付的沉重'],
  ['主角目标/关键选择', '要真实素材；在报批与先去听故事之间选一个'],
  ['章节定位', '推进'],
  ['本章结构公式', '接到邀约 + 上门 + 老兵开口 + 立下承诺'],
  ['章首钩子', '悬念前置 — 老人把铁盒推过来'],
  ['爽点', '无显性爽点，功能是把宏大叙事落到具体的人身上'],
  ['本章标价', '铁盒＝老兵一辈子唯一没交出去的东西；尺子在点1立好（他连勋章都捐了）'],
  ['闭环状态', '获得+使用，见效与估值扣住，第22章开奖'],
  ['本章禁止提前释放', '铁盒内容与终局表彰的关系'],
  ['写手自由区', '老兵讲故事的细节、屋内陈设、对话内容由写手自定'],
  ['契约风险', '契约安全'],
]

function outline(overrides = {}) {
  const fields = FIELDS
    .filter(([name]) => overrides.dropField !== name)
    .map(([name, value]) => `- ${name}：${overrides.fieldValues?.[name] ?? value}`)
  const table = overrides.plotTable ?? [
    '| # | 情节点（谁做了什么） | 功能标签 | 分辨率 | 执行边界 |',
    '|---|---|---|---|---|',
    '| 1 | 江晨接到邀约 | 铺垫 | 疏 | 禁：不提铁盒。放：无 |',
    '| 2 | 老人推过铁盒 | 高潮 | 密 | 禁：不评价当下。放：允许老人当场说出这东西他留了几十年 |',
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
    '#### 内容概括（五段式）',
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

  // 值未定时写 [待补充] 是契约允许的写法，不能因此判失败。
  const pending = run(writeCase('pending-value', outline({
    fieldValues: { 契约风险: '[待补充]', 单元ID位置: '[待补充]' },
  })))
  assert.strictEqual(pending.status, 0, pending.stdout + pending.stderr)
  assert.strictEqual(pending.report.ok, true)

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
    fieldValues: { 契约风险: '[待补充]', 章节定位: '[待补充]' },
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

  // 三列表格缺执行边界，也是偏离。
  const threeCol = run(writeCase('plot-three-col', outline({
    plotTable: '| # | 情节点 | 功能标签 |\n|---|---|---|\n| 1 | 江晨接到邀约 | 铺垫 |',
  })))
  assert.strictEqual(threeCol.status, 1)
  assert.deepStrictEqual(failureIds(threeCol), ['outline.plotpoint-table'])

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

  const noCaliber = run(writeCase('no-caliber', outline({ fieldValues: { 字数口径: 'chars' } })))
  assert.strictEqual(noCaliber.status, 1)
  assert.deepStrictEqual(failureIds(noCaliber), ['outline.wordcount-target'])

  // 五列表全是禁令（一个「放」都没有）必须被判出来——015 章的实测事故形态。
  const allForbid = run(writeCase('plot-all-forbid', outline({
    plotTable: [
      '| # | 情节点（谁做了什么） | 功能标签 | 分辨率 | 执行边界 |',
      '|---|---|---|---|---|',
      '| 1 | 江晨接到邀约 | 铺垫 | 疏 | 禁：不提铁盒 |',
      '| 2 | 老人推过铁盒 | 高潮 | 密 | 禁：不评价当下 |',
    ].join('\n'),
  })))
  assert.strictEqual(allForbid.status, 1)
  assert(failureIds(allForbid).includes('outline.plotpoint-release'))

  // 有「放」但不足三分之一：blocking 通过，advisory 提示。
  const lowRelease = run(writeCase('plot-low-release', outline({
    plotTable: [
      '| # | 情节点（谁做了什么） | 功能标签 | 分辨率 | 执行边界 |',
      '|---|---|---|---|---|',
      '| 1 | 江晨接到邀约 | 铺垫 | 疏 | 禁：不提铁盒。放：允许邻居搭话 |',
      '| 2 | 老人推过铁盒 | 高潮 | 密 | 禁：不评价当下 |',
      '| 3 | 江晨接过铁盒 | 高潮 | 中 | 禁：不开盒 |',
      '| 4 | 告辞出门 | 余波 | 疏 | 禁：不回头 |',
    ].join('\n'),
  })))
  assert.strictEqual(lowRelease.status, 0, lowRelease.stdout + lowRelease.stderr)
  assert(lowRelease.report.advisories.map((a) => a.id).includes('outline.plotpoint-release-ratio'))

  // 禁止提前释放条目超过五条：疑似复读卷级常任，advisory 不阻断。
  const boilerplate = run(writeCase('release-boilerplate', outline({
    fieldValues: { 本章禁止提前释放: '铁盒内容、终局表彰、幕后资助人、母亲身世、纪念馆改建、旧部队番号' },
  })))
  assert.strictEqual(boilerplate.status, 0, boilerplate.stdout + boilerplate.stderr)
  assert(boilerplate.report.advisories.map((a) => a.id).includes('outline.release-brevity'))

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

  // --supply：单元卡含「供给自查」小节通过，缺则失败。
  const volumeDir = path.join(tmpRoot, 'supply-case', '大纲')
  fs.mkdirSync(volumeDir, { recursive: true })
  const volumeFile = path.join(volumeDir, '卷纲_第一卷.md')
  fs.writeFileSync(volumeFile, [
    '# 第一卷 卷纲',
    '### 剧情单元 D1-02',
    '- 单元ID：D1-02',
    '- 章节范围：第 11-20 章',
    '#### 供给自查',
    '- 对手供给：贾雄手下（B 级，落 设定/角色/贾雄.md）',
    '### 剧情单元 D1-03',
    '- 单元ID：D1-03',
    '- 章节范围：第 21-34 章',
    '## 核心矛盾',
  ].join('\n'), 'utf8')
  const supplyOk = spawnSync(process.execPath, [verifier, '--json', '--supply', volumeFile, 'D1-02'], { cwd: repoRoot, encoding: 'utf8' })
  assert.strictEqual(supplyOk.status, 0, supplyOk.stdout + supplyOk.stderr)
  const supplyMissing = spawnSync(process.execPath, [verifier, '--json', '--supply', volumeFile, 'D1-03'], { cwd: repoRoot, encoding: 'utf8' })
  assert.strictEqual(supplyMissing.status, 1)
  assert.match(JSON.parse(supplyMissing.stdout).evidence, /供给自查/)

  for (const empty of ['无', '无。', '[待补充]', '；禁：不说破', '']) {
    const body = outline().replace('允许老人当场说出这东西他留了几十年', empty)
    const result = run(writeCase(`empty-release-${Buffer.from(empty).toString('hex')}`, body))
    assert(failureIds(result).includes('outline.plotpoint-release'), result.stdout)
  }
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
  const supplyCases = [
    ['### 剧情单元 L1-010\n#### 供给自查', false],
    ['### 剧情单元 L1-01\n尚未执行供给自查', false],
    ['### 剧情单元 L1-01\n### 剧情单元 L1-02\n#### 供给自查', false],
    ['### 剧情单元 L1-01\n```md\n#### 供给自查\n```', false],
    ['### 剧情单元 L1-01\n#### 供给自查', true],
    ['### 剧情单元 L1-01：码头\n#### 供给自查（本批）\n无缺口', true],
    ['### 码头\n- **单元ID**：L1-01\n#### 信息\n##### 供给自查\n无', true],
  ]
  for (const [body, ok] of supplyCases) {
    fs.writeFileSync(volumeFile, body)
    const result = spawnSync(process.execPath, [verifier, '--supply', volumeFile, 'L1-01'], { encoding: 'utf8' })
    assert.strictEqual(result.status, ok ? 0 : 1, result.stdout + body)
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
