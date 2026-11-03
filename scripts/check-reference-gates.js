#!/usr/bin/env node
/**
 * check-reference-gates.js — static guard for the two Reference Gates.
 *
 * The gates are prompt text executed by a model, so there is no runtime entry
 * point to call and no return value to assert. This guard therefore pins the
 * source policy only: the gate stays on the first screen and keeps naming every
 * reference it routes. Gate adherence itself is measured by real writing runs,
 * not here; do not read a pass as evidence that a model obeyed the gate.
 */

'use strict'

const assert = require('assert')
const fs = require('fs')
const path = require('path')

const repoRoot = path.resolve(__dirname, '..')

function readSkill(name) {
  return fs.readFileSync(path.join(repoRoot, `skills/${name}/SKILL.md`), 'utf8')
}

const long = readSkill('story-long-write')
const longLines = long.split(/\r?\n/)
const longGateLine = longLines.findIndex((line) => line.includes('## 写前必读')) + 1
assert(longGateLine > 0 && longGateLine <= 20, `long 写前必读 gate must stay in first screen, got line ${longGateLine}`)
for (const reference of [
  'workflow-setup.md', 'workflow-volume.md', 'workflow-outline.md', 'outline-template.md', 'workflow-chapter.md', 'workflow-daily.md', 'workflow-revision.md', 'long-format.md',
  'writing-craft.md', 'long-chapter-quality.md', 'style-combat-face.md', 'long-suspense.md',
  'long-reversal.md',
]) {
  assert(long.includes(reference), `long gate must route ${reference}`)
}
// 写前原样记录本轮明确约束（字数、必发生、禁止发生、停笔点）的行为锚点。
assert.match(long, /记下本轮约束/)
// 首屏总表是唯一的文件级路由；按节读只允许任务包切好的节或总表、文件内「什么时候读这份」点名的节。
assert.match(long, /按节读只允许两种/)
// 细纲模板单独成文件，出细纲与写前补建细纲都按它；文件内的模板围栏带标签，脚本按标签取。
const outlineTemplate = fs.readFileSync(path.join(repoRoot, 'skills/story-long-write/references/outline-template.md'), 'utf8')
assert.match(outlineTemplate, /^```markdown template=细纲$/m, 'outline-template.md must keep the tagged 细纲 fence')
for (const workflow of ['workflow-outline.md', 'workflow-chapter.md']) {
  const text = fs.readFileSync(path.join(repoRoot, `skills/story-long-write/references/${workflow}`), 'utf8')
  assert(text.includes('outline-template.md'), `${workflow} must route the outline template to outline-template.md`)
}

const short = readSkill('story-short-write')
const shortLines = short.split(/\r?\n/)
const shortGateLine = shortLines.findIndex((line) => line.includes('## 写前必读')) + 1
assert(shortGateLine > 0 && shortGateLine <= 20, `short 写前必读 gate must stay in first screen, got line ${shortGateLine}`)

// Check the Phase 2 route and completion gate in the stage reference.
const shortGate = shortLines.slice(shortGateLine - 1, shortGateLine + 11).join('\n')
assert.match(shortGate, /^\| 构思[^\n]*`workflow-design\.md`/m, 'Phase 2 gate must route workflow-design on the first screen')
const shortDesign = fs.readFileSync(path.join(repoRoot, 'skills/story-short-write/references/workflow-design.md'), 'utf8')
assert.match(shortDesign, /check-phase2-contract\.js --json/)

// Phase 3 must be self-sufficient: #418 left workflow-draft pointing at "the Phase 4
// command", which only lived in workflow-revision; a real run wrote prose first and
// never ran the precheck. Pin the route, the literal command and its position.
function phaseSection(heading) {
  const start = short.indexOf(heading)
  assert(start >= 0, `short SKILL.md must keep ${heading}`)
  const next = short.indexOf('\n### Phase ', start + heading.length)
  return short.slice(start, next < 0 ? undefined : next)
}
assert.match(shortGate, /^\| 写正文[^\n]*`workflow-draft\.md`/m)
assert.match(shortGate, /^\| 精修[^\n]*`workflow-revision\.md`/m)
assert(phaseSection('### Phase 3：').includes('(references/workflow-draft.md)'), 'Phase 3 must route workflow-draft.md')
assert(phaseSection('### Phase 4：').includes('(references/workflow-revision.md)'), 'Phase 4 must route workflow-revision.md')

const shortDraft = fs.readFileSync(path.join(repoRoot, 'skills/story-short-write/references/workflow-draft.md'), 'utf8')
const precheck = shortDraft.match(/`node \{skill 根\}\/scripts\/check-delivery-contract\.js ([^`]*)`/)
assert(precheck, 'workflow-draft must spell out the check-delivery-contract precheck command')
for (const flag of ['--check-contract', '--min-chars {MIN}', '--max-chars {MAX}', '--sections {N}', '--min-section-chars']) {
  assert(precheck[1].includes(flag), `workflow-draft precheck must pass ${flag}`)
}
const draftingStep = shortDraft.indexOf('**写前准备**')
assert(draftingStep > 0 && precheck.index < draftingStep, 'workflow-draft precheck must come before the drafting step')
assert.doesNotMatch(shortDraft, /Phase 4 的交付命令/, 'workflow-draft must not defer the precheck command to Phase 4')
// #445 实跑会话在批间自己写了约 40 轮 Python 计数：批间要有「去掉 --check-contract 重跑同一命令」这条命令锚。
assert.match(shortDraft, /去掉 `--check-contract` 重跑/, 'workflow-draft must tell the writer to re-run the same command between batches')

const shortRevision = fs.readFileSync(path.join(repoRoot, 'skills/story-short-write/references/workflow-revision.md'), 'utf8')
const finalCheck = shortRevision.match(/`node scripts\/check-delivery-contract\.js ([^`]*)`/)
assert(finalCheck && !finalCheck[1].includes('--check-contract'), 'workflow-revision must keep the final delivery check')

// v0.8.2 短篇按作者时刻加载：写正文只靠落盘的设计文件接上构思，不再路由构思时读的方法论
// （以前写正文要回查反派/钩子/公式/导语/对标召回，换了对话就得整份重读）。
assert.match(short, /\*\*交接只靠落盘\*\*/, 'short SKILL.md must state the design-to-draft handoff')
for (const reference of [
  'workflow-design.md', 'short-reversal.md', 'submission-craft.md', 'villain-and-reveal.md',
  'genre-writing-formulas.md', 'hooks-chapter.md', 'benchmark-recall.md', 'cross-book-recall.md',
]) {
  assert(!shortDraft.includes(reference), `workflow-draft must take ${reference} decisions from 设定.md, not re-read it`)
}
// 写正文时刻还会加载格式协议和题材包；它们也不能把写手指回构思时刻的平台、设计与揭露资料。
const shortRefs = path.join(repoRoot, 'skills/story-short-write/references')
for (const file of ['short-format.md', ...fs.readdirSync(path.join(shortRefs, 'genre-styles')).map((name) => `genre-styles/${name}`)]) {
  const text = fs.readFileSync(path.join(shortRefs, file), 'utf8')
  for (const reference of ['submission-craft.md', 'workflow-design.md', 'villain-and-reveal.md']) {
    assert(!text.includes(reference), `${file} is loaded while drafting and must not point to ${reference}; use 设定.md instead`)
  }
}
for (const field of ['平台基调', '作者已定']) {
  assert(shortDesign.includes(field), `workflow-design must land ${field} in 设定.md for the draft moment`)
}
// 「像」只有一个口径：入口完成门槛的逐处复核功能，不设全文硬上限。
assert.doesNotMatch(shortRevision, /全文不超 10 处/, 'workflow-revision must not reintroduce a hard 像 cap')

process.stdout.write('reference-gates: source policy holds\n')
