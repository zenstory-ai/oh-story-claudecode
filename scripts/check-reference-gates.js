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
const longGateLine = longLines.findIndex((line) => line.includes('章节 Reference Gate')) + 1
assert(longGateLine > 0 && longGateLine <= 20, `long Reference Gate must stay in first screen, got line ${longGateLine}`)
assert.match(long, /只读本 SKILL\.md 不算完成/)
assert.match(long, /`rg` 检索或局部摘读也不算完整读取/)
for (const reference of [
  'workflow-setup.md', 'workflow-chapter.md', 'workflow-daily.md', 'workflow-revision.md', 'long-format.md',
  'writing-craft.md', 'long-chapter-quality.md', 'long-chapter-hooks.md', 'long-suspense.md',
  'long-reversal.md',
]) {
  assert(long.includes(reference), `long gate must route ${reference}`)
}
assert.match(long, /不得先写正文再补读/)
assert.match(long, /Constraint Lock/)
assert.match(long, /references 只提供技法，不得覆盖这些项目事实/)

const short = readSkill('story-short-write')
const shortLines = short.split(/\r?\n/)
const shortGateLine = shortLines.findIndex((line) => line.includes('阶段 Reference Gate')) + 1
assert(shortGateLine > 0 && shortGateLine <= 20, `short Reference Gate must stay in first screen, got line ${shortGateLine}`)
assert.match(short, /只读本 SKILL\.md 不算完成门禁/)
assert.match(short, /任一必需路径不存在、不可读/)
assert.match(short, /分块直到 EOF；`rg` 检索或局部摘读不算读完/)

// Check the Phase 2 route and completion gate in the stage reference.
const shortGate = shortLines.slice(shortGateLine - 1, shortGateLine + 11).join('\n')
assert(shortGate.includes('`references/workflow-design.md`'), 'Phase 2 gate must route workflow-design on the first screen')
const shortDesign = fs.readFileSync(path.join(repoRoot, 'skills/story-short-write/references/workflow-design.md'), 'utf8')
assert.match(shortDesign, /check-phase2-contract\.js --json/)
assert.match(shortDesign, /最多做 2 轮定向 repair/)

// Phase 3 must be self-sufficient: #418 left workflow-draft pointing at "the Phase 4
// command", which only lived in workflow-revision; a real run wrote prose first and
// never ran the precheck. Pin the route, the literal command and its position.
function phaseSection(heading) {
  const start = short.indexOf(heading)
  assert(start >= 0, `short SKILL.md must keep ${heading}`)
  const next = short.indexOf('\n### Phase ', start + heading.length)
  return short.slice(start, next < 0 ? undefined : next)
}
assert.match(shortGate, /Phase 3 写正文前完整读取 `references\/workflow-draft\.md`/)
assert.match(shortGate, /Phase 4 精修前完整读取 `references\/workflow-revision\.md`/)
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
assert.match(shortDraft, /不自写 Python 计数/)

const shortRevision = fs.readFileSync(path.join(repoRoot, 'skills/story-short-write/references/workflow-revision.md'), 'utf8')
const finalCheck = shortRevision.match(/`node scripts\/check-delivery-contract\.js ([^`]*)`/)
assert(finalCheck && !finalCheck[1].includes('--check-contract'), 'workflow-revision must keep the final delivery check')

process.stdout.write('reference-gates: source policy holds\n')
